import json

import requests

from predictor.fetch import fetch_all
from predictor.football_data import FootballDataError
from tests.conftest import scorer


class FakeFootballData:
    def __init__(self, restricted=()):
        self.restricted = set(restricted)

    def competition(self):
        return {"currentSeason": {"startDate": "2026-08-15"}}

    def scorers(self, season, limit):
        if season in self.restricted:
            raise FootballDataError("403: restricted")
        return {"scorers": [scorer(1, "Bukayo Saka", "Bukayo", "Saka", "2001-09-05", "Offence",
                                   "ARS", 30, 12, 10)]}


class FakeFpl:
    def __init__(self, fail=False):
        self.fail = fail
        self.summaries = []

    def bootstrap(self):
        if self.fail:
            raise requests.ConnectionError("blocked")
        return {"teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
                "elements": [{"id": 101, "code": 1, "first_name": "Bukayo", "second_name": "Saka",
                              "web_name": "Saka", "team": 1, "element_type": 3, "minutes": 0,
                              "status": "a"}]}

    def element_summary(self, element_id):
        self.summaries.append(element_id)
        return {"history_past": []}


def test_fetch_defaults_to_last_three_completed_seasons(paths):
    fpl = FakeFpl()
    manifest = fetch_all("key", fd_client=FakeFootballData(restricted={2023}), fpl_client=fpl,
                         log=lambda m: None)
    assert manifest["seasons"] == [2024, 2025]  # 2023 was refused and skipped
    assert manifest["fpl"] is True
    assert fpl.summaries == [101]
    raw = paths.RAW_DIR
    assert json.loads((raw / "manifest.json").read_text())["current_season"] == 2026
    assert (raw / "scorers_2025.json").exists() and not (raw / "scorers_2023.json").exists()
    assert (raw / "fpl" / "element_1.json").exists()  # keyed by FPL's stable `code`


def test_fpl_outage_is_not_fatal(paths):
    logs = []
    manifest = fetch_all("key", seasons=[2025], fd_client=FakeFootballData(),
                         fpl_client=FakeFpl(fail=True), log=logs.append)
    assert manifest["fpl"] is False
    assert any("FPL unavailable" in line for line in logs)


def test_repeated_or_unsorted_seasons_are_fetched_once_in_order(paths):
    manifest = fetch_all("key", seasons=[2025, 2024, 2025], fd_client=FakeFootballData(),
                         use_fpl=False, log=lambda m: None)
    assert manifest["seasons"] == [2024, 2025]
