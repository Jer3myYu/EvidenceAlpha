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
        "single_calls": {
            "scope.1": records.Attempt(
                id="scope.1",
                task_id="scope",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(turns=5),
                started_at=NOW,
            )
        },
        "phase": "mapping",
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


def test_loaded_records_are_revalidated():
    claim = records.Claim(
        id="C1", statement="s", kind="fact", topics=["cost_differentiation"]
    )
    assert not persist.validate_records({"claims": {"C1": claim}})
    # model_copy does not validate, so it produces the degraded shape a
    # reader would choke on: an invalid topic and a dictionary quantity.
    broken = claim.model_copy(
        update={
            "id": "C2",
            "topics": ["not_a_topic"],
            "quantity": {"value": 1},
        }
    )
    problems = persist.validate_records({"claims": {"C2": broken}})
    assert problems and problems[0].startswith("claims[C2]")


def test_validate_records_covers_every_persisted_field():
    malformed = records.IndustryMap().model_copy(
        update={"segments": [{"id": "G1", "name": "x"}]}
    )
    problems = persist.validate_records({"map": malformed})
    assert problems and problems[0].startswith("map")
    fine = {"map": records.IndustryMap(), "coverage": [], "question": "q"}
    assert not persist.validate_records(fine)
    bad_list = {
        "coverage": [
            records.Coverage(question=1, status="covered").model_copy(
                update={"question": "one"}
            )
        ]
    }
    assert persist.validate_records(bad_list)


def test_validate_records_rejects_a_field_degraded_to_a_dictionary():
    raw = {"segments": [{"id": "G1"}], "links": [], "participants": []}
    problems = persist.validate_records({"map": raw})
    assert problems and "IndustryMap" in problems[0]
    registry = {"C1": {"id": "C1", "statement": "x"}}
    assert persist.validate_records({"claims": registry})
    assert not persist.validate_records({"review": None, "cycle": 2})


def test_a_thread_of_another_record_schema_is_refused(tmp_path):
    # C1 round 1, finding 2: only the workflow version was compared, so
    # a checkpoint written by another record schema resumed on records
    # the serializer had silently stripped.
    path = str(tmp_path / "wf.db")
    config = persist.thread_config("t")

    async def run():
        async with persist.open_checkpointer(path) as saver:
            graph = StateGraph(state_module.IndustryState)

            async def start(_):
                return {
                    "meta": sample_meta().model_copy(
                        update={"schema_version": 999}
                    )
                }

            graph.add_node("start", start)
            graph.add_edge(START, "start")
            graph.add_edge("start", END)
            compiled = graph.compile(checkpointer=saver)
            await compiled.ainvoke({"question": "q"}, config)
            with pytest.raises(persist.LegacyThreadError, match="schema 999"):
                await persist.load_industry_state(
                    compiled, "t", state_module.WORKFLOW_VERSION
                )

    asyncio.run(run())


def test_an_unknown_persisted_field_is_refused_before_it_is_dropped():
    # C1 round 2, finding 3: the serializer rebuilt a record that failed
    # validation with model_construct, which drops the fields it does
    # not know; with no nested record left over there was nothing for a
    # post-deserialization check to notice, and the thread loaded with
    # the field silently gone.
    class Claim(records.Record):
        """A Claim as another schema wrote it: one field more, no nested
        record to leave behind."""

        id: str
        statement: str
        kind: str = "fact"
        review: str = "qualified"
        restriction: str = "merchant market only"

    Claim.__module__ = "industry.records"
    blob = persist.SERIALIZER.dumps_typed(
        {"claims": {"C1": Claim(id="C1", statement="s")}}
    )
    loaded = persist.SERIALIZER.loads_typed(blob)
    item = loaded["claims"]["C1"]
    # The payload is handed back whole rather than reconstructed, so the
    # unknown field is still there to be refused, not already lost.
    assert isinstance(item, dict)
    assert item["restriction"] == "merchant market only"
    problems = persist.validate_records(loaded)
    assert problems and "dict where Claim is required" in problems[0]


def test_a_record_may_not_be_built_without_validation():
    # The refusal that makes the serializer hand back the raw payload.
    with pytest.raises(TypeError, match="without validation"):
        records.Claim.model_construct(id="C1", statement="s", kind="fact")


def test_a_nested_record_left_as_a_dictionary_is_rejected():
    # Defence in depth: whatever leaves a declared record as a plain
    # value, no reader should be handed it.
    claim = records.Claim(id="C1", statement="s", kind="fact").model_copy(
        update={
            "quantity": {
                "value": 52,
                "unit": "亿元",
                "as_written": "52亿元",
                "period": None,
                "scope": None,
            }
        }
    )
    problems = persist.validate_records({"claims": {"C1": claim}})
    assert problems and "dict where Quantity is required" in problems[0]
    good = claim.model_copy(
        update={
            "quantity": records.Quantity(
                value=52, unit="亿元", as_written="52亿元"
            )
        }
    )
    assert not persist.validate_records({"claims": {"C1": good}})
    calculation = records.Calculation(
        id="K1",
        kind="share",
        label="l",
        inputs=[records.CalcInput(claim_id="C1", value=1.0, unit="u")],
        formula="f",
        status="ok",
    ).model_copy(
        update={"inputs": [{"claim_id": "C1", "value": 1.0, "unit": "u"}]}
    )
    deep = persist.validate_records({"calculations": {"K1": calculation}})
    assert deep and "CalcInput is required" in deep[0]


def test_a_checkpoint_citing_a_withdrawn_calculation_is_refused():
    # C1 round 3, finding 2: the load side of the same inconsistency —
    # a derived claim must never come back citable while the
    # calculation behind it is stopped.
    claim = records.Claim(
        id="C3",
        statement="share: 52.0 %",
        kind="derived",
        calculation_id="K1",
        review="supported",
        material=True,
        partition="q4",
    )
    stopped = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[records.CalcInput(claim_id="C1", value=52, unit="亿元")],
        formula="f",
        status="error",
        message="stale_input: C1 changed after the calculation",
    )
    problems = persist.validate_records(
        {"claims": {"C3": claim}, "calculations": {"K1": stopped}}
    )
    assert problems and "not current" in problems[0]
    current = stopped.model_copy(
        update={"status": "ok", "message": None, "result": 52.0, "unit": "%"}
    )
    assert not persist.validate_records(
        {"claims": {"C3": claim}, "calculations": {"K1": current}}
    )
