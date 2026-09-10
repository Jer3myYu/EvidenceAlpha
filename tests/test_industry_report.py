"""The delivered report: removability, redaction, and delivery status.

Headline live run 4 (thread `b9632d7d`, 2026-09-08) delivered a report
whose limitations listed issues that no redaction had applied, and a
table a redaction had broken. These cover the removability contract of
plan revision 33 §4.39.8: an issue counts as removed only when its exact
unit is actually gone, and a table survives a row removal or the removal
fails closed.
"""

import dataclasses
import json
import pathlib

import quantity_support as support

from industry import coverage as coverage_module
from industry import merge
from industry import records
from industry import report

from industry import roles

TABLE = (
    "| 公司 | 份额 |\n" "|---|---|\n" "| HOYA | 60% |\n" "| DNP | 5% [C1] |\n"
)


def _section(text: str) -> records.Section:
    return records.Section(
        id="economics", title="经济性", text=text, claim_ids=["C1"]
    )


def _issue(text: str | None) -> records.Issue:
    return records.Issue(
        id="I1",
        key="unsupported:economics:x",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="edit",
        description="uncited sentence with a number",
        text=text,
    )


def _state(section: records.Section, issue: records.Issue) -> dict:
    return {
        "brief": roles.default_brief("光掩模产业调研"),
        "draft_version": 1,
        "sections": [section],
        "claims": {
            "C1": records.Claim(
                id="C1", statement="s", kind="fact", review="supported"
            )
        },
        "evidence": {},
        "sources": {},
        "source_versions": {},
        "findings": {},
        "issues": {issue.id: issue},
    }


def _covered() -> list[records.Coverage]:
    return [
        records.Coverage(question=q, status="covered")
        for q in records.REQUIRED_QUESTIONS
    ]


def test_stale_issue_text_is_not_a_successful_redaction():
    # Defect 1. `not i.text` asked whether the issue carries a text
    # field, not whether that text is still in the draft. An issue
    # outliving the draft its text came from passed the gate, redact
    # silently did nothing, and the run reported
    # complete_with_limitations with the section intact.
    section = _section("豪雅份额超过60%[C1]。")
    state = _state(section, _issue("一句在草稿里根本不存在的话。"))
    assert len(report.unremovable_section_issues(state)) == 1
    assert (
        coverage_module.report_status(_covered(), state, verified=True)
        == "incomplete"
    )


def test_a_present_unit_is_removable_and_redacted():
    section = _section("豪雅份额超过60%[C1]。不受支持的一句。")
    state = _state(section, _issue("不受支持的一句。"))
    assert not report.unremovable_section_issues(state)
    out = report.redact(
        section.text, list(state["issues"].values()), "economics", "[removed]"
    )
    assert "不受支持的一句。" not in out
    assert "[removed]" in out
    assert "豪雅份额超过60%[C1]。" in out


def test_removing_a_table_row_keeps_the_table_valid():
    # Defect 2. Replacing the row line in place left the note between
    # the separator and the surviving rows, destroying the table.
    section = _section(TABLE)
    state = _state(section, _issue("| HOYA | 60% |"))
    assert not report.unremovable_section_issues(state)
    out = report.redact(
        section.text, list(state["issues"].values()), "economics", "[removed]"
    )
    lines = [line for line in out.split("\n") if line.strip()]
    assert lines[0] == "| 公司 | 份额 |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| DNP | 5% [C1] |"
    assert "| HOYA | 60% |" not in out
    # The note sits outside the table, never between its rows.
    assert lines[3] == "[removed]"
    for line in out.split("\n"):
        assert not (line.startswith("|") and "[removed]" in line)


def test_a_row_removal_that_would_empty_the_table_fails_closed():
    # The only data row cannot be removed without leaving a headed table
    # with nothing in it, so the issue is unremovable and the status
    # fails closed rather than delivering a broken or empty table.
    one_row = "| 公司 | 份额 |\n|---|---|\n| HOYA | 60% |\n"
    section = _section(one_row)
    state = _state(section, _issue("| HOYA | 60% |"))
    assert len(report.unremovable_section_issues(state)) == 1
    assert (
        coverage_module.report_status(_covered(), state, verified=True)
        == "incomplete"
    )
    out = report.redact(
        section.text, list(state["issues"].values()), "economics", "[removed]"
    )
    assert out == one_row


def test_an_issue_without_text_stays_unremovable():
    section = _section("豪雅份额超过60%[C1]。")
    state = _state(section, _issue(None))
    assert len(report.unremovable_section_issues(state)) == 1
    assert (
        coverage_module.report_status(_covered(), state, verified=True)
        == "incomplete"
    )


# --- the Level A/B/C delivery contract (plan revision 33 §4.39) -------------


