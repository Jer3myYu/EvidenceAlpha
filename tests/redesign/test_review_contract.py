"""Small boundary checks; model judgments are injected, not evaluated."""

import copy

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import review
from evidencealpha import tools
from evidencealpha import workflow


def example(tmp_path):
    """Return a source-bound claim independent of the photomask case."""
    source = tmp_path / "water.txt"
    source.write_text("Water revenue was 10 EUR in 2025. Pilot supply only.")
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(source)["id"]
    chunk = store.sources()[0]["chunks"][0]["id"]
    claim = {
        "id": "status",
        "claim": "Pilot supply only.",
        "location": "Pilot supply only.",
        "requirement_id": "technology",
    }
    spec = review.inventory(
        {"review_claims": [claim]},
        "# Water\nPilot supply only.",
        [{"id": "technology", "question": "Supply status"}],
    )
    check = {
        "id": "status",
        "checked_claim": claim["claim"],
        "status": "examined",
        "outcome": "supported",
        "explanation": "The source explicitly limits supply to pilot status.",
        "remaining": "",
        "checks_performed": "Read the original sentence.",
        "original_passages": [
            {"source_id": sid, "chunk_id": chunk, "quote": claim["claim"]}
        ],
    }
    output = {
        "content": "Status checked; no material objection.",
        "issues": [],
        "review_checks": [check],
        "inventory_assessment": "The only material claim is supply status.",
        "editorial_assessment": "Heading inspected, no quotation needed.",
    }
    return store, spec, output


def test_examination_is_separate_from_support_and_editorial(tmp_path):
    store, spec, output = example(tmp_path)
    baseline = review.assess(output, spec, store)
    assert baseline["factual_status"] == "supported"
    invalid_location = copy.deepcopy(spec)
    invalid_location["items"][0]["location_verified"] = False
    assert review.assess(output, invalid_location, store)["status"] == "partial"
    baseline["items"][0]["outcome"] = "contradicted"
    baseline["factual_status"] = "unresolved"
    finding = {"claim_ids": ["status"]}
    recheck = {"items": [{"id": "finding-0", "status": "examined"}]}
    assert (
        review.resolution(baseline, [finding], recheck)["status"] == "supported"
    )
    assert review.resolution(baseline, [{}], recheck)["status"] == "unresolved"
    baseline["status"] = "partial"
    assert (
        review.resolution(baseline, [finding], recheck)["status"]
        == "unresolved"
    )
    changed = copy.deepcopy(output)
    check = changed["review_checks"][0]
    check["original_passages"] = []
    assert review.assess(changed, spec, store)["status"] == "partial"
    check["outcome"] = "insufficient_evidence"
    result = review.assess(changed, spec, store)
    assert result["status"] == "complete"
    assert result["factual_status"] == "unresolved"
    check["remaining"] = "Commercial scale not checked"
    assert review.assess(changed, spec, store)["status"] == "partial"
    check["remaining"] = ""
    check["original_passages"] = output["review_checks"][0]["original_passages"]
    check["original_passages"][0]["quote"] = "Mass production."
    assert review.assess(changed, spec, store)["errors"]
    fixed = tools.EvidenceTools(store, config.Settings(), "fixed-corpus")
    assert "search_web" not in fixed.definitions()
    try:
        fixed.call("fetch_source", {"url": "https://example.com"})
    except ValueError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("Fixed-corpus network dispatch was admitted")


def test_one_completion_preserves_initial_and_then_stops(tmp_path):
    store, spec, complete = example(tmp_path)
    initial = {"content": "Read the report.", "issues": [], "review_checks": []}
    provider = providers.FixtureProvider({"review": [initial, complete]})
    settings = config.Settings(tool_rounds=5)
    result = workflow.StageRunner(
        settings, provider, tools.EvidenceTools(store, settings, "fixture")
    ).run(
        "review",
        "review",
        {"draft": "# Water\nPilot supply only.", "review_inventory": spec},
        tmp_path / "run",
    )
    assert len(provider.calls) == 2
    folder = tmp_path / "run" / result["path"]
    assert artifacts.read(folder / "initial-review.json") == initial
    assert review.assess(result["output"], spec, store)["status"] == "complete"
    # A repeated incomplete answer must not start an automatic third review.
    provider = providers.FixtureProvider({"review": [initial, initial]})
    result = workflow.StageRunner(
        settings, provider, tools.EvidenceTools(store, settings, "fixture")
    ).run(
        "review",
        "review",
        {"draft": "# Water\nPilot supply only.", "review_inventory": spec},
        tmp_path / "partial",
    )
    assert len(provider.calls) == 2
    assert review.assess(result["output"], spec, store)["status"] == "partial"
