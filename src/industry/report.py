"""The delivered report: citation check, Markdown rendering, atomic write.

The editor writes sections citing claims as ``[C#]``. The deterministic
check here finds unknown ids, claims cited as fact although reviewed
``unsupported`` or ``contradicted``, and sentences that state numbers
without any citation; each becomes an issue for the router, never a
silent edit. Rendering turns ``[C#]`` into source citations from the
claim's evidence, lists the sources with their version dates, and
appends the open issues as limitations and the status line.
"""

import dataclasses
import os
import pathlib
import re
import tempfile

from industry import merge
from industry import records
from industry import state as state_module

REPORTS_DIR = "data/reports"
_CITATION = re.compile(r"\[(C\d+)(?:\s*,\s*(C\d+))*\]")
_CITATION_IDS = re.compile(r"C\d+")
_TERMINATORS = "。！？!?."
_DIGITS = re.compile(r"\d")
_CLAIM_ID = re.compile(r"\bC\d+\b")
_STATUS_TEXT = {
    "complete": "complete",
    "complete_with_limitations": "complete with limitations",
    "incomplete": "incomplete",
}


def cited_claims(text: str) -> list[str]:
    """Every ``C#`` cited in the text, in first-seen order."""
    seen: list[str] = []
    for match in _CITATION.finditer(text):
        for cid in _CITATION_IDS.findall(match.group(0)):
            if cid not in seen:
                seen.append(cid)
    return seen


@dataclasses.dataclass(frozen=True)
class CitationProblem:
    """One deterministic finding about a section's citations."""

    section_id: str
    description: str
    # The offending factual unit, when the problem is about one.
    text: str | None = None


def redact(
    text: str, issues: list[records.Issue], section_id: str, note: str
) -> str:
    """Remove every factual unit an open material issue names.

    An unsupported or contradicted unit that the section still carries
    is replaced by ``note`` (and stays listed under limitations), so no
    open issue's text is ever delivered as fact.
    """
    for issue in issues:
        if (
            issue.status in records.UNRESOLVED_ISSUE_STATUSES
            and issue.target == section_id
            and issue.severity == "material"
            and issue.category in ("unsupported", "contradiction")
            and issue.text
            and issue.text in text
        ):
            text = text.replace(issue.text, note)
    return text


def unremovable_section_issues(
    state: state_module.IndustryState,
) -> list[records.Issue]:
    """Unresolved material section issues without a removable unit.

    A final-review issue names a section and a problem but not the exact
    unit; while one is open, or retired unanswered at the follow-up
    limit, the report cannot be delivered as complete with limitations,
    because the offending text would stay.
    """
    section_ids = {s.id for s in state.get("sections", [])}
    return [
        i
        for i in state.get("issues", {}).values()
        if i.status in records.UNRESOLVED_ISSUE_STATUSES
        and i.severity == "material"
        and i.category in ("unsupported", "contradiction")
        and i.target in section_ids
        and not i.text
    ]


def cited_ids(text: str) -> list[str]:
    """Every claim id mentioned in free text (``C12``, ``[C12]``)."""
    return sorted(set(_CLAIM_ID.findall(text)))


def check_citations(
    sections: list[records.Section],
    claims: dict[str, records.Claim],
    entities: list[str] | None = None,
    calculations: dict[str, records.Calculation] | None = None,
) -> list[CitationProblem]:
    """Find unknown, unreviewed, disallowed, and missing citations.

    A citation must name a claim that may be cited (``merge.citable``:
    reviewed supported or qualified, and, for a derived claim, still
    agreeing with the calculation behind it); an uncited sentence that
    states a number or names a known entity (a claim entity or a map
    participant) is flagged.
    """
    live = calculations or {}
    problems: list[CitationProblem] = []
    names = [e for e in (entities or []) if len(e) >= 2]
    for section in sections:
        for cid in cited_claims(section.text):
            claim = claims.get(cid)
            if claim is None:
                problems.append(
                    CitationProblem(section.id, f"cites unknown claim {cid}")
                )
            elif not merge.citable(claim, claims, live):
                if not claim.is_reviewed():
                    detail = (
                        "qualified without its qualification on record"
                        if claim.review == "qualified"
                        else f"reviewed {claim.review}"
                    )
                else:
                    detail = (
                        "whose calculation "
                        f"{claim.calculation_id} is not current"
                    )
                problems.append(
                    CitationProblem(
                        section.id, f"cites {cid}, {detail}, as fact"
                    )
                )
        for stripped in factual_units(section.text):
            if _CITATION.search(stripped):
                continue
            if _DIGITS.search(stripped):
                problems.append(
                    CitationProblem(
                        section.id,
                        "uncited sentence with a number: " f"{stripped[:80]}",
                        stripped,
                    )
                )
            elif any(name in stripped for name in names):
                problems.append(
                    CitationProblem(
                        section.id,
                        "uncited sentence naming an entity: "
                        f"{stripped[:80]}",
                        stripped,
                    )
                )
    return problems


