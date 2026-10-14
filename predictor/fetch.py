"""Download Premier League stats and cache the raw responses under data/raw/."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from . import config
from .dataset import load_season_records, match_fpl_elements
from .football_data import (FootballDataClient, FootballDataError, current_season_start_year,
                            recent_seasons)
from .fpl import FplClient, summary_filename
from .jsonio import write_json as _write


def fetch_all(
    api_key: str,
    seasons: list[int] | None = None,
    season_count: int = config.DEFAULT_SEASON_COUNT,
    include_current: bool = False,
    limit: int = config.DEFAULT_SCORERS_LIMIT,
    use_fpl: bool = True,
    refresh: bool = False,
    raw_dir: Path | None = None,
    fd_client: FootballDataClient | None = None,
    fpl_client: FplClient | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    raw_dir = raw_dir or config.RAW_DIR
    fd = fd_client or FootballDataClient(api_key)

    competition = fd.competition()
    _write(raw_dir / "competition.json", competition)
    current = current_season_start_year(competition)
    if seasons:
        seasons = sorted(set(seasons))  # a repeated season would be counted twice
    else:
        seasons = recent_seasons(current, season_count, include_current)
    log(f"Premier League seasons: {', '.join(config.season_label(s) for s in seasons)}")

    fetched = []
    for season in seasons:
        try:
            data = fd.scorers(season, limit)
        except FootballDataError as exc:
            log(f"  ! {config.season_label(season)} skipped: {exc}")
            continue
        _write(raw_dir / f"scorers_{season}.json", data)
        fetched.append(season)
        log(f"  {config.season_label(season)}: {len(data.get('scorers', []))} players")
    if not fetched:
        raise FootballDataError("No season could be downloaded; check your API key and plan.")

    fpl_ok = False
    if use_fpl:
        try:
            fpl = fpl_client or FplClient()
            bootstrap = fpl.bootstrap()
            _write(raw_dir / "fpl_bootstrap.json", bootstrap)
            bios, records = load_season_records(raw_dir, fetched)
            matched = match_fpl_elements(bios, records, bootstrap)
            log(f"FPL: matched {len(matched)}/{len(bios)} players; downloading season histories...")
            for element in matched.values():
                path = raw_dir / "fpl" / summary_filename(element)
                if refresh or not path.exists():
                    _write(path, fpl.element_summary(element["id"]))
            fpl_ok = True
        except requests.RequestException as exc:
            log(f"  ! FPL unavailable ({exc}); minutes will be estimated from appearances "
                f"and form from availability.")

    manifest = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "competition": config.COMPETITION,
        "current_season": current,
        "seasons": fetched,
        "fpl": fpl_ok,
    }
    _write(raw_dir / "manifest.json", manifest)
    return manifest
