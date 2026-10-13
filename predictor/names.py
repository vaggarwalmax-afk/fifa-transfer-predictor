"""Fuzzy name matching across sources that spell players differently.

football-data.org, FPL and the hand-kept market values CSV disagree on accents, word
order ("Son Heung-min" vs "Heung-Min Son") and nicknames ("Rodri"), so matching
works on normalised token sets with a small bonus when the clubs agree.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Iterable, Sequence

# Letters that NFKD does not decompose into ASCII + combining mark.
_SPECIAL = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss", "ł": "l",
                          "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "œ": "oe", "þ": "th"})
_CLUB_NOISE = {"fc", "afc", "cf", "the"}

MATCH_THRESHOLD = 0.85
TEAM_BONUS = 0.1


def normalize(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name.translate(_SPECIAL))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def name_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta == tb:
        return 0.98
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if small <= large:
        # "Gabriel Martinelli" inside "Gabriel Martinelli Silva" is safe; a lone
        # "Gabriel" could be several people, so it needs the club bonus to pass.
        return 0.9 if len(small) >= 2 else 0.78
    return 0.85 * difflib.SequenceMatcher(None, na, nb).ratio()


def best_name_similarity(names_a: Iterable[str | None], names_b: Iterable[str | None]) -> float:
    names_b = [n for n in names_b if n]
    return max((name_similarity(a, b) for a in names_a if a for b in names_b), default=0.0)


def clubs_match(a: str | None, b: str | None) -> bool:
    ta = set(normalize(a).split()) - _CLUB_NOISE
    tb = set(normalize(b).split()) - _CLUB_NOISE
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta or normalize(a) == normalize(b)


def match_one(
    names: Sequence[str | None],
    clubs: Sequence[str | None],
    candidates: Sequence[tuple[Sequence[str | None], Sequence[str | None]]],
    threshold: float = MATCH_THRESHOLD,
) -> int | None:
    """Index of the candidate (names, clubs) that best matches, or None if unclear."""
    scored = []
    for i, (cand_names, cand_clubs) in enumerate(candidates):
        score = best_name_similarity(names, cand_names)
        if score <= 0:
            continue
        if any(clubs_match(c1, c2) for c1 in clubs if c1 for c2 in cand_clubs if c2):
            score += TEAM_BONUS
        scored.append((score, i))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_idx = scored[0]
    if best_score < threshold:
        return None
    if len(scored) > 1 and best_score - scored[1][0] < 0.05:
        return None  # two players look equally plausible; better unmatched than wrong
    return best_idx
