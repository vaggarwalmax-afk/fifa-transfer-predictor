import math

import pytest

from predictor.model import predict, train
from tests.conftest import synthetic_players


def test_recovers_known_effects():
    model = train(synthetic_players(n=150, noise=0.02))
    coef = model["coefficients"]
    assert coef["goals"] == pytest.approx(0.05, abs=0.005)
    assert coef["assists"] == pytest.approx(0.04, abs=0.008)
    assert coef["age_sq"] == pytest.approx(-0.004, abs=0.001)
    assert coef["form_injured"] == pytest.approx(-0.5, abs=0.05)
    assert coef["position_Goalkeeper"] == pytest.approx(-0.6, abs=0.05)
    assert model["peak_age"] == pytest.approx(26, abs=1.5)
    assert model["metrics"]["r2_log_cv"] > 0.95


def test_contributions_explain_the_prediction():
    model = train(synthetic_players())
    features = {"goals": 20, "assists": 8, "minutes": 3000, "matches": 35, "age": 24,
                "position": "Forward", "form": "fit"}
    result = predict(model, features)
    total = sum(c["log"] for c in result["contributions"])
    assert math.exp(total) * result["baseline_value_eur_m"] == pytest.approx(result["predicted_value_eur_m"])
    assert result["warnings"] == []


def test_injury_lowers_value():
    model = train(synthetic_players())
    fit = {"goals": 10, "assists": 5, "minutes": 2500, "matches": 30, "age": 26,
           "position": "Midfielder", "form": "fit"}
    injured = {**fit, "form": "injured"}
    assert predict(model, injured)["predicted_value_eur_m"] < predict(model, fit)["predicted_value_eur_m"]


def test_warns_on_extrapolation_and_unseen_categories():
    players = [p for p in synthetic_players() if p["features"]["position"] != "Goalkeeper"]
    model = train(players)
    result = predict(model, {"goals": 59, "assists": 5, "minutes": 2500, "matches": 30, "age": 26,
                             "position": "Goalkeeper", "form": "fit"})
    assert any("Goals is outside" in w for w in result["warnings"])
    assert any("goalkeeper" in w for w in result["warnings"])


def test_needs_enough_players():
    with pytest.raises(ValueError, match="at least"):
        train(synthetic_players(n=5))


def test_drops_minutes_when_they_are_mostly_estimated():
    players = synthetic_players()
    for p in players:  # what the dataset looks like without FPL: minutes = appearances x 80
        p["features"]["minutes"] = round(p["features"]["matches"] * 80)
        p["minutes_estimated"] = True
    model = train(players)
    assert "minutes" in model["dropped_features"]
    assert model["coefficients"]["minutes"] == 0
    assert abs(model["coefficients"]["matches"]) < 0.1  # no runaway offsetting coefficients
    assert next(e for e in model["per_unit_effects"] if e["feature"] == "minutes")["dropped"]
    result = predict(model, {"goals": 10, "assists": 5, "minutes": 2500, "matches": 30, "age": 26,
                             "position": "Forward", "form": "fit"})
    assert any("Minutes is not used" in w for w in result["warnings"])


def test_no_range_warning_for_a_dropped_feature():
    players = synthetic_players()
    for p in players:
        p["features"]["minutes"] = round(p["features"]["matches"] * 80)
        p["minutes_estimated"] = True
    model = train(players)
    result = predict(model, {"goals": 10, "assists": 5, "minutes": 10, "matches": 30, "age": 26,
                             "position": "Forward", "form": "fit"})
    assert not any("Minutes is outside" in w for w in result["warnings"])


def test_extrapolation_range_comes_from_training_rows_only():
    players = synthetic_players()
    star = {**players[0], "id": 999, "market_value_eur_m": None,
            "features": {**players[0]["features"], "goals": 59}}
    model = train(players + [star])
    assert model["feature_ranges"]["goals"][1] < 59
    result = predict(model, {**star["features"], "goals": 50})
    assert any("Goals is outside" in w for w in result["warnings"])


def test_peak_age_only_reported_inside_the_training_ages():
    players = synthetic_players()
    for p in players:  # value falls with age throughout; the parabola's vertex is at -24
        age = p["features"]["age"]
        p["market_value_eur_m"] = math.exp(3 - 0.05 * age - 0.0005 * (age - 26) ** 2)
    assert train(players)["peak_age"] is None


def test_needs_at_least_two_folds():
    with pytest.raises(ValueError, match="2 folds"):
        train(synthetic_players(), folds=1)
