"""Phase 6 workflow tests: routing, accumulation, finish, and verify.

No model calls: the graph tests pass fake nodes to ``build_graph``; the
pure functions are tested directly.
"""

import asyncio
from typing import Any

from langgraph.graph import END, START

from research import agent
from research import evaluate
from research import plan
from research import sources
from research import synthesize
from research import verify
from research import workflow

PLAN = plan.ResearchPlan(
    use_tot=False, candidates=[], selected="", reason="One clear path."
)
CHOSEN = plan.Candidate("B", "Technology stack", "strong", "medium", "strong")
TOT_PLAN = plan.ResearchPlan(
    use_tot=True, candidates=[CHOSEN], selected="B", reason="Best fit."
)
INGESTED = (
    "Ingested 3 chunks from https://x.example/p into the local document "
    "collection. Use search_documents to retrieve from it."
)
# Raw observations as the tools label them: round 2's [D1] is a different
# source from round 1's [D1], and its web hit is the URL round 1 ingested.
ROUNDS = [
    (
        ["[D1] source: a.txt (distance 0.1000)\nAcme makes arms.", INGESTED],
        "answer 1",
    ),
    (
        [
            "[W1] Site - https://x.example/p\nSnippet.",
            "[D1] source: b.md (distance 0.2000)\nBeta sells peas.",
        ],
        "answer 2",
    ),
    (["never used"], "answer 3"),
]
STABLE = [
    ["[S1] source: a.txt (distance 0.1000)\nAcme makes arms.", INGESTED],
    [
        "[S2] Site - https://x.example/p\nSnippet.",
        "[S3] source: b.md (distance 0.2000)\nBeta sells peas.",
    ],
]
CLEAN = verify.Verification(claims=[], conflicts=[], source_ratings=[])


