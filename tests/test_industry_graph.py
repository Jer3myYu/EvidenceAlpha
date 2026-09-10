"""The industry graph with fake roles and a fake worker.

Covers the happy path to delivery, dependency waves, worker crashes
with resume in a fresh and in the same runtime, two consecutive
interruptions of a single call, budget exhaustion, issue routing with
the no-progress stop, and the revision route after the final review.
"""

import asyncio
import dataclasses
import pathlib

import claude_agent_sdk
import pytest
from langgraph.checkpoint.memory import MemorySaver

import quantity_support as support
from industry import budget
from industry import calc
from industry import coverage
from industry import graph as graph_module
from industry import pdf as pdf_module
from industry import merge
from industry import report
from industry import quantities
from industry import records
from industry import roles
from industry import schedule
from industry import worker
from industry import tools
from industry import trace
from research import crew
from research import persist

NOW = "2026-09-07T00:00:00+00:00"
USAGE = records.Usage(turns=2, duration_s=1.0)


@pytest.mark.parametrize("node", ["analyze", "write"])
@pytest.mark.parametrize("new_step", [False, True])
def test_repetition_guard_distinguishes_concrete_correction_from_bookkeeping(
    tmp_path, node, new_step
):
    runtime, api, _, compiled = make(tmp_path)
    state = graph_module.initial_state("fixture", runtime.limits)
    state["brief"] = roles.default_brief("fixture")
    calls = []

    async def call(*args, **kwargs):
        del args, kwargs
        calls.append(node)
        return (roles.Analysis() if node == "analyze" else roles.Draft()), USAGE

    setattr(api, node, call)
    issue = records.Issue(
        id="I1",
        key="first",
        category="weak_inference",
        severity="material",
        target="economics",
        requested_action="analyze",
        text="Prices will certainly grow.",
        description="Qualify certainty.",
    )

    def invoke(current, objection, number):
        current = {**current, "issues": {objection.id: objection}}
        key = f"{node}.{number}"
        current["single_calls"] = {
            **current.get("single_calls", {}),
            key: records.Attempt(
                id=key,
                task_id=node,
                started_at=records.now_iso(),
                reserved=records.Reservation(
                    turns=10, tool_calls=0, seconds=480
                ),
            ),
        }
        update = asyncio.run(compiled.nodes[node].node.steps[0].afunc(current))
        return {**current, **update}

    state = invoke(state, issue, 1)
    cosmetic = issue.model_copy(
        update={
            "id": "I2",
            "key": "renamed",
            "description": "Avoid overcertainty.",
        }
    )
    state["meta"] = state["meta"].model_copy(
        update={"started_at": records.now_iso()}
    )
    first = state["single_calls"][f"{node}.1"]
    state["single_calls"][first.id] = first.model_copy(
        update={"observed": USAGE.model_copy(update={"duration_s": 2})}
    )
    state = invoke(state, cosmetic, 2)
    assert calls == [node]
    assert state["single_calls"][f"{node}.2"].observed.turns == 0
    concrete = cosmetic.model_copy(
        update=(
            {"next_step": "Test demand separately from capacity."}
            if new_step
            else {"text": "Rising capacity proves stronger demand."}
        )
    )
    state = invoke(state, concrete, 3)
    assert calls == [node, node]
    assert state["single_calls"][f"{node}.3"].observed.turns == USAGE.turns


def version(source_id):
    return records.SourceVersion(
        id=f"v-{source_id}",
        source_id=source_id,
        content_hash="h",
        blob_path="b",
        meta_path="m",
        final_url="u",
        content_type="text/html",
        size=1,
        retrieved_at=NOW,
        extraction_version="v2",
    )


def passage(eid, sid, text):
    return records.Evidence(
        id=eid,
        source_id=sid,
        source_version_id=f"v-{sid}",
        excerpt=text,
        locator="sec 1",
        kind="passage",
        extraction="html_text",
        task_id="T",
        retrieved_at=NOW,
    )


def map_draft():
    return records.MapDraft(
        segments=[
            records.SegmentDraft(
                key="u",
                name="基板",
                stage="upstream",
                description="石英基板",
                evidence_refs=["E1"],
            ),
            records.SegmentDraft(
                key="m",
                name="掩模制造",
                stage="midstream",
                description="",
                evidence_refs=["E1"],
            ),
            records.SegmentDraft(
                key="d",
                name="晶圆厂",
                stage="downstream",
                description="",
                evidence_refs=["E1"],
            ),
        ],
        links=[
            records.LinkDraft(
                from_key="u",
                to_key="m",
                what_flows="基板",
                evidence_refs=["E1"],
            ),
            records.LinkDraft(
                from_key="m",
                to_key="d",
                what_flows="掩模版",
                evidence_refs=["E1"],
            ),
        ],
        participants=[
            records.ParticipantDraft(
                name=name,
                segment_key=key,
                role="supplier",
                supplies="x",
                region=region,
                evidence_refs=["E1"],
            )
            for name, key, region in (
                ("HOYA", "u", "日本"),
                ("AGC", "u", "日本"),
                ("清溢光电", "m", "中国"),
                ("Photronics", "m", "美国"),
                ("中芯国际", "d", "中国"),
                ("TSMC", "d", "台湾"),
            )
        ],
        boundary_note="掩模版及其直接上下游",
    )


def finding_draft(statement, topics, questions, entity=None, **kw):
    return records.FindingDraft(
        statement=statement,
        evidence_refs=["E1"],
        material=True,
        topics=topics,
        questions=questions,
        entity=entity,
        **kw,
    )


class FakeWorker:
    """Returns canned results per task kind; can crash or fail once."""

    def __init__(self):
        self.calls: list[records.WorkerInput] = []
        self.crash_once: set[str] = set()
        self.fail_once: set[str] = set()
        self.order: list[str] = []
        self.duration_s = 2.0

    async def __call__(self, work, runtime, backend, on_event=None):
        del backend, on_event
        self.calls.append(work)
        meter = runtime.meter_for(work.thread_id)
        if meter is None or not meter.is_admitted(work.attempt.id):
            return records.TaskResult(
                attempt_id=work.attempt.id,
                task_id=work.task.id,
                status="unknown",
                usage=records.Usage(unknown=True),
                error="replayed attempt not admitted",
            )
        self.order.append(work.attempt.id)
        if work.attempt.id in self.crash_once:
            self.crash_once.discard(work.attempt.id)
            await asyncio.sleep(0.05)  # let a sibling finish first
            raise RuntimeError(f"{work.attempt.id} crashed")
        if work.attempt.id in self.fail_once:
            self.fail_once.discard(work.attempt.id)
            return records.TaskResult(
                attempt_id=work.attempt.id,
                task_id=work.task.id,
                status="failed",
                usage=records.Usage(unknown=True),
                error="transport: CLIConnectionError",
            )
        await asyncio.sleep(0.01)
        sid = "S1"
        common = {
            "sources": [
                records.Source(
                    id=sid,
                    canonical_url="https://a.example/x",
                    title="A",
                    kind="web_page",
                )
            ],
            "source_versions": [version(sid)],
            "evidence": [
                passage(
                    "E1",
                    sid,
                    "HOYA 供应 TSMC 掩模基板，市场规模 52亿元（2024）。",
                )
            ],
            "usage": records.Usage(
                turns=3, tool_calls=2, duration_s=self.duration_s
            ),
        }
        if work.task.kind == "map":
            return records.TaskResult(
                attempt_id=work.attempt.id,
                task_id=work.task.id,
                status="done",
                map=map_draft(),
                findings=[
                    finding_draft(
                        "掩模版是光刻母版，芯片制造必需",
                        ["product", "boundary"],
                        [1],
                    ),
                    finding_draft(
                        "HOYA 供应 TSMC 掩模基板",
                        ["payer_flow"],
                        [3],
                        entity="HOYA",
                        relationships=[
                            records.RelationshipDraft(
                                from_entity="HOYA",
                                to_entity="TSMC",
                                relation="supplies",
                                evidence_refs=["E1"],
                            )
                        ],
                    ),
                ],
                **common,
            )
        findings = [
            finding_draft("晶圆厂向掩模厂付费", ["payer_flow"], [4]),
            finding_draft("先进制程带动需求", ["demand_driver"], [4]),
            finding_draft("基板成本占比高", ["cost_structure"], [4]),
            finding_draft("高端产品差异化在于缺陷率", ["differentiation"], [4]),
            finding_draft("HOYA 议价能力强", ["bargaining_power"], [4]),
            finding_draft("技术壁垒高", ["barrier"], [5]),
            finding_draft(
                "清溢光电 2024 年稳定量产",
                ["commercialization"],
                [5],
                entity="清溢光电",
                kind="company_claim",
                milestone="stable_production",
                milestone_date="2024-06",
            ),
            finding_draft(
                "HOYA 全球领先", ["global_china"], [6], entity="HOYA"
            ),
            finding_draft(
                "清溢光电 国内领先", ["global_china"], [6], entity="清溢光电"
            ),
            finding_draft(
                "HOYA 2024 收入",
                ["comparison"],
                [7],
                entity="HOYA",
                dimension="2024 revenue",
            ),
            finding_draft(
                "清溢光电 2024 收入",
                ["comparison"],
                [7],
                entity="清溢光电",
                dimension="2024 revenue",
            ),
        ]
        return records.TaskResult(
            attempt_id=work.attempt.id,
            task_id=work.task.id,
            status="done",
            findings=findings,
            **common,
        )


class FakeRoles:
    """Canned single-call outputs; each call is recorded."""

    def __init__(self):
        self.calls: list[str] = []
        self.audit_verdict = "supported"
        self.scope_failures = 0
        # The first allocation admits one ordinary industry task, which
        # owns the map; the handoff after its merge plans company work
        # against the map it produced.
        self.plans = [
            roles.TaskPlan(
                tasks=[
                    roles.TaskSpec(
                        key="a", role="industry", objective="upstream"
                    )
                ]
            ),
            roles.TaskPlan(
                tasks=[
                    roles.TaskSpec(
                        key="b", role="company", objective="companies"
                    )
                ]
            ),
        ]
        self.review_verdict = "supported"
        self.draft_text = None
        self.final_issues: list[records.SectionIssue] = []

    async def scope(self, question, max_turns, deadline):
        del max_turns, deadline
        self.calls.append("scope")
        if self.scope_failures:
            self.scope_failures -= 1
            raise RuntimeError("transport: gone")
        return roles.default_brief(question), USAGE

    async def plan_tasks(
        self, state, limits, slots, purpose, max_turns, deadline
    ):
        del state, limits, slots, max_turns, deadline
        self.calls.append(f"plan:{purpose[:12]}")
        plan = self.plans.pop(0) if self.plans else roles.TaskPlan()
        return plan, USAGE

    async def assess_coverage(self, state, max_turns, deadline):
        del state, max_turns, deadline
        self.calls.append("assess")
        return records.LeadAssessment(), USAGE

    async def analyze(self, state, note, max_turns, deadline):
        del note, max_turns, deadline
        self.calls.append("analyze")
        claims = [c for c in state.get("claims", {}).values() if not c.map_ref]
        findings = (
            [
                roles.FindingSpec(
                    conclusion="经济学结论",
                    claim_ids=[c.id for c in claims],
                    mechanism="m",
                    implication="i",
                    counterargument="ca",
                    uncertainty="u",
                    monitor="mo",
                    material=True,
                    questions=[4, 5, 6, 7, 8],
                )
            ]
            if claims
            else []
        )
        return roles.Analysis(findings=findings), USAGE

    async def review_claims(self, state, claim_ids, max_turns, deadline):
        del max_turns, deadline
        self.calls.append("review")
        verdicts = [
            records.ClaimVerdict(
                claim_id=cid,
                verdict=self.review_verdict,
                reason="r",
                topics_supported=list(state["claims"][cid].topics),
            )
            for cid in claim_ids
        ]
        relationships = [
            records.RelationshipVerdict(
                relationship_id=rid, supported=True, reason="named"
            )
            for rid in state.get("relationships", {})
        ]
        return (
            records.ClaimReview(claims=verdicts, relationships=relationships),
            USAGE,
        )

    async def scope_and_plan(
        self, question, limits, slots, max_turns, deadline
    ):
        del limits, max_turns, deadline
        self.calls.append("scope_and_plan")
        brief = roles.default_brief(question)
        brief = brief.model_copy(update=roles.derive_obligations(brief))
        plan = self.plans[0] if self.plans else roles.TaskPlan()
        self.plans = self.plans[1:]
        return (brief, roles.TaskPlan(tasks=plan.tasks[:slots])), USAGE

    async def audit_findings(self, state, max_turns, deadline):
        del max_turns, deadline
        self.calls.append("audit")
        # Clean by default: the audit's own routing is tested directly,
        # and every other case should reach the Editor as it always did.
        return (
            records.FindingAudit(
                judgements=[
                    records.FindingJudgement(
                        finding_id=fid,
                        verdict=self.audit_verdict,
                        reason="the mechanism follows from the premises",
                    )
                    for fid in state.get("findings", {})
                ]
            ),
            USAGE,
        )

    async def write(
        self, state, instructions, max_turns, deadline, owner=False
    ):
        del max_turns, deadline
        self.calls.append(
            ("owner-" if owner else "")
            + "write:"
            + ("revise" if "Revise" in instructions else "full")
        )
        draft_text = self.draft_text
        if draft_text is None:
            units = [
                f"{claim.statement.strip().rstrip('.。')} [{cid}]。"
                for cid, claim in state.get("claims", {}).items()
            ]
            draft_text = "".join(units)
        else:
            units = report.factual_units(draft_text)
        return (
            roles.Draft(
                sections=[
                    roles.SectionSpec(
                        id="intro",
                        title="概览",
                        text=draft_text,
                        blocks=[
                            roles.BlockSpec(
                                key=f"b{number}",
                                kind="sentence",
                                text=text,
                                claim_ids=report.cited_claims(text),
                                depends_on=[],
                            )
                            for number, text in enumerate(units, 1)
                        ],
                    )
                ]
            ),
            USAGE,
        )

    async def final_review(self, state, max_turns, deadline):
        del max_turns, deadline
        self.calls.append("final")
        return (
            records.DraftReview(
                issues=list(self.final_issues),
                consistent=not self.final_issues,
                units=[
                    records.UnitReview(
                        block_id=b.id,
                        version=b.version,
                        supported=True,
                        dependencies_complete=True,
                        reason="fixture judgment",
                    )
                    for s in state.get("sections", [])
                    for b in s.blocks
                ],
            ),
            USAGE,
        )


# These cases exercise routing, issues and redaction with tiny fake
# drafts, not investor usefulness, so they run under a permissive
# Level-B floor. The floor itself is covered in test_industry_report.py.
OPEN_FLOOR = coverage.UsefulnessFloor(
    mandatory_questions=(),
    central_required=0,
    min_supported_claims=0,
    definition_topics=(),
)


def seed_map_task():
    """One dispatchable map task, as the first allocation would create.

    Tests about admission, cancellation and resume need a worker
    session without first spending a planning call; production reaches
    the same task through `prepare_tasks`.
    """
    return {
        "T1": records.Task(
            id="T1",
            kind="map",
            role="industry",
            objective="map the value chain",
            required_fields=list(graph_module.MAP_FIELDS),
        )
    }


def make(tmp_path, limits=None, saver=None, floor=OPEN_FLOOR):
    runtime = budget.Runtime(
        limits or records.Limits(),
        reports_dir=str(tmp_path / "reports"),
        floor=floor,
    )
    api = FakeRoles()
    worker = FakeWorker()
    compiled = graph_module.build_graph(
        runtime,
        backend=object(),
        api=api,
        worker_fn=worker,
        checkpointer=saver or MemorySaver(),
    )
    return runtime, api, worker, compiled


def run(coro):
    return asyncio.run(coro)


