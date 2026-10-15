"""Fuzzy name matching across sources that spell players differently.

football-data.org, FPL and the hand-kept market values CSV disagree on accents, word
order ("Son Heung-min" vs "Heung-Min Son") and nicknames ("Rodri"), so matching
works on normalised token sets with a small bonus when the clubs agree.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Sequence

# Letters that NFKD does not decompose into ASCII + combining mark.
_SPECIAL = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss", "ł": "l",
                          "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "œ": "oe", "þ": "th"})
_CLUB_NOISE = {"fc", "afc", "cf", "the"}
# FPL and football-data.org spell a few clubs differently ("Nott'm Forest"/"NFO" vs
# "Nottingham Forest FC"/"NOT"); rewrite them to one spelling before comparing.
_CLUB_ALIASES = [
    (re.compile(r"\bnott m\b"), "nottingham"),
    (re.compile(r"\butd\b"), "united"),
    (re.compile(r"\bspurs\b"), "tottenham hotspur"),
    (re.compile(r"\bwolves\b"), "wolverhampton wanderers"),
    (re.compile(r"^nfo$"), "not"),
    (re.compile(r"^shu$"), "she"),
]

MATCH_THRESHOLD = 0.85
TEAM_BONUS = 0.1
AMBIGUITY_MARGIN = 0.05
FUZZY_WEIGHT = 0.85
# A fuzzy score below (threshold - margin - bonus) can neither pass nor make a passing match
# look ambiguous, so pairs whose cheap upper bound is under this ratio skip the slow ratio().
_FUZZY_FLOOR = (MATCH_THRESHOLD - AMBIGUITY_MARGIN - TEAM_BONUS) / FUZZY_WEIGHT


@lru_cache(maxsize=16384)
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
    matcher = difflib.SequenceMatcher(None, na, nb)
    if matcher.real_quick_ratio() < _FUZZY_FLOOR or matcher.quick_ratio() < _FUZZY_FLOOR:
        return 0.0
    return FUZZY_WEIGHT * matcher.ratio()


def best_name_similarity(names_a: Iterable[str | None], names_b: Iterable[str | None]) -> float:
    names_b = [n for n in names_b if n]
    return max((name_similarity(a, b) for a in names_a if a for b in names_b), default=0.0)


def _club_key(name: str | None) -> str:
    key = normalize(name)
    for pattern, replacement in _CLUB_ALIASES:
        key = pattern.sub(replacement, key)
    return key


def clubs_match(a: str | None, b: str | None) -> bool:
    ka, kb = _club_key(a), _club_key(b)
    ta, tb = set(ka.split()) - _CLUB_NOISE, set(kb.split()) - _CLUB_NOISE
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta or ka == kb


Candidate = tuple[Sequence[str | None], Sequence[str | None]]  # (names, clubs)


def best_match(
    names: Sequence[str | None],
    clubs: Sequence[str | None],
    candidates: Sequence[Candidate],
    threshold: float = MATCH_THRESHOLD,
) -> tuple[int, float] | None:
    """(index, score) of the candidate that best matches, or None if unclear."""
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
    if len(scored) > 1 and best_score - scored[1][0] < AMBIGUITY_MARGIN:
        return None  # two players look equally plausible; better unmatched than wrong
    return best_idx, best_score


def match_one(
    names: Sequence[str | None],
    clubs: Sequence[str | None],
    candidates: Sequence[Candidate],
    threshold: float = MATCH_THRESHOLD,
) -> int | None:
    match = best_match(names, clubs, candidates, threshold)
    return match[0] if match else None


def assign_matches(
    queries: Sequence[Candidate],
    candidates: Sequence[Candidate],
    threshold: float = MATCH_THRESHOLD,
) -> dict[int, int]:
    """Pair queries with distinct candidates, strongest matches first.

    Assigning in score order (not input order) stops a weak partial match such as
    "Gabriel Jesus" -> "Gabriel" from taking a candidate that an exact match needs.
    """
    proposals = []
    for qi, (names, clubs) in enumerate(queries):
        match = best_match(names, clubs, candidates, threshold)
        if match:
            proposals.append((match[1], qi, match[0]))
    proposals.sort(key=lambda p: (-p[0], p[1]))
    assigned: dict[int, int] = {}
    taken: set[int] = set()
    for _score, qi, ci in proposals:
        if ci not in taken:
            assigned[qi] = ci
            taken.add(ci)
    return assigned
