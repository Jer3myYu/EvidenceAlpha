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
import hashlib
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


_SEPARATOR_ROW = re.compile(r"^\|?\s*:?-{2,}")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def _is_row(unit: str) -> bool:
    """Whether a factual unit is a Markdown table row."""
    return unit.strip().startswith("|")


def _table_blocks(lines: list[str]) -> list[list[int]]:
    """The line indexes of each run of consecutive table lines."""
    blocks: list[list[int]] = []
    current: list[int] = []
    for index, line in enumerate(lines):
        if _is_row(line):
            current.append(index)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _data_rows(lines: list[str], block: list[int]) -> set[int]:
    """A block's data-row indexes: not its header, not its rule."""
    rows: set[int] = set()
    for position, index in enumerate(block):
        line = lines[index].strip()
        if _SEPARATOR_ROW.match(line):
            continue
        following = (
            lines[block[position + 1]].strip()
            if position + 1 < len(block)
            else ""
        )
        if _SEPARATOR_ROW.match(following):
            continue
        rows.add(index)
    return rows


@dataclasses.dataclass(frozen=True)
class Block:
    """One reviewable unit of a section: a paragraph, row, or list item.

    Derived from the section text, never stored beside it. A block is a
    projection, so it cannot drift from the words it names: re-deriving
    after an edit gives new ids and new hashes, and an issue whose block
    no longer resolves fails closed (plan D-U12).
    """

    id: str
    kind: str
    text: str
    sha256: str


def blocks_of(section: records.Section) -> list[Block]:
    """The reviewable units of one section, in order.

    A table row is its own unit -- one bad row should cost one row --
    and so is a list item. Everything else is a paragraph. Ids are
    positional within the section and stable for as long as the text is,
    which is exactly as long as a verdict about it is worth anything.
    """
    units: list[tuple[str, str]] = []
    for paragraph in section.text.split("\n\n"):
        lines = [line for line in paragraph.split("\n") if line.strip()]
        if not lines:
            continue
        if all(_is_row(line) for line in lines):
            units.extend(("row", line.strip()) for line in lines)
        elif all(_LIST_MARK.match(line.strip()) for line in lines):
            units.extend(("list_item", line.strip()) for line in lines)
        else:
            units.append(("paragraph", paragraph.strip()))
    return [
        Block(
            id=f"{section.id}:b{number}",
            kind=kind,
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        )
        for number, (kind, text) in enumerate(units, start=1)
    ]


def resolve_block(
    sections: list[records.Section], section_id: str, block_id: str | None
) -> Block | None:
    """The block an issue names, or None when it names nothing usable.

    None is not a soft failure. `blocking_issues` treats an issue with
    no removable text as blocking, which removes the whole section --
    the behaviour this delta inherited and deliberately kept as the
    floor. Naming a block correctly buys a smaller removal; naming one
    badly buys nothing worse than before (plan D-U12, U0-04).
    """
    if not block_id:
        return None
    for section in sections:
        if section.id != section_id:
            continue
        for block in blocks_of(section):
            if block.id == block_id:
                return block
    return None


def render_blocks(section: records.Section) -> str:
    """The section with every reviewable unit labelled, for the reviewer."""
    lines = [f"[{section.id}] {section.title}"]
    for block in blocks_of(section):
        lines.append(f"  <{block.id}> {block.text}")
    return "\n".join(lines)


def unremovable_units(text: str, units: list[str]) -> list[str]:
    """The units of ``units`` that ``text`` cannot safely give up.

    The one authority on removability, so the delivery status and the
    renderer can never disagree about what was removed. A prose unit
    must actually occur -- carrying a text field is not the same as
    still being in the draft, and an issue outliving the draft its text
    came from used to pass this check and redact nothing. A table row
    must occur as its own line and leave at least one data row behind:
    a header and a rule over nothing is not a table, so that removal
    fails closed instead.

    Args:
      text: The section text the units would be removed from.
      units: The exact factual units named by the issues.

    Returns:
      The units that cannot be removed, in first-seen order.
    """
    lines = text.split("\n")
    stripped = [line.strip() for line in lines]
    unremovable: list[str] = []
    matched: dict[str, set[int]] = {}
    for unit in units:
        if not unit:
            continue
        if not _is_row(unit):
            if unit not in text:
                unremovable.append(unit)
            continue
        found = {i for i, line in enumerate(stripped) if line == unit.strip()}
        if found:
            matched[unit] = found
        else:
            unremovable.append(unit)
    for block in _table_blocks(lines):
        data = _data_rows(lines, block)
        requested = {
            unit: hit
            for unit, found in matched.items()
            if (hit := data & found)
        }
        if not requested:
            continue
        going: set[int] = set().union(*requested.values())
        if not data - going:
            unremovable.extend(u for u in requested if u not in unremovable)
    return unremovable