def test_happy_path_delivers_a_report(tmp_path):
    runtime, api, worker, compiled = make(tmp_path)
    config = persist.thread_config("t1")
    runtime.begin("t1")
    state = run(compiled.ainvoke({"question": "光掩模产业调研"}, config))
    meta = state["meta"]
    assert meta.execution_status == "completed"
    assert meta.report_status == "complete"
    assert (tmp_path / "reports" / "t1.md").exists()
    text = (tmp_path / "reports" / "t1.md").read_text(encoding="utf-8")
    assert "# 光掩模产业调研" in text and "## 概览" in text and "[1]" in text
    # Two tasks, not three: the dedicated map session is gone and the
    # first ordinary task owns the map.
    assert [t.status for t in state["tasks"].values()] == ["done", "done"]
    assert [t.kind for t in state["tasks"].values()] == ["map", "research"]
    assert {c.task_id: c.status for c in state["single_calls"].values()} == {
        "scope": "done",
        "prepare_tasks": "done",
        "assess_coverage": "done",
        "analyze": "done",
        "review": "done",
        # The analysis is judged before any prose is written (D-U11).
        "audit_findings": "done",
        "write": "done",
        "final_review": "done",
    }
    assert len(state["coverage"]) == 8
    assert state["map"].segments
    assert state["relationships"]["R1"].confirmed
    spent = budget.ledger(state)
    # Two executions, not three: the dedicated map session is gone.
    assert spent.task_executions == 2
    calls = state["single_calls"].values()
    assert all(c.status == "done" for c in calls)
    assert spent.turns == 2 * 3 + sum(c.observed.turns for c in calls)
    assert api.calls[0] == "scope" and api.calls[1].startswith("plan:")
    # The fixture's material claims exceed one review batch; the loop
    # reviews them in consecutive calls before analysis.
    reviews = [c for c in api.calls if c == "review"]
    reviewable = sum(
        1 for c in state["claims"].values() if c.material or c.map_ref
    )
    assert len(reviews) == -(-reviewable // graph_module.REVIEW_BATCH) >= 2
    assert graph_module.review_remaining(state) == 0
    # The handoff after the map task merges is the one added Lead call:
    # company selection now sees the map instead of guessing before it.
    assert [c for c in api.calls[2:] if c != "review"] == [
        "plan:the first re",
        "analyze",
        "assess",
        # The reasoning is judged before the prose, not after it.
        "audit",
        "write:full",
        "final",
    ]
    assessments = [c for c in state["single_calls"] if c.startswith("assess")]
    assert len(assessments) <= 1 + runtime.limits.follow_up_rounds
    assert worker.order == ["T1.1", "T2.1"], "the map owner runs first"
    assert all(isinstance(w, records.WorkerInput) for w in worker.calls)
    assert worker.calls[1].brief.industry == "光掩模产业调研"


def test_worker_crash_keeps_siblings_and_resumes_with_a_new_attempt(tmp_path):
    saver = MemorySaver()
    # Wall clock raised so the handoff can plan the two siblings this
    # case needs; it is about crash recovery, not about the budget.
    runtime, api, worker, compiled = make(
        tmp_path, records.Limits(wall_clock_s=9000.0), saver=saver
    )
    api.plans = [
        roles.TaskPlan(
            tasks=[
                roles.TaskSpec(key="a", role="industry", objective="upstream"),
                roles.TaskSpec(key="b", role="company", objective="companies"),
            ]
        )
    ]
    # The first allocation admits the map owner; the siblings this case
    # is about are planned by the handoff after it merges.
    api.plans.insert(
        0,
        roles.TaskPlan(
            tasks=[roles.TaskSpec(key="m", role="industry", objective="map")]
        ),
    )
    worker.crash_once.add("T3.1")
    config = persist.thread_config("t2")
    runtime.begin("t2")
    with pytest.raises(RuntimeError, match="T3.1 crashed"):
        run(compiled.ainvoke({"question": "q"}, config, durability="sync"))
    snapshot = run(compiled.aget_state(config))
    assert set(snapshot.next) == {"run_task"}
    assert budget.ledger(snapshot.values).task_executions == 3
    # Same runtime, new invocation: the replayed Send is refused, the
    # task is re-queued, and a second attempt runs.
    runtime.begin("t2")
    state = run(compiled.ainvoke(None, config, durability="sync"))
    assert state["attempts"]["T3.1"].status == "unknown"
    assert state["attempts"]["T3.2"].status == "done"
    assert worker.order.count("T3.1") == 1 and "T3.2" in worker.order
    assert (
        state["tasks"]["T3"].status == "done"
        and state["tasks"]["T3"].attempts == 2
    )
    spent = budget.ledger(state)
    assert spent.unknown_attempts == 1 and spent.task_executions == 4
    assert state["meta"].execution_status == "completed"


def test_fresh_process_resume_refuses_the_replayed_send(tmp_path):
    saver = MemorySaver()
    runtime, _, worker, compiled = make(tmp_path, saver=saver)
    worker.crash_once.add("T1.1")
    config = persist.thread_config("t3")
    runtime.begin("t3")
    with pytest.raises(RuntimeError):
        run(compiled.ainvoke({"question": "q"}, config, durability="sync"))
    # A fresh process: new Runtime, new graph object, same saver.
    runtime2 = budget.Runtime(
        records.Limits(), reports_dir=str(tmp_path / "reports")
    )
    worker2 = FakeWorker()
    compiled2 = graph_module.build_graph(
        runtime2,
        backend=object(),
        api=FakeRoles(),
        worker_fn=worker2,
        checkpointer=saver,
    )
    runtime2.begin("t3")
    state = run(compiled2.ainvoke(None, config, durability="sync"))
    assert worker2.calls[0].attempt.id == "T1.1" and "T1.1" not in worker2.order
    assert state["attempts"]["T1.1"].status == "unknown"
    assert state["attempts"]["T1.2"].status == "done"


def test_two_consecutive_scope_interruptions_each_charge_a_reservation(
    tmp_path,
):
    saver = MemorySaver()
    runtime, api, _, compiled = make(tmp_path, saver=saver)
    api.scope_failures = 2
    config = persist.thread_config("t4")
    limits = runtime.limits
    runtime.begin("t4")
    with pytest.raises(RuntimeError):
        run(compiled.ainvoke({"question": "q"}, config, durability="sync"))
    for _ in range(2):
        snapshot = run(compiled.aget_state(config))
        assert snapshot.next == ("scope",)
        updates = graph_module.resume_updates(snapshot.values, "scope", limits)
        run(compiled.aupdate_state(config, updates, as_node="reserve_scope"))
        runtime.begin("t4")
        try:
            run(compiled.ainvoke(None, config, durability="sync"))
            break
        except RuntimeError:
            continue
    state = run(compiled.aget_state(config)).values
    calls = state["single_calls"]
    assert (
        calls["scope.1"].status == "unknown"
        and calls["scope.2"].status == "unknown"
    )
    assert calls["scope.3"].status == "done"
    assert budget.ledger(state).turns >= 5 + 5 + 2
    assert state["meta"].execution_status == "completed"


def test_exhausted_budget_skips_calls_and_delivers_incomplete(tmp_path):
    limits = records.Limits(model_calls=22, model_call_reserve=20)
    runtime, api, _, compiled = make(tmp_path, limits)
    config = persist.thread_config("t5")
    runtime.begin("t5")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert "scope" not in api.calls  # 22 - 20 reserve < 10: refused
    assert any("reserve_scope: refused" in line for line in state["route_log"])
    assert state["brief"].industry == "q"  # deterministic defaults
    assert state["meta"].report_status == "incomplete"
    assert state["meta"].execution_status == "completed"
    assert "write:full" in api.calls  # the reserve pays for writing


def test_unsupported_material_claim_routes_to_remediation_then_stops(tmp_path):
    runtime, api, _, compiled = make(tmp_path)
    api.review_verdict = "unsupported"
    config = persist.thread_config("t6")
    runtime.begin("t6")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert any(
        "remediate: cycle 1 -> research" in line for line in state["route_log"]
    )
    assert state["cycle"] == 1
    assert state["meta"].report_status == "incomplete"
    # The second cycle stopped for lack of progress rather than looping.
    assert state["cycle"] < runtime.limits.remediation_cycles
    assert "write:full" in api.calls and "final" in api.calls


def test_uncited_number_in_the_draft_reopens_editing(tmp_path):
    runtime, api, _, compiled = make(tmp_path)
    api.draft_text = "市场规模 52亿元。结论 [C1]。"
    config = persist.thread_config("t7")
    runtime.begin("t7")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert any(
        i.category == "unsupported" and i.target == "intro"
        for i in state["issues"].values()
    )
    assert any(
        "remediate: cycle 1 -> write" in line for line in state["route_log"]
    )
    assert "write:revise" in api.calls
    # An open editorial issue is a limitation, not a central gap, and
    # its text is redacted from the delivered report.
    # Plan revision 33 §4.39: a body redacted after its final review
    # is a substantive change the certificate no longer covers, so it
    # is delivered as an explicitly partial Level-B report and never
    # as complete_with_limitations.
    assert state["meta"].report_status == "incomplete"
    assert state["delivery"].level == "partial"
    text = pathlib.Path(state["meta"].report_path).read_text(encoding="utf-8")
    if any(
        i.status == "open" and i.text and "52亿元" in i.text
        for i in state["issues"].values()
    ):
        body = text.split("## Limitations")[0].split("## 局限性")[0]
        assert "市场规模 52亿元" not in body
        assert "[unverified statement removed]" in body or "已移除" in body


def test_initial_state_carries_meta_so_an_early_interruption_resumes(tmp_path):
    saver = MemorySaver()
    runtime, api, _, compiled = make(tmp_path, saver=saver)
    api.scope_failures = 1
    config = persist.thread_config("t8")
    runtime.begin("t8")
    payload = graph_module.initial_state("q", runtime.limits)
    with pytest.raises(RuntimeError):
        run(compiled.ainvoke(payload, config, durability="sync"))
    # The loader the CLI uses must recognise the thread as Phase 10.
    snapshot = run(
        persist.load_industry_state(
            compiled, "t8", graph_module.state_module.WORKFLOW_VERSION
        )
    )
    assert snapshot.next == ("scope",)
    assert snapshot.values["meta"].limits == runtime.limits


def test_resume_updates_apply_admission_and_reserve_only_what_fits():
    limits = records.Limits(
        model_calls=18, model_call_reserve=10, turns_per_exchange=1
    )
    state = {
        "attempts": {},
        "single_calls": {
            "scope.1": records.Attempt(
                id="scope.1",
                task_id="scope",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                started_at=NOW,
            )
        },
    }
    updates = graph_module.resume_updates(state, "scope", limits)
    calls = updates["single_calls"]
    assert calls["scope.1"].status == "unknown"
    # 18 - 5 charged = 13 left, 3 after the reserve: an intermediate
    # call needs 5, so no reservation.
    assert "scope.2" not in calls
    assert any("budget exhausted" in line for line in updates["route_log"])
    # A reserved node may take the remainder.
    writing = {"attempts": {}, "single_calls": {}}
    writing["single_calls"]["write.1"] = records.Attempt(
        id="write.1",
        task_id="write",
        reserved=records.Reservation(turns=5, tool_calls=0, seconds=480),
        started_at=NOW,
    )
    updates = graph_module.resume_updates(writing, "write", limits)
    assert updates["single_calls"]["write.2"].reserved.turns == 5
    assert budget.ledger({"attempts": {}, **updates}).turns == 10
    assert budget.max_turns_for(5, limits) == 5


def test_forward_dependencies_and_duplicate_keys_in_a_plan(tmp_path):
    # Wall clock raised so the handoff has room for two tasks: this case
    # is about dependency resolution, not about what the budget affords.
    runtime, api, worker, compiled = make(
        tmp_path, records.Limits(wall_clock_s=9000.0)
    )
    api.plans = [
        # The first allocation admits the map owner; forward
        # dependencies and duplicate keys are a planning concern of the
        # handoff, where slots are not capped to one.
        roles.TaskPlan(
            tasks=[
                roles.TaskSpec(key="m", role="industry", objective="the map")
            ]
        ),
        roles.TaskPlan(
            tasks=[
                roles.TaskSpec(
                    key="b",
                    role="company",
                    objective="companies",
                    depends_on=["a"],
                ),
                roles.TaskSpec(key="a", role="industry", objective="upstream"),
                roles.TaskSpec(key="a", role="industry", objective="duplicate"),
            ]
        ),
    ]
    config = persist.thread_config("t9")
    runtime.begin("t9")
    state = run(compiled.ainvoke({"question": "q"}, config))
    tasks = state["tasks"]
    assert tasks["T2"].objective == "companies" and tasks["T2"].depends_on == [
        "T3"
    ]
    assert tasks["T3"].objective == "upstream" and "T4" not in tasks
    assert tasks["T1"].kind == "map"
    assert any("duplicate key" in line for line in state["route_log"])
    assert worker.order.index("T3.1") < worker.order.index("T2.1")


def test_calculations_take_only_reviewed_inputs(tmp_path):
    runtime, api, _, compiled = make(tmp_path)

    async def analyze(state, note, max_turns, deadline):
        del note, max_turns, deadline
        api.calls.append("analyze")
        quantified = [c for c in state["claims"].values() if c.quantity]
        request = roles.Analysis(
            calc_requests=[
                records.CalcRequest(
                    kind="ratio",
                    label="r",
                    numerator_claim_id=quantified[0].id if quantified else "C1",
                    denominator_claim_id=(
                        quantified[0].id if quantified else "C1"
                    ),
                )
            ]
        )
        return request, USAGE

    api.analyze = analyze
    api.review_verdict = "unsupported"
    config = persist.thread_config("t10")
    runtime.begin("t10")
    state = run(compiled.ainvoke({"question": "q"}, config))
    calcs = list(state["calculations"].values())
    assert calcs and all(c.status == "error" for c in calcs)
    assert all(c.kind != "derived" for c in state["claims"].values())


def test_final_review_issue_stays_open_until_a_later_clean_review(tmp_path):
    runtime, api, _, compiled = make(tmp_path)
    api.final_issues = [
        records.SectionIssue(
            section_id="intro",
            category="wording",
            severity="material",
            description="unclear",
        )
    ]
    config = persist.thread_config("t11")
    runtime.begin("t11")
    state = run(compiled.ainvoke({"question": "q"}, config))
    issue = [i for i in state["issues"].values() if i.category == "wording"][0]
    assert issue.status == "open" and issue.draft_version >= 1
    # Plan revision 33 §4.39: a body redacted after its final review
    # is a substantive change the certificate no longer covers, so it
    # is delivered as an explicitly partial Level-B report and never
    # as complete_with_limitations.
    assert state["meta"].report_status == "incomplete"
    assert state["delivery"].level == "partial"
    assert "write:revise" in api.calls  # the cycle rewrote and re-reviewed


def test_review_loops_in_batches_until_nothing_material_is_left(tmp_path):
    runtime, api, worker, compiled = make(tmp_path)
    original = worker.__call__

    async def many_findings(work, rt, backend, on_event=None):
        result = await original(work, rt, backend, on_event)
        if work.task.kind != "map":
            extra = [fakes_finding(f"claim number {n}", n) for n in range(60)]
            result = result.model_copy(
                update={"findings": result.findings + extra}
            )
        return result

    def fakes_finding(statement, n):
        return records.FindingDraft(
            statement=statement,
            evidence_refs=["E1"],
            material=True,
            topics=["other"],
            questions=[8],
            entity=f"co{n}",
        )

    worker_fn = many_findings
    compiled = graph_module.build_graph(
        runtime,
        backend=object(),
        api=api,
        worker_fn=worker_fn,
        checkpointer=MemorySaver(),
    )
    config = persist.thread_config("t13")
    runtime.begin("t13")
    state = run(compiled.ainvoke({"question": "q"}, config))
    reviews = [c for c in api.calls if c == "review"]
    assert len(reviews) >= 3
    assert graph_module.review_remaining(state) == 0
    assert all(
        len(c) <= graph_module.REVIEW_BATCH
        for c in [graph_module.pending_review(state)]
    )


def test_inconsistent_final_review_without_issues_fails_closed(tmp_path):
    runtime, api, _, compiled = make(tmp_path)

    async def final_review(state, max_turns, deadline):
        del state, max_turns, deadline
        api.calls.append("final")
        return (
            records.DraftReview(
                issues=[], consistent=False, summary="tables disagree"
            ),
            USAGE,
        )

    api.final_review = final_review
    config = persist.thread_config("t14")
    runtime.begin("t14")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert state["meta"].report_status != "complete"
    assert any(
        i.target == "draft" and i.status == "open"
        for i in state["issues"].values()
    )


def test_editor_citations_of_unreviewed_claims_are_rejected(tmp_path):
    runtime, api, _, compiled = make(tmp_path)
    api.review_verdict = "supported"
    original_write = api.write

    async def write(state, instructions, max_turns, deadline, owner=False):
        unreviewed = [
            c.id for c in state["claims"].values() if c.review == "unreviewed"
        ]
        target = unreviewed[0] if unreviewed else "C999"
        api.draft_text = f"结论 [C1]。另一句 [{target}]。"
        return await original_write(state, instructions, max_turns, deadline)

    api.write = write
    config = persist.thread_config("t15")
    runtime.begin("t15")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert any(
        i.category == "unsupported" and "cites" in i.description
        for i in state["issues"].values()
    )


def test_initial_state_records_the_fixture():
    payload = graph_module.initial_state("q", records.Limits(), fixture="tmp/f")
    assert payload["meta"].fixture == "tmp/f"
    assert (
        graph_module.initial_state("q", records.Limits())["meta"].fixture
        is None
    )


def test_pending_review_orders_by_citability_priority():
    limits = records.Limits()
    del limits
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="other",
            kind="fact",
            material=True,
            questions=[7],
        ),
        "C2": records.Claim(
            id="C2",
            statement="central",
            kind="fact",
            material=True,
            questions=[3],
        ),
        "C3": records.Claim(
            id="C3",
            statement="map",
            kind="fact",
            material=True,
            map_ref="stage:upstream",
            questions=[1],
        ),
        "C4": records.Claim(
            id="C4", statement="immaterial", kind="fact", material=False
        ),
    }
    assert graph_module.pending_review({"claims": claims}) == ["C3", "C2", "C1"]


def test_dispatch_worker_input_caps_the_session_at_limits_max_turns(tmp_path):
    runtime, _, worker, compiled = make(tmp_path)
    config = persist.thread_config("t16")
    runtime.begin("t16")
    run(compiled.ainvoke({"question": "q"}, config))
    assert worker.calls, "workers ran"
    first = worker.calls[0]
    assert first.allowance.turns == runtime.limits.attempt_turns() == 34
    assert first.max_turns == runtime.limits.max_turns == 12


def test_pending_review_interleaves_map_and_central_questions():
    def claim(cid, **kw):
        return records.Claim(id=cid, statement=cid, kind="fact", **kw)

    claims = {
        "C1": claim("C1", material=True, questions=[7]),
        "C2": claim("C2", material=True, questions=[4]),
        "C3": claim("C3", material=True, map_ref="P1", questions=[3]),
        "C4": claim("C4", material=True, questions=[4, 5]),
        "C5": claim("C5", material=True, map_ref="P2", questions=[3]),
        "C6": claim("C6", material=True, questions=[2]),
        "C7": claim("C7", material=False),
    }
    order = graph_module.pending_review({"claims": claims})
    # map, q2, q4, then the next of each queue, then the non-central.
    assert order == ["C3", "C6", "C2", "C5", "C4", "C1"]


def test_scope_review_drops_out_of_batch_relationship_and_source_verdicts():
    state = {
        "claims": {
            "C1": records.Claim(
                id="C1",
                statement="a",
                kind="fact",
                material=True,
                evidence_ids=["E1"],
            ),
            "C2": records.Claim(
                id="C2",
                statement="b",
                kind="fact",
                material=True,
                evidence_ids=["E2"],
            ),
        },
        "evidence": {
            "E1": records.Evidence(
                id="E1",
                source_id="S1",
                kind="snippet",
                excerpt="x",
                locator="l",
                extraction="search_snippet",
                task_id="T",
                retrieved_at=NOW,
            ),
            "E2": records.Evidence(
                id="E2",
                source_id="S2",
                kind="snippet",
                excerpt="y",
                locator="l",
                extraction="search_snippet",
                task_id="T",
                retrieved_at=NOW,
            ),
        },
        "relationships": {
            "R1": records.Relationship(
                id="R1",
                claim_id="C1",
                from_entity="a",
                to_entity="b",
                relation="supplies",
                evidence_ids=["E1"],
            ),
            "R2": records.Relationship(
                id="R2",
                claim_id="C2",
                from_entity="a",
                to_entity="c",
                relation="supplies",
                evidence_ids=["E2"],
            ),
        },
    }
    hostile = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1", verdict="supported", reason="r"
            ),
            records.ClaimVerdict(
                claim_id="C2", verdict="supported", reason="r"
            ),
        ],
        relationships=[
            records.RelationshipVerdict(
                relationship_id="R1", supported=True, reason="r"
            ),
            records.RelationshipVerdict(
                relationship_id="R2", supported=True, reason="r"
            ),
            records.RelationshipVerdict(
                relationship_id="R9", supported=True, reason="r"
            ),
        ],
        sources=[
            records.SourceOriginJudgement(
                source_id="S1", origin="primary", reason="r"
            ),
            records.SourceOriginJudgement(
                source_id="S2", origin="primary", reason="r"
            ),
        ],
    )
    scoped = graph_module.scope_review(state, hostile, ["C1"])
    assert [v.claim_id for v in scoped.claims] == ["C1"]
    assert [v.relationship_id for v in scoped.relationships] == ["R1"]
    assert [v.source_id for v in scoped.sources] == ["S1"]
    applied = merge.apply_review(state, scoped)
    assert applied["claims"]["C2"].review == "unreviewed"
    assert not applied["relationships"]["R2"].confirmed


def test_findings_citing_unreviewed_claims_are_dropped(tmp_path):
    runtime, api, _, compiled = make(tmp_path)
    original = api.analyze

    async def analyze(state, note, max_turns, deadline):
        out, usage = await original(state, note, max_turns, deadline)
        unreviewed = [
            c.id for c in state["claims"].values() if c.review == "unreviewed"
        ]
        if unreviewed and out.findings:
            spec = out.findings[0].model_copy(
                update={"claim_ids": out.findings[0].claim_ids + unreviewed[:1]}
            )
            out = out.model_copy(update={"findings": [spec] + out.findings[1:]})
        return out, usage

    api.analyze = analyze
    config = persist.thread_config("t17")
    runtime.begin("t17")
    state = run(compiled.ainvoke({"question": "q"}, config))
    reviewed = {
        c.id
        for c in state["claims"].values()
        if c.review in ("supported", "qualified")
    }
    assert all(set(f.claim_ids) <= reviewed for f in state["findings"].values())


