"""Workflow Studio: a local page that shows the industry workflow at work.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/studio.py              # http://127.0.0.1:8765
    .venv/bin/python scripts/studio.py --port 9000

The page (``scripts/studio.html``) draws the architecture and the
graph, then drives the graph two ways. *Live*: a question starts a real
run on a new thread, checkpointed exactly like
``scripts/industry_workflow.py``, and every completed node, every
concurrent task attempt, and each tool call inside an attempt streams
to the page as it happens. *Replay*: a recorded thread in
``data/workflow.db`` is stepped through checkpoint by checkpoint with
no model call; a Phase 6-9 thread replays read-only as states and
updates, labelled legacy.

Both produce the same event sequence. A ``node`` event carries what
the node returned, the merged state after it, the trace lines the CLI
prints, the budget ledger (through the one ``budget.ledger``), and the
node's *context window*: the system and user text its model call
received, rebuilt from the state before the node with the same prompt
builders the graph uses and the CrewAI framing that ``tests/test_crew.py``
pins. Every reconstruction is labelled as such; Studio never changes
what the workflow does and never re-implements a routing decision.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import json
import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pydantic
import uvicorn
from langgraph.graph.state import CompiledStateGraph
from starlette import applications
from starlette import requests
from starlette import responses
from starlette import routing

from industry import budget
from industry import graph as graph_module
from industry import records
from industry import roles
from industry import state as state_module
from industry import tools
from industry import trace
from industry import worker
from research import persist
from research import web

PAGE = pathlib.Path(__file__).with_name("studio.html")

# CrewAI 1.15's framing around a no-tools agent (asserted against a real
# crew run in tests/test_studio.py, so a CrewAI upgrade that changes it
# fails there).
SYSTEM_FRAME = "You are {name}. {backstory}\nYour personal goal is: {goal}"
USER_FRAME = (
    "\nCurrent Task: {description}\n\n"
    "This is the expected criteria for your final answer: {expected}\n"
    "you MUST return the actual complete content as the final answer, "
    "not a summary.\n\n"
    "Provide your complete response:"
)
DETERMINISTIC = "deterministic (Python, no model call)"
LIST_KEYS = ("task_results", "route_log")


def encode(value: Any) -> Any:
    """Turn state values into JSON-ready data: models and dataclasses too."""
    if isinstance(value, pydantic.BaseModel):
        return value.model_dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return encode(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def derive_update(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """What changed between two states: new list items, changed values."""
    update: dict[str, Any] = {}
    for key, value in after.items():
        if key in LIST_KEYS:
            old = len(before.get(key, []))
            if len(value) > old:
                update[key] = value[old:]
        elif before.get(key) != value:
            update[key] = value
    return update


def description_for(
    node: str, before: dict[str, Any], limits: records.Limits
) -> str:
    """The task text a single-call node sends, from the state it saw."""
    if node == "scope":
        return roles.scope_description(before["question"])
    if node == "prepare_tasks":
        return roles.plan_description(
            before,
            limits,
            graph_module.planning_slots(before, limits),
            graph_module.planning_purpose(before),
        )
    if node == "assess_coverage":
        return roles.coverage_description(before)
    if node == "analyze":
        return roles.analysis_description(before, graph_module.ANALYSIS_NOTE)
    if node == "review":
        return roles.review_description(
            before, graph_module.pending_review(before)
        )
    if node == "write":
        return roles.draft_description(
            before, graph_module.write_instructions(before)
        )
    if node == "final_review":
        return roles.final_review_description(before)
    raise ValueError(f"{node} makes no single call")


def role_context(
    node: str, before: dict[str, Any], limits: records.Limits
) -> dict[str, Any]:
    """Rebuild the context window of a single-call node."""
    role = roles.ROLE_FOR[node]
    key = roles.ROLE_KEY[node]
    description = description_for(node, before, limits)
    return {
        "who": f"{role.name} (CrewAI crew of one, via ClaudeLLM)",
        "model": roles.ROLE_MODELS[key],
        "system": SYSTEM_FRAME.format(
            name=role.name, backstory=role.backstory, goal=role.goal
        ),
        "user": USER_FRAME.format(
            description=description, expected=roles.EXPECTED[node]
        ),
        "schema": role.output.model_json_schema() if role.output else None,
        "reconstructed": True,
    }


def attempt_context(
    before: dict[str, Any], attempt_id: str, thread_id: str
) -> dict[str, Any]:
    """Rebuild the context window of one tool-using attempt."""
    attempt = before["attempts"][attempt_id]
    work = graph_module.build_worker_input(before, attempt, thread_id)
    collector = tools.Collector(attempt.id, attempt.task_id)
    return {
        "who": f"{work.task.role} researcher (Claude Agent SDK tool loop)",
        "model": work.model,
        "system": worker.system_prompt(work),
        "user": worker.user_prompt(work, collector),
        "tools": list(tools.TOOL_NAMES),
        "max_turns": work.allowance.turns,
        "schema": worker.TaskOutput.model_json_schema(),
        "reconstructed": True,
    }


def context_for(
    node: str,
    update: dict[str, Any],
    before: dict[str, Any],
    thread_id: str,
    limits: records.Limits,
) -> dict[str, Any]:
    """The context window of any completed node."""
    if node in state_module.SINGLE_CALL_NODES:
        if graph_module.running_reservation(before, node) is None:
            return {"who": "skipped: no reservation (budget)", "model": None}
        return role_context(node, before, limits)
    if node == "run_task":
        results = update.get("task_results", [])
        if results and results[0].attempt_id in before.get("attempts", {}):
            return attempt_context(before, results[0].attempt_id, thread_id)
    return {"who": DETERMINISTIC, "model": None}


def node_event(
    node: str,
    update: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    thread_id: str,
    limits: records.Limits,
) -> dict[str, Any]:
    """Build the ``node`` event the page renders for one completed node."""
    ledger = budget.ledger(after)
    return {
        "type": "node",
        "node": node,
        "attempt_id": (
            update["task_results"][0].attempt_id
            if node == "run_task" and update.get("task_results")
            else None
        ),
        "update": encode(update),
        "state": encode(after),
        "trace": trace.render_update(node, update, after),
        "budget": {
            **dataclasses.asdict(ledger),
            "limits": limits.model_dump(),
        },
        "context": context_for(node, update, before, thread_id, limits),
    }


async def replay_industry(
    graph: CompiledStateGraph, thread_id: str, limits: records.Limits
) -> dict[str, Any]:
    """Rebuild a Phase 10 thread's events from its checkpoints."""
    config = persist.thread_config(thread_id)
    history = [s async for s in graph.aget_state_history(config)]
    history.reverse()
    events: list[dict[str, Any]] = []
    for earlier, later in zip(history, history[1:]):
        if not earlier.next or earlier.next[0] == "__start__":
            continue
        update = derive_update(earlier.values, later.values)
        nodes = list(earlier.next)
        if nodes[0] == "run_task":
            for result in update.get("task_results", []):
                events.append(
                    node_event(
                        "run_task",
                        {"task_results": [result]},
                        earlier.values,
                        later.values,
                        thread_id,
                        limits,
                    )
                )
            continue
        events.append(
            node_event(
                nodes[0],
                update,
                earlier.values,
                later.values,
                thread_id,
                limits,
            )
        )
    last = history[-1] if history else None
    if last is not None and last.next:
        events.append({"type": "pending", "node": last.next[0]})
    meta = last.values.get("meta") if last else None
    return {
        "thread_id": thread_id,
        "version": state_module.WORKFLOW_VERSION,
        "question": last.values.get("question", "") if last else "",
        "completed": bool(last) and not last.next,
        "report_status": meta.report_status if meta else None,
        "report_path": meta.report_path if meta else None,
        "events": events,
    }


