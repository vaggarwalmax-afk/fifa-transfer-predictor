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
    form = STATUS_TO_FORM.get(status)
    if form == "weak" and chance_of_playing is not None and chance_of_playing <= 25:
        return "injured"
    return form