_SEPARATOR_ROW = re.compile(r"^\|?\s*:?-{2,}")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def _ends_unit(text: str, index: int) -> bool:
    """Whether the character at ``index`` terminates a factual unit.

    Every terminator ends one, with a single exception: an ASCII period
    between two digits is a decimal point. Cutting there would split a
    figure and leave the fragments without the citation standing at the
    sentence's real end.
    """
    char = text[index]
    if char not in _TERMINATORS:
        return False
    if char != ".":
        return True
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return not (before.isdigit() and after.isdigit())


def _sentences(line: str) -> list[str]:
    """One line split into sentences, decimal figures kept whole."""
    units: list[str] = []
    start = 0
    for index in range(len(line)):
        if _ends_unit(line, index):
            units.append(line[start : index + 1])
            start = index + 1
    if start < len(line):
        units.append(line[start:])
    return units


def factual_units(text: str) -> list[str]:
    """The units a citation check judges: sentences, table rows, items.

    A Markdown table row (other than the header row and its separator)
    is one unit, so a figure in a cell needs a citation in that row; a
    list item is a unit after its marker. Headings are skipped.
    """
    units: list[str] = []
    lines = text.split("\n")
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            if _SEPARATOR_ROW.match(line):
                continue
            following = (
                lines[index + 1].strip() if index + 1 < len(lines) else ""
            )
            if _SEPARATOR_ROW.match(following):
                continue  # the header row
            units.append(line)
            continue
        line = _LIST_MARK.sub("", line)
        units.extend(s.strip() for s in _sentences(line) if s.strip())
    return units


def known_entities(state: state_module.IndustryState) -> list[str]:
    """Entity names the citation check watches for in uncited sentences."""
    names: set[str] = set()
    for claim in state.get("claims", {}).values():
        if claim.entity:
            names.add(claim.entity)
    industry_map = state.get("map")
    if industry_map is not None:
        for participant in industry_map.participants:
            names.add(participant.name)
    return sorted(names)


def _source_index(
    state: state_module.IndustryState,
) -> tuple[dict[str, int], list[str]]:
    """Number the sources cited by any current section's claims."""
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    versions = state.get("source_versions", {})
    order: dict[str, int] = {}
    lines: list[str] = []
    for section in state.get("sections", []):
        for cid in cited_claims(section.text):
            claim = claims.get(cid)
            if claim is None:
                continue
            for eid in claim.evidence_ids:
                item = evidence.get(eid)
                if item is None or item.source_id in order:
                    continue
                source = sources.get(item.source_id)
                if source is None:
                    continue
                order[source.id] = len(order) + 1
                where = source.canonical_url or source.path or ""
                dates = sorted(
                    {
                        versions[v].retrieved_at[:10]
                        for v in source.versions
                        if v in versions
                    }
                )
                extra = []
                if source.publisher:
                    extra.append(source.publisher)
                if source.published:
                    extra.append(f"published {source.published}")
                if dates:
                    extra.append("retrieved " + ", ".join(dates))
                else:
                    extra.append("search result only, no snapshot")
                if source.origin != "unknown":
                    extra.append(source.origin)
                if source.syndicated_of:
                    extra.append(f"syndicates {source.syndicated_of}")
                details = "; ".join(extra)
                lines.append(
                    f"{order[source.id]}. {source.title} — {where} ({details})"
                )
    return order, lines