def _claim(cid, statement, **kw):
    return records.Claim(
        id=cid,
        statement=statement,
        kind=kw.pop("kind", "fact"),
        review="supported",
        evidence_ids=["E1"],
        material=True,
        **kw,
    )


def useful_state(body: str) -> dict:
    """A state whose delivered body clears the usefulness floor."""
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id=f"G{n}",
                name=name,
                stage=stage,
                description="d",
                claim_id=cid,
            )
            for n, name, stage, cid in (
                (1, "上游", "upstream", "C3"),
                (2, "中游", "midstream", "C4"),
                (3, "下游", "downstream", "C5"),
            )
        ],
        links=[
            records.Link(
                id="L1",
                from_segment="G1",
                to_segment="G2",
                what_flows="掩模基板",
                claim_id="C6",
            )
        ],
        participants=[
            records.Participant(
                id="P1",
                name="HOYA",
                segment_id="G1",
                role="supplier",
                selection_rationale="r",
                claim_id="C7",
                supplies="掩模基板",
            )
        ],
    )
    claims = {
        "C1": _claim(
            "C1", "产品定义", topics=["product"], reviewed_topics=["product"]
        ),
        "C2": _claim(
            "C2", "边界说明", topics=["boundary"], reviewed_topics=["boundary"]
        ),
        "C3": _claim("C3", "上游环节", kind="map", map_ref="G1"),
        "C4": _claim("C4", "中游环节", kind="map", map_ref="G2"),
        "C5": _claim("C5", "下游环节", kind="map", map_ref="G3"),
        "C6": _claim("C6", "上游连接中游", kind="map", map_ref="L1"),
        "C7": _claim("C7", "HOYA供应掩模基板", kind="map", map_ref="P1"),
        "C8": _claim(
            "C8",
            "技术壁垒很高",
            topics=["barrier"],
            reviewed_topics=["barrier"],
        ),
    }
    return {
        "brief": roles.default_brief("光掩模产业调研"),
        "sections": [
            records.Section(
                id="intro",
                title="概述",
                text=body,
                claim_ids=report.cited_claims(body),
            )
        ],
        "claims": claims,
        "map": industry_map,
        "evidence": {},
        "sources": {},
        "source_versions": {},
        "findings": {},
        "calculations": {},
        "relationships": {},
        "issues": {},
        "coverage": [],
        "draft_version": 1,
    }


BODY = (
    "产品定义[C1]。边界说明[C2]。上游环节[C3]。中游环节[C4]。"
    "下游环节[C5]。上游连接中游[C6]。HOYA供应掩模基板[C7]。技术壁垒很高[C8]。"
)


def rows(overrides: dict | None = None) -> list[records.Coverage]:
    """Eight coverage rows, ``covered`` unless overridden."""
    overrides = overrides or {}
    return [
        records.Coverage(question=q, status=overrides.get(q, "covered"))
        for q in sorted(records.REQUIRED_QUESTIONS)
    ]


def certify(state: dict, consistent: bool = True, retainable=None) -> dict:
    """Give the state a certificate over its current body."""
    subject = report.review_subject(state, state.get("coverage") or [])
    state["review_subject"] = subject
    state["final_review"] = records.DraftReview(
        consistent=consistent, retainable=list(retainable or [])
    )
    state["final_review_version"] = state["draft_version"]
    return state


def _classify(state: dict, coverage: list[records.Coverage] | None = None):
    plan = report.plan_delivery(state, "[removed]")
    if coverage is None:
        coverage = coverage_module.derive(state, None)
    return plan, coverage_module.classify_delivery(state, coverage, plan)


def test_a_verified_unchanged_body_is_level_a():
    state = certify(useful_state(BODY))
    plan, result = _classify(state, rows())
    assert plan.certified and not plan.changed
    assert result.level == "verified"
    assert result.status == "complete"


def test_a_verified_body_with_disclosed_limitations_is_level_a():
    # A minor, disclosed issue is a limitation, not a redaction: the
    # body is untouched, so the certificate still covers it.
    state = certify(useful_state(BODY))
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="wording:intro",
            category="wording",
            severity="minor",
            target="intro",
            requested_action="edit",
            description="缩写未解释",
        )
    }
    # Q6 short of covered: a disclosed coverage limitation, not a
    # redaction, so the certificate still covers the delivered words.
    _, result = _classify(state, rows({6: "partial"}))
    assert result.level == "verified"
    assert result.status == "complete_with_limitations"


def test_skipped_final_verification_is_never_level_a():
    state = useful_state(BODY)  # no certificate at all
    plan, result = _classify(state)
    assert not plan.certified
    assert result.level != "verified"
    assert result.status == "incomplete"
    assert "no final review" in result.reason