def fake_nodes(
    verdicts: list[bool],
    synthesis: str = "final",
    verifications: list[verify.Verification] | None = None,
    revised: str = "revised",
):
    """Build fake nodes that record calls and the state each one saw.

    ``synthesis`` is what the fake finish writes first and ``revised``
    what it writes when asked to revise; the fake verify runs the real
    citation check on the synthesis and returns the next of
    ``verifications`` (clean by default) in place of the model call.
    """
    calls: list[str] = []
    seen: dict[str, dict[str, Any]] = {}  # last state each node saw
    pending = list(verdicts)
    results = list(verifications or [])

    async def fake_plan(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("plan")
        seen["plan"] = dict(state)
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("research")
        seen["research"] = dict(state)
        completed = state.get("research_round", 0)
        observations, answer = ROUNDS[completed]
        evidence, registry = sources.normalize_observations(
            observations, state.get("sources", {})
        )
        return {
            "evidence": evidence,
            "sources": registry,
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
        if state.get("verification") is None:
            text, revision = synthesis, 0
        else:
            text, revision = revised, state["revision_round"] + 1
        final = text
        block = workflow.format_unresolved_gaps(state["evidence_gaps"])
        if block and not state["evidence_sufficient"]:
            final = f"{text}\n\n{block}"
        return {
            "synthesis": text,
            "final_answer": final,
            "revision_round": revision,
        }

    async def fake_verify(state: workflow.ResearchState) -> dict[str, Any]:
        calls.append("verify")
        seen["verify"] = dict(state)
        issues = verify.check_citations(state["synthesis"], state["sources"])
        verification = results.pop(0) if results else CLEAN
        notes = verify.format_verification_notes(issues, verification)
        update = {"citation_issues": issues, "verification": verification}
        if notes:
            update["final_answer"] = state["final_answer"] + "\n\n" + notes
        return update

    graph = workflow.build_graph(
        plan=fake_plan,
        research=fake_research,
        evaluate=fake_evaluate,
        finish=fake_finish,
        verify=fake_verify,
    )
    return graph, calls, seen


def run(graph) -> workflow.ResearchState:
    return asyncio.run(graph.ainvoke({"question": "Where is Acme based?"}))


def test_sufficient_after_round_one_goes_straight_to_finish():
    graph, calls, seen = fake_nodes([True])

    state = run(graph)

    assert calls == ["plan", "research", "evaluate", "finish", "verify"]
    assert state["research_round"] == 1
    assert state["evidence"] == STABLE[0]
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
        "verify",
    ]
    assert state["research_round"] == 2
    assert state["evidence"] == STABLE[0] + STABLE[1]
    assert state["answers"] == ["answer 1", "answer 2"]
    # The follow-up round saw round one's evidence and the gaps.
    assert seen["research"]["evidence"] == STABLE[0]
    assert seen["research"]["evidence_gaps"] == ["gap after round 1"]
    # The second evaluation saw everything, and finish saw both answers.
    assert seen["evaluate"]["evidence"] == STABLE[0] + STABLE[1]
    assert seen["finish"]["answers"] == ["answer 1", "answer 2"]
    assert state["evidence_sufficient"] is True


def test_insufficient_twice_stops_after_the_second_round():
    graph, calls, seen = fake_nodes([False, False])

    state = run(graph)

    assert calls.count("research") == 2
    assert calls[-4:] == ["research", "evaluate", "finish", "verify"]
    assert state["research_round"] == 2
    assert state["evidence_sufficient"] is False
    assert state["evidence_gaps"] == ["gap after round 2"]
    assert seen["finish"]["evidence"] == STABLE[0] + STABLE[1]


def test_round_two_receives_stable_labels_and_one_id_per_source():
    graph, _, seen = fake_nodes([False, True])

    state = run(graph)

    # Round one's [D1] became [S1] before round two saw it.
    assert seen["research"]["evidence"] == STABLE[0]
    assert set(seen["research"]["sources"]) == {"S1", "S2"}
    followup = agent.followup_prompt(
        "Where is Acme based?",
        PLAN,
        seen["research"]["evidence"],
        seen["research"]["evidence_gaps"],
    )
    assert "[S1] source: a.txt" in followup
    assert "[D1]" not in followup
    # Round two's [D1] is a different file and got its own id; its web
    # hit is the URL round one ingested, so the id was reused.
    registry = state["sources"]
    assert [record.source_id for record in registry.values()] == [
        "S1",
        "S2",
        "S3",
    ]
    assert registry["S2"].canonical_url == "https://x.example/p"
    assert registry["S2"].seen_via == ("ingest", "web")
    assert registry["S2"].title == "Site"
    assert registry["S3"].local_document_id == "b.md"


def test_synthesis_sees_only_stable_source_ids():
    graph, _, seen = fake_nodes([False, True])
    run(graph)
    finish_state = seen["finish"]

    prompt = synthesize.build_prompt(
        finish_state["question"],
        finish_state["research_plan"],
        finish_state["answers"],
        finish_state["evidence"],
    )
    observations = prompt[prompt.index("Tool observations (evidence):") :]

    assert "[S1]" in observations and "[S3]" in observations
    assert "[D" not in observations and "[W" not in observations
    rules = " ".join(synthesize.SYSTEM_PROMPT.split())
    assert "a final citation is always [S#]" in rules
    assert "are round-local and are not valid citations" in rules


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


def test_verify_runs_after_finish_on_the_synthesis_and_the_registry():
    flawed = "Acme [S1]; peas [S3]; bad [D1] [S9]."
    graph, calls, seen = fake_nodes(
        [False, True], synthesis=flawed, revised=flawed
    )

    state = run(graph)

    assert calls[-2:] == ["finish", "verify"]
    assert seen["verify"]["synthesis"] == flawed
    assert state["final_answer"].startswith(flawed)
    assert set(seen["verify"]["sources"]) == {"S1", "S2", "S3"}
    assert state["citation_issues"] == [
        "[D1] is a round-local label, not a source.",
        "[S9] is not a known source.",
    ]
    clean, _, _ = fake_nodes([True], synthesis="Acme [S1].")
    assert run(clean)["citation_issues"] == []


UNSUPPORTED = verify.Verification(
    claims=[
        verify.ClaimCheck(
            claim="Acme makes arms.",
            cited_sources=["S1"],
            verdict="supported",
            reason="Observation 1 states it.",
        ),
        verify.ClaimCheck(
            claim="Acme earns $50 million.",
            cited_sources=["S1"],
            verdict="unsupported",
            reason="No observation mentions revenue.",
        ),
    ],
    conflicts=[],
    source_ratings=[],
)


def contradicted() -> verify.Verification:
    return verify.Verification(
        claims=[
            verify.ClaimCheck(
                claim="Acme was founded in 2013.",
                cited_sources=["S1"],
                verdict="contradicted",
                reason="Observation 1 states 2011.",
            )
        ],
        conflicts=[],
        source_ratings=[],
    )


WEAK_ONLY = verify.Verification(
    claims=[
        verify.ClaimCheck(
            claim="Acme makes arms.",
            cited_sources=["S1"],
            verdict="supported",
            reason="Observation 1 states it.",
        )
    ],
    conflicts=[],
    source_ratings=[
        verify.SourceRating(source_id="S1", quality="weak", reason="Unknown.")
    ],
)


def test_clean_verification_ends_the_run_with_a_bare_answer():
    graph, calls, _ = fake_nodes([True], synthesis="Acme [S1].")

    state = run(graph)

    assert calls[-3:] == ["evaluate", "finish", "verify"]
    assert state["revision_round"] == 0
    assert state["final_answer"] == "Acme [S1]."


def test_problems_cause_exactly_one_revision_from_the_findings():
    graph, calls, seen = fake_nodes(
        [True], synthesis="Acme [S1] earns [D2].", verifications=[UNSUPPORTED]
    )

    state = run(graph)

    assert calls[-4:] == ["finish", "verify", "finish", "verify"]
    assert calls.count("finish") == 2
    assert state["revision_round"] == 1
    # The revision saw the draft and the findings; the evidence is still
    # the observations only.
    revision = seen["finish"]
    assert revision["synthesis"] == "Acme [S1] earns [D2]."
    assert revision["verification"] == UNSUPPORTED
    assert revision["citation_issues"] == [
        "[D2] is a round-local label, not a source."
    ]
    assert revision["evidence"] == STABLE[0]
    # A clean second verification leaves no notes from the first one.
    assert state["final_answer"] == "revised"
    assert state["verification"] == CLEAN
    assert state["citation_issues"] == []


def test_problems_after_the_revision_end_with_notes_from_the_last_check():
    graph, calls, _ = fake_nodes(
        [False, False],
        synthesis="Acme [S1] earns [D2].",
        verifications=[UNSUPPORTED, contradicted()],
        revised="Acme [S1] was founded in 2013 [W1].",
    )

    state = run(graph)

    assert calls[-4:] == ["finish", "verify", "finish", "verify"]
    assert state["revision_round"] == 1
    assert state["final_answer"] == (
        "Acme [S1] was founded in 2013 [W1].\n\n"
        "Unresolved evidence gaps:\n"
        "1. gap after round 2\n\n"
        "Verification notes:\n"
        "1. [W1] is a round-local label, not a source.\n"
        '2. Contradicted claim: "Acme was founded in 2013." '
        "Observation 1 states 2011."
    )
    assert "[D2]" not in state["final_answer"]


def test_source_quality_alone_never_causes_a_revision():
    graph, calls, _ = fake_nodes(
        [True], synthesis="Acme [S1].", verifications=[WEAK_ONLY]
    )

    state = run(graph)

    assert calls.count("finish") == 1
    assert state["revision_round"] == 0
    assert state["final_answer"] == "Acme [S1]."


def test_router_revises_once_at_most():
    problem = {"citation_issues": ["[D1] is bad."], "verification": CLEAN}
    clean = {"citation_issues": [], "verification": WEAK_ONLY}

    assert workflow.route_after_verify({**problem, "revision_round": 0}) == (
        "revise"
    )
    assert workflow.route_after_verify({**problem, "revision_round": 1}) == (
        "end"
    )
    assert workflow.route_after_verify({**clean, "revision_round": 0}) == "end"
    assert workflow.MAX_REVISIONS == 1


def test_revision_prompt_carries_draft_and_findings_after_the_evidence():
    findings = verify.format_verification_notes(
        ["[D2] is a round-local label, not a source."], UNSUPPORTED
    )
    prompt = synthesize.build_prompt(
        "Where is Acme based?",
        PLAN,
        ["answer 1"],
        STABLE[0],
        draft="Acme [S1] earns [D2].",
        findings=findings,
    )

    headings = [
        "Tool observations (evidence):",
        "Previous draft:\nAcme [S1] earns [D2].",
        "Verification findings on the previous draft:\n" + findings,
        synthesize.REVISION_INSTRUCTION,
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert prompt.endswith(synthesize.REVISION_INSTRUCTION)
    assert "The findings are not evidence; the observations are." in prompt
    assert "Add no new facts." in prompt
    first = synthesize.build_prompt(
        "Where is Acme based?", PLAN, ["answer 1"], STABLE[0]
    )
    assert "Previous draft" not in first and "findings" not in first


def test_verifier_prompt_shows_answer_sources_and_evidence_only():
    graph, _, seen = fake_nodes([False, True], synthesis="Acme [S1].")
    run(graph)
    state = seen["verify"]

    prompt = verify.build_prompt(
        state["question"],
        state["synthesis"],
        state["evidence"],
        state["sources"],
    )

    headings = [
        "Question:",
        "Answer to verify:",
        "Sources:",
        "Tool observations (evidence):",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "Acme [S1]." in prompt
    assert "[S1] a.txt - a.txt (local); via documents" in prompt
    assert "[S2] Site - https://x.example/p; via ingest, web" in prompt
    observations = prompt[prompt.index("Tool observations (evidence):") :]
    assert "--- observation 4 ---\n" + STABLE[1][1] in observations
    assert "[D" not in observations and "[W" not in observations
    # Independence: no plan, no round answers.
    assert "Research plan" not in prompt
    assert "answer 1" not in prompt and "Round answers" not in prompt


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
        ("finish", "verify"),
        ("verify", "finish"),
        ("verify", END),
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


GAPS = ["No source gives the 2025 revenue.", "No IPO date is stated."]
FOLLOWUP = agent.followup_prompt(
    "Where is Acme based?", TOT_PLAN, ROUNDS[0][0], GAPS
)
INSTRUCTION = "Address each unresolved gap."


def test_followup_prompt_lists_every_gap_verbatim_and_numbered():
    heading = FOLLOWUP.index("Unresolved evidence gaps:")

    assert FOLLOWUP[heading:].startswith(
        "Unresolved evidence gaps:\n"
        "1. No source gives the 2025 revenue.\n"
        "2. No IPO date is stated.\n"
    )


def test_followup_prompt_puts_gaps_right_before_the_final_instruction():
    gaps_block = "Unresolved evidence gaps:\n1. " + GAPS[0] + "\n2. " + GAPS[1]
    after_gaps = FOLLOWUP[FOLLOWUP.index(gaps_block) + len(gaps_block) :]

    assert after_gaps.startswith("\n\n" + INSTRUCTION)
    assert FOLLOWUP.rstrip().endswith("which gaps you could not resolve.")


def test_followup_prompt_shows_prior_evidence_in_order_before_the_gaps():
    first, second = ROUNDS[0][0]
    evidence_at = FOLLOWUP.index("Evidence already collected:")

    assert evidence_at < FOLLOWUP.index(first) < FOLLOWUP.index(second)
    assert FOLLOWUP.index(second) < FOLLOWUP.index("Unresolved evidence gaps:")
    assert "--- observation 2 ---\n" + second in FOLLOWUP


def test_followup_prompt_frames_the_round_around_the_gaps():
    assert FOLLOWUP.startswith("Where is Acme based?\n\n")
    assert "Selected research approach (B): Technology stack" in FOLLOWUP
    assert (
        "Your task is the numbered list of unresolved evidence gaps" in FOLLOWUP
    )
    assert (
        "Do not re-research claims the evidence above already supports."
        in FOLLOWUP
    )


def test_followup_prompt_imposes_no_tool_order():
    # Only the instruction may name tools; the evidence block is quoted
    # tool output and can mention them too.
    instruction = FOLLOWUP[FOLLOWUP.index(INSTRUCTION) :]

    for tool in ("search_documents", "search_web", "ingest_url"):
        assert instruction.count(tool) == 1
        assert f"use {tool} when" in instruction
    for sequence in (
        "first search",
        "then search",
        "then ingest",
        "after search",
    ):
        assert sequence not in instruction.lower()


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
        STABLE[0] + STABLE[1],
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
    assert STABLE[1][0] in prompt


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
