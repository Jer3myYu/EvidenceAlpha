"""Phase 6.6 tests: the trace renders completed node updates faithfully."""

import asyncio
from typing import Any

from research import plan
from research import trace
from research import workflow

PLAN = plan.ResearchPlan(
    use_tot=False, candidates=[], selected="", reason="One clear path."
)
TOT_PLAN = plan.ResearchPlan(
    use_tot=True,
    candidates=[
        plan.Candidate("A", "Value chain", "strong", "strong", "strong")
    ],
    selected="A",
    reason="Best fit.",
)


def traced_run(verdicts: list[bool]) -> tuple[list[str], list[str]]:
    """Stream the graph with fakes; return (node sequence, trace lines)."""
    pending = list(verdicts)

    async def fake_plan(unused_state: workflow.ResearchState) -> dict[str, Any]:
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        completed = state.get("research_round", 0)
        return {
            "evidence": [
                f"[S1] source: a.txt (distance 0.1000)\n{completed}",
                "x",
            ],
            "sources": {},
            "answers": [f"answer {completed + 1}"],
            "research_round": completed + 1,
        }

    async def fake_evaluate(state: workflow.ResearchState) -> dict[str, Any]:
        sufficient = pending.pop(0)
        completed = state["research_round"]
        gaps = [] if sufficient else [f"gap after round {completed}"]
        return {"evidence_sufficient": sufficient, "evidence_gaps": gaps}

    async def fake_finish(
        unused_state: workflow.ResearchState,
    ) -> dict[str, Any]:
        return {"final_answer": "final"}

    graph = workflow.build_graph(
        plan=fake_plan,
        research=fake_research,
        evaluate=fake_evaluate,
        finish=fake_finish,
    )

    async def collect() -> tuple[list[str], list[str]]:
        nodes: list[str] = []
        lines: list[str] = []
        research_round = 0
        async for chunk in graph.astream(
            {"question": "q"}, stream_mode="updates"
        ):
            for node, update in chunk.items():
                nodes.append(node)
                if node == "research":
                    research_round = update["research_round"]
                lines.extend(trace.render_update(node, update, research_round))
        return nodes, lines

    return asyncio.run(collect())


def test_one_round_run_traces_plan_research_verdict_route_and_finish():
    nodes, lines = traced_run([True])

    assert nodes == ["plan", "research", "evaluate", "finish"]
    assert lines == [
        "PLAN: no tree-of-thought",
        "RESEARCH ROUND 1",
        "RESEARCH ROUND 1: 2 observations",
        "EVALUATE: sufficient",
        "ROUTE: finish",
        "FINISH",
    ]


def test_two_round_run_traces_the_gap_the_route_and_the_second_round():
    nodes, lines = traced_run([False, True])

    assert nodes == [
        "plan",
        "research",
        "evaluate",
        "research",
        "evaluate",
        "finish",
    ]
    assert lines == [
        "PLAN: no tree-of-thought",
        "RESEARCH ROUND 1",
        "RESEARCH ROUND 1: 2 observations",
        "EVALUATE: insufficient",
        "GAPS:",
        "- gap after round 1",
        "ROUTE: research",
        "RESEARCH ROUND 2",
        "RESEARCH ROUND 2: 2 observations",
        "EVALUATE: sufficient",
        "ROUTE: finish",
        "FINISH",
    ]


def test_verdict_gaps_route_and_plan_lines_render_exactly():
    insufficient = trace.render_update(
        "evaluate",
        {"evidence_sufficient": False, "evidence_gaps": ["a", "b"]},
        1,
    )
    sufficient = trace.render_update(
        "evaluate", {"evidence_sufficient": True, "evidence_gaps": []}, 1
    )

    assert insufficient == [
        "EVALUATE: insufficient",
        "GAPS:",
        "- a",
        "- b",
        "ROUTE: research",
        "RESEARCH ROUND 2",
    ]
    assert sufficient == ["EVALUATE: sufficient", "ROUTE: finish"]
    assert trace.render_update("plan", {"research_plan": TOT_PLAN}, 0) == [
        "PLAN: approach A selected",
        "RESEARCH ROUND 1",
    ]
    assert trace.render_update("finish", {"final_answer": "x"}, 2) == ["FINISH"]


def test_no_third_round_is_ever_traced():
    nodes, lines = traced_run([False, False])

    assert nodes.count("research") == 2
    assert lines[-3:] == ["- gap after round 2", "ROUTE: finish", "FINISH"]
    assert "RESEARCH ROUND 3" not in lines
    assert lines.count("ROUTE: research") == 1
