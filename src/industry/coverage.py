"""Evidence-linked coverage of the required questions, and report status.

Only reviewed claims count (``supported`` or ``qualified``); map items
count through their map claims; findings count only while ``current``
and only when every claim they cite is reviewed. For the central
questions, ``covered`` further requires *context-backed* claims: a
``supported`` claim with at least one ``passage`` or ``table`` evidence
item whose source version exists in the registry and belongs to the
evidence's source, so a search snippet or an unverifiable passage never
completes a central requirement. Topics count only when the verifier
confirmed them (``reviewed_topics``), so tagging alone covers nothing.
The Lead proposes a status; Python derives the maximum permissible one
and stores both. Exhaustion of any limit changes nothing here, and a
missing question fails closed.
"""

import dataclasses

from industry import merge
from industry import records
from industry import report
from industry import state as state_module

_ORDER = {"uncovered": 0, "partial": 1, "covered": 2}
_STAGES = ("upstream", "midstream", "downstream")
_CHINA_MARKERS = ("中国", "china", "chinese", "大陆", "prc", "国内", "a股")


@dataclasses.dataclass
class _View:
    """The reviewed subset of the registry, indexed for the checks."""

    claims: dict[str, records.Claim]
    evidence: dict[str, records.Evidence]
    versions: dict[str, records.SourceVersion]
    findings: list[records.Finding]
    relationships: dict[str, records.Relationship]
    industry_map: records.IndustryMap
    issues: list[records.Issue]
    calculations: dict[str, records.Calculation] = dataclasses.field(
        default_factory=dict
    )

    def reviewed(self, claim: records.Claim) -> bool:
        """Whether the claim counts at all (``merge.citable``)."""
        return merge.citable(claim, self.claims, self.calculations)

    def context_backed(self, claim: records.Claim) -> bool:
        """Supported, with original context whose version is verifiable."""
        if claim.review != "supported":
            return False
        for eid in claim.evidence_ids:
            item = self.evidence.get(eid)
            if item is None or item.kind not in ("passage", "table"):
                continue
            version = self.versions.get(item.source_version_id or "")
            if version is not None and version.source_id == item.source_id:
                return True
        return False

    def cited_by_finding(self, claim_id: str) -> list[str]:
        """Ids of current, fully reviewed findings citing the claim."""
        return [
            finding.id
            for finding in self.findings
            if claim_id in finding.claim_ids and self.finding_ok(finding)
        ]

    def finding_ok(self, finding: records.Finding) -> bool:
        """Current and every cited claim reviewed."""
        return finding.status == "current" and all(
            cid in self.claims and self.reviewed(self.claims[cid])
            for cid in finding.claim_ids
        )

    def map_claims(self, prefix: str) -> list[records.Claim]:
        """Reviewed map claims whose ``map_ref`` starts with ``prefix``."""
        return [
            claim
            for claim in self.claims.values()
            if claim.map_ref
            and claim.map_ref.startswith(prefix)
            and self.reviewed(claim)
        ]

    def topic_claims(self, topic: str) -> list[records.Claim]:
        """Reviewed claims whose verifier-confirmed topics include it.

        The legacy topic ``cost_differentiation`` counts toward
        ``cost_structure`` only, never toward ``differentiation``.
        """
        wanted = {topic}
        if topic == "cost_structure":
            wanted.add("cost_differentiation")
        return [
            claim
            for claim in self.claims.values()
            if wanted & set(claim.reviewed_topics) and self.reviewed(claim)
        ]

    def entity_region(self, entity: str | None) -> str | None:
        """``china`` or ``global`` from the map's participant region."""
        if not entity:
            return None
        wanted = entity.casefold()
        for participant in self.industry_map.participants:
            if participant.name.casefold() == wanted:
                # Only a reviewed participant claim may classify others
                # (``Claim.is_reviewed``: a qualification without a
                # reason on record does not classify anything).
                backing = self.claims.get(participant.claim_id)
                if backing is None or not backing.is_reviewed():
                    return None
                region = (participant.region or "").casefold()
                if not region:
                    return None
                return (
                    "china"
                    if any(marker in region for marker in _CHINA_MARKERS)
                    else "global"
                )
        return None


def _status(covered: bool, partial: bool) -> records.CoverageStatus:
    if covered:
        return "covered"
    return "partial" if partial else "uncovered"


