"""Thread ids and checkpoint plumbing for the persisted workflow.

LangGraph does the persistence: a checkpointer given to
``workflow.build_graph`` stores the state after every completed node
under a thread id, and the graph resumes or reopens from it. This
module only holds the few pieces the graph itself does not decide: how
a thread id is minted, the config that names it, the serializer that
knows this project's state classes, a loader that fails clearly when a
thread does not exist, and the SQLite file the script checkpoints to.

One thread id is exactly one research question and one run. Starting
another question on an existing thread would append to its evidence
and answers through the state reducers, so it is never done.
"""

import contextlib
import sqlite3
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.serde import jsonplus
from langgraph.checkpoint.sqlite import aio
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot

from industry import records as industry_records

# The legacy (Phase 6-9) state classes; they stay importable so the
# recorded threads can be read after the old graph is gone.
LEGACY_CLASSES = [
    ("research.plan", "Candidate"),
    ("research.plan", "ResearchPlan"),
    ("research.sources", "SourceRecord"),
    ("research.verify", "ClaimCheck"),
    ("research.verify", "Conflict"),
    ("research.verify", "SourceRating"),
    ("research.verify", "Verification"),
]

# The default serializer rebuilds dataclasses and pydantic models by
# importing them, and refuses classes that are not listed: the legacy
# classes plus every Phase 10 record (``industry.records.PERSISTED``).
SERIALIZER = jsonplus.JsonPlusSerializer(
    allowed_msgpack_modules=LEGACY_CLASSES
    + [("industry.records", cls.__name__) for cls in industry_records.PERSISTED]
)


class LegacyThreadError(LookupError):
    """The thread was recorded by another workflow version."""


def new_thread_id() -> str:
    """Mint a short random id for a new run."""
    return uuid.uuid4().hex[:8]


def thread_config(thread_id: str) -> dict[str, Any]:
    """The run config that puts a graph call on one thread."""
    return {"configurable": {"thread_id": thread_id}}


async def load_state(
    graph: CompiledStateGraph, thread_id: str
) -> StateSnapshot:
    """Return the latest checkpoint of a thread.

    Args:
      graph: A graph compiled with the checkpointer holding the thread.
      thread_id: The id printed when the run started.

    Returns:
      The snapshot: ``values`` is the state after the last completed
      node; ``next`` names the node still to run, or is empty when the
      run completed.

    Raises:
      LookupError: If the thread has no checkpoint. Nothing is created.
    """
    snapshot = await graph.aget_state(thread_config(thread_id))
    if not snapshot.values:
        raise LookupError(f"No workflow found for thread {thread_id!r}.")
    return snapshot


def thread_version(snapshot: StateSnapshot) -> str | None:
    """The workflow version a thread was recorded with; ``None`` if legacy."""
    meta = snapshot.values.get("meta")
    return getattr(meta, "workflow_version", None)


async def load_industry_state(
    graph: CompiledStateGraph, thread_id: str, expected_version: str
) -> StateSnapshot:
    """Return a Phase 10 thread's latest checkpoint, or refuse clearly.

    Raises:
      LookupError: If the thread has no checkpoint.
      LegacyThreadError: If the thread was recorded by the Phase 6-9
        workflow (no ``meta``) or by another workflow version; such a
        thread can be replayed read-only in Studio but not resumed.
    """
    snapshot = await load_state(graph, thread_id)
    version = thread_version(snapshot)
    if version is None:
        raise LegacyThreadError(
            f"Thread {thread_id!r} was recorded by the Phase 6-9 workflow; "
            "replay it read-only in Studio, it cannot be resumed here."
        )
    if version != expected_version:
        raise LegacyThreadError(
            f"Thread {thread_id!r} was recorded by workflow "
            f"{version!r}; this program runs {expected_version!r}."
        )
    problems = validate_records(snapshot.values)
    if problems:
        raise LegacyThreadError(
            f"Thread {thread_id!r} holds records the current schema "
            f"rejects ({len(problems)}): {problems[0]}"
        )
    return snapshot


REGISTRY_KEYS = (
    "tasks",
    "attempts",
    "single_calls",
    "sources",
    "source_versions",
    "evidence",
    "claims",
    "relationships",
    "calculations",
    "issues",
    "findings",
)


def validate_records(values: dict[str, Any]) -> list[str]:
    """Re-validate the registries of a loaded state; return the problems.

    The checkpoint serializer rebuilds a model that fails validation
    with ``model_construct`` and no error, leaving nested values as
    dictionaries; a loaded thread must not proceed on such records.
    """
    problems: list[str] = []
    for key in REGISTRY_KEYS:
        for item_id, item in (values.get(key) or {}).items():
            try:
                type(item).model_validate(item.model_dump())
            except (AttributeError, ValueError) as error:
                problems.append(f"{key}[{item_id}]: {str(error)[:120]}")
    return problems


def resume_config(thread_id: str, snapshot: StateSnapshot) -> dict[str, Any]:
    """The run config for resuming a thread at its unfinished node.

    ``interrupted_node`` names the node that did not complete, so a
    single-call node can charge the conservative reservation of its
    lost attempt when it runs again (``industry.graph``).
    """
    config = thread_config(thread_id)
    config["configurable"]["interrupted_node"] = (
        snapshot.next[0] if snapshot.next else None
    )
    return config


def backup(path: str, destination: str) -> None:
    """Copy the checkpoint database consistently with SQLite's backup API.

    Safe while another process holds the file (WAL included); a plain
    file copy of an active database is not.
    """
    source = sqlite3.connect(path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


# One SQLite file next to the Chroma store; gitignored like it.
DB_PATH = "data/workflow.db"


@contextlib.asynccontextmanager
async def open_checkpointer(
    path: str = DB_PATH,
) -> AsyncIterator[aio.AsyncSqliteSaver]:
    """Open the SQLite checkpointer on ``path`` for the duration of a run.

    The file and its tables are created on first use. The saver only
    accepts its serializer through the constructor, which
    ``from_conn_string`` does not expose, so it is set afterwards.
    """
    async with aio.AsyncSqliteSaver.from_conn_string(path) as saver:
        saver.serde = SERIALIZER
        yield saver