def test_initial_state_records_the_fixture_digest():
    payload = graph_module.initial_state(
        "q", records.Limits(), fixture="tmp/f", fixture_digest="abc"
    )
    assert payload["meta"].fixture_digest == "abc"


def test_check_citations_covers_table_rows_and_list_items():
    claims = {
        "C1": records.Claim(
            id="C1", statement="s", kind="fact", review="supported"
        )
    }
    section = records.Section(
        id="cmp",
        title="对比",
        text=(
            "| 公司 | 2025收入 |\n|---|---|\n| HOYA | 999亿元 |\n"
            "| DNP | 500亿元 [C1] |\n\n- 清溢光电产能翻倍\n- 路维光电 [C1]\n"
        ),
        claim_ids=["C1"],
    )
    problems = report.check_citations(
        [section], claims, ["清溢光电", "路维光电"]
    )
    texts = [p.description for p in problems]
    assert any("999亿元" in t for t in texts)
    assert any("清溢光电" in t for t in texts)
    assert not any(
        "DNP" in t or "路维光电" in t or "2025收入" in t for t in texts
    )


def test_scope_review_drops_contradictions_and_acquisitions_outside_batch():
    state = {
        "claims": {
            "C1": records.Claim(
                id="C1", statement="a", kind="fact", material=True
            ),
            "C2": records.Claim(
                id="C2", statement="b", kind="fact", material=True
            ),
        },
        "evidence": {},
        "relationships": {},
    }
    hostile = records.ClaimReview(
        contradictions=["C1 and C7 disagree on size", "C2 contradicts C9"],
        acquisitions=[
            records.AcquisitionRequest(
                objective="get C1 original", claim_id="C1"
            ),
            records.AcquisitionRequest(
                objective="get C2 original", claim_id="C2"
            ),
            records.AcquisitionRequest(objective="anything", claim_id=None),
        ],
    )
    scoped = graph_module.scope_review(state, hostile, ["C1"])
    assert scoped.contradictions == ["C1 and C7 disagree on size"]
    assert [r.claim_id for r in scoped.acquisitions] == ["C1"]


def test_reviewed_map_rendering_omits_boundary_note_and_gaps():
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="上游",
                stage="upstream",
                description="d",
                claim_id="C1",
            )
        ],
        boundary_note="Unverified: 石英玻璃 belongs to this industry",
        gaps=["Unverified: no Chinese supplier exists"],
    )
    claims = {
        "C1": records.Claim(
            id="C1", statement="s", kind="map", review="supported", map_ref="G1"
        )
    }
    reviewed = roles.render_map(industry_map, claims)
    assert "Unverified" not in reviewed and "G1" in reviewed
    assert "Unverified" in roles.render_map(industry_map)


def test_unsupported_section_text_is_redacted_or_the_report_is_incomplete():
    claims = {
        "C1": records.Claim(
            id="C1", statement="s", kind="fact", review="supported"
        )
    }
    section = records.Section(
        id="intro",
        title="概览",
        text="市场规模为52亿元。结论 [C1]。",
        claim_ids=["C1"],
    )
    removable = records.Issue(
        id="I1",
        key="unsupported:intro",
        category="unsupported",
        severity="material",
        target="intro",
        description="uncited",
        requested_action="edit",
        text="市场规模为52亿元。",
    )
    state = {
        "brief": records.Brief(industry="光掩模", language="zh"),
        "claims": claims,
        "evidence": {},
        "sources": {},
        "sections": [section],
        "issues": {"I1": removable},
    }
    rendered = report.render(state, [], "complete_with_limitations")
    assert (
        "市场规模为52亿元" not in rendered
        and "已移除未经核实的表述" in rendered
    )
    assert "结论" in rendered
    coverage_rows = [
        records.Coverage(question=q, status="covered") for q in range(1, 9)
    ]
    assert (
        coverage.report_status(coverage_rows, state)
        == "complete_with_limitations"
    )
    vague = removable.model_copy(update={"text": None, "id": "I2"})
    state["issues"] = {"I2": vague}
    assert coverage.report_status(coverage_rows, state) == "incomplete"
    assert report.unremovable_section_issues(state) == [vague]


def test_calc_requests_and_acquisitions_are_bounded_per_call(tmp_path):
    limits = records.Limits(calc_requests_per_call=1, acquisition_executions=1)
    runtime, api, _, compiled = make(tmp_path, limits=limits)
    original_review = api.review_claims

    async def review_claims(state, claim_ids, max_turns, deadline):
        out, usage = await original_review(
            state, claim_ids, max_turns, deadline
        )
        extra = [
            records.AcquisitionRequest(objective=f"get {cid}", claim_id=cid)
            for cid in claim_ids
        ]
        return out.model_copy(update={"acquisitions": extra}), usage

    api.review_claims = review_claims
    config = persist.thread_config("t18")
    runtime.begin("t18")
    state = run(compiled.ainvoke({"question": "q"}, config))
    acquisitions = [
        t for t in state["tasks"].values() if t.kind == "acquisition"
    ]
    # Plan revision 38 §4.45.4: every request is recorded, the ceiling
    # bounds what becomes a task, and the rest are deferred with a
    # reason rather than truncated away.
    assert len(acquisitions) == 1
    assert len(state["repairs"]) > 1
    deferred = [r for r in state["repairs"].values() if r.status == "deferred"]
    assert deferred and all(r.reason for r in deferred)
    assert all(t.target is not None for t in acquisitions)


def test_acquisition_attempts_are_capped_for_the_run(tmp_path):
    limits = records.Limits(acquisition_executions=1)
    runtime, api, _, compiled = make(tmp_path, limits=limits)
    original_review = api.review_claims

    async def review_claims(state, claim_ids, max_turns, deadline):
        out, usage = await original_review(
            state, claim_ids, max_turns, deadline
        )
        extra = [
            records.AcquisitionRequest(objective=f"get {cid}", claim_id=cid)
            for cid in claim_ids[:3]
        ]
        return out.model_copy(update={"acquisitions": extra}), usage

    api.review_claims = review_claims
    config = persist.thread_config("t19")
    runtime.begin("t19")
    state = run(compiled.ainvoke({"question": "q"}, config))
    acquisition_tasks = [
        t for t in state["tasks"].values() if t.kind == "acquisition"
    ]
    executed = [t for t in acquisition_tasks if t.attempts > 0]
    assert len(executed) == 1
    # The ceiling now binds at creation, so the run never plans work it
    # will refuse; the requests it could not fund are on the record.
    assert len(acquisition_tasks) == 1
    assert any(
        r.status == "deferred" and "ceiling" in r.reason
        for r in state["repairs"].values()
    )


def test_non_material_map_claims_are_not_reviewable():
    claims = {
        "C1": records.Claim(
            id="C1", statement="m", kind="map", material=False, map_ref="P9"
        ),
        "C2": records.Claim(id="C2", statement="f", kind="fact", material=True),
    }
    state = {"claims": claims}
    assert graph_module.pending_review(state) == ["C2"]
    assert graph_module.review_remaining(state) == 1
    assert budget.review_batches(state, records.Limits()) == 1


def test_q6_needs_a_reviewed_participant_claim_for_the_region():
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="中游",
                stage="midstream",
                description="d",
                claim_id="C1",
            )
        ],
        participants=[
            records.Participant(
                id="P1",
                name="清溢光电",
                segment_id="G1",
                role="manufacturer",
                region="中国",
                selection_rationale="r",
                claim_id="C2",
            ),
            records.Participant(
                id="P2",
                name="HOYA",
                segment_id="G1",
                role="manufacturer",
                region="Japan",
                selection_rationale="r",
                claim_id="C3",
            ),
        ],
    )
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="s",
            kind="map",
            review="supported",
            map_ref="G1",
            material=True,
        ),
        "C2": records.Claim(
            id="C2",
            statement="p",
            kind="map",
            review="unreviewed",
            map_ref="P1",
            material=True,
        ),
        "C3": records.Claim(
            id="C3",
            statement="p",
            kind="map",
            review="supported",
            map_ref="P2",
            material=True,
        ),
    }
    view = coverage._View(  # pylint: disable=protected-access
        industry_map=industry_map,
        claims=claims,
        evidence={},
        versions={},
        findings=[],
        relationships={},
        issues=[],
    )
    assert view.entity_region("清溢光电") is None
    assert view.entity_region("HOYA") == "global"


def test_default_budget_keeps_analysis_and_delivery_reachable(tmp_path):
    """Attempts that each consume most of a reservation cannot crowd out
    review, analysis, coverage, writing and final review."""
    runtime, api, worker, compiled = make(tmp_path)
    worker.duration_s = 850.0
    config = persist.thread_config("t20")
    runtime.begin("t20")
    state = run(compiled.ainvoke({"question": "q"}, config))
    for call in ("review", "analyze", "assess", "write:full", "final"):
        assert call in api.calls, call
    assert state["meta"].report_status == "complete"
    spent = budget.ledger(state)
    assert spent.wall_clock_s <= runtime.limits.wall_clock_s


def test_every_unsupported_unit_in_a_section_is_redacted(tmp_path):
    # C0 round 13, finding 1: with two uncited sentences the first was
    # delivered as fact because both shared one issue key.
    runtime, api, _, compiled = make(tmp_path)
    api.draft_text = "本行业需求每年增长99%。行业利润率永久保持88%。结论 [C1]。"
    config = persist.thread_config("t20")
    runtime.begin("t20")
    state = run(compiled.ainvoke({"question": "q"}, config))
    units = {
        i.text
        for i in state["issues"].values()
        if i.status == "open" and i.target == "intro" and i.text
    }
    assert units == {"本行业需求每年增长99%。", "行业利润率永久保持88%。"}
    # Plan revision 33 §4.39: a body redacted after its final review
    # is a substantive change the certificate no longer covers, so it
    # is delivered as an explicitly partial Level-B report and never
    # as complete_with_limitations.
    assert state["meta"].report_status == "incomplete"
    assert state["delivery"].level == "partial"
    text = pathlib.Path(state["meta"].report_path).read_text(encoding="utf-8")
    heading = "## 局限性" if "## 局限性" in text else "## Limitations"
    body, _, rest = text.partition(heading)
    assert "99%" not in body and "88%" not in body and "结论" in body
    assert "99%" in rest and "88%" in rest  # both listed as limitations


def test_review_batch_size_follows_the_run_limits(tmp_path):
    # C0 round 13, finding 6: the graph used the module constant while
    # the budget used ``Limits.review_batch``.
    claims = {
        f"C{i}": records.Claim(
            id=f"C{i}",
            statement=f"s{i}",
            kind="fact",
            material=True,
            questions=[4],
        )
        for i in range(1, 21)
    }
    state = {"claims": claims}
    assert len(graph_module.pending_review(state)) == graph_module.REVIEW_BATCH
    limits = records.Limits(review_batch=20)
    assert len(graph_module.pending_review(state, limits.review_batch)) == 20
    assert budget.review_batches(state, limits) == 1
    runtime, api, _, compiled = make(tmp_path, records.Limits(review_batch=3))
    sizes: list[int] = []
    original = api.review_claims

    async def review_claims(state, claim_ids, max_turns, deadline):
        sizes.append(len(claim_ids))
        return await original(state, claim_ids, max_turns, deadline)

    api.review_claims = review_claims
    config = persist.thread_config("t21")
    runtime.begin("t21")
    state = run(compiled.ainvoke({"question": "q"}, config))
    reviewed = sum(
        1
        for c in state["claims"].values()
        if c.material and c.review != "unreviewed"
    )
    assert sizes and max(sizes) <= 3
    assert (
        len(sizes)
        >= -(-reviewed // 3)
        > -(-reviewed // graph_module.REVIEW_BATCH)
    )


def test_retired_issues_keep_redaction_and_never_make_a_report_complete():
    # C0 round 14, finding 1: an issue retired at the follow-up limit
    # dropped out of redaction and status, so its unit came back as fact.
    unit = "本行业需求每年增长99%。"
    section = records.Section(
        id="intro", title="概览", text=f"{unit}结论 [C1]。", claim_ids=["C1"]
    )
    retired = records.Issue(
        id="I1",
        key=merge.issue_key("unsupported", "intro", unit),
        category="unsupported",
        severity="material",
        target="intro",
        description=f"uncited sentence with a number: {unit}",
        requested_action="edit",
        attempts=2,
        status="unresolvable",
        resolution="follow-up limit",
        text=unit,
    )
    state = {
        "brief": records.Brief(industry="光掩模", language="zh"),
        "claims": {
            "C1": records.Claim(
                id="C1", statement="s", kind="fact", review="supported"
            )
        },
        "evidence": {},
        "sources": {},
        "sections": [section],
        "issues": {"I1": retired},
    }
    rendered = report.render(state, [], "complete_with_limitations")
    body = rendered.split("## 局限性", maxsplit=1)[0]
    assert "99%" not in body and "已移除未经核实的表述" in body
    assert "99%" in rendered  # still listed under limitations
    covered = [
        records.Coverage(question=q, status="covered") for q in range(1, 9)
    ]
    assert (
        coverage.report_status(covered, state, verified=True)
        == "complete_with_limitations"
    )
    vague = retired.model_copy(
        update={"id": "I2", "text": None, "key": "unsupported:intro"}
    )
    state["issues"] = {"I2": vague}
    assert coverage.report_status(covered, state, verified=True) == "incomplete"
    assert report.unremovable_section_issues(state) == [vague]


def test_follow_up_limit_is_enforced_at_task_admission_and_on_recurrence():
    # C0 round 14, finding 4: tasks kept being admitted for an exhausted
    # issue, and a retired unit reopened with a fresh allowance.
    limits = records.Limits()
    exhausted = records.Issue(
        id="I1",
        key="missing_evidence:Q4",
        category="missing_evidence",
        severity="material",
        target="Q4",
        description="no payer data",
        requested_action="research",
        attempts=limits.issue_follow_ups,
    )
    fresh = exhausted.model_copy(
        update={
            "id": "I2",
            "key": "missing_evidence:Q5",
            "target": "Q5",
            "attempts": 0,
        }
    )
    state = {
        "tasks": {},
        "issues": {"I1": exhausted, "I2": fresh},
        "evidence": {},
    }
    plan = roles.TaskPlan(
        tasks=[
            roles.TaskSpec(
                key="a", role="industry", objective="on I1", issue_id="I1"
            ),
            roles.TaskSpec(
                key="b", role="industry", objective="on I2", issue_id="I2"
            ),
            roles.TaskSpec(key="c", role="company", objective="free"),
        ]
    )
    tasks, issues, log = (
        graph_module._tasks_from_plan(  # pylint: disable=protected-access
            state, plan, 3, "follow_up", limits
        )
    )
    assert [t.objective for t in tasks.values()] == ["on I2", "free"]
    assert issues["I1"].attempts == limits.issue_follow_ups
    assert issues["I2"].attempts == 1
    assert any("works on I1" in line and "dropped" in line for line in log)
    # The conditional third attempt is honoured at admission too.
    productive = exhausted.model_copy(
        update={"evidence_added": True, "next_step": "fetch the filing"}
    )
    tasks, issues, _ = (
        graph_module._tasks_from_plan(  # pylint: disable=protected-access
            {**state, "issues": {"I1": productive}},
            plan,
            3,
            "follow_up",
            limits,
        )
    )
    assert issues["I1"].attempts == limits.issue_follow_ups + 1
    # A retired unit that recurs refreshes the retired issue, no new id.
    retired = exhausted.model_copy(
        update={"status": "unresolvable", "resolution": "limit"}
    )
    issues, again = merge.open_issue(
        {"I1": retired},
        "missing_evidence",
        "material",
        "Q4",
        "research",
        "again",
    )
    assert again.id == "I1" and again.status == "unresolvable"
    assert again.attempts == limits.issue_follow_ups and list(issues) == ["I1"]


def test_a_claim_a_live_calculation_consumes_is_still_cited():
    # C1 round 1, finding 1: an unsupported issue on a calculation input
    # closed as "claim no longer cited" while the derived number that
    # depended on it was still deliverable.
    quantity = support.bound(52, "亿元", "E1", "52亿元", period="2024")
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="Acme 2024 revenue was 52亿元",
            kind="fact",
            evidence_ids=["E1"],
            quantity=quantity,
            review="unsupported",
            material=True,
            partition="q4",
        ),
        "C3": records.Claim(
            id="C3",
            statement="share: 52.0 %",
            kind="derived",
            evidence_ids=["E1"],
            calculation_id="K1",
            review="supported",
            material=True,
            partition="q4",
        ),
    }
    calculation = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[support.cinput(claims["C1"])],
        formula="f",
        result=52.0,
        unit=support.unit("%"),
        status="ok",
    )
    issues, issue = merge.open_issue(
        {}, "unsupported", "material", "C1", "acquire", "no source"
    )
    state = {
        "claims": claims,
        "calculations": {"K1": calculation},
        "issues": issues,
        "findings": {},
        "sections": [],
        "coverage": [],
    }
    kept = graph_module.resolve_issues(state)
    assert kept["issues"][issue.id].status == "open"
    # Once the calculation is no longer current, nothing cites C1.
    state["calculations"]["K1"] = calculation.model_copy(
        update={"status": "error", "message": "stale_input: C1 changed"}
    )
    closed = graph_module.resolve_issues(state)
    assert closed["issues"][issue.id].status == "resolved"
    assert closed["issues"][issue.id].resolution == "claim no longer cited"


def test_one_review_batch_stales_everything_it_touched():
    # C1 round 2 (routed to C2), introduced by 5faf1c3: the review node
    # recomputed findings from the pre-cascade state, discarding what
    # the cascade had staled through a calculation. Staling for rejected
    # claims and staling through the cascade are now one pass over one
    # authority, so neither can drop the other.
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="an input",
            kind="fact",
            evidence_ids=["E1"],
            quantity=support.bound(52, "亿元", "E1", "52亿元"),
            review="supported",
            material=True,
            partition="q4",
        )
    }
    state = {
        "claims": {
            **claims,
            "C3": records.Claim(
                id="C3",
                statement="share: 52.0 %",
                kind="derived",
                evidence_ids=["E1"],
                calculation_id="K1",
                calculation_version=1,
                quantity=support.derived(52.0, "%"),
                review="supported",
                material=True,
                partition="q4",
            ),
            "C9": records.Claim(
                id="C9",
                statement="an unrelated claim",
                kind="fact",
                evidence_ids=["E1"],
                review="supported",
                material=True,
                partition="q4",
            ),
        },
        "calculations": {
            "K1": records.Calculation(
                id="K1",
                kind="share",
                label="share",
                inputs=[support.cinput(claims["C1"])],
                formula="f",
                result=52.0,
                unit=support.unit("%"),
                status="ok",
            )
        },
        "findings": {
            fid: records.Finding(
                id=fid,
                conclusion=fid,
                claim_ids=[cid],
                mechanism="m",
                implication="i",
                counterargument="c",
                uncertainty="u",
                monitor="mo",
                questions=[8],
            )
            for fid, cid in (("F1", "C3"), ("F2", "C9"))
        },
        "sections": [],
        "relationships": {},
    }
    applied = merge.apply_review(
        state,
        records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1", verdict="unsupported", reason="no source"
                ),
                records.ClaimVerdict(
                    claim_id="C9", verdict="unsupported", reason="no source"
                ),
            ]
        ),
    )
    # F1 goes stale through the calculation, F2 because its claim was
    # rejected; one call has to deliver both.
    assert applied["findings"]["F1"].status == "stale"
    assert applied["findings"]["F2"].status == "stale"
    assert applied["calculations"]["K1"].status == "error"
    assert applied["claims"]["C3"].review == "unreviewed"


