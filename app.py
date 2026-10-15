"""Web app: python app.py, then open http://127.0.0.1:5000"""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from predictor import config
from predictor.model import predict

app = Flask(__name__)

_cache: dict[Path, tuple[float, dict]] = {}


def _load(path: Path) -> dict | None:
    """Read a JSON file, re-reading only when it changes (so retraining needs no restart)."""
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if not cached or cached[0] != mtime:
        try:
            cached = (mtime, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):  # unreadable, corrupt or empty: keep serving what we had
            return cached[1] if cached else None
        _cache[path] = cached
    return cached[1]


def _summary(player: dict, model: dict) -> dict:
    prediction = predict(model, player["features"])["predicted_value_eur_m"]
    actual = player["market_value_eur_m"]
    return {
        "id": player["id"],
        "name": player["name"],
        "team": player["team"],
        "position": player["features"]["position"],
        "form": player["features"]["form"],
        "age": player["features"]["age"],
        "features": player["features"],
        "photo_url": player["photo_url"],
        "photo_code": (player.get("fpl") or {}).get("code"),
        "market_value_eur_m": actual,
        "predicted_value_eur_m": prediction,
        "diff_pct": (prediction - actual) / actual if actual else None,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    dataset = _load(config.PLAYERS_PATH)
    model = _load(config.MODEL_PATH)
    if not dataset or not model:
        missing = "data" if not dataset else "trained model"
        return jsonify({"ready": False, "message": f"No {missing} yet.",
                        "api_key_set": bool(config.api_key())})
    players = [_summary(p, model) for p in dataset["players"] if p["features"].get("age") is not None]
    return jsonify({
        "ready": True,
        "dataset": {k: dataset.get(k) for k in ("as_of", "seasons", "season_labels", "fetched_at",
                                                 "sources", "unmatched_market_values")},
        "model": {k: model.get(k) for k in ("trained_at", "metrics", "per_unit_effects", "peak_age",
                                             "feature_ranges", "category_counts", "dropped_features",
                                             "baseline_value_eur_m", "baselines")},
        "positions": config.POSITIONS,
        "forms": config.FORMS,
        "photo_templates": config.PHOTO_URL_TEMPLATES,
        "players": players,
    })


@app.get("/api/players/<int:player_id>")
def player_detail(player_id: int):
    dataset, model = _load(config.PLAYERS_PATH), _load(config.MODEL_PATH)
    if not dataset or not model:
        return jsonify({"error": "Model not trained yet."}), 503
    player = next((p for p in dataset["players"] if p["id"] == player_id), None)
    if player is None or player["features"].get("age") is None:
        return jsonify({"error": "Unknown player."}), 404
    return jsonify({**player, **_summary(player, model), "prediction": predict(model, player["features"])})


@app.post("/api/predict")
def predict_custom():
    model = _load(config.MODEL_PATH)
    if not model:
        return jsonify({"error": "Model not trained yet."}), 503
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    try:
        features = parse_features(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(predict(model, features))


LIMITS = {"goals": (0, 60), "assists": (0, 40), "minutes": (0, 3420), "matches": (0, 38), "age": (15, 45)}


def parse_features(body: dict) -> dict:
    features = {}
    for name, (lo, hi) in LIMITS.items():
        raw = body.get(name)
        if isinstance(raw, bool):  # float(True) == 1.0, but true is not a goal count
            raise ValueError(f"'{name}' must be a number")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"'{name}' must be a number") from None
        if not lo <= value <= hi:  # also rejects NaN and infinities
            raise ValueError(f"'{name}' must be between {lo} and {hi}")
        features[name] = value
    if body.get("position") not in config.POSITIONS:
        raise ValueError(f"'position' must be one of {', '.join(config.POSITIONS)}")
    if body.get("form") not in config.FORMS:
        raise ValueError(f"'form' must be one of {', '.join(config.FORMS)}")
    features["position"], features["form"] = body["position"], body["form"]
    return features


if __name__ == "__main__":
    # Debug mode follows FLASK_DEBUG, parsed by Flask itself (so "0"/"false" mean off).
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
