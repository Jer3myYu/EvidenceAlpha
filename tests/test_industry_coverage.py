"""Coverage derivation and report status."""

from industry import coverage
from industry import records

NOW = "2026-09-07T00:00:00+00:00"


def evidence(eid, kind="passage"):
    return records.Evidence(
        id=eid,
        source_id="S1",
        source_version_id="v1" if kind != "snippet" else None,
        excerpt="x" * 50,
        locator="p1",
        kind=kind,
        extraction="html_text" if kind != "snippet" else "search_snippet",
        task_id="T1",
        retrieved_at=NOW,
    )


def claim(cid, review="supported", evidence_ids=("E1",), **kw):
    return records.Claim(
        id=cid,
        statement=cid,
        kind=kw.pop("kind", "fact"),
        evidence_ids=list(evidence_ids),
        review=review,
        material=True,
        **kw,
    )


def finding(fid, claim_ids, status="current"):
    return records.Finding(
        id=fid,
        conclusion="c",
        claim_ids=claim_ids,
        mechanism="m",
        implication="i",
        counterargument="ca",
        uncertainty="u",
        monitor="mo",
        material=True,
        status=status,
    )


def full_map():
    segments = [
        records.Segment(
            id="G1", name="up", stage="upstream", description="", claim_id="C1"
        ),
        records.Segment(
            id="G2",
            name="mid",
            stage="midstream",
            description="",
            claim_id="C2",
        ),
        records.Segment(
            id="G3",
            name="down",
            stage="downstream",
            description="",
            claim_id="C3",
        ),
    ]
    links = [
        records.Link(
            id="L1",
            from_segment="G1",
            to_segment="G2",
            what_flows="",
            claim_id="C4",
        ),
        records.Link(
            id="L2",
            from_segment="G2",
            to_segment="G3",
            what_flows="",
            claim_id="C5",
        ),
    ]
    participants = []
    n = 10
    for seg in ("G1", "G2", "G3"):
        for _ in range(2):
            n += 1
            participants.append(
                records.Participant(
                    id=f"P{n}",
                    name=f"co{n}",
                    segment_id=seg,
                    role="supplier",
                    supplies="mask blanks",
                    selection_rationale="",
                    claim_id=f"C{n}",
                )
            )
    return records.IndustryMap(
        segments=segments, links=links, participants=participants
    )


def full_state(evidence_kind="passage", review="supported"):
    industry_map = full_map()
    claims = {}
    for seg in industry_map.segments:
        claims[seg.claim_id] = claim(
            seg.claim_id, review, kind="map", map_ref=seg.id
        )
    for link in industry_map.links:
        claims[link.claim_id] = claim(
            link.claim_id, review, kind="map", map_ref=link.id
        )
    for part in industry_map.participants:
        claims[part.claim_id] = claim(
            part.claim_id, review, kind="map", map_ref=part.id, entity=part.name
        )
    claims["C30"] = claim("C30", review, topics=["boundary"])
    for i, topic in enumerate(records.QUESTION_4_TOPICS, start=31):
        claims[f"C{i}"] = claim(f"C{i}", review, topics=[topic])
    claims["C40"] = claim("C40", review, topics=["barrier"])
    claims["C41"] = claim(
        "C41",
        review,
        kind="company_claim",
        milestone="stable_production",
        milestone_date="2024-06",
        entity="co11",
    )
    claims["C42"] = claim("C42", review, topics=["global_china"], entity="HOYA")
    claims["C43"] = claim(
        "C43", review, topics=["global_china"], entity="清溢光电"
    )
    claims["C44"] = claim("C44", review, topics=["comparison"], entity="A")
    claims["C45"] = claim("C45", review, topics=["comparison"], entity="B")
    findings = {
        "F1": finding("F1", ["C31", "C32", "C33", "C34", "C40"]),
        "F2": finding("F2", ["C42", "C43", "C44", "C45"]),
    }
    relationships = {
        "R1": records.Relationship(
            id="R1",
            from_entity="co11",
            to_entity="co13",
            relation="supplies",
            confirmed=True,
            claim_id="C11",
            review="supported",
        )
    }
    return {
        "map": industry_map,
        "claims": claims,
        "evidence": {"E1": evidence("E1", evidence_kind)},
        "findings": findings,
        "relationships": relationships,
        "issues": {},
    }


def statuses(cov):
    return {c.question: c.status for c in cov}


