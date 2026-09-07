"""Rendering and defaults of the single-call roles."""

from industry import records
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
            quantity=records.Quantity(
                value=60, unit="%", scope="全球", as_written="60%"
            ),
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
