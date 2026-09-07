"""Deterministic registry mutations: merge, review, invalidation, issues.

``merge_results`` folds worker results into the registries in stable
order (task number, then attempt number), assigns canonical ids,
deduplicates sources by identity, versions by content, evidence by
location and text, and never folds the same attempt twice. Nothing
here calls a model.

The other functions are the remaining ways the registry changes:
``apply_review`` writes the verifier's verdicts, ``invalidate_claim``
versions a corrected claim and marks what cites it stale, and
``open_issue`` canonicalises issues so a repeated problem cannot reset
its attempt count.
"""

import hashlib
import re
from typing import Any

from industry import records
from industry import schedule
from industry import state as state_module

_LABEL = re.compile(r"^\[?([A-Za-z]+\d+)\]?$")
# Excerpts this short coincide by accident; syndication needs more.
_SYNDICATION_MIN_CHARS = 200


def next_id(prefix: str, existing: dict[str, Any]) -> str:
    """The next id with ``prefix`` after the highest one in ``existing``."""
    numbers = [
        schedule.task_number(key) for key in existing if key.startswith(prefix)
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"


def attempt_number(attempt_id: str) -> int:
    """The attempt number in ``T3.2``."""
    return int(attempt_id.rsplit(".", 1)[1]) if "." in attempt_id else 0


def normalize_text(text: str) -> str:
    """Collapse whitespace and casefold, for comparing excerpts."""
    return " ".join(text.split()).casefold()


def text_hash(text: str) -> str:
    """A short digest of the normalized text."""
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def _label(ref: str) -> str:
    match = _LABEL.match(ref.strip())
    return match.group(1) if match else ref.strip()


def quantity_in_excerpts(
    quantity: records.Quantity, excerpts: list[str]
) -> bool:
    """Whether the number as written occurs in any excerpt.

    Thousands separators and spaces are ignored on both sides so that
    ``52亿`` matches ``52 亿`` and ``1,546.1`` matches ``1546.1``.
    """

    def squash(text: str) -> str:
        return re.sub(r"[,\s，]", "", text)

    needle = squash(quantity.as_written)
    return bool(needle) and any(
        needle in squash(excerpt) for excerpt in excerpts
    )


class _Registry:
    """Working copies of the registries while one merge runs."""

    def __init__(self, state: state_module.IndustryState) -> None:
        self.sources = dict(state.get("sources", {}))
        self.versions = dict(state.get("source_versions", {}))
        self.evidence = dict(state.get("evidence", {}))
        self.claims = dict(state.get("claims", {}))
        self.relationships = dict(state.get("relationships", {}))
        self.industry_map = state.get("map", records.IndustryMap())
        self.log: list[str] = []

    def source_id(self, local: records.Source) -> str:
        """Find the canonical source for a local one, or register it."""
        for existing in self.sources.values():
            same_url = (
                local.canonical_url is not None
                and existing.canonical_url == local.canonical_url
            )
            same_path = local.path is not None and existing.path == local.path
            if same_url or same_path:
                if existing.title in (
                    existing.canonical_url,
                    existing.path,
                ) and local.title not in (local.canonical_url, local.path):
                    self.sources[existing.id] = existing.model_copy(
                        update={"title": local.title}
                    )
                return existing.id
        new_id = next_id("S", self.sources)
        self.sources[new_id] = local.model_copy(
            update={"id": new_id, "versions": []}
        )
        return new_id

    def version_id(self, local: records.SourceVersion, source_id: str) -> str:
        """Register a fetch under its canonical source; mark syndication."""
        if local.id not in self.versions:
            self.versions[local.id] = local.model_copy(
                update={"source_id": source_id}
            )
            for other in self.versions.values():
                if (
                    other.id != local.id
                    and other.content_hash == local.content_hash
                    and other.source_id != source_id
                ):
                    self._syndicate(source_id, other.source_id)
                    break
        source = self.sources[source_id]
        if local.id not in source.versions:
            self.sources[source_id] = source.model_copy(
                update={"versions": source.versions + [local.id]}
            )
        return local.id

    def _syndicate(self, later: str, earlier: str) -> None:
        source = self.sources[later]
        if source.syndicated_of is None and later != earlier:
            self.sources[later] = source.model_copy(
                update={"syndicated_of": earlier}
            )
            self.log.append(f"source {later} syndicates {earlier}")

    def evidence_id(
        self,
        local: records.Evidence,
        source_id: str,
        version_id: str | None,
    ) -> str:
        """Find identical evidence or register it under a new id."""
        digest = text_hash(local.excerpt)
        for existing in self.evidence.values():
            if (
                existing.source_id == source_id
                and existing.source_version_id == version_id
                and existing.locator == local.locator
                and text_hash(existing.excerpt) == digest
            ):
                return existing.id
        if local.kind in ("passage", "table") and (
            len(local.excerpt) >= _SYNDICATION_MIN_CHARS
        ):
            for existing in self.evidence.values():
                if (
                    existing.source_id != source_id
                    and text_hash(existing.excerpt) == digest
                ):
                    self._syndicate(source_id, existing.source_id)
                    break
        new_id = next_id("E", self.evidence)
        self.evidence[new_id] = local.model_copy(
            update={
                "id": new_id,
                "source_id": source_id,
                "source_version_id": version_id,
            }
        )
        return new_id

    def add_claim(self, claim: records.Claim) -> str:
        """Register a claim unless an identical one exists."""
        key = (
            normalize_text(claim.statement),
            tuple(sorted(claim.evidence_ids)),
        )
        for existing in self.claims.values():
            if (
                normalize_text(existing.statement),
                tuple(sorted(existing.evidence_ids)),
            ) == key:
                return existing.id
        new_id = next_id("C", self.claims)
        self.claims[new_id] = claim.model_copy(update={"id": new_id})
        return new_id

    def add_relationship(
        self,
        draft: records.RelationshipDraft,
        evidence_ids: list[str],
        claim_id: str,
    ) -> str:
        """Register a proposed relation, unconfirmed."""
        key = (
            normalize_text(draft.from_entity),
            normalize_text(draft.to_entity),
            draft.relation,
        )
        for existing in self.relationships.values():
            if (
                normalize_text(existing.from_entity),
                normalize_text(existing.to_entity),
                existing.relation,
            ) == key:
                return existing.id
        new_id = next_id("R", self.relationships)
        self.relationships[new_id] = records.Relationship(
            id=new_id,
            from_entity=draft.from_entity,
            to_entity=draft.to_entity,
            relation=draft.relation,
            confirmed=False,
            evidence_ids=evidence_ids,
            date=draft.date,
            claim_id=claim_id,
        )
        return new_id


def _map_refs(
    refs: list[str], local_to_canonical: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Translate local evidence labels; return (canonical, unknown)."""
    canonical: list[str] = []
    unknown: list[str] = []
    for ref in refs:
        label = _label(ref)
        if label in local_to_canonical:
            if local_to_canonical[label] not in canonical:
                canonical.append(local_to_canonical[label])
        else:
            unknown.append(ref)
    return canonical, unknown


def _fold_result(registry: _Registry, result: records.TaskResult) -> None:
    """Fold one successful result's sources, evidence, findings, map."""
    source_map: dict[str, str] = {}
    for local in result.sources:
        source_map[local.id] = registry.source_id(local)
    version_map: dict[str, str] = {}
    for local in result.source_versions:
        source_id = source_map.get(local.source_id)
        if source_id is None:
            registry.log.append(
                f"{result.attempt_id}: version {local.id} names unknown "
                f"source {local.source_id}; dropped"
            )
            continue
        version_map[local.id] = registry.version_id(local, source_id)
    evidence_map: dict[str, str] = {}
    for local in result.evidence:
        source_id = source_map.get(local.source_id)
        if source_id is None:
            registry.log.append(
                f"{result.attempt_id}: evidence {local.id} names unknown "
                f"source {local.source_id}; dropped"
            )
            continue
        version_id = (
            version_map.get(local.source_version_id)
            if local.source_version_id
            else None
        )
        evidence_map[local.id] = registry.evidence_id(
            local, source_id, version_id
        )
    for draft in result.findings:
        _fold_finding(registry, result.attempt_id, draft, evidence_map)
    if result.map is not None:
        _fold_map(registry, result.attempt_id, result.map, evidence_map)


def _fold_finding(
    registry: _Registry,
    attempt_id: str,
    draft: records.FindingDraft,
    evidence_map: dict[str, str],
) -> None:
    evidence_ids, unknown = _map_refs(draft.evidence_refs, evidence_map)
    if unknown or not evidence_ids:
        registry.log.append(
            f"{attempt_id}: finding dropped, evidence refs "
            f"{unknown or draft.evidence_refs} unknown: "
            f"{draft.statement[:60]}"
        )
        return
    limitations: list[str] = []
    quantity = draft.quantity
    if quantity is not None:
        excerpts = [registry.evidence[eid].excerpt for eid in evidence_ids]
        if not quantity_in_excerpts(quantity, excerpts):
            limitations.append("quantity_not_in_excerpt")
            quantity = None
    if draft.milestone and not draft.milestone_date:
        limitations.append("undated_milestone")
    claim_id = registry.add_claim(
        records.Claim(
            id="C0",
            statement=draft.statement,
            kind=draft.kind,
            evidence_ids=evidence_ids,
            material=draft.material,
            entity=draft.entity,
            period=draft.period,
            quantity=quantity,
            milestone=draft.milestone,
            milestone_date=draft.milestone_date,
            limitations=limitations,
            questions=draft.questions,
            topics=draft.topics,
            origin=attempt_id,
        )
    )
    for relation in draft.relationships:
        rel_evidence, rel_unknown = _map_refs(
            relation.evidence_refs, evidence_map
        )
        if rel_unknown:
            registry.log.append(
                f"{attempt_id}: relationship {relation.from_entity} -> "
                f"{relation.to_entity} dropped, refs {rel_unknown} unknown"
            )
            continue
        registry.add_relationship(
            relation, rel_evidence or evidence_ids, claim_id
        )


def _fold_map(
    registry: _Registry,
    attempt_id: str,
    draft: records.MapDraft,
    evidence_map: dict[str, str],
) -> None:
    current = registry.industry_map
    segments = list(current.segments)
    links = list(current.links)
    participants = list(current.participants)
    by_name = {normalize_text(s.name): s.id for s in segments}
    key_to_id: dict[str, str] = {}
    for item in draft.segments:
        evidence_ids, unknown = _map_refs(item.evidence_refs, evidence_map)
        if unknown or not evidence_ids:
            registry.log.append(
                f"{attempt_id}: map segment {item.name} dropped, refs "
                f"{unknown or item.evidence_refs} unknown"
            )
            continue
        name = normalize_text(item.name)
        if name in by_name:
            key_to_id[item.key] = by_name[name]
            continue
        seg_id = next_id("G", {s.id: s for s in segments})
        claim_id = registry.add_claim(
            records.Claim(
                id="C0",
                statement=(
                    f"[map segment] {item.name} ({item.stage}): "
                    f"{item.description}"
                ),
                kind="map",
                evidence_ids=evidence_ids,
                material=True,
                questions=[1],
                origin=attempt_id,
                map_ref=seg_id,
            )
        )
        segments.append(
            records.Segment(
                id=seg_id,
                name=item.name,
                stage=item.stage,
                description=item.description,
                claim_id=claim_id,
            )
        )
        by_name[name] = seg_id
        key_to_id[item.key] = seg_id
    seg_name = {s.id: s.name for s in segments}
    existing_links = {(l.from_segment, l.to_segment) for l in links}
    for item in draft.links:
        evidence_ids, unknown = _map_refs(item.evidence_refs, evidence_map)
        from_id = key_to_id.get(item.from_key)
        to_id = key_to_id.get(item.to_key)
        if unknown or not evidence_ids or from_id is None or to_id is None:
            registry.log.append(
                f"{attempt_id}: map link {item.from_key}->{item.to_key} "
                "dropped (unknown segment or evidence)"
            )
            continue
        if (from_id, to_id) in existing_links:
            continue
        link_id = next_id("L", {l.id: l for l in links})
        claim_id = registry.add_claim(
            records.Claim(
                id="C0",
                statement=(
                    f"[map link] {seg_name[from_id]} -> {seg_name[to_id]}: "
                    f"{item.what_flows}"
                ),
                kind="map",
                evidence_ids=evidence_ids,
                material=True,
                questions=[2],
                origin=attempt_id,
                map_ref=link_id,
            )
        )
        links.append(
            records.Link(
                id=link_id,
                from_segment=from_id,
                to_segment=to_id,
                what_flows=item.what_flows,
                claim_id=claim_id,
            )
        )
        existing_links.add((from_id, to_id))
    existing_participants = {
        (normalize_text(p.name), p.segment_id) for p in participants
    }
    for item in draft.participants:
        evidence_ids, unknown = _map_refs(item.evidence_refs, evidence_map)
        seg_id = key_to_id.get(item.segment_key)
        if unknown or not evidence_ids or seg_id is None:
            registry.log.append(
                f"{attempt_id}: map participant {item.name} dropped "
                "(unknown segment or evidence)"
            )
            continue
        if (normalize_text(item.name), seg_id) in existing_participants:
            continue
        part_id = next_id("P", {p.id: p for p in participants})
        region = f", {item.region}" if item.region else ""
        unstated = "no supply/buy stated"
        flows = "; ".join(
            part
            for part in (
                f"supplies {item.supplies}" if item.supplies else "",
                f"buys {item.buys}" if item.buys else "",
            )
            if part
        )
        claim_id = registry.add_claim(
            records.Claim(
                id="C0",
                statement=(
                    f"[map participant] {item.name} - {seg_name[seg_id]} "
                    f"({item.role}{region}): {flows or unstated}. "
                    f"{item.selection_rationale}"
                ),
                kind="map",
                evidence_ids=evidence_ids,
                material=True,
                entity=item.name,
                questions=[3],
                origin=attempt_id,
                map_ref=part_id,
            )
        )
        participants.append(
            records.Participant(
                id=part_id,
                name=item.name,
                segment_id=seg_id,
                role=item.role,
                supplies=item.supplies,
                buys=item.buys,
                listed=item.listed,
                region=item.region,
                selection_rationale=item.selection_rationale,
                claim_id=claim_id,
            )
        )
        existing_participants.add((normalize_text(item.name), seg_id))
    registry.industry_map = records.IndustryMap(
        segments=segments,
        links=links,
        participants=participants,
        boundary_note=draft.boundary_note or current.boundary_note,
        gaps=current.gaps + [g for g in draft.gaps if g not in current.gaps],
        version=current.version + 1,
    )


def merge_results(
    state: state_module.IndustryState,
    results: list[records.TaskResult],
    limits: records.Limits,
) -> dict[str, Any]:
    """Fold the not-yet-merged results into the registries.

    Args:
      state: The state after the workers' results were appended.
      results: ``state["task_results"]`` (or the subset to consider).
      limits: For the re-queue rule (``task_attempts``).

    Returns:
      The state update: ``tasks``, ``attempts``, ``merged``, the five
      registries, ``map``, and ``route_log`` lines describing drops,
      syndication, and re-queues. Attempts already in ``merged`` are
      ignored, so a re-run of the merge superstep is idempotent.
    """
    merged = list(state.get("merged", []))
    tasks = dict(state.get("tasks", {}))
    attempts = dict(state.get("attempts", {}))
    registry = _Registry(state)
    pending = [r for r in results if r.attempt_id not in merged]
    pending.sort(
        key=lambda r: (
            schedule.task_number(r.task_id),
            attempt_number(r.attempt_id),
        )
    )
    for result in pending:
        attempt = attempts.get(result.attempt_id)
        if attempt is None:
            registry.log.append(
                f"{result.attempt_id}: result for an unknown attempt ignored"
            )
            merged.append(result.attempt_id)
            continue
        observed = result.usage if result.status != "unknown" else None
        attempts[attempt.id] = attempt.model_copy(
            update={
                "status": result.status,
                "observed": observed,
                "duration_s": (
                    result.usage.duration_s if observed is not None else None
                ),
            }
        )
        task = tasks[result.task_id]
        if result.status == "done":
            status: records.TaskStatus = "done"
            _fold_result(registry, result)
        elif (
            not (result.error or "").startswith("schema")
            and task.attempts < limits.task_attempts
        ):
            status = "pending"
            reason = result.error or "no usage observed"
            registry.log.append(
                f"{result.attempt_id}: {result.status} ({reason}); "
                f"{task.id} re-queued"
            )
        else:
            status = "failed"
            reason = result.error or "no usage observed"
            registry.log.append(
                f"{result.attempt_id}: {result.status} ({reason}); "
                f"{task.id} failed"
            )
        tasks[task.id] = task.model_copy(update={"status": status})
        merged.append(result.attempt_id)
    return {
        "tasks": tasks,
        "attempts": attempts,
        "merged": merged,
        "sources": registry.sources,
        "source_versions": registry.versions,
        "evidence": registry.evidence,
        "claims": registry.claims,
        "relationships": registry.relationships,
        "map": registry.industry_map,
        "route_log": registry.log,
    }


def apply_review(
    state: state_module.IndustryState, review: records.ClaimReview
) -> dict[str, Any]:
    """Write the verifier's verdicts into claims, relationships, sources.

    A relationship becomes ``confirmed`` only through a supporting
    relationship verdict; a ``generic_dependency`` never does.
    """
    claims = dict(state.get("claims", {}))
    relationships = dict(state.get("relationships", {}))
    sources = dict(state.get("sources", {}))
    log: list[str] = []
    for verdict in review.claims:
        claim = claims.get(verdict.claim_id)
        if claim is None:
            log.append(f"review names unknown claim {verdict.claim_id}")
            continue
        claims[claim.id] = claim.model_copy(update={"review": verdict.verdict})
    for verdict in review.relationships:
        relation = relationships.get(verdict.relationship_id)
        if relation is None:
            log.append(
                f"review names unknown relationship {verdict.relationship_id}"
            )
            continue
        confirmed = (
            verdict.supported and relation.relation != "generic_dependency"
        )
        relationships[relation.id] = relation.model_copy(
            update={
                "confirmed": confirmed,
                "review": "supported" if verdict.supported else "unsupported",
            }
        )
    for judgement in review.sources:
        source = sources.get(judgement.source_id)
        if source is None:
            log.append(f"review names unknown source {judgement.source_id}")
            continue
        sources[source.id] = source.model_copy(
            update={"origin": judgement.origin}
        )
    return {
        "claims": claims,
        "relationships": relationships,
        "sources": sources,
        "route_log": log,
    }


def invalidate_claim(
    state: state_module.IndustryState, claim_id: str, **changes: Any
) -> dict[str, Any]:
    """Version a corrected claim and mark what cites it stale.

    Args:
      state: The current state.
      claim_id: The claim to correct.
      **changes: New field values (``statement``, ``evidence_ids``,
        ``quantity``, ``milestone``, ...).

    Returns:
      Updated ``claims``, ``findings``, and ``sections``: the claim's
      version is incremented, ``supersedes`` names the previous
      version, ``review`` is reset, and every current finding or
      section citing the claim is marked stale.
    """
    claims = dict(state.get("claims", {}))
    claim = claims[claim_id]
    claims[claim_id] = claim.model_copy(
        update={
            **changes,
            "version": claim.version + 1,
            "supersedes": f"{claim_id}@{claim.version}",
            "review": "unreviewed",
        }
    )
    findings = {
        fid: (
            finding.model_copy(update={"status": "stale"})
            if claim_id in finding.claim_ids
            else finding
        )
        for fid, finding in state.get("findings", {}).items()
    }
    sections = [
        (
            section.model_copy(update={"stale": True})
            if claim_id in section.claim_ids
            else section
        )
        for section in state.get("sections", [])
    ]
    return {"claims": claims, "findings": findings, "sections": sections}


def issue_key(category: str, target: str) -> str:
    """The canonical key of an issue: one per category and target."""
    return f"{category}:{target}"


def open_issue(
    issues: dict[str, records.Issue],
    category: records.IssueCategory,
    severity: records.Severity,
    target: str,
    requested_action: records.RequestedAction,
    description: str,
    next_step: str | None = None,
) -> tuple[dict[str, records.Issue], records.Issue]:
    """Return the open issue with this key, or add a new one.

    An existing issue keeps its attempt count; only the description
    and next step are refreshed, so repeats never reset the limit.
    """
    key = issue_key(category, target)
    updated = dict(issues)
    for issue in issues.values():
        if issue.key == key and issue.status == "open":
            refreshed = issue.model_copy(
                update={"description": description, "next_step": next_step}
            )
            updated[issue.id] = refreshed
            return updated, refreshed
    new_id = next_id("I", issues)
    issue = records.Issue(
        id=new_id,
        key=key,
        category=category,
        severity=severity,
        target=target,
        description=description,
        requested_action=requested_action,
        next_step=next_step,
    )
    updated[new_id] = issue
    return updated, issue
