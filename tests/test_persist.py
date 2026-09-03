"""Phase 7 persistence tests: resume, reopen, isolation, serialisation.

No model calls: fake nodes run under an in-memory checkpointer. The
non-persistent path is covered by ``tests/test_workflow.py``, which
still builds the graph with no checkpointer.
"""

import asyncio
import warnings
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from research import persist
from research import plan
from research import sources
from research import verify
from research import workflow

PLAN = plan.ResearchPlan(
    use_tot=True,
    candidates=[
        plan.Candidate("A", "Filings first", "strong", "strong", "medium")
    ],
    selected="A",
    reason="Best fit.",
)
# Round 2's web hit is the source round 1 ingested, so the reloaded
# registry has to accept a new provenance kind on an existing record.
ROUNDS = [
    (
        [
            "[D1] source: a.txt (distance 0.1000)\nAcme makes arms.",
            "Ingested 3 chunks from https://x.example/p into the local "
            "document collection. Use search_documents to retrieve from it.",
        ],
        "answer 1",
    ),
    (["[W1] Site - https://x.example/p\nSnippet."], "answer 2"),
]


def fake_graph(
    verdicts: list[bool],
    fail_at: tuple[str, int] | None = None,
    checkpointer=None,
):
    """A checkpointed graph of fakes, in memory unless one is given.

    ``fail_at=("research", 2)`` makes the second call of that node raise,
    once; the retry after a resume succeeds.
    """
    calls: list[str] = []
    pending = list(verdicts)
    failures = [fail_at] if fail_at else []

    def enter(node: str) -> None:
        calls.append(node)
        if failures and failures[0] == (node, calls.count(node)):
            failures.clear()
            raise RuntimeError(f"{node} interrupted")

    async def fake_plan(unused_state: workflow.ResearchState) -> dict[str, Any]:
        enter("plan")
        return {"research_plan": PLAN}

    async def fake_research(state: workflow.ResearchState) -> dict[str, Any]:
        enter("research")
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

    async def fake_evaluate(
        unused_state: workflow.ResearchState,
    ) -> dict[str, Any]:
        enter("evaluate")
        sufficient = pending.pop(0)
        return {
            "evidence_sufficient": sufficient,
            "evidence_gaps": [] if sufficient else ["gap"],
        }

    async def fake_finish(
        unused_state: workflow.ResearchState,
    ) -> dict[str, Any]:
        enter("finish")
        return {"synthesis": "final [S1]", "final_answer": "final [S1]"}

    async def fake_verify(state: workflow.ResearchState) -> dict[str, Any]:
        enter("verify")
        return {
            "citation_issues": verify.check_citations(
                state["synthesis"], state["sources"]
            )
        }

    graph = workflow.build_graph(
        plan=fake_plan,
        research=fake_research,
        evaluate=fake_evaluate,
        finish=fake_finish,
        verify=fake_verify,
        checkpointer=checkpointer or InMemorySaver(serde=persist.SERIALIZER),
    )
    return graph, calls


def run(graph, thread_id: str, question: str | None = "Where is Acme?"):
    """Invoke on a thread; ``None`` resumes whatever is pending."""
    payload = None if question is None else {"question": question}
    return asyncio.run(graph.ainvoke(payload, persist.thread_config(thread_id)))


def load(graph, thread_id: str):
    return asyncio.run(persist.load_state(graph, thread_id))


def test_interrupted_run_resumes_at_the_failed_node_only():
    graph, calls = fake_graph([True], fail_at=("evaluate", 1))

    with pytest.raises(RuntimeError, match="evaluate interrupted"):
        run(graph, "t1")
    snapshot = load(graph, "t1")

    assert snapshot.next == ("evaluate",)
    assert snapshot.values["research_round"] == 1
    assert "final_answer" not in snapshot.values

    state = run(graph, "t1", question=None)

    assert calls == [
        "plan",
        "research",
        "evaluate",
        "evaluate",
        "finish",
        "verify",
    ]
    assert state["final_answer"] == "final [S1]"
    assert state["citation_issues"] == []
    assert state["answers"] == ["answer 1"]  # Not doubled by the resume.
    assert load(graph, "t1").next == ()


