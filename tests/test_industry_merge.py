"""Deterministic merge, review application, invalidation, issues."""

from industry import budget
from industry import merge
from industry import records

NOW = "2026-09-07T00:00:00+00:00"
LIMITS = records.Limits()


def source(sid, url, title=None):
    return records.Source(
        id=sid, canonical_url=url, title=title or url, kind="web_page"
    )


def version(vid, sid, content_hash):
    return records.SourceVersion(
        id=vid,
        source_id=sid,
        content_hash=content_hash,
        blob_path="b",
        meta_path="m",
        final_url="u",
        content_type="text/html",
        size=1,
        retrieved_at=NOW,
        extraction_version="v2",
    )


def evidence(eid, sid, excerpt, vid="va", kind="passage", locator="sec 1"):
    return records.Evidence(
        id=eid,
        source_id=sid,
        source_version_id=vid,
        excerpt=excerpt,
        locator=locator,
        kind=kind,
        extraction="html_text" if kind != "snippet" else "search_snippet",
        task_id="T1",
        retrieved_at=NOW,
    )


def attempt(aid, task_id):
    return records.Attempt(
        id=aid,
        task_id=task_id,
        reserved=records.Reservation(turns=12, tool_calls=24, seconds=1200),
        started_at=NOW,
    )


def task(tid, kind="research", attempts=1):
    return records.Task(
        id=tid,
        kind=kind,
        role="industry",
        objective=tid,
        status="running",
        attempts=attempts,
    )


def base_state():
    return {
        "tasks": {"T1": task("T1", "map"), "T2": task("T2")},
        "attempts": {
            "T1.1": attempt("T1.1", "T1"),
            "T2.1": attempt("T2.1", "T2"),
        },
        "merged": [],
    }