def _drop_rows(text: str, rows: list[str], note: str) -> str:
    """Delete whole table rows, leaving the note outside the table."""
    wanted = {row.strip() for row in rows}
    kept: list[str] = []
    dropped = False
    for line in text.split("\n"):
        if _is_row(line):
            if line.strip() in wanted:
                dropped = True
                continue
        elif dropped:
            kept.append(note)
            dropped = False
        kept.append(line)
    if dropped:
        kept.append(note)
    return "\n".join(kept)


def removable_issue_units(
    issues: list[records.Issue], section_id: str
) -> list[str]:
    """The exact units the unresolved material issues of a section name."""
    return [
        issue.text
        for issue in issues
        if issue.status in records.UNRESOLVED_ISSUE_STATUSES
        and issue.target == section_id
        and issue.severity == "material"
        and issue.category in ("unsupported", "contradiction")
        and issue.text
    ]


def redact(
    text: str, issues: list[records.Issue], section_id: str, note: str
) -> str:
    """Remove every factual unit an open material issue names.

    An unsupported or contradicted unit the section still carries is
    replaced by ``note`` (and stays listed under limitations), so no
    open issue's text is ever delivered as fact. A table row is deleted
    whole and the note follows the table, because a note standing
    between a rule and the surviving rows destroys the table. A unit
    ``unremovable_units`` refuses is left alone; the delivery status
    fails closed on it instead of half-removing it.
    """
    units = removable_issue_units(issues, section_id)
    blocked = set(unremovable_units(text, units))
    rows = [u for u in units if _is_row(u) and u not in blocked]
    for unit in units:
        if not _is_row(unit) and unit not in blocked:
            text = text.replace(unit, note)
    if rows:
        text = _drop_rows(text, rows, note)
    return text


def blocking_issues(
    issues: list[records.Issue], section: records.Section
) -> list[records.Issue]:
    """The section's material issues that name nothing removable.

    The one authority behind both the delivery plan and the status, so
    they can never disagree about whether an issue's text would
    actually go (plan revision 37 §4.44.2). An issue blocks when it
    carries no text at all -- every model-authored final-review issue
    does, because ``records.SectionIssue`` has no text field -- or when
    its exact unit is no longer in the draft, or when removing it
    together with the section's other units would empty a table. A
    blocking issue removes the whole section: the text is never
    guessed, and the section is never silently kept.

    Args:
      issues: Every issue in the run.
      section: The section the delivery plan is judging.

    Returns:
      The blocking issues, in registry order.
    """
    named = [
        issue
        for issue in issues
        if issue.status in records.UNRESOLVED_ISSUE_STATUSES
        and issue.severity == "material"
        and issue.category in ("unsupported", "contradiction")
        and issue.target == section.id
    ]
    units = [issue.text for issue in named if issue.text]
    stuck = set(unremovable_units(section.text, units))
    return [issue for issue in named if not issue.text or issue.text in stuck]


def unremovable_section_issues(
    state: state_module.IndustryState,
) -> list[records.Issue]:
    """Unresolved material section issues without a removable unit.

    A final-review issue names a section and a problem but not the exact
    unit; while one is open, or retired unanswered at the follow-up
    limit, the report cannot be delivered as complete with limitations,
    because the offending text would stay. An issue whose exact unit is
    no longer in the draft, or whose removal would empty a table, is
    equally unremovable: carrying a text field never meant the text
    would actually go.
    """
    out: list[records.Issue] = []
    issues = list(state.get("issues", {}).values())
    for section in state.get("sections", []):
        out.extend(blocking_issues(issues, section))
    return out


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
    sections: list[records.Section] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """Number the sources cited by the delivered sections' claims."""
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    versions = state.get("source_versions", {})
    if sections is None:
        sections = state.get("sections", [])
    order: dict[str, int] = {}
    lines: list[str] = []
    for section in sections:
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