def _segment_stage(view: _View) -> dict[str, str]:
    return {seg.id: seg.stage for seg in view.industry_map.segments}


def _q1(view: _View) -> tuple[records.CoverageStatus, list[str], str]:
    stage_of = _segment_stage(view)
    segments = view.map_claims("G")
    stages_reviewed = {stage_of.get(c.map_ref, "") for c in segments}
    stages_backed = {
        stage_of.get(c.map_ref, "") for c in segments if view.context_backed(c)
    }
    boundary = view.topic_claims("boundary")
    product = view.topic_claims("product")
    covered = (
        all(s in stages_backed for s in _STAGES)
        and any(view.context_backed(c) for c in boundary)
        and any(view.context_backed(c) for c in product)
    )
    partial = len(stages_reviewed & set(_STAGES)) >= 2 or (
        bool(product) and bool(stages_reviewed)
    )
    ids = [c.id for c in segments + boundary + product]
    return (
        _status(covered, partial),
        ids,
        "product definition + segments per stage + boundary",
    )


def _q2(view: _View) -> tuple[records.CoverageStatus, list[str], str]:
    stage_of = _segment_stage(view)
    link_stage = {
        link.id: (
            stage_of.get(link.from_segment),
            stage_of.get(link.to_segment),
        )
        for link in view.industry_map.links
    }
    links = view.map_claims("L")
    backed_pairs = {
        link_stage.get(c.map_ref) for c in links if view.context_backed(c)
    }
    needed = {("upstream", "midstream"), ("midstream", "downstream")}
    covered = needed <= backed_pairs
    partial = bool(links)
    return _status(covered, partial), [c.id for c in links], "links"


def _q3(
    view: _View,
) -> tuple[records.CoverageStatus, list[str], list[str], str]:
    stage_of = _segment_stage(view)
    seg_of = {p.id: p.segment_id for p in view.industry_map.participants}
    flows = {
        p.id: bool(p.supplies or p.buys) for p in view.industry_map.participants
    }
    participants = view.map_claims("P")
    per_stage_backed: dict[str, int] = {}
    per_stage_reviewed: dict[str, int] = {}
    for claim in participants:
        stage = stage_of.get(seg_of.get(claim.map_ref, ""), "")
        per_stage_reviewed[stage] = per_stage_reviewed.get(stage, 0) + 1
        # Only a participant whose claim says what it supplies or buys,
        # with original context behind it, completes the requirement.
        if view.context_backed(claim) and flows.get(claim.map_ref, False):
            per_stage_backed[stage] = per_stage_backed.get(stage, 0) + 1
    confirmed = [
        r.id
        for r in view.relationships.values()
        if merge.relationship_live(r, view.claims)
    ]
    unavailable = any(
        issue.category == "unavailable"
        and issue.status != "resolved"
        and "relationship" in issue.target
        for issue in view.issues
    )
    covered = (
        all(per_stage_backed.get(s, 0) >= 2 for s in _STAGES)
        and bool(confirmed)
        and not unavailable
    )
    stages_with_two = [s for s in _STAGES if per_stage_reviewed.get(s, 0) >= 2]
    partial = len(stages_with_two) >= 2
    note = "participants with supply/buy per stage + confirmed relationship"
    if unavailable:
        note += "; relationship evidence unavailable caps at partial"
    return (
        _status(covered, partial),
        [c.id for c in participants],
        confirmed,
        note,
    )


def _q4(view: _View) -> tuple[records.CoverageStatus, list[str], list[str]]:
    ids: list[str] = []
    finding_ids: list[str] = []
    covered_topics = 0
    reviewed_topics = 0
    covering_claims: set[str] = set()
    for topic in records.QUESTION_4_TOPICS:
        claims = view.topic_claims(topic)
        if claims:
            reviewed_topics += 1
            ids.extend(c.id for c in claims)
        backed = [
            c
            for c in claims
            if view.context_backed(c) and view.cited_by_finding(c.id)
        ]
        if backed:
            covered_topics += 1
            covering_claims.update(c.id for c in backed)
        for claim in claims:
            finding_ids.extend(view.cited_by_finding(claim.id))
    covered = covered_topics == len(records.QUESTION_4_TOPICS) and (
        len(covering_claims) >= 2
    )
    partial = reviewed_topics >= 2 and bool(finding_ids)
    return _status(covered, partial), ids, sorted(set(finding_ids))