def test_a_stale_derived_claim_is_not_offered_for_review():
    # C1 round 2, finding 1: review cannot settle it, only recomputation
    # can, so it must not consume a review slot either.
    measured = records.Claim(
        id="C1",
        statement="a measured claim",
        kind="fact",
        evidence_ids=["E1"],
        quantity=support.bound(52, "亿元", "E1", "52亿元"),
        review="unreviewed",
        material=True,
        partition="q4",
        questions=[4],
    )
    current = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[support.cinput(measured)],
        formula="f",
        result=52.0,
        unit=support.unit("%"),
        status="ok",
    )
    stopped = current.model_copy(
        update={
            "status": "error",
            "message": "stale_input: C1 changed after the calculation",
            "result": None,
            "unit": None,
        }
    )
    claims = {"C1": measured}
    # The derived claim is the projection of the calculation as it
    # stood, awaiting review.
    claims["C3"] = records.Claim(
        id="C3",
        kind="derived",
        material=True,
        partition="q4",
        questions=[4],
        **{
            **merge.derived_fields(current, claims),
            "review": "unreviewed",
            "review_reason": None,
        },
    )
    state = {"claims": claims, "calculations": {"K1": stopped}}
    assert graph_module.pending_review(state, 10) == ["C1"]
    assert graph_module.review_remaining(state) == 1
    # Current again, and agreeing with the claim: it queues normally.
    state["claims"]["C1"] = claims["C1"].model_copy(
        update={"review": "supported", "review_reason": None}
    )
    state["calculations"]["K1"] = current
    assert graph_module.pending_review(state, 10) == ["C3"]


def _withdrawn_input_state():
    """A derived claim awaiting review over an input the verifier rejected.

    Its calculation is still ``ok`` and still agrees with the claim, so
    ``calculation_current`` holds while ``producer_chain_intact`` does
    not: exactly the shape the C1 round-5 review routed to C2.
    """
    measured = records.Claim(
        id="C1",
        statement="a measured claim",
        kind="fact",
        evidence_ids=["E1"],
        quantity=support.bound(52, "亿元", "E1", "52亿元"),
        review="unsupported",
        material=True,
        partition="q4",
        questions=[4],
    )
    producer = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[
            support.cinput(measured.model_copy(update={"review": "supported"}))
        ],
        formula="f",
        result=52.0,
        unit=support.unit("%"),
        status="ok",
    )
    claims = {"C1": measured}
    claims["C3"] = records.Claim(
        id="C3",
        kind="derived",
        material=True,
        partition="q4",
        questions=[4],
        **{
            **merge.derived_fields(producer, claims),
            "review": "unreviewed",
            "review_reason": None,
        },
    )
    return {"claims": claims, "calculations": {"K1": producer}}


def test_a_withdrawn_input_never_asks_for_another_review_round(tmp_path):
    # C1 round 5, routed to C2: review_remaining counted a claim
    # pending_review would never hand over, so the router asked for a
    # batch the node found empty, released its reservation unused and
    # was routed back -- a cycle that charges nothing and ends only at
    # LangGraph's recursion limit, with no report.
    state = _withdrawn_input_state()
    assert merge.calculation_current(
        state["claims"]["C3"], state["claims"], state["calculations"]
    )
    assert not merge.producer_chain_intact(
        state["claims"]["C3"], state["claims"], state["calculations"]
    )
    assert graph_module.pending_review(state, 10) == []
    assert graph_module.review_remaining(state) == 0

    saver = MemorySaver()
    runtime, api, _, compiled = make(tmp_path, saver=saver)
    config = persist.thread_config("t-loop")
    seeded = {
        **state,
        "question": "q",
        "meta": graph_module.initial_state("q", runtime.limits)["meta"],
        "brief": roles.default_brief("q"),
        "phase": "researching",
        "review_rounds": 0,
    }
    run(compiled.aupdate_state(config, seeded, as_node="merge"))
    runtime.begin("t-loop")
    state = run(compiled.ainvoke(None, {**config, "recursion_limit": 200}))
    assert state["route_log"][:2] == [
        "reserve_review: review.1 reserved (10 turns)",
        "review: nothing unreviewed",
    ]
    assert "analyze" in api.calls  # the run went on instead of repeating
    reservations = [
        c for c in state["single_calls"].values() if c.task_id == "review"
    ]
    assert len(reservations) <= state["review_rounds"]
    assert state["meta"].execution_status == "completed"


def test_recomputation_stands_without_the_analysts_reservation(tmp_path):
    # Recomputing a stopped calculation is deterministic arithmetic, so
    # an analyze node that could not reserve a model call must still
    # write it: it used to log the recomputation and drop it.
    quantity = support.bound(52, "亿元", "E1", "52亿元", period="2024")
    parent = records.Claim(
        id="C1",
        statement="a measured claim",
        kind="fact",
        evidence_ids=["E1"],
        quantity=quantity,
        review="supported",
        material=True,
        partition="q4",
        questions=[4],
    )
    # Two distinct figures: a share of one over itself states nothing
    # and is refused before the division.
    whole = parent.model_copy(
        update={
            "id": "C0",
            "quantity": support.bound(
                104, "亿元", "E1", "104亿元", period="2024"
            ),
        }
    )
    claims = {"C0": whole, "C1": parent}
    request = records.CalcRequest(
        kind="share",
        label="share",
        numerator_claim_id="C1",
        denominator_claim_id="C0",
    )
    producer = calc.compute("K1", request, calc.inputs_from_claims(claims, {}))
    claims["C2"] = records.Claim(
        id="C2",
        kind="derived",
        material=True,
        partition="q4",
        questions=[4],
        origin="K1",
        **calc.derived_fields(producer, claims),
    )
    claims["C1"] = claims["C1"].model_copy(
        update={"review": "qualified", "review_reason": "sample only"}
    )
    stale = merge.cascade_changes(
        {"claims": claims, "calculations": {"K1": producer}}, {"C1"}, claims
    )
    claims, calculations = stale["claims"], stale["calculations"]
    assert calculations["K1"].status == "error"

    runtime, api, _, compiled = make(tmp_path)
    api.calls.clear()
    state = {
        "claims": claims,
        "calculations": calculations,
        "single_calls": {},
        "attempts": {},
        "issues": {},
        "analysis_rounds": 0,
        "meta": graph_module.initial_state("q", runtime.limits)["meta"],
    }
    node = compiled.nodes["analyze"].node
    update = run(node.steps[0].afunc(state))
    assert "analyze" not in api.calls  # no reservation, no model call
    assert update["calculations"]["K1"].status == "ok"
    assert merge.citable(
        update["claims"]["C2"], update["claims"], update["calculations"]
    )


def test_the_follow_up_allowance_is_spent_within_one_plan():
    # C0 round 14, finding 4, second half: the allowance was read once
    # for the whole plan, so several tasks naming one open issue all
    # passed admission and the issue ended past its limit.
    limits = records.Limits()
    issue = records.Issue(
        id="I1",
        key="missing_evidence:Q4",
        category="missing_evidence",
        severity="material",
        target="Q4",
        description="no payer data",
        requested_action="research",
    )
    plan = roles.TaskPlan(
        tasks=[
            roles.TaskSpec(
                key=f"k{n}",
                role="industry",
                objective=f"on I1 #{n}",
                issue_id="I1",
            )
            for n in range(limits.issue_follow_ups + 2)
        ]
    )
    tasks, issues, log = (
        graph_module._tasks_from_plan(  # pylint: disable=protected-access
            {"tasks": {}, "issues": {"I1": issue}, "evidence": {}},
            plan,
            len(plan.tasks),
            "follow_up",
            limits,
        )
    )
    assert len(tasks) == limits.issue_follow_ups
    assert issues["I1"].attempts == limits.issue_follow_ups
    assert graph_module.followups_exhausted(issues["I1"], limits)
    assert sum("works on I1" in line for line in log) == 2


def test_a_role_deadline_charges_its_reservation_and_the_run_delivers(
    tmp_path,
):
    # A single call that misses its deadline is cancelled by the
    # adapter; the graph used to let RoleTimeout end the whole run, so
    # everything already collected went undelivered.
    runtime, api, _, compiled = make(tmp_path)

    async def analyze(state, note, max_turns, deadline):
        del state, note, max_turns
        api.calls.append("analyze")
        raise crew.RoleTimeout(f"Analyst exceeded {deadline:.0f} s")

    api.analyze = analyze
    config = persist.thread_config("t-deadline")
    runtime.begin("t-deadline")
    state = run(compiled.ainvoke({"question": "q"}, config))
    calls = [
        c for c in state["single_calls"].values() if c.task_id == "analyze"
    ]
    failed = [c for c in calls if c.status == "failed"]
    assert failed
    assert all(c.observed.turns == 0 for c in calls if c.status == "done")
    assert all(
        budget.attempt_charge(c).turns == c.reserved.turns for c in failed
    )
    assert any("RoleTimeout" in line for line in state["route_log"])
    assert state["meta"].execution_status == "completed"
    assert state["meta"].report_status in (
        "complete_with_limitations",
        "incomplete",
    )


@pytest.mark.parametrize("error_type", [crew.RoleTimeout, crew.RoleFailure])
def test_empty_body_after_failed_write_cannot_be_verified_complete(
    tmp_path, error_type
):
    runtime, api, _, compiled = make(tmp_path, floor=coverage.UsefulnessFloor())

    async def fail(*args, **kwargs):
        del args, kwargs
        raise error_type("offline write failure")

    api.write = fail
    runtime.begin("empty-body")
    state = run(
        compiled.ainvoke({"question": "q"}, persist.thread_config("empty-body"))
    )
    assert all(
        row.status == "covered"
        for row in coverage.derive(state, state.get("assessment"))
    ), "the registry alone could have passed the old fast path"
    assert state["sections"] == []
    assert state["delivery"].level == "diagnostic_only"
    assert state["meta"].report_status == "incomplete"
    assert state.get("final_review") is None
    assert "final" not in api.calls
    attempt = state["single_calls"]["final_review.1"]
    assert attempt.status == "done" and attempt.observed.turns == 0
    assert attempt.invoked_at is None


def test_nonempty_placeholder_cannot_borrow_registry_coverage(tmp_path):
    runtime, api, _, compiled = make(tmp_path, floor=coverage.UsefulnessFloor())
    api.draft_text = "Overview."
    runtime.begin("placeholder")
    state = run(
        compiled.ainvoke(
            {"question": "q"}, persist.thread_config("placeholder")
        )
    )
    assert all(
        row.status == "covered"
        for row in coverage.derive(state, state.get("assessment"))
    )
    assert state["final_review"].consistent
    assert state["delivery"].level == "diagnostic_only"
    assert state["meta"].report_status == "incomplete"
    assert all(row.status == "uncovered" for row in state["coverage"])
    assert state["coverage"] == coverage.delivery_coverage(state, [])


def test_withheld_body_keeps_reviewed_appendix_and_releases_held_usage(
    tmp_path,
):
    runtime, _, _, compiled = make(tmp_path, floor=coverage.UsefulnessFloor())
    runtime.begin("withheld")
    state = run(
        compiled.ainvoke({"question": "q"}, persist.thread_config("withheld"))
    )
    assert state["delivery"].status == "complete"
    frozen = state["review_subject"].appendix
    state["issues"] = {
        "I99": records.Issue(
            id="I99",
            key="post-review-objection",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="remove",
            description="Unresolved scope requires withholding this section",
            draft_version=state["draft_version"],
        )
    }
    state["candidate"] = None
    state["single_calls"] = {
        "final_review.99": records.Attempt(
            id="final_review.99",
            task_id="final_review",
            started_at=records.now_iso(),
            reserved=records.Reservation(
                turns=10, tool_calls=0, seconds=480, held=True
            ),
        )
    }
    delivered = run(compiled.nodes["deliver"].node.steps[0].afunc(state))
    assert delivered["delivery"].level == "diagnostic_only"
    assert delivered["coverage"] == coverage.delivery_coverage(state, [])
    assert delivered["delivery"].drift
    assert state["review_subject"].appendix == frozen
    text = pathlib.Path(delivered["meta"].report_path).read_text(
        encoding="utf-8"
    )
    assert all(part in text for part in frozen)
    released = delivered["single_calls"]["final_review.99"]
    assert released.status == "done" and not released.reserved.held
    assert released.observed.cost_usd == 0
    assert released.observed.complete
    assert released.observed.cost_basis == "not_invoked"