def test_an_unverified_but_useful_body_is_level_b():
    # The latest draft has no review, but every unit repeats a claim
    # statement the verifier approved for standalone use, so the exact
    # wording is supported and the body is still worth delivering.
    state = useful_state(BODY)
    state["claims"] = {
        cid: claim.model_copy(update={"standalone": True})
        for cid, claim in state["claims"].items()
    }
    plan, result = _classify(state)
    assert result.level == "partial"
    assert result.status == "incomplete"
    assert plan.sections and plan.sections[0].text
    assert "[C1]" in plan.sections[0].text


def test_unreviewed_wording_is_not_retained_on_citation_presence():
    # The exact-wording rule. This sentence carries a valid citation to
    # a supported claim and says something that claim does not say; the
    # deterministic citation check cannot tell, so nothing retains it.
    state = useful_state(BODY + "该公司2025年已实现量产并增长99%[C1]。")
    state["claims"] = {
        cid: claim.model_copy(update={"standalone": True})
        for cid, claim in state["claims"].items()
    }
    plan, _ = _classify(state)
    assert plan.sections
    assert "量产" not in plan.sections[0].text


def test_a_substantive_redaction_without_re_review_is_level_b_at_best():
    state = certify(useful_state(BODY + "未获支持的一句。"))
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="unsupported:intro#1",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="edit",
            description="unsupported",
            text="未获支持的一句。",
        )
    }
    plan, result = _classify(state)
    assert plan.changed
    assert result.level == "partial"
    assert result.status == "incomplete"
    assert "未获支持的一句。" not in plan.sections[0].text


def test_a_body_below_the_usefulness_floor_is_level_c():
    state = certify(useful_state("孤立的一句[C1]。"))
    _, result = _classify(state)
    assert result.level == "diagnostic_only"
    assert result.status == "incomplete"
    assert not result.sections
    # The body is too thin to teach anything: it loses the mandatory
    # questions before the claim count even matters.
    assert "uncovered" in result.floor


def test_a_structural_redaction_failure_withholds_the_section():
    # The only data row cannot go without emptying the table, so the
    # removal escalates to the section, and with nothing left the
    # delivery falls to diagnostics.
    table = "| 公司 | 份额 |\n|---|---|\n| HOYA | 60% |\n"
    state = certify(useful_state(table))
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="unsupported:intro#row",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="edit",
            description="unsupported row",
            text="| HOYA | 60% |",
        )
    }
    plan, result = _classify(state)
    assert plan.removed == ["intro"]
    assert result.level == "diagnostic_only"
    assert not plan.sections


def test_a_certificate_cannot_migrate_to_a_changed_body():
    state = certify(useful_state(BODY))
    assert report.certificate_applies(state)
    # The same draft version, one reworded sentence.
    state["sections"] = [
        state["sections"][0].model_copy(
            update={"text": BODY + "新增的一句[C1]。"}
        )
    ]
    assert not report.certificate_applies(state)
    _, result = _classify(state)
    assert result.level != "verified"


def test_a_certificate_cannot_survive_a_requalified_claim():
    state = certify(useful_state(BODY))
    assert report.certificate_applies(state)
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "qualified", "review_reason": "仅限商用市场"}
    )
    assert not report.certificate_applies(state)


def test_the_delivered_report_states_the_level_above_the_body():
    state = useful_state(BODY)
    state["claims"] = {
        cid: claim.model_copy(update={"standalone": True})
        for cid, claim in state["claims"].items()
    }
    plan, result = _classify(state)
    derived = coverage_module.derive(state, None)
    text = report.render(state, derived, result.status, result, plan)
    head = text.split("## ", maxsplit=1)[0]
    assert "部分研究报告" in head
    assert "未经完整最终核验" in head
    assert result.reason in head


def test_a_withheld_body_is_absent_from_the_delivered_report():
    state = certify(useful_state("孤立的一句[C1]。"))
    plan, result = _classify(state)
    derived = coverage_module.derive(state, None)
    text = report.render(state, derived, result.status, result, plan)
    assert "孤立的一句" not in text
    assert "仅提供诊断信息" in text


def test_delivery_renders_the_reviewed_appendix_not_a_fresh_one():
    state = useful_state(BODY)
    state["coverage"] = [records.Coverage(question=4, status="partial")]
    state = certify(state)
    frozen = list(state["review_subject"].appendix)
    # The workflow moves on after the review: a new issue is opened.
    state["issues"] = {
        "I9": records.Issue(
            id="I9",
            key="missing_evidence:Q8",
            category="missing_evidence",
            severity="material",
            target="Q8",
            requested_action="research",
            description="Q8 uncovered",
        )
    }
    plan, result = _classify(state)
    derived = coverage_module.derive(state, None)
    text = report.render(state, derived, result.status, result, plan)
    for line in frozen:
        if line.strip():
            assert line in text
    # What moved since is reported separately, never written into them.
    assert "Q8 uncovered" not in "\n".join(frozen)
    assert "Q8 uncovered" in text