def _q5(view: _View) -> tuple[records.CoverageStatus, list[str], list[str]]:
    barriers = view.topic_claims("barrier")
    milestones = [
        c
        for c in view.claims.values()
        if c.milestone
        and c.milestone_date
        and c.entity
        and c.kind in ("company_claim", "fact")
        and view.reviewed(c)
    ]
    finding_ids = sorted(
        {fid for c in barriers for fid in view.cited_by_finding(c.id)}
    )
    covered = any(
        view.context_backed(c) and view.cited_by_finding(c.id) for c in barriers
    ) and any(view.context_backed(c) for c in milestones)
    partial = bool(barriers)
    ids = [c.id for c in barriers] + [c.id for c in milestones]
    return _status(covered, partial), ids, finding_ids


def _q6(view: _View) -> tuple[records.CoverageStatus, list[str], list[str]]:
    claims = view.topic_claims("global_china")
    finding_ids = sorted(
        {fid for c in claims for fid in view.cited_by_finding(c.id)}
    )
    # Covered: one current finding cites a reviewed claim about a
    # Chinese participant and one about a non-Chinese participant.
    covered = False
    for finding in view.findings:
        if not view.finding_ok(finding):
            continue
        regions = {
            view.entity_region(view.claims[cid].entity)
            for cid in finding.claim_ids
            if cid in view.claims
            and "global_china" in view.claims[cid].reviewed_topics
        }
        if {"china", "global"} <= regions:
            covered = True
            break
    return _status(covered, bool(claims)), [c.id for c in claims], finding_ids


def _q7(view: _View) -> tuple[records.CoverageStatus, list[str], list[str]]:
    comparison = view.topic_claims("comparison")
    finding_ids = sorted(
        {fid for c in comparison for fid in view.cited_by_finding(c.id)}
    )
    # Covered: one current finding compares two entities on the same
    # dimension, each through its own reviewed comparison claim.
    covered = False
    for finding in view.findings:
        if not view.finding_ok(finding):
            continue
        by_dimension: dict[str, set[str]] = {}
        for cid in finding.claim_ids:
            claim = view.claims.get(cid)
            if (
                claim is None
                or "comparison" not in claim.reviewed_topics
                or not claim.entity
                or not claim.dimension
            ):
                continue
            key = " ".join(claim.dimension.split()).casefold()
            by_dimension.setdefault(key, set()).add(claim.entity.casefold())
        if any(len(entities) >= 2 for entities in by_dimension.values()):
            covered = True
            break
    entities_any = {
        c.entity for c in view.claims.values() if c.entity and view.reviewed(c)
    }
    partial = len(entities_any) >= 2
    return _status(covered, partial), [c.id for c in comparison], finding_ids


def _q8(view: _View) -> tuple[records.CoverageStatus, list[str]]:
    current = [f for f in view.findings if f.status == "current"]
    complete = [
        f
        for f in current
        if f.material
        and f.counterargument.strip()
        and f.monitor.strip()
        and view.finding_ok(f)
    ]
    return _status(bool(complete), bool(current)), [f.id for f in complete]


def _clamp(
    derived: records.CoverageStatus,
    lead: records.CoverageStatus | None,
) -> records.CoverageStatus:
    if lead is None:
        return derived
    return derived if _ORDER[derived] <= _ORDER[lead] else lead


