"""Run the LangGraph research workflow on a question and show its state.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/workflow.py "What risks does Acme disclose?"

Compare with ``scripts/agent.py``, which runs the same planner and agent
without the graph and prints each tool call as it happens. Here the
graph runs to completion first, then the final state is printed.
"""

import asyncio
import sys

from research import web
from research import workflow


def show(title: str, body: str) -> None:
    """Print one stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


async def main() -> None:
    """Run the graph once and print every field of the final state."""
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/workflow.py "<question>"')
    try:
        web.api_key()
    except RuntimeError as error:
        sys.exit(str(error))
    question = sys.argv[1]
    show("USER QUESTION", question)

    state = await workflow.build_graph().ainvoke({"question": question})

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
    verdict = "yes" if state["evidence_sufficient"] else "no"
    gaps = (
        "".join(
            f"\n{n}. {gap}" for n, gap in enumerate(state["evidence_gaps"], 1)
        )
        or " none"
    )
    show("EVIDENCE EVALUATION", f"sufficient: {verdict}\ngaps:{gaps}")
    show("FINAL ANSWER", state["final_answer"])
    sources = [
        line
        for text in state["evidence"]
        for line in text.splitlines()
        if line.startswith(("[D", "[W"))
    ]
    show("SOURCES", "\n".join(sources) or "none (no tool called)")


if __name__ == "__main__":
    asyncio.run(main())