def test_the_usefulness_floor_is_one_rule_with_pinned_boundaries():
    # Calibrated 2026-09-09 against headline run 4 and the fixed-evidence
    # fixtures. Each constant is pinned on its own boundary, so a later
    # change to any of them has to be deliberate.
    state = useful_state(BODY)
    body = [state["sections"][0]]
    assert coverage_module.meets_floor(state, body)[0]

    # eight supported claims survive in the body: eight passes, nine does not
    floor = coverage_module.FLOOR
    assert coverage_module.meets_floor(
        state, body, dataclasses.replace(floor, min_supported_claims=8)
    )[0]
    ok, why = coverage_module.meets_floor(
        state, body, dataclasses.replace(floor, min_supported_claims=9)
    )
    assert not ok and "9 supported claims" in why

    # three central questions have surviving content: four does not
    assert coverage_module.meets_floor(
        state, body, dataclasses.replace(floor, central_required=3)
    )[0]
    ok, why = coverage_module.meets_floor(
        state, body, dataclasses.replace(floor, central_required=4)
    )
    assert not ok and "central" in why

    # a mandatory question with nothing behind it fails closed
    ok, why = coverage_module.meets_floor(
        state, body, dataclasses.replace(floor, mandatory_questions=(1, 2, 7))
    )
    assert not ok and "Q7 uncovered" in why


def test_the_floor_needs_a_definition_or_a_boundary_but_not_both():
    # The calibration finding: requiring product *and* boundary, and a
    # participant role besides, withheld real reports of 18 and 19
    # supported claims answering four of five central questions.
    state = useful_state(BODY)
    body = [state["sections"][0]]
    for dropped in ("product", "boundary"):
        thinned = {
            cid: (
                claim.model_copy(update={"reviewed_topics": []})
                if dropped in claim.reviewed_topics
                else claim
            )
            for cid, claim in state["claims"].items()
        }
        assert coverage_module.meets_floor({**state, "claims": thinned}, body)[
            0
        ]
    without = {
        cid: (
            claim.model_copy(update={"reviewed_topics": []})
            if {"product", "boundary"} & set(claim.reviewed_topics)
            else claim
        )
        for cid, claim in state["claims"].items()
    }
    ok, why = coverage_module.meets_floor({**state, "claims": without}, body)
    assert not ok and "product definition or industry boundary" in why


def test_a_registry_claim_the_body_never_cites_does_not_count():
    # The floor counts what the delivered body says, never the registry:
    # a finding nobody copied into the report teaches the reader nothing.
    state = useful_state("产品定义[C1]。")
    body = [state["sections"][0]]
    kept = coverage_module.delivered_claims(state, body)
    assert set(kept) == {"C1"}
    assert not coverage_module.meets_floor(state, body)[0]


# --- plan revision 37 §4.44: strength and coverage are two floors ----------


def _qualify(state: dict, *ids: str, reason: str = "片段无原文佐证") -> dict:
    """Requalify claims the way the Verifier's snippet rule does."""
    for cid in ids:
        state["claims"][cid] = state["claims"][cid].model_copy(
            update={"review": "qualified", "review_reason": reason}
        )
    return state


def arm_state(supported_facts: int = 6) -> dict:
    """A body shaped like the recorded fixture arms.

    The after arm (thread `a1ce9159`) delivered 45 cited claims, all of
    them citable: 12 `supported` and 33 `qualified`, 16 of its 19 map
    claims among the latter, because a claim resting on a search
    snippet without original context is `qualified` by definition. Here
    the map claims carry the industry explanation and are qualified,
    while a handful of plain facts stay supported.
    """
    state = useful_state(BODY)
    text = state["sections"][0].text
    for n in range(9, 9 + supported_facts):
        cid = f"C{n}"
        state["claims"][cid] = _claim(
            cid,
            f"事实{n}",
            topics=["demand_driver"],
            reviewed_topics=["demand_driver"],
        )
        text += f"事实{n}[{cid}]。"
    state["sections"] = [
        records.Section(
            id="intro",
            title="概述",
            text=text,
            claim_ids=report.cited_claims(text),
        )
    ]
    return _qualify(state, "C3", "C4", "C5", "C6", "C7")


def test_coverage_counts_citable_claims_and_strength_counts_supported():
    # The blocker of 2026-09-09: `delivered_claims` kept only supported
    # claims, so the floor judged a body by a third of the evidence it
    # legitimately rests on. Coverage is `C(D)`, the minimum is `P(D)`.
    state = arm_state()
    body = state["sections"]
    kept = coverage_module.delivered_claims(state, body)
    assert len(kept) == 14
    assert set(coverage_module.delivered_strength(kept)) == {
        "C1",
        "C2",
        "C8",
        "C9",
        "C10",
        "C11",
        "C12",
        "C13",
        "C14",
    }
    row = {
        c.question: c for c in coverage_module.delivery_coverage(state, body)
    }
    # The qualified map claims carry Q1 and Q2, exactly as they do in
    # `derive` over the registry everywhere else in the system.
    assert row[1].status != "uncovered"
    assert row[2].status != "uncovered"
    assert "C6" in row[2].claim_ids
    ok, why = coverage_module.meets_floor(state, body)
    assert ok and "14 citable claims (9 supported)" in why


