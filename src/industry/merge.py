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

from industry import quantities
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


def _unique(items: list[str]) -> list[str]:
    """The items in order, each kept once."""
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _label(ref: str) -> str:
    match = _LABEL.match(ref.strip())
    return match.group(1) if match else ref.strip()


class _Registry:
    """Working copies of the registries while one merge runs."""

    def __init__(
        self,
        state: state_module.IndustryState,
        limits: records.Limits | None = None,
    ) -> None:
        self.limits = limits or records.Limits()
        self.sources = dict(state.get("sources", {}))
        self.versions = dict(state.get("source_versions", {}))
        self.evidence = dict(state.get("evidence", {}))
        self.claims = dict(state.get("claims", {}))
        self.relationships = dict(state.get("relationships", {}))
        self.industry_map = state.get("map", records.IndustryMap())
        self.log: list[str] = []
        # Claims whose meaning changed in this merge; their dependants
        # (findings, sections) are marked stale by merge_results.
        self.changed: set[str] = set()

    def material_quota(self, partition: str) -> bool:
        """Whether one more material claim fits ``partition``."""
        return admit_material(self.claims, self.limits, partition)

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
        """Register a claim, or fold a repeat into the existing one.

        A repeat (same statement, same evidence) adds its questions,
        topics, and materiality to the existing claim. When it brings
        a quantity, milestone, entity, period, or dimension the
        existing claim lacks, the claim's meaning changes: it gets a
        new version and its review is reset.
        """
        key = (
            normalize_text(claim.statement),
            tuple(sorted(claim.evidence_ids)),
        )
        for existing in self.claims.values():
            if (
                normalize_text(existing.statement),
                tuple(sorted(existing.evidence_ids)),
            ) != key:
                continue
            if existing.calculation_id is not None:
                # A derived claim states its calculation's result; a
                # researcher's repeat must not fold into it, reset its
                # review, or drop the restrictions it inherited.
                self.log.append(
                    f"claim {existing.id} is derived; a repeat of its "
                    "statement was kept separate"
                )
                break
            # The repeat's questions join the claim, but its partition is
            # fixed at admission; a non-material claim becomes material
            # only if its own partition still has room.
            material = existing.material or (
                claim.material
                and self.material_quota(material_partition(existing))
            )
            update: dict[str, Any] = {
                "questions": sorted(
                    set(existing.questions) | set(claim.questions)
                ),
                "topics": existing.topics
                + [t for t in claim.topics if t not in existing.topics],
                "material": material,
                # A limitation the repeat was admitted with (a dropped
                # quantity, an undated milestone) belongs on the
                # canonical claim; otherwise folding a repeat would
                # leave the record of the drop only in the route log.
                "limitations": _unique(
                    existing.limitations + claim.limitations
                ),
            }
            meaning_changed = False
            conflicts = []
            for field in (
                "quantity",
                "milestone",
                "milestone_date",
                "entity",
                "period",
                "dimension",
            ):
                mine = getattr(existing, field)
                theirs = getattr(claim, field)
                if mine is None and theirs is not None:
                    update[field] = theirs
                    meaning_changed = True
                elif mine is not None and theirs is not None and mine != theirs:
                    conflicts.append(field)
            if conflicts:
                update["limitations"] = _unique(
                    update["limitations"]
                    + [f"conflicting_repeat:{field}" for field in conflicts]
                )
                names = ", ".join(conflicts)
                self.log.append(
                    f"claim {existing.id}: a repeat disagreed on {names}; "
                    "existing values kept"
                )
            if meaning_changed:
                update["version"] = existing.version + 1
                update["supersedes"] = f"{existing.id}@{existing.version}"
                update["review"] = "unreviewed"
                update["review_reason"] = None
                update["reviewed_topics"] = []
                self.changed.add(existing.id)
                self.log.append(
                    f"claim {existing.id} gained fields from a repeat; "
                    f"version {existing.version + 1}, review reset"
                )
            self.claims[existing.id] = existing.model_copy(update=update)
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
        version_id = None
        if local.source_version_id:
            # A version the result carried, or one the registry already
            # holds (a reference reused by a later task, or a passage
            # retrieved from a chunk an earlier attempt indexed): version
            # ids are content-derived, so they match across attempts.
            version_id = version_map.get(
                local.source_version_id, local.source_version_id
            )
            version = registry.versions.get(version_id or "")
            if version is None or version.source_id != source_id:
                registry.log.append(
                    f"{result.attempt_id}: evidence {local.id} names "
                    f"version {local.source_version_id} that is missing or "
                    "belongs to another source; dropped"
                )
                continue
        elif local.kind in ("passage", "table"):
            registry.log.append(
                f"{result.attempt_id}: {local.kind} evidence {local.id} "
                "has no source version; dropped"
            )
            continue
        evidence_map[local.id] = registry.evidence_id(
            local, source_id, version_id
        )
    for draft in result.findings:
        _fold_finding(registry, result.attempt_id, draft, evidence_map)
    if result.map is not None:
        _fold_map(registry, result.attempt_id, result.map, evidence_map)


