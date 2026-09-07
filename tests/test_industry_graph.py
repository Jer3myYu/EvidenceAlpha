"""The industry graph with fake roles and a fake worker.

Covers the happy path to delivery, dependency waves, worker crashes
with resume in a fresh and in the same runtime, two consecutive
interruptions of a single call, budget exhaustion, issue routing with
the no-progress stop, and the revision route after the final review.
"""

import asyncio
import pathlib

import pytest
from langgraph.checkpoint.memory import MemorySaver

from industry import budget
from industry import coverage
from industry import graph as graph_module
from industry import merge
from industry import report
from industry import records
from industry import roles
from research import persist

NOW = "2026-09-07T00:00:00+00:00"
USAGE = records.Usage(turns=2, duration_s=1.0)


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
        self.scope_failures = 0
        self.plans = [
            roles.TaskPlan(
                tasks=[
                    roles.TaskSpec(
                        key="a", role="industry", objective="upstream"
                    ),
                    roles.TaskSpec(
                        key="b",
                        role="company",
                        objective="companies",
                        depends_on=["a"],
                    ),
                ]
            )
        ]
        self.review_verdict = "supported"
        self.draft_text = "掩模版市场规模 52亿元 [C1][C2]。"
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

    async def write(self, state, instructions, max_turns, deadline):
        del state, max_turns, deadline
        self.calls.append(
            "write:" + ("revise" if "Revise" in instructions else "full")
        )
        return (
            roles.Draft(
                sections=[
                    roles.SectionSpec(
                        id="intro", title="概览", text=self.draft_text
                    )
                ]
            ),
            USAGE,
        )

    async def final_review(self, state, max_turns, deadline):
        del state, max_turns, deadline
        self.calls.append("final")
        return (
            records.DraftReview(
                issues=list(self.final_issues), consistent=not self.final_issues
            ),
            USAGE,
        )


def make(tmp_path, limits=None, saver=None):
    runtime = budget.Runtime(
        limits or records.Limits(), reports_dir=str(tmp_path / "reports")
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
    assert [t.status for t in state["tasks"].values()] == [
        "done",
        "done",
        "done",
    ]
    assert {c.task_id: c.status for c in state["single_calls"].values()} == {
        "scope": "done",
        "prepare_tasks": "done",
        "assess_coverage": "done",
        "analyze": "done",
        "review": "done",
        "write": "done",
        "final_review": "done",
    }
    assert len(state["coverage"]) == 8
    assert state["map"].segments
    assert state["relationships"]["R1"].confirmed
    spent = budget.ledger(state)
    assert spent.task_executions == 3
    calls = state["single_calls"].values()
    assert all(c.status == "done" for c in calls)
    assert spent.turns == 3 * 3 + sum(c.observed.turns for c in calls)
    assert api.calls[0] == "scope" and api.calls[1].startswith("plan:")
    # The fixture's material claims exceed one review batch; the loop
    # reviews them in consecutive calls before analysis.
    reviews = [c for c in api.calls if c == "review"]
    reviewable = sum(
        1 for c in state["claims"].values() if c.material or c.map_ref
    )
    assert len(reviews) == -(-reviewable // graph_module.REVIEW_BATCH) >= 2
    assert graph_module.review_remaining(state) == 0
    assert [c for c in api.calls[2:] if c != "review"] == [
        "analyze",
        "assess",
        "write:full",
        "final",
    ]
    assessments = [c for c in state["single_calls"] if c.startswith("assess")]
    assert len(assessments) <= 1 + runtime.limits.follow_up_rounds
    assert worker.order == ["T1.1", "T2.1", "T3.1"], "waves follow dependencies"
    assert all(isinstance(w, records.WorkerInput) for w in worker.calls)
    assert worker.calls[1].brief.industry == "光掩模产业调研"


def test_worker_crash_keeps_siblings_and_resumes_with_a_new_attempt(tmp_path):
    saver = MemorySaver()
    runtime, api, worker, compiled = make(tmp_path, saver=saver)
    api.plans = [
        roles.TaskPlan(
            tasks=[
                roles.TaskSpec(key="a", role="industry", objective="upstream"),
                roles.TaskSpec(key="b", role="company", objective="companies"),
            ]
        )
    ]
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
    assert state["meta"].report_status == "complete_with_limitations"
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
    runtime, api, worker, compiled = make(tmp_path)
    api.plans = [
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
        )
    ]
    config = persist.thread_config("t9")
    runtime.begin("t9")
    state = run(compiled.ainvoke({"question": "q"}, config))
    tasks = state["tasks"]
    assert tasks["T2"].objective == "companies" and tasks["T2"].depends_on == [
        "T3"
    ]
    assert tasks["T3"].objective == "upstream" and "T4" not in tasks
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
    assert state["meta"].report_status == "complete_with_limitations"
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

    async def write(state, instructions, max_turns, deadline):
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
    limits = records.Limits(calc_requests_per_call=1, acquisitions_per_review=1)
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
    reviews = sum(1 for c in api.calls if c == "review")
    assert 0 < len(acquisitions) <= reviews
    assert any(
        "acquisition requests, the first 1 taken" in l
        for l in state["route_log"]
    )


def test_acquisition_attempts_are_capped_for_the_run(tmp_path):
    limits = records.Limits(acquisitions_per_review=3, acquisition_executions=1)
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
    skipped = [t for t in acquisition_tasks if t.status == "skipped"]
    assert len(executed) == 1 and skipped
    assert all(
        "acquisition attempts is the cap" in t.skip_reason for t in skipped
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
    assert state["meta"].report_status == "complete_with_limitations"
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
    quantity = records.Quantity(
        value=52, unit="亿元", period="2024", as_written="52亿元"
    )
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
        inputs=[records.CalcInput(claim_id="C1", value=52, unit="亿元")],
        formula="f",
        result=52.0,
        unit="%",
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
    state = {
        "claims": {
            "C1": records.Claim(
                id="C1",
                statement="an input",
                kind="fact",
                evidence_ids=["E1"],
                quantity=records.Quantity(
                    value=52, unit="亿元", as_written="52亿元"
                ),
                review="supported",
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
                inputs=[
                    records.CalcInput(claim_id="C1", value=52, unit="亿元")
                ],
                formula="f",
                result=52.0,
                unit="%",
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
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="a measured claim",
            kind="fact",
            evidence_ids=["E1"],
            review="unreviewed",
            material=True,
            partition="q4",
            questions=[4],
        ),
        "C3": records.Claim(
            id="C3",
            statement="share: 52.0 %",
            kind="derived",
            evidence_ids=["E1"],
            calculation_id="K1",
            calculation_version=1,
            quantity=records.Quantity(value=52.0, unit="%", as_written="52.0"),
            review="unreviewed",
            material=True,
            partition="q4",
            questions=[4],
        ),
    }
    stopped = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[records.CalcInput(claim_id="C1", value=52, unit="亿元")],
        formula="f",
        status="error",
        message="stale_input: C1 changed after the calculation",
    )
    state = {"claims": claims, "calculations": {"K1": stopped}}
    assert graph_module.pending_review(state, 10) == ["C1"]
    assert graph_module.review_remaining(state) == 1
    # Once the calculation is current again, it queues normally.
    # Current again, and agreeing with the claim: it queues normally.
    state["claims"]["C1"] = claims["C1"].model_copy(
        update={"review": "supported", "review_reason": None}
    )
    state["calculations"]["K1"] = stopped.model_copy(
        update={"status": "ok", "message": None, "result": 52.0, "unit": "%"}
    )
    assert graph_module.pending_review(state, 10) == ["C3"]
