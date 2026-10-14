"""Turn cached API responses + the market values CSV into one row per player."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from . import config
from .fpl import ELEMENT_TYPE_TO_POSITION, form_from_status, fpl_season, summary_filename
from .jsonio import read_json, write_json
from .names import assign_matches, clubs_match

DEFAULT_MINUTES_PER_MATCH = 75.0
TEAM_KEYS = ("team", "team_short", "team_tla", "crest")


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


def form_from_availability(matches: float, matchdays: int = config.LEAGUE_MATCHES_PER_SEASON) -> str:
    """Fallback when FPL is unavailable: how much of the season so far the player featured in."""
    share = matches / max(1, matchdays)
    if share >= 0.5:
        return "fit"
    if share >= 0.25:
        return "weak"
    return "injured"


def _fd_names(bio: dict) -> list[str]:
    full = " ".join(p for p in (bio.get("firstName"), bio.get("lastName")) if p)
    return [n for n in (bio.get("name"), full) if n]


def _club_names(team: dict) -> list[str]:
    return [team.get(k) for k in ("team", "team_short", "team_tla") if team.get(k)]


def _fd_clubs(records: list[dict]) -> list[str]:
    """Every club a player turned out for, including both clubs in a mid-season move."""
    return [c for r in records for spell in r.get("spells", [r]) for c in _club_names(spell)]


def _season_matchdays(scorers: dict) -> int:
    """Matchdays played in the season: 38 once it's over, fewer for the season in progress."""
    try:
        played = int((scorers.get("season") or {}).get("currentMatchday") or 0)
    except (TypeError, ValueError):
        played = 0
    full = config.LEAGUE_MATCHES_PER_SEASON
    return played if 0 < played < full else full


# --------------------------------------------------------------------------- football-data

def load_season_records(raw_dir: Path, seasons: list[int]) -> tuple[dict[int, dict], dict[int, list[dict]]]:
    """Read cached scorers files -> (player bios by id, per-season stat records by id)."""
    bios: dict[int, dict] = {}
    records: dict[int, dict[int, dict]] = defaultdict(dict)
    for season in seasons:
        path = raw_dir / f"scorers_{season}.json"
        if not path.exists():
            continue
        data = read_json(path)
        matchdays = _season_matchdays(data)
        for entry in data.get("scorers", []):
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
            spell = {"team": team.get("name"), "team_short": team.get("shortName"),
                     "team_tla": team.get("tla"), "crest": team.get("crest"), "matches": stats["matches"]}
            if rec:  # listed twice in a season (moved clubs mid-season): add the spells up
                for k, v in stats.items():
                    rec[k] += v
                rec["spells"].append(spell)
            else:
                rec = records[pid][season] = {"season": season, "label": config.season_label(season),
                                              "matchdays": matchdays, **stats, "spells": [spell]}
            # Show the club the player featured most for until FPL says which is current.
            main = max(rec["spells"], key=lambda s: s["matches"])
            rec.update({k: main[k] for k in TEAM_KEYS})
    return bios, {pid: [by_season[s] for s in sorted(by_season)] for pid, by_season in records.items()}


# --------------------------------------------------------------------------- FPL

def fpl_team_names(bootstrap: dict, element: dict) -> list[str]:
    team = next((t for t in bootstrap.get("teams", []) if t.get("id") == element.get("team")), {})
    return [n for n in (team.get("name"), team.get("short_name")) if n]


def match_fpl_elements(bios: dict[int, dict], records: dict[int, list[dict]],
                       bootstrap: dict) -> dict[int, dict]:
    """football-data player id -> FPL element, for players we can match confidently."""
    elements = bootstrap.get("elements", [])
    candidates = [
        ([f"{el.get('first_name', '')} {el.get('second_name', '')}".strip(), el.get("web_name")],
         fpl_team_names(bootstrap, el))
        for el in elements
    ]
    pids = list(bios)
    queries = [(_fd_names(bios[pid]), _fd_clubs(records.get(pid, []))) for pid in pids]
    return {pids[qi]: elements[ci] for qi, ci in assign_matches(queries, candidates).items()}


def fpl_minutes_by_season(element: dict, summary: dict | None, current_season: int | None) -> dict[int, int]:
    minutes: dict[int, int] = {}
    for past in (summary or {}).get("history_past", []):
        if past.get("element_code") not in (None, element.get("code")):
            continue  # a cached history that belongs to someone else
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
    # utf-8-sig: Excel's "CSV UTF-8" starts the file with a byte-order mark.
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                value = float(row.get("market_value_eur_m") or "")
            except ValueError:
                continue
            if not math.isfinite(value) or value <= 0 or not (row.get("name") or "").strip():
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
    manifest = read_json(manifest_path)
    seasons: list[int] = sorted(set(manifest["seasons"]))
    current_season = manifest.get("current_season")
    as_of = today or datetime.fromisoformat(manifest["fetched_at"]).date()

    bios, records = load_season_records(raw_dir, seasons)
    if not bios:
        raise ValueError(f"The scorers files in {raw_dir} contain no players.")

    # Minutes + availability + photos from FPL, when it was fetched.
    fpl_matches: dict[int, dict] = {}
    bootstrap: dict = {}
    bootstrap_path = raw_dir / "fpl_bootstrap.json"
    if manifest.get("fpl") and bootstrap_path.exists():
        bootstrap = read_json(bootstrap_path)
        fpl_matches = match_fpl_elements(bios, records, bootstrap)
    summary_season = manifest.get("fpl_season") or fpl_season(bootstrap) or current_season
    for pid, element in fpl_matches.items():
        summary_path = raw_dir / "fpl" / summary_filename(element, summary_season)
        summary = read_json(summary_path) if summary_path.exists() else None
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
        team = {k: latest.get(k) for k in TEAM_KEYS}
        if element:  # FPL knows the current club; prefer that spell after a mid-season move
            fpl_clubs = fpl_team_names(bootstrap, element)
            for spell in latest["spells"]:
                if any(clubs_match(c, f) for c in _club_names(spell) for f in fpl_clubs):
                    team = {k: spell.get(k) for k in TEAM_KEYS}
                    break
        # Per-season rates, weighted by matchdays so a season in progress counts for what
        # it is rather than as a full 38-game season. Never scaled *up*, though: a player
        # with only a few matchdays of data keeps their raw counts instead of having
        # 2 goals in 1 game stretched to 76 a season.
        full = config.LEAGUE_MATCHES_PER_SEASON
        matchdays = max(sum(r["matchdays"] for r in recs), full)

        def per_season(key: str) -> float:
            return full * sum(r[key] for r in recs) / matchdays

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
            "team": team,
            "seasons": recs,
            "features": {
                "goals": round(per_season("goals"), 2),
                "assists": round(per_season("assists"), 2),
                "minutes": round(min(per_season("minutes"), full * 90), 1),
                "matches": round(min(per_season("matches"), full), 2),
                "age": age_on(bio.get("dateOfBirth"), as_of),
                "position": position or "Midfielder",
                "form": fpl_form or form_from_availability(latest["matches"], latest["matchdays"]),
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
    rows = load_market_values(market_values_path)
    assigned = assign_matches([([r["name"]], [r["club"]]) for r in rows], candidates)
    unmatched_values = [r["name"] for i, r in enumerate(rows) if i not in assigned]
    for ri, idx in assigned.items():
        row, p = rows[ri], players[idx]
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
    write_json(path or config.PLAYERS_PATH, dataset)


def load_dataset(path: Path | None = None) -> dict | None:
    path = path or config.PLAYERS_PATH
    return read_json(path) if path.exists() else None