def _admit_quantity(
    registry: _Registry,
    attempt_id: str,
    draft: records.FindingDraft,
    evidence_map: dict[str, str],
    evidence_ids: list[str],
    limitations: list[str],
) -> records.Quantity | None:
    """Admit a draft's quantity against the canonical evidence it names.

    The evidence is read as stored in the registry (its canonical
    excerpt and layout), never as the attempt copied it, so the binding
    addresses the coordinates every later reader has. A refusal writes
    its code as a limitation and a log line; the finding is kept.
    """
    proposal = draft.quantity
    canonical = evidence_map.get(_label(proposal.evidence_ref))
    if canonical is None or canonical not in evidence_ids:
        limitations.append("quantity_evidence_ref_unknown")
        registry.log.append(
            f"{attempt_id}: quantity dropped, its evidence "
            f"{proposal.evidence_ref!r} is not among the finding's: "
            f"{draft.statement[:60]}"
        )
        return None
    outcome = quantities.admit(
        proposal, registry.evidence[canonical], canonical
    )
    if isinstance(outcome, quantities.Refusal):
        limitations.append(f"quantity_{outcome.code}")
        registry.log.append(
            f"{attempt_id}: quantity dropped ({outcome.code}: "
            f"{outcome.detail}), value {proposal.value} unit "
            f"{proposal.unit_text!r} quoted {proposal.quote!r} in "
            f"{canonical}: {draft.statement[:60]}"
        )
        return None
    return outcome


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
    quantity: records.Quantity | None = None
    if draft.quantity is not None:
        quantity = _admit_quantity(
            registry, attempt_id, draft, evidence_map, evidence_ids, limitations
        )
    if draft.milestone and not draft.milestone_date:
        limitations.append("undated_milestone")
    material = draft.material
    partition = partition_for(draft.questions)
    if material and not registry.material_quota(partition):
        # Beyond its quota a finding is kept as non-material: it stays
        # in the registry but does not enter the bounded review.
        material = False
        registry.log.append(
            f"{attempt_id}: material quota of {partition} reached; kept "
            f"non-material: {draft.statement[:60]}"
        )
    kind = draft.kind
    if kind == "derived":
        # "derived" belongs to a calculation's own claim; a researcher
        # reporting arithmetic is stating an inference.
        registry.log.append(
            f"{attempt_id}: finding claimed kind=derived; recorded as an "
            f"inference: {draft.statement[:60]}"
        )
        kind = "inference"
    claim_id = registry.add_claim(
        records.Claim(
            id="C0",
            statement=draft.statement,
            kind=kind,
            evidence_ids=evidence_ids,
            material=material,
            partition=partition,
            entity=draft.entity,
            period=draft.period,
            quantity=quantity,
            milestone=draft.milestone,
            milestone_date=draft.milestone_date,
            limitations=limitations,
            questions=draft.questions,
            topics=draft.topics,
            dimension=draft.dimension,
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
        if normalize_text(item.name) not in by_name and (
            not registry.material_quota("map:segment")
        ):
            registry.log.append(
                f"{attempt_id}: map segment {item.name} not added: "
                f"{registry.limits.map_segments} segments is the cap"
            )
            continue
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
                partition="map:segment",
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
    seg_stage = {s.id: s.stage for s in segments}
    existing_links = {(l.from_segment, l.to_segment) for l in links}
    for item in draft.links:
        if not registry.material_quota("map:link"):
            registry.log.append(
                f"{attempt_id}: map link {item.from_key}->{item.to_key} not "
                f"added: {registry.limits.map_links} links is the cap"
            )
            continue
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
                partition="map:link",
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
        stage = seg_stage.get(seg_id, "adjacent")
        if not registry.material_quota(f"map:participant:{stage}"):
            registry.log.append(
                f"{attempt_id}: map participant {item.name} not added: "
                f"{registry.limits.map_participants_per_stage} {stage} "
                "participants is the cap"
            )
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
                partition=f"map:participant:{stage}",
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
    registry = _Registry(state, limits)
    pending = [r for r in results if r.attempt_id not in merged]
    pending.sort(
        key=lambda r: (
            schedule.task_number(r.task_id),
            attempt_number(r.attempt_id),
        )
    )
    for result in pending:
        if result.attempt_id in merged:
            # The same attempt twice in one batch: the first fold has
            # already counted it, a second would duplicate its evidence.
            registry.log.append(
                f"{result.attempt_id}: duplicate result in the same merge "
                "ignored"
            )
            continue
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
            # A transport failure gets one more attempt with a fresh
            # reservation; a schema failure (the session's own
            # structured-output attempts exhausted) is not retried by the
            # graph, so SDK retries never compound with graph retries.
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
    update: dict[str, Any] = {
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
    if registry.changed:
        cascade = cascade_changes(
            state,
            registry.changed,
            registry.claims,
            registry.relationships,
        )
        update["route_log"] = registry.log + cascade.pop("route_log")
        update.update(cascade)
    return update


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
    evidence = state.get("evidence", {})
    versions = state.get("source_versions", {})
    log: list[str] = []

    def context_backed(evidence_ids: list[str]) -> bool:
        for eid in evidence_ids:
            item = evidence.get(eid)
            if item is None or item.kind not in ("passage", "table"):
                continue
            version = versions.get(item.source_version_id or "")
            if version is not None and version.source_id == item.source_id:
                return True
        return False

    calculations = state.get("calculations", {})
    changed: set[str] = set()
    for verdict in review.claims:
        claim = claims.get(verdict.claim_id)
        if claim is None:
            log.append(f"review names unknown claim {verdict.claim_id}")
            continue
        if not producer_chain_intact(claim, claims, calculations):
            # Reviewing the text of a stale derived claim would approve
            # arithmetic its own calculation has already withdrawn; it
            # has to be recomputed instead.
            log.append(
                f"verdict on {claim.id} ignored: the calculation behind "
                f"it ({claim.calculation_id}) is not current"
            )
            continue
        reason = verdict.reason.strip() or None
        if verdict.verdict == "qualified" and reason is None:
            # Without a reason the qualification could not reach the
            # report; the marker keeps the claim citable only with an
            # explicit "unstated" restriction and is logged.
            reason = "qualified by the verifier without a stated reason"
            log.append(f"claim {claim.id} qualified without a reason")
        claims[claim.id] = claim.model_copy(
            update={
                "review": verdict.verdict,
                "review_reason": reason,
                "reviewed_topics": [
                    t for t in verdict.topics_supported if t in claim.topics
                ],
                # Standalone delivery is approved only for a supported
                # claim: a qualified statement quoted alone would drop
                # the restriction that makes it true.
                "standalone": verdict.standalone
                and verdict.verdict == "supported",
            }
        )
        # What rests on a claim is invalidated when the claim stops
        # being citable or when its restriction changes. Rewording the
        # reason behind an unchanged supported verdict changes neither,
        # and must not cost the run its analysis.
        restriction = (
            claim.review_reason if claim.review == "qualified" else None
        )
        restricted_now = reason if verdict.verdict == "qualified" else None
        if claim.is_reviewed() and (
            not claims[claim.id].is_reviewed() or restriction != restricted_now
        ):
            changed.add(claim.id)
    # A parent that this batch rejected takes its relationships, its
    # derived claims and their calculations, findings and sections with
    # it; a parent it merely re-qualified takes them too, so nothing
    # keeps an approval its basis no longer supports. Rejected claims
    # join the same set, so one pass over one authority stales
    # everything this batch touched -- recomputing any part of it from
    # the state as it stood before would drop the rest.
    changed |= {
        verdict.claim_id
        for verdict in review.claims
        if verdict.verdict in ("unsupported", "contradicted")
        and verdict.claim_id in claims
    }
    cascade = cascade_changes(state, changed, claims, relationships)
    claims = cascade["claims"]
    relationships = cascade["relationships"]
    log.extend(cascade["route_log"])
    for verdict in review.relationships:
        relation = relationships.get(verdict.relationship_id)
        if relation is None:
            log.append(
                f"review names unknown relationship {verdict.relationship_id}"
            )
            continue
        parent = claims.get(relation.claim_id)
        parent_ok = parent is not None and parent.is_reviewed()
        confirmed = (
            verdict.supported
            and relation.relation != "generic_dependency"
            and context_backed(relation.evidence_ids)
            and parent_ok
        )
        if verdict.supported and not confirmed:
            reason = (
                "its parent claim is not reviewed supported/qualified"
                if not parent_ok
                else "no registry-backed passage or table behind it"
            )
            log.append(
                f"relationship {relation.id} judged supported but not "
                f"confirmed: {reason}"
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
        "calculations": cascade["calculations"],
        "findings": cascade["findings"],
        "sections": cascade["sections"],
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
      An empty update when every named value already holds; otherwise
      the update from ``cascade_changes``: the claim's version is
      incremented, ``supersedes`` names the previous version, its
      review is reset, and everything resting on it — claims derived
      through a calculation, those calculations, the findings and
      sections citing any of them, and its relationships — is
      invalidated with it.
    """
    claims = dict(state.get("claims", {}))
    claim = claims[claim_id]
    for field in ("calculation_id", "calculation_version", "kind"):
        # The producer owns these. A correction that could detach a
        # derived claim from its arithmetic is refused, not applied.
        changes.pop(field, None)
    if not changes or all(
        getattr(claim, field, None) == value for field, value in changes.items()
    ):
        # Nothing actually changed; a new version here would withdraw
        # the analysis that rests on the claim for no reason.
        return {}
    corrected = claim.model_copy(
        update={
            **changes,
            "version": claim.version + 1,
            "supersedes": f"{claim_id}@{claim.version}",
            "review": "unreviewed",
            "review_reason": None,
            "reviewed_topics": [],
        }
    )
    if corrected.quantity is not None and corrected.calculation_id is None:
        # A correction cannot leave an observed quantity resting on a
        # binding the evidence no longer establishes: it is re-verified
        # against the registry, and dropped with a limitation if it
        # fails, never searched for elsewhere.
        evidence = state.get("evidence", {})
        binding = corrected.quantity.binding
        holder = evidence.get(binding.evidence_id) if binding else None
        refused = (
            quantities.verify_binding(corrected.quantity, holder)
            if binding is not None
            and binding.evidence_id in corrected.evidence_ids
            else quantities.Refusal("unbound", "no binding among the evidence")
        )
        if refused is not None:
            corrected = corrected.model_copy(
                update={
                    "quantity": None,
                    "limitations": _unique(
                        corrected.limitations
                        + ["quantity_unbound_after_correction"]
                    ),
                }
            )
    claims[claim_id] = corrected
    return cascade_changes(state, {claim_id}, claims)


def stale_findings(
    findings: dict[str, records.Finding], claim_ids: set[str]
) -> dict[str, records.Finding]:
    """Mark every current finding citing one of the claims stale."""
    return {
        fid: (
            finding.model_copy(update={"status": "stale"})
            if finding.status == "current"
            and set(finding.claim_ids) & claim_ids
            else finding
        )
        for fid, finding in findings.items()
    }


def derived_dependants(
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
    changed: set[str],
) -> set[str]:
    """Claims computed, directly or transitively, from ``changed``.

    A calculation names the claims it consumed (``Calculation.inputs``)
    and the claim it produced carries its ``calculation_id``; following
    both links to a fixed point gives everything whose number depends
    on a claim that changed. A derived claim reached this way counts
    even when the same batch judged it directly: a verdict on its text
    cannot stand in for the arithmetic behind it.
    """
    consumers: dict[str, set[str]] = {}
    for calc in calculations.values():
        for item in calc.inputs:
            consumers.setdefault(item.claim_id, set()).add(calc.id)
    produced: dict[str, set[str]] = {}
    for cid, claim in claims.items():
        if claim.calculation_id:
            produced.setdefault(claim.calculation_id, set()).add(cid)
    found: set[str] = set()
    queue = list(changed)
    while queue:
        current = queue.pop()
        for calc_id in consumers.get(current, ()):
            for cid in produced.get(calc_id, ()):
                # A claim the same batch also judged is still a
                # dependant: being named as a root must not exempt it
                # from losing the approval its calculation withdrew.
                if cid in found:
                    continue
                found.add(cid)
                queue.append(cid)
    return found - {
        cid for cid in changed if claims[cid].calculation_id is None
    }


def cascade_changes(
    state: state_module.IndustryState,
    changed: set[str],
    claims: dict[str, records.Claim],
    relationships: dict[str, records.Relationship] | None = None,
) -> dict[str, Any]:
    """Carry a claim change through everything resting on it.

    A claim whose meaning or review changed takes its dependants with
    it: every claim derived from it through a calculation loses its
    review with a new version, every calculation that consumed one of
    them stops being current (the record stays, its status becomes an
    error naming the stale input), every current finding and every
    section citing any of them goes stale, and a relationship whose
    parent left supported/qualified is unconfirmed and must be judged
    again. Coverage follows from the findings and reviews, so it needs
    no separate step.

    Args:
      state: The state the change is applied to (for the registries the
        caller did not rebuild).
      changed: The ids of the claims that changed.
      claims: The claims registry *after* the change.
      relationships: The relationships registry after the change, when
        the caller rebuilt it; otherwise the one in ``state``.

    Returns:
      The state update for ``claims``, ``calculations``, ``findings``,
      ``relationships`` and ``sections``, plus its ``route_log`` lines.
    """
    claims = dict(claims)
    calculations = dict(state.get("calculations", {}))
    log: list[str] = []
    dependants = derived_dependants(claims, calculations, changed)
    for cid in sorted(dependants):
        claim = claims[cid]
        if not claim.is_reviewed() and not calculation_current(
            claim, claims, calculations
        ):
            # Already withdrawn by an earlier change; versioning it
            # again would only churn the record.
            continue
        claims[cid] = claim.model_copy(
            update={
                "version": claim.version + 1,
                "supersedes": f"{cid}@{claim.version}",
                "review": "unreviewed",
                "review_reason": None,
                "reviewed_topics": [],
            }
        )
        log.append(
            f"claim {cid} rests on a changed claim; version "
            f"{claim.version + 1}, review reset"
        )
    touched = set(changed) | dependants
    produced_by = {
        claims[cid].calculation_id: cid
        for cid in touched
        if cid in claims and claims[cid].calculation_id is not None
    }
    withdrawn: set[str] = set()
    for calc_id, calc in sorted(calculations.items()):
        stale = sorted({i.claim_id for i in calc.inputs} & touched)
        if calc.status == "ok" and calc_id in produced_by and not stale:
            # The claim reporting this result was corrected or
            # withdrawn directly; the arithmetic has to run again
            # rather than the claim be approved as it stands.
            calculations[calc_id] = calc.model_copy(
                update={
                    "status": "error",
                    "message": (
                        f"stale_input: {produced_by[calc_id]} was changed "
                        "after the calculation"
                    ),
                }
            )
            log.append(
                f"calculation {calc_id} no longer current: "
                f"{produced_by[calc_id]} was changed"
            )
            withdrawn.add(produced_by[calc_id])
            continue
        if calc.status == "ok" and stale:
            names = ", ".join(stale)
            calculations[calc_id] = calc.model_copy(
                update={
                    "status": "error",
                    "message": (
                        f"stale_input: {names} changed after the calculation"
                    ),
                }
            )
            log.append(
                f"calculation {calc_id} no longer current: {names} changed"
            )
    for cid in sorted(withdrawn):
        # Its own arithmetic has just been stopped, so whatever this
        # batch decided about the claim's text no longer stands: the
        # record has to say so, not only the citability predicate.
        claim = claims[cid]
        if claim.review == "unreviewed":
            continue
        claims[cid] = claim.model_copy(
            update={
                "version": claim.version + 1,
                "supersedes": f"{cid}@{claim.version}",
                "review": "unreviewed",
                "review_reason": None,
                "reviewed_topics": [],
            }
        )
        log.append(
            f"claim {cid} lost its review with calculation "
            f"{claim.calculation_id}; it must be recomputed"
        )
    if relationships is None:
        relationships = state.get("relationships", {})
    relationships, revoked = revoke_orphaned_relationships(
        relationships, claims
    )
    log.extend(revoked)
    return {
        "claims": claims,
        "calculations": calculations,
        "findings": stale_findings(state.get("findings", {}), touched),
        "relationships": relationships,
        "sections": [
            (
                section.model_copy(update={"stale": True})
                if set(section.claim_ids) & touched
                else section
            )
            for section in state.get("sections", [])
        ],
        "route_log": log,
    }


def issue_key(category: str, target: str, text: str | None = None) -> str:
    """The canonical key of an issue.

    One per category and target; when the issue is about one exact
    factual unit (``text``), one per unit, so several unsupported
    sentences in the same section are separate issues that are each
    redacted while open, and a section-wide problem (no unit) stays
    distinguishable from them. Repeats of the same unit share the key,
    and so the attempt count.
    """
    key = f"{category}:{target}"
    if text:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        key = f"{key}#{digest}"
    return key


def partition_for(questions: list[int]) -> str:
    """The partition of a non-map claim: its lowest central question."""
    central = [q for q in questions if q in records.CENTRAL_QUESTIONS]
    return f"q{min(central)}" if central else "other"


def material_partition(claim: records.Claim) -> str:
    """The partition a claim counts against (fixed at admission)."""
    if claim.partition:
        return claim.partition
    if claim.map_ref is not None:
        return "map:legacy"
    return partition_for(claim.questions)


def partition_cap(partition: str, limits: records.Limits) -> int:
    """How many material claims ``partition`` may hold."""
    if partition == "map:segment":
        return limits.map_segments
    if partition == "map:link":
        return limits.map_links
    if partition.startswith("map:participant:"):
        return limits.map_participants_per_stage
    if partition == "other":
        return limits.material_other
    if partition.startswith("q"):
        return limits.material_per_question
    return 0


def admit_material(
    claims: dict[str, records.Claim],
    limits: records.Limits,
    partition: str,
) -> bool:
    """The one authority admitting a material claim to a partition.

    Findings, map items, and derived claims all pass through here. A
    map segment, link, or participant counts against its own sub-quota
    (participants per stage); any other claim against the lowest
    central question it serves (``material_per_question`` each) or,
    serving none, against ``material_other``. The partitions are
    disjoint and fixed at admission (``Claim.partition``), so a full
    map never starves an economics question and a repeat that adds
    questions never moves a claim.
    """
    used = sum(
        1
        for c in claims.values()
        if c.material and material_partition(c) == partition
    )
    return used < partition_cap(partition, limits)


def derived_fields(
    result: records.Calculation, claims: dict[str, records.Claim]
) -> dict[str, Any]:
    """The claim fields that report one calculation's result.

    The one projection rule: ``calc`` writes a derived claim from it and
    ``calculation_current`` compares a derived claim against it. A
    derived claim states the result, cites the evidence of every claim
    the calculation consumed, and inherits their restrictions: it is
    qualified when an input was, or when the periods or scopes were
    only comparable under an alignment note, and supported otherwise.
    Its approval comes from its inputs and the arithmetic, never from a
    verdict on its text.
    """
    cited = [item.claim_id for item in result.inputs]
    cited_text = ", ".join(cited)
    evidence_ids: list[str] = []
    for cid in cited:
        for eid in claims[cid].evidence_ids:
            if eid not in evidence_ids:
                evidence_ids.append(eid)
    qualifications = [
        f"{item.claim_id}: {item.qualification}"
        for item in result.inputs
        if item.qualification
    ]
    if result.alignment_note:
        qualifications.append(f"alignment: {result.alignment_note}")
    unit = quantities.render(result.unit) if result.unit else ""
    last = result.inputs[-1].quantity
    return {
        "statement": (
            f"{result.label}: {result.result} {unit} "
            f"(computed from {cited_text}; {result.formula})"
        ),
        "evidence_ids": evidence_ids,
        "calculation_id": result.id,
        "calculation_version": result.version,
        "review": "qualified" if qualifications else "supported",
        "review_reason": "; ".join(qualifications) or None,
        "quantity": records.Quantity(
            value=result.result if result.result is not None else 0.0,
            unit=result.unit,
            period=last.period,
            scope=last.scope,
            binding=None,
        ),
        "limitations": (
            [f"alignment: {result.alignment_note}"]
            if result.alignment_note
            else []
        ),
    }


def calc_input_origin(
    consumed: records.CalcInput,
) -> tuple[Any, ...] | None:
    """Where an input's figure came from, or ``None`` if untraceable.

    Two operands are the same figure when they came from the same
    place, not when they happen to be equal: an observed value is its
    exact evidence occurrence, a derived one is the producer result it
    projects. Wording, scope, period and qualification are deliberately
    excluded -- rewording a claim must not mint a second occurrence.
    """
    producer = consumed.source_calculation_id
    version = consumed.source_calculation_version
    if producer and version:
        return ("derived", producer, version)
    binding = consumed.quantity.binding if consumed.quantity else None
    if binding is None:
        return None
    return (
        "observed",
        binding.evidence_id,
        binding.excerpt_sha256,
        binding.number_start,
        binding.number_end,
    )


def identical_operands(
    numerator: records.CalcInput, denominator: records.CalcInput
) -> str | None:
    """Why two operands are one figure, or ``None`` when they differ.

    A share of a figure over itself is always 100% and a ratio always
    1.0, so it states nothing and cannot be right. Headline run 5's
    analyst asked for four of them, meaning two different numbers that
    lived inside one claim; the claim carries one quantity, so both
    operands resolved to the same one. Claim ids alone are too weak a
    test: two claims can quote one occurrence, and two derived claims
    can project one producer.
    """
    if numerator.claim_id == denominator.claim_id:
        return (
            "identical_operands: both sides are claim " f"{numerator.claim_id}"
        )
    left = calc_input_origin(numerator)
    right = calc_input_origin(denominator)
    if left is None or right is None:
        unknown = numerator.claim_id if left is None else denominator.claim_id
        return (
            f"unknown_origin: claim {unknown} has no evidence binding and "
            "no producer, so its figure cannot be told from another"
        )
    if left == right:
        return (
            "identical_operands: "
            f"{numerator.claim_id} and {denominator.claim_id} are the same "
            "figure"
        )
    return None


def calculation_identity_ok(record: records.Calculation) -> bool:
    """Whether a successful share or ratio divided two distinct figures.

    Only the identity of the two operands is judged here. An unusual
    input count is a structural matter the record checks already cover,
    and refusing it in this rule's name would reject states for a
    reason that has nothing to do with dividing a figure by itself.
    """
    if record.status != "ok" or record.kind not in ("share", "ratio"):
        return True
    if len(record.inputs) != 2:
        return True
    return identical_operands(record.inputs[0], record.inputs[1]) is None


def calculation_current(
    claim: records.Claim,
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
    seen: frozenset[str] = frozenset(),
) -> bool:
    """Whether a claim reporting a calculation still agrees with it.

    A derived claim is only ever as good as the arithmetic behind it,
    so it must still *be* that arithmetic: the producer has to exist,
    be current, be the version the claim reports, state the same value
    and unit, and rest on inputs that are themselves citable. Anything
    else -- the producer stopped, recomputed, deleted, or a claim
    corrected away from it -- makes the claim uncitable until
    ``calc.recompute_stale`` writes a new version of it. This is what
    stops a verdict on a claim's text from standing in for its
    arithmetic.
    """
    if claim.calculation_id is None:
        # A claim of kind "derived" with no producer is a claim about
        # arithmetic with no arithmetic behind it, whoever wrote it.
        return claim.kind != "derived"
    if claim.id in seen:
        return False
    record = calculations.get(claim.calculation_id)
    if record is not None and not calculation_identity_ok(record):
        # A figure divided by itself is not arithmetic anyone may cite,
        # however well the snapshots round-trip.
        return False
    if record is None or record.status != "ok" or record.unit is None:
        return False
    if record.result is None or claim.calculation_version != record.version:
        return False
    if any(item.claim_id not in claims for item in record.inputs):
        return False
    # The claim must *be* the projection of its producer over the
    # current parents: the generated statement, value exactly, unit
    # structurally, period, scope, evidence, and -- while it carries
    # approval -- the inherited restriction. A parent re-qualified
    # without a version bump shows up here even when a cascade missed
    # it; so does a statement that no longer says what was computed.
    projection = derived_fields(record, claims)
    if claim.statement != projection["statement"]:
        return False
    if claim.quantity != projection["quantity"]:
        return False
    if claim.evidence_ids != projection["evidence_ids"]:
        return False
    if claim.is_reviewed() and (claim.review, claim.review_reason) != (
        projection["review"],
        projection["review_reason"],
    ):
        return False
    return True


def producer_chain_intact(
    claim: records.Claim,
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
    seen: frozenset[str] = frozenset(),
) -> bool:
    """Whether every claim under a derived claim is itself citable.

    A calculation left ``ok`` over an input that has since been
    withdrawn would otherwise keep its result citable, so the check
    walks the whole chain.
    """
    if not calculation_current(claim, claims, calculations, seen):
        return False
    if claim.calculation_id is None:
        return True
    if claim.calculation_id not in calculations:
        return False
    record = calculations[claim.calculation_id]
    deeper = seen | {claim.id}
    for item in record.inputs:
        parent = claims.get(item.claim_id)
        if parent is None or not parent.is_reviewed():
            return False
        # The input is a preserved copy of the parent as consumed; any
        # drift -- version, quantity, or qualification -- withdraws the
        # result even if a cascade missed the change.
        if parent.version != item.claim_version:
            return False
        if parent.quantity != item.quantity:
            return False
        basis = parent.review_reason if parent.review == "qualified" else None
        if basis != item.qualification:
            return False
        if not producer_chain_intact(parent, claims, calculations, deeper):
            return False
    return True


def citable(
    claim: records.Claim,
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
) -> bool:
    """Whether the claim may be cited: reviewed, and its arithmetic live."""
    return claim.is_reviewed() and producer_chain_intact(
        claim, claims, calculations
    )


def relationship_live(
    relation: records.Relationship, claims: dict[str, records.Claim]
) -> bool:
    """Confirmed and resting on a currently supported/qualified parent."""
    parent = claims.get(relation.claim_id)
    return relation.confirmed and parent is not None and parent.is_reviewed()


def revoke_orphaned_relationships(
    relationships: dict[str, records.Relationship],
    claims: dict[str, records.Claim],
) -> tuple[dict[str, records.Relationship], list[str]]:
    """Unconfirm every relationship whose parent left supported/qualified.

    Citability is ``Claim.is_reviewed``, so a parent that came back
    qualified without a reason on record takes its relationships with
    it exactly like a rejected one.
    """
    updated = dict(relationships)
    log: list[str] = []
    for rel in relationships.values():
        parent = claims.get(rel.claim_id)
        parent_ok = parent is not None and parent.is_reviewed()
        if rel.confirmed and not parent_ok:
            updated[rel.id] = rel.model_copy(
                update={"confirmed": False, "review": "unreviewed"}
            )
            log.append(
                f"relationship {rel.id} unconfirmed: its parent claim "
                f"{rel.claim_id} is no longer supported/qualified"
            )
    return updated, log


def open_issue(
    issues: dict[str, records.Issue],
    category: records.IssueCategory,
    severity: records.Severity,
    target: str,
    requested_action: records.RequestedAction,
    description: str,
    next_step: str | None = None,
    draft_version: int | None = None,
    text: str | None = None,
) -> tuple[dict[str, records.Issue], records.Issue]:
    """Return the unresolved issue with this key, or add a new one.

    An existing open issue keeps its attempt count; only the description,
    next step, and draft version are refreshed, so repeats never reset
    the limit. An issue retired at the follow-up limit (``unresolvable``)
    is refreshed the same way and stays retired: the same problem
    recurring never starts a fresh allowance.
    """
    key = issue_key(category, target, text)
    updated = dict(issues)
    for issue in issues.values():
        if (
            issue.key == key
            and issue.status in records.UNRESOLVED_ISSUE_STATUSES
        ):
            refreshed = issue.model_copy(
                update={
                    "description": description,
                    "next_step": next_step,
                    "draft_version": (
                        draft_version
                        if draft_version is not None
                        else issue.draft_version
                    ),
                    "text": text if text is not None else issue.text,
                }
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
        draft_version=draft_version,
        text=text,
    )
    updated[new_id] = issue
    return updated, issue