def test_qualified_claims_never_satisfy_the_supported_minimum():
    # Five supported claims and any number of qualified ones is still
    # five: the strength floor is `P(D)` alone.
    state = arm_state(supported_facts=2)
    body = state["sections"]
    kept = coverage_module.delivered_claims(state, body)
    strong = coverage_module.delivered_strength(kept)
    assert len(kept) == 10 and len(strong) == 5
    row = {
        c.question: c.status
        for c in coverage_module.delivery_coverage(state, body)
    }
    assert row[1] != "uncovered" and row[2] != "uncovered"
    ok, why = coverage_module.meets_floor(state, body)
    assert not ok and "5 of 6 supported claims" in why


def test_a_qualification_off_the_record_earns_no_coverage_and_no_topic():
    # `Claim.is_reviewed`: a qualified claim whose reason is missing
    # cannot carry its restriction to the reader, so it is not citable
    # -- and a claim that may not be cited may not be counted either.
    state = arm_state()
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "qualified", "review_reason": None}
    )
    body = state["sections"]
    kept = coverage_module.delivered_claims(state, body)
    assert "C1" not in kept
    state["claims"]["C2"] = state["claims"]["C2"].model_copy(
        update={"review": "qualified", "review_reason": None}
    )
    ok, why = coverage_module.meets_floor(state, body)
    assert not ok and "product definition or industry boundary" in why


def test_a_qualified_definition_anchor_satisfies_the_third_rule():
    # Rule 3 asks for a verifier-confirmed topic, not a supported one.
    state = arm_state()
    state = _qualify(state, "C1", "C2")
    body = state["sections"]
    ok, why = coverage_module.meets_floor(state, body)
    assert ok and "citable claims" in why


def test_the_before_arm_shape_still_withholds_with_qualified_counted():
    # The before arm (thread `ef342cca`) fails Q2 on its own content:
    # counting its 22 qualified claims changes nothing, because no
    # surviving claim establishes a value-chain link at all. Counting
    # citable claims is not a blanket pass.
    state = arm_state()
    text = state["sections"][0].text.replace("上游连接中游[C6]。", "")
    state["sections"] = [
        records.Section(
            id="intro",
            title="概述",
            text=text,
            claim_ids=report.cited_claims(text),
        )
    ]
    body = state["sections"]
    row = {
        c.question: c.status
        for c in coverage_module.delivery_coverage(state, body)
    }
    assert row[2] == "uncovered"
    ok, why = coverage_module.meets_floor(state, body)
    assert not ok and "Q2 uncovered" in why
    state = certify(state, consistent=False)
    _, result = _classify(state)
    assert result.level == "diagnostic_only" and not result.sections


def test_the_after_arm_shape_is_level_b_only_once_its_issue_is_handled():
    # Both halves of revision 37 in one place. With no unresolved
    # material issue the body is a useful partial report; with I23 --
    # open, material, `unsupported`, naming no removable unit -- the
    # section goes, and with it the body.
    state = certify(arm_state(), consistent=False)
    _, result = _classify(state)
    assert result.level == "partial" and result.sections == ["intro"]
    state["issues"] = {
        "I23": records.Issue(
            id="I23",
            key="unsupported:intro:china",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="remove",
            description="[intro] 中国厂商尚无量产迹象[C6]，但该主张并未如此陈述",
        )
    }
    plan, result = _classify(state)
    assert plan.removed == ["intro"] and not plan.sections
    assert "I23" in " ".join(plan.reasons)
    assert result.level == "diagnostic_only" and not result.sections


def test_a_material_issue_naming_no_removable_unit_removes_its_section():
    # Every model-authored final-review issue carries no text
    # (`SectionIssue` has none), so exact-unit removal could never
    # target it and the offending sentence stayed in the body.
    section = _section("豪雅份额超过60%[C1]。")
    state = _state(section, _issue(None))
    assert [i.id for i in report.blocking_issues([_issue(None)], section)] == [
        "I1"
    ]
    plan = report.plan_delivery(certify(state), "[removed]")
    assert plan.removed == ["economics"] and not plan.sections
    assert plan.changed


