"""The delivered report: removability, redaction, and delivery status.

Headline live run 4 (thread `b9632d7d`, 2026-09-08) delivered a report
whose limitations listed issues that no redaction had applied, and a
table a redaction had broken. These cover the removability contract of
plan revision 33 §4.39.8: an issue counts as removed only when its exact
unit is actually gone, and a table survives a row removal or the removal
fails closed.
"""

from industry import coverage as coverage_module
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


def _useful_state(body: str) -> dict:
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


def _rows(overrides: dict | None = None) -> list[records.Coverage]:
    """Eight coverage rows, ``covered`` unless overridden."""
    overrides = overrides or {}
    return [
        records.Coverage(question=q, status=overrides.get(q, "covered"))
        for q in sorted(records.REQUIRED_QUESTIONS)
    ]


def _certify(state: dict, consistent: bool = True, retainable=None) -> dict:
    """Give the state a certificate over its current body."""
    subject = report.review_subject(state, state.get("coverage") or [])
    state["review_subject"] = subject
    state["final_review"] = records.DraftReview(
        consistent=consistent, retainable=list(retainable or [])
    )
    state["final_review_version"] = state["draft_version"]
    return state


def _classify(state: dict, rows: list[records.Coverage] | None = None):
    plan = report.plan_delivery(state, "[removed]")
    if rows is None:
        rows = coverage_module.derive(state, None)
    return plan, coverage_module.classify_delivery(state, rows, plan)


def test_a_verified_unchanged_body_is_level_a():
    state = _certify(_useful_state(BODY))
    plan, result = _classify(state, _rows())
    assert plan.certified and not plan.changed
    assert result.level == "verified"
    assert result.status == "complete"


def test_a_verified_body_with_disclosed_limitations_is_level_a():
    # A minor, disclosed issue is a limitation, not a redaction: the
    # body is untouched, so the certificate still covers it.
    state = _certify(_useful_state(BODY))
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
    _, result = _classify(state, _rows({6: "partial"}))
    assert result.level == "verified"
    assert result.status == "complete_with_limitations"


def test_skipped_final_verification_is_never_level_a():
    state = _useful_state(BODY)  # no certificate at all
    plan, result = _classify(state)
    assert not plan.certified
    assert result.level != "verified"
    assert result.status == "incomplete"
    assert "no final review" in result.reason


def test_an_unverified_but_useful_body_is_level_b():
    # The latest draft has no review, but every unit repeats a claim
    # statement the verifier approved for standalone use, so the exact
    # wording is supported and the body is still worth delivering.
    state = _useful_state(BODY)
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
    state = _useful_state(BODY + "该公司2025年已实现量产并增长99%[C1]。")
    state["claims"] = {
        cid: claim.model_copy(update={"standalone": True})
        for cid, claim in state["claims"].items()
    }
    plan, _ = _classify(state)
    assert plan.sections
    assert "量产" not in plan.sections[0].text


def test_a_substantive_redaction_without_re_review_is_level_b_at_best():
    state = _certify(_useful_state(BODY + "未获支持的一句。"))
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
    state = _certify(_useful_state("孤立的一句[C1]。"))
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
    state = _certify(_useful_state(table))
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
    state = _certify(_useful_state(BODY))
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
    state = _certify(_useful_state(BODY))
    assert report.certificate_applies(state)
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "qualified", "review_reason": "仅限商用市场"}
    )
    assert not report.certificate_applies(state)


def test_the_delivered_report_states_the_level_above_the_body():
    state = _useful_state(BODY)
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
    state = _certify(_useful_state("孤立的一句[C1]。"))
    plan, result = _classify(state)
    derived = coverage_module.derive(state, None)
    text = report.render(state, derived, result.status, result, plan)
    assert "孤立的一句" not in text
    assert "仅提供诊断信息" in text


def test_delivery_renders_the_reviewed_appendix_not_a_fresh_one():
    state = _useful_state(BODY)
    state["coverage"] = [records.Coverage(question=4, status="partial")]
    state = _certify(state)
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
