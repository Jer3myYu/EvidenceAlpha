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

from industry import records
from industry import state as state_module

REPORTS_DIR = "data/reports"
_CITATION = re.compile(r"\[(C\d+)(?:\s*,\s*(C\d+))*\]")
_CITATION_IDS = re.compile(r"C\d+")
_SENTENCE = re.compile(r"[^。！？.!?\n]+[。！？.!?]?")
_DIGITS = re.compile(r"\d")
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


def check_citations(
    sections: list[records.Section],
    claims: dict[str, records.Claim],
    entities: list[str] | None = None,
) -> list[CitationProblem]:
    """Find unknown, unreviewed, disallowed, and missing citations.

    A citation must name a claim reviewed ``supported`` or
    ``qualified``; an uncited sentence that states a number or names a
    known entity (a claim entity or a map participant) is flagged.
    """
    problems: list[CitationProblem] = []
    names = [e for e in (entities or []) if len(e) >= 2]
    for section in sections:
        for cid in cited_claims(section.text):
            claim = claims.get(cid)
            if claim is None:
                problems.append(
                    CitationProblem(section.id, f"cites unknown claim {cid}")
                )
            elif claim.review not in ("supported", "qualified"):
                problems.append(
                    CitationProblem(
                        section.id,
                        f"cites {cid}, reviewed {claim.review}, as fact",
                    )
                )
        for sentence in _SENTENCE.findall(section.text):
            stripped = sentence.strip()
            if (
                not stripped
                or _CITATION.search(stripped)
                or stripped.startswith(("|", "#", "-", "*"))
            ):
                continue
            if _DIGITS.search(stripped):
                problems.append(
                    CitationProblem(
                        section.id,
                        "uncited sentence with a number: " f"{stripped[:80]}",
                    )
                )
            elif any(name in stripped for name in names):
                problems.append(
                    CitationProblem(
                        section.id,
                        "uncited sentence naming an entity: "
                        f"{stripped[:80]}",
                    )
                )
    return problems


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
    for section in state.get("sections", []):
        text = _CITATION.sub(
            lambda m: _cite(m, claims, evidence, order), section.text
        )
        parts += [f"## {section.title}", "", text, ""]
    open_issues = [
        i for i in state.get("issues", {}).values() if i.status == "open"
    ]
    unresolvable = [
        i
        for i in state.get("issues", {}).values()
        if i.status == "unresolvable"
    ]
    if open_issues or unresolvable:
        parts += ["## " + ("局限性" if zh else "Limitations"), ""]
        for issue in open_issues + unresolvable:
            parts.append(
                f"- [{issue.severity}] {issue.category} on {issue.target}: "
                f"{issue.description}"
                + (f" ({issue.resolution})" if issue.resolution else "")
            )
        parts.append("")
    parts += ["## " + ("问题覆盖" if zh else "Coverage"), ""]
    for item in coverage:
        parts.append(f"- Q{item.question}: {item.status}")
    parts.append("")
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