LEGACY_NODE_BY_KEY = (
    ("verification", "verify"),
    ("synthesis", "finish"),
    ("evidence_sufficient", "evaluate"),
    ("research_round", "research"),
    ("research_plan", "plan"),
)


def legacy_node(update: dict[str, Any]) -> str | None:
    """Name the Phase 6-9 node from the keys its checkpoint changed."""
    for key, node in LEGACY_NODE_BY_KEY:
        if key in update:
            return node
    return None


async def replay_legacy(checkpointer: Any, thread_id: str) -> dict[str, Any]:
    """Read-only replay of a Phase 6-9 thread: node, update, state.

    Rebuilt from the checkpoints' channel values alone (the saver
    records no per-node writes): the node is named from the keys that
    changed between consecutive checkpoints. No legacy graph code runs
    and no context window is reconstructed.
    """
    config = persist.thread_config(thread_id)
    saved = [item async for item in checkpointer.alist(config)]
    saved.reverse()
    if not saved:
        raise LookupError(f"No workflow found for thread {thread_id!r}.")
    events: list[dict[str, Any]] = []
    previous: dict[str, Any] = {}
    for item in saved:
        values = {
            k: v
            for k, v in item.checkpoint.get("channel_values", {}).items()
            if not k.startswith("branch:") and k != "__start__"
        }
        update = {k: v for k, v in values.items() if previous.get(k) != v}
        node = legacy_node(update)
        if node is not None:
            events.append(
                {
                    "type": "node",
                    "node": node,
                    "legacy": True,
                    "update": encode(update),
                    "state": encode(values),
                    "trace": [f"{node.upper()}: legacy checkpoint"],
                    "context": {
                        "who": "legacy thread: context window not "
                        "reconstructed",
                        "model": None,
                    },
                }
            )
        previous = values
    return {
        "thread_id": thread_id,
        "version": "legacy",
        "question": previous.get("question", ""),
        "completed": bool(previous.get("final_answer")),
        "events": events,
    }


