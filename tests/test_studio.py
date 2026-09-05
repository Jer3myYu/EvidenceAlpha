"""Studio tests: events, context windows, and live-versus-replay agreement.

No model calls and no server: the graph runs with fake nodes on an
in-memory checkpointer, and the crew framing is captured from a real
CrewAI crew with a fake LLM.
"""

import asyncio
from typing import Any

import pydantic
import studio
from langgraph import config as langgraph_config
from langgraph.checkpoint.memory import InMemorySaver

from research import agent
from research import crew
from research import persist
from research import plan
from research import sources
from research import verify
from research import workflow

QUESTION = "What does Acme make?"
PLAN = plan.ResearchPlan(
    use_tot=True,
    candidates=[
        plan.Candidate("A", "Filings first", "strong", "strong", "medium")
    ],
    selected="A",
    reason="Best fit.",
)
OBSERVATION = "[D1] source: a.txt (distance 0.1000)\nAcme makes arms."
CLEAN = verify.Verification(claims=[], conflicts=[], source_ratings=[])
FLAWED = verify.Verification(
    claims=[
        verify.ClaimCheck(
            claim="Acme makes legs.",
            cited_sources=["S1"],
            verdict="unsupported",
            reason="The observation says arms.",
        )
    ],
    conflicts=[],
    source_ratings=[],
)


def run(coroutine):
    return asyncio.run(coroutine)


def fake_nodes():
    """Two research rounds, then one revision: every route is taken."""
    verdicts = [False, True]
    verifications = [FLAWED, CLEAN]

    async def fake_plan(_: workflow.ResearchState) -> dict[str, Any]:
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        writer = langgraph_config.get_stream_writer()
        writer(
            {
                "event": "tool_use",
                "tool": "search_documents",
                "input": {"query": "Acme"},
            }
        )
        writer({"event": "tool_result", "text": OBSERVATION})
        evidence, registry = sources.normalize_observations(
            [OBSERVATION], state.get("sources", {})
        )
        return {
            "evidence": evidence,
            "sources": registry,
            "answers": ["Acme makes arms [S1]."],
            "research_round": state.get("research_round", 0) + 1,
        }

    async def fake_evaluate(_: workflow.ResearchState) -> dict[str, Any]:
        sufficient = verdicts.pop(0)
        return {
            "evidence_sufficient": sufficient,
            "evidence_gaps": [] if sufficient else ["Where is Acme based?"],
        }

    async def fake_finish(state: workflow.ResearchState) -> dict[str, Any]:
        revising = state.get("verification") is not None
        text = "Revised: Acme makes arms [S1]." if revising else "Arms [S1]."
        return {
            "synthesis": text,
            "final_answer": text,
            "revision_round": state.get("revision_round", 0) + revising,
        }

    async def fake_verify(state: workflow.ResearchState) -> dict[str, Any]:
        verification = verifications.pop(0)
        issues = verify.check_citations(state["synthesis"], state["sources"])
        update = {"citation_issues": issues, "verification": verification}
        notes = verify.format_verification_notes(issues, verification)
        if notes:
            update["final_answer"] = state["final_answer"] + "\n\n" + notes
        return update

    return {
        "plan": fake_plan,
        "research": fake_research,
        "evaluate": fake_evaluate,
        "finish": fake_finish,
        "verify": fake_verify,
    }


def build():
    return workflow.build_graph(
        **fake_nodes(), checkpointer=InMemorySaver(serde=persist.SERIALIZER)
    )


async def collect(graph, thread_id: str) -> list[dict[str, Any]]:
    return [event async for event in studio.run(graph, QUESTION, thread_id)]


def test_encode_turns_state_classes_into_json_data():
    record = sources.SourceRecord("S1", "a.txt", None, "a.txt", ("documents",))
    encoded = studio.encode(
        {
            "research_plan": PLAN,
            "sources": {"S1": record},
            "verification": FLAWED,
        }
    )
    assert encoded["research_plan"]["candidates"][0]["label"] == "A"
    assert encoded["sources"]["S1"]["seen_via"] == ["documents"]
    assert encoded["verification"]["claims"][0]["verdict"] == "unsupported"