@pytest.mark.parametrize("known_usage", [False, True])
def test_terminal_role_failure_settles_and_delivers_without_unchanged_retry(
    tmp_path, monkeypatch, known_usage
):
    runtime, api, _, compiled = make(tmp_path)
    result = claude_agent_sdk.ResultMessage(
        subtype="error_max_structured_output_retries",
        duration_ms=10,
        duration_api_ms=9,
        is_error=True,
        num_turns=7,
        session_id="offline",
        total_cost_usd=0.25,
        usage={
            "input_tokens": 11,
            "output_tokens": 13,
            "cache_read_input_tokens": 17,
            "cache_creation_input_tokens": 19,
        },
    )
    invocations = []

    async def query(**kwargs):
        del kwargs
        invocations.append("sdk")
        if known_usage:
            yield result
        raise claude_agent_sdk.ResultError(
            "exhausted", dataclasses.asdict(result) if known_usage else {}
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    api.analyze = graph_module.LiveRoles(runtime.admission).analyze
    config = persist.thread_config("terminal-failure")
    runtime.begin("terminal-failure")
    state = run(compiled.ainvoke({"question": "q"}, config))
    attempts = [
        c for c in state["single_calls"].values() if c.task_id == "analyze"
    ]
    failed = [c for c in attempts if c.status == "failed"]
    assert len(failed) == len(invocations) == 1, "\n".join(state["route_log"])
    attempt = failed[0]
    assert attempt.queued_at <= attempt.admitted_at <= attempt.kickoff_at
    assert attempt.kickoff_at <= attempt.invoked_at <= attempt.finished_at
    assert attempt.observed.unknown is not known_usage
    assert attempt.observed.turns == (7 if known_usage else 0)
    assert attempt.observed.cost_usd == (0.25 if known_usage else None)
    assert budget.attempt_charge(attempt).turns == (
        7 if known_usage else attempt.reserved.turns
    )
    assert len(state["stage_inputs"]["analyze"]) == 1
    assert any("schema: RoleFailure" in line for line in state["route_log"])
    assert state["meta"].execution_status == "completed"
    assert not runtime.admission.live()


@pytest.mark.parametrize(
    ("node", "action"),
    [("analyze", "analyze"), ("write", "edit"), ("write", "remove")],
)
@pytest.mark.parametrize("changed", ["text", "support"])
def test_failure_guard_allows_changed_support_or_concrete_correction(
    tmp_path, node, action, changed
):
    runtime, api, _, compiled = make(tmp_path)
    state = graph_module.initial_state("fixture", runtime.limits)
    state["brief"] = roles.default_brief("fixture")
    calls = []

    async def fail(*args, **kwargs):
        del args, kwargs
        calls.append(node)
        raise crew.RoleFailure("exhausted")

    setattr(api, node, fail)
    issue = records.Issue(
        id="I1",
        key="first",
        category="weak_inference",
        severity="material",
        target="economics",
        requested_action=action,
        text="Prices will certainly grow.",
        description="Qualify certainty.",
    )

    def invoke(current, objection, number):
        current = {**current, "issues": {objection.id: objection}}
        key = f"{node}.{number}"
        current["single_calls"] = {
            **current.get("single_calls", {}),
            key: records.Attempt(
                id=key,
                task_id=node,
                started_at=records.now_iso(),
                reserved=records.Reservation(
                    turns=10, tool_calls=0, seconds=480
                ),
            ),
        }
        update = run(compiled.nodes[node].node.steps[0].afunc(current))
        return {**current, **update}

    state = invoke(state, issue, 1)
    cosmetic = issue.model_copy(
        update={"id": "I2", "description": "Other words."}
    )
    state = invoke(state, cosmetic, 2)
    assert calls == [node]
    assert state["single_calls"][f"{node}.1"].status == "failed"
    assert state["single_calls"][f"{node}.2"].observed.turns == 0
    if changed == "support":
        state["evidence"] = {"E1": passage("E1", "S1", "new passage")}
    else:
        cosmetic = cosmetic.model_copy(
            update={"text": "Demand certainly doubled."}
        )
    state = invoke(state, cosmetic, 3)
    assert calls == [node, node]
    assert state["single_calls"][f"{node}.1"].status == "failed"
    assert state["single_calls"][f"{node}.3"].status == "failed"


def test_failed_final_review_cannot_approve_rewrite_or_lose_prior_candidate(
    tmp_path,
):
    runtime, api, _, compiled = make(tmp_path)
    runtime.begin("review-failure")
    original = run(
        compiled.ainvoke(
            {"question": "q"}, persist.thread_config("review-failure")
        )
    )
    assert report.certificate_applies(original)
    candidate = records.DeliveryCandidate(
        sections=original["sections"],
        subject=original["review_subject"],
        review=original["final_review"],
        draft_version=original["draft_version"],
        issues=original["issues"],
        level=original["delivery"].level,
        status=original["delivery"].status,
    )
    state = {
        **original,
        "candidate": candidate,
        "draft_version": original["draft_version"] + 1,
        "sections": [
            records.Section(id="replacement", title="New", text="Unreviewed.")
        ],
        "single_calls": {
            "final_review.99": records.Attempt(
                id="final_review.99",
                task_id="final_review",
                started_at=records.now_iso(),
                reserved=records.Reservation(
                    turns=10, tool_calls=0, seconds=480
                ),
            )
        },
    }

    async def fail(*args):
        del args
        raise crew.RoleFailure("no structured output")

    api.final_review = fail
    update = run(compiled.nodes["final_review"].node.steps[0].afunc(state))
    state.update(update)
    assert state["single_calls"]["final_review.99"].status == "failed"
    assert not report.certificate_applies(state)
    delivered = run(compiled.nodes["deliver"].node.steps[0].afunc(state))
    assert delivered["delivery"].level == original["delivery"].level
    text = pathlib.Path(delivered["meta"].report_path).read_text(
        encoding="utf-8"
    )
    assert "Unreviewed." not in text
    assert "reviewed draft" in delivered["delivery"].reason
    assert delivered["coverage"] == coverage.delivery_coverage(
        state, candidate.sections
    )
    assert delivered["coverage"] != coverage.delivery_coverage(
        state, state["sections"]
    )


@pytest.mark.parametrize("known", [False, True])
def test_failed_claim_review_does_not_repeat_its_unchanged_batch(
    tmp_path, known
):
    runtime, api, _, compiled = make(tmp_path, floor=coverage.UsefulnessFloor())
    calls = []
    actual_review = api.review_claims
    succeeding = False

    async def fail(state, claim_ids, max_turns, deadline):
        calls.append(roles.review_description(state, claim_ids))
        if succeeding:
            return await actual_review(state, claim_ids, max_turns, deadline)
        raise crew.RoleFailure(
            "exhausted", {"turns": 1, "cost_usd": 0.25} if known else None
        )

    api.review_claims = fail
    runtime.begin("review-batch-failure")
    state = run(
        compiled.ainvoke(
            {"question": "q"}, persist.thread_config("review-batch-failure")
        )
    )
    assert len(calls) == len(set(calls)) == 1
    assert state["meta"].execution_status == "completed"
    assert all(c.review == "unreviewed" for c in state["claims"].values())
    assert state["delivery"].level == "diagnostic_only"
    assert state["review_stalls"] == graph_module.REVIEW_STALLS
    assert len(state["stage_inputs"]["review:terminal_failure"]) == 1

    def invoke(current, number):
        key = f"review.{number}"
        current["single_calls"] = {
            **current["single_calls"],
            key: records.Attempt(
                id=key,
                task_id="review",
                started_at=records.now_iso(),
                reserved=records.Reservation(
                    turns=10, tool_calls=0, seconds=480
                ),
            ),
        }
        update = run(compiled.nodes["review"].node.steps[0].afunc(current))
        return {**current, **update}

    state["issues"] = {
        key: item.model_copy(update={"description": "Cosmetic change."})
        for key, item in state["issues"].items()
    }
    state = invoke(state, 998)
    assert len(calls) == 1
    assert state["single_calls"]["review.998"].observed.turns == 0
    pending = graph_module.pending_review(state, runtime.limits.review_batch)
    eid = state["claims"][pending[0]].evidence_ids[0]
    evidence = state["evidence"][eid]
    state["evidence"] = {
        **state["evidence"],
        eid: evidence.model_copy(
            update={"excerpt": evidence.excerpt + " New evidence."}
        ),
    }
    succeeding = True
    state = invoke(state, 999)
    assert len(calls) == len(set(calls)) == 2
    assert state["single_calls"]["review.999"].status == "done"
    assert state["single_calls"]["review.1"].status == "failed"
    assert state["review_stalls"] == 0


def test_a_whole_run_stays_well_inside_the_superstep_bound(tmp_path):
    # The bound must be a backstop, not something a heavy but legitimate
    # run can reach: twelve task executions, sixty extra claims a task,
    # six review batches and a remediation cycle.
    runtime, api, worker, _ = make(tmp_path)
    original = worker.__call__

    async def crowded(work, rt, backend, on_event=None):
        result = await original(work, rt, backend, on_event)
        if work.task.kind == "map":
            return result
        extra = [
            records.FindingDraft(
                statement=f"claim number {n}",
                evidence_refs=["E1"],
                material=True,
                topics=["other"],
                questions=[8],
                entity=f"co{n}",
            )
            for n in range(60)
        ]
        return result.model_copy(update={"findings": result.findings + extra})

    api.final_issues = [
        records.SectionIssue(
            section_id="intro",
            category="unsupported",
            severity="material",
            description="d",
        )
    ]
    compiled = graph_module.build_graph(
        runtime,
        backend=object(),
        api=api,
        worker_fn=crowded,
        checkpointer=MemorySaver(),
    )
    config = persist.thread_config("t-steps")
    runtime.begin("t-steps")

    async def count():
        steps = 0
        async for _ in compiled.astream(
            {"question": "q"}, config, stream_mode="values"
        ):
            steps += 1
        return steps

    steps = run(count())
    assert steps < persist.RECURSION_LIMIT / 3


def test_a_single_call_that_never_succeeds_is_stopped_by_the_ledger(tmp_path):
    # Single calls have no retry counter: a role that fails on every
    # resume is bounded only by what its lost reservations cost. That
    # bound has to exist and the run has to end honestly.
    saver = MemorySaver()
    runtime, api, _, compiled = make(tmp_path, saver=saver)
    api.scope_failures = 10_000
    limits = runtime.limits
    config = persist.thread_config("t-forever")
    payload = graph_module.initial_state("q", limits)
    runtime.begin("t-forever")
    refusals = []
    for _ in range(40):
        try:
            state = run(compiled.ainvoke(payload, config, durability="sync"))
            break
        except RuntimeError:
            snapshot = run(compiled.aget_state(config))
            pending = snapshot.next[0]
            config = persist.resume_config("t-forever", snapshot)
            updates = graph_module.resume_updates(
                snapshot.values, pending, limits
            )
            run(
                compiled.aupdate_state(config, updates, as_node="reserve_scope")
            )
            refusals += [
                line
                for line in updates["route_log"]
                if "budget exhausted" in line
            ]
            payload = None
            runtime.begin("t-forever")
    else:
        raise AssertionError("the failing call was never stopped")
    assert refusals  # the ledger, not a counter, is what stopped it
    assert api.calls.count("scope") < 10
    scope_calls = [
        c for c in state["single_calls"].values() if c.task_id == "scope"
    ]
    assert all(c.status == "unknown" for c in scope_calls)
    assert any(
        "deterministic defaults used" in line for line in state["route_log"]
    )
    assert state["meta"].execution_status == "completed"
    assert state["meta"].report_status == "incomplete"
    spent = budget.ledger(state)
    assert spent.turns <= limits.model_calls
    assert spent.wall_clock_s <= limits.wall_clock_s


def test_a_decimal_does_not_end_a_factual_unit():
    # Headline live run 4 (thread b9632d7d, 2026-09-08): every ASCII "."
    # was a sentence terminator, so "20.6%" cut one cited sentence into
    # fragments that had lost the citation standing at its end. 31 of
    # the 53 open material issues that run were such fragments.
    cited = (
        "全球掩模基板市场高度寡头垄断——豪雅份额超过60%，信越化学份额20.6%，"
        "AGC份额16.1%（较上年10.3%提升5.8个百分点）[C1]。"
    )
    share = (
        "2020年全球平板显示掩模版市场占有率20.13%，位居全球第二"
        "（仅次于Photronics 22.31%）[C1]。"
    )
    revenue = "Photronics FY2024营收约8.669亿美元（FY2023约8.921亿美元）[C1]。"
    for text in (cited, share, revenue):
        assert report.factual_units(text) == [text]


def test_a_cited_sentence_of_several_decimals_raises_no_citation_issue():
    # The same run's false "uncited sentence with a number" issues: the
    # sentence carries its [C1] once, at the end, where the fragments
    # could not see it.
    claims = {
        "C1": records.Claim(
            id="C1", statement="s", kind="fact", review="supported"
        )
    }
    section = records.Section(
        id="economics",
        title="经济性",
        text=(
            "全球掩模基板市场高度寡头垄断——豪雅份额超过60%，"
            "信越化学份额20.6%，AGC份额16.1%"
            "（较上年10.3%提升5.8个百分点）[C1]。\n"
            "Photronics FY2024营收约8.669亿美元[C1]。\n"
        ),
        claim_ids=["C1"],
    )
    assert not report.check_citations([section], claims, [])


def test_ordinary_sentence_boundaries_still_end_a_factual_unit():
    # The decimal rule must not swallow real boundaries: a period ends a
    # sentence everywhere except between two digits.
    assert report.factual_units("份额60%。产能翻倍。") == [
        "份额60%。",
        "产能翻倍。",
    ]
    assert report.factual_units("Revenue was 8.6. It fell in 2025.") == [
        "Revenue was 8.6.",
        "It fell in 2025.",
    ]
    assert report.factual_units("Growth stalled. 2024 was flat.") == [
        "Growth stalled.",
        "2024 was flat.",
    ]


def test_a_retention_approval_naming_no_body_section_is_recorded(tmp_path):
    # Plan revision 37 §4.44.3. The after arm's Verifier returned
    # `retainable: ['问题覆盖']` -- a Chinese title, and an appendix
    # one, where the role asks for section ids. It granted nothing, as
    # it should, and said nothing about it, which left an operator no
    # way to see that a retention basis had been thrown away.
    runtime, api, _, compiled = make(tmp_path)

    async def final_review(state, max_turns, deadline):
        del max_turns, deadline
        api.calls.append("final")
        return (
            records.DraftReview(
                issues=[],
                consistent=True,
                retainable=["问题覆盖", "intro"],
                units=[
                    records.UnitReview(
                        block_id=b.id,
                        version=b.version,
                        supported=True,
                        dependencies_complete=True,
                        reason="fixture judgment",
                    )
                    for s in state.get("sections", [])
                    for b in s.blocks
                ],
            ),
            USAGE,
        )

    api.final_review = final_review
    config = persist.thread_config("t-retainable")
    runtime.begin("t-retainable")
    state = run(compiled.ainvoke({"question": "q"}, config))
    rejected = [
        line
        for line in state["route_log"]
        if line.startswith("retainable_rejected:")
    ]
    assert len(rejected) == 1
    assert "'问题覆盖'" in rejected[0] and "intro" not in rejected[0]
    assert "draft 1" in rejected[0]
    # The valid id still stands; the invalid one is never guessed into
    # a section, and retention is granted only to what was frozen.
    assert report.retainable_sections(state) == {"intro"}


# --- targeted evidence repair (plan revision 38 §4.45) ---------------------


def repair_state(pending=3, claims=None):
    """A state after one review, with `pending` repairs requested."""
    claims = claims or {
        f"C{n}": records.Claim(
            id=f"C{n}",
            statement=f"claim {n}",
            kind="fact",
            review="qualified",
            review_reason="search snippet only",
            evidence_ids=["E1"],
            material=True,
        )
        for n in range(1, pending + 1)
    }
    return {
        "claims": claims,
        "relationships": {},
        "calculations": {},
        "issues": {},
        "coverage": [],
        "tasks": {},
        "attempts": {},
        "single_calls": {},
        "repairs": {},
        "evidence": {"E1": None},
        "meta": records.RunMeta(
            workflow_version="industry-v1",
            prompt_version="10.3",
            models={},
            limits=records.Limits(),
            started_at="2026-09-09T00:00:00+00:00",
        ),
    }


def requests_for(state):
    return [
        records.AcquisitionRequest(
            objective=f"original for {cid}", claim_id=cid
        )
        for cid in state["claims"]
    ]


def charged(state, seconds):
    """The state with one finished attempt that spent `seconds`."""
    return {
        **state,
        "tasks": {
            "T1": records.Task(
                id="T1",
                kind="research",
                role="industry",
                objective="o",
                status="done",
            )
        },
        "attempts": {
            "T1.1": records.Attempt(
                id="T1.1",
                task_id="T1",
                reserved=records.Reservation(
                    turns=2, tool_calls=2, seconds=seconds
                ),
                started_at="2026-09-09T00:00:00+00:00",
                status="done",
                observed=records.Usage(duration_s=seconds),
            )
        },
    }


def test_every_request_is_recorded_and_one_pair_runs_at_a_time():
    # 23 requests, nothing truncated, and exactly one repair pair
    # admitted: plan revision 39 §4.46.2 funds a repair together with
    # the review its attachment forces, and owns one at a time.
    state = repair_state(pending=23)
    limits = records.Limits()
    repairs, log = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    assert len(repairs) == 23 and log
    repairs, tasks, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, limits
    )
    admitted = [r for r in repairs.values() if r.status == "admitted"]
    deferred = [r for r in repairs.values() if r.status == "deferred"]
    assert len(admitted) == 1 and len(deferred) == 22
    assert len([t for t in tasks.values() if t.kind == "acquisition"]) == 1
    assert all(r.reason for r in deferred)
    assert any("one repair pair runs at a time" in r.reason for r in deferred)
    task = tasks[admitted[0].task_id]
    assert task.target is not None and task.target.claim_version == 1
    assert task.target.qualification == "search snippet only"


def test_a_repair_pair_costs_a_short_attempt_and_a_full_review():
    # The measured failure of revision 38: a 60-second session reserved
    # 900 seconds, so 757 free seconds funded nothing.
    limits = records.Limits()
    assert budget.repair_reservation_for(limits).seconds == 180.0
    assert budget.reservation_for(limits).seconds == 900.0
    seconds, turns = budget.repair_pair_cost(limits)
    assert seconds == 180.0 + limits.single_call_timeout_s
    assert turns == limits.attempt_turns() + limits.single_call_reserved()


def test_a_repair_is_admitted_only_when_its_review_fits_too():
    # Both halves or neither, across the run's budget.
    limits = records.Limits()
    base = repair_state(pending=1)
    admitted_anywhere = False
    for spent in (500, 1500, 2000, 2400, 2800, 3200):
        state = charged(base, spent)
        repairs, _ = graph_module.record_repairs(
            state, requests_for(state), state["claims"], 1
        )
        repairs, tasks, _ = graph_module.schedule_repairs(
            {**state, "repairs": repairs}, limits
        )
        created = [t for t in tasks.values() if t.kind == "acquisition"]
        fits = budget.admit_repair_pair(state, limits) > 0
        assert bool(created) == fits
        if created:
            admitted_anywhere = True
            left = budget.remaining(state, limits)
            seconds, turns = budget.repair_pair_cost(limits)
            assert left.seconds - limits.time_reserve_s >= seconds
            assert left.turns - limits.model_call_reserve >= turns
    assert admitted_anywhere


def test_the_earmark_holds_one_pair_back_from_broad_work():
    # An earmark of existing capacity: while the window is open, broad
    # dispatch and ordinary review cannot spend the last repair.
    limits = records.Limits()
    state = charged(repair_state(pending=1), 2000)
    assert budget.repair_earmark(state, limits) == budget.repair_pair_cost(
        limits
    )
    open_slots = budget.dispatchable(state, limits, False)
    closed = {**state, "repair_window": "closed"}
    assert budget.repair_earmark(closed, limits) == (0.0, 0)
    assert budget.dispatchable(closed, limits, False) >= open_slots
    used = {**state, "repair_window": "used"}
    assert budget.repair_earmark(used, limits) == (0.0, 0)


def test_a_repair_whose_target_moved_is_not_dispatched():
    # `dispatch` refuses it: the claim it was sent to repair has been
    # versioned since, so the question is no longer the live one.
    task = records.Task(
        id="T5",
        kind="acquisition",
        role="verifier",
        objective="o",
        target=records.RepairTarget(
            claim_id="C1", claim_version=1, statement="claim 1"
        ),
    )
    claims = repair_state(pending=1)["claims"]
    assert not graph_module.stale_repair(task, claims)
    moved = {"C1": claims["C1"].model_copy(update={"version": 2})}
    assert graph_module.stale_repair(task, moved)
    assert graph_module.stale_repair(task, {})
    ordinary = records.Task(
        id="T6", kind="research", role="industry", objective="o"
    )
    assert not graph_module.stale_repair(ordinary, moved)


def test_an_acquisition_without_a_target_is_not_a_task():
    tasks = {
        "T1": records.Task(
            id="T1", kind="acquisition", role="verifier", objective="o"
        )
    }
    validated = schedule.validate(tasks)
    assert validated["T1"].status == "skipped"
    assert "names no target" in (validated["T1"].skip_reason or "")


def test_a_repair_is_done_only_when_evidence_was_attached():
    state = repair_state(pending=1)
    request = records.RepairRequest(
        id="RQ1", claim_id="C1", status="admitted", task_id="T5"
    )
    state["repairs"] = {"RQ1": request}
    state["tasks"] = {
        "T5": records.Task(
            id="T5",
            kind="acquisition",
            role="verifier",
            objective="o",
            status="done",
        )
    }
    # The task ran and attached nothing.
    settled = graph_module.settle_repairs(state, {"claims": state["claims"]})
    assert settled["RQ1"].status == "dropped"
    assert "without attaching evidence" in settled["RQ1"].reason
    # The same task, with this attempt's attachment on the record. Only
    # the owning task's attempts count: another request for the same
    # target must not be credited with an attachment it did not make.
    after = {
        "claims": {
            "C1": state["claims"]["C1"].model_copy(update={"version": 2})
        },
        "route_log": [
            merge.ATTACHED_PREFIX + '{"attempt_id": "T5.1", "claim_id": "C1", '
            '"evidence_ids": ["E2"]}'
        ],
    }
    settled = graph_module.settle_repairs(state, after)
    assert settled["RQ1"].status == "done"
    other = records.RepairRequest(
        id="RQ2", claim_id="C1", status="admitted", task_id="T7"
    )
    state["repairs"] = {"RQ1": request, "RQ2": other}
    state["tasks"]["T7"] = records.Task(
        id="T7",
        kind="acquisition",
        role="verifier",
        objective="o",
        status="done",
    )
    settled = graph_module.settle_repairs(state, after)
    assert settled["RQ1"].status == "done"
    assert settled["RQ2"].status == "dropped"


def test_a_closed_request_does_not_suppress_a_later_one():
    # A review may legitimately ask again once an attempt attached
    # nothing; deduplicating terminal requests silenced the repeat.
    state = repair_state(pending=1)
    first, _ = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    assert len(first) == 1
    again, _ = graph_module.record_repairs(
        {**state, "repairs": first}, requests_for(state), state["claims"], 2
    )
    assert len(again) == 1  # still open: not asked twice
    closed = {
        rid: r.model_copy(update={"status": "dropped", "reason": "nothing"})
        for rid, r in first.items()
    }
    third, _ = graph_module.record_repairs(
        {**state, "repairs": closed}, requests_for(state), state["claims"], 3
    )
    assert len(third) == 2
    assert any(
        r.status == "pending" and r.review_round == 3 for r in third.values()
    )


def test_two_requests_for_one_target_do_not_both_run():
    state = repair_state(pending=1)
    twice = [
        records.AcquisitionRequest(objective="original for C1", claim_id="C1"),
        records.AcquisitionRequest(
            objective="the filing itself", claim_id="C1"
        ),
    ]
    repairs, _ = graph_module.record_repairs(state, twice, state["claims"], 1)
    assert len(repairs) == 2
    repairs, tasks, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, records.Limits()
    )
    assert len([t for t in tasks.values() if t.kind == "acquisition"]) == 1
    assert any(
        r.status == "deferred" and "already targets" in r.reason
        for r in repairs.values()
    )


def test_a_request_whose_target_stopped_being_repairable_is_closed():
    state = repair_state(pending=1)
    repairs, _ = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"material": False}
    )
    repairs, tasks, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, records.Limits()
    )
    assert not [t for t in tasks.values() if t.kind == "acquisition"]
    request = next(iter(repairs.values()))
    assert request.status == "dropped" and request.reason


def test_a_held_repair_review_is_activated_without_a_second_charge():
    # The §4.41 shape, applied to a repair: the review it forces is
    # taken with it and charged from that moment, then activated.
    limits = records.Limits()
    held = records.Attempt(
        id="review.2",
        task_id="review",
        status="running",
        reserved=records.Reservation(
            turns=limits.single_call_reserved(),
            tool_calls=0,
            seconds=limits.single_call_timeout_s,
            pair_id="T5.1",
            held=True,
        ),
        started_at="2026-09-09T00:00:00+00:00",
    )
    state = {"single_calls": {"review.2": held}}
    # A held allowance is not a running call: the router must not read
    # it as one, or another review round could never be asked for.
    assert graph_module.running_reservation(state, "review") is None
    reserve = graph_module.reserve_node("review", limits)
    update = run(reserve(state))
    activated = update["single_calls"]["review.2"]
    assert activated.reserved.held is False
    assert activated.reserved.pair_id == "T5.1"
    assert activated.reserved.seconds == limits.single_call_timeout_s
    assert any("activated" in line for line in update["route_log"])


