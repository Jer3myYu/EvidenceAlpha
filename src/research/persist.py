"""Thread ids and checkpoint plumbing for the persisted workflow.

LangGraph does the persistence: a checkpointer given to
``workflow.build_graph`` stores the state after every completed node
under a thread id, and the graph resumes or reopens from it. This
module only holds the few pieces the graph itself does not decide: how
a thread id is minted, the config that names it, the serializer that
knows this project's state classes, and a loader that fails clearly
when a thread does not exist.

One thread id is exactly one research question and one run. Starting
another question on an existing thread would append to its evidence
and answers through the state reducers, so it is never done.
"""

import uuid
from typing import Any

from langgraph.checkpoint.serde import jsonplus
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot

# The default serializer rebuilds dataclasses by importing them, and from
# a future version refuses classes that are not listed. These are the
# three that live in ResearchState.
SERIALIZER = jsonplus.JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("research.plan", "Candidate"),
        ("research.plan", "ResearchPlan"),
        ("research.sources", "SourceRecord"),
    ]
)


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
