"""Rendering and defaults of the single-call roles."""

import quantity_support as support
from industry import records
from industry import report
from industry import roles

NOW = "2026-09-07T00:00:00+00:00"


def test_language_and_defaults_are_deterministic():
    assert roles.detect_language("光掩模产业调研") == "zh"
    assert roles.detect_language("photomask industry") == "en"
    brief = roles.default_brief("光掩模产业调研")
    assert brief.language == "zh" and brief.mode == "brief"
    assert brief.geography.startswith("global")
    assert len(brief.required_questions) == 8 and brief.cutoff


def sample_state():
    version = records.SourceVersion(
        id="v1",
        source_id="S1",
        content_hash="h",
        blob_path="b",
        meta_path="m",
        final_url="u",
        content_type="text/html",
        size=1,
        retrieved_at=NOW,
        extraction_version="v2",
    )
    evidence = {
        "E1": records.Evidence(
            id="E1",
            source_id="S1",
            source_version_id="v1",
            excerpt="HOYA supplies mask blanks to TSMC.",
            locator="sec 2",
            kind="passage",
            extraction="html_text",
            task_id="T1",
            retrieved_at=NOW,
        ),
        "E2": records.Evidence(
            id="E2",
            source_id="S1",
            excerpt="snippet",
            locator="search snippet",
            kind="snippet",
            extraction="search_snippet",
            task_id="T1",
            retrieved_at=NOW,
        ),
    }
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="HOYA supplies TSMC",
            kind="fact",
            evidence_ids=["E1"],
            material=True,
            topics=["payer_flow"],
            questions=[3],
            quantity=support.bound(60, "%", "E1", "60%", scope="全球"),
        ),
        "C2": records.Claim(
            id="C2", statement="other", kind="fact", evidence_ids=["E2"]
        ),
    }
    relationships = {
        "R1": records.Relationship(
            id="R1",
            from_entity="HOYA",
            to_entity="TSMC",
            relation="supplies",
            evidence_ids=["E1"],
            claim_id="C1",
        ),
        "R2": records.Relationship(
            id="R2",
            from_entity="A",
            to_entity="B",
            relation="competes_with",
            evidence_ids=["E2"],
            claim_id="C2",
        ),
    }
    return {
        "brief": roles.default_brief("光掩模产业调研"),
        "sources": {
            "S1": records.Source(
                id="S1",
                canonical_url="https://a",
                title="A",
                kind="web_page",
                origin="primary",
            )
        },
        "source_versions": {"v1": version},
        "evidence": evidence,
        "claims": claims,
        "relationships": relationships,
    }


def test_relationships_render_bound_to_selected_claims():
    state = sample_state()
    text = roles.render_relationships(state, ["C1"], with_excerpts=True)
    assert (
        "[R1] HOYA --supplies--> TSMC (unreviewed; claim C1; evidence E1"
        in text
    )
    assert '[E1] passage @ sec 2: "HOYA supplies mask blanks to TSMC."' in text
    assert "[R2]" not in text
    everything = roles.render_relationships(state)
    assert (
        "[R1]" in everything
        and "[R2]" in everything
        and "@ sec 2" not in everything
    )


def test_claims_render_excerpts_with_provenance_and_omit_visibly():
    state = sample_state()
    text = roles.render_claims(state, None, True, 10_000)
    assert (
        "[C1] (kind=fact; review=unreviewed; material; quantity=60% % (全球)"
        in text
    )
    assert (
        "[E1] passage from A (https://a; primary; sec 2; retrieved 2026-09-07)"
        in text
    )
    short = roles.render_claims(state, None, True, 200)
    assert "Omitted for length" in short and "C2" in short


def test_verifier_prompt_binds_relationships_to_excerpts():
    state = sample_state()
    # Build the description the way review_claims does, without a model.
    text = roles.render_relationships(state, ["C1"], with_excerpts=True)
    assert "claim C1" in text and "sec 2" in text
    assert "co-mention" in roles.VERIFIER_PROMPT


