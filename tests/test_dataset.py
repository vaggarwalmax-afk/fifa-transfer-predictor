from datetime import date

import pytest

from predictor.dataset import (build_dataset, form_from_availability, normalize_position)


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
