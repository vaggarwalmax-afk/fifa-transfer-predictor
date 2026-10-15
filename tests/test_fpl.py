from predictor.fpl import form_from_status, fpl_season, summary_filename


def test_form_from_status():
    assert form_from_status("a") == "fit"
    assert form_from_status("d", 75) == "weak"
    assert form_from_status("d", 25) == "injured"
    assert form_from_status("i", 0) == "injured"
    # Sold / loaned out / can't face the parent club: 0% chance but not injured.
    assert form_from_status("u", 0) == "weak"
    assert form_from_status("n", 0) == "weak"
    assert form_from_status(None) is None


def test_summary_cache_is_keyed_by_stable_code_and_fpl_season():
    assert summary_filename({"id": 381, "code": 223340}, 2026) == "element_223340_2026.json"
    assert summary_filename({"id": 381}, 2026) == "element_id381_2026.json"
    assert summary_filename({"id": 381, "code": 223340}, None) == "element_223340.json"


def test_fpl_season_from_first_gameweek_deadline():
    assert fpl_season({"events": [{"id": 1, "deadline_time": "2026-08-14T17:30:00Z"}]}) == 2026
    assert fpl_season({"events": []}) is None
    assert fpl_season({}) is None
