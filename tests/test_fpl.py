from predictor.fpl import form_from_status, summary_filename


def test_form_from_status():
    assert form_from_status("a") == "fit"
    assert form_from_status("d", 75) == "weak"
    assert form_from_status("d", 25) == "injured"
    assert form_from_status("i", 0) == "injured"
    # Sold / loaned out / can't face the parent club: 0% chance but not injured.
    assert form_from_status("u", 0) == "weak"
    assert form_from_status("n", 0) == "weak"
    assert form_from_status(None) is None


def test_summary_cache_is_keyed_by_stable_code():
    assert summary_filename({"id": 381, "code": 223340}) == "element_223340.json"
    assert summary_filename({"id": 381}) == "element_id381.json"
