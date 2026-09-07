"""Deterministic merge, review application, invalidation, issues."""

from industry import budget
from industry import calc
from industry import merge
from industry import records
from industry import report

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
    assert any(
        "material quota of q4 reached" in line for line in update["route_log"]
    )


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


def test_material_partitions_are_disjoint_and_fixed_at_admission():
    limits = records.Limits(
        map_segments=1,
        map_links=1,
        map_participants_per_stage=1,
        material_per_question=1,
        material_other=1,
    )
    claims = {}

    def add(cid, questions, partition, map_ref=None):
        claims[cid] = records.Claim(
            id=cid,
            statement=cid,
            kind="map" if map_ref else "fact",
            questions=questions,
            map_ref=map_ref,
            material=True,
            partition=partition,
        )

    add("C1", [1], "map:segment", map_ref="G1")
    assert not merge.admit_material(claims, limits, "map:segment")
    assert merge.admit_material(claims, limits, "map:link")
    assert merge.admit_material(claims, limits, "map:participant:upstream")
    add("C2", [3], "map:participant:upstream", map_ref="P1")
    assert not merge.admit_material(claims, limits, "map:participant:upstream")
    assert merge.admit_material(claims, limits, "map:participant:midstream")
    # Q4 and Q5 are untouched by the full map and a full Q1.
    add("C3", [1], "q1")
    assert not merge.admit_material(claims, limits, "q1")
    assert merge.admit_material(claims, limits, "q4")
    add("C4", [4], "q4")
    # A derived claim counts against Q4 too: overflow is non-material.
    assert not merge.admit_material(claims, limits, "q4")
    assert merge.admit_material(claims, limits, "other")
    # A repeat adding Q1 to the Q4 claim does not move it into Q1.
    claims["C4"] = claims["C4"].model_copy(update={"questions": [1, 4]})
    assert merge.material_partition(claims["C4"]) == "q4"
    assert (
        sum(1 for c in claims.values() if merge.material_partition(c) == "q1")
        == 1
    )
    assert limits.material_claims() == (1 + 1 + 4) + 5 * 1 + 1


def test_map_items_beyond_their_sub_quota_are_not_added():
    state = base_state()
    limits = records.Limits(**{**LIMITS.model_dump(), "map_segments": 1})
    draft = records.MapDraft(
        segments=[
            records.SegmentDraft(
                key=f"s{n}",
                name=f"segment {n}",
                stage="upstream",
                description="d",
                evidence_refs=["E1"],
            )
            for n in range(2)
        ]
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
    map_claims = [c for c in update["claims"].values() if c.map_ref]
    assert len(map_claims) == 1 and map_claims[0].partition == "map:segment"
    assert len(update["map"].segments) == 1
    assert any("segments is the cap" in line for line in update["route_log"])


def test_repeat_cannot_promote_a_claim_past_its_partition():
    state = base_state()
    limits = records.Limits(
        **{**LIMITS.model_dump(), "material_per_question": 1}
    )
    first = records.TaskResult(
        attempt_id="T1.1",
        task_id="T1",
        status="done",
        usage=records.Usage(turns=3),
        sources=[source("S1", "https://a.example/x", "A page")],
        source_versions=[version("va", "S1", "hash-a")],
        evidence=[evidence("E1", "S1", "fact text", "va")],
        findings=[
            records.FindingDraft(
                statement="fact A",
                material=True,
                evidence_refs=["E1"],
                questions=[4],
            ),
            records.FindingDraft(
                statement="fact B",
                material=True,
                evidence_refs=["E1"],
                questions=[4],
            ),
            # A repeat of B, now also claiming Q1: it joins B (non-material,
            # Q4 full) and may not become material through Q1.
            records.FindingDraft(
                statement="fact B",
                material=True,
                evidence_refs=["E1"],
                questions=[1, 4],
            ),
        ],
    )
    update = merge.merge_results(state, [first], limits)
    by_text = {c.statement: c for c in update["claims"].values()}
    assert by_text["fact A"].material and by_text["fact A"].partition == "q4"
    assert not by_text["fact B"].material
    assert by_text["fact B"].questions == [1, 4]
    assert merge.material_partition(by_text["fact B"]) == "q4"


def test_relationships_are_revoked_when_the_parent_stops_being_supported():
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    supported = records.ClaimReview(
        claims=[
            records.ClaimVerdict(claim_id="C1", verdict="supported", reason="r")
        ],
        relationships=[
            records.RelationshipVerdict(
                relationship_id="R1", supported=True, reason="r"
            )
        ],
    )
    state.update(merge.apply_review(state, supported))
    assert state["relationships"]["R1"].confirmed
    # A later batch rejects the parent without repeating the verdict.
    rejected = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1", verdict="unsupported", reason="r"
            )
        ]
    )
    later = merge.apply_review(state, rejected)
    assert not later["relationships"]["R1"].confirmed
    assert any("unconfirmed" in line for line in later["route_log"])
    # And a corrected (re-versioned) parent takes its relationships too.
    state.update(merge.apply_review(state, supported))
    corrected = merge.invalidate_claim(state, "C1", statement="corrected")
    assert corrected["claims"]["C1"].review == "unreviewed"
    assert not corrected["relationships"]["R1"].confirmed
    assert not merge.relationship_live(
        state["relationships"]["R1"], corrected["claims"]
    )