def deferred_review(
    state: state_module.IndustryState,
) -> list[records.Claim]:
    """Material claims the bounded review never reached.

    The one reader of ``review_disposition == "deferred"`` outside
    merge: coverage says how many obligations are unmet, delivery caps
    the status because of them, and the reader is told. A queue that
    filled is a limitation of the run, and the reader owns it.
    """
    return sorted(
        (
            claim
            for claim in state.get("claims", {}).values()
            if claim.material and claim.review_disposition == "deferred"
        ),
        key=lambda c: c.id,
    )


def deferred_note(state: state_module.IndustryState) -> str | None:
    """What to tell the reader about unreviewed material, if anything."""
    deferred = deferred_review(state)
    if not deferred:
        return None
    partitions = sorted({merge.material_partition(c) for c in deferred})
    named = ", ".join(partitions)
    return (
        f"{len(deferred)} material finding(s) were collected but not "
        "independently verified within this run's review budget "
        f"({named}); they are not cited in this report."
    )


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
    note = deferred_note(state)
    if note:
        # A material claim the review never reached is a limitation of
        # this run, and the reader owns it. Before D-U2 the claim was
        # written non-material and nobody was told (U1-01).
        if not unresolved:
            lines += ["## " + ("局限性" if zh else "Limitations"), ""]
        lines.append(f"- [material] unreviewed: {note}")
        lines.append("")
    omitted = map_omissions(state)
    if omitted:
        if not unresolved and not note:
            lines += ["## " + ("局限性" if zh else "Limitations"), ""]
        lines.append(f"- [minor] scope: {omitted}")
        lines.append("")
    lines += ["## " + ("问题覆盖" if zh else "Coverage"), ""]
    for item in coverage:
        lines.append(f"- Q{item.question}: {item.status}")
    lines.append("")
    return lines


def map_omissions(state: state_module.IndustryState) -> str | None:
    """What the bounded map view left out of the delivered report.

    The registry keeps every candidate segment, link and participant
    since D-U3, and the view bounds what any reader sees. A reader who
    is not told the view is bounded would read a partial chain as the
    whole industry (U1-14).
    """
    industry_map = state.get("map", records.IndustryMap())
    if not industry_map.segments:
        return None
    limits = _limits_of(state)
    _, beyond, _ = merge.map_view(industry_map, limits, state.get("claims"))
    if not beyond:
        return None
    detail = ", ".join(
        f"{count} {kind}" for kind, count in sorted(beyond.items())
    )
    return (
        f"the industry map holds further candidates this report does not "
        f"show ({detail}); they were recorded but not selected for the "
        "delivered view"
    )


def _limits_of(state: state_module.IndustryState) -> records.Limits:
    """The run's configured limits, or the defaults for an older thread."""
    meta = state.get("meta")
    return getattr(meta, "limits", None) or records.Limits()


_UNIT = "\x1f"


def _support_context(
    state: state_module.IndustryState, cited: list[str]
) -> list[str]:
    """The support a section rests on, as comparable strings.

    A requalified claim, a reworded restriction, a replaced statement or
    a recomputed calculation all change what the draft means, so each
    changes the digest and costs the section its approval.
    """
    claims = state.get("claims", {})
    out: list[str] = []
    for cid in sorted(set(cited)):
        claim = claims.get(cid)
        if claim is None:
            out.append(f"{cid}:absent")
            continue
        out.append(
            _UNIT.join(
                [
                    cid,
                    claim.statement,
                    claim.review,
                    claim.review_reason or "",
                    claim.calculation_id or "",
                    ",".join(claim.evidence_ids),
                    "standalone" if claim.standalone else "",
                ]
            )
        )
    return out


def section_digest(
    state: state_module.IndustryState, section: records.Section
) -> str:
    """The identity of one section: its exact text and its support."""
    parts = [section.id, section.title, section.text]
    parts += _support_context(state, cited_claims(section.text))
    return hashlib.sha256(_UNIT.join(parts).encode("utf-8")).hexdigest()


