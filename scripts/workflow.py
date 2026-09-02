"""Run the LangGraph research workflow on a question and show its state.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/workflow.py "What risks does Acme disclose?"

Compare with ``scripts/agent.py``, which runs the same planner and agent
without the graph and prints each tool call as it happens. Here the
graph streams: a short trace line per completed node while it runs,
then the final state in full.
"""

import asyncio
import sys

from research import trace
from research import web
from research import workflow


def show(title: str, body: str) -> None:
    """Print one stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


async def main() -> None:
    """Stream the graph, trace each node, then print the final state."""
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/workflow.py "<question>"')
    try:
        web.api_key()
    except RuntimeError as error:
        sys.exit(str(error))
    question = sys.argv[1]
    show("USER QUESTION", question)

    show("TRACE", "")
    state: workflow.ResearchState = {}
    research_round = 0
    async for mode, chunk in workflow.build_graph().astream(
        {"question": question}, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            state = chunk  # The last one is the final, merged state.
            continue
        for node, update in chunk.items():
            if node == "research":
                research_round = update["research_round"]
            for line in trace.render_update(node, update, research_round):
                print(line)

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
    sources = []
    for record in state["sources"].values():
        seen_via = ", ".join(record.seen_via)
        location = record.canonical_url or record.local_document_id
        sources.append(
            f"{record.source_id}  {record.title}  {location}  via {seen_via}"
        )
    show("SOURCES", "\n".join(sources) or "none (no source seen)")


if __name__ == "__main__":
    asyncio.run(main())
