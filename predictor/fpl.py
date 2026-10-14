"""Client for the public Fantasy Premier League API (no key needed).

football-data.org's free tier has no minutes played, injury news or player photos,
so these are filled in from FPL where a player can be matched.
"""

from __future__ import annotations

import time
from typing import Callable

import requests

from . import config

# FPL availability codes -> our physical form categories.
STATUS_TO_FORM = {
    "a": "fit",      # available
    "s": "fit",      # suspended, but physically fine
    "d": "weak",     # doubtful: knock, illness, lacking fitness
    "i": "injured",
    "u": "weak",     # unavailable (left the club, personal reasons...)
    "n": "weak",     # not eligible (on loan to a parent club, etc.)
}

ELEMENT_TYPE_TO_POSITION = {1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward"}


class FplClient:
    def __init__(
        self,
        base_url: str = config.FPL_BASE_URL,
        session: requests.Session | None = None,
        delay: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "transfer-value-predictor/1.0")
        self.delay = delay
        self.sleep = sleep

    def _get(self, path: str) -> dict:
        resp = self.session.get(f"{self.base_url}/{path}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def bootstrap(self) -> dict:
        """Every current player with season totals, availability status and photo code."""
        return self._get("bootstrap-static/")

    def element_summary(self, element_id: int) -> dict:
        """Per-player detail; `history_past` holds totals (incl. minutes) for previous seasons."""
        self.sleep(self.delay)  # be polite: this is called once per player
        return self._get(f"element-summary/{element_id}/")


def form_from_status(status: str | None, chance_of_playing: int | None = None) -> str | None:
    if not status:
        return None
    # A doubtful player with little chance of playing is really injured. Only for 'd':
    # FPL also sets 0% for players who were sold or can't face their parent club.
    if status == "d" and chance_of_playing is not None and chance_of_playing <= 25:
        return "injured"
    return STATUS_TO_FORM.get(status)


def fpl_season(bootstrap: dict) -> int | None:
    """Start year of the FPL game a bootstrap snapshot belongs to (from gameweek 1's deadline)."""
    for event in bootstrap.get("events") or []:
        deadline = str(event.get("deadline_time") or "")
        if deadline[:4].isdigit():
            return int(deadline[:4])
    return None


def summary_filename(element: dict, season: int | None) -> str:
    """Cache file for a player's element-summary.

    Keyed by `code`, which is stable across seasons (element ids are renumbered every
    season), plus the FPL season, because `history_past` gains a row each new season.
    """
    code = element.get("code")
    who = code if code is not None else f"id{element['id']}"
    return f"element_{who}_{season}.json" if season is not None else f"element_{who}.json"