def result_t2(
    excerpt="Acme revenue reached 52亿元 in 2024, up 12%.", quantity=True
):
    return records.TaskResult(
        attempt_id="T2.1",
        task_id="T2",
        status="done",
        sources=[source("S1", "https://a.example/x", "A page")],
        source_versions=[version("va", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", excerpt, "va")],
        findings=[
            records.FindingDraft(
                statement="Acme 2024 revenue was 52亿元",
                evidence_refs=["[E1]"],
                entity="Acme",
                period="2024",
                material=True,
                quantity=(
                    records.Quantity(
                        value=52,
                        unit="亿元",
                        period="2024",
                        as_written="52亿元",
                    )
                    if quantity
                    else None
                ),
                relationships=[
                    records.RelationshipDraft(
                        from_entity="Acme",
                        to_entity="Beta",
                        relation="supplies",
                        evidence_refs=["E1"],
                    )
                ],
                questions=[4],
                topics=["demand_driver"],
            ),
            records.FindingDraft(statement="dangling", evidence_refs=["E7"]),
        ],
        usage=records.Usage(turns=5, tool_calls=3, duration_s=40),
    )


def test_merge_assigns_canonical_ids_and_reconciles_attempt():
    state = base_state()
    update = merge.merge_results(state, [result_t2()], LIMITS)
    assert list(update["sources"]) == ["S1"]
    assert update["source_versions"]["va"].source_id == "S1"
    assert update["sources"]["S1"].versions == ["va"]
    assert list(update["evidence"]) == ["E1"]
    claim = update["claims"]["C1"]
    assert claim.evidence_ids == ["E1"] and claim.quantity.value == 52
    assert claim.origin == "T2.1" and claim.topics == ["demand_driver"]
    rel = update["relationships"]["R1"]
    assert rel.confirmed is False and rel.review == "unreviewed"
    assert rel.claim_id == "C1" and rel.evidence_ids == ["E1"]
    assert update["attempts"]["T2.1"].status == "done"
    assert update["attempts"]["T2.1"].observed.turns == 5
    assert update["attempts"]["T2.1"].duration_s == 40
    assert update["tasks"]["T2"].status == "done"
    assert update["merged"] == ["T2.1"]
    assert any(
        "dangling" in line and "dropped" in line for line in update["route_log"]
    )


def test_merge_is_idempotent_and_dedups_across_attempts():
    state = base_state()
    first = merge.merge_results(state, [result_t2()], LIMITS)
    state.update(first)
    again = merge.merge_results(state, [result_t2()], LIMITS)
    assert again["merged"] == ["T2.1"] and len(again["claims"]) == 1
    # A second attempt re-reporting the same source and excerpt maps to
    # the same ids; a different excerpt from the same page gets E2.
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    second = result_t2().model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    second.sources[0] = source("S9", "https://a.example/x")
    second.source_versions[0] = version("va", "S9", "hash-a")
    second.evidence[0] = evidence(
        "E3", "S9", "Acme revenue reached 52亿元 in 2024, up 12%.", "va"
    )
    second.evidence.append(
        evidence("E4", "S9", "Beta buys from Acme.", "va", locator="sec 2")
    )
    second.findings[0] = second.findings[0].model_copy(
        update={"evidence_refs": ["E3"]}
    )
    update = merge.merge_results(state, [second], LIMITS)
    assert list(update["sources"]) == ["S1"]
    assert sorted(update["evidence"]) == ["E1", "E2"]
    assert len(update["claims"]) == 1  # identical statement + evidence


def test_quantity_not_in_excerpt_is_dropped_with_limitation():
    state = base_state()
    update = merge.merge_results(
        state,
        [result_t2(excerpt="Acme revenue grew strongly in 2024.")],
        LIMITS,
    )
    claim = update["claims"]["C1"]
    assert claim.quantity is None
    assert "quantity_not_in_excerpt" in claim.limitations


def test_quantity_matching_ignores_separators():
    quantity = records.Quantity(
        value=1546.1, unit="亿美元", as_written="1,546.1"
    )
    assert merge.quantity_in_excerpts(quantity, ["进口额高达1546.1亿美元"])
    assert merge.quantity_in_excerpts(
        records.Quantity(value=52, unit="亿", as_written="52亿"), ["约 52 亿元"]
    )
    assert not merge.quantity_in_excerpts(quantity, ["进口额高达 154 亿美元"])


def test_same_url_different_bytes_is_a_new_version_old_evidence_kept():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    later = records.TaskResult(
        attempt_id="T3.1",
        task_id="T3",
        status="done",
        sources=[source("S1", "https://a.example/x")],
        source_versions=[version("vb", "S1", "hash-b")],
        evidence=[evidence("E1", "S1", "Updated text of the page.", "vb")],
        findings=[
            records.FindingDraft(statement="updated", evidence_refs=["E1"])
        ],
    )
    update = merge.merge_results(state, [later], LIMITS)
    assert update["sources"]["S1"].versions == ["va", "vb"]
    assert update["evidence"]["E1"].source_version_id == "va"
    assert update["evidence"]["E2"].source_version_id == "vb"


def test_two_urls_same_bytes_marks_syndication():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    mirror = records.TaskResult(
        attempt_id="T3.1",
        task_id="T3",
        status="done",
        sources=[source("S1", "https://mirror.example/y")],
        source_versions=[version("vm", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", "Mirrored.", "vm")],
        findings=[records.FindingDraft(statement="m", evidence_refs=["E1"])],
    )
    update = merge.merge_results(state, [mirror], LIMITS)
    assert update["sources"]["S2"].syndicated_of == "S1"
    assert any("syndicates" in line for line in update["route_log"])


def test_identical_long_passages_across_sources_mark_syndication():
    state = base_state()
    long_text = "同一段落 " * 60
    first = result_t2(excerpt=long_text, quantity=False)
    state.update(merge.merge_results(state, [first], LIMITS))
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    copy = records.TaskResult(
        attempt_id="T3.1",
        task_id="T3",
        status="done",
        sources=[source("S1", "https://copy.example/z")],
        source_versions=[version("vc", "S1", "hash-c")],
        evidence=[evidence("E1", "S1", long_text, "vc")],
        findings=[records.FindingDraft(statement="c", evidence_refs=["E1"])],
    )
    update = merge.merge_results(state, [copy], LIMITS)
    assert update["sources"]["S2"].syndicated_of == "S1"


def test_map_draft_becomes_map_items_with_map_claims():
    state = base_state()
    draft = records.MapDraft(
        segments=[
            records.SegmentDraft(
                key="u",
                name="基板",
                stage="upstream",
                description="石英",
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
                key="x",
                name="幽灵",
                stage="adjacent",
                description="",
                evidence_refs=["E9"],
            ),
        ],
        links=[
            records.LinkDraft(
                from_key="u",
                to_key="m",
                what_flows="基板",
                evidence_refs=["E1"],
            )
        ],
        participants=[
            records.ParticipantDraft(
                name="HOYA",
                segment_key="u",
                role="supplier",
                supplies="EUV 掩模基板",
                region="日本",
                evidence_refs=["E1"],
            ),
            records.ParticipantDraft(
                name="Nobody",
                segment_key="zz",
                role="other",
                evidence_refs=["E1"],
            ),
        ],
        boundary_note="掩模版制造及其直接上游",
        gaps=["下游未覆盖"],
    )
    result = records.TaskResult(
        attempt_id="T1.1",
        task_id="T1",
        status="done",
        sources=[source("S1", "https://a.example/x")],
        source_versions=[version("va", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", "HOYA supplies mask blanks.")],
        map=draft,
    )
    update = merge.merge_results(state, [result], LIMITS)
    industry_map = update["map"]
    assert [s.id for s in industry_map.segments] == ["G1", "G2"]
    assert industry_map.links[0].id == "L1"
    assert industry_map.participants[0].id == "P1"
    assert industry_map.version == 1 and industry_map.gaps == ["下游未覆盖"]
    claims = update["claims"]
    assert claims[industry_map.segments[0].claim_id].map_ref == "G1"
    assert claims[industry_map.links[0].claim_id].questions == [2]
    part_claim = claims[industry_map.participants[0].claim_id]
    assert part_claim.entity == "HOYA" and part_claim.kind == "map"
    assert "supplies EUV 掩模基板" in part_claim.statement
    assert industry_map.participants[0].supplies == "EUV 掩模基板"
    assert part_claim.material and part_claim.review == "unreviewed"
    assert sum("dropped" in line for line in update["route_log"]) == 2
    # Merging the same draft again adds nothing.
    state.update(update)
    state["tasks"]["T3"] = task("T3", "map")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    again = merge.merge_results(
        state,
        [result.model_copy(update={"attempt_id": "T3.1", "task_id": "T3"})],
        LIMITS,
    )
    assert len(again["map"].segments) == 2 and len(again["claims"]) == 4


def test_failed_attempt_requeues_once_then_fails():
    state = base_state()
    failed = records.TaskResult(
        attempt_id="T2.1",
        task_id="T2",
        status="failed",
        usage=records.Usage(unknown=True),
        error="transport: CLIConnectionError",
    )
    update = merge.merge_results(state, [failed], LIMITS)
    assert update["tasks"]["T2"].status == "pending"
    assert update["attempts"]["T2.1"].status == "failed"
    assert update["attempts"]["T2.1"].observed is not None
    # Unknown usage is informational; the reservation stays charged.
    charged = budget.ledger({"attempts": update["attempts"]})
    assert (charged.turns, charged.tool_calls) == (24, 48)
    assert charged.wall_clock_s == 2400 and charged.unknown_attempts == 2
    state.update(update)
    state["tasks"]["T2"] = state["tasks"]["T2"].model_copy(
        update={"attempts": 2, "status": "running"}
    )
    state["attempts"]["T2.2"] = attempt("T2.2", "T2")
    unknown = records.TaskResult(
        attempt_id="T2.2", task_id="T2", status="unknown"
    )
    update = merge.merge_results(state, [unknown], LIMITS)
    assert update["tasks"]["T2"].status == "failed"
    assert update["attempts"]["T2.2"].status == "unknown"
    assert update["attempts"]["T2.2"].observed is None


def test_schema_failure_is_not_requeued():
    state = base_state()
    failed = records.TaskResult(
        attempt_id="T2.1",
        task_id="T2",
        status="failed",
        usage=records.Usage(turns=13),
        error="schema: ResultError[error_during_execution]",
    )
    update = merge.merge_results(state, [failed], LIMITS)
    assert update["tasks"]["T2"].status == "failed"
    charged = budget.ledger({"attempts": update["attempts"]})
    assert charged.turns == 13 + 12  # observed T2.1 + running T1.1


def test_results_fold_in_task_order_regardless_of_arrival():
    state = base_state()
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    r2 = result_t2()
    r3 = records.TaskResult(
        attempt_id="T3.1",
        task_id="T3",
        status="done",
        sources=[source("S1", "https://b.example/")],
        source_versions=[version("vb", "S1", "hash-b")],
        evidence=[evidence("E1", "S1", "Beta text.", "vb")],
        findings=[records.FindingDraft(statement="beta", evidence_refs=["E1"])],
    )
    update = merge.merge_results(state, [r3, r2], LIMITS)
    assert update["sources"]["S1"].canonical_url == "https://a.example/x"
    assert update["sources"]["S2"].canonical_url == "https://b.example/"
    assert update["merged"] == ["T2.1", "T3.1"]


def test_apply_review_confirms_only_supported_non_generic_relations():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    state["relationships"]["R2"] = records.Relationship(
        id="R2",
        from_entity="A",
        to_entity="B",
        relation="generic_dependency",
        claim_id="C1",
    )
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1", verdict="qualified", reason="snippet only"
            )
        ],
        relationships=[
            records.RelationshipVerdict(
                relationship_id="R1", supported=True, reason="named"
            ),
            records.RelationshipVerdict(
                relationship_id="R2", supported=True, reason="generic"
            ),
            records.RelationshipVerdict(
                relationship_id="R9", supported=True, reason="?"
            ),
        ],
        sources=[
            records.SourceOriginJudgement(
                source_id="S1", origin="secondary", reason="news"
            )
        ],
    )
    update = merge.apply_review(state, review)
    assert update["claims"]["C1"].review == "qualified"
    assert (
        update["relationships"]["R1"].confirmed
        and update["relationships"]["R1"].review == "supported"
    )
    assert not update["relationships"]["R2"].confirmed
    assert update["sources"]["S1"].origin == "secondary"
    assert any("R9" in line for line in update["route_log"])


def test_invalidate_claim_versions_and_marks_stale():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "supported"}
    )
    state["findings"] = {
        "F1": records.Finding(
            id="F1",
            conclusion="",
            claim_ids=["C1"],
            mechanism="",
            implication="",
            counterargument="",
            uncertainty="",
            monitor="",
        )
    }
    state["sections"] = [
        records.Section(id="s1", title="t", text="[C1]", claim_ids=["C1"])
    ]
    update = merge.invalidate_claim(state, "C1", statement="corrected")
    claim = update["claims"]["C1"]
    assert claim.version == 2 and claim.supersedes == "C1@1"
    assert claim.review == "unreviewed" and claim.statement == "corrected"
    assert update["findings"]["F1"].status == "stale"
    assert update["sections"][0].stale


def test_open_issue_is_canonical_and_keeps_attempts():
    issues, first = merge.open_issue(
        {}, "missing_evidence", "material", "Q4", "research", "no payer data"
    )
    issues[first.id] = first.model_copy(update={"attempts": 2})
    issues, again = merge.open_issue(
        issues,
        "missing_evidence",
        "material",
        "Q4",
        "research",
        "still none",
        "fetch filing",
    )
    assert again.id == first.id and again.attempts == 2
    assert (
        again.description == "still none" and again.next_step == "fetch filing"
    )
    issues, other = merge.open_issue(
        issues, "contradiction", "material", "Q4", "acquire", "x"
    )
    assert other.id == "I2"


def test_passage_without_a_valid_version_is_dropped():
    state = base_state()
    result = result_t2()
    result.evidence[0] = evidence(
        "E1", "S1", "Acme revenue reached 52亿元 in 2024, up 12%.", "missing"
    )
    update = merge.merge_results(state, [result], LIMITS)
    assert not update["evidence"] and not update["claims"]
    assert any(
        "missing or belongs to another source" in l for l in update["route_log"]
    )
    # A version that belongs to another source is refused too.
    state = base_state()
    result = result_t2()
    result.sources.append(source("S2", "https://other.example/"))
    result.source_versions[0] = version("va", "S2", "hash-a")
    update = merge.merge_results(state, [result], LIMITS)
    assert not update["evidence"]
    # A snippet needs no version.
    state = base_state()
    result = result_t2()
    result.source_versions = []
    result.evidence[0] = evidence(
        "E1",
        "S1",
        "Acme revenue reached 52亿元 in 2024, up 12%.",
        None,
        "snippet",
    )
    update = merge.merge_results(state, [result], LIMITS)
    assert list(update["evidence"]) == ["E1"]


def test_repeated_claim_gains_metadata_and_resets_review_when_meaning_changes():
    state = base_state()
    plain = result_t2(quantity=False)
    plain.findings[0] = plain.findings[0].model_copy(
        update={
            "questions": [4],
            "topics": ["demand_driver"],
            "entity": None,
            "period": None,
        }
    )
    state.update(merge.merge_results(state, [plain], LIMITS))
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "supported"}
    )
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    richer = result_t2().model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    richer.findings[0] = richer.findings[0].model_copy(
        update={"questions": [7], "topics": ["comparison"], "material": True}
    )
    update = merge.merge_results(state, [richer], LIMITS)
    claim = update["claims"]["C1"]
    assert len(update["claims"]) == 1
    assert claim.questions == [4, 7] and claim.topics == [
        "demand_driver",
        "comparison",
    ]
    assert claim.quantity is not None and claim.entity == "Acme"
    assert claim.version == 2 and claim.review == "unreviewed"
    # A repeat that only adds classification does not reset the review.
    state.update(update)
    state["claims"]["C1"] = claim.model_copy(update={"review": "supported"})
    state["tasks"]["T4"] = task("T4")
    state["attempts"]["T4.1"] = attempt("T4.1", "T4")
    tagged = result_t2().model_copy(
        update={"attempt_id": "T4.1", "task_id": "T4"}
    )
    tagged.findings[0] = tagged.findings[0].model_copy(
        update={"questions": [3]}
    )
    update = merge.merge_results(state, [tagged], LIMITS)
    assert update["claims"]["C1"].review == "supported"
    assert update["claims"]["C1"].questions == [3, 4, 7]