def test_each_unsupported_unit_is_its_own_issue_and_all_are_redacted():
    # C0 round 13, finding 1: two uncited sentences in one section used
    # to collapse into one issue, and the first was delivered as fact.
    first_unit = "本行业需求每年增长99%。"
    second_unit = "行业利润率永久保持88%。"
    issues, first = merge.open_issue(
        {}, "unsupported", "material", "s1", "edit", "a", text=first_unit
    )
    issues, second = merge.open_issue(
        issues, "unsupported", "material", "s1", "edit", "b", text=second_unit
    )
    assert first.id != second.id and first.key != second.key
    assert first.key.startswith("unsupported:s1#")
    # The same unit repeats under the same key and keeps its attempts.
    issues[first.id] = first.model_copy(update={"attempts": 1})
    issues, again = merge.open_issue(
        issues, "unsupported", "material", "s1", "edit", "c", text=first_unit
    )
    assert again.id == first.id and again.attempts == 1
    # A section-wide problem (no unit) is a third, distinguishable issue.
    issues, wide = merge.open_issue(
        issues, "unsupported", "material", "s1", "remove", "cites unknown"
    )
    assert wide.key == "unsupported:s1" and wide.id not in (first.id, second.id)
    open_issues = [i for i in issues.values() if i.status == "open"]
    text = report.redact(
        f"{first_unit}{second_unit}结论 [C1]。", open_issues, "s1", "[removed]"
    )
    assert "99%" not in text and "88%" not in text
    assert text == "[removed][removed]结论 [C1]。"
    state = {
        "sections": [
            records.Section(id="s1", title="t", text="x", claim_ids=[])
        ],
        "issues": issues,
    }
    assert report.unremovable_section_issues(state) == [wide]


def test_quantity_value_must_be_the_number_written():
    # C0 round 13, finding 2: value 520 written as "52" reached calc.
    state = base_state()
    result = result_t2()
    result.findings[0] = result.findings[0].model_copy(
        update={
            "quantity": records.Quantity(
                value=520, unit="亿元", period="2024", as_written="52"
            )
        }
    )
    update = merge.merge_results(state, [result], LIMITS)
    claim = update["claims"]["C1"]
    assert claim.quantity is None
    assert "quantity_value_mismatch" in claim.limitations
    assert any("not the number written" in l for l in update["route_log"])
    consistent = merge.quantity_consistent
    assert consistent(
        records.Quantity(value=1546.1, unit="亿美元", as_written="1,546.1")
    )
    assert consistent(
        records.Quantity(value=52, unit="亿元", as_written="52亿元")
    )
    assert consistent(
        records.Quantity(value=-3.5, unit="%", as_written="-3.5%")
    )
    assert not consistent(
        records.Quantity(value=52, unit="亿元", as_written="五十二亿元")
    )
    assert not consistent(
        records.Quantity(value=52, unit="%", as_written="52%至60%")
    )
    assert not consistent(
        records.Quantity(value=5200, unit="万元", as_written="52")
    )


