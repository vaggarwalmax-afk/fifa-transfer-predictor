from datetime import date

import pytest

from predictor.dataset import (build_dataset, form_from_availability, load_market_values,
                               normalize_position)
from tests.conftest import scorer, write_json


def test_position_mapping():
    assert normalize_position("Right Winger") == "Forward"
    assert normalize_position("Defensive Midfield") == "Midfielder"
    assert normalize_position("Centre-Back") == "Defender"
    assert normalize_position(None, "Offence") == "Forward"
    assert normalize_position("Goalkeeper") == "Goalkeeper"
    assert normalize_position(None, None) is None


def test_availability_fallback():
    assert form_from_availability(30) == "fit"
    assert form_from_availability(12) == "weak"
    assert form_from_availability(3) == "injured"
    assert form_from_availability(5, matchdays=7) == "fit"


def test_build_dataset(small_raw):
    ds = build_dataset(today=date(2026, 10, 1))
    players = {p["name"]: p for p in ds["players"]}
    assert ds["season_labels"] == ["2024/25", "2025/26"]

    saka = players["Bukayo Saka"]
    assert saka["features"]["goals"] == 14  # (12 + 16) / 2
    assert saka["features"]["minutes"] == 2750  # FPL history: (2500 + 3000) / 2
    assert not saka["minutes_estimated"]
    assert saka["features"]["position"] == "Forward"
    assert saka["features"]["form"] == "fit"
    assert saka["features"]["age"] == 25.1
    assert saka["fpl"]["code"] == 223340
    assert saka["market_value_eur_m"] == 140
    assert saka["team"]["team_tla"] == "ARS"

    # Accent-insensitive value match + FPL injury flag.
    ode = players["Martin Ødegaard"]
    assert ode["market_value_eur_m"] == 75
    assert ode["features"]["form"] == "injured"
    assert ode["form_source"] == "fpl"
    assert "Knee" in ode["fpl"]["news"]

    # No FPL match: minutes estimated from known minutes per appearance, CSV overrides form.
    joe = players["Joelinton"]
    assert joe["fpl"] is None
    assert joe["minutes_estimated"]
    per_match = (2500 + 3000 + 2720) / (30 + 36 + 34)
    assert joe["features"]["minutes"] == round(8 * per_match)
    assert joe["features"]["form"] == "weak"
    assert joe["form_source"] == "override"
    assert joe["photo_url"] == "https://example.com/joe.png"

    # CSV uses the full name, football-data the nickname: matched via firstName + lastName.
    assert players["Rodri"]["market_value_eur_m"] == 60
    assert players["Rodri"]["features"]["position"] == "Midfielder"

    assert ds["unmatched_market_values"] == ["Nobody Atall"]
    assert ds["sources"]["fpl_matched"] == 2


def test_build_without_fetch_is_a_clear_error(paths):
    with pytest.raises(FileNotFoundError, match="python -m predictor fetch"):
        build_dataset()


def test_season_in_progress_is_weighted_by_matchdays(paths):
    raw = paths.RAW_DIR
    write_json(raw / "manifest.json", {"fetched_at": "2026-10-01T12:00:00", "current_season": 2026,
                                       "seasons": [2025, 2026], "fpl": False})
    haaland = ("Erling Haaland", "Erling", "Haaland", "2000-07-21", "Offence", "MCI")
    write_json(raw / "scorers_2025.json", {"season": {"currentMatchday": 38},
                                           "scorers": [scorer(9, *haaland, 36, 27, 4)]})
    write_json(raw / "scorers_2026.json", {"season": {"currentMatchday": 7},
                                           "scorers": [scorer(9, *haaland, 7, 9, 1)]})
    paths.MARKET_VALUES_PATH.write_text("name,club,market_value_eur_m\n", encoding="utf-8")

    p = build_dataset(today=date(2026, 10, 1))["players"][0]
    assert p["features"]["goals"] == round(38 * 36 / 45, 2)  # 36 goals in 45 matchdays, per 38
    assert p["features"]["matches"] == round(38 * 43 / 45, 2)
    assert p["features"]["form"] == "fit"  # played 7 of the 7 matchdays so far


def test_mid_season_move_keeps_both_clubs(paths):
    raw = paths.RAW_DIR
    write_json(raw / "manifest.json", {"fetched_at": "2026-10-01T12:00:00", "current_season": 2026,
                                       "seasons": [2025], "fpl": False})
    ramsey = ("Jacob Ramsey", "Jacob", "Ramsey", "2001-05-28", "Midfield")
    # The scorers table is sorted by goals, so the newer club comes first.
    write_json(raw / "scorers_2025.json", {"scorers": [scorer(5, *ramsey, "NEW", 15, 6, 1),
                                                       scorer(5, *ramsey, "ARS", 18, 1, 0)]})
    # Surname only: matches only with the club bonus, so the Newcastle spell must count.
    paths.MARKET_VALUES_PATH.write_text("name,club,market_value_eur_m\nRamsey,Newcastle United,30\n",
                                        encoding="utf-8")

    p = build_dataset(today=date(2026, 10, 1))["players"][0]
    assert p["features"]["matches"] == 33
    assert {s["team_tla"] for s in p["seasons"][0]["spells"]} == {"NEW", "ARS"}
    assert p["team"]["team_tla"] == "ARS"  # most appearances, absent FPL
    assert p["market_value_eur_m"] == 30

    # With FPL, the current club wins.
    write_json(raw / "manifest.json", {"fetched_at": "2026-10-01T12:00:00", "current_season": 2026,
                                       "seasons": [2025], "fpl": True})
    write_json(raw / "fpl_bootstrap.json", {
        "teams": [{"id": 15, "name": "Newcastle", "short_name": "NEW"}],
        "elements": [{"id": 7, "code": 77, "first_name": "Jacob", "second_name": "Ramsey",
                      "web_name": "Ramsey", "team": 15, "element_type": 3, "minutes": 0, "status": "a"}],
    })
    assert build_dataset(today=date(2026, 10, 1))["players"][0]["team"]["team_tla"] == "NEW"


def test_market_values_csv_with_bom_and_bad_numbers(tmp_path):
    path = tmp_path / "values.csv"
    path.write_text("﻿name,club,market_value_eur_m\nA Player,X,10\nB Player,X,nan\n"
                    "C Player,X,inf\nD Player,X,-1\nE Player,X,\n", encoding="utf-8")
    assert [r["name"] for r in load_market_values(path)] == ["A Player"]


def test_cached_history_of_another_player_is_ignored(small_raw):
    # e.g. a summary cached under this code by an older version that keyed files by element id
    write_json(small_raw.RAW_DIR / "fpl" / "element_223340.json", {"history_past": [
        {"season_name": "2024/25", "element_code": 118748, "minutes": 3371}]})
    saka = next(p for p in build_dataset(today=date(2026, 10, 1))["players"] if p["name"] == "Bukayo Saka")
    assert saka["seasons"][0]["minutes_estimated"]
    assert saka["seasons"][0]["minutes"] != 3371
