"""Linear regression on log(market value).

Fitting log(value) instead of value keeps predictions positive and makes each
feature a percentage effect ("+1 goal per season = +4% value"), which matches how
transfer prices scale far better than a flat euro amount per goal would. Age also
enters squared (centred on 26) so the model can learn that value peaks mid-career.

The trained model is stored as plain JSON (intercept + coefficients), so the web
app can score players without scikit-learn.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold

from . import config

AGE_CENTRE = 26.0
BASE_POSITION = "Midfielder"
BASE_FORM = "fit"
MIN_TRAINING_PLAYERS = 12
# Without FPL data, minutes are estimated as appearances x average minutes, which makes
# them a copy of `matches`; fitting both gives huge offsetting coefficients, so drop minutes.
MAX_ESTIMATED_MINUTES_SHARE = 0.5
VALUE_FLOOR, VALUE_CAP = 0.1, 400.0  # €m; keeps wild what-if inputs on the chart

COLUMNS = (
    list(config.NUMERIC_FEATURES)
    + ["age_sq"]
    + [f"position_{p}" for p in config.POSITIONS if p != BASE_POSITION]
    + [f"form_{f}" for f in config.FORMS if f != BASE_FORM]
)
GROUPS = {
    "goals": ["goals"],
    "assists": ["assists"],
    "minutes": ["minutes"],
    "matches": ["matches"],
    "age": ["age", "age_sq"],
    "position": [c for c in COLUMNS if c.startswith("position_")],
    "form": [c for c in COLUMNS if c.startswith("form_")],
}


def design_row(features: dict) -> np.ndarray:
    row = {c: float(features[c]) for c in config.NUMERIC_FEATURES}
    row["age_sq"] = (row["age"] - AGE_CENTRE) ** 2
    for p in config.POSITIONS:
        row[f"position_{p}"] = 1.0 if features["position"] == p else 0.0
    for f in config.FORMS:
        row[f"form_{f}"] = 1.0 if features["form"] == f else 0.0
    return np.array([row[c] for c in COLUMNS])


def design_matrix(features: list[dict]) -> np.ndarray:
    return np.vstack([design_row(f) for f in features])


def training_rows(players: list[dict]) -> list[dict]:
    return [p for p in players if p.get("market_value_eur_m") and p["features"].get("age") is not None]


def train(players: list[dict], folds: int = 5, seed: int = 42) -> dict:
    rows = training_rows(players)
    if len(rows) < MIN_TRAINING_PLAYERS:
        raise ValueError(
            f"Only {len(rows)} players have both stats and a market value; need at least "
            f"{MIN_TRAINING_PLAYERS}. Add rows to data/market_values.csv or fetch more seasons."
        )
    feats = [p["features"] for p in rows]
    X = design_matrix(feats)
    y = np.log([p["market_value_eur_m"] for p in rows])
    actual = np.exp(y)

    dropped = {}
    estimated_share = sum(bool(p.get("minutes_estimated")) for p in rows) / len(rows)
    if estimated_share > MAX_ESTIMATED_MINUTES_SHARE:
        dropped["minutes"] = (f"estimated from appearances for {estimated_share:.0%} of players "
                              f"(no FPL data), so it adds nothing beyond appearances")
    active = [i for i, c in enumerate(COLUMNS) if c not in dropped]
    Xa = X[:, active]

    reg = LinearRegression().fit(Xa, y)

    # Out-of-fold predictions: each player is scored by a model that never saw them.
    oof = np.empty_like(y)
    for train_idx, test_idx in KFold(n_splits=min(folds, len(rows)), shuffle=True,
                                     random_state=seed).split(Xa):
        fold = LinearRegression().fit(Xa[train_idx], y[train_idx])
        oof[test_idx] = fold.predict(Xa[test_idx])
    oof_value = np.exp(oof)

    coef = dict.fromkeys(COLUMNS, 0.0)
    coef.update(zip((COLUMNS[i] for i in active), reg.coef_.tolist()))
    coef_vec = np.array([coef[c] for c in COLUMNS])
    means = dict(zip(COLUMNS, X.mean(axis=0).tolist()))
    peak_age = None
    if coef["age_sq"] < 0:
        peak_age = round(AGE_CENTRE - coef["age"] / (2 * coef["age_sq"]), 1)

    all_feats = [p["features"] for p in players if p["features"].get("age") is not None]
    return {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "target": "log(market value in EUR millions)",
        "columns": COLUMNS,
        "intercept": float(reg.intercept_),
        "coefficients": coef,
        "feature_means": means,
        "baseline_value_eur_m": float(np.exp(reg.intercept_ + X.mean(axis=0) @ coef_vec)),
        "peak_age": peak_age,
        "dropped_features": dropped,
        "metrics": {
            "n_train": len(rows),
            "n_players": len(players),
            "folds": min(folds, len(rows)),
            "r2_log_in_sample": _r2(y, reg.predict(Xa)),
            "r2_log_cv": _r2(y, oof),
            "mae_eur_m_cv": float(np.mean(np.abs(oof_value - actual))),
            "median_abs_pct_error_cv": float(np.median(np.abs(oof_value - actual) / actual)),
        },
        "per_unit_effects": per_unit_effects(coef, dropped),
        "feature_ranges": {
            c: [float(min(f[c] for f in all_feats)), float(max(f[c] for f in all_feats))]
            for c in config.NUMERIC_FEATURES
        },
        "category_counts": {
            "position": {p: sum(f["position"] == p for f in feats) for p in config.POSITIONS},
            "form": {k: sum(f["form"] == k for f in feats) for k in config.FORMS},
        },
        "baselines": {"position": BASE_POSITION, "form": BASE_FORM, "age_centre": AGE_CENTRE},
    }


def per_unit_effects(coef: dict, dropped: dict | None = None) -> list[dict]:
    """Coefficients translated to '% change in value' for a sensible unit of each feature."""
    def pct(x: float) -> float:
        return math.exp(x) - 1

    effects = [
        {"feature": "goals", "unit": "+1 goal per season", "pct": pct(coef["goals"])},
        {"feature": "assists", "unit": "+1 assist per season", "pct": pct(coef["assists"])},
        {"feature": "minutes", "unit": "+90 minutes per season", "pct": pct(90 * coef["minutes"])},
        {"feature": "matches", "unit": "+1 appearance per season", "pct": pct(coef["matches"])},
        {"feature": "age", "unit": "23 -> 24 years old",
         "pct": pct(coef["age"] + coef["age_sq"] * ((24 - AGE_CENTRE) ** 2 - (23 - AGE_CENTRE) ** 2))},
        {"feature": "age", "unit": "30 -> 31 years old",
         "pct": pct(coef["age"] + coef["age_sq"] * ((31 - AGE_CENTRE) ** 2 - (30 - AGE_CENTRE) ** 2))},
    ]
    for p in config.POSITIONS:
        if p != BASE_POSITION:
            effects.append({"feature": "position", "unit": f"{p} vs {BASE_POSITION}",
                            "pct": pct(coef[f"position_{p}"])})
    for f in config.FORMS:
        if f != BASE_FORM:
            effects.append({"feature": "form", "unit": f"{f.title()} vs {BASE_FORM.title()}",
                            "pct": pct(coef[f"form_{f}"])})
    for effect in effects:
        effect["dropped"] = effect["feature"] in (dropped or {})
    return effects


def predict(model: dict, features: dict) -> dict:
    x = design_row(features)
    coef = np.array([model["coefficients"][c] for c in model["columns"]])
    means = np.array([model["feature_means"][c] for c in model["columns"]])
    log_value = model["intercept"] + float(x @ coef)
    value = float(np.clip(math.exp(log_value), VALUE_FLOOR, VALUE_CAP))

    # Split log(value) - log(average player) into one additive piece per feature group.
    index = {c: i for i, c in enumerate(model["columns"])}
    contributions = []
    for group, cols in GROUPS.items():
        delta = sum(coef[index[c]] * (x[index[c]] - means[index[c]]) for c in cols)
        contributions.append({"feature": group, "log": float(delta), "pct": math.exp(delta) - 1})

    warnings = [f"{name.title()} is not used by this model: {why}."
                for name, why in model.get("dropped_features", {}).items()]
    for c in config.NUMERIC_FEATURES:
        lo, hi = model["feature_ranges"][c]
        if not lo <= float(features[c]) <= hi:
            warnings.append(f"{c.title()} is outside the range seen in training "
                            f"({lo:g}-{hi:g}), so this is an extrapolation.")
    for cat in ("position", "form"):
        if model["category_counts"][cat].get(features[cat], 0) == 0:
            warnings.append(f"No {features[cat].lower()} players in the training data, "
                            f"so {cat} has no learned effect here.")
    if value in (VALUE_FLOOR, VALUE_CAP):
        warnings.append("Prediction hit the model's display limit.")

    return {
        "predicted_value_eur_m": value,
        "baseline_value_eur_m": model["baseline_value_eur_m"],
        "contributions": contributions,
        "warnings": warnings,
    }


def save_model(model: dict, path: Path | None = None) -> None:
    path = path or config.MODEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=1), encoding="utf-8")


def load_model(path: Path | None = None) -> dict | None:
    path = path or config.MODEL_PATH
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _r2(y: np.ndarray, pred: np.ndarray) -> float:
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1 - ss_res / ss_tot if ss_tot else 0.0