def test_review_reason_persists_on_the_reviewed_version_and_resets():
    # C0 round 13, finding 3: a qualified verdict's reason was dropped.
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    reason = "merchant market only, excludes captive production"
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1",
                verdict="qualified",
                reason=reason,
                topics_supported=["demand_driver"],
            )
        ]
    )
    state.update(merge.apply_review(state, review))
    claim = state["claims"]["C1"]
    assert claim.review == "qualified" and claim.review_reason == reason
    # A later batch that does not name C1 leaves the reason in place.
    later = merge.apply_review(state, records.ClaimReview())
    assert later["claims"]["C1"].review_reason == reason
    # A corrected claim is a new version, reviewed again from scratch.
    corrected = merge.invalidate_claim(state, "C1", statement="corrected")
    assert corrected["claims"]["C1"].review == "unreviewed"
    assert corrected["claims"]["C1"].review_reason is None
    # A meaning-changing repeat resets it too.
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    richer = result_t2().model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    richer.findings[0] = richer.findings[0].model_copy(
        update={"dimension": "revenue"}
    )
    update = merge.merge_results(state, [richer], LIMITS)
    repeated = update["claims"]["C1"]
    assert repeated.version == 2 and repeated.review == "unreviewed"
    assert repeated.review_reason is None


def test_scale_words_must_be_carried_by_the_unit():
    # C0 round 14, finding 2: "52 million" with unit "USD" passed the
    # guard and a share came out as 0.000052%.
    consistent = merge.quantity_consistent
    assert not consistent(
        records.Quantity(value=52, unit="USD", as_written="52 million")
    )
    assert consistent(
        records.Quantity(value=52, unit="USD million", as_written="52 million")
    )
    assert consistent(
        records.Quantity(value=52, unit="亿元", as_written="52亿")
    )
    assert consistent(records.Quantity(value=60, unit="%", as_written="60%"))
    assert consistent(records.Quantity(value=52, unit="亿元", as_written="52"))
    assert not consistent(
        records.Quantity(value=52, unit="元", as_written="52亿")
    )


def test_qualified_claim_without_a_reason_is_not_citable_until_reviewed():
    # C0 round 14, finding 3: a claim persisted as qualified before
    # review_reason existed stayed citable without its restriction.
    old = records.Claim(
        id="C1",
        statement="85% of the global market",
        kind="fact",
        material=True,
    ).model_copy(update={"review": "qualified"})
    assert not old.is_reviewed() and old.needs_review()
    state = {"claims": {"C1": old}, "sections": []}
    assert not merge.relationship_live(
        records.Relationship(
            id="R1",
            from_entity="a",
            to_entity="b",
            relation="supplies",
            confirmed=True,
            claim_id="C1",
        ),
        state["claims"],
    )
    problems = report.check_citations(
        [records.Section(id="s", title="t", text="x [C1]", claim_ids=["C1"])],
        state["claims"],
    )
    assert any("without its qualification" in p.description for p in problems)
    # A qualified verdict with an empty reason leaves an explicit marker.
    applied = merge.apply_review(
        state,
        records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1", verdict="qualified", reason=" "
                )
            ]
        ),
    )
    reviewed = applied["claims"]["C1"]
    assert (
        reviewed.is_reviewed()
        and "without a stated reason" in reviewed.review_reason
    )
    assert any("qualified without a reason" in l for l in applied["route_log"])


def test_omitting_the_scale_from_a_quantity_is_refused():
    # C1 round 1, finding 3: "52" copied from "52 million USD" with unit
    # "USD" is internally consistent and a million-fold wrong.
    state = base_state()
    excerpt = "Acme 2024 revenue was 52 million USD, up 12%."
    result = result_t2(excerpt=excerpt).model_copy(
        update={"evidence": [evidence("E1", "S1", excerpt, "va")]}
    )
    result.findings[0] = result.findings[0].model_copy(
        update={
            "quantity": records.Quantity(
                value=52, unit="USD", period="2024", as_written="52"
            )
        }
    )
    update = merge.merge_results(state, [result], LIMITS)
    claim = update["claims"]["C1"]
    assert claim.quantity is None
    assert "quantity_scale_omitted" in claim.limitations
    assert any("scales" in line for line in update["route_log"])
    # The same number with the scale in the unit is admitted.
    carried = result.model_copy()
    carried.findings[0] = result.findings[0].model_copy(
        update={
            "quantity": records.Quantity(
                value=52,
                unit="USD million",
                period="2024",
                as_written="52 million",
            )
        }
    )
    kept = merge.merge_results(base_state(), [carried], LIMITS)
    assert kept["claims"]["C1"].quantity is not None
    # And the excerpt's own scale is only read beside the number.
    check = merge.quantity_scale_in_excerpts
    assert check(
        records.Quantity(value=52, unit="USD", as_written="52"),
        ["Acme 2024 revenue was 52 USD"],
    )
    assert check(
        records.Quantity(value=52, unit="亿元", as_written="52"),
        ["营业收入52亿元"],
    )
    assert not check(
        records.Quantity(value=52, unit="元", as_written="52"),
        ["营业收入52亿元"],
    )


