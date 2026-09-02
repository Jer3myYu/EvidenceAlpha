"""Phase 6 workflow tests: state moves plan -> research -> evaluate -> finish.

No model calls: the plan, research, and evaluate nodes are fakes passed
to ``build_graph``; the finish node is the real one.
"""

import asyncio
from typing import Any

from langgraph.graph import END, START

from research import evaluate
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


def test_linear_graph_passes_plan_evidence_verdict_and_answer_through():
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

    async def fake_evaluate(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("evaluate")
        seen["evaluate"] = dict(state)
        return {"evidence_sufficient": False, "evidence_gaps": ["g1"]}

    graph = workflow.build_graph(
        plan=fake_plan, research=fake_research, evaluate=fake_evaluate
    )
    state = asyncio.run(graph.ainvoke({"question": "Where is Acme based?"}))

    assert calls == ["plan", "research", "evaluate"]
    assert seen["plan"] == {"question": "Where is Acme based?"}
    assert seen["research"]["research_plan"] is PLAN
    assert seen["evaluate"]["answer"] == ANSWER
    assert seen["evaluate"]["evidence"] == OBSERVATIONS
    assert state["evidence_sufficient"] is False
    assert state["evidence_gaps"] == ["g1"]
    assert state["final_answer"] == ANSWER


def test_graph_topology_is_linear():
    edges = {
        (edge.source, edge.target)
        for edge in workflow.build_graph().get_graph().edges
    }

    assert edges == {
        (START, "plan"),
        ("plan", "research"),
        ("research", "evaluate"),
        ("evaluate", "finish"),
        ("finish", END),
    }


def test_evaluator_prompt_lays_out_question_plan_answer_and_observations():
    chosen = plan.Candidate(
        "B", "Technology stack", "strong", "medium", "strong"
    )
    tot_plan = plan.ResearchPlan(
        use_tot=True, candidates=[chosen], selected="B", reason="Best fit."
    )

    prompt = evaluate.build_prompt(
        "Where is Acme based?", tot_plan, ANSWER, OBSERVATIONS
    )

    headings = [
        "Question:",
        "Research plan:",
        "Agent answer:",
        "Tool observations:",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "(B) Technology stack" in prompt
    assert ANSWER in prompt
    assert prompt.index(OBSERVATIONS[0]) < prompt.index(OBSERVATIONS[1])
    assert "--- observation 2 ---" in prompt

    plain = evaluate.build_prompt("Where is Acme based?", PLAN, ANSWER, [])
    assert "none: single-path question" in plain
    assert "none: no tool was called" in plain


def test_evaluation_schema_uses_question_keys_not_sufficient():
    # Regression: with the key named "sufficient" the model judged a
    # well-supported "nothing found" answer as sufficient every time.
    schema = evaluate.EvidenceEvaluation.model_json_schema()

    assert set(schema["properties"]) == {
        "question_answerable_from_observations",
        "missing_evidence",
    }
    assert schema["additionalProperties"] is False

    verdict = evaluate.EvidenceEvaluation.model_validate(
        {
            "question_answerable_from_observations": False,
            "missing_evidence": ["No source gives the 2025 revenue."],
        }
    )
    assert verdict.sufficient is False
    assert verdict.gaps == ["No source gives the 2025 revenue."]