def test_priority_puts_a_central_promotable_target_first():
    # Plan revision 39 §4.46.4: what the reader loses most by not
    # repairing, then how real the route to original context is.
    state = repair_state(pending=3)
    state["coverage"] = [
        records.Coverage(question=1, status="partial"),
        records.Coverage(question=8, status="covered"),
    ]
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"questions": [8]}
    )
    state["claims"]["C2"] = state["claims"]["C2"].model_copy(
        update={"questions": [1]}
    )
    state["claims"]["C3"] = state["claims"]["C3"].model_copy(
        update={"questions": [8], "milestone": "mass_production"}
    )
    requests = {
        cid: records.RepairRequest(
            id=f"RQ{n}", claim_id=cid, objective=f"o{n}", status="pending"
        )
        for n, cid in enumerate(("C1", "C2", "C3"), start=1)
    }
    ranked = sorted(
        requests.values(),
        key=lambda r: graph_module.repair_priority({**state}, r),
    )
    # C2 answers an uncovered central question; C3 carries a milestone;
    # C1 is neither.
    assert [r.claim_id for r in ranked] == ["C2", "C3", "C1"]


def test_a_speculative_repair_waits_behind_an_accessible_one():
    state = repair_state(pending=2)
    state["evidence"] = {
        "E1": records.Evidence(
            id="E1",
            source_id="S1",
            source_version_id="v1",
            excerpt="x",
            locator="l",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-09T00:00:00+00:00",
        ),
        "E2": records.Evidence(
            id="E2",
            source_id="S2",
            source_version_id=None,
            excerpt="y",
            locator="l",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-09T00:00:00+00:00",
        ),
    }
    state["sources"] = {
        "S1": records.Source(
            id="S1",
            canonical_url="https://a.example/x",
            title="a",
            kind="web_page",
        ),
        "S2": records.Source(id="S2", title="b", kind="web_page"),
    }
    state["source_versions"] = {
        "v1": records.SourceVersion(
            id="v1",
            source_id="S1",
            content_hash="h",
            blob_path="b",
            meta_path="m",
            final_url="u",
            content_type="text/html",
            size=1,
            retrieved_at="2026-09-09T00:00:00+00:00",
            extraction_version="v3",
        )
    }
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"evidence_ids": ["E2"]}
    )
    state["claims"]["C2"] = state["claims"]["C2"].model_copy(
        update={"evidence_ids": ["E1"]}
    )
    speculative = records.RepairRequest(
        id="RQ1", claim_id="C1", objective="find something"
    )
    accessible = records.RepairRequest(
        id="RQ2", claim_id="C2", objective="open the original"
    )
    ranked = sorted(
        [speculative, accessible],
        key=lambda r: graph_module.repair_priority(state, r),
    )
    assert [r.id for r in ranked] == ["RQ2", "RQ1"]


def test_the_completed_review_reaches_the_repair_decision():
    # The stale ledger of revision 38: `graph.review` decided against
    # the reservation the call no longer held, which is the difference
    # between admitting a repair and refusing one on all four saved
    # runs (plan revision 39 §4.46.0).
    limits = records.Limits()
    # 2,420 s charged rather than 2,600: the pre-draft audit reserves
    # 180 s of the pipeline, and this case is about the stale ledger,
    # not about where the boundary sits.
    state = charged(repair_state(pending=1), 2420)
    running = records.Attempt(
        id="review.1",
        task_id="review",
        status="running",
        reserved=records.Reservation(
            turns=limits.single_call_reserved(),
            tool_calls=0,
            seconds=limits.single_call_timeout_s,
        ),
        started_at="2026-09-09T00:00:00+00:00",
    )
    stale = {**state, "single_calls": {"review.1": running}}
    done = {
        **state,
        "single_calls": {
            "review.1": running.model_copy(
                update={
                    "status": "done",
                    "observed": records.Usage(turns=3, duration_s=175.2),
                }
            )
        },
    }
    assert budget.admit_repair_pair(stale, limits) == 0
    assert budget.admit_repair_pair(done, limits) > 0


def test_an_admitted_repair_does_not_wait_for_an_ordinary_slot():
    # Post-implementation finding 1: a pair admitted on its own terms
    # was then routed away because no 900-second slot was free -- and
    # at every recorded decision boundary there was none.
    limits = records.Limits()
    state = charged(repair_state(pending=1), 2600)
    repairs, _ = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    repairs, tasks, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, limits
    )
    task = next(t for t in tasks.values() if t.kind == "acquisition")
    ready = [task]
    assert budget.dispatchable({**state, "tasks": tasks}, limits, False) == 0
    assert graph_module.can_start({**state, "tasks": tasks}, limits, ready)
    # An ordinary task alone at the same budget point does not start.
    ordinary = records.Task(
        id="T7", kind="research", role="industry", objective="o"
    )
    assert not graph_module.can_start(
        {**state, "tasks": tasks}, limits, [ordinary]
    )


def test_the_funded_review_takes_the_repaired_target_first():
    # Post-implementation finding 2: the queue's ordinary order could
    # spend every funded batch elsewhere and leave the repaired claim
    # withdrawn, with its review already paid for.
    state = repair_state(pending=12)
    for n in range(1, 13):
        state["claims"][f"C{n}"] = state["claims"][f"C{n}"].model_copy(
            update={
                "review": "unreviewed",
                "review_reason": None,
                "questions": [1],
            }
        )
    target = "C12"
    state["repairs"] = {
        "RQ1": records.RepairRequest(
            id="RQ1",
            claim_id=target,
            status="done",
            reason="evidence attached",
        )
    }
    assert graph_module.repaired_awaiting_review(state) == [target]
    batch = graph_module.pending_review(state, 10)
    assert batch[0] == target and len(batch) == 10
    assert len(set(batch)) == len(batch)
    # Once it has its verdict it is an ordinary claim again.
    state["claims"][target] = state["claims"][target].model_copy(
        update={"review": "supported"}
    )
    assert not graph_module.repaired_awaiting_review(state)
    assert graph_module.pending_review(state, 10)[0] != target


def test_one_pair_stays_outstanding_across_scheduling_calls():
    # Finding 3: `admitted_now` counted one invocation, so a second
    # call, or a retry, could open a second pair.
    limits = records.Limits()
    state = charged(repair_state(pending=3), 1500)
    repairs, _ = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    repairs, tasks, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, limits
    )
    assert len([t for t in tasks.values() if t.kind == "acquisition"]) == 1
    again, tasks_again, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs, "tasks": tasks}, limits
    )
    assert (
        len([t for t in tasks_again.values() if t.kind == "acquisition"]) == 1
    )
    assert any(
        r.status == "deferred" and "one repair pair" in r.reason
        for r in again.values()
    )


def test_a_deferral_names_the_dimension_admission_refused_on():
    # Finding 5: the explanation subtracted nothing downstream, so it
    # could blame executions for a refusal about seconds.
    limits = records.Limits()
    state = charged(repair_state(pending=1), 3300)
    assert budget.admit_repair_pair(state, limits) == 0
    assert budget.repair_shortfall(state, limits) == "seconds"
    repairs, _ = graph_module.record_repairs(
        state, requests_for(state), state["claims"], 1
    )
    repairs, _, _ = graph_module.schedule_repairs(
        {**state, "repairs": repairs}, limits
    )
    request = next(iter(repairs.values()))
    assert request.status == "deferred" and "seconds:" in request.reason


def test_anacquisition_route_claims_only_what_the_record_shows():
    # Finding 6: "not a URL" ranked as a fetch route, and a passage
    # with a matching version ranked as the strongest one.
    state = repair_state(pending=1)
    claim = state["claims"]["C1"]
    state["evidence"] = {
        "E1": records.Evidence(
            id="E1",
            source_id="S1",
            source_version_id=None,
            excerpt="x",
            locator="l",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-09T00:00:00+00:00",
        )
    }
    state["sources"] = {
        "S1": records.Source(id="S1", title="a", kind="web_page")
    }
    state["source_versions"] = {}
    bogus = records.RepairRequest(id="RQ1", claim_id="C1", url="not a URL")
    assert graph_module.acquisition_route(state, claim, bogus) == 2
    real = records.RepairRequest(
        id="RQ2", claim_id="C1", url="https://a.example/doc"
    )
    assert graph_module.acquisition_route(state, claim, real) == 1


def test_a_dispatched_repair_is_visible_in_the_trace():
    # The CLI counts started attempts by looking for "admitted" in the
    # dispatch log, so a repair that did not say it would have read as
    # "0 attempts started" while it ran.
    limits = records.Limits()
    line = (
        f"dispatch: T5.1 admitted, reserved "
        f"{limits.repair_timeout_s:.0f}s with review.3 held for the "
        "review it forces"
    )
    assert "admitted" in line
    rendered = trace.render_update(
        "dispatch", {"route_log": [line]}, {"tasks": {}, "attempts": {}}
    )
    assert rendered == ["DISPATCH: 1 attempts started"]


def test_delivery_writes_the_pdf_beside_the_markdown(tmp_path):
    """Plan §4.47: the formatted copy is rendered after the gate."""
    runtime, _, _, compiled = make(tmp_path)
    config = persist.thread_config("t1")
    runtime.begin("t1")
    state = run(compiled.ainvoke({"question": "光掩模产业调研"}, config))
    written = tmp_path / "reports" / "t1.pdf"
    assert written.is_file()
    assert written.read_bytes().startswith(b"%PDF")
    assert f"deliver: pdf {written}" in state["route_log"]
    assert pdf_module.pdf_beside(state["meta"].report_path) == str(written)


def test_a_failed_pdf_render_costs_the_reader_nothing_but_the_pdf(
    tmp_path, monkeypatch
):
    """Typography never decides what was verified.

    The Markdown report, its path and its status are the delivered
    artifact; a broken renderer is recorded in the route log and
    changes none of them.
    """
    monkeypatch.setattr(
        pdf_module,
        "write_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no space")),
    )
    runtime, _, _, compiled = make(tmp_path)
    config = persist.thread_config("t1")
    runtime.begin("t1")
    state = run(compiled.ainvoke({"question": "光掩模产业调研"}, config))
    meta = state["meta"]
    assert meta.execution_status == "completed"
    assert meta.report_status == "complete"
    assert state["delivery"].level == "verified"
    assert meta.report_path == str(tmp_path / "reports" / "t1.md")
    assert (tmp_path / "reports" / "t1.md").is_file()
    assert not (tmp_path / "reports" / "t1.pdf").exists()
    assert (
        "deliver: pdf rendering failed, the Markdown report stands "
        "(OSError: no space)" in state["route_log"]
    )
    assert pdf_module.pdf_beside(meta.report_path) is None


def test_a_failed_rerender_does_not_leave_last_run_s_pdf_behind(
    tmp_path, monkeypatch
):
    """A stale PDF beside fresh Markdown would misstate the delivery.

    The Markdown is replaced first. If the PDF then fails, the previous
    run's file would still be sitting there -- different claims, maybe
    a different verification warning -- and `pdf_beside` would offer it
    as this report's formatted copy.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    stale = reports / "t1.pdf"
    stale.write_bytes(b"%PDF-1.7 an older delivery")
    monkeypatch.setattr(
        pdf_module,
        "write_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no space")),
    )
    runtime, _, _, compiled = make(tmp_path)
    config = persist.thread_config("t1")
    runtime.begin("t1")
    state = run(compiled.ainvoke({"question": "光掩模产业调研"}, config))
    assert not stale.exists()
    assert (reports / "t1.md").is_file()
    assert state["meta"].report_status == "complete"
    assert pdf_module.pdf_beside(state["meta"].report_path) is None


def test_d_u6b_a_review_batch_groups_claims_that_share_a_source():
    """D-U6b: the verifier reads a document once per batch, not per claim.

    Priority still decides what is reviewed at all; grouping decides only
    what travels with it.
    """
    evidence = {
        "E1": records.Evidence(
            id="E1",
            source_id="S1",
            excerpt="x",
            locator="p1",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-10T00:00:00+00:00",
        ),
        "E2": records.Evidence(
            id="E2",
            source_id="S2",
            excerpt="y",
            locator="p1",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-10T00:00:00+00:00",
        ),
    }
    claims = {
        "C1": records.Claim(
            id="C1", statement="a", kind="fact", evidence_ids=["E1"]
        ),
        "C2": records.Claim(
            id="C2", statement="b", kind="fact", evidence_ids=["E2"]
        ),
        "C3": records.Claim(
            id="C3", statement="c", kind="fact", evidence_ids=["E1"]
        ),
        "C4": records.Claim(
            id="C4", statement="d", kind="fact", evidence_ids=["E2"]
        ),
    }
    state = {"claims": claims, "evidence": evidence}
    grouped = graph_module.group_by_source(state, ["C1", "C2", "C3", "C4"])
    # C1 keeps its position; C3 shares S1 and is pulled up behind it.
    assert grouped == ["C1", "C3", "C2", "C4"]
    # Stable and deterministic: the same input gives the same order.
    assert graph_module.group_by_source(state, grouped) == grouped
    # A claim with no evidence is left exactly where priority put it.
    state2 = {
        "claims": {
            **claims,
            "C5": records.Claim(id="C5", statement="e", kind="fact"),
        },
        "evidence": evidence,
    }
    assert graph_module.group_by_source(state2, ["C5", "C1", "C3"]) == [
        "C5",
        "C1",
        "C3",
    ]


def test_a18_a_required_comparison_gets_a_task_or_a_recorded_failure():
    """A18: a role definition is not a comparison (plan D-U5).

    Run 7 defined a Company Researcher, gave it a focus and a prompt, and
    never created one task for it.
    """
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="midstream",
                stage="midstream",
                description="d",
                claim_id="C1",
            )
        ],
        participants=[
            records.Participant(
                id="P1",
                name="清溢光电",
                segment_id="G1",
                role="supplier",
                selection_rationale="listed",
                claim_id="C2",
            )
        ],
    )
    brief = records.Brief(
        industry="光掩模", required_ids=[1, 7], priority=[1, 7]
    )
    state = {"brief": brief, "map": industry_map}
    industry_only = {
        "T1": records.Task(
            id="T1", kind="research", role="industry", objective="o"
        )
    }
    issues, log = graph_module.company_obligation(
        state, industry_only, {}, "the plan filled 2 slot(s) with other work"
    )
    assert len(issues) == 1 and log
    issue = next(iter(issues.values()))
    assert issue.severity == "material" and issue.target == "Q7"
    assert issue.category == "missing_evidence"
    assert "the plan filled 2 slot(s)" in issue.description

    # A company task naming the participant satisfies it; an untargeted
    # one does not -- it assigns nobody (U1-09).
    with_company = {
        **industry_only,
        "T2": records.Task(
            id="T2",
            kind="research",
            role="company",
            objective="o",
            targets=["清溢光电"],
        ),
    }
    assert graph_module.company_obligation(state, with_company, {}, "r") == (
        {},
        [],
    )
    untargeted = {
        **industry_only,
        "T2": records.Task(
            id="T2", kind="research", role="company", objective="o"
        ),
    }
    open_issues, log = graph_module.company_obligation(
        state, untargeted, {}, "r"
    )
    assert (
        log and "name no target" in next(iter(open_issues.values())).description
    )
    narrow = {**state, "brief": records.Brief(industry="x", required_ids=[1])}
    assert graph_module.company_obligation(narrow, industry_only, {}, "r") == (
        {},
        [],
    )
    # And it is recorded once, not once per planning round.
    again, log2 = graph_module.company_obligation(
        state, industry_only, issues, "r"
    )
    assert again == issues and log2 == []


def test_a_task_naming_more_targets_than_a_session_can_cover_is_split():
    """A05/D-U5: run 7's first task asked for nine areas and ten companies."""
    limits = records.Limits(tools_per_attempt=6, tools_per_target=3)
    assert schedule.target_capacity(limits) == 2
    assert schedule.decompose(["a", "b", "c", "d", "e"], limits) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    # Deterministic: the Lead's order is preserved for replay.
    assert schedule.decompose([], limits) == [[]]


def test_u1_01_a_settled_claim_frees_its_slot_inside_the_review_node():
    """The helper existed and nothing called it, so deferral was forever."""
    limits = records.Limits(material_per_question=1)
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="a",
            kind="fact",
            material=True,
            partition="q4",
            review_disposition="pending",
        ),
        "C2": records.Claim(
            id="C2",
            statement="b",
            kind="fact",
            material=True,
            partition="q4",
            review_disposition="deferred",
            review_deferred_reason="q4 at capacity",
        ),
    }
    # Only the admitted one is selectable while it waits for a verdict.
    assert [c.id for c in merge.outstanding_review(claims, {})] == ["C1"]
    settled = {
        **claims,
        "C1": claims["C1"].model_copy(update={"review": "supported"}),
    }
    promoted, log = merge.reconsider_deferred(settled, limits)
    assert log and promoted["C2"].review_disposition == "pending"
    assert promoted["C2"].review_deferred_reason is None
    assert [c.id for c in merge.outstanding_review(promoted, {})] == ["C2"]


def test_u1_01_an_unreviewed_material_claim_caps_the_report_status():
    rows = [
        records.Coverage(question=q, status="covered", note="n")
        for q in sorted(records.REQUIRED_QUESTIONS)
    ]
    state = {
        "brief": records.Brief(industry="x"),
        "claims": {
            "C1": records.Claim(
                id="C1",
                statement="a",
                kind="fact",
                material=True,
                partition="q4",
                review_disposition="deferred",
                review_deferred_reason="q4 at capacity",
            )
        },
        "findings": {},
        "issues": {},
    }
    assert coverage.report_status(rows, state, verified=True) != "complete"
    assert report.deferred_review(state)[0].id == "C1"
    note = report.deferred_note(state)
    assert "not independently verified" in note and "q4" in note
    # And the reader is told, in the delivered appendix.
    lines = report.appendices(state, rows)
    assert any("unreviewed" in line for line in lines)


def test_u1_08_a_decomposed_task_dispatches_a_smaller_contract():
    limits = records.Limits(tools_per_attempt=6, tools_per_target=3)
    plan = roles.TaskPlan(
        tasks=[
            roles.TaskSpec(
                key="cmp",
                role="company",
                objective="Compare A, B, C, D, E",
                scope="the five listed vendors",
                targets=["A", "B", "C", "D", "E"],
            )
        ]
    )
    state = {"tasks": {}, "issues": {}, "evidence": {}}
    # Two slots for three parts: the third is an explicit partial plan.
    tasks, _, log = graph_module._tasks_from_plan(
        state, plan, 2, "research", limits
    )
    created = sorted(tasks.values(), key=lambda t: t.id)
    assert [t.targets for t in created] == [["A", "B"], ["C", "D"]]
    # Each part says what it alone must cover, in the text the worker
    # actually renders.
    for task in created:
        assert "part " in task.objective and "cover only" in task.objective
        allowance = records.Reservation(turns=1, tool_calls=1, seconds=1.0)
        prompt = worker.user_prompt(
            records.WorkerInput(
                thread_id="t",
                attempt=records.Attempt(
                    id=f"{task.id}.1",
                    task_id=task.id,
                    reserved=allowance,
                    started_at="2026-09-10T00:00:00+00:00",
                ),
                task=task,
                brief=records.Brief(industry="x"),
                language="en",
                allowance=allowance,
                model="claude-sonnet-5",
                prompt_version=roles.PROMPT_VERSION,
            ),
            tools.Collector(f"{task.id}.1", task.id),
        )
        assert "; ".join(task.targets) in prompt
    assert any("has no slot" in line and "E" in line for line in log)
    assert any("is split into 3" in line for line in log)


