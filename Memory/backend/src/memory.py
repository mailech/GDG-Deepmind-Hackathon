"""Day 4: memory that survives a restart.

One table, one row per student. The agent reaches this only through tools —
never through the prompt — so what it remembers is auditable and can be deleted
on request.

Track: Learning & Literacy, so the facts worth keeping are the ones that change
how you teach someone next time:

    level            -- beginner / intermediate / advanced, in their words
    topics_covered   -- what we have already been through
    weak_spots       -- mistakes they keep repeating (the most useful of all)
    language         -- which language they prefer to be taught in

Deliberately NOT stored: anything that is not about learning. No phone number,
no school, no address, no marks. A CS tutor has no business holding those.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger("agent.memory")

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_executor: concurrent.futures.ThreadPoolExecutor | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    user_id             TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    language_preference TEXT,
    facts               JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_interaction    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def slugify(name: str) -> str:
    """Turn a spoken name into a stable key.

    Speech-to-text spells names inconsistently, so we normalise hard: lowercase,
    strip punctuation, collapse whitespace. "Ravi Kumar", "ravi  kumar" and
    "Ravi, Kumar" all land on the same row.
    """
    cleaned = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE).strip().lower()
    return re.sub(r"\s+", "-", cleaned)


def _install_executor(loop: asyncio.AbstractEventLoop) -> None:
    """Give the loop a live thread pool for DNS lookups.

    LiveKit shuts down the job loop's default executor once the agent is up.
    asyncpg resolves hostnames through `loop.getaddrinfo`, which uses that
    executor, so every connection opened afterwards dies with
    "Executor shutdown has been called".

    We cannot dodge DNS by connecting to an IP either: Neon routes by TLS SNI,
    so the hostname has to survive all the way to the handshake. So we supply
    our own executor instead. LiveKit shut the default one down because it had
    finished with it, not to forbid its use.
    """
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="nova-db"
        )
    loop.set_default_executor(_executor)


async def init() -> None:
    """Open the pool and make sure the table exists. Safe to call repeatedly.

    Rebuilds the pool if the running event loop changed — a pool is bound to
    the loop that created it, and each LiveKit job gets a fresh one.
    """
    global _pool, _pool_loop

    loop = asyncio.get_running_loop()
    _install_executor(loop)

    if _pool is not None and _pool_loop is loop and not _pool.is_closing():
        return

    if _pool is not None and _pool_loop is not loop:
        logger.info("event loop changed — rebuilding pool")
        _pool = None

    dsn = os.environ["DATABASE_URL"]
    # asyncpg speaks SSL natively and rejects libpq-style query params that the
    # Neon console hands out, so strip them and ask for TLS directly.
    dsn = re.sub(r"[?&](sslmode|channel_binding)=[^&]*", "", dsn)

    _pool = await asyncpg.create_pool(
        dsn,
        ssl="require",
        # Open every connection now, while the executor is definitely alive,
        # so a mid-call acquire() never has to resolve DNS again.
        min_size=2,
        max_size=2,
        # Neon's pooler drops idle connections; let asyncpg notice and replace
        # them rather than handing us a dead socket.
        max_inactive_connection_lifetime=180.0,
    )
    _pool_loop = loop
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("memory ready")


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def recall(name: str) -> dict[str, Any] | None:
    """Look a student up by name. None if we have never met them."""
    await init()
    assert _pool is not None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, name, language_preference, facts, last_interaction "
            "FROM students WHERE user_id = $1",
            slugify(name),
        )
    if row is None:
        return None

    facts = row["facts"]
    return {
        "user_id": row["user_id"],
        "name": row["name"],
        "language_preference": row["language_preference"],
        "facts": json.loads(facts) if isinstance(facts, str) else dict(facts or {}),
        "last_interaction": row["last_interaction"].isoformat(),
    }


async def remember(
    name: str,
    facts: dict[str, Any] | None = None,
    language_preference: str | None = None,
) -> dict[str, Any]:
    """Create or update a student's record.

    Facts merge rather than replace, so saving one new weak spot does not wipe
    the topics we covered last month.
    """
    await init()
    assert _pool is not None

    user_id = slugify(name)
    now = datetime.now(timezone.utc)

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (user_id, name, language_preference, facts, last_interaction)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                language_preference =
                    COALESCE(EXCLUDED.language_preference, students.language_preference),
                facts = students.facts || EXCLUDED.facts,
                last_interaction = EXCLUDED.last_interaction
            """,
            user_id,
            name.strip(),
            language_preference,
            json.dumps(facts or {}, ensure_ascii=False),
            now,
        )

    logger.info(
        "remembered", extra={"user_id": user_id, "keys": list((facts or {}).keys())}
    )
    result = await recall(name)
    assert result is not None
    return result


async def forget(name: str) -> bool:
    """Delete a student's record entirely. Returns True if a row was removed."""
    await init()
    assert _pool is not None

    async with _pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM students WHERE user_id = $1", slugify(name)
        )
    removed = status.endswith("1")
    logger.info("forget", extra={"user_id": slugify(name), "removed": removed})
    return removed
