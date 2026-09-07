"""The industry graph with fake roles and a fake worker.

Covers the happy path to delivery, dependency waves, worker crashes
with resume in a fresh and in the same runtime, two consecutive
interruptions of a single call, budget exhaustion, issue routing with
the no-progress stop, and the revision route after the final review.
"""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from industry import budget
from industry import graph as graph_module
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
            "usage": records.Usage(turns=3, tool_calls=2, duration_s=2.0),
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
    assert api.calls[2:] == [
        "review",
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
    limits = records.Limits(model_calls=14, model_call_reserve=12)
    runtime, api, _, compiled = make(tmp_path, limits)
    config = persist.thread_config("t5")
    runtime.begin("t5")
    state = run(compiled.ainvoke({"question": "q"}, config))
    assert "scope" not in api.calls  # 14 - 12 reserve < 5: refused
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
    # An open editorial issue is a limitation, not a central gap.
    assert state["meta"].report_status == "complete_with_limitations"


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
    limits = records.Limits(model_calls=8, model_call_reserve=0)
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
    # 8 - 5 charged = 3 left: an intermediate call needs 5, so no reservation.
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
    assert updates["single_calls"]["write.2"].reserved.turns == 3
    assert budget.ledger({"attempts": {}, **updates}).turns == 8


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