def test_u1_09_a_company_task_covers_only_the_companies_it_names():
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="mid",
                stage="midstream",
                description="d",
                claim_id="C1",
            )
        ],
        participants=[
            records.Participant(
                id=f"P{n}",
                name=name,
                segment_id="G1",
                role="supplier",
                selection_rationale="r",
                claim_id=f"C{n}",
            )
            for n, name in enumerate(["清溢", "龙图", "路维"], start=2)
        ],
    )
    brief = records.Brief(industry="x", required_ids=[7], priority=[7])
    state = {"brief": brief, "map": industry_map}
    tasks = {
        "T1": records.Task(
            id="T1",
            kind="research",
            role="company",
            objective="o",
            targets=["清溢"],
        )
    }
    issues, log = graph_module.company_obligation(state, tasks, {}, "r")
    assert log and "龙图" in next(iter(issues.values())).description
    assert "路维" in next(iter(issues.values())).description
    # A failed task leaves its own targets unmet.
    failed = {
        "T1": tasks["T1"].model_copy(
            update={"targets": ["清溢", "龙图", "路维"], "status": "failed"}
        )
    }
    issues2, log2 = graph_module.company_obligation(state, failed, {}, "r")
    assert log2 and "清溢" in next(iter(issues2.values())).description
    # A short name covers the participant it abbreviates.
    short = {"T1": tasks["T1"].model_copy(update={"targets": ["清溢"]})}
    issues3, _ = graph_module.company_obligation(state, short, {}, "r")
    assert "清溢" not in next(iter(issues3.values())).description
    # And an untargeted task assigns nobody, rather than everybody.
    general = {"T1": tasks["T1"].model_copy(update={"targets": []})}
    issues4, log4 = graph_module.company_obligation(state, general, {}, "r")
    assert log4 and "清溢" in next(iter(issues4.values())).description


def test_u1_10_grouping_reorders_the_batch_but_never_reselects_it():
    """One source's mates must not crowd out a required question."""
    evidence = {
        f"E{n}": records.Evidence(
            id=f"E{n}",
            source_id="S1" if n != 2 else "S2",
            excerpt="x",
            locator="p",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at="2026-09-10T00:00:00+00:00",
        )
        for n in (1, 2)
    }
    state = {"claims": {}, "evidence": evidence}
    ordered = ["C1", "C2", "C3"]
    state["claims"] = {
        "C1": records.Claim(
            id="C1", statement="a", kind="fact", evidence_ids=["E1"]
        ),
        "C2": records.Claim(
            id="C2", statement="b", kind="fact", evidence_ids=["E2"]
        ),
        "C3": records.Claim(
            id="C3", statement="c", kind="fact", evidence_ids=["E1"]
        ),
    }
    grouped = graph_module.group_by_source(state, ordered)
    assert sorted(grouped) == sorted(
        ordered
    ), "grouping must not change membership"
    assert grouped == ["C1", "C3", "C2"]


def _quantity(value: float, unit_text: str = "亿元"):
    parsed = quantities.parse_declaration(unit_text)
    return records.Quantity(
        value=value,
        unit=parsed,
        binding=records.EvidenceBinding(
            evidence_id="E1",
            excerpt_sha256="0" * 64,
            number_start=0,
            number_end=1,
            expression_start=0,
            expression_end=1,
            as_written="1",
        ),
    )


def test_u1_12_a_qualitative_conclusion_is_not_an_arithmetic_obligation():
    """The escape hatch has to be real, or the issue blocks delivery."""
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="a",
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(52.0),
        ),
        "C2": records.Claim(
            id="C2",
            statement="b",
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(40.0),
        ),
    }
    base = dict(
        id="F1",
        conclusion="Both suppliers have commercial sales; monitor retention.",
        claim_ids=["C1", "C2"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
    )
    qualitative = records.Finding(**base)
    assert graph_module.uncomputed_comparison(qualitative, claims, {}) is None
    quantitative = records.Finding(**base, compares=["C1", "C2"])
    assert (
        graph_module.uncomputed_comparison(quantitative, claims, {}) == "C1, C2"
    )


def test_u1_12_the_obligation_closes_when_the_comparison_is_calculated():
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="a",
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(52.0),
        ),
        "C2": records.Claim(
            id="C2",
            statement="b",
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(40.0),
        ),
    }
    finding = records.Finding(
        id="F1",
        conclusion="A is larger than B",
        claim_ids=["C1", "C2", "C3"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2"],
    )
    inputs = [
        records.CalcInput(
            claim_id=cid, claim_version=1, quantity=_quantity(1.0)
        )
        for cid in ("C1", "C2")
    ]
    calculation = records.Calculation(
        id="K1",
        kind="ratio",
        label="A over B",
        formula="C1 / C2",
        inputs=inputs,
        status="ok",
        result=1.3,
    )
    claims["C3"] = records.Claim(
        id="C3",
        statement="ratio",
        kind="derived",
        calculation_id="K1",
        calculation_version=1,
        evidence_ids=["E1"],
    )
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K1": calculation})
        is None
    )
    # An unrelated calculation discharges nothing.
    other = calculation.model_copy(
        update={
            "id": "K2",
            "inputs": [
                records.CalcInput(
                    claim_id="C9", claim_version=1, quantity=_quantity(1.0)
                )
            ],
        }
    )
    claims["C3"] = claims["C3"].model_copy(update={"calculation_id": "K2"})
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K2": other})
        == "C1, C2"
    )


def test_u1_08_a_dependant_waits_for_every_part_of_a_split_task():
    limits = records.Limits(tools_per_attempt=6, tools_per_target=3)
    plan = roles.TaskPlan(
        tasks=[
            roles.TaskSpec(
                key="companies",
                role="company",
                objective="Profile A, B, C, D",
                targets=["A", "B", "C", "D"],
            ),
            roles.TaskSpec(
                key="synth",
                role="industry",
                objective="Compare them",
                depends_on=["companies"],
            ),
        ]
    )
    tasks, _, _ = graph_module._tasks_from_plan(
        {"tasks": {}, "issues": {}, "evidence": {}},
        plan,
        4,
        "research",
        limits,
    )
    dependant = next(t for t in tasks.values() if t.objective == "Compare them")
    parts = sorted(t.id for t in tasks.values() if t.role == "company")
    assert len(parts) == 2
    assert sorted(dependant.depends_on) == parts
    # And it is not ready while a part is unfinished.
    done_first = {
        **tasks,
        parts[0]: tasks[parts[0]].model_copy(update={"status": "done"}),
    }
    _, ready = schedule.ready(schedule.validate(done_first))
    assert dependant.id not in [t.id for t in ready]


def test_u1_07_a_repaired_evidence_obligation_can_close():
    claim = records.Claim(
        id="C1",
        statement="revenue was 1.2bn",
        kind="fact",
        evidence_ids=["E1", "E2"],
        review="supported",
        material=True,
    )
    finding = records.Finding(
        id="F1",
        conclusion="c",
        claim_ids=["C1"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
    )
    issue = records.Issue(
        id="I1",
        key="missing_evidence:C1",
        category="missing_evidence",
        severity="material",
        target="C1",
        requested_action="acquire",
        description="the original context has not been read",
    )
    snippet = records.Evidence(
        id="E1",
        source_id="S1",
        excerpt="x",
        locator="search snippet",
        kind="snippet",
        extraction="search_snippet",
        task_id="T1",
        retrieved_at="2026-09-10T00:00:00+00:00",
    )
    state = {
        "claims": {"C1": claim},
        "findings": {"F1": finding},
        "issues": {"I1": issue},
        "coverage": [],
        "evidence": {"E1": snippet},
    }
    # Supported, but still only a snippet: the obligation stands.
    assert graph_module.resolve_issues(state)["issues"]["I1"].status == "open"
    passage = snippet.model_copy(
        update={
            "id": "E2",
            "kind": "passage",
            "source_version_id": "v1",
            "locator": "page 12",
        }
    )
    repaired = {**state, "evidence": {"E1": snippet, "E2": passage}}
    closed = graph_module.resolve_issues(repaired)["issues"]["I1"]
    assert (
        closed.status == "resolved" and "original context" in closed.resolution
    )


def test_u1_n02_arithmetic_absence_never_clears_an_inference_verdict():
    """The two obligations are both weak_inference on a finding and are
    not the same problem (U1-N02)."""
    finding = records.Finding(
        id="F1",
        conclusion="the barrier is insurmountable",
        claim_ids=[],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        inference_review="unsupported_certainty",
        inference_reason="asserted more firmly than the premises allow",
        inference_version=1,
        version=1,
    )
    issues = {}
    issues, audit_issue = merge.open_issue(
        issues,
        "weak_inference",
        "material",
        "F1",
        "analyze",
        "the reasoning does not hold",
        kind=graph_module.INFERENCE_ISSUE,
    )
    issues, arithmetic = merge.open_issue(
        issues,
        "weak_inference",
        "material",
        "F1",
        "analyze",
        "the comparison has no calculation",
        kind=graph_module.ARITHMETIC_ISSUE,
    )
    # Two obligations, not one folded record.
    assert audit_issue.id != arithmetic.id
    assert audit_issue.key != arithmetic.key
    state = {
        "findings": {"F1": finding},
        "issues": issues,
        "claims": {},
        "calculations": {},
        "coverage": [],
    }
    after = graph_module.resolve_issues(state)["issues"]
    # No arithmetic gap exists, so the arithmetic obligation closes and
    # the audit's verdict stands.
    assert after[arithmetic.id].status == "resolved"
    assert after[audit_issue.id].status == "open"
    # It closes only when the reasoning is re-audited on the current
    # version and accepted.
    repaired = finding.model_copy(
        update={
            "version": 2,
            "inference_review": "supported",
            "inference_version": 2,
        }
    )
    reaudited = graph_module.resolve_issues(
        {**state, "findings": {"F1": repaired}}
    )["issues"]
    assert reaudited[audit_issue.id].status == "resolved"


def test_u1_09_prefix_matching_never_covers_a_different_company():
    """丰田通商 must not discharge 丰田's obligation (U1-09)."""
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="mid",
                stage="midstream",
                description="d",
                claim_id="C1",
            )
        ],
        participants=[
            records.Participant(
                id="P1",
                name="丰田",
                segment_id="G1",
                role="customer",
                selection_rationale="r",
                claim_id="C2",
            )
        ],
    )
    state = {
        "brief": records.Brief(industry="x", required_ids=[7], priority=[7]),
        "map": industry_map,
    }
    tasks = {
        "T1": records.Task(
            id="T1",
            kind="research",
            role="company",
            objective="o",
            targets=["丰田通商"],
        )
    }
    issues, log = graph_module.company_obligation(state, tasks, {}, "r")
    assert log and "丰田" in next(iter(issues.values())).description
    # An alias is resolved once, at task creation, against the map.
    resolved, notes = graph_module.canonical_targets(["丰田"], industry_map)
    assert resolved == ["丰田"] and notes == []
    longer = records.IndustryMap(
        segments=industry_map.segments,
        participants=[
            industry_map.participants[0].model_copy(update={"name": "清溢光电"})
        ],
    )
    resolved, notes = graph_module.canonical_targets(["清溢"], longer)
    assert resolved == ["清溢光电"] and notes


def test_u1_12_an_unrelated_calculation_discharges_nothing():
    claims = {
        cid: records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(value),
        )
        for cid, value in (("C1", 52.0), ("C2", 40.0), ("C9", 7.0))
    }
    finding = records.Finding(
        id="F1",
        conclusion="A is twice B",
        claim_ids=["C1", "C2", "C3"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2"],
    )
    # A calculation over C1 and C9 touches one compared operand only.
    calculation = records.Calculation(
        id="K1",
        kind="ratio",
        label="A over an unrelated figure",
        formula="C1 / C9",
        inputs=[
            records.CalcInput(
                claim_id=cid, claim_version=1, quantity=_quantity(1.0)
            )
            for cid in ("C1", "C9")
        ],
        status="ok",
        result=7.4,
    )
    claims["C3"] = records.Claim(
        id="C3",
        statement="ratio",
        kind="derived",
        calculation_id="K1",
        calculation_version=1,
        evidence_ids=["E1"],
    )
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K1": calculation})
        == "C1, C2"
    )