def test_one_authority_answers_whether_an_issue_can_be_removed():
    # `unremovable_section_issues` (the status) and `plan_delivery`
    # (the body) read the same rule, so they cannot disagree.
    for text in (None, "一句在草稿里根本不存在的话。"):
        section = _section("豪雅份额超过60%[C1]。")
        state = _state(section, _issue(text))
        blocked = report.unremovable_section_issues(state)
        plan = report.plan_delivery(certify(state), "[removed]")
        assert [i.id for i in blocked] == ["I1"]
        assert plan.removed == ["economics"]


def test_a_row_removal_that_would_empty_a_table_takes_the_section():
    # Fail closed, and never render half a table: the note would
    # otherwise stand between the rule and nothing.
    one_row = "| 公司 | 份额 |\n|---|---|\n| DNP | 5% [C1] |\n"
    section = _section(one_row)
    state = _state(section, _issue("| DNP | 5% [C1] |"))
    plan = report.plan_delivery(certify(state), "[removed]")
    assert plan.removed == ["economics"] and not plan.sections


def test_citability_is_validated_wider_than_credit_is_counted():
    # A delivered body cites a derived claim without citing the claims
    # it was computed from; `producer_chain_intact` walks those, so the
    # credit set must not be the registry the check reads.
    state = useful_state(BODY)
    quantity = support.bound(52, "亿元", "E1", "52亿元", period="2024")
    parent = records.Claim(
        id="C21",
        statement="Acme 2024 revenue was 52亿元",
        kind="fact",
        review="supported",
        evidence_ids=["E1"],
        quantity=quantity,
        material=True,
    )
    state["claims"]["C21"] = parent
    calculation = records.Calculation(
        id="K1",
        kind="share",
        label="share",
        inputs=[support.cinput(parent)],
        formula="f",
        result=52.0,
        unit=support.unit("%"),
        status="ok",
    )
    state["calculations"] = {"K1": calculation}
    fields = merge.derived_fields(calculation, {"C21": parent})
    state["claims"]["C20"] = records.Claim(
        id="C20",
        kind="derived",
        material=True,
        topics=["product"],
        reviewed_topics=["product"],
        **fields,
    )
    text = BODY + "推导结论[C20]。"
    state["sections"] = [
        records.Section(
            id="intro",
            title="概述",
            text=text,
            claim_ids=report.cited_claims(text),
        )
    ]
    body = state["sections"]
    kept = coverage_module.delivered_claims(state, body)
    assert "C20" in kept and "C21" not in kept
    row = {
        c.question: c for c in coverage_module.delivery_coverage(state, body)
    }
    assert "C20" in row[1].claim_ids
    # Validating against the credit set alone loses it: the producer is
    # not there to be found.
    narrow = {
        c.question: c
        for c in coverage_module.derive({**state, "claims": kept}, None)
    }
    assert "C20" not in narrow[1].claim_ids
    # A withdrawn producer still withdraws the result.
    state["claims"]["C21"] = parent.model_copy(update={"review": "unsupported"})
    assert "C20" not in coverage_module.delivered_claims(state, body)


def test_delivery_reports_what_it_could_not_strengthen():
    # Plan revision 39 §4.46.5: a deferred repair is a gap the reader is
    # entitled to see. §4.45.4 asserted this and nothing implemented it.
    state = useful_state(BODY)
    state["repairs"] = {
        "RQ1": records.RepairRequest(
            id="RQ1",
            claim_id="C1",
            objective="open the original filing behind the 66% figure",
            status="deferred",
            reason="seconds: the repair and the review it needs do not fit",
        ),
        "RQ2": records.RepairRequest(
            id="RQ2",
            claim_id="C2",
            objective="x",
            status="done",
            reason="evidence attached",
        ),
    }
    lines = report.repair_lines(state)
    text = "\n".join(lines)
    assert "证据补强" in text
    assert "RQ1" not in text  # the claim and the reason, not the ids
    assert "C1" in text and "original filing" in text
    assert "seconds:" in text
    state["repairs"] = {}
    assert not report.repair_lines(state)


def _section(text: str) -> records.Section:
    return records.Section(id="economics", title="Economics", text=text)


def test_a14_blocks_are_derived_from_the_text_they_name():
    section = _section(
        "Mask blanks are concentrated [C1].\n\n"
        "This compresses margins.\n\n"
        "| vendor | share |\n| --- | --- |\n| HOYA | 60% |"
    )
    blocks = report.blocks_of(section)
    assert [b.id for b in blocks] == [f"economics:b{n}" for n in range(1, 6)]
    assert [b.kind for b in blocks] == [
        "paragraph",
        "paragraph",
        "row",
        "row",
        "row",
    ]
    # A projection cannot drift from its text: editing re-derives.
    edited = _section(section.text.replace("compresses", "widens"))
    assert report.blocks_of(edited)[1].sha256 != blocks[1].sha256
    assert report.blocks_of(edited)[1].id == blocks[1].id


