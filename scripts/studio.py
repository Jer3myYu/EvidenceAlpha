"""Workflow Studio: a local page that shows the research workflow at work.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/studio.py              # http://127.0.0.1:8765
    .venv/bin/python scripts/studio.py --port 9000

The page (``scripts/studio.html``) draws the architecture and the
graph, then drives the graph two ways. *Live*: a question starts a real
run on a new thread, checkpointed exactly like ``scripts/workflow.py``,
and every completed node, plus each tool call inside the research
node, streams to the page as it happens. *Replay*: a recorded thread in
``data/workflow.db`` is stepped through checkpoint by checkpoint with
no model call.

Both produce the same event sequence. A ``node`` event carries what
the node returned, the merged state after it, the trace lines the CLI
would print, the next node, and the node's *context window*: the
system and user text its model call received, rebuilt from the state
before the node with the same prompt builders and the CrewAI framing
that ``tests/test_crew.py`` pins. Nothing here changes the graph.
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

from research import agent
from research import crew
from research import evaluate
from research import persist
from research import synthesize
from research import trace
from research import verify
from research import web
from research import workflow

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

# The expected-output sentence each role function passes to run_task.
EXPECTED = {
    "plan": "The structured research plan.",
    "evaluate": "The structured evaluation.",
    "finish": "The answer as plain prose, citing [S#] labels only.",
    "verify": "The structured verification.",
}
ROLES = {
    "plan": crew.PLANNER,
    "evaluate": crew.EVALUATOR,
    "finish": crew.REPORTER,
    "verify": crew.VERIFIER,
}
TOOLS = ["search_documents", "search_web", "ingest_url"]


def encode(value: Any) -> Any:
    """Turn state values into JSON-ready data: dataclasses and models too."""
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
    node: str, before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild what ``node`` returned from the states around it.

    Replay only has checkpoints, so the node's return value is read back
    from the difference: accumulated lists give their new items, other
    keys the value after the node.

    Args:
      node: The node that ran between the two states.
      before: The state the node saw.
      after: The state after LangGraph merged the node's return value.

    Returns:
      The update in the shape the node function returns it.
    """
    if node == "plan":
        return {"research_plan": after["research_plan"]}
    if node == "research":
        old_evidence = len(before.get("evidence", []))
        old_answers = len(before.get("answers", []))
        return {
            "evidence": after["evidence"][old_evidence:],
            "sources": after["sources"],
            "answers": after["answers"][old_answers:],
            "research_round": after["research_round"],
        }
    if node == "evaluate":
        return {
            "evidence_sufficient": after["evidence_sufficient"],
            "evidence_gaps": after["evidence_gaps"],
        }
    if node == "finish":
        return {
            "synthesis": after["synthesis"],
            "final_answer": after["final_answer"],
            "revision_round": after["revision_round"],
        }
    if node == "verify":
        update = {
            "citation_issues": after["citation_issues"],
            "verification": after["verification"],
        }
        if after["final_answer"] != before.get("final_answer"):
            update["final_answer"] = after["final_answer"]
        return update
    raise ValueError(f"Unknown node {node!r}.")


def next_node(node: str, after: dict[str, Any]) -> str:
    """Name the node that follows ``node``, or ``"end"``, from the state."""
    if node == "plan":
        return "research"
    if node == "research":
        return "evaluate"
    if node == "evaluate":
        return workflow.route_after_evaluate(after)
    if node == "finish":
        return "verify"
    if node == "verify":
        route = workflow.route_after_verify(after)
        return "finish" if route == "revise" else "end"
    raise ValueError(f"Unknown node {node!r}.")


