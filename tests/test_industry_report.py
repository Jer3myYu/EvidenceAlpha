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