def test_a_unit_carries_its_scale_in_any_order_and_as_a_symbol():
    # C1 round 1, finding 5: valid notation was rejected, which loses
    # evidence as silently as accepting a wrong scale delivers it.
    consistent = merge.quantity_consistent
    assert consistent(
        records.Quantity(value=52, unit="USD million", as_written="52 million")
    )
    assert consistent(
        records.Quantity(
            value=52, unit="USD million", as_written="52 million USD"
        )
    )
    assert consistent(records.Quantity(value=52, unit="USD", as_written="$52"))
    assert consistent(
        records.Quantity(value=52, unit="亿元", as_written="52亿")
    )
    assert consistent(records.Quantity(value=60, unit="%", as_written="60%"))
    # A scale the unit does not carry is still refused (C0 round 14).
    assert not consistent(
        records.Quantity(value=52, unit="USD", as_written="52 million")
    )
    assert not consistent(
        records.Quantity(value=52, unit="USD", as_written="52 tonnes")
    )


def test_a_repeat_keeps_the_limitation_its_quantity_was_dropped_with():
    # C1 round 1, finding 5: folding a repeat left the record of the
    # drop only in the route log.
    state = base_state()
    state.update(
        merge.merge_results(state, [result_t2(quantity=False)], LIMITS)
    )
    assert state["claims"]["C1"].limitations == []
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    repeat = result_t2(quantity=False).model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    repeat.findings[0] = repeat.findings[0].model_copy(
        update={
            "quantity": records.Quantity(
                value=999, unit="亿元", period="2024", as_written="52亿元"
            )
        }
    )
    update = merge.merge_results(state, [repeat], LIMITS)
    claim = update["claims"]["C1"]
    assert claim.quantity is None
    assert "quantity_value_mismatch" in claim.limitations


def test_the_same_attempt_twice_in_one_batch_is_folded_once():
    # C1 round 1, finding 7: filtering happened before the fold, so a
    # duplicate in the same batch was merged twice.
    state = base_state()
    result = result_t2()
    once = merge.merge_results(state, [result], LIMITS)
    twice = merge.merge_results(state, [result, result], LIMITS)
    assert twice["merged"] == once["merged"] == ["T2.1"]
    assert len(twice["evidence"]) == len(once["evidence"])
    assert len(twice["claims"]) == len(once["claims"])
    assert any("duplicate result" in line for line in twice["route_log"])


def derived_state():
    """Two measured claims, a calculation, and what rests on its result."""
    quantity = records.Quantity(
        value=52, unit="亿元", period="2024", as_written="52亿元"
    )
    whole = records.Quantity(
        value=100, unit="亿元", period="2024", as_written="100亿元"
    )
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="Acme 2024 revenue was 52亿元",
            kind="fact",
            evidence_ids=["E1"],
            quantity=quantity,
            review="supported",
            material=True,
            partition="q4",
            questions=[4],
        ),
        "C2": records.Claim(
            id="C2",
            statement="the 2024 market was 100亿元",
            kind="fact",
            evidence_ids=["E1"],
            quantity=whole,
            review="supported",
            material=True,
            partition="q4",
            questions=[4],
        ),
        "C3": records.Claim(
            id="C3",
            statement="share: 52.0 % (computed from C1, C2)",
            kind="derived",
            evidence_ids=["E1"],
            calculation_id="K1",
            review="supported",
            material=True,
            partition="q4",
            questions=[4],
            origin="K1",
        ),
    }
    calculation = records.Calculation(
        id="K1",
        kind="share",
        label="Acme share",
        inputs=[
            records.CalcInput(claim_id="C1", value=52, unit="亿元"),
            records.CalcInput(claim_id="C2", value=100, unit="亿元"),
        ],
        formula="52 / 100 * 100",
        result=52.0,
        unit="%",
        status="ok",
    )
    return {
        "claims": claims,
        "calculations": {"K1": calculation},
        "findings": {
            "F1": records.Finding(
                id="F1",
                conclusion="Acme leads",
                claim_ids=["C3"],
                mechanism="m",
                implication="i",
                counterargument="c",
                uncertainty="u",
                monitor="mo",
                questions=[8],
            )
        },
        "sections": [
            records.Section(
                id="s1",
                title="t",
                text="Acme holds 52% [C3].",
                claim_ids=["C3"],
            )
        ],
        "relationships": {
            "R1": records.Relationship(
                id="R1",
                from_entity="Acme",
                to_entity="Beta",
                relation="supplies",
                confirmed=True,
                evidence_ids=["E1"],
                claim_id="C1",
                review="supported",
            )
        },
    }