def test_apply_review_keeps_only_confirmed_topics():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1",
                verdict="supported",
                reason="r",
                topics_supported=["demand_driver", "barrier"],
            )
        ]
    )
    update = merge.apply_review(state, review)
    assert update["claims"]["C1"].reviewed_topics == ["demand_driver"]


def test_reference_reuse_and_indexed_passage_keep_their_version():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    # T3 cites the same passage (a reference, or a fresh retrieval of the
    # chunk T2 indexed) without carrying the version record itself.
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    reuse = records.TaskResult(
        attempt_id="T3.1",
        task_id="T3",
        status="done",
        sources=[source("S1", "https://a.example/x")],
        evidence=[
            evidence(
                "E1", "S1", "Acme revenue reached 52亿元 in 2024, up 12%.", "va"
            )
        ],
        findings=[
            records.FindingDraft(
                statement="downstream reuse", evidence_refs=["E1"]
            )
        ],
    )
    update = merge.merge_results(state, [reuse], LIMITS)
    assert list(update["evidence"]) == ["E1"]
    assert "C2" in update["claims"] and update["claims"]["C2"].evidence_ids == [
        "E1"
    ]


def test_snippet_only_relationship_is_supported_but_not_confirmed():
    state = base_state()
    result = result_t2()
    result.source_versions = []
    result.evidence[0] = evidence(
        "E1", "S1", "Acme supplies Beta with blanks (52亿元).", None, "snippet"
    )
    state.update(merge.merge_results(state, [result], LIMITS))
    review = records.ClaimReview(
        relationships=[
            records.RelationshipVerdict(
                relationship_id="R1", supported=True, reason="named"
            )
        ]
    )
    update = merge.apply_review(state, review)
    rel = update["relationships"]["R1"]
    assert rel.review == "supported" and rel.confirmed is False
    assert any("not confirmed" in line for line in update["route_log"])


