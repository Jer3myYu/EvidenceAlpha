"""Focused integration contracts; injected outputs are not live research."""

import dataclasses
import json
from unittest import mock

import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import handoff
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import stage_context
from evidencealpha import tools
from evidencealpha import workflow


def corpus(tmp_path):
    """Create original evidence outside the photomask domain."""
    file = tmp_path / "source.txt"
    file.write_text(
        "Water revenue: 10 EUR in 2025. Pilot supply only.\nRisk: drought."
    )
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(file)["id"]
    chunk = store.sources()[0]["chunks"][0]["id"]
    passage = store.concise_passage(store.open_source(sid, chunk))
    return store, passage


def test_compaction_and_lineage(tmp_path):
    """Geometry removal cannot alter original text, identity or offsets."""
    store, passage = corpus(tmp_path)
    passage["block_ids"] = ["block"]
    passage["chunk_refs"] = [
        {
            "chunk_id": passage["chunk_id"],
            "spans": [{**passage["spans"][0], "bbox": [1, 2]}],
        }
    ]
    result = handoff.originals(store, documents.group_passages([passage]))
    compact = documents.ungroup_passages(result)[0]
    assert compact["text"] == passage["text"]
    assert compact["spans"] == passage["spans"]
    assert reading.reference(compact) == reading.reference(passage)
    assert "bbox" not in compact["chunk_refs"][0]["spans"][0]
    passage["text"] += " Mass production."
    with pytest.raises(ValueError, match="differs"):
        handoff.originals(store, documents.group_passages([passage]))


def test_required_originals_cannot_silently_disappear(tmp_path):
    """Payload pressure fails explicitly instead of losing used qualifiers."""
    store, passage = corpus(tmp_path)
    del store
    state = stage_context.StageContext(
        tmp_path / "state.json",
        {
            "brief": "water",
            "required_original_refs": [reading.reference(passage)],
        },
    )
    state.settle(documents.group_passages([passage]))
    view = state.build(10000)
    assert (
        documents.ungroup_passages(view["settled_evidence"])[0]["text"]
        == passage["text"]
    )
    with pytest.raises(ValueError, match="budget"):
        state.build(50)


def test_missing_review_scope_is_partial(tmp_path):
    """An empty finding list never implies that the report was examined."""
    store, passage = corpus(tmp_path)
    required = [
        {"id": "financial", "question": "financials"},
        {"id": "technical", "question": "technical status"},
    ]
    quote = {
        "source_id": passage["source_id"],
        "chunk_id": passage["chunk_id"],
        "quote": "10 EUR",
    }
    result = handoff.scope(
        {
            "issues": [],
            "scope": [
                {
                    "id": "financial",
                    "status": "examined",
                    "explanation": "Checked units",
                    "original_passages": [quote],
                }
            ],
        },
        required,
        store,
        True,
    )
    assert result["status"] == "partial"
    assert result["items"][1]["status"] == "unexamined"
    quote["quote"] = "100 USD"
    with pytest.raises(ValueError, match="quote"):
        handoff.validate_quotes([{"original_passages": [quote]}], store)


def test_additive_ledger_protects_writing_and_unknown_usage(tmp_path):
    """One-worker/call/time/unknown-usage checks survive provider wrappers."""
    settings = config.Settings()
    ledger = budget.ExecutionLedger(tmp_path / "ledger.json", settings)
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("full")
    ledger.stage = "research"
    ledger.research = True
    ledger.stage_seconds = 600
    reservation = ledger.reserve(attempt, "codex", 500)
    assert reservation["reserved_seconds"] == 300
    with pytest.raises(budget.BudgetExceeded, match="concurrency"):
        ledger.reserve(attempt, "codex", 10)
    ledger.settle(reservation, 300, "complete", {"output_tokens": 20})
    assert ledger.writing_due()
    ledger.final_writing = True
    reservation = ledger.reserve(attempt, "codex", 500)
    assert reservation["reserved_seconds"] == 300
    ledger.settle(reservation, 1, "failed", {})
    with pytest.raises(budget.BudgetExceeded, match="Unknown"):
        ledger.reserve(attempt, "codex", 1)


def test_capacity_guard_uses_mode_not_concrete_provider(tmp_path):
    """A wrapped provider cannot bypass declared model capacity."""
    store, _ = corpus(tmp_path)
    provider = mock.Mock()
    settings = config.Settings(tool_rounds=1)
    runner = workflow.StageRunner(
        settings, provider, tools.EvidenceTools(store, settings, "fixed-corpus")
    )
    with pytest.raises(ValueError, match="capacity"):
        runner.run(
            "synthesis", "synthesis", {"brief": "water"}, tmp_path / "run"
        )
    provider.run.assert_not_called()


