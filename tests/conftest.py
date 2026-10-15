"""Fixtures shaped like football-data.org v4 and FPL API responses."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from predictor import config

TEAMS = {
    "ARS": {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "tla": "ARS",
            "crest": "https://crests.football-data.org/57.png"},
    "MCI": {"id": 65, "name": "Manchester City FC", "shortName": "Man City", "tla": "MCI",
            "crest": "https://crests.football-data.org/65.png"},
    "NEW": {"id": 67, "name": "Newcastle United FC", "shortName": "Newcastle", "tla": "NEW",
            "crest": "https://crests.football-data.org/67.png"},
}


def scorer(pid, name, first, last, dob, section, team, matches, goals, assists, position=None):
    return {
        "player": {"id": pid, "name": name, "firstName": first, "lastName": last,
                   "dateOfBirth": dob, "nationality": "England", "section": section,
                   "position": position, "shirtNumber": 7},
        "team": TEAMS[team],
        "playedMatches": matches,
        "goals": goals,
        "assists": assists,
        "penalties": None,
    }


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point every data/model path at a temp directory."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "RAW_DIR", data_dir / "raw")
    monkeypatch.setattr(config, "PLAYERS_PATH", data_dir / "players.json")
    monkeypatch.setattr(config, "MARKET_VALUES_PATH", data_dir / "market_values.csv")
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "models" / "model.json")
    return config


@pytest.fixture
def small_raw(paths):
    """Two seasons, three players, FPL data for two of them, values for all three."""
    raw = paths.RAW_DIR
    write_json(raw / "manifest.json", {"fetched_at": "2026-10-01T12:00:00", "current_season": 2026,
                                       "seasons": [2024, 2025], "fpl": True})
    write_json(raw / "scorers_2024.json", {"scorers": [
        scorer(1, "Bukayo Saka", "Bukayo", "Saka", "2001-09-05", "Offence", "ARS", 30, 12, 10,
               position="Right Winger"),
        scorer(2, "Martin Ødegaard", "Martin", "Ødegaard", "1998-12-17", "Midfield", "ARS", 34, 8, 9),
    ]})
    write_json(raw / "scorers_2025.json", {"scorers": [
        scorer(1, "Bukayo Saka", "Bukayo", "Saka", "2001-09-05", "Offence", "ARS", 36, 16, 12,
               position="Right Winger"),
        scorer(3, "Joelinton", "Joelinton", "Cássio Apolinário de Lira", "1996-08-14", "Midfield",
               "NEW", 8, 2, 1),
        scorer(4, "Rodri", "Rodrigo", "Hernández", "1996-06-22", "Midfield", "MCI", 20, 3, 2,
               position="Defensive Midfield"),
    ]})
    write_json(raw / "fpl_bootstrap.json", {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"},
                  {"id": 15, "name": "Newcastle", "short_name": "NEW"}],
        "elements": [
            {"id": 101, "code": 223340, "first_name": "Bukayo", "second_name": "Saka",
             "web_name": "Saka", "team": 1, "element_type": 3, "minutes": 400, "status": "a",
             "chance_of_playing_next_round": None, "news": ""},
            {"id": 102, "code": 184029, "first_name": "Martin", "second_name": "Ødegaard",
             "web_name": "Ødegaard", "team": 1, "element_type": 3, "minutes": 90, "status": "i",
             "chance_of_playing_next_round": 0, "news": "Knee injury - Expected back 01 Nov"},
        ],
    })
    write_json(raw / "fpl" / "element_223340_2026.json", {"history_past": [
        {"season_name": "2024/25", "minutes": 2500, "goals_scored": 12, "assists": 10},
        {"season_name": "2025/26", "minutes": 3000, "goals_scored": 16, "assists": 12},
    ]})
    write_json(raw / "fpl" / "element_184029_2026.json", {"history_past": [
        {"season_name": "2024/25", "minutes": 2720, "goals_scored": 8, "assists": 9},
    ]})
    paths.MARKET_VALUES_PATH.write_text(
        "name,club,market_value_eur_m,as_of,form,photo_url\n"
        "Bukayo Saka,Arsenal,140,2025/26,,\n"
        "Martin Odegaard,Arsenal,75,2025/26,,\n"
        "Joelinton,Newcastle United,25,2025/26,weak,https://example.com/joe.png\n"
        "Rodrigo Hernandez,Manchester City,60,2025/26,,\n"
        "Nobody Atall,Arsenal,10,2025/26,,\n",
        encoding="utf-8",
    )
    return paths


def synthetic_players(n=80, seed=0, noise=0.05):
    """Players whose log(value) follows a known linear rule, for checking the fit."""
    rng = random.Random(seed)
    players = []
    for i in range(n):
        position = rng.choice(config.POSITIONS)
        form = rng.choices(config.FORMS, weights=[6, 2, 2])[0]
        f = {
            "goals": rng.uniform(0, 25), "assists": rng.uniform(0, 12),
            "minutes": rng.uniform(300, 3300), "matches": rng.uniform(5, 38),
            "age": rng.uniform(18, 35), "position": position, "form": form,
        }
        log_value = (2.0 + 0.05 * f["goals"] + 0.04 * f["assists"] + 0.0003 * f["minutes"]
                     + 0.01 * f["matches"] - 0.004 * (f["age"] - 26) ** 2
                     + {"Goalkeeper": -0.6, "Defender": -0.2, "Midfielder": 0, "Forward": 0.1}[position]
                     + {"fit": 0, "weak": -0.2, "injured": -0.5}[form]
                     + rng.gauss(0, noise))
        players.append({
            "id": i, "name": f"Player {i}", "features": f, "seasons": [],
            "team": {"team": "Test FC", "team_short": "Test", "team_tla": "TST", "crest": None},
            "photo_url": None, "fpl": None, "market_value_eur_m": round(2.718281828 ** log_value, 2),
        })
    return players