def test_resume_into_a_second_round_uses_the_reloaded_registry():
    graph, calls = fake_graph([False, True], fail_at=("research", 2))
    with pytest.raises(RuntimeError, match="research interrupted"):
        run(graph, "t2")
    # The reloaded state has been through the serializer.
    snapshot = load(graph, "t2")
    reloaded = snapshot.values["sources"]["S2"]
    assert snapshot.next == ("research",)
    assert reloaded.seen_via == ("ingest",)
    assert isinstance(reloaded.seen_via, tuple)

    state = run(graph, "t2", question=None)

    assert calls[-5:] == [
        "research",
        "research",
        "evaluate",
        "finish",
        "verify",
    ]
    assert state["research_round"] == 2
    assert state["sources"]["S2"].seen_via == ("ingest", "web")
    assert state["evidence"][-1].startswith("[S2] Site - https://x.example/p")


def test_interrupted_verify_resumes_at_verify_only():
    graph, calls = fake_graph([True], fail_at=("verify", 1))

    with pytest.raises(RuntimeError, match="verify interrupted"):
        run(graph, "t7")
    snapshot = load(graph, "t7")

    assert snapshot.next == ("verify",)
    assert snapshot.values["synthesis"] == "final [S1]"
    assert "citation_issues" not in snapshot.values

    state = run(graph, "t7", question=None)

    assert calls[-3:] == ["finish", "verify", "verify"]
    assert calls.count("finish") == 1
    assert state["citation_issues"] == []
    assert load(graph, "t7").next == ()


def test_completed_thread_reopens_without_running_any_node():
    graph, calls = fake_graph([True])
    final = run(graph, "t3")
    calls.clear()

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # Unlisted types would warn here.
        snapshot = load(graph, "t3")

    assert not calls
    assert snapshot.next == ()
    assert snapshot.values == final
    assert snapshot.values["research_plan"] == PLAN
    assert isinstance(snapshot.values["research_plan"], plan.ResearchPlan)
    assert isinstance(snapshot.values["sources"]["S1"], sources.SourceRecord)


def test_threads_are_isolated_and_unknown_ids_fail():
    graph, unused_calls = fake_graph([True, True])
    run(graph, "a", question="Question A")
    run(graph, "b", question="Question B")

    assert load(graph, "a").values["question"] == "Question A"
    assert load(graph, "b").values["question"] == "Question B"
    assert load(graph, "a").values["answers"] == ["answer 1"]
    with pytest.raises(LookupError, match="'nope'"):
        load(graph, "nope")


def test_source_record_restores_the_tuple_invariant():
    record = sources.SourceRecord("S1", "t", None, "a.txt", ["documents"])
    assert record.seen_via == ("documents",)


def test_sqlite_checkpoint_survives_closing_and_reopening(tmp_path):
    path = str(tmp_path / "workflow.db")

    async def first_process() -> None:
        async with persist.open_checkpointer(path) as saver:
            graph, unused_calls = fake_graph([True], checkpointer=saver)
            await graph.ainvoke(
                {"question": "Where is Acme?"}, persist.thread_config("t6")
            )

    async def second_process():
        async with persist.open_checkpointer(path) as saver:
            graph, calls = fake_graph([True], checkpointer=saver)
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                snapshot = await persist.load_state(graph, "t6")
            return snapshot, calls

    asyncio.run(first_process())
    snapshot, calls = asyncio.run(second_process())

    assert not calls
    assert snapshot.next == ()
    assert snapshot.values["final_answer"] == "final [S1]"
    assert snapshot.values["citation_issues"] == []
    assert snapshot.values["research_plan"] == PLAN
    assert snapshot.values["sources"]["S1"].seen_via == ("documents",)
