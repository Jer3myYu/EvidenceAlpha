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
import typing
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.serde import jsonplus
from langgraph.checkpoint.sqlite import aio
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot

from industry import merge
from industry import quantities
from industry import records as industry_records
from industry import state as state_module

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


def recorded_meta(values: dict[str, Any], field: str) -> Any:
    """A ``RunMeta`` field of a loaded state, model or raw mapping.

    A thread written by another record schema comes back with its
    ``meta`` as the raw mapping the serializer read (``Record.
    model_construct`` refuses to rebuild it); it is still that
    workflow's thread, so readers classify it by what it recorded.
    """
    meta = values.get("meta")
    if isinstance(meta, dict):
        return meta.get(field)
    return getattr(meta, field, None)


def thread_version(snapshot: StateSnapshot) -> str | None:
    """The workflow version a thread was recorded with; ``None`` if legacy."""
    return recorded_meta(snapshot.values, "workflow_version")


async def load_industry_state(
    graph: CompiledStateGraph, thread_id: str, expected_version: str
) -> StateSnapshot:
    """Return a Phase 10 thread's latest checkpoint, or refuse clearly.

    Raises:
      LookupError: If the thread has no checkpoint.
      LegacyThreadError: If the thread was recorded by the Phase 6-9
        workflow (no ``meta``), by another workflow version, or with
        another record schema, or if its records did not survive
        deserialization; such a thread can be replayed read-only in
        Studio but not resumed.
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
    schema = recorded_meta(snapshot.values, "schema_version")
    if schema != industry_records.SCHEMA_VERSION:
        # A record schema this program does not write is not resumable:
        # the serializer drops the fields it does not know without an
        # error, so the thread would continue on silently stripped
        # records. Replay stays available and read-only.
        raise LegacyThreadError(
            f"Thread {thread_id!r} was recorded with record schema "
            f"{schema}; this program writes schema "
            f"{industry_records.SCHEMA_VERSION}. Replay it read-only in "
            "Studio, it cannot be resumed here."
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


def nested_problems(label: str, item: Any) -> list[str]:
    """Record-typed fields of a loaded record that are not records.

    ``model_validate(item.model_dump())`` cannot see this: a dump turns
    a genuine nested record and a plain dictionary left behind by the
    serializer's ``model_construct`` fallback into the same payload, and
    validating that payload rebuilds the record either way. The loaded
    object's own attributes are what the readers use, so they are what
    is checked.
    """
    problems: list[str] = []
    hints = typing.get_type_hints(type(item))
    for name in type(item).model_fields:
        kind, model = state_module.container_of(hints.get(name))
        if model is None:
            continue
        value = getattr(item, name, None)
        if kind == "dict" and isinstance(value, dict):
            entries = [(f"{label}.{name}[{k}]", v) for k, v in value.items()]
        elif kind == "list" and isinstance(value, list):
            entries = [(f"{label}.{name}[{i}]", v) for i, v in enumerate(value)]
        elif value is None:
            continue
        else:
            entries = [(f"{label}.{name}", value)]
        for sub_label, sub in entries:
            if not isinstance(sub, model):
                problems.append(
                    f"{sub_label}: {type(sub).__name__} where "
                    f"{model.__name__} is required"
                )
            else:
                problems.extend(nested_problems(sub_label, sub))
    return problems


def validate_records(values: dict[str, Any]) -> list[str]:
    """Re-validate the registries of a loaded state; return the problems.

    The checkpoint serializer rebuilds a model that fails validation
    with ``model_construct`` and no error, leaving nested values as
    dictionaries; a loaded thread must not proceed on such records.
    """
    problems: list[str] = []
    expected = state_module.record_types()

    def check(label: str, item: Any, model: type | None) -> None:
        if model is not None and not isinstance(item, model):
            problems.append(
                f"{label}: {type(item).__name__} where {model.__name__} "
                "is required"
            )
            return
        if not hasattr(item, "model_dump"):
            return
        try:
            type(item).model_validate(item.model_dump())
        except (AttributeError, ValueError) as error:
            problems.append(f"{label}: {str(error)[:120]}")
            return
        problems.extend(nested_problems(label, item))

    for key, value in values.items():
        container, model = expected.get(key, (None, None))
        if value is None and container == "optional":
            continue
        if container == "dict" and not isinstance(value, dict):
            problems.append(f"{key}: not a registry")
        elif container == "list" and not isinstance(value, list):
            problems.append(f"{key}: not a list")
        elif isinstance(value, dict) and container != "model":
            for item_id, item in value.items():
                check(f"{key}[{item_id}]", item, model)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                check(f"{key}[{index}]", item, model)
        else:
            check(key, value, model)
    if problems:
        # A degraded record is reason enough to refuse; the semantic
        # checks below read records, not mappings.
        return problems
    problems.extend(_unbound_quantities(values))
    problems.extend(_withdrawn_but_citable(values))
    return problems


def _unbound_quantities(values: dict[str, Any]) -> list[str]:
    """Observed quantities whose binding the stored evidence refutes.

    An admitted quantity is only as good as the occurrence that
    established it, so a state in which one names missing evidence, a
    changed excerpt, or spans and a parse the evidence does not
    reproduce is not a state this program could have written. The
    stored binding is verified; nothing is searched for.
    """
    claims = values.get("claims")
    evidence = values.get("evidence")
    if not isinstance(claims, dict):
        return []
    problems = []
    for cid, claim in claims.items():
        quantity = getattr(claim, "quantity", None)
        if quantity is None or getattr(claim, "calculation_id", None):
            continue
        if not isinstance(quantity, industry_records.Quantity):
            # A quantity that came back as a mapping is reported by
            # ``nested_problems``; there is no binding to verify here.
            continue
        binding = getattr(quantity, "binding", None)
        holder = (
            evidence.get(binding.evidence_id)
            if isinstance(evidence, dict) and binding is not None
            else None
        )
        refused = quantities.verify_binding(quantity, holder)
        if refused is not None:
            problems.append(
                f"claims[{cid}]: quantity binding not established by the "
                f"evidence ({refused.detail or refused.code})"
            )
    return problems


def _withdrawn_but_citable(values: dict[str, Any]) -> list[str]:
    """Claims whose arithmetic no longer stands behind them.

    A derived claim's approval comes from its calculation, so a state in
    which one is citable while its producer is missing, stopped, of
    another version, disagreeing about the value or unit, or resting on
    a withdrawn input is not a state this program could have written.
    Such a thread is replayed read-only rather than resumed on a number
    nothing supports.
    """
    claims = values.get("claims")
    if not isinstance(claims, dict):
        return []
    derived = [
        (cid, claim)
        for cid, claim in claims.items()
        if getattr(claim, "calculation_id", None)
        or getattr(claim, "kind", None) == "derived"
    ]
    if not derived:
        return []
    calculations = values.get("calculations")
    if not isinstance(calculations, dict):
        return [
            f"claims[{cid}]: reports calculation "
            f"{claim.calculation_id!r} but the thread carries no "
            "calculations"
            for cid, claim in derived
        ]
    problems = []
    for cid, claim in derived:
        if not getattr(claim, "is_reviewed", bool)():
            continue
        if not merge.producer_chain_intact(claim, claims, calculations):
            problems.append(
                f"claims[{cid}]: citable while the calculation behind it "
                f"({claim.calculation_id}) is not current"
            )
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
