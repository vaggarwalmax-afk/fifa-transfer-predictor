import pytest

import app as webapp
from predictor.dataset import save_dataset
from predictor.model import save_model, train
from tests.conftest import synthetic_players


@pytest.fixture
def client(paths):
    webapp._cache.clear()
    return webapp.app.test_client()


@pytest.fixture
def trained(paths):
    players = synthetic_players()
    players[0]["market_value_eur_m"] = None  # one player without a value on file
    save_dataset({"players": players, "season_labels": ["2024/25", "2025/26"], "seasons": [2024, 2025],
                  "sources": {"fpl": False, "fpl_matched": 0}, "unmatched_market_values": []})
    save_model(train(players))
    return players


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Transfer Value Predictor" in resp.data


def test_state_before_training(client):
    body = client.get("/api/state").get_json()
    assert body["ready"] is False


def test_state_after_training(client, trained):
    body = client.get("/api/state").get_json()
    assert body["ready"] is True
    assert len(body["players"]) == len(trained)
    first = next(p for p in body["players"] if p["id"] == 0)
    assert first["market_value_eur_m"] is None and first["diff_pct"] is None
    other = next(p for p in body["players"] if p["id"] == 1)
    assert other["predicted_value_eur_m"] > 0
    assert other["diff_pct"] == pytest.approx(
        (other["predicted_value_eur_m"] - other["market_value_eur_m"]) / other["market_value_eur_m"])


def test_player_detail(client, trained):
    body = client.get("/api/players/3").get_json()
    assert body["name"] == "Player 3"
    assert {c["feature"] for c in body["prediction"]["contributions"]} == {
        "goals", "assists", "minutes", "matches", "age", "position", "form"}
    assert client.get("/api/players/9999").status_code == 404


def test_predict_custom_player(client, trained):
    payload = {"goals": 15, "assists": 7, "minutes": 2800, "matches": 34, "age": 23,
               "position": "Forward", "form": "fit"}
    fit = client.post("/api/predict", json=payload).get_json()["predicted_value_eur_m"]
    hurt = client.post("/api/predict", json={**payload, "form": "injured"}).get_json()["predicted_value_eur_m"]
    assert fit > hurt > 0


@pytest.mark.parametrize("bad", [
    {"goals": "lots"},
    {"goals": -1},
    {"age": 80},
    {"position": "Striker"},
    {"form": "tired"},
])
def test_predict_rejects_bad_input(client, trained, bad):
    payload = {"goals": 15, "assists": 7, "minutes": 2800, "matches": 34, "age": 23,
               "position": "Forward", "form": "fit", **bad}
    resp = client.post("/api/predict", json=payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_predict_rejects_non_object_body(client, trained):
    assert client.post("/api/predict", json=[1, 2, 3]).status_code == 400


def test_predict_before_training(client):
    assert client.post("/api/predict", json={}).status_code == 503
