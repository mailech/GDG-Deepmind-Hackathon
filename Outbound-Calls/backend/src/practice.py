"""Day 5: real practice problems, fetched live from Codeforces.

A CS tutor that cannot hand you something to actually solve is just a talking
textbook. This pulls the real Codeforces problemset — about 11,000 problems,
each with tags and a difficulty rating — filters it to the student's topic and
level, and returns one they can go and attempt.

Data source: https://codeforces.com/api/problemset.problems
Public, no API key, no rate limit that a tutor would ever reach. LIVE data.

The response is ~5 MB, so it is cached in memory for six hours. The fetch
timestamp travels with every result, because "I pulled this six hours ago"
and "I pulled this just now" are different claims and the student deserves the
honest one.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import aiohttp

logger = logging.getLogger("agent.practice")

API = "https://codeforces.com/api/problemset.problems"
CACHE_TTL = 6 * 60 * 60  # six hours
TIMEOUT = 12  # seconds; slow connections are the norm for our users

_cache: list[dict[str, Any]] | None = None
_cached_at: float = 0.0
_lock = asyncio.Lock()


class PracticeUnavailableError(Exception):
    """Raised when the problemset genuinely cannot be reached.

    The agent turns this into a spoken apology, never silence and never a
    made-up problem.
    """


# Friendly words a student might say -> the tags Codeforces actually uses.
# Order matters: the first match wins, so put specific before general.
TOPIC_TAGS: list[tuple[tuple[str, ...], str]] = [
    (("binary search", "bsearch"), "binary search"),
    (("dp", "dynamic programming"), "dp"),
    (("graph", "bfs", "dfs", "shortest path"), "graphs"),
    (("tree", "trees", "binary tree"), "trees"),
    (("string", "strings"), "strings"),
    (("sort", "sorting", "sortings"), "sortings"),
    (("greedy",), "greedy"),
    (("recursion", "recursive", "divide and conquer"), "divide and conquer"),
    (("two pointer", "two pointers", "sliding window"), "two pointers"),
    (("math", "maths", "number theory"), "math"),
    (("bit", "bitmask", "bits"), "bitmasks"),
    (("array", "arrays", "loop", "loops", "basics"), "implementation"),
]

# Level -> Codeforces rating band. 800 is the easiest rung on the ladder.
LEVEL_BANDS: dict[str, tuple[int, int]] = {
    "beginner": (800, 1000),
    "easy": (800, 1100),
    "intermediate": (1200, 1600),
    "medium": (1200, 1600),
    "advanced": (1700, 2200),
    "hard": (1700, 2400),
}


def tag_for(topic: str) -> str | None:
    """Map a spoken topic onto a Codeforces tag, or None if we cannot."""
    t = (topic or "").strip().lower()
    if not t:
        return None
    for words, tag in TOPIC_TAGS:
        if any(w in t for w in words):
            return tag
    return None


def band_for(level: str | None) -> tuple[int, int]:
    """Map a spoken level onto a rating band. Unknown -> beginner."""
    return LEVEL_BANDS.get((level or "").strip().lower(), (800, 1100))


async def _load() -> tuple[list[dict[str, Any]], float]:
    """Fetch the problemset, or serve the cache. Raises PracticeUnavailable."""
    global _cache, _cached_at

    async with _lock:
        fresh = _cache is not None and (time.time() - _cached_at) < CACHE_TTL
        if fresh:
            assert _cache is not None
            return _cache, _cached_at

        try:
            timeout = aiohttp.ClientTimeout(total=TIMEOUT)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(API, headers={"User-Agent": "nova-cs-tutor/1.0"}) as resp,
            ):
                resp.raise_for_status()
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            # Stale data beats no data — say how old it is and carry on.
            if _cache is not None:
                logger.warning("codeforces unreachable, serving stale cache: %s", exc)
                return _cache, _cached_at
            raise PracticeUnavailableError(str(exc)) from exc

        if payload.get("status") != "OK":
            if _cache is not None:
                return _cache, _cached_at
            raise PracticeUnavailableError(f"API returned {payload.get('status')}")

        _cache = payload["result"]["problems"]
        _cached_at = time.time()
        logger.info("codeforces problemset loaded", extra={"count": len(_cache)})
        return _cache, _cached_at


def _age_phrase(fetched_at: float) -> str:
    """Human wording for how old the data is. Never claim it is newer."""
    mins = int((time.time() - fetched_at) / 60)
    if mins < 2:
        return "just fetched now"
    if mins < 60:
        return f"fetched {mins} minutes ago"
    hours = mins // 60
    return f"fetched {hours} hour{'s' if hours > 1 else ''} ago"


async def find_problem(topic: str, level: str | None = None) -> dict[str, Any]:
    """Return one real problem matching topic and level.

    Raises PracticeUnavailable if the source cannot be reached and nothing is
    cached — the caller must handle that out loud.
    """
    problems, fetched_at = await _load()

    tag = tag_for(topic)
    low, high = band_for(level)

    def matches(p: dict[str, Any], widen: int = 0) -> bool:
        rating = p.get("rating")
        if rating is None or not (low - widen <= rating <= high + widen):
            return False
        return tag is None or tag in p.get("tags", [])

    pool = [p for p in problems if matches(p)]
    # Nothing at this exact difficulty? Widen before giving up — a slightly
    # off-level problem is far more useful than "sorry, nothing found".
    if not pool:
        pool = [p for p in problems if matches(p, widen=400)]
    if not pool and tag:
        pool = [p for p in problems if p.get("rating") and low <= p["rating"] <= high]
    if not pool:
        raise PracticeUnavailableError("no problem matched")

    p = random.choice(pool)
    return {
        "name": p["name"],
        "rating": p.get("rating"),
        "tags": p.get("tags", []),
        "url": f"https://codeforces.com/problemset/problem/{p['contestId']}/{p['index']}",
        "contest_id": p["contestId"],
        "index": p["index"],
        "matched_tag": tag,
        "source": "Codeforces",
        "freshness": _age_phrase(fetched_at),
        "pool_size": len(pool),
    }
