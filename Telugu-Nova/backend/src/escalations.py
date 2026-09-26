"""Day 7: knowing when to fetch a human.

Nova teaches Computer Science. There are two situations where continuing to
teach is the wrong thing to do, and both end with a real person being told:

    wellbeing   -- the student is distressed, frightened, or says something
                   that worries you about their safety. Nova is not a
                   counsellor and must not try to be one.
    teacher     -- Nova has genuinely failed. Explained the same thing several
                   ways and the student still cannot follow, or they need
                   something only a real teacher can give.

Everything here runs on the database loop from memory.py, so it inherits the
same isolation from LiveKit's executor lifecycle.

What is deliberately NOT stored: the conversation transcript. A human helping
a distressed student does not need a recording of them being distressed. They
need to know who, what, what was already tried, and how urgent it is.
"""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from memory import _call, _ensure_pool

logger = logging.getLogger("agent.escalations")

REASONS = ("wellbeing", "teacher")
URGENCY = ("low", "medium", "high", "emergency")


SCHEMA = """
CREATE TABLE IF NOT EXISTS escalations (
    ref              TEXT PRIMARY KEY,
    student          TEXT,
    reason           TEXT NOT NULL,
    urgency          TEXT NOT NULL,
    summary          TEXT NOT NULL,
    already_tried    TEXT,
    language         TEXT,
    follow_up        TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# --- redaction ---------------------------------------------------------------
# The prompt tells Nova not to include these. Prompts are requests; this is a
# guarantee. Anything that looks like a credential or contact detail is stripped
# before it reaches a human's screen.

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email removed]"),
    (re.compile(r"\b(?:\+?\d[\d\s-]{8,}\d)\b"), "[phone removed]"),
    (re.compile(r"\b\d{4,}\b"), "[number removed]"),
    (
        re.compile(
            r"\b(otp|pin|password|passcode|cvv|aadhaar|aadhar)\b[:\s]*\S*", re.I
        ),
        "[credential removed]",
    ),
]


def redact(text: str) -> str:
    """Strip anything that looks like a credential or contact detail."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def new_ref() -> str:
    """A reference a student can repeat back over a phone line.

    Four digits, no letters — 'NOVA four eight two one' survives a bad line and
    a Telugu speaker reading it aloud. Anything longer gets misheard.
    """
    return f"NOVA-{random.randint(1000, 9999)}"


# --- implementations, on the database loop -----------------------------------


async def _ensure_table() -> None:
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def _find_open(student: str | None, reason: str) -> dict[str, Any] | None:
    """An open request for the same student and reason in the last 24 hours."""
    await _ensure_table()
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ref, summary, urgency, status, created_at FROM escalations "
            "WHERE status = 'open' AND reason = $1 "
            "AND student IS NOT DISTINCT FROM $2 AND created_at > $3 "
            "ORDER BY created_at DESC LIMIT 1",
            reason,
            student,
            datetime.now(timezone.utc) - timedelta(hours=24),
        )
    return dict(row) if row else None


async def _create(
    student: str | None,
    reason: str,
    urgency: str,
    summary: str,
    already_tried: str | None,
    language: str | None,
    follow_up: str | None,
) -> dict[str, Any]:
    await _ensure_table()
    pool = await _ensure_pool()

    # Same problem still open? Update it rather than pile up duplicates.
    existing = await _find_open(student, reason)
    if existing:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE escalations SET summary = $1, urgency = $2, "
                "already_tried = $3, updated_at = now() WHERE ref = $4",
                redact(summary),
                urgency,
                redact(already_tried or ""),
                existing["ref"],
            )
        logger.info("escalation updated", extra={"ref": existing["ref"]})
        return {"ref": existing["ref"], "updated": True}

    ref = new_ref()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO escalations "
            "(ref, student, reason, urgency, summary, already_tried, language, follow_up) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            ref,
            student,
            reason,
            urgency,
            redact(summary),
            redact(already_tried or ""),
            language,
            follow_up,
        )
    logger.info("escalation created", extra={"ref": ref, "urgency": urgency})
    return {"ref": ref, "updated": False}


async def _status(ref: str) -> dict[str, Any] | None:
    await _ensure_table()
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ref, status, urgency, reason, created_at, updated_at "
            "FROM escalations WHERE ref = $1",
            ref.strip().upper(),
        )
    return dict(row) if row else None


async def _list_all(limit: int = 50) -> list[dict[str, Any]]:
    await _ensure_table()
    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM escalations ORDER BY "
            "CASE urgency WHEN 'emergency' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]


# --- public API --------------------------------------------------------------


async def create(
    student: str | None,
    reason: str,
    urgency: str,
    summary: str,
    already_tried: str | None = None,
    language: str | None = None,
    follow_up: str | None = None,
) -> dict[str, Any]:
    """File a request for a human. Returns {ref, updated}."""
    if reason not in REASONS:
        reason = "teacher"
    if urgency not in URGENCY:
        urgency = "medium"
    return await _call(
        _create(student, reason, urgency, summary, already_tried, language, follow_up)
    )


async def status(ref: str) -> dict[str, Any] | None:
    """Where a request has got to, or None if the reference is unknown."""
    return await _call(_status(ref))


async def list_all(limit: int = 50) -> list[dict[str, Any]]:
    """Everything on the desk, most urgent first."""
    return await _call(_list_all(limit))