def test_correcting_a_claim_invalidates_what_was_computed_from_it():
    # C1 round 1, finding 1: the derived claim, its calculation, the
    # finding, the section and the relationship all kept their approval
    # after the input changed.
    state = derived_state()
    update = merge.invalidate_claim(
        state,
        "C1",
        quantity=records.Quantity(
            value=26, unit="亿元", period="2024", as_written="26亿元"
        ),
    )
    assert update["claims"]["C1"].review == "unreviewed"
    derived = update["claims"]["C3"]
    assert derived.review == "unreviewed" and derived.review_reason is None
    assert derived.version == 2 and derived.supersedes == "C3@1"
    assert not derived.is_reviewed() and derived.needs_review()
    assert update["calculations"]["K1"].status == "error"
    assert "stale_input" in update["calculations"]["K1"].message
    assert update["findings"]["F1"].status == "stale"
    assert update["sections"][0].stale
    assert not update["relationships"]["R1"].confirmed
    # And the stale result is no longer an input to a new calculation.
    assert "C3" not in calc.inputs_from_claims(update["claims"])


def test_rejecting_an_input_invalidates_what_was_computed_from_it():
    # C1 round 1, finding 1: the same leak through the review path.
    state = derived_state()
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1", verdict="unsupported", reason="no source"
            )
        ]
    )
    update = merge.apply_review(state, review)
    assert update["claims"]["C3"].review == "unreviewed"
    assert update["calculations"]["K1"].status == "error"
    assert update["findings"]["F1"].status == "stale"
    assert update["sections"][0].stale
    assert not update["relationships"]["R1"].confirmed


def test_requalifying_an_input_invalidates_what_was_computed_from_it():
    # C1 round 1, finding 1: a restriction added after the fact left the
    # derived number carrying the old, unrestricted qualification.
    state = derived_state()
    review = records.ClaimReview(
        claims=[
            records.ClaimVerdict(
                claim_id="C1",
                verdict="qualified",
                reason="merchant market only",
            )
        ]
    )
    update = merge.apply_review(state, review)
    assert update["claims"]["C1"].review_reason == "merchant market only"
    assert update["claims"]["C3"].review == "unreviewed"
    assert update["calculations"]["K1"].status == "error"
    # A verdict that changes nothing leaves the dependants alone.
    state = derived_state()
    again = merge.apply_review(
        state,
        records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1", verdict="supported", reason=""
                )
            ]
        ),
    )
    assert again["claims"]["C3"].review == "supported"
    assert again["calculations"]["K1"].status == "ok"


