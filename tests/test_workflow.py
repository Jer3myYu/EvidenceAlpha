"""Phase 6.1 tests: the linear graph moves state plan -> research -> finish.

No model calls: the plan and research nodes are fakes passed to
``build_graph``; the finish node is the real one.
"""

import asyncio
from typing import Any

from langgraph.graph import END, START

from research import plan
from research import workflow

PLAN = plan.ResearchPlan(
    use_tot=False, candidates=[], selected="", reason="One clear path."
)
OBSERVATIONS = [
    "[D1] source: a.txt (distance 0.1000)\nAcme makes arms in Pittsburgh.",
    "Ingested 3 chunks from https://x.example/p into the local collection.",
]
ANSWER = "Acme is based in Pittsburgh [D1]."


def test_linear_graph_passes_plan_evidence_and_answer_through():
    calls: list[str] = []
    seen: dict[str, Any] = {}

    async def fake_plan(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("plan")
        seen["plan"] = dict(state)
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("research")
        seen["research"] = dict(state)
        return {"answer": ANSWER, "evidence": OBSERVATIONS}

    graph = workflow.build_graph(plan=fake_plan, research=fake_research)
    state = asyncio.run(graph.ainvoke({"question": "Where is Acme based?"}))

    assert calls == ["plan", "research"]
    assert seen["plan"] == {"question": "Where is Acme based?"}
    assert seen["research"]["research_plan"] is PLAN
    assert state["evidence"] == OBSERVATIONS
    assert state["answer"] == ANSWER
    assert state["final_answer"] == ANSWER


def test_graph_topology_is_linear():
    edges = {
        (edge.source, edge.target)
        for edge in workflow.build_graph().get_graph().edges
    }

    assert edges == {
        (START, "plan"),
        ("plan", "research"),
        ("research", "finish"),
        ("finish", END),
    }
