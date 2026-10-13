import pytest

from predictor.football_data import (FootballDataClient, FootballDataError,
                                     current_season_start_year, recent_seasons)


class FakeResponse:
    def __init__(self, status, body, headers=None, url="https://api.football-data.org/v4/x"):
        self.status_code, self._body, self.headers, self.url = status, body, headers or {}, url
        self.text = str(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def test_sends_token_and_params():
    session = FakeSession([FakeResponse(200, {"scorers": []})])
    client = FootballDataClient("secret", session=session, sleep=lambda s: None)
    client.scorers(2024, limit=50)
    assert session.headers["X-Auth-Token"] == "secret"
    assert session.calls == [("https://api.football-data.org/v4/competitions/PL/scorers",
                              {"season": 2024, "limit": 50})]


def test_waits_and_retries_when_rate_limited():
    slept = []
    session = FakeSession([
        FakeResponse(429, {"message": "slow down"}, {"X-RequestCounter-Reset": "12"}),
        FakeResponse(200, {"ok": True}),
    ])
    client = FootballDataClient("k", session=session, sleep=slept.append)
    assert client.get("competitions/PL") == {"ok": True}
    assert slept == [13]


def test_error_includes_api_message():
    session = FakeSession([FakeResponse(403, {"message": "The resource you are looking for is restricted."})])
    client = FootballDataClient("k", session=session, sleep=lambda s: None)
    with pytest.raises(FootballDataError, match="restricted"):
        client.scorers(2019)


def test_missing_key_is_a_clear_error():
    with pytest.raises(FootballDataError, match="FOOTBALL_DATA_API_KEY"):
        FootballDataClient("")


def test_season_helpers():
    assert current_season_start_year({"currentSeason": {"startDate": "2026-08-15"}}) == 2026
    assert recent_seasons(2026, 3) == [2023, 2024, 2025]
    assert recent_seasons(2026, 2, include_current=True) == [2025, 2026]
