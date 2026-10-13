"""Turn cached API responses + the market values CSV into one row per player."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from . import config
from .fpl import ELEMENT_TYPE_TO_POSITION, form_from_status
from .names import match_one

DEFAULT_MINUTES_PER_MATCH = 75.0


# --------------------------------------------------------------------------- helpers

def normalize_position(*labels: str | None) -> str | None:
    """Map football-data.org labels ('Offence', 'Centre-Back', 'Defensive Midfield'...)."""
    for label in labels:
        if not label:
            continue
        text = label.lower()
        if "goal" in text or "keeper" in text:
            return "Goalkeeper"
        if "midfield" in text:  # before 'defen' so 'Defensive Midfield' stays a midfielder
            return "Midfielder"
        if "back" in text or "defen" in text:
            return "Defender"
        if any(k in text for k in ("offen", "forward", "attack", "striker", "wing")):
            return "Forward"
    return None


def age_on(dob: str | None, on: date) -> float | None:
    if not dob:
        return None
    born = datetime.strptime(dob[:10], "%Y-%m-%d").date()
    return round((on - born).days / 365.25, 1)


def form_from_availability(matches: float) -> str:
    """Fallback when FPL is unavailable: how much of the season the player was on the pitch."""
    share = matches / config.LEAGUE_MATCHES_PER_SEASON
    if share >= 0.5:
        return "fit"
    if share >= 0.25:
        return "weak"
    return "injured"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fd_names(bio: dict) -> list[str]:
    full = " ".join(p for p in (bio.get("firstName"), bio.get("lastName")) if p)
    return [n for n in (bio.get("name"), full) if n]


def _fd_clubs(records: list[dict]) -> list[str]:
    clubs = []
    for r in records:
        clubs += [r.get("team"), r.get("team_short"), r.get("team_tla")]
    return [c for c in clubs if c]


# --------------------------------------------------------------------------- football-data

def load_season_records(raw_dir: Path, seasons: list[int]) -> tuple[dict[int, dict], dict[int, list[dict]]]:
    """Read cached scorers files -> (player bios by id, per-season stat records by id)."""
    bios: dict[int, dict] = {}
    records: dict[int, dict[int, dict]] = defaultdict(dict)
    for season in seasons:
        path = raw_dir / f"scorers_{season}.json"
        if not path.exists():
            continue
        for entry in _read_json(path).get("scorers", []):
            player, team = entry.get("player") or {}, entry.get("team") or {}
            pid = player.get("id")
            if pid is None:
                continue
            bios[pid] = {**bios.get(pid, {}), **{k: v for k, v in player.items() if v is not None}}
            rec = records[pid].get(season)
            stats = {
                "matches": entry.get("playedMatches") or 0,
                "goals": entry.get("goals") or 0,
                "assists": entry.get("assists") or 0,
                "penalties": entry.get("penalties") or 0,
            }
            if rec:  # listed twice in a season (moved clubs mid-season): add the spells up
                for k, v in stats.items():
                    rec[k] += v
            else:
                rec = records[pid][season] = {"season": season, "label": config.season_label(season), **stats}
            rec.update({
                "team": team.get("name"),
                "team_short": team.get("shortName"),
                "team_tla": team.get("tla"),
                "crest": team.get("crest"),
            })
    return bios, {pid: [by_season[s] for s in sorted(by_season)] for pid, by_season in records.items()}


# --------------------------------------------------------------------------- FPL

def match_fpl_elements(bios: dict[int, dict], records: dict[int, list[dict]],
                       bootstrap: dict) -> dict[int, dict]:
    """football-data player id -> FPL element, for players we can match confidently."""
    teams = {t["id"]: t for t in bootstrap.get("teams", [])}
    elements = bootstrap.get("elements", [])
    candidates = []
    for el in elements:
        team = teams.get(el.get("team"), {})
        candidates.append((
            [f"{el.get('first_name', '')} {el.get('second_name', '')}".strip(), el.get("web_name")],
            [team.get("name"), team.get("short_name")],
        ))
    matched: dict[int, dict] = {}
    taken: set[int] = set()
    for pid, bio in bios.items():
        idx = match_one(_fd_names(bio), _fd_clubs(records.get(pid, [])), candidates)
        if idx is not None and idx not in taken:
            matched[pid] = elements[idx]
            taken.add(idx)
    return matched


def fpl_minutes_by_season(element: dict, summary: dict | None, current_season: int | None) -> dict[int, int]:
    minutes: dict[int, int] = {}
    for past in (summary or {}).get("history_past", []):
        try:
            start = int(str(past["season_name"])[:4])
        except (KeyError, ValueError):
            continue
        minutes[start] = int(past.get("minutes") or 0)
    if current_season is not None and element.get("minutes") is not None:
        minutes[current_season] = int(element["minutes"])
    return minutes


# --------------------------------------------------------------------------- market values

def load_market_values(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                value = float(row.get("market_value_eur_m") or "")
            except ValueError:
                continue
            if value <= 0 or not (row.get("name") or "").strip():
                continue
            form = (row.get("form") or "").strip().lower()
            rows.append({
                "name": row["name"].strip(),
                "club": (row.get("club") or "").strip(),
                "value": value,
                "as_of": (row.get("as_of") or "").strip() or None,
                "form": form if form in config.FORMS else None,
                "photo_url": (row.get("photo_url") or "").strip() or None,
            })
    return rows


# --------------------------------------------------------------------------- build

def build_dataset(raw_dir: Path | None = None,
                  market_values_path: Path | None = None,
                  today: date | None = None) -> dict:
    raw_dir = raw_dir or config.RAW_DIR
    market_values_path = market_values_path or config.MARKET_VALUES_PATH
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No fetched data in {raw_dir}. Run `python -m predictor fetch` first.")
    manifest = _read_json(manifest_path)
    seasons: list[int] = manifest["seasons"]
    current_season = manifest.get("current_season")
    as_of = today or datetime.fromisoformat(manifest["fetched_at"]).date()

    bios, records = load_season_records(raw_dir, seasons)
    if not bios:
        raise ValueError(f"The scorers files in {raw_dir} contain no players.")

    # Minutes + availability + photos from FPL, when it was fetched.
    fpl_matches: dict[int, dict] = {}
    bootstrap_path = raw_dir / "fpl_bootstrap.json"
    if manifest.get("fpl") and bootstrap_path.exists():
        fpl_matches = match_fpl_elements(bios, records, _read_json(bootstrap_path))
    for pid, element in fpl_matches.items():
        summary_path = raw_dir / "fpl" / f"element_{element['id']}.json"
        summary = _read_json(summary_path) if summary_path.exists() else None
        minutes = fpl_minutes_by_season(element, summary, current_season)
        for rec in records[pid]:
            if rec["season"] in minutes:
                rec["minutes"] = minutes[rec["season"]]
                rec["minutes_estimated"] = False

    # Estimate the rest from the average minutes per appearance where we do know them.
    known = [(r["minutes"], r["matches"]) for recs in records.values() for r in recs
             if "minutes" in r and r["matches"] > 0]
    per_match = (sum(m for m, _ in known) / sum(n for _, n in known)) if known else DEFAULT_MINUTES_PER_MATCH
    for recs in records.values():
        for r in recs:
            if "minutes" not in r:
                r["minutes"] = round(r["matches"] * per_match)
                r["minutes_estimated"] = True

    players = []
    for pid, bio in bios.items():
        recs = records[pid]
        latest = recs[-1]
        element = fpl_matches.get(pid)
        position = normalize_position(bio.get("position"), bio.get("section"))
        if position is None and element:
            position = ELEMENT_TYPE_TO_POSITION.get(element.get("element_type"))
        fpl_form = form_from_status(element.get("status"), element.get("chance_of_playing_next_round")) \
            if element else None
        players.append({
            "id": pid,
            "name": bio.get("name") or " ".join(_fd_names(bio)),
            "first_name": bio.get("firstName"),
            "last_name": bio.get("lastName"),
            "date_of_birth": bio.get("dateOfBirth"),
            "nationality": bio.get("nationality"),
            "shirt_number": bio.get("shirtNumber"),
            "position": position or "Midfielder",
            "position_detail": bio.get("position") or bio.get("section"),
            "team": {k: latest.get(k) for k in ("team", "team_short", "team_tla", "crest")},
            "seasons": recs,
            "features": {
                "goals": round(mean(r["goals"] for r in recs), 2),
                "assists": round(mean(r["assists"] for r in recs), 2),
                "minutes": round(mean(r["minutes"] for r in recs), 1),
                "matches": round(mean(r["matches"] for r in recs), 2),
                "age": age_on(bio.get("dateOfBirth"), as_of),
                "position": position or "Midfielder",
                "form": fpl_form or form_from_availability(latest["matches"]),
            },
            "form_source": "fpl" if fpl_form else "availability",
            "minutes_estimated": any(r["minutes_estimated"] for r in recs),
            "fpl": {
                "id": element["id"],
                "code": element.get("code"),
                "status": element.get("status"),
                "news": element.get("news") or "",
                "chance_of_playing": element.get("chance_of_playing_next_round"),
            } if element else None,
            "photo_url": None,
            "market_value_eur_m": None,
            "market_value_as_of": None,
        })

    # Attach reference market values (the regression target).
    candidates = [(_fd_names(bios[p["id"]]) or [p["name"]], _fd_clubs(p["seasons"])) for p in players]
    unmatched_values, claimed = [], {}
    for row in load_market_values(market_values_path):
        idx = match_one([row["name"]], [row["club"]], candidates)
        if idx is None or idx in claimed:
            unmatched_values.append(row["name"])
            continue
        claimed[idx] = row["name"]
        p = players[idx]
        p["market_value_eur_m"] = row["value"]
        p["market_value_as_of"] = row["as_of"]
        if row["photo_url"]:
            p["photo_url"] = row["photo_url"]
        if row["form"]:
            p["features"]["form"] = row["form"]
            p["form_source"] = "override"

    players.sort(key=lambda p: (-(p["market_value_eur_m"] or 0), -p["features"]["goals"], p["name"]))
    return {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "seasons": seasons,
        "season_labels": [config.season_label(s) for s in seasons],
        "current_season": current_season,
        "fetched_at": manifest.get("fetched_at"),
        "sources": {
            "football_data": True,
            "fpl": bool(manifest.get("fpl")),
            "fpl_matched": len(fpl_matches),
            "minutes_per_match_used_for_estimates": round(per_match, 1),
        },
        "unmatched_market_values": unmatched_values,
        "players": players,
    }


def save_dataset(dataset: dict, path: Path | None = None) -> None:
    path = path or config.PLAYERS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset, indent=1, ensure_ascii=False), encoding="utf-8")


def load_dataset(path: Path | None = None) -> dict | None:
    path = path or config.PLAYERS_PATH
    return _read_json(path) if path.exists() else None