def test_live_run_streams_tool_events_then_nodes_with_routes():
    graph = build()
    events = run(collect(graph, "t1"))
    assert events[0] == {
        "type": "thread",
        "thread_id": "t1",
        "question": QUESTION,
    }
    assert events[-1] == {"type": "end"}
    assert [e["type"] for e in events[1:5]] == [
        "node",
        "tool_use",
        "tool_result",
        "node",
    ]
    nodes = [e for e in events if e["type"] == "node"]
    assert [(e["node"], e["next"]) for e in nodes] == [
        ("plan", "research"),
        ("research", "evaluate"),
        ("evaluate", "research"),
        ("research", "evaluate"),
        ("evaluate", "finish"),
        ("finish", "verify"),
        ("verify", "finish"),
        ("finish", "verify"),
        ("verify", "end"),
    ]
    assert nodes[0]["trace"] == [
        "PLAN: approach A selected",
        "RESEARCH ROUND 1",
    ]
    assert nodes[1]["update"]["evidence"] == [
        "[S1] source: a.txt (distance 0.1000)\nAcme makes arms."
    ]
    # Round 2 saw the same source: same [S1] id, appended by the reducer.
    assert nodes[3]["update"]["evidence"] == nodes[1]["update"]["evidence"]
    assert len(nodes[3]["state"]["evidence"]) == 2
    assert nodes[3]["state"]["research_round"] == 2
    assert nodes[8]["state"]["revision_round"] == 1


def test_context_windows_follow_the_state_each_node_saw():
    nodes = [e for e in run(collect(build(), "t2")) if e["type"] == "node"]
    first, second = nodes[1]["context"], nodes[3]["context"]
    assert first["user"] == agent.research_prompt(QUESTION, PLAN)
    assert first["system"] == agent.SYSTEM_PROMPT
    assert first["tools"] == ["search_documents", "search_web", "ingest_url"]
    assert "Where is Acme based?" in second["user"]
    assert "follow-up research round" in second["user"]
    revision = nodes[7]["context"]
    assert "Arms [S1]." in revision["user"]  # The draft under revision.
    assert "Acme makes legs." in revision["user"]  # The verifier's finding.
    assert nodes[0]["context"]["schema"]["title"] == "PlanOutput"
    assert nodes[5]["context"]["schema"] is None


def test_replay_rebuilds_the_same_events_as_the_live_run():
    graph = build()
    live = [e for e in run(collect(graph, "t3")) if e["type"] == "node"]
    replayed = run(studio.replay(graph, "t3"))
    assert replayed["question"] == QUESTION
    assert replayed["completed"] is True
    keys = ("node", "next", "update", "state", "trace", "context")
    assert [[e[k] for k in keys] for e in replayed["events"]] == [
        [e[k] for k in keys] for e in live
    ]


def test_replay_of_an_unknown_thread_fails_clearly():
    try:
        run(studio.replay(build(), "nope"))
    except LookupError as error:
        assert "nope" in str(error)
    else:
        raise AssertionError("expected LookupError")


class FakeLLM(crew.crewai.BaseLLM):
    """Records what CrewAI sends, as tests/test_crew.py does."""

    reply: Any = None
    seen: list[tuple[Any, Any]] = pydantic.Field(default_factory=list)

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        self.seen.append((messages, response_model))
        return self.reply


def test_role_contexts_match_what_crewai_really_sends():
    registry = {
        "S1": sources.SourceRecord("S1", "a.txt", None, "a.txt", ("documents",))
    }
    evidence = ["[S1] source: a.txt (distance 0.1000)\nAcme makes arms."]
    state = {
        "question": QUESTION,
        "research_plan": PLAN,
        "evidence": evidence,
        "sources": registry,
        "answers": ["Acme makes arms [S1]."],
        "synthesis": "Arms [S1].",
        "final_answer": "Arms [S1].",
        "citation_issues": [],
        "verification": FLAWED,
        "revision_round": 0,
    }
    fakes = {
        "plan": FakeLLM(
            model="fake",
            reply=plan.PlanOutput(
                use_tot=False, candidates=[], selected="", reason="r"
            ),
        ),
        "evaluate": FakeLLM(
            model="fake",
            reply=crew.evaluate_module.EvidenceEvaluation(
                question_answerable_from_observations=True,
                missing_evidence=[],
            ),
        ),
        "finish": FakeLLM(model="fake", reply="Final Answer: text"),
        "verify": FakeLLM(model="fake", reply=CLEAN),
    }
    calls = {
        "plan": crew.plan(QUESTION, fakes["plan"]),
        "evaluate": crew.evaluate(
            QUESTION, PLAN, state["answers"][-1], evidence, fakes["evaluate"]
        ),
        "finish": crew.report(
            QUESTION,
            PLAN,
            state["answers"],
            evidence,
            state["synthesis"],
            verify.format_verification_notes([], FLAWED),
            fakes["finish"],
        ),
        "verify": crew.verify(
            QUESTION, state["synthesis"], evidence, registry, fakes["verify"]
        ),
    }
    for node, call in calls.items():
        run(call)
        system, user = crew.split_messages(fakes[node].seen[0][0])
        context = studio.role_context(node, state)
        assert context["system"] == system, node
        assert context["user"] == user, node


def test_sse_frames_one_event_per_message():
    assert studio.sse({"type": "end"}) == 'data: {"type": "end"}\n\n'