async def run(
    graph: CompiledStateGraph,
    runtime: budget.Runtime,
    question: str,
    thread_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Run a question on a new thread and yield events as they happen.

    Streams ``updates`` (one per completed node or task attempt),
    ``values`` (the merged state, which closes the superstep's events)
    and ``custom`` (each attempt's tool loop, with ``attempt_id``).
    """
    yield {"type": "thread", "thread_id": thread_id, "question": question}
    before: dict[str, Any] = {}
    pending: list[tuple[str, dict[str, Any]]] = []
    runtime.begin(thread_id)
    async for mode, chunk in graph.astream(
        graph_module.initial_state(question, runtime.limits),
        persist.thread_config(thread_id),
        stream_mode=["updates", "values", "custom"],
        durability="sync",
    ):
        if mode == "custom":
            yield {"type": chunk.get("event", "custom"), **chunk}
        elif mode == "updates":
            node, update = next(iter(chunk.items()))
            pending.append((node, update or {}))
        elif not pending:
            before = chunk
        else:
            for node, update in pending:
                yield node_event(
                    node, update, before, chunk, thread_id, runtime.limits
                )
            pending = []
            before = chunk
    yield {"type": "end"}


def sse(event: dict[str, Any]) -> str:
    """Format one event as a server-sent-events message."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def page(_: requests.Request) -> responses.Response:
    """Serve the studio page."""
    return responses.HTMLResponse(PAGE.read_text(encoding="utf-8"))


async def list_threads(request: requests.Request) -> responses.Response:
    """List every recorded thread, newest first, with its version."""
    checkpointer = request.app.state.checkpointer
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    async for saved in checkpointer.alist(None):
        thread_id = saved.config["configurable"]["thread_id"]
        stamp = saved.checkpoint["ts"]
        if thread_id not in latest or stamp > latest[thread_id][0]:
            latest[thread_id] = (
                stamp,
                saved.checkpoint.get("channel_values", {}),
            )
    threads = []
    for thread_id, (stamp, values) in sorted(
        latest.items(), key=lambda item: item[1][0], reverse=True
    ):
        meta = values.get("meta")
        version = getattr(meta, "workflow_version", None) or "legacy"
        if version == "legacy":
            completed = bool(values.get("final_answer"))
        else:
            completed = meta.execution_status == "completed"
        threads.append(
            {
                "thread_id": thread_id,
                "version": version,
                "question": values.get("question", ""),
                "completed": completed,
                "updated": stamp,
            }
        )
    return responses.JSONResponse(threads)


async def get_thread(request: requests.Request) -> responses.Response:
    """Replay one recorded thread, industry or legacy."""
    thread_id = request.path_params["thread_id"]
    graph = request.app.state.graph
    checkpointer = request.app.state.checkpointer
    try:
        snapshot = await persist.load_state(graph, thread_id)
    except LookupError as error:
        return responses.JSONResponse({"error": str(error)}, status_code=404)
    if persist.thread_version(snapshot) is None:
        payload = await replay_legacy(checkpointer, thread_id)
    else:
        payload = await replay_industry(
            graph, thread_id, snapshot.values["meta"].limits
        )
    return responses.JSONResponse(payload)


async def run_question(request: requests.Request) -> responses.Response:
    """Start a live run and stream its events; one run at a time."""
    question = request.query_params.get("question", "").strip()
    lock: asyncio.Lock = request.app.state.lock
    refusal = None
    if not question:
        refusal = "A question is required."
    elif lock.locked():
        refusal = "A run is already in progress; wait for it to finish."
    else:
        try:
            web.api_key()
        except RuntimeError as error:
            refusal = str(error)

    async def events() -> AsyncIterator[str]:
        if refusal is not None:
            yield sse({"type": "error", "message": refusal})
            return
        async with lock:
            thread_id = persist.new_thread_id()
            try:
                async for event in run(
                    request.app.state.graph,
                    request.app.state.runtime,
                    question,
                    thread_id,
                ):
                    yield sse(event)
            except Exception as error:  # pylint: disable=broad-exception-caught
                yield sse(
                    {
                        "type": "error",
                        "message": f"{type(error).__name__}: {error}",
                        "thread_id": thread_id,
                    }
                )

    return responses.StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@contextlib.asynccontextmanager
async def lifespan(app: applications.Starlette) -> AsyncIterator[None]:
    """Open the checkpointer and compile the graph for the server's life."""
    async with persist.open_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer
        app.state.runtime = budget.Runtime()
        app.state.graph = graph_module.build_graph(
            app.state.runtime, checkpointer=checkpointer
        )
        app.state.lock = asyncio.Lock()
        yield


def build_app() -> applications.Starlette:
    """The studio application."""
    return applications.Starlette(
        routes=[
            routing.Route("/", page),
            routing.Route("/api/threads", list_threads),
            routing.Route("/api/threads/{thread_id}", get_thread),
            routing.Route("/api/run", run_question),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    """Parse the port and serve on localhost."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", maxsplit=1)[0]
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Workflow Studio: http://127.0.0.1:{args.port}")
    uvicorn.run(
        build_app(), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
