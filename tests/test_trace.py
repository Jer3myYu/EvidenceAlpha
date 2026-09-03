"""Phase 6.6 tests: the trace renders completed node updates faithfully."""

import asyncio
from typing import Any

from research import plan
from research import trace
from research import verify
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
CLEAN = verify.Verification(claims=[], conflicts=[], source_ratings=[])


def claim(verdict: str) -> verify.ClaimCheck:
    return verify.ClaimCheck(
        claim="Acme employs 520 people.",
        cited_sources=["S1"],
        verdict=verdict,
        reason="Observation 1 says 400.",
    )


def traced_run(
    verdicts: list[bool],
    verifications: list[verify.Verification] | None = None,
) -> tuple[list[str], list[str]]:
    """Stream the graph with fakes; return (node sequence, trace lines)."""
    pending = list(verdicts)
    results = list(verifications or [])

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

    async def fake_finish(state: workflow.ResearchState) -> dict[str, Any]:
        revision = 0
        if state.get("verification") is not None:
            revision = state["revision_round"] + 1
        return {
            "synthesis": "final",
            "final_answer": "final",
            "revision_round": revision,
        }

    async def fake_verify(
        unused_state: workflow.ResearchState,
    ) -> dict[str, Any]:
        verification = results.pop(0) if results else CLEAN
        return {"citation_issues": [], "verification": verification}

    graph = workflow.build_graph(
        plan=fake_plan,
        research=fake_research,
        evaluate=fake_evaluate,
        finish=fake_finish,
        verify=fake_verify,
    )

    async def collect() -> tuple[list[str], list[str]]:
        nodes: list[str] = []
        lines: list[str] = []
        research_round = revision_round = 0
        async for chunk in graph.astream(
            {"question": "q"}, stream_mode="updates"
        ):
            for node, update in chunk.items():
                nodes.append(node)
                if node == "research":
                    research_round = update["research_round"]
                if node == "finish":
                    revision_round = update["revision_round"]
                lines.extend(
                    trace.render_update(
                        node, update, research_round, revision_round
                    )
                )
        return nodes, lines

    return asyncio.run(collect())


def test_one_round_run_traces_plan_research_verdict_route_and_finish():
    nodes, lines = traced_run([True])

    assert nodes == ["plan", "research", "evaluate", "finish", "verify"]
    assert lines == [
        "PLAN: no tree-of-thought",
        "RESEARCH ROUND 1",
        "RESEARCH ROUND 1: 2 observations",
        "EVALUATE: sufficient",
        "ROUTE: finish",
        "FINISH",
        "VERIFY: 0 claims",
        "ROUTE: end",
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
        "verify",
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
        "VERIFY: 0 claims",
        "ROUTE: end",
    ]


def test_revision_is_traced_once_and_the_second_verify_ends():
    problem = verify.Verification(
        claims=[claim("unsupported")], conflicts=[], source_ratings=[]
    )
    issue = (
        '- Unsupported claim: "Acme employs 520 people." Observation 1 '
        "says 400."
    )

    nodes, lines = traced_run([True], verifications=[problem, problem])

    assert nodes == [
        "plan",
        "research",
        "evaluate",
        "finish",
        "verify",
        "finish",
        "verify",
    ]
    assert lines[-11:] == [
        "FINISH",
        "VERIFY: 1 claims: 1 unsupported",
        "ISSUES:",
        issue,
        "ROUTE: revise",
        "REVISION: 1",
        "FINISH: revision 1",
        "VERIFY: 1 claims: 1 unsupported",
        "ISSUES:",
        issue,
        "ROUTE: end",
    ]
    assert lines.count("ROUTE: revise") == 1
    assert "REVISION: 2" not in lines


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
    assert trace.render_update(
        "finish", {"final_answer": "x", "revision_round": 0}, 2
    ) == ["FINISH"]
    assert trace.render_update(
        "finish", {"final_answer": "x", "revision_round": 1}, 2
    ) == ["FINISH: revision 1"]
    mixed = verify.Verification(
        claims=[claim("supported"), claim("supported"), claim("contradicted")],
        conflicts=[
            verify.Conflict(
                sources=["S1", "S2"],
                description="Founding years differ.",
                disclosed_in_answer=False,
            )
        ],
        source_ratings=[
            verify.SourceRating(source_id="S2", quality="weak", reason="Blog.")
        ],
    )
    assert trace.render_update(
        "verify",
        {
            "citation_issues": ["[D1] is a round-local label."],
            "verification": mixed,
        },
        1,
    ) == [
        "VERIFY: 3 claims: 2 supported, 1 contradicted",
        "ISSUES:",
        "- [D1] is a round-local label.",
        '- Contradicted claim: "Acme employs 520 people." Observation 1 '
        "says 400.",
        "- Conflicting evidence not disclosed ([S1], [S2]): Founding years "
        "differ.",
        "ROUTE: revise",
        "REVISION: 1",
    ]
    assert trace.render_update(
        "verify",
        {
            "citation_issues": ["[D1] is a round-local label."],
            "verification": mixed,
        },
        1,
        revision_round=1,
    )[-1:] == ["ROUTE: end"]
    clean = verify.Verification(
        claims=[claim("supported")], conflicts=[], source_ratings=[]
    )
    assert trace.render_update(
        "verify", {"citation_issues": [], "verification": clean}, 1
    ) == ["VERIFY: 1 claims: 1 supported", "ROUTE: end"]


def test_no_third_round_is_ever_traced():
    nodes, lines = traced_run([False, False])

    assert nodes.count("research") == 2
    assert lines[-5:] == [
        "- gap after round 2",
        "ROUTE: finish",
        "FINISH",
        "VERIFY: 0 claims",
        "ROUTE: end",
    ]
    assert "RESEARCH ROUND 3" not in lines
    assert lines.count("ROUTE: research") == 1