def test_a14_a_resolving_block_removes_one_unit_not_the_section():
    section = _section(
        "Mask blanks are concentrated [C1].\n\nThis compresses margins."
    )
    block = report.resolve_block([section], "economics", "economics:b2")
    assert block is not None and block.text == "This compresses margins."
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        text=block.text,
    )
    # The section is not blocked, and only the named unit goes.
    assert report.blocking_issues([issue], section) == []
    redacted = report.redact(section.text, [issue], "economics", "[removed]")
    assert "concentrated [C1]" in redacted
    assert "compresses margins" not in redacted


def test_a20_an_unresolvable_block_falls_back_to_whole_section_removal():
    """U0-04: this delta may only make removal more precise, never weaker."""
    section = _section("Mask blanks are concentrated [C1].")
    for block_id in (None, "", "economics:b99", "barriers:b1"):
        assert report.resolve_block([section], "economics", block_id) is None
    # An issue with no text is exactly what run 7's model-authored issues
    # were, and it still takes the section.
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        text=None,
    )
    assert report.blocking_issues([issue], section) == [issue]


def test_a20_a_stale_block_text_cannot_certify_a_patch():
    """A block resolved against an older draft names nothing in this one."""
    section = _section("The current wording is different.")
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        text="The wording the reviewer saw.",
    )
    assert report.blocking_issues([issue], section) == [issue]


def test_a14_removing_a_block_that_empties_a_table_still_takes_the_section():
    """U0 recheck (c): resolving an id does not make removal safe."""
    section = _section("| vendor | share |\n| --- | --- |\n| HOYA | 60% |")
    blocks = report.blocks_of(section)
    only_row = blocks[-1]
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        text=only_row.text,
    )
    # A header and a rule over nothing is not a table.
    assert report.blocking_issues([issue], section) == [issue]


def test_the_reviewer_is_shown_the_block_ids_it_must_name():
    section = _section("One.\n\nTwo.")
    labelled = roles.render_sections([section], labelled=True)
    assert "<economics:b1> One." in labelled
    assert "<economics:b2> Two." in labelled
    plain = roles.render_sections([section])
    assert "<economics:b1>" not in plain and "One." in plain


def test_a16_the_reader_gets_the_gap_not_the_bookkeeping():
    """D-U13: run 7 published `[material] unsupported on economics: ...`."""
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        description=(
            "[economics] 'the margin ceiling is set upstream' is an "
            "analytical inference stated as fact with no claim citation. "
            "(claim C3)"
        ),
    )
    line = report.reader_limitation(issue, zh=False)
    assert line.startswith("Stated without support, and withheld:")
    # No internal ids, no severity, no category name, no section tag.
    for machinery in ("[economics]", "C3", "material", "unsupported"):
        assert machinery not in line
    assert "the margin ceiling is set upstream" in line
    assert report.reader_limitation(issue, zh=True).startswith("缺乏支撑")


def test_a16_history_stays_in_the_audit_record(tmp_path):
    """Resolved issues belong to the auditor, not the reader."""
    resolved = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="economics",
        requested_action="remove",
        description="an earlier draft said something wrong",
        status="resolved",
        resolution="rewritten",
    )
    open_issue = resolved.model_copy(
        update={
            "id": "I2",
            "key": "k2",
            "status": "open",
            "category": "missing_evidence",
            "description": "the 2024 filing was not retrieved",
            "resolution": None,
        }
    )
    finding = records.Finding(
        id="F1",
        conclusion="c",
        claim_ids=[],
        mechanism="m",
        implication="i",
        counterargument="c",
        uncertainty="u",
        monitor="mo",
        inference_review="scope_change",
        inference_reason="the conclusion widens the period",
    )
    rows = [
        records.Coverage(question=q, status="partial", note="n")
        for q in sorted(records.REQUIRED_QUESTIONS)
    ]
    state = {
        "brief": records.Brief(industry="x", language="en"),
        "issues": {"I1": resolved, "I2": open_issue},
        "findings": {"F1": finding},
        "claims": {},
        "meta": None,
        "route_log": ["deliver: done"],
    }
    lines = report.appendices(state, rows)
    body = "\n".join(lines)
    # The reader sees the live gap and not the resolved history.
    assert "the 2024 filing was not retrieved" in body
    assert "an earlier draft said something wrong" not in body

    delivery = records.DeliveryResult(
        level="partial", status="incomplete", reason="r", floor="f"
    )
    record = report.audit_record(state, rows, delivery)
    assert record["resolved"] == 1 and record["unresolved"] == 1
    ids = {issue["id"] for issue in record["issues"]}
    assert ids == {"I1", "I2"}
    assert record["inference_audit"][0]["verdict"] == "scope_change"
    path = report.write_audit("t1", record, str(tmp_path))
    assert pathlib.Path(path).name == "t1.audit.json"
    written = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    assert written["resolved"] == 1