def review_subject(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
) -> records.ReviewSubject:
    """Freeze the exact document a final review is about to judge.

    Called before the review, so the appendix lines the verifier reads
    are the ones delivery renders: ``final_review`` reopens issues and
    re-derives coverage after the call, and delivery derives it again,
    which used to let the delivered limitations differ from the
    reviewed ones with no new draft.

    Args:
      state: The run state as the reviewer will see it.
      coverage: The coverage rows behind the appendix.

    Returns:
      The frozen subject, digested per section and as a whole.
    """
    sections = state.get("sections", [])
    appendix = appendices(state, coverage)
    digests = {s.id: section_digest(state, s) for s in sections}
    brief = state["brief"]
    parts = [
        brief.industry,
        brief.geography,
        brief.cutoff,
        brief.language,
        brief.mode,
    ]
    for section in sections:
        parts += [section.id, digests[section.id]]
    parts += appendix
    return records.ReviewSubject(
        digest=hashlib.sha256(_UNIT.join(parts).encode("utf-8")).hexdigest(),
        sections=digests,
        section_ids=[s.id for s in sections],
        appendix=appendix,
        draft_version=state.get("draft_version", 0),
    )


def certificate_applies(state: state_module.IndustryState) -> bool:
    """Whether the stored review still judges the current body.

    The frozen appendix is what delivery renders, so appendix drift does
    not invalidate the certificate; it is reported as a diagnostic. A
    changed section, a changed set of sections, or changed support does
    invalidate it.
    """
    subject = state.get("review_subject")
    review = state.get("final_review")
    if subject is None or review is None:
        return False
    sections = state.get("sections", [])
    if [s.id for s in sections] != subject.section_ids:
        return False
    return all(
        subject.sections.get(s.id) == section_digest(state, s) for s in sections
    )


def retainable_sections(state: state_module.IndustryState) -> set[str]:
    """Sections the review judged able to stand on their own, unchanged.

    A section the verifier did not name, or one whose text or support
    has changed since, is not retainable: its approval was for the words
    that were reviewed.
    """
    subject = state.get("review_subject")
    review = state.get("final_review")
    if subject is None or review is None:
        return set()
    named = set(review.retainable)
    return {
        section.id
        for section in state.get("sections", [])
        if section.id in named
        and subject.sections.get(section.id) == section_digest(state, section)
    }


def standalone_statements(state: state_module.IndustryState) -> list[str]:
    """Claim statements the verifier approved for verbatim delivery."""
    live = state.get("calculations", {})
    claims = state.get("claims", {})
    return [
        claim.statement
        for claim in claims.values()
        if claim.standalone
        and claim.review == "supported"
        and claim.kind in ("fact", "map")
        and merge.citable(claim, claims, live)
    ]


def appendix_drift(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
) -> list[str]:
    """Appendix lines that changed after the review, as diagnostics.

    The reviewed lines are delivered unchanged; what moved since is
    reported separately rather than silently rewritten into them.
    """
    subject = state.get("review_subject")
    if subject is None:
        return []
    now = appendices(state, coverage)
    if now == subject.appendix:
        return []
    frozen = set(subject.appendix)
    return [line for line in now if line.strip() and line not in frozen]


@dataclasses.dataclass(frozen=True)
class DeliveryPlan:
    """The body delivery would publish, and how it got there."""

    sections: list[records.Section]
    # The review read these exact words: every section is eligible for
    # retention, whatever verdict it reached about them.
    covered: bool
    # Eligible *and* passed: the Level-A condition, with ``changed``.
    certified: bool
    consistent: bool
    changed: bool
    removed: list[str]
    reasons: list[str]


def _strip_citations(text: str) -> str:
    return _CITATION.sub("", text).strip().strip("。.").strip()


def _standalone_units(
    section: records.Section, statements: set[str]
) -> list[str]:
    """Units of the section that are an approved statement verbatim.

    The exact-wording rule: a unit survives an unreviewed draft only by
    saying what an approved claim says. Citation markers are the one
    difference tolerated, because they are delivery's own notation.
    """
    kept: list[str] = []
    for unit in factual_units(section.text):
        if _strip_citations(unit) in statements:
            kept.append(unit)
    return kept


