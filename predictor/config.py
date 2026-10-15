"""Paths, API settings and shared constants."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding the real environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(ROOT / ".env")

# Data locations can be overridden (the tests point them at temp directories).
DATA_DIR = Path(os.environ.get("TVP_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
MARKET_VALUES_PATH = Path(os.environ.get("TVP_MARKET_VALUES", ROOT / "data" / "market_values.csv"))
PLAYERS_PATH = DATA_DIR / "players.json"
MODEL_DIR = Path(os.environ.get("TVP_MODEL_DIR", ROOT / "models"))
MODEL_PATH = MODEL_DIR / "model.json"

# football-data.org (https://www.football-data.org/documentation/api)
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
FOOTBALL_DATA_API_KEY_ENV = "FOOTBALL_DATA_API_KEY"
API_KEY_PLACEHOLDER = "your-key-here"  # what .env.example ships with
COMPETITION = "PL"
DEFAULT_SEASON_COUNT = 3
DEFAULT_SCORERS_LIMIT = 100

# Fantasy Premier League public API: minutes, availability and photos,
# none of which football-data.org's free tier provides.
FPL_BASE_URL = "https://fantasy.premierleague.com/api"
PHOTO_URL_TEMPLATES = [
    "https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png",
    "https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
]

POSITIONS = ["Goalkeeper", "Defender", "Midfielder", "Forward"]
FORMS = ["fit", "weak", "injured"]
NUMERIC_FEATURES = ["goals", "assists", "minutes", "matches", "age"]
LEAGUE_MATCHES_PER_SEASON = 38


def api_key() -> str:
    """The football-data.org key, or '' if it is unset or still the .env.example placeholder."""
    key = os.environ.get(FOOTBALL_DATA_API_KEY_ENV, "").strip()
    return "" if key == API_KEY_PLACEHOLDER else key


def season_label(start_year: int) -> str:
    """2024 -> '2024/25' (the format FPL uses for past seasons)."""
    return f"{start_year}/{(start_year + 1) % 100:02d}"
