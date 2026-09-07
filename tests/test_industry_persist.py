"""Checkpoint round trips, legacy threads, resume config, and backup."""

import asyncio
import pathlib
import sqlite3
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from industry import records
from industry import state as state_module
from research import persist
from research import workflow

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legacy_thread.db"
NOW = "2026-09-07T00:00:00+00:00"


def sample_meta():
    return records.RunMeta(
        workflow_version=state_module.WORKFLOW_VERSION,
        prompt_version="10.1",
        models={"lead": "claude-sonnet-5"},
        limits=records.Limits(),
        started_at=NOW,
    )


def sample_state():
    """Every registry populated with one record of each persisted kind."""
    attempt = records.Attempt(
        id="T1.1",
        task_id="T1",
        reserved=records.Reservation(turns=12, tool_calls=24, seconds=1200),
        started_at=NOW,
    )
    task = records.Task(id="T1", kind="map", role="industry", objective="map")
    brief = records.Brief(industry="光掩模")
    evidence = records.Evidence(
        id="E1",
        source_id="S1",
        source_version_id="v1",
        excerpt="e",
        locator="p1",
        kind="passage",
        extraction="html_text",
        task_id="T1",
        retrieved_at=NOW,
    )
    return {
        "question": "光掩模产业调研",
        "meta": sample_meta(),
        "brief": brief,
        "map": records.IndustryMap(
            segments=[
                records.Segment(
                    id="G1",
                    name="up",
                    stage="upstream",
                    description="",
                    claim_id="C1",
                )
            ],
            links=[
                records.Link(
                    id="L1",
                    from_segment="G1",
                    to_segment="G1",
                    what_flows="",
                    claim_id="C1",
                )
            ],
            participants=[
                records.Participant(
                    id="P1",
                    name="x",
                    segment_id="G1",
                    role="supplier",
                    selection_rationale="",
                    claim_id="C1",
                )
            ],
        ),
        "tasks": {"T1": task},
        "attempts": {"T1.1": attempt},
        "task_results": [
            records.TaskResult(
                attempt_id="T1.1",
                task_id="T1",
                status="done",
                sources=[
                    records.Source(
                        id="S1",
                        canonical_url="https://x",
                        title="x",
                        kind="web_page",
                    )
                ],
                source_versions=[
                    records.SourceVersion(
                        id="v1",
                        source_id="S1",
                        content_hash="h",
                        blob_path="b",
                        meta_path="m",
                        final_url="u",
                        content_type="t",
                        size=1,
                        retrieved_at=NOW,
                        extraction_version="v2",
                    )
                ],
                evidence=[evidence],
                findings=[
                    records.FindingDraft(
                        statement="s",
                        evidence_refs=["E1"],
                        quantity=records.Quantity(
                            value=1, unit="u", as_written="1"
                        ),
                        relationships=[
                            records.RelationshipDraft(
                                from_entity="a",
                                to_entity="b",
                                relation="supplies",
                            )
                        ],
                    )
                ],
                map=records.MapDraft(
                    segments=[
                        records.SegmentDraft(
                            key="u", name="up", stage="upstream", description=""
                        )
                    ],
                    links=[
                        records.LinkDraft(
                            from_key="u", to_key="u", what_flows=""
                        )
                    ],
                    participants=[
                        records.ParticipantDraft(
                            name="x", segment_key="u", role="supplier"
                        )
                    ],
                ),
            )
        ],
        "merged": ["T1.1"],
        "sources": {
            "S1": records.Source(
                id="S1", canonical_url="https://x", title="x", kind="web_page"
            )
        },
        "source_versions": {},
        "evidence": {"E1": evidence},
        "claims": {
            "C1": records.Claim(
                id="C1",
                statement="s",
                kind="fact",
                quantity=records.Quantity(value=1, unit="u", as_written="1"),
            )
        },
        "relationships": {
            "R1": records.Relationship(
                id="R1",
                from_entity="a",
                to_entity="b",
                relation="supplies",
                claim_id="C1",
            )
        },
        "calculations": {
            "K1": records.Calculation(
                id="K1",
                kind="ratio",
                label="l",
                inputs=[records.CalcInput(claim_id="C1", value=1, unit="u")],
                formula="1/1",
                result=1.0,
                unit="ratio",
                status="ok",
            )
        },
        "issues": {
            "I1": records.Issue(
                id="I1",
                key="k",
                category="unsupported",
                severity="minor",
                target="C1",
                requested_action="edit",
            )
        },
        "findings": {
            "F1": records.Finding(
                id="F1",
                conclusion="c",
                claim_ids=["C1"],
                mechanism="m",
                implication="i",
                counterargument="ca",
                uncertainty="u",
                monitor="mo",
            )
        },
        "coverage": [records.Coverage(question=1, status="partial")],
        "sections": [
            records.Section(id="s1", title="t", text="x [C1]", claim_ids=["C1"])
        ],
        "review": records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1", verdict="supported", reason="r"
                )
            ],
            relationships=[
                records.RelationshipVerdict(
                    relationship_id="R1", supported=False, reason="r"
                )
            ],
            sources=[
                records.SourceOriginJudgement(
                    source_id="S1", origin="primary", reason="r"
                )
            ],
            acquisitions=[records.AcquisitionRequest(objective="o")],
        ),
        "final_review": records.DraftReview(
            issues=[
                records.SectionIssue(
                    section_id="s1",
                    category="wording",
                    severity="minor",
                    description="d",
                )
            ]
        ),
        "assessment": records.LeadAssessment(
            coverage=[records.CoverageProposal(question=1, status="partial")]
        ),
        "usage_events": [records.Usage(turns=5, node="scope")],
        "cycle": 0,
        "follow_up_rounds": 0,
        "route_log": ["scope: ok"],
    }