class StageFixture:
    """Inject stage completion artifacts while testing shared orchestration."""

    def __init__(self, passage, fail=None):
        self.passage = passage
        self.fail = fail
        self.calls = []
        self.inputs = {}

    def run(self, stage, role, portable, root, **kwargs):
        """Record inputs and supply bounded source-backed fixture notes."""
        del role, kwargs
        self.calls.append(stage)
        self.inputs[stage] = portable
        if stage == self.fail:
            raise providers.ProviderError("Injected concrete failure")
        p = self.passage
        ref = {
            "source_id": p["source_id"],
            "chunk_id": p["chunk_id"],
            "quote": "Pilot supply only.",
        }
        output = {
            "content": "## Water\n10 EUR; pilot supply only.",
            "issues": [],
            "figures": [],
        }
        if stage == "followup":
            output["scope"] = [
                {
                    "id": "tech",
                    "status": "supported",
                    "explanation": "Pilot, not mass production",
                    "original_passages": [ref],
                }
            ]
        if stage == "recheck":
            output["scope"] = [
                {
                    "id": "finding-0",
                    "status": "examined",
                    "explanation": "Qualifier checked",
                    "original_passages": [ref],
                }
            ]
        folder = root / "stages" / stage / "fixture"
        state = stage_context.StageContext(
            folder / "context-state.json", {"brief": "water"}
        )
        state.settle(documents.group_passages([p]))
        artifacts.write(folder / "writing-context.json", state.build(10000))
        artifacts.write(folder / "output.json", output)
        return {
            "path": str(folder.relative_to(root)),
            "output": output,
            "output_hash": artifacts.digest(output),
        }


def orchestration(tmp_path, fail=None):
    """Run the actual orchestrator with deterministic stage boundaries."""
    store, passage = corpus(tmp_path)
    fixture = StageFixture(passage, fail)
    issue = {
        "severity": "material",
        "location": "Water",
        "evidence": "Pilot qualifier",
        "impact": "Prevents status inflation",
        "suggestion": "Keep pilot qualification",
        "original_passages": [
            {
                "source_id": passage["source_id"],
                "chunk_id": passage["chunk_id"],
                "quote": "Pilot supply only.",
            }
        ],
    }
    execution = {
        "tasks": [{"role": "company", "question": "Water economics"}],
        "required_scope": [{"id": "tech", "question": "Technical status"}],
        "supplemental_findings": [issue],
    }
    with mock.patch.object(
        workflow.render, "export", return_value={"pdf_status": "complete"}
    ):
        result = workflow.run(
            {"topic": "water"},
            dataclasses.replace(config.Settings(), workers=1),
            providers.FixtureProvider({}),
            [],
            tmp_path / "run",
            source_corpus=store.root,
            execution=execution,
            replay_runner=fixture,
        )
    return result, fixture


def test_followup_evidence_review_revision_route(tmp_path):
    """One follow-up and material supplemental finding share the normal path."""
    result, fixture = orchestration(tmp_path)
    assert fixture.calls == [
        "research-0",
        "followup",
        "synthesis",
        "review",
        "revision",
        "recheck",
    ]
    assert result["initial_coverage"]["status"] == "partial"
    assert result["coverage_status"] == "complete"
    assert result["review_status"] == "partial"
    assert result["reviewed_hash"] is None
    assert result["revision_resolution"] == "complete"
    for stage in ("synthesis", "review", "revision", "recheck"):
        assert "Pilot supply only." in json.dumps(
            fixture.inputs[stage]["settled_evidence"]
        )
    assert "initial_gaps" in fixture.inputs["followup"]
    assert "upstream_omissions" in fixture.inputs["revision"]


def test_review_failure_propagates_without_revision(tmp_path):
    """A failed review preserves the draft and cannot claim reviewed status."""
    result, fixture = orchestration(tmp_path, "review")
    assert result["execution_status"] == "failed"
    assert result["reviewed_hash"] is None
    assert "revision" not in fixture.calls
    assert (tmp_path / "run/reports/report.md").exists()
    assert result["export_status"] == "complete"


def test_supplemental_support_is_mandatory(tmp_path):
    """A quoted correction must not lose its original during reselection."""
    store, passage = corpus(tmp_path)
    del store
    assembly = {
        "settled_evidence": {"sources": []},
        "required_original_refs": [],
    }
    handoff.require_support(assembly, documents.group_passages([passage]))
    state = stage_context.StageContext(
        tmp_path / "mandatory.json",
        {
            "brief": "Correct the qualification",
            "required_original_refs": assembly["required_original_refs"],
        },
    )
    state.settle(assembly["settled_evidence"])
    view = state.build(10000)
    assert assembly["required_original_refs"] == [reading.reference(passage)]
    assert (
        documents.ungroup_passages(view["settled_evidence"])[0]["text"]
        == passage["text"]
    )


def test_cancellation_stops_later_stages_and_export(tmp_path):
    """Controller cancellation is terminal, not a research gap to retry."""
    store, _ = corpus(tmp_path)
    with (
        mock.patch.object(
            workflow.StageRunner,
            "run",
            side_effect=providers.ProviderCancelled("stop"),
        ) as run_stage,
        mock.patch.object(workflow.render, "export") as export,
        mock.patch.object(workflow.providers, "cancel_all") as cancel,
    ):
        result = workflow.run(
            {"topic": "water"},
            dataclasses.replace(config.Settings(), workers=1),
            providers.FixtureProvider({}),
            [],
            tmp_path / "cancelled",
            source_corpus=store.root,
            execution={"tasks": [{"role": "company", "question": "water"}]},
        )
    assert result["execution_status"] == "failed"
    assert result["error"]["type"] == "ProviderCancelled"
    assert run_stage.call_count == 1
    export.assert_not_called()
    cancel.assert_called_once()