def test_u2_03_removal_never_corrupts_a_paragraph_that_quotes_its_premise():
    """Sequential replacement delivered "Therefore: [REMOVED] ..." (U2-03)."""
    premise = "This market has no competing suppliers."
    text = (
        f"{premise}\n\n"
        f"Therefore: {premise} Prices are dictated.\n\n"
        "**Accordingly** margins expand."
    )
    section = records.Section(id="intro", title="I", text=text)
    blocks = report.blocks_of(section)
    # Emphasis and ordinary consequence phrasing are both recognised.
    assert blocks[1].depends_on == blocks[0].id
    assert blocks[2].depends_on == blocks[1].id
    # b2 quotes the premise, so it repeats the same assertion and goes
    # whole rather than being redacted in place; b3 falls behind it.
    assert [b.id for b in report.dependents_of(section, blocks[0].id)] == [
        blocks[1].id,
        blocks[2].id,
    ]
    assert report.carries(blocks[1].text, premise)
    issues = [
        records.Issue(
            id=f"I{n}",
            key=f"k{n}",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="remove",
            text=unit,
        )
        for n, unit in enumerate([premise, blocks[1].text], start=1)
    ]
    out = report.redact(text, issues, "intro", "[REMOVED]")
    # The dependent goes whole; no half-removed sentence survives.
    assert "Prices are dictated" not in out
    assert "competing suppliers" not in out
    assert "margins expand" in out


def test_u2_03_ordinary_consequence_phrasings_are_recognised():
    for opener in (
        "Accordingly",
        "For this reason",
        "**Therefore**",
        "> Consequently",
        "因此",
        "据此",
    ):
        section = records.Section(
            id="s", title="T", text=f"A premise.\n\n{opener}, B follows."
        )
        blocks = report.blocks_of(section)
        assert blocks[1].depends_on == blocks[0].id, opener
    # And an unrelated paragraph does not depend on the one before it.
    plain = records.Section(
        id="s", title="T", text="A premise.\n\nSeparately, C is true."
    )
    assert report.blocks_of(plain)[1].depends_on is None


def test_u2_03_a_premise_written_twice_takes_its_consequence():
    """Expansion started from one block id and reached only that one's
    consequences, leaving the conclusion after both premises had gone."""
    premise = "This market has no competing suppliers."
    section = records.Section(
        id="s",
        title="T",
        text=(
            f"{premise}\n\nAn unrelated paragraph.\n\n{premise}\n\n"
            "Therefore suppliers can dictate prices."
        ),
    )
    falling = report.dependents_of_text(section, premise)
    assert [b.text for b in falling] == [
        "Therefore suppliers can dictate prices."
    ]
    issues = [
        records.Issue(
            id=f"I{n}",
            key=f"k{n}",
            category="unsupported",
            severity="material",
            target="s",
            requested_action="remove",
            text=text,
        )
        for n, text in enumerate([premise] + [b.text for b in falling], start=1)
    ]
    out = report.redact(section.text, issues, "s", "[X]")
    assert "competing suppliers" not in out
    assert "dictate prices" not in out
    assert "An unrelated paragraph." in out


def test_u2_03_a_dependent_that_quotes_its_premise_goes_whole():
    """Redacting in place left "Therefore: [X] Prices are dictated."
    standing -- an unsupported consequence with a hole in it (U2-03)."""
    premise = "This market has no competing suppliers."
    section = records.Section(
        id="s",
        title="T",
        text=(
            f"{premise}\n\nTherefore: {premise} Prices are dictated."
            "\n\nAccordingly margins expand."
        ),
    )
    falling = report.dependents_of_text(section, premise)
    assert [b.text[:20] for b in falling] == [
        "Therefore: This mark",
        "Accordingly margins ",
    ]
    issues = [
        records.Issue(
            id=f"I{n}",
            key=f"k{n}",
            category="unsupported",
            severity="material",
            target="s",
            requested_action="remove",
            text=text,
        )
        for n, text in enumerate([premise] + [b.text for b in falling], 1)
    ]
    out = report.redact(section.text, issues, "s", "[X]")
    assert "Prices are dictated" not in out
    assert "margins expand" not in out


def test_u2_03_a_sentence_inside_a_paragraph_is_still_redacted_in_place():
    """The case whole-block removal could have broken: an objected unit
    that is a sentence, never a whole block, is removed where it sits."""
    section = records.Section(
        id="s",
        title="T",
        text="A good sentence. A bad sentence. More context.\n\nTherefore X.",
    )
    # It is not a whole block anywhere, so nothing is dragged with it.
    assert report.dependents_of_text(section, "A bad sentence.") == []
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="s",
        requested_action="remove",
        text="A bad sentence.",
    )
    out = report.redact(section.text, [issue], "s", "[X]")
    assert "A good sentence. [X] More context." in out
    assert "Therefore X." in out