def test_meaning_change_stales_dependants_and_conflicts_are_kept():
    state = base_state()
    plain = result_t2(quantity=False)
    state.update(merge.merge_results(state, [plain], LIMITS))
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "supported"}
    )
    state["findings"] = {
        "F1": records.Finding(
            id="F1",
            conclusion="",
            claim_ids=["C1"],
            mechanism="",
            implication="",
            counterargument="",
            uncertainty="",
            monitor="",
        )
    }
    state["sections"] = [
        records.Section(id="s1", title="t", text="[C1]", claim_ids=["C1"])
    ]
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    richer = result_t2().model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    update = merge.merge_results(state, [richer], LIMITS)
    assert update["claims"]["C1"].version == 2
    assert update["findings"]["F1"].status == "stale"
    assert update["sections"][0].stale
    # A repeat that disagrees keeps the existing value and records it.
    state.update(update)
    state["tasks"]["T4"] = task("T4")
    state["attempts"]["T4.1"] = attempt("T4.1", "T4")
    other = result_t2().model_copy(
        update={"attempt_id": "T4.1", "task_id": "T4"}
    )
    other.findings[0] = other.findings[0].model_copy(update={"period": "2023"})
    update = merge.merge_results(state, [other], LIMITS)
    assert update["claims"]["C1"].period == "2024"
    assert "conflicting_repeat:period" in update["claims"]["C1"].limitations