def test_everything_supported_and_context_backed_is_complete():
    state = full_state()
    cov = coverage.derive(state, None)
    assert all(s == "covered" for s in statuses(cov).values())
    assert coverage.report_status(cov, state) == "complete"


def test_snippet_only_evidence_caps_central_questions_at_partial():
    state = full_state(evidence_kind="snippet")
    cov = statuses(coverage.derive(state, None))
    assert all(cov[q] == "partial" for q in records.CENTRAL_QUESTIONS)
    assert cov[8] == "covered"
    assert coverage.report_status(coverage.derive(state, None), state) == (
        "complete_with_limitations"
    )


def test_qualified_claims_cannot_complete_central_questions():
    state = full_state(review="qualified")
    cov = statuses(coverage.derive(state, None))
    assert all(cov[q] == "partial" for q in records.CENTRAL_QUESTIONS)


def test_unavailable_relationship_caps_question_3():
    state = full_state()
    state["relationships"] = {}
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="unavailable:relationships",
            category="unavailable",
            severity="material",
            target="relationships",
            requested_action="research",
        )
    }
    cov = coverage.derive(state, None)
    assert statuses(cov)[3] == "partial"
    assert "caps at partial" in [c for c in cov if c.question == 3][0].note


def test_missing_economics_subtopic_is_partial_and_uncovered_when_thin():
    state = full_state()
    del state["claims"]["C34"]  # bargaining power
    state["findings"]["F1"] = finding("F1", ["C31", "C32", "C33", "C40"])
    assert statuses(coverage.derive(state, None))[4] == "partial"
    for cid in ("C31", "C32", "C33"):
        del state["claims"][cid]
    state["findings"]["F1"] = finding("F1", ["C40"])
    assert statuses(coverage.derive(state, None))[4] == "uncovered"
    assert (
        coverage.report_status(coverage.derive(state, None), state)
        == "incomplete"
    )


def test_lead_can_lower_but_not_raise():
    state = full_state()
    proposal = records.LeadAssessment(
        coverage=[
            records.CoverageProposal(question=1, status="partial", note="thin"),
            records.CoverageProposal(question=8, status="covered"),
        ]
    )
    del state["claims"]["C1"]  # question 1 truly partial now
    cov = {c.question: c for c in coverage.derive(state, proposal)}
    assert cov[1].status == "partial" and cov[1].lead_status == "partial"
    assert "lead: thin" in cov[1].note
    # A generous lead cannot raise a derived status.
    state2 = full_state()
    del state2["findings"]["F1"]
    del state2["findings"]["F2"]
    generous = records.LeadAssessment(
        coverage=[records.CoverageProposal(question=8, status="covered")]
    )
    assert {c.question: c.status for c in coverage.derive(state2, generous)}[
        8
    ] == "uncovered"


def test_open_material_issue_on_central_claim_is_incomplete():
    state = full_state()
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="contradiction:C31",
            category="contradiction",
            severity="material",
            target="C31",
            requested_action="acquire",
        )
    }
    cov = coverage.derive(state, None)
    assert coverage.report_status(cov, state) == "incomplete"
    state["issues"]["I1"] = state["issues"]["I1"].model_copy(
        update={"severity": "minor"}
    )
    assert coverage.report_status(cov, state) == "complete"


def test_central_finding_on_contradicted_claim_is_incomplete():
    state = full_state()
    state["claims"]["C40"] = state["claims"]["C40"].model_copy(
        update={"review": "contradicted"}
    )
    cov = coverage.derive(state, None)
    assert (
        statuses(cov)[5] == "uncovered"
        or coverage.report_status(cov, state) == "incomplete"
    )
    assert coverage.report_status(cov, state) == "incomplete"


def test_stale_findings_do_not_count():
    state = full_state()
    state["findings"]["F1"] = finding(
        "F1", ["C31", "C32", "C33", "C34", "C40"], status="stale"
    )
    cov = statuses(coverage.derive(state, None))
    assert cov[4] == "uncovered"


def test_participants_without_supply_or_buy_do_not_complete_question_3():
    state = full_state()
    industry_map = state["map"]
    stripped = [
        p.model_copy(update={"supplies": None, "buys": None})
        for p in industry_map.participants
    ]
    state["map"] = industry_map.model_copy(update={"participants": stripped})
    assert statuses(coverage.derive(state, None))[3] == "partial"