def graph_with_pending_send():
    """A graph that stores every state key and leaves a Send pending."""

    class WorkerState(TypedDict, total=False):
        payload: records.WorkerInput

    async def fill(_):
        return sample_state()

    def fan_out(state):
        return [
            Send(
                "worker",
                records.WorkerInput(
                    thread_id="t",
                    attempt=state["attempts"]["T1.1"],
                    task=state["tasks"]["T1"],
                    brief=state["brief"],
                    language="zh",
                    references=[
                        records.Reference(
                            evidence=state["evidence"]["E1"], source_title="x"
                        )
                    ],
                    allowance=records.Reservation(
                        turns=12, tool_calls=24, seconds=1200
                    ),
                    model="claude-sonnet-5",
                    prompt_version="10.1",
                ),
            )
        ]

    async def worker(payload: records.WorkerInput):
        raise RuntimeError("interrupted before finishing")

    graph = StateGraph(state_module.IndustryState)
    graph.add_node("fill", fill)
    graph.add_node("worker", worker)
    graph.add_edge(START, "fill")
    graph.add_conditional_edges("fill", fan_out, ["worker"])
    graph.add_edge("worker", END)
    del WorkerState
    return graph


def test_full_state_and_pending_send_survive_close_and_reopen(tmp_path):
    path = str(tmp_path / "wf.db")
    config = persist.thread_config("t")

    async def write():
        async with persist.open_checkpointer(path) as saver:
            compiled = graph_with_pending_send().compile(checkpointer=saver)
            with pytest.raises(RuntimeError):
                await compiled.ainvoke(
                    {"question": "q"}, config, durability="sync"
                )

    async def read():
        async with persist.open_checkpointer(path) as saver:
            compiled = graph_with_pending_send().compile(checkpointer=saver)
            snapshot = await compiled.aget_state(config)
            return snapshot

    asyncio.run(write())
    snapshot = asyncio.run(read())
    assert snapshot.next == ("worker",)
    expected = sample_state()
    for key, value in expected.items():
        assert snapshot.values[key] == value, key
    assert persist.thread_version(snapshot) == state_module.WORKFLOW_VERSION
    pending = [t for t in snapshot.tasks if t.name == "worker"]
    assert pending and isinstance(pending[0].interrupts, tuple)


def test_legacy_fixture_loads_and_refuses_resume():
    async def run():
        async with persist.open_checkpointer(str(FIXTURE)) as saver:
            graph = workflow.build_graph(checkpointer=saver)
            snapshot = await persist.load_state(graph, "b29768d7")
            assert persist.thread_version(snapshot) is None
            assert "research_plan" in snapshot.values
            with pytest.raises(persist.LegacyThreadError, match="Phase 6-9"):
                await persist.load_industry_state(
                    graph, "b29768d7", state_module.WORKFLOW_VERSION
                )
            with pytest.raises(LookupError):
                await persist.load_state(graph, "nope")

    asyncio.run(run())


def test_version_mismatch_is_refused(tmp_path):
    path = str(tmp_path / "wf.db")
    config = persist.thread_config("t")

    async def run():
        async with persist.open_checkpointer(path) as saver:
            graph = StateGraph(state_module.IndustryState)

            async def start(_):
                meta = sample_meta().model_copy(
                    update={"workflow_version": "industry-v0"}
                )
                return {"meta": meta}

            graph.add_node("start", start)
            graph.add_edge(START, "start")
            graph.add_edge("start", END)
            compiled = graph.compile(checkpointer=saver)
            await compiled.ainvoke({"question": "q"}, config)
            with pytest.raises(persist.LegacyThreadError, match="industry-v0"):
                await persist.load_industry_state(compiled, "t", "industry-v1")
            snapshot = await compiled.aget_state(config)
            resumed = persist.resume_config("t", snapshot)
            assert resumed["configurable"]["interrupted_node"] is None

    asyncio.run(run())


def test_backup_copies_a_consistent_database(tmp_path):
    destination = str(tmp_path / "copy.db")
    persist.backup(str(FIXTURE), destination)
    copy = sqlite3.connect(destination)
    threads = copy.execute(
        "select distinct thread_id from checkpoints"
    ).fetchall()
    copy.close()
    assert threads == [("b29768d7",)]
