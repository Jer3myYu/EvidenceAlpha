"""Phase 6 workflow tests: routing, accumulation, and the finish pieces.

No model calls: the graph tests pass fake nodes to ``build_graph``; the
pure functions are tested directly.
"""

import asyncio
from typing import Any

from langgraph.graph import END, START

from research import agent
from research import evaluate
from research import plan
from research import synthesize
from research import workflow

PLAN = plan.ResearchPlan(
    use_tot=False, candidates=[], selected="", reason="One clear path."
)
CHOSEN = plan.Candidate("B", "Technology stack", "strong", "medium", "strong")
TOT_PLAN = plan.ResearchPlan(
    use_tot=True, candidates=[CHOSEN], selected="B", reason="Best fit."
)
ROUNDS = [
    (["[D1] a.txt\nAcme makes arms.", "Ingested 3 chunks."], "answer 1"),
    (["[W1] Site - https://x.example\nSnippet."], "answer 2"),
    (["never used"], "answer 3"),
]


def fake_nodes(verdicts: list[bool]):
    """Build fake nodes that record calls and the state each one saw."""
    calls: list[str] = []
    seen: dict[str, dict[str, Any]] = {}  # last state each node saw
    pending = list(verdicts)

    async def fake_plan(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("plan")
        seen["plan"] = dict(state)
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("research")
        seen["research"] = dict(state)
        completed = state.get("research_round", 0)
        observations, answer = ROUNDS[completed]
        return {
            "evidence": observations,
            "answers": [answer],
            "research_round": completed + 1,
        }

    async def fake_evaluate(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("evaluate")
        seen["evaluate"] = dict(state)
        sufficient = pending.pop(0)
        completed = state["research_round"]
        gaps = [] if sufficient else [f"gap after round {completed}"]
        return {"evidence_sufficient": sufficient, "evidence_gaps": gaps}

    async def fake_finish(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("finish")
        seen["finish"] = dict(state)
        return {"final_answer": "final"}

    graph = workflow.build_graph(
        plan=fake_plan,
        research=fake_research,
        evaluate=fake_evaluate,
        finish=fake_finish,
    )
    return graph, calls, seen


def run(graph) -> workflow.ResearchState:
    return asyncio.run(graph.ainvoke({"question": "Where is Acme based?"}))


def test_sufficient_after_round_one_goes_straight_to_finish():
    graph, calls, seen = fake_nodes([True])

    state = run(graph)

    assert calls == ["plan", "research", "evaluate", "finish"]
    assert state["research_round"] == 1
    assert state["evidence"] == ROUNDS[0][0]
    assert state["answers"] == ["answer 1"]
    assert state["evidence_sufficient"] is True
    assert state["final_answer"] == "final"
    assert seen["finish"]["answers"] == ["answer 1"]


def test_insufficient_then_sufficient_runs_a_second_round_and_accumulates():
    graph, calls, seen = fake_nodes([False, True])

    state = run(graph)

    assert calls == [
        "plan",
        "research",
        "evaluate",
        "research",
        "evaluate",
        "finish",
    ]
    assert state["research_round"] == 2
    assert state["evidence"] == ROUNDS[0][0] + ROUNDS[1][0]
    assert state["answers"] == ["answer 1", "answer 2"]
    # The follow-up round saw round one's evidence and the gaps.
    assert seen["research"]["evidence"] == ROUNDS[0][0]
    assert seen["research"]["evidence_gaps"] == ["gap after round 1"]
    # The second evaluation saw everything, and finish saw both answers.
    assert seen["evaluate"]["evidence"] == ROUNDS[0][0] + ROUNDS[1][0]
    assert seen["finish"]["answers"] == ["answer 1", "answer 2"]
    assert state["evidence_sufficient"] is True


def test_insufficient_twice_stops_after_the_second_round():
    graph, calls, seen = fake_nodes([False, False])

    state = run(graph)

    assert calls.count("research") == 2
    assert calls[-3:] == ["research", "evaluate", "finish"]
    assert state["research_round"] == 2
    assert state["evidence_sufficient"] is False
    assert state["evidence_gaps"] == ["gap after round 2"]
    assert seen["finish"]["evidence"] == ROUNDS[0][0] + ROUNDS[1][0]


def test_router_never_allows_a_third_round():
    assert (
        workflow.route_after_evaluate(
            {"evidence_sufficient": True, "research_round": 1}
        )
        == "finish"
    )
    assert (
        workflow.route_after_evaluate(
            {"evidence_sufficient": False, "research_round": 1}
        )
        == "research"
    )
    assert (
        workflow.route_after_evaluate(
            {"evidence_sufficient": False, "research_round": 2}
        )
        == "finish"
    )
    assert (
        workflow.route_after_evaluate(
            {"evidence_sufficient": False, "research_round": 3}
        )
        == "finish"
    )


def test_graph_topology_has_the_evaluate_loop():
    edges = {
        (edge.source, edge.target)
        for edge in workflow.build_graph().get_graph().edges
    }

    assert edges == {
        (START, "plan"),
        ("plan", "research"),
        ("research", "evaluate"),
        ("evaluate", "finish"),
        ("evaluate", "research"),
        ("finish", END),
    }


def test_format_unresolved_gaps_numbers_and_normalises_only():
    assert workflow.format_unresolved_gaps([]) == ""

    block = workflow.format_unresolved_gaps(
        ["  No   source\n gives the 2025 revenue. ", "No IPO date is stated."]
    )

    assert block == (
        "Unresolved evidence gaps:\n"
        "1. No source gives the 2025 revenue.\n"
        "2. No IPO date is stated."
    )


def test_followup_prompt_carries_question_approach_evidence_and_gaps():
    prompt = agent.followup_prompt(
        "Where is Acme based?", TOT_PLAN, ROUNDS[0][0], ["gap one", "gap two"]
    )

    assert prompt.startswith("Where is Acme based?")
    assert "Selected research approach (B): Technology stack" in prompt
    assert prompt.index("Evidence collected so far:") < prompt.index(
        ROUNDS[0][0][0]
    )
    assert prompt.index(ROUNDS[0][0][0]) < prompt.index(ROUNDS[0][0][1])
    assert "Unresolved evidence gaps:\n1. gap one\n2. gap two" in prompt
    assert prompt.rstrip().endswith("already supports.")


def test_evaluator_prompt_lays_out_question_plan_answer_and_observations():
    prompt = evaluate.build_prompt(
        "Where is Acme based?", TOT_PLAN, "answer 1", ROUNDS[0][0]
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
    assert "answer 1" in prompt
    assert prompt.index(ROUNDS[0][0][0]) < prompt.index(ROUNDS[0][0][1])
    assert "--- observation 2 ---" in prompt

    plain = evaluate.build_prompt("Where is Acme based?", PLAN, "answer 1", [])
    assert "none: single-path question" in plain
    assert "none: no tool was called" in plain


def test_synthesis_prompt_labels_rounds_and_keeps_observations_verbatim():
    prompt = synthesize.build_prompt(
        "Where is Acme based?",
        PLAN,
        ["answer 1", "answer 2"],
        ROUNDS[0][0] + ROUNDS[1][0],
    )

    headings = [
        "Question:",
        "Research plan:",
        "Round answers (context, not evidence):",
        "Tool observations (evidence):",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "--- round 1 answer ---\nanswer 1" in prompt
    assert "--- round 2 answer ---\nanswer 2" in prompt
    assert prompt.index("--- observation 3 ---") > prompt.index(
        "--- observation 2 ---"
    )
    assert ROUNDS[1][0][0] in prompt


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