def test_material_findings_beyond_the_question_quota_stay_non_material():
    state = base_state()
    limits = records.Limits(
        **{**LIMITS.model_dump(), "material_per_question": 2}
    )
    drafts = [
        records.FindingDraft(
            statement=f"fact {n}",
            material=True,
            evidence_refs=["E1"],
            questions=[4],
        )
        for n in range(4)
    ]
    result = records.TaskResult(
        attempt_id="T1.1",
        task_id="T1",
        status="done",
        usage=records.Usage(turns=3),
        sources=[source("S1", "https://a.example/x", "A page")],
        source_versions=[version("va", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", "fact text", "va")],
        findings=drafts,
    )
    update = merge.merge_results(state, [result], limits)
    added = [
        c for c in update["claims"].values() if c.statement.startswith("fact ")
    ]
    assert sum(c.material for c in added) == 2 and len(added) == 4
    assert any("material quota reached" in line for line in update["route_log"])


def test_map_segments_links_and_participants_are_capped():
    state = base_state()
    limits = records.Limits(
        **{
            **LIMITS.model_dump(),
            "map_segments": 2,
            "map_links": 1,
            "map_participants_per_stage": 1,
        }
    )
    draft = records.MapDraft(
        segments=[
            records.SegmentDraft(
                key=f"s{n}",
                name=f"segment {n}",
                stage="upstream" if n == 0 else "midstream",
                description="d",
                evidence_refs=["E1"],
            )
            for n in range(4)
        ],
        links=[
            records.LinkDraft(
                from_key="s0", to_key="s1", what_flows="x", evidence_refs=["E1"]
            ),
            records.LinkDraft(
                from_key="s1", to_key="s0", what_flows="y", evidence_refs=["E1"]
            ),
        ],
        participants=[
            records.ParticipantDraft(
                name=f"company {n}",
                segment_key="s0" if n < 3 else "s1",
                role="supplier",
                evidence_refs=["E1"],
            )
            for n in range(4)
        ],
    )
    result = records.TaskResult(
        attempt_id="T1.1",
        task_id="T1",
        status="done",
        usage=records.Usage(turns=3),
        sources=[source("S1", "https://a.example/x", "A page")],
        source_versions=[version("va", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", "map text", "va")],
        map=draft,
    )
    update = merge.merge_results(state, [result], limits)
    industry_map = update["map"]
    assert len(industry_map.segments) == 2
    assert len(industry_map.links) == 1
    # One participant per stage: the second segment is midstream, so
    # its company is admitted beside the first stage's one.
    assert len(industry_map.participants) == 2
    assert sum(1 for c in update["claims"].values() if c.map_ref) == 5


def test_relationship_needs_a_supported_parent_to_confirm():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1", verdict="unsupported", reason="r"
            )
        ],
        relationships=[
            records.RelationshipVerdict(
                relationship_id="R1", supported=True, reason="r"
            )
        ],
    )
    applied = merge.apply_review(state, review)
    assert applied["claims"]["C1"].review == "unsupported"
    assert not applied["relationships"]["R1"].confirmed
    assert any("parent claim" in line for line in applied["route_log"])