def role_context(node: str, before: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the context window of the model call ``node`` makes.

    Every call's text is a pure function of the state the node saw:
    the role's system prompt inside CrewAI's framing, and the stage's
    prompt builder inside the task framing. The research node's context
    is the agent's system prompt, its tools, and the round's message.

    Args:
      node: The node about to run.
      before: The state it sees.

    Returns:
      ``who`` (what executes the call), ``model``, ``system``, ``user``,
      and for the crew roles ``schema`` (the structured output model's
      JSON schema, or ``None`` for plain text); for the research node
      ``tools`` and ``max_turns`` instead.
    """
    question = before["question"]
    if node == "research":
        completed = before.get("research_round", 0)
        if completed == 0:
            prompt = agent.research_prompt(question, before["research_plan"])
        else:
            prompt = agent.followup_prompt(
                question,
                before["research_plan"],
                before["evidence"],
                before["evidence_gaps"],
            )
        return {
            "who": "Research Agent (Claude Agent SDK tool loop)",
            "model": agent.MODEL,
            "system": agent.SYSTEM_PROMPT,
            "user": prompt,
            "tools": TOOLS,
            "max_turns": agent.MAX_TURNS,
        }
    if node == "plan":
        description = question
    elif node == "evaluate":
        description = evaluate.build_prompt(
            question,
            before["research_plan"],
            before["answers"][-1],
            before["evidence"],
        )
    elif node == "finish":
        verification = before.get("verification")
        draft = findings = None
        if verification is not None:
            draft = before["synthesis"]
            findings = verify.format_verification_notes(
                before["citation_issues"], verification
            )
        description = synthesize.build_prompt(
            question,
            before["research_plan"],
            before["answers"],
            before["evidence"],
            draft,
            findings,
        )
    elif node == "verify":
        description = verify.build_prompt(
            question, before["synthesis"], before["evidence"], before["sources"]
        )
    else:
        raise ValueError(f"Unknown node {node!r}.")
    role = ROLES[node]
    return {
        "who": f"{role.name} (CrewAI crew of one, via ClaudeLLM)",
        "model": crew.MODEL,
        "system": SYSTEM_FRAME.format(
            name=role.name, backstory=role.backstory, goal=role.goal
        ),
        "user": USER_FRAME.format(
            description=description, expected=EXPECTED[node]
        ),
        "schema": (role.output.model_json_schema() if role.output else None),
    }


def node_event(
    node: str,
    update: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    following: str,
) -> dict[str, Any]:
    """Build the ``node`` event the page renders for one completed node."""
    lines = trace.render_update(
        node,
        update,
        after.get("research_round", 0),
        after.get("revision_round", 0),
    )
    return {
        "type": "node",
        "node": node,
        "update": encode(update),
        "state": encode(after),
        "trace": lines,
        "next": following,
        "context": role_context(node, before),
    }


async def replay(graph: CompiledStateGraph, thread_id: str) -> dict[str, Any]:
    """Rebuild a recorded thread's events from its checkpoints.

    Args:
      graph: The graph compiled with the checkpointer holding the thread.
      thread_id: The thread to replay.

    Returns:
      ``thread_id``, ``question``, ``completed``, and ``events``: one
      ``node`` event per completed node in run order, then a ``pending``
      event naming the unfinished node when the run was interrupted.

    Raises:
      LookupError: If the thread has no checkpoint.
    """
    config = persist.thread_config(thread_id)
    history = [snapshot async for snapshot in graph.aget_state_history(config)]
    if not history:
        raise LookupError(f"No workflow found for thread {thread_id!r}.")
    history.reverse()  # Oldest first.
    events = []
    for earlier, later in zip(history, history[1:]):
        node = earlier.next[0]
        if node == "__start__":
            continue
        update = derive_update(node, earlier.values, later.values)
        following = later.next[0] if later.next else "end"
        events.append(
            node_event(node, update, earlier.values, later.values, following)
        )
    last = history[-1]
    if last.next:
        events.append({"type": "pending", "node": last.next[0]})
    return {
        "thread_id": thread_id,
        "question": last.values.get("question", ""),
        "completed": not last.next,
        "events": events,
    }


async def run(
    graph: CompiledStateGraph, question: str, thread_id: str
) -> AsyncIterator[dict[str, Any]]:
    """Run a question on a new thread and yield events as they happen.

    Streams ``updates`` (the node's return value), ``values`` (the merged
    state, which closes the node event) and ``custom`` (the research
    node's tool loop, forwarded as ``tool_use``, ``tool_result``, and
    ``assistant_text`` events).
    """
    yield {"type": "thread", "thread_id": thread_id, "question": question}
    before: dict[str, Any] = {}
    pending: tuple[str, dict[str, Any]] | None = None
    async for mode, chunk in graph.astream(
        {"question": question},
        persist.thread_config(thread_id),
        stream_mode=["updates", "values", "custom"],
        durability="sync",
    ):
        if mode == "custom":
            yield {"type": chunk["event"], **chunk}
        elif mode == "updates":
            node, update = next(iter(chunk.items()))
            pending = (node, update)
        elif pending is None:
            before = chunk  # The input step: the question alone.
        else:
            node, update = pending
            pending = None
            yield node_event(
                node, update, before, chunk, next_node(node, chunk)
            )
            before = chunk
    yield {"type": "end"}


def sse(event: dict[str, Any]) -> str:
    """Format one event as a server-sent-events message."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def page(_: requests.Request) -> responses.Response:
    """Serve the studio page."""
    return responses.HTMLResponse(PAGE.read_text(encoding="utf-8"))


async def list_threads(request: requests.Request) -> responses.Response:
    """List every recorded thread, newest first."""
    graph = request.app.state.graph
    checkpointer = request.app.state.checkpointer
    latest: dict[str, str] = {}
    async for saved in checkpointer.alist(None):
        thread_id = saved.config["configurable"]["thread_id"]
        latest[thread_id] = max(
            latest.get(thread_id, ""), saved.checkpoint["ts"]
        )
    threads = []
    for thread_id, stamp in sorted(
        latest.items(), key=lambda item: item[1], reverse=True
    ):
        snapshot = await graph.aget_state(persist.thread_config(thread_id))
        threads.append(
            {
                "thread_id": thread_id,
                "question": snapshot.values.get("question", ""),
                "completed": not snapshot.next,
                "updated": stamp,
            }
        )
    return responses.JSONResponse(threads)


async def get_thread(request: requests.Request) -> responses.Response:
    """Replay one recorded thread."""
    try:
        payload = await replay(
            request.app.state.graph, request.path_params["thread_id"]
        )
    except LookupError as error:
        return responses.JSONResponse({"error": str(error)}, status_code=404)
    return responses.JSONResponse(payload)


async def run_question(request: requests.Request) -> responses.Response:
    """Start a live run and stream its events; one run at a time.

    Every outcome is a stream, so the page shows a refusal (no question,
    no Tavily key, a run already in progress) as an error event rather
    than a dropped connection.
    """
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
                    request.app.state.graph, question, thread_id
                ):
                    yield sse(event)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # The page must learn why the run stopped; the thread is
                # checkpointed and resumable from the CLI.
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
        app.state.graph = workflow.build_graph(checkpointer=checkpointer)
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