def test_a_repeat_that_changes_meaning_revokes_its_relationship():
    # C1 round 1, finding 1: the parent was re-versioned and unreviewed
    # but its relationship stayed confirmed, and supporting the new
    # version made it live again without a relationship judgement.
    state = base_state()
    state.update(
        merge.merge_results(state, [result_t2(quantity=False)], LIMITS)
    )
    state.update(
        merge.apply_review(
            state,
            records.ClaimReview(
                claims=[
                    records.ClaimVerdict(
                        claim_id="C1", verdict="supported", reason="ok"
                    )
                ],
                relationships=[
                    records.RelationshipVerdict(
                        relationship_id="R1", supported=True, reason="ok"
                    )
                ],
            ),
        )
    )
    assert state["relationships"]["R1"].confirmed
    state["tasks"]["T3"] = task("T3")
    state["attempts"]["T3.1"] = attempt("T3.1", "T3")
    richer = result_t2().model_copy(
        update={"attempt_id": "T3.1", "task_id": "T3"}
    )
    state.update(merge.merge_results(state, [richer], LIMITS))
    assert state["claims"]["C1"].version == 2
    assert state["claims"]["C1"].review == "unreviewed"
    assert not state["relationships"]["R1"].confirmed
    assert state["relationships"]["R1"].review == "unreviewed"
    # Supporting the new version alone does not bring the relation back.
    state.update(
        merge.apply_review(
            state,
            records.ClaimReview(
                claims=[
                    records.ClaimVerdict(
                        claim_id="C1", verdict="supported", reason="ok"
                    )
                ]
            ),
        )
    )
    assert not state["relationships"]["R1"].confirmed
    assert not merge.relationship_live(
        state["relationships"]["R1"], state["claims"]
    )


def test_a_qualification_without_a_reason_revokes_its_relationship():
    # C1 round 1, finding 4: revocation still compared review directly.
    state = derived_state()
    state["claims"]["C1"] = state["claims"]["C1"].model_copy(
        update={"review": "qualified", "review_reason": None}
    )
    relationships, log = merge.revoke_orphaned_relationships(
        state["relationships"], state["claims"]
    )
    assert not relationships["R1"].confirmed
    assert log and "no longer supported" in log[0]


def test_a_stale_derived_claim_cannot_be_re_approved_by_review():
    # C1 round 2, finding 1: the derived claim kept its old statement
    # and quantity, entered the review queue, and a supported verdict
    # made it citable and calculation-eligible again while its own
    # calculation was still an error.
    state = derived_state()
    state["calculations"]["K1"] = state["calculations"]["K1"].model_copy(
        update={
            "request": records.CalcRequest(
                kind="share",
                label="Acme share",
                numerator_claim_id="C1",
                denominator_claim_id="C2",
            )
        }
    )
    state.update(
        merge.invalidate_claim(
            state,
            "C1",
            quantity=records.Quantity(
                value=26, unit="亿元", period="2024", as_written="26亿元"
            ),
        )
    )
    assert state["calculations"]["K1"].status == "error"
    assert not merge.calculation_current(
        state["claims"]["C3"], state["calculations"]
    )
    applied = merge.apply_review(
        state,
        records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1", verdict="supported", reason="corrected"
                ),
                records.ClaimVerdict(
                    claim_id="C3", verdict="supported", reason="looks fine"
                ),
            ]
        ),
    )
    derived = applied["claims"]["C3"]
    assert derived.review == "unreviewed" and not derived.is_reviewed()
    assert "C3" not in calc.inputs_from_claims(
        applied["claims"], applied["calculations"]
    )
    assert any("verdict on C3 ignored" in l for l in applied["route_log"])
    # Recomputation is the only way back, and it writes a new version.
    claims, calculations, log = calc.recompute_stale(
        applied["claims"], applied["calculations"]
    )
    assert calculations["K1"].status == "ok"
    assert claims["C3"].version == 3 and claims["C3"].quantity.value == 26.0
    assert claims["C3"].supersedes == "C3@2"
    assert log and "recomputed" in log[0]


def test_a_calculation_that_cannot_be_recomputed_stays_stopped():
    # The other half of finding 1: a permanently rejected input must
    # not quietly restore the derived claim either.
    state = derived_state()
    state["calculations"]["K1"] = state["calculations"]["K1"].model_copy(
        update={
            "request": records.CalcRequest(
                kind="share",
                label="Acme share",
                numerator_claim_id="C1",
                denominator_claim_id="C2",
            )
        }
    )
    state.update(
        merge.apply_review(
            state,
            records.ClaimReview(
                claims=[
                    records.ClaimVerdict(
                        claim_id="C1",
                        verdict="unsupported",
                        reason="no source",
                    )
                ]
            ),
        )
    )
    claims, calculations, log = calc.recompute_stale(
        state["claims"], state["calculations"]
    )
    assert calculations["K1"].status == "error"
    assert not claims["C3"].is_reviewed()
    assert not log


