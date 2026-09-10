"""Durable run intervals, separate from reservation and session accounting."""

import contextlib
import datetime
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def stream(graph: Any, payload: Any, config: dict, **options: Any):
    """Stream one tracked graph invocation for the Studio."""
    connection = getattr(graph.checkpointer, "conn", None)
    async with invocation(connection, config["configurable"]["thread_id"]):
        async for event in graph.astream(payload, config, **options):
            yield event


@contextlib.asynccontextmanager
async def invocation(
    connection: aiosqlite.Connection | None, thread_id: str
) -> AsyncIterator[None]:
    """Record one active run interval without changing graph checkpoints.

    A hard kill leaves an open row, explicitly an unknown interval end.
    Completed rows use monotonic duration; UTC dates measure pause gaps.

    Args:
      connection: The checkpointer's SQLite connection, absent in memory tests.
      thread_id: The run being executed or resumed.

    Yields:
      Control to the graph invocation.
    """
    if connection is None:
        yield
        return
    await connection.execute(
        "CREATE TABLE IF NOT EXISTS industry_invocations ("
        "id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, "
        "started_at TEXT NOT NULL, finished_at TEXT, active_s REAL)"
    )
    key = uuid.uuid4().hex
    started = time.monotonic()
    await connection.execute(
        "INSERT INTO industry_invocations(id, thread_id, started_at) "
        "VALUES (?, ?, ?)",
        (key, thread_id, _now()),
    )
    await connection.commit()
    try:
        yield
    finally:
        await connection.execute(
            "UPDATE industry_invocations SET finished_at=?, active_s=? "
            "WHERE id=? AND finished_at IS NULL",
            (_now(), time.monotonic() - started, key),
        )
        await connection.commit()


async def summary(
    connection: aiosqlite.Connection, thread_id: str
) -> dict[str, Any]:
    """Return measured active time, known pauses and explicit unknowns."""
    async with connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='industry_invocations'"
    ) as cursor:
        exists = await cursor.fetchone()
    if not exists:
        return {
            "active_elapsed_s": None,
            "paused_s": None,
            "unknown_intervals": None,
            "intervals": 0,
            "timing_complete": False,
        }
    async with connection.execute(
        "SELECT started_at, finished_at, active_s FROM industry_invocations "
        "WHERE thread_id=? ORDER BY started_at",
        (thread_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    active = sum(row[2] or 0.0 for row in rows)
    paused = 0.0
    gaps_complete = True
    for previous, following in zip(rows, rows[1:]):
        if previous[1] is None:
            gaps_complete = False
            continue
        gap = (
            datetime.datetime.fromisoformat(following[0])
            - datetime.datetime.fromisoformat(previous[1])
        ).total_seconds()
        if gap < 0:
            gaps_complete = False
        else:
            paused += gap
    unknown = sum(row[1] is None for row in rows)
    return {
        "active_elapsed_s": round(active, 3),
        "paused_s": round(paused, 3),
        "unknown_intervals": unknown,
        "intervals": len(rows),
        "timing_complete": bool(rows) and not unknown and gaps_complete,
    }