def derive(
    state: state_module.IndustryState,
    proposal: records.LeadAssessment | None,
) -> list[records.Coverage]:
    """Derive the coverage of every required question.

    Args:
      state: The state after the latest merge, analysis, and review.
      proposal: The Lead's assessment, if one was made; its status per
        question is stored as ``lead_status`` and can only lower the
        derived status, never raise it.

    Returns:
      One ``Coverage`` per required question, in question order.
    """
    view = _View(
        claims=state.get("claims", {}),
        evidence=state.get("evidence", {}),
        versions=state.get("source_versions", {}),
        findings=list(state.get("findings", {}).values()),
        relationships=state.get("relationships", {}),
        industry_map=state.get("map", records.IndustryMap()),
        issues=list(state.get("issues", {}).values()),
        calculations=state.get("calculations", {}),
    )
    proposed = {
        item.question: item for item in (proposal.coverage if proposal else [])
    }
    results: list[records.Coverage] = []
    for number in sorted(records.REQUIRED_QUESTIONS):
        claim_ids: list[str] = []
        finding_ids: list[str] = []
        relationship_ids: list[str] = []
        note = ""
        if number == 1:
            status, claim_ids, note = _q1(view)
        elif number == 2:
            status, claim_ids, note = _q2(view)
        elif number == 3:
            status, claim_ids, relationship_ids, note = _q3(view)
        elif number == 4:
            status, claim_ids, finding_ids = _q4(view)
        elif number == 5:
            status, claim_ids, finding_ids = _q5(view)
        elif number == 6:
            status, claim_ids, finding_ids = _q6(view)
        elif number == 7:
            status, claim_ids, finding_ids = _q7(view)
        else:
            status, finding_ids = _q8(view)
        lead = proposed.get(number)
        lead_status = lead.status if lead else None
        if lead and lead.note:
            note = f"{note}; lead: {lead.note}" if note else lead.note
        results.append(
            records.Coverage(
                question=number,
                status=_clamp(status, lead_status),
                claim_ids=sorted(set(claim_ids)),
                finding_ids=sorted(set(finding_ids)),
                relationship_ids=sorted(set(relationship_ids)),
                note=note,
                lead_status=lead_status,
            )
        )
    return results


@dataclasses.dataclass(frozen=True)
class UsefulnessFloor:
    """The Level-B bar: one rule, in one place, tuned in one object.

    Plan revision 33 §4.39.3. The constants are a starting point, not a
    validated threshold; they are calibrated on fixtures before being
    fixed, which is why they live here rather than spread through the
    delivery code.
    """

    mandatory_questions: tuple[int, ...] = (1, 2)
    central_required: int = 3
    min_supported_claims: int = 6
    require_product: bool = True
    require_boundary: bool = True
    require_participant: bool = True


FLOOR = UsefulnessFloor()


def delivered_claims(
    state: state_module.IndustryState, sections: list[records.Section]
) -> dict[str, records.Claim]:
    """The supported claims the delivered body actually cites.

    Computed from what survives in the body, never from the registry: a
    finding nobody copied into the report teaches the reader nothing.
    """
    claims = state.get("claims", {})
    live = state.get("calculations", {})
    cited: set[str] = set()
    for section in sections:
        cited.update(report.cited_claims(section.text))
    return {
        cid: claims[cid]
        for cid in cited
        if cid in claims
        and claims[cid].review == "supported"
        and merge.citable(claims[cid], claims, live)
    }


def delivery_coverage(
    state: state_module.IndustryState, sections: list[records.Section]
) -> list[records.Coverage]:
    """Coverage of what the delivered body says, not of the registry."""
    kept = delivered_claims(state, sections)
    return derive({**state, "claims": kept}, state.get("assessment"))


def meets_floor(
    state: state_module.IndustryState,
    sections: list[records.Section],
    floor: UsefulnessFloor = FLOOR,
) -> tuple[bool, str]:
    """Whether the surviving body is still a useful research document.

    Args:
      state: The run state at delivery.
      sections: The body delivery would publish.
      floor: The tunable bar; defaults to ``FLOOR``.

    Returns:
      Whether the floor is met, and the reason either way.
    """
    if not sections:
        return False, "no substantive body survived"
    kept = delivered_claims(state, sections)
    rows = {c.question: c for c in delivery_coverage(state, sections)}
    missing = [
        q
        for q in floor.mandatory_questions
        if rows.get(q) is None or rows[q].status == "uncovered"
    ]
    if missing:
        names = ", ".join(f"Q{q}" for q in missing)
        return False, f"{names} uncovered"
    answered = [
        q
        for q in records.CENTRAL_QUESTIONS
        if rows.get(q) is not None and rows[q].status != "uncovered"
    ]
    if len(answered) < floor.central_required:
        return (
            False,
            f"{len(answered)} of {floor.central_required} central "
            "questions have surviving content",
        )
    if len(kept) < floor.min_supported_claims:
        return (
            False,
            f"{len(kept)} of {floor.min_supported_claims} supported "
            "claims survive in the body",
        )
    topics = {t for claim in kept.values() for t in claim.reviewed_topics}
    if floor.require_product and "product" not in topics:
        return False, "no surviving product definition"
    if floor.require_boundary and "boundary" not in topics:
        return False, "no surviving industry boundary"
    if floor.require_participant and not _participant_role(state, kept):
        return False, "no surviving participant supply/buy role"
    return (
        True,
        f"{len(kept)} supported claims, {len(answered)} central questions",
    )