def test_the_scale_governing_the_number_is_read_wherever_it_is_written():
    # C1 round 2, findings 2 and 6: the check only looked after the
    # number and matched digits inside a longer number, and it rejected
    # a valid quantity because another figure elsewhere had a scale.
    def usd(as_written="52"):
        return records.Quantity(
            value=52, unit="USD", period="2024", as_written=as_written
        )

    def supported(quantity, excerpt):
        return merge.quantity_in_excerpts(
            quantity, [excerpt]
        ) and merge.quantity_scale_in_excerpts(quantity, [excerpt])

    # The reviewer's four rows.
    assert not supported(usd(), "Acme 2024 revenue was 52 million USD")
    assert not supported(usd(), "Acme 2024 revenue (USD million): 52")
    assert not supported(usd(), "Acme 2024 revenue was 52m USD")
    assert not supported(usd(), "Acme revenue was 152 million USD")
    # Digits inside a longer number are not the number at all.
    assert not merge.quantity_in_excerpts(
        usd(), ["Acme revenue was 152 million USD"]
    )
    # Nearby variants: a scale after the unit, and Chinese notation.
    assert not supported(usd(), "Acme 2024 revenue was 52 USD million")
    assert not supported(
        records.Quantity(value=52, unit="元", as_written="52"),
        "营业收入52亿元",
    )
    # And valid ones are still admitted.
    assert supported(usd(), "Acme 2024 revenue was 52 USD")
    assert supported(
        records.Quantity(value=52, unit="USD million", as_written="52"),
        "Acme 2024 revenue was 52 million USD",
    )
    assert supported(
        records.Quantity(value=52, unit="亿元", as_written="52"),
        "同比上升12%至52亿元",
    )
    assert supported(
        records.Quantity(value=1546.1, unit="亿美元", as_written="1,546.1"),
        "市场规模为1,546.1亿美元",
    )
    # A different figure's scale does not reach back into this one.
    assert supported(
        usd(), "Acme revenue was 52 USD. Another firm sold 52 million units."
    )
    # Nor does an ordinary word that merely starts like an abbreviation.
    assert supported(usd(), "Acme sold 52 bags and 3 firms agreed")
    assert supported(usd(), "In autumn Acme sold 52 USD")


def test_invalidation_is_idempotent_and_ignores_semantic_no_ops():
    # C1 round 2, finding 5: repeating the cascade re-versioned the
    # dependant, correcting a claim to the value it already had
    # invalidated everything, and rewording a supported verdict's
    # reason withdrew the analysis resting on it.
    state = derived_state()
    first = merge.invalidate_claim(state, "C1", statement="corrected")
    assert first["claims"]["C3"].version == 2
    state.update(first)
    again = merge.cascade_changes(
        state, {"C1"}, state["claims"], state["relationships"]
    )
    assert again["claims"]["C3"].version == 2
    # A correction to the value already on record changes nothing.
    assert not merge.invalidate_claim(state, "C1", statement="corrected")
    # Rewording a supported verdict's reason is not a meaning change.
    state = derived_state()
    reworded = merge.apply_review(
        state,
        records.ClaimReview(
            claims=[
                records.ClaimVerdict(
                    claim_id="C1",
                    verdict="supported",
                    reason="confirmed against source",
                )
            ]
        ),
    )
    assert reworded["claims"]["C3"].review == "supported"
    assert reworded["calculations"]["K1"].status == "ok"


def test_limitations_never_accumulate_duplicates():
    # C1 round 2, finding 7: each conflicting repeat appended another
    # identical marker.
    state = base_state()
    state.update(merge.merge_results(state, [result_t2()], LIMITS))
    for number in (3, 4, 5):
        state["tasks"][f"T{number}"] = task(f"T{number}")
        state["attempts"][f"T{number}.1"] = attempt(
            f"T{number}.1", f"T{number}"
        )
        clashing = result_t2().model_copy(
            update={
                "attempt_id": f"T{number}.1",
                "task_id": f"T{number}",
            }
        )
        clashing.findings[0] = clashing.findings[0].model_copy(
            update={"entity": f"Other{number}"}
        )
        state.update(merge.merge_results(state, [clashing], LIMITS))
    limitations = state["claims"]["C1"].limitations
    assert limitations.count("conflicting_repeat:entity") == 1
    assert len(limitations) == len(set(limitations))