def _citations_resolve(state: state_module.IndustryState, text: str) -> bool:
    """Whether every claim cited by the text may still be cited."""
    claims = state.get("claims", {})
    live = state.get("calculations", {})
    for cid in cited_claims(text):
        claim = claims.get(cid)
        if claim is None or not merge.citable(claim, claims, live):
            return False
    return True


def plan_delivery(state: state_module.IndustryState, note: str) -> DeliveryPlan:
    """Decide the substantive body, unit by unit, before anything renders.

    The deterministic gate of plan revision 33 §4.39.4. A section is
    eligible when an applicable certificate covers the whole body, or
    when the review named that section retainable and it has not
    changed since. An ineligible section keeps only the units that
    repeat an approved claim statement verbatim. A required removal that
    cannot be applied safely -- no text at all, stale text, or a row
    that would empty its table -- escalates to removing the section,
    never to a partial edit (plan revision 37 §4.44.2). A surviving
    unit whose citations no longer resolve goes with its section.

    Args:
      state: The run state at delivery.
      note: The redaction marker for a removed unit.

    Returns:
      The plan: the sections to render, whether a certificate covers
      them, whether anything changed after the review, what was removed
      and why.
    """
    review = state.get("final_review")
    # A certificate bound to this body means the reviewer read these
    # exact words. That alone makes a section eligible: a review that
    # faulted one section did not withdraw the others, and removing a
    # whole report over one unresolved section is what this contract
    # exists to avoid.
    covered = certificate_applies(state)
    consistent = review is not None and review.consistent
    certified = covered and consistent
    issues = list(state.get("issues", {}).values())
    approved = retainable_sections(state)
    statements = {
        _strip_citations(text) for text in standalone_statements(state)
    }
    kept: list[records.Section] = []
    removed: list[str] = []
    reasons: list[str] = []
    changed = False
    for section in state.get("sections", []):
        if not (covered or section.id in approved):
            units = _standalone_units(section, statements)
            changed = True
            if units:
                kept.append(
                    section.model_copy(update={"text": "\n\n".join(units)})
                )
                reasons.append(
                    f"{section.id}: kept {len(units)} approved statement(s); "
                    "the rest was not reviewed"
                )
            else:
                removed.append(section.id)
                reasons.append(f"{section.id}: removed, no reviewed wording")
            continue
        blocked = blocking_issues(issues, section)
        if blocked:
            # A material issue that names no unit this section can give
            # up takes the section with it (plan revision 37 §4.44.2).
            # Every model-authored final-review issue is one of these,
            # so before this rule a known unsupported sentence stayed
            # in the body with nothing to remove it.
            removed.append(section.id)
            named = ", ".join(issue.id for issue in blocked)
            reasons.append(
                f"{section.id}: removed, a required removal could not be "
                f"applied safely ({named})"
            )
            changed = True
            continue
        text = redact(section.text, issues, section.id, note)
        if text != section.text:
            changed = True
            reasons.append(f"{section.id}: unsupported text removed")
        if not _citations_resolve(state, text):
            removed.append(section.id)
            reasons.append(
                f"{section.id}: removed, a citation no longer resolves"
            )
            changed = True
            continue
        kept.append(section.model_copy(update={"text": text}))
    return DeliveryPlan(
        kept, covered, certified, consistent, changed, removed, reasons
    )


def removal_note(state: state_module.IndustryState) -> str:
    """The marker delivery leaves where a unit was removed."""
    return (
        "[已移除未经核实的表述]"
        if state["brief"].language == "zh"
        else "[unverified statement removed]"
    )