def _participant_role(
    state: state_module.IndustryState, kept: dict[str, records.Claim]
) -> bool:
    """Whether a surviving claim names a participant's supply or buy."""
    industry_map = state.get("map")
    if industry_map is None:
        return False
    flows = {
        p.id: bool(p.supplies or p.buys) for p in industry_map.participants
    }
    return any(
        claim.map_ref and flows.get(claim.map_ref, False)
        for claim in kept.values()
    )


def classify_delivery(
    state: state_module.IndustryState,
    coverage: list[records.Coverage],
    plan: report.DeliveryPlan,
    floor: UsefulnessFloor = FLOOR,
) -> records.DeliveryResult:
    """Decide Level A, B or C for a finished run.

    A needs an applicable certificate over an unchanged body and a
    status better than ``incomplete``; a substantive change after the
    review forbids it however well the change went. B needs the body to
    clear the usefulness floor. C withholds the body.
    """
    kept = [s.id for s in plan.sections]
    if plan.certified and not plan.changed:
        status = report_status(coverage, state, verified=True)
        if status != "incomplete":
            return records.DeliveryResult(
                level="verified",
                status=status,
                reason="final review applies to the delivered body",
                sections=kept,
                removed=list(plan.removed),
            )
        reason = "verified, but the coverage is incomplete"
    elif state.get("final_review") is None:
        reason = "no final review was made of this draft"
    elif not plan.covered:
        reason = "the draft changed after its final review"
    elif not plan.consistent:
        reason = "the final review did not judge the draft consistent"
    else:
        reason = "the body changed after its final review"
    ok, detail = meets_floor(state, plan.sections, floor)
    if ok:
        return records.DeliveryResult(
            level="partial",
            status="incomplete",
            reason=reason,
            sections=kept,
            removed=list(plan.removed),
            floor=detail,
        )
    return records.DeliveryResult(
        level="diagnostic_only",
        status="incomplete",
        reason=reason,
        sections=[],
        removed=list(plan.removed) + kept,
        floor=detail,
    )


def report_status(
    coverage: list[records.Coverage],
    state: state_module.IndustryState,
    verified: bool = False,
) -> records.ReportStatus:
    """Decide ``complete``, ``complete_with_limitations``, or ``incomplete``.

    ``complete``: every question covered, no material issue unresolved
    (open, or retired at the follow-up limit: retirement never makes a
    report complete), and ``verified`` (a final review ran on the
    delivered draft); without verification the best status is
    ``complete_with_limitations``.
    ``complete_with_limitations``: every central question at least
    partial, no unresolved material issue targeting anything counted
    toward a central question, and no finding cited for a central
    question resting on an unsupported or contradicted claim.
    ``incomplete``: otherwise, including when the coverage does not
    hold exactly the eight required questions (fail closed).
    """
    by_question = {c.question: c for c in coverage}
    if sorted(by_question) != sorted(records.REQUIRED_QUESTIONS):
        return "incomplete"
    claims = state.get("claims", {})
    findings = state.get("findings", {})
    issues = [
        i
        for i in state.get("issues", {}).values()
        if i.status in records.UNRESOLVED_ISSUE_STATUSES
        and i.severity == "material"
    ]
    if all(c.status == "covered" for c in coverage) and not issues:
        return "complete" if verified else "complete_with_limitations"
    # An open unsupported/contradiction issue the renderer cannot
    # actually remove -- no exact unit, a unit no longer in the draft,
    # or a row whose removal would empty its table -- would leave the
    # text delivered as fact: fail closed. `report` is the one authority
    # on removability, so status and renderer cannot disagree.
    if report.unremovable_section_issues(state):
        return "incomplete"
    central_targets: set[str] = set()
    for number in records.CENTRAL_QUESTIONS:
        item = by_question[number]
        if item.status == "uncovered":
            return "incomplete"
        central_targets.update(item.claim_ids)
        central_targets.update(item.finding_ids)
        central_targets.update(item.relationship_ids)
        central_targets.add(f"Q{number}")
        for fid in item.finding_ids:
            finding = findings.get(fid)
            if finding and any(
                claims[cid].review in ("unsupported", "contradicted")
                for cid in finding.claim_ids
                if cid in claims
            ):
                return "incomplete"
    for issue in issues:
        if issue.target in central_targets:
            return "incomplete"
    return "complete_with_limitations"
