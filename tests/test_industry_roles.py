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