def _cite(match: re.Match, claims, evidence, order) -> str:
    numbers: list[int] = []
    for cid in _CITATION_IDS.findall(match.group(0)):
        claim = claims.get(cid)
        if claim is None:
            continue
        for eid in claim.evidence_ids:
            item = evidence.get(eid)
            if item and item.source_id in order:
                number = order[item.source_id]
                if number not in numbers:
                    numbers.append(number)
    if not numbers:
        return ""
    return "[" + ", ".join(str(n) for n in numbers) + "]"


def appendices(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
) -> list[str]:
    """The substantive blocks delivery appends after the sections.

    One definition of the draft being verified. The limitations (every
    unresolved issue) and the question coverage carry meaning the reader
    acts on, and a draft points at them by name, so the final verifier
    is given exactly these lines too -- it saw the sections alone until
    2026-09-08 and reported the limitations section missing from a
    report that has one. Delivery-only metadata stays out: the title,
    the status line and the numbered source list are mechanical, and the
    verifier reads ``[C#]`` claim ids rather than source numbers.

    Args:
      state: The run state; ``brief`` fixes the language, ``issues`` the
        limitations.
      coverage: The coverage rows delivery publishes.

    Returns:
      The Markdown lines, in delivery's order.
    """
    zh = state["brief"].language == "zh"
    unresolved = [
        i
        for i in state.get("issues", {}).values()
        if i.status in records.UNRESOLVED_ISSUE_STATUSES
    ]
    lines: list[str] = []
    if unresolved:
        lines += ["## " + ("局限性" if zh else "Limitations"), ""]
        for issue in unresolved:
            lines.append(
                f"- [{issue.severity}] {issue.category} on {issue.target}: "
                f"{issue.description}"
                + (f" ({issue.resolution})" if issue.resolution else "")
            )
        lines.append("")
    lines += ["## " + ("问题覆盖" if zh else "Coverage"), ""]
    for item in coverage:
        lines.append(f"- Q{item.question}: {item.status}")
    lines.append("")
    return lines


def render(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
    status: records.ReportStatus,
) -> str:
    """The Markdown report with source citations, limitations, status."""
    brief = state["brief"]
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})
    order, source_lines = _source_index(state)
    zh = brief.language == "zh"
    parts = [f"# {brief.industry}", ""]
    scope_line = (
        f"范围：{brief.geography}；模式：{brief.mode}；信息截止：{brief.cutoff}；"
        f"报告状态：{_STATUS_TEXT[status]}"
        if zh
        else f"Scope: {brief.geography}; mode: {brief.mode}; information "
        f"cutoff: {brief.cutoff}; report status: {_STATUS_TEXT[status]}"
    )
    parts += [scope_line, ""]
    unresolved = [
        i
        for i in state.get("issues", {}).values()
        if i.status in records.UNRESOLVED_ISSUE_STATUSES
    ]
    removed_note = (
        "[已移除未经核实的表述]" if zh else "[unverified statement removed]"
    )
    for section in state.get("sections", []):
        # Open and retired (unresolvable) issues both redact: retiring
        # an issue at the follow-up limit never makes its unit deliverable.
        text = redact(section.text, unresolved, section.id, removed_note)
        text = _CITATION.sub(lambda m: _cite(m, claims, evidence, order), text)
        parts += [f"## {section.title}", "", text, ""]
    parts += appendices(state, coverage)
    parts += ["## " + ("来源" if zh else "Sources"), ""]
    parts += source_lines or ["(none cited)"]
    parts.append("")
    return "\n".join(parts)


def write_report(
    thread_id: str, text: str, directory: str = REPORTS_DIR
) -> str:
    """Write the report atomically to ``<directory>/<thread_id>.md``."""
    path = pathlib.Path(directory) / f"{thread_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=".tmp-",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    )
    try:
        handle.write(text)
        handle.close()
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)
    return str(path)