def test_editor_and_analyst_see_reviewed_lineage_only():
    industry_map = records.IndustryMap(
        segments=[
            records.Segment(
                id="G1",
                name="上游",
                stage="upstream",
                description="d",
                claim_id="C1",
            ),
            records.Segment(
                id="G2",
                name="中游",
                stage="midstream",
                description="d",
                claim_id="C2",
            ),
        ],
        participants=[
            records.Participant(
                id="P1",
                name="菲利华",
                segment_id="G1",
                role="supplier",
                selection_rationale="r",
                claim_id="C3",
            )
        ],
    )
    claims = {
        "C1": records.Claim(
            id="C1",
            statement="s1",
            kind="map",
            review="supported",
            map_ref="G1",
        ),
        "C2": records.Claim(
            id="C2",
            statement="s2",
            kind="map",
            review="unreviewed",
            map_ref="G2",
        ),
        "C3": records.Claim(
            id="C3",
            statement="s3",
            kind="map",
            review="unreviewed",
            map_ref="P1",
        ),
        "C4": records.Claim(
            id="C4", statement="s4", kind="fact", review="supported"
        ),
    }
    text = roles.render_map(industry_map, claims)
    assert "G1" in text and "G2" not in text and "菲利华" not in text
    assert "2 map items" in text
    state = {
        "brief": records.Brief(industry="光掩模"),
        "map": industry_map,
        "claims": claims,
        "relationships": {
            "R1": records.Relationship(
                id="R1",
                claim_id="C4",
                from_entity="a",
                to_entity="b",
                relation="supplies",
                confirmed=True,
            ),
            "R2": records.Relationship(
                id="R2",
                claim_id="C2",
                from_entity="a",
                to_entity="c",
                relation="supplies",
            ),
        },
        "findings": {
            "F1": records.Finding(
                id="F1",
                conclusion="ok",
                claim_ids=["C4"],
                mechanism="m",
                implication="i",
                counterargument="c",
                uncertainty="u",
                monitor="w",
            ),
            "F2": records.Finding(
                id="F2",
                conclusion="leaky",
                claim_ids=["C4", "C2"],
                mechanism="m",
                implication="i",
                counterargument="c",
                uncertainty="u",
                monitor="w",
            ),
        },
    }
    draft = roles.draft_description(state, "write")
    assert "[R1]" in draft and "[R2]" not in draft
    assert "[F1]" in draft and "[F2]" not in draft
    assert "s2" not in draft and "s3" not in draft
    analysis = roles.analysis_description(state, "")
    assert (
        "[C2]" not in analysis
        and "[F2]" not in analysis
        and "[R2]" not in analysis
    )
    final = roles.final_review_description(state)
    assert "[F2]" not in final


def test_claim_line_carries_value_period_and_qualification_to_every_reader():
    # C0 round 13, findings 2 and 3: the verifier never saw the numeric
    # value, and a qualification never reached the Editor or the final
    # verifier.
    state = sample_state()
    claims = state["claims"]
    claims["C1"] = claims["C1"].model_copy(
        update={
            "review": "qualified",
            "review_reason": "merchant market only, excludes captive",
            "quantity": support.bound(
                60, "%", "E1", "60%", period="2024", scope="全球"
            ),
        }
    )
    line = roles.render_claims(state, ["C1"], True, 10_000)
    assert "quantity=60% % (全球) [value=60, period=2024]" in line
    assert "qualification=merchant market only, excludes captive" in line
    for text in (
        roles.review_description(state, ["C1"]),
        roles.analysis_description(state, "note"),
        roles.draft_description(state, "write"),
        roles.final_review_description(state),
    ):
        assert "[value=60, period=2024]" in text
        assert "qualification=merchant market only" in text
    assert "qualification= restriction" in roles.draft_description(state, "w")
    assert "qualification= restriction" in roles.final_review_description(state)
    claims["C1"] = claims["C1"].model_copy(
        update={"review": "supported", "review_reason": "E1 states it"}
    )
    assert "qualification=" not in roles.render_claims(
        state, ["C1"], False, 9_999
    )


def test_an_empty_reviewed_selection_renders_no_claims():
    # C1 round 9, finding 1: `claim_ids or claims` made an empty
    # selection mean "every claim", so the analyst, the editor and the
    # final review saw unreviewed claims whenever none were citable yet.
    state = {
        "claims": {
            "C1": records.Claim(
                id="C1",
                statement="an unreviewed claim",
                kind="fact",
                review="unreviewed",
                material=True,
                partition="q4",
                questions=[4],
            )
        },
        "calculations": {},
    }
    assert roles.reviewed_claim_ids(state) == []
    assert roles.render_claims(state, [], False, 10_000) == "Claims: none."
    assert "C1" in roles.render_claims(state, None, False, 10_000)


def test_the_final_verifier_sees_the_draft_delivery_publishes():
    # Headline live run 4 (thread b9632d7d, 2026-09-08): the verifier was
    # shown render_sections() alone, while delivery appended the
    # limitations and the question coverage. It reported the limitations
    # section missing from a report that has one, three times, as
    # material issues.
    state = sample_state()
    state["sections"] = [
        records.Section(
            id="scope",
            title="范围",
            text="具体缺口见文末“局限性”。",
            claim_ids=[],
        )
    ]
    state["issues"] = {
        "I1": records.Issue(
            id="I1",
            key="missing_evidence:Q4",
            category="missing_evidence",
            severity="material",
            target="Q4",
            requested_action="research",
            description="Q4 uncovered: 需求驱动的议价机制",
        )
    }
    coverage = [
        records.Coverage(question=4, status="uncovered"),
        records.Coverage(question=5, status="partial"),
    ]
    state["coverage"] = coverage
    text = roles.final_review_description(state)
    assert "局限性" in text
    assert "Q4 uncovered: 需求驱动的议价机制" in text
    assert "问题覆盖" in text
    assert "Q4: uncovered" in text and "Q5: partial" in text
    # One authoritative definition: the very lines delivery publishes.
    delivered = report.render(state, coverage, "incomplete")
    for line in report.appendices(state, coverage):
        if line.strip():
            assert line in delivered
            assert line in text


def test_the_report_scope_line_is_rendered_and_never_written():
    # Plan revision 38 §4.45.5. The Editor used to be told to state
    # scope and cutoff, `report.render` also rendered them, and the
    # final verifier flagged the Editor's copy as an uncited assertion
    # (issue I26 in the after arm) -- which under §4.44.2 now removes
    # the whole section that carries it.
    assert "State scope and information cutoff" not in roles.EDITOR_PROMPT
    assert "rendered for" in roles.EDITOR_PROMPT
