"""Run the LangGraph research workflow on a question and show its state.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/workflow.py "What risks does Acme disclose?"
    .venv/bin/python scripts/workflow.py --resume 3f9c2a1b

Compare with ``scripts/agent.py``, which runs the same planner and agent
without the graph and prints each tool call as it happens. Here the
graph streams: a short trace line per completed node while it runs,
then the final state in full.

Every run is checkpointed to ``data/workflow.db`` under a thread id,
printed first. A run that was interrupted resumes with ``--resume`` at
the node that did not finish; a completed run reopens with the same
flag and prints its state without calling any model. One thread id is
one question: a new question always starts a new thread.
"""

import argparse
import asyncio
import sys

from research import persist
from research import trace
from research import web
from research import workflow


def show(title: str, body: str) -> None:
    """Print one stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


def parse_args() -> argparse.Namespace:
    """A question for a new thread, or ``--resume`` with an existing id."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", maxsplit=1)[0]
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("question", nargs="?", help="start a new thread")
    target.add_argument(
        "--resume", metavar="THREAD_ID", help="resume or reopen a thread"
    )
    return parser.parse_args()


async def stream(graph, payload, thread_id: str, research_round: int):
    """Stream the graph on a thread, trace each node, return the state."""
    state: workflow.ResearchState = {}
    config = persist.thread_config(thread_id)
    try:
        async for mode, chunk in graph.astream(
            payload,
            config,
            stream_mode=["updates", "values"],
            durability="sync",  # Checkpoint before the next node starts.
        ):
            if mode == "values":
                state = chunk  # The last one is the final, merged state.
                continue
            for node, update in chunk.items():
                if node == "research":
                    research_round = update["research_round"]
                for line in trace.render_update(node, update, research_round):
                    print(line)
    except asyncio.CancelledError:
        print(
            f"\nInterrupted. The last completed node is saved; continue "
            f"with:\n  scripts/workflow.py --resume {thread_id}"
        )
        raise
    return state


async def main() -> None:
    """Start, resume, or reopen a thread, then print the final state."""
    args = parse_args()
    async with persist.open_checkpointer() as checkpointer:
        graph = workflow.build_graph(checkpointer=checkpointer)
        if args.resume is None:
            thread_id = persist.new_thread_id()
            show(
                "THREAD", f"{thread_id}  (--resume {thread_id} if interrupted)"
            )
            show("USER QUESTION", args.question)
            snapshot = None
        else:
            thread_id = args.resume
            try:
                snapshot = await persist.load_state(graph, thread_id)
            except LookupError as error:
                sys.exit(str(error))
            show("THREAD", thread_id)
            show("USER QUESTION", snapshot.values["question"])

        if snapshot is not None and not snapshot.next:
            show("TRACE", "completed earlier; reopened without any model call")
            state = snapshot.values
        else:
            try:
                web.api_key()
            except RuntimeError as error:
                sys.exit(str(error))
            show("TRACE", "")
            if snapshot is None:
                payload, research_round = {"question": args.question}, 0
            else:
                pending = ", ".join(snapshot.next)
                print(f"RESUMING AT: {pending}")
                payload = None
                research_round = snapshot.values.get("research_round", 0)
            state = await stream(graph, payload, thread_id, research_round)
    show_state(state)


def show_state(state: workflow.ResearchState) -> None:
    """Print the final state, section by section."""
    plan = state["research_plan"]
    show("TREE-OF-THOUGHT TRIGGER", "yes" if plan.use_tot else "no")
    if plan.use_tot:
        show(
            "RESEARCH ALTERNATIVES",
            "\n\n".join(
                f"{c.label}. {c.approach}\n   scope: {c.scope}\n"
                f"   evidence: {c.evidence}\n   coverage: {c.coverage}"
                for c in plan.candidates
            ),
        )
        chosen = plan.chosen()
        show(
            "SELECTED APPROACH",
            f"{chosen.label}. {chosen.approach}" if chosen else plan.selected,
        )
        show("REASON", plan.reason)

    if not state["evidence"]:
        show("TOOL OBSERVATION", "none (no tool called)")
    for observation in state["evidence"]:
        show("TOOL OBSERVATION", observation)
    for number, answer in enumerate(state["answers"], start=1):
        show(f"ROUND {number} ANSWER", answer)
    verdict = "yes" if state["evidence_sufficient"] else "no"
    gaps = (
        "".join(
            f"\n{n}. {gap}" for n, gap in enumerate(state["evidence_gaps"], 1)
        )
        or " none"
    )
    show("EVIDENCE EVALUATION", f"sufficient: {verdict}\ngaps:{gaps}")
    show("RESEARCH ROUNDS", str(state["research_round"]))
    show("FINAL ANSWER", state["final_answer"])
    show("VERIFICATION", format_verification(state))
    ratings = {
        rating.source_id: rating
        for rating in state["verification"].source_ratings
    }
    sources = []
    for record in state["sources"].values():
        seen_via = ", ".join(record.seen_via)
        location = record.canonical_url or record.local_document_id
        line = f"{record.source_id}  {record.title}  {location}  via {seen_via}"
        rating = ratings.get(record.source_id)
        if rating:
            line += f"\n    quality: {rating.quality}. {rating.reason}"
        sources.append(line)
    show("SOURCES", "\n".join(sources) or "none (no source seen)")


def format_verification(state: workflow.ResearchState) -> str:
    """Render citation issues, claim checks, and conflicts."""
    verification = state["verification"]
    issues = "".join(f"\n- {issue}" for issue in state["citation_issues"])
    claims = ""
    for number, check in enumerate(verification.claims, 1):
        cited = ", ".join(check.cited_sources) or "no citation"
        claims += (
            f'\n{number}. {check.verdict} ({cited}): "{check.claim}" '
            f"{check.reason}"
        )
    conflicts = ""
    for conflict in verification.conflicts:
        labels = ", ".join(conflict.sources)
        status = (
            "disclosed" if conflict.disclosed_in_answer else "not disclosed"
        )
        conflicts += f"\n- {labels}: {conflict.description} ({status})"
    none = " none"
    return (
        f"citation issues:{issues or none}\n"
        f"claims:{claims or none}\n"
        f"conflicts:{conflicts or none}"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
