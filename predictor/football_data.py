"""Thin client for the football-data.org v4 REST API, built on requests."""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from . import config


class FootballDataError(RuntimeError):
    """The API refused a request (bad key, plan restriction, unknown resource...)."""


class FootballDataClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = config.FOOTBALL_DATA_BASE_URL,
        session: requests.Session | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise FootballDataError(
                f"No API key. Get a free one at https://www.football-data.org/client/register "
                f"and set {config.FOOTBALL_DATA_API_KEY_ENV} (or put it in .env)."
            )
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"X-Auth-Token": api_key, "Accept": "application/json"})
        self.max_retries = max_retries
        self.sleep = sleep

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429 and attempt < self.max_retries:
                # Free tier allows 10 requests/minute; the reset header says how long to wait.
                self.sleep(_reset_seconds(resp) + 1)
                continue
            if resp.status_code >= 400:
                raise FootballDataError(f"{resp.status_code} for {resp.url}: {_error_message(resp)}")
            if resp.headers.get("X-Requests-Available-Minute") == "0":
                self.sleep(_reset_seconds(resp) + 1)
            return resp.json()
        raise FootballDataError(f"Still rate limited after {self.max_retries} retries: {url}")

    def competition(self, code: str = config.COMPETITION) -> dict:
        return self.get(f"competitions/{code}")

    def scorers(self, season: int, limit: int = config.DEFAULT_SCORERS_LIMIT,
                code: str = config.COMPETITION) -> dict:
        """Top scorers for a season: goals, assists, matches played plus player and team info."""
        return self.get(f"competitions/{code}/scorers", params={"season": season, "limit": limit})


def current_season_start_year(competition: dict) -> int:
    return int(competition["currentSeason"]["startDate"][:4])


def recent_seasons(current_start_year: int, count: int, include_current: bool = False) -> list[int]:
    """The last `count` completed seasons (plus the in-progress one if asked), oldest first."""
    last = current_start_year if include_current else current_start_year - 1
    return list(range(last - count + 1, last + 1))


def _reset_seconds(resp: requests.Response) -> int:
    try:
        return int(resp.headers.get("X-RequestCounter-Reset", 60))
    except ValueError:
        return 60


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("message") or resp.text
    except ValueError:
        return resp.text[:200]