def test_u1_12_an_explicit_comparison_is_caught_without_a_declaration():
    """A declaration alone cannot carry a delivery obligation (U1-12)."""
    claims = {
        cid: records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(value),
        )
        for cid, value in (("C1", 52.0), ("C2", 40.0))
    }
    base = dict(
        id="F1",
        claim_ids=["C1", "C2"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
    )
    stated = records.Finding(conclusion="A 的营收是 B 的两倍", **base)
    assert graph_module.uncomputed_comparison(stated, claims, {}) == "C1, C2"
    english = records.Finding(conclusion="A earns twice what B does", **base)
    assert graph_module.uncomputed_comparison(english, claims, {}) == "C1, C2"
    quiet = records.Finding(
        conclusion="Both suppliers sell commercially; watch retention.",
        **base,
    )
    assert graph_module.uncomputed_comparison(quiet, claims, {}) is None


def test_u1_08_a_partly_admitted_prerequisite_is_not_met():
    limits = records.Limits(tools_per_attempt=6, tools_per_target=3)
    plan = roles.TaskPlan(
        tasks=[
            roles.TaskSpec(
                key="synth",
                role="industry",
                objective="Compare them",
                depends_on=["companies"],
            ),
            roles.TaskSpec(
                key="companies",
                role="company",
                objective="Profile A, B, C, D",
                targets=["A", "B", "C", "D"],
            ),
        ]
    )
    tasks, issues, log = graph_module._tasks_from_plan(
        {
            "tasks": {},
            "issues": {},
            "evidence": {},
            "map": records.IndustryMap(),
        },
        plan,
        2,
        "research",
        limits,
    )
    dependant = next(t for t in tasks.values() if t.objective == "Compare them")
    assert any("has no slot" in line for line in log)
    # It says the prerequisite is incomplete, in the task and as an issue.
    assert "prerequisite" in dependant.scope
    unmet = [i for i in issues.values() if i.target == dependant.id]
    assert unmet and unmet[0].severity == "material"
    assert "only partly admitted" in unmet[0].description


def test_u1_n03_an_unjudged_finding_keeps_its_own_limitation():
    """Unjudged reasoning is not audited reasoning (U1-N03)."""
    finding = records.Finding(
        id="F1",
        conclusion="c",
        claim_ids=[],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
    )
    assert finding.inference_review == "unreviewed"
    note = roles._inference_note(finding)
    assert "not audited" in note
    qualified = finding.model_copy(
        update={
            "inference_review": "qualified",
            "inference_reason": "only while export licences remain available",
        }
    )
    # The restriction reaches the writer, not just the audit record.
    assert "export licences" in roles._inference_note(qualified)
    state = {"findings": {"F1": qualified}, "claims": {}}
    assert "export licences" in roles.render_findings(state)


def test_u1_09_canonicalisation_resolves_only_a_short_name():
    """丰田通商 is a different company from 丰田, not an alias of it."""

    def mapped(*names):
        return records.IndustryMap(
            segments=[
                records.Segment(
                    id="G1",
                    name="mid",
                    stage="midstream",
                    description="d",
                    claim_id="C1",
                )
            ],
            participants=[
                records.Participant(
                    id=f"P{n}",
                    name=name,
                    segment_id="G1",
                    role="supplier",
                    selection_rationale="r",
                    claim_id=f"C{n + 1}",
                )
                for n, name in enumerate(names)
            ],
        )

    resolved, _ = graph_module.canonical_targets(["丰田通商"], mapped("丰田"))
    assert resolved == ["丰田通商"]
    # A short name still resolves to the participant it abbreviates.
    resolved, notes = graph_module.canonical_targets(
        ["清溢"], mapped("清溢光电")
    )
    assert resolved == ["清溢光电"] and notes
    # And an ambiguous prefix is left alone rather than guessed.
    resolved, notes = graph_module.canonical_targets(
        ["清"], mapped("清溢光电", "清华紫光")
    )
    assert resolved == ["清"] and "2 participants" in notes[0]


def test_u1_12_a_declaration_cannot_suppress_a_stated_comparison():
    claims = {
        cid: records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(value),
        )
        for cid, value in (("C1", 52.0), ("C2", 40.0))
    }
    base = dict(
        id="F1",
        conclusion="A earns twice what B does",
        claim_ids=["C1", "C2"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
    )
    # One declared operand no longer hides the pair the words compare.
    singleton = records.Finding(compares=["C1"], **base)
    assert graph_module.uncomputed_comparison(singleton, claims, {}) == "C1, C2"
    # Nor does a declaration naming claims the conclusion does not cite.
    unrelated = records.Finding(compares=["C8", "C9"], **base)
    assert graph_module.uncomputed_comparison(unrelated, claims, {}) == "C1, C2"


def test_u1_n04_an_affordable_repair_is_not_a_blocked_acquisition():
    limits = records.Limits()
    waiting = records.RepairRequest(
        id="RQ1",
        claim_id="C1",
        objective="open the original and read the passage",
        status="pending",
    )
    state = charged(repair_state(pending=1), 2600)
    state = {**state, "repair_window": "closed", "repairs": {"RQ1": waiting}}
    assert budget.dispatchable(state, limits, False) == 0
    assert budget.admit_repair_pair(state, limits) > 0
    # Ordinary capacity is gone, but a repair pair is admitted from its
    # own earmark, so evidence is still reachable (U1-N04).
    assert graph_module.acquisition_blocked(state, limits) == ""
    # With no repair waiting, it is genuinely blocked.
    assert graph_module.acquisition_blocked({**state, "repairs": {}}, limits)


def test_u1_n05_a_measured_duration_counts_even_when_tokens_are_unknown():
    reservation = records.Reservation(turns=10, tool_calls=0, seconds=480.0)
    done = records.Attempt(
        id="T1.1",
        task_id="T1",
        status="done",
        reserved=reservation,
        observed=records.Usage(turns=3, duration_s=100.0),
        started_at="2026-09-10T00:00:00+00:00",
    )
    failed = records.Attempt(
        id="T2.1",
        task_id="T2",
        status="failed",
        reserved=reservation,
        observed=records.Usage(duration_s=123.0, unknown=True),
        started_at="2026-09-10T00:00:00+00:00",
    )
    held = records.Attempt(
        id="T3.1",
        task_id="T3",
        status="running",
        reserved=reservation,
        started_at="2026-09-10T00:00:00+00:00",
    )
    state = {
        "attempts": {a.id: a for a in (done, failed, held)},
        "single_calls": {},
    }
    spent = budget.ledger(state)
    # Only the uninvoked reservation contributes no observed time.
    assert spent.observed_session_s == 223.0
    # Charged time still includes the reservation it never spent.
    assert spent.wall_clock_s == 100.0 + 123.0 + 480.0
    assert not spent.cost_complete


def test_u1_n06_the_provider_cache_counts_are_captured():
    full = records.provider_usage(
        {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 500,
        },
        0.5,
    )
    assert full["cache_read_input_tokens"] == 1000
    assert full["cache_creation_input_tokens"] == 500
    assert full["cost_basis"] == "sdk_total_cost_usd" and full["complete"]
    # A provider that exposed no cache figures is incomplete, not zero.
    partial = records.provider_usage({"input_tokens": 10}, None)
    assert partial["complete"] is False and partial["cost_usd"] is None
    # And the counts add without losing a category.
    total = records.Usage(**full) + records.Usage(**full)
    assert total.cache_read_input_tokens == 2000


def test_d_u16_route_s_shares_every_authority_and_saves_two_calls(tmp_path):
    """The candidate is a routing flag, not a second workflow."""
    runtime = budget.Runtime(
        records.Limits(wall_clock_s=9000.0),
        reports_dir=str(tmp_path / "reports"),
        floor=OPEN_FLOOR,
        route="S",
    )
    api = FakeRoles()
    compiled = graph_module.build_graph(
        runtime,
        backend=object(),
        api=api,
        worker_fn=FakeWorker(),
        checkpointer=MemorySaver(),
    )
    config = persist.thread_config("s1")
    runtime.begin("s1")
    state = run(compiled.ainvoke({"question": "光掩模产业调研"}, config))
    assert state["meta"].route == "S"
    calls = state["single_calls"]
    # No separate coverage call, and the owner writes the draft.
    assert "assess_coverage" not in {c.task_id for c in calls.values()}
    assert any(c.startswith("owner-write") for c in api.calls)
    assert any(
        "deterministic obligations only (route S)" in line
        for line in state["route_log"]
    )
    # The independent audit still runs, before the prose.
    assert api.calls.index("audit") < next(
        i for i, c in enumerate(api.calls) if c.startswith("owner-write")
    )
    # Coverage, delivery and the report are the same authorities.
    assert len(state["coverage"]) == 8
    assert state["delivery"] is not None
    assert (tmp_path / "reports" / "s1.md").exists()


def test_u2_08_a_verifier_that_settles_nothing_stops_being_asked(tmp_path):
    """One measured case reached 143 identical batches and no delivery."""
    runtime, api, worker, compiled = make(
        tmp_path, records.Limits(wall_clock_s=9000.0)
    )

    async def empty_review(state, claim_ids, max_turns, deadline):
        del state, claim_ids, max_turns, deadline
        api.calls.append("review")
        return records.ClaimReview(claims=[], relationships=[]), USAGE

    api.review_claims = empty_review
    config = persist.thread_config("stall1")
    runtime.begin("stall1")
    state = run(compiled.ainvoke({"question": "q"}, config))
    reviews = sum(1 for c in api.calls if c == "review")
    # It asks a few times and then advances, rather than forever.
    # A handful of stalled rounds per review phase, not 143.
    assert reviews <= 2 * (graph_module.REVIEW_STALLS + 1), reviews
    assert state["review_stalls"] >= graph_module.REVIEW_STALLS
    assert any("settled nothing" in line for line in state["route_log"])
    # And the run still reaches a delivery decision.
    assert state["meta"].execution_status == "completed"
    assert state["delivery"] is not None


def test_u2_01_a_coarse_objection_reaches_the_retained_body():
    """A body retained from an earlier draft was published with the
    sentence a later review had faulted (U2-01)."""
    section = records.Section(
        id="intro", title="I", text="This market has one supplier [C1]."
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[section],
        subject=records.ReviewSubject(
            digest="d", sections={"intro": "s"}, section_ids=["intro"]
        ),
        issues={},
    )
    coarse = records.Issue(
        id="I1",
        key="unsupported:intro",
        category="unsupported",
        severity="material",
        target="intro",
        requested_action="remove",
        description="the monopoly assertion is unsupported",
        draft_version=2,
        text=None,
    )
    applies = graph_module.issues_for_candidate(candidate, {"I1": coarse})
    assert "I1" in applies, "a coarse objection must reach the retained body"
    # And it still blocks that section, which is the whole point.
    assert report.blocking_issues([applies["I1"]], section) == [applies["I1"]]


def test_u2_02_a_section_target_is_never_read_as_a_claim():
    """A section named `C1` is a section (U2-02)."""
    section = records.Section(id="C1", title="Economics", text="text [C2].")
    claim = records.Claim(
        id="C1", statement="s", kind="fact", review="supported"
    )
    issue = records.Issue(
        id="I1",
        key="unsupported:C1",
        category="unsupported",
        severity="material",
        target="C1",
        requested_action="remove",
        description="unsupported wording",
        draft_version=1,
    )
    state = {
        "sections": [section],
        "claims": {"C1": claim},
        "issues": {"I1": issue},
        "findings": {},
        "coverage": [],
        "evidence": {},
    }
    after = graph_module.resolve_issues(state)["issues"]["I1"]
    assert after.status == "open", "a supported claim cannot clear a section"
    # And a mistyped section id still identifies its section.
    assert report.resolve_section([section], " c1 ") == "C1"
    assert report.resolve_section([section], "nowhere") == "nowhere"


def test_u2_05_a_calculation_answers_one_comparison_not_every_one():
    """Pooling every compared operand let a capex calculation discharge a
    revenue comparison in the same finding (U2-05)."""

    def numeric(cid, value, metric):
        return records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension=metric,
            quantity=_quantity(value),
        )

    claims = {
        "C1": numeric("C1", 52.0, "revenue"),
        "C2": numeric("C2", 40.0, "revenue"),
        "C8": numeric("C8", 3.0, "capex"),
        "C9": numeric("C9", 2.0, "capex"),
    }
    capex_ratio = records.Calculation(
        id="K1",
        kind="ratio",
        label="capex ratio",
        formula="C8 / C9",
        inputs=[
            records.CalcInput(
                claim_id=cid, claim_version=1, quantity=_quantity(1.0)
            )
            for cid in ("C8", "C9")
        ],
        status="ok",
        result=1.5,
    )
    claims["C3"] = records.Claim(
        id="C3",
        statement="ratio",
        kind="derived",
        calculation_id="K1",
        calculation_version=1,
        evidence_ids=["E1"],
    )
    finding = records.Finding(
        id="F1",
        conclusion="A earns twice what B does",
        claim_ids=["C1", "C2", "C8", "C9", "C3"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2", "C8", "C9"],
    )
    # The revenue comparison is still outstanding.
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K1": capex_ratio})
        == "C1, C2"
    )
    # Its own calculation discharges it.
    revenue_ratio = capex_ratio.model_copy(
        update={
            "id": "K2",
            "inputs": [
                records.CalcInput(
                    claim_id=cid, claim_version=1, quantity=_quantity(1.0)
                )
                for cid in ("C1", "C2")
            ],
        }
    )
    claims["C4"] = claims["C3"].model_copy(
        update={"id": "C4", "calculation_id": "K2"}
    )
    both = finding.model_copy(update={"claim_ids": finding.claim_ids + ["C4"]})
    assert (
        graph_module.uncomputed_comparison(
            both, claims, {"K1": capex_ratio, "K2": revenue_ratio}
        )
        is None
    )


def test_u2_10_route_s_does_not_reserve_the_call_it_skips():
    limits = records.Limits()
    meta_s = records.RunMeta(
        workflow_version="industry-v1",
        route="S",
        prompt_version="x",
        models={},
        limits=limits,
        started_at="2026-09-10T00:00:00+00:00",
    )
    base = {"attempts": {}, "single_calls": {}, "claims": {}}
    c_state = {**base, "meta": meta_s.model_copy(update={"route": "C"})}
    s_state = {**base, "meta": meta_s}
    assert "assess_coverage" in budget.downstream_calls(c_state, "research")
    assert "assess_coverage" not in budget.downstream_calls(s_state, "research")
    c_seconds, _ = budget.pipeline_reserve(c_state, limits, "research")
    s_seconds, _ = budget.pipeline_reserve(s_state, limits, "research")
    assert c_seconds - s_seconds == limits.single_call_timeout_s
    # Which is the difference between admitting a worker and refusing one.
    assert budget.dispatchable(s_state, limits, False) >= budget.dispatchable(
        c_state, limits, False
    )


def test_u2_11_the_sdk_per_model_record_fills_the_cache_categories():
    filled = records.provider_usage(
        {"input_tokens": 10},
        0.5,
        {
            "claude-sonnet-5": {
                "outputTokens": 200,
                "cacheReadInputTokens": 1000,
                "cacheCreationInputTokens": 500,
            }
        },
    )
    assert filled["cache_read_input_tokens"] == 1000
    assert filled["per_model"] == {"claude-sonnet-5": 200}
    assert filled["complete"]
    # One category alone is not a cache report.
    half = records.provider_usage({"cache_read_input_tokens": 7}, None)
    assert half["complete"] is False


def test_u2_01_a_renamed_section_does_not_shed_its_objection():
    """Draft 2 renamed the section; the objection must still bind (U2-01)."""
    retained = records.Section(
        id="intro", title="I", text="This market has one supplier [C1]."
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[retained],
        subject=records.ReviewSubject(
            digest="d", sections={"intro": "s"}, section_ids=["intro"]
        ),
        issues={},
    )
    exact = records.Issue(
        id="I1",
        key="unsupported:new_intro",
        category="unsupported",
        severity="material",
        target="new_intro",
        requested_action="remove",
        description="unsupported",
        draft_version=2,
        text="This market has one supplier [C1].",
    )
    applies = graph_module.issues_for_candidate(candidate, {"I1": exact})
    assert applies["I1"].target == "intro", "retargeted to the retained id"
    assert report.blocking_issues([], retained) == []
    assert (
        report.redact(retained.text, [applies["I1"]], "intro", "[X]") == "[X]"
    )
    # A coarse objection that names nothing in this body reaches every
    # section of it, rather than lapsing.
    coarse = exact.model_copy(update={"id": "I2", "text": None})
    spread = graph_module.issues_for_candidate(candidate, {"I2": coarse})
    assert [i.target for i in spread.values()] == ["intro"]
    assert report.blocking_issues(list(spread.values()), retained)


def test_u2_02_a_section_named_q1_is_not_question_one():
    section = records.Section(id="Q1", title="Overview", text="text [C2].")
    issue = records.Issue(
        id="I1",
        key="unsupported:Q1",
        category="unsupported",
        severity="material",
        target="Q1",
        requested_action="remove",
        description="unsupported wording",
        draft_version=1,
    )
    state = {
        "sections": [section],
        "claims": {},
        "issues": {"I1": issue},
        "findings": {},
        "coverage": [records.Coverage(question=1, status="covered", note="n")],
        "evidence": {},
    }
    assert graph_module.resolve_issues(state)["issues"]["I1"].status == "open"


def test_u2_05_a_declared_cross_metric_comparison_is_its_own_obligation():
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="revenue",
            kind="fact",
            evidence_ids=["E1"],
            dimension="revenue",
            quantity=_quantity(52.0),
        ),
        "C2": records.Claim(
            id="C2",
            statement="capex",
            kind="fact",
            evidence_ids=["E1"],
            dimension="capex",
            quantity=_quantity(5.2),
        ),
    }
    finding = records.Finding(
        id="F1",
        conclusion="Capex is 10% of revenue",
        claim_ids=["C1", "C2"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2"],
    )
    # Two metrics, one declared comparison: per-metric grouping alone
    # made two singletons and returned nothing (U2-05).
    assert graph_module.uncomputed_comparison(finding, claims, {}) == "C1, C2"


def test_u2_01_a_later_clean_draft_cannot_clear_a_retained_body():
    """Draft 3 omits the sentence, reviews clean, and its resolution used
    to authorise the sentence still standing in draft 1 (U2-01)."""
    retained = records.Section(
        id="intro", title="I", text="This market has no competing suppliers."
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[retained],
        subject=records.ReviewSubject(digest="d"),
        issues={},
    )
    settled_elsewhere = records.Issue(
        id="I1",
        key="unsupported:new_intro",
        category="unsupported",
        severity="material",
        target="new_intro",
        requested_action="remove",
        description="unsupported",
        draft_version=3,
        status="resolved",
        resolution="draft 3 reviewed clean",
        text="This market has no competing suppliers.",
    )
    applies = graph_module.issues_for_candidate(
        candidate, {"I1": settled_elsewhere}
    )
    assert applies["I1"].status == "open"
    assert applies["I1"].target == "intro"
    # And it therefore still removes the sentence from this body.
    assert (
        report.redact(retained.text, list(applies.values()), "intro", "[X]")
        == "[X]"
    )


def test_u2_r2_01_a_row_objection_does_not_spread_by_substring():
    """`| A | 1 |` does not occur inside `| A | 1 | estimate |`."""
    a = records.Section(
        id="a", title="A", text="| v | n |\n| --- | --- |\n| A | 1 |\n| B | 2 |"
    )
    b = records.Section(
        id="b",
        title="B",
        text="| v | n | note |\n| --- | --- | --- |\n| A | 1 | estimate |",
    )
    row = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="a",
        requested_action="remove",
        text="| A | 1 |",
        draft_version=2,
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[a, b],
        subject=records.ReviewSubject(digest="d"),
        issues={},
    )
    applies = graph_module.issues_for_candidate(candidate, {"I1": row})
    assert [i.target for i in applies.values()] == ["a"], "b does not hold it"
    # Section B survives, and A gives up its row.
    assert report.blocking_issues(list(applies.values()), b) == []
    assert "| A | 1 |" not in report.redact(
        a.text, list(applies.values()), "a", "[X]"
    )


def test_u2_05_a_metric_literally_named_declared_does_not_collide():
    def numeric(cid, value, metric):
        return records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension=metric,
            quantity=_quantity(value),
        )

    claims = {
        "C1": numeric("C1", 52.0, "declared"),
        "C2": numeric("C2", 40.0, "declared"),
        "C8": numeric("C8", 3.0, "capex"),
        "C9": numeric("C9", 2.0, "capex"),
    }
    capex = records.Calculation(
        id="K1",
        kind="ratio",
        label="capex",
        formula="C8 / C9",
        inputs=[
            records.CalcInput(
                claim_id=cid, claim_version=1, quantity=_quantity(1.0)
            )
            for cid in ("C8", "C9")
        ],
        status="ok",
        result=1.5,
    )
    claims["C3"] = records.Claim(
        id="C3",
        statement="r",
        kind="derived",
        calculation_id="K1",
        calculation_version=1,
        evidence_ids=["E1"],
    )
    finding = records.Finding(
        id="F1",
        conclusion="A is twice B",
        claim_ids=["C1", "C2", "C8", "C9", "C3"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2", "C8", "C9"],
    )
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K1": capex})
        == "C1, C2"
    )


def test_u2_01_a_resolution_names_the_body_that_authorised_it():
    """`draft_version` names the draft that raised the issue and does not
    move when a later one settles it (U2-01)."""
    retained = records.Section(
        id="intro", title="I", text="This market has no competing suppliers."
    )
    raised_here = records.Issue(
        id="I1",
        key="unsupported:intro",
        category="unsupported",
        severity="material",
        target="intro",
        requested_action="remove",
        description="unsupported",
        draft_version=1,
        text="This market has no competing suppliers.",
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[retained],
        subject=records.ReviewSubject(digest="d"),
        issues={"I1": raised_here},
    )
    # Draft 2 omits the sentence and reviews clean, resolving I1.
    settled_by_two = raised_here.model_copy(
        update={
            "status": "resolved",
            "resolution": "draft 2 reviewed clean",
            "resolved_by_draft": 2,
        }
    )
    applies = graph_module.issues_for_candidate(
        candidate, {"I1": settled_by_two}
    )
    assert applies["I1"].status == "open", "draft 2 cannot clear draft 1"
    # A resolution earned by this very body does stand.
    settled_here = settled_by_two.model_copy(update={"resolved_by_draft": 1})
    assert (
        graph_module.issues_for_candidate(candidate, {"I1": settled_here})[
            "I1"
        ].status
        == "resolved"
    )


def test_u2_r3_01_a_list_item_matches_whole_and_not_by_prefix():
    short = "- Capacity: 10"
    longer = "- Capacity: 100 units"
    assert report.unit_spans(longer, short) == []
    assert report.unit_spans(short, short) == [(0, len(short))]
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="s",
        requested_action="remove",
        text=short,
    )
    # The longer item survives untouched; the exact one is removable.
    assert report.redact(longer, [issue], "s", "[X]") == longer
    assert report.redact(short, [issue], "s", "[X]") == "[X]"


def test_u2_05_a_json_null_escape_dimension_cannot_collide():
    import json as _json

    hostile = _json.loads('"\\u0000declared"')

    def numeric(cid, value, metric):
        return records.Claim(
            id=cid,
            statement=cid,
            kind="fact",
            evidence_ids=["E1"],
            dimension=metric,
            quantity=_quantity(value),
        )

    claims = {
        "C1": numeric("C1", 52.0, hostile),
        "C2": numeric("C2", 40.0, hostile),
        "C8": numeric("C8", 3.0, "capex"),
        "C9": numeric("C9", 2.0, "capex"),
    }
    capex = records.Calculation(
        id="K1",
        kind="ratio",
        label="capex",
        formula="C8 / C9",
        inputs=[
            records.CalcInput(
                claim_id=cid, claim_version=1, quantity=_quantity(1.0)
            )
            for cid in ("C8", "C9")
        ],
        status="ok",
        result=1.5,
    )
    claims["C3"] = records.Claim(
        id="C3",
        statement="r",
        kind="derived",
        calculation_id="K1",
        calculation_version=1,
        evidence_ids=["E1"],
    )
    finding = records.Finding(
        id="F1",
        conclusion="A is twice B",
        claim_ids=["C1", "C2", "C8", "C9", "C3"],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        compares=["C1", "C2", "C8", "C9"],
    )
    assert (
        graph_module.uncomputed_comparison(finding, claims, {"K1": capex})
        == "C1, C2"
    )


def test_u2_r3_01_candidate_import_uses_the_one_matching_rule():
    """A local substring test here imported an objection to a shorter
    list item into a section holding a longer one (U2-R3-01)."""
    longer = records.Section(
        id="spec", title="S", text="- Capacity: 100 units\n- Uptime: 99%"
    )
    candidate = records.DeliveryCandidate(
        draft_version=1,
        sections=[longer],
        subject=records.ReviewSubject(digest="d"),
        issues={},
    )
    shorter = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="spec",
        requested_action="remove",
        text="- Capacity: 10",
        draft_version=2,
    )
    applies = graph_module.issues_for_candidate(candidate, {"I1": shorter})
    assert applies == {}, "the longer item does not hold the shorter one"
    # So the section stays deliverable rather than being withheld whole.
    assert report.blocking_issues(list(applies.values()), longer) == []
    # And the exact item is still importable where it does occur.
    exact = records.Section(
        id="spec", title="S", text="- Capacity: 10\n- Uptime: 99%"
    )
    on_exact = graph_module.issues_for_candidate(
        candidate.model_copy(update={"sections": [exact]}), {"I1": shorter}
    )
    assert [i.target for i in on_exact.values()] == ["spec"]