def _label_lines(
    state: state_module.IndustryState, delivery: records.DeliveryResult
) -> list[str]:
    """The prominent statement of what this report is, before the body.

    A reader must not be able to mistake a partial, unverified report
    for a verified one, so the level, the verification condition and
    what is missing all stand above the first section.
    """
    if delivery.level == "verified":
        return []
    zh = state["brief"].language == "zh"
    if delivery.level == "partial":
        head = (
            "**不完整——部分研究报告，未经完整最终核验**"
            if zh
            else "**Incomplete - partial research report, not fully "
            "verified**"
        )
    else:
        head = (
            "**不完整——正文已保留未发布，仅提供诊断信息**"
            if zh
            else "**Incomplete - the substantive body was withheld; "
            "diagnostics only**"
        )
    lines = ["> " + head, ">", f"> {delivery.reason}."]
    if delivery.removed:
        removed = (
            "、".join(delivery.removed) if zh else ", ".join(delivery.removed)
        )
        label = "未纳入的部分" if zh else "Not included"
        lines.append(f"> {label}: {removed}.")
    if delivery.floor:
        lines.append(f"> {delivery.floor}.")
    lines.append(
        "> "
        + (
            "覆盖缺口与已移除内容见下文“局限性”与“问题覆盖”。"
            if zh
            else "Coverage gaps and removed content are listed under "
            "Limitations and Coverage below."
        )
    )
    return lines + [""]


def render(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
    status: records.ReportStatus,
    delivery: records.DeliveryResult | None = None,
    plan: DeliveryPlan | None = None,
) -> str:
    """The Markdown report with source citations, limitations, status.

    With a ``delivery`` result and its ``plan``, the body is the one the
    deterministic gate approved -- already redacted, already reduced to
    what may be published -- the level is stated above it, the appendix
    is the frozen one the reviewer read, and anything that moved since
    is reported separately instead of rewriting those lines.
    """
    brief = state["brief"]
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})
    sections = plan.sections if plan is not None else state.get("sections", [])
    if delivery is not None and delivery.level == "diagnostic_only":
        sections = []
    order, source_lines = _source_index(state, sections)
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
    if delivery is not None:
        parts += _label_lines(state, delivery)
    for section in sections:
        # Open and retired (unresolvable) issues both redact: retiring
        # an issue at the follow-up limit never makes its unit
        # deliverable. With a plan the gate has already applied them.
        text = section.text
        if plan is None:
            text = redact(
                section.text, unresolved, section.id, removal_note(state)
            )
        text = _CITATION.sub(lambda m: _cite(m, claims, evidence, order), text)
        parts += [f"## {section.title}", "", text, ""]
    subject = state.get("review_subject")
    if delivery is not None and subject is not None:
        parts += list(subject.appendix)
        drift = appendix_drift(state, coverage)
        if drift:
            parts += [
                "## " + ("核验后的变化" if zh else "Changes after review"),
                "",
            ]
            parts += drift
            parts.append("")
    else:
        parts += appendices(state, coverage)
    parts += repair_lines(state)
    parts += ["## " + ("来源" if zh else "Sources"), ""]
    parts += source_lines or ["(none cited)"]
    parts.append("")
    return "\n".join(parts)


def repair_lines(state: state_module.IndustryState) -> list[str]:
    """What the run asked to strengthen, and what became of it.

    Plan revision 39 §4.46.5: a deferred repair is a gap the reader is
    entitled to see, not an internal accounting detail. Nothing here
    asserts anything about the industry.
    """
    repairs = state.get("repairs", {})
    if not repairs:
        return []
    zh = state["brief"].language == "zh"
    done = [r for r in repairs.values() if r.status == "done"]
    waiting = [
        r for r in repairs.values() if r.status in ("deferred", "pending")
    ]
    dropped = [r for r in repairs.values() if r.status == "dropped"]
    lines = ["## " + ("证据补强" if zh else "Evidence repair"), ""]
    lines.append(
        (
            f"请求 {len(repairs)} 项；已补强 {len(done)} 项，"
            f"未能安排 {len(waiting)} 项，已放弃 {len(dropped)} 项。"
        )
        if zh
        else (
            f"{len(repairs)} requested; {len(done)} strengthened, "
            f"{len(waiting)} not scheduled, {len(dropped)} dropped."
        )
    )
    lines.append("")
    for request in sorted(waiting, key=lambda r: r.id)[:10]:
        lines.append(f"- {request.claim_id}: {request.objective[:110]}")
        if request.reason:
            lines.append(f"  - {request.reason}")
    if waiting:
        lines.append("")
    return lines


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
