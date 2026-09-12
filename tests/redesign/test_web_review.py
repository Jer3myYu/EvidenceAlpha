"""Explicit web capability, original capture and stable source identity."""

import json

import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import handoff
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow


def test_model_resolution_and_role_selection():
    settings = config.Settings()
    assert settings.model("review").model == "gpt-6-astra"
    assert settings.model("recheck").model == "gpt-6-astra"
    assert settings.model("revision").model == "gpt-5.6-sol"
    with pytest.raises(ValueError, match="unavailable"):
        providers.installed_model("unavailable-test-model")


def test_capture_lineage_cutoff_aliases_and_offline_boundary(
    tmp_path, monkeypatch
):
    store = documents.SourceStore(tmp_path / "sources")
    original = tmp_path / "original.txt"
    original.write_text("Initial corpus fact.")
    sid = store.ingest(original)["id"]
    reports = tmp_path / "reports"
    reports.mkdir()
    workflow._prepare_report(  # pylint: disable=protected-access
        {"content": "# Draft", "figures": []}, reports, store, "draft.md"
    )
    alias = next(
        k
        for k, v in artifacts.read(reports / "source-map.json").items()
        if v["source_id"] == sid
    )
    settings = config.Settings(
        web_verification=True, information_cutoff="2026-09-12"
    )
    ledger = budget.ExecutionLedger(tmp_path / "ledger.json", settings)
    ledger.initialize()
    ledger.start()
    offline = tools.EvidenceTools(store, settings, "fixed-corpus", ledger)
    with pytest.raises(ValueError, match="unavailable"):
        offline.call("fetch_source", {"url": "https://example.org/source"})
    online = tools.EvidenceTools(store, settings, "live", ledger)

    class Response:
        """Captured primary document, not a search snippet."""

        status_code = 200
        headers = {"content-type": "text/html"}
        url = "https://example.org/source"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _):
            yield (
                b"<html><body><h1>Issuer</h1><p>2026-09-10. FY2025: "
                b"10 EUR. Pilot supply only.</p></body></html>"
            )

    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: Response())
    captured = online.call("fetch_source", {"url": Response.url})
    new_id = captured["source"]["id"]
    opened = online.call("open_source", {"source_id": new_id})
    identity = store.source_context(new_id)
    assert (
        identity["external_verification"]["information_cutoff"] == "2026-09-12"
    )
    assert identity["acquired_at"]
    assert identity["document_date"] is None  # Never guess from capture date.
    assembly = {"settled_evidence": {"sources": []}}
    handoff.require_support(assembly, opened)
    assert assembly["required_original_refs"]
    passages = documents.ungroup_passages(assembly["settled_evidence"])
    assert any("Pilot supply" in p["text"] for p in passages)
    assert all(p["external_verification"] for p in passages)
    workflow._prepare_report(  # pylint: disable=protected-access
        {"content": "# Revision\n" + new_id, "figures": []},
        reports,
        store,
        "revised.md",
    )
    assert (
        artifacts.read(reports / "source-map.json")[alias]["source_id"] == sid
    )
    assert artifacts.read(ledger.path)["fetch_attempts"] == 1
    assert "search_web" not in offline.definitions()
    assert "search_web" in online.definitions()
    with pytest.raises(ValueError, match="Fixed-corpus"):
        workflow.run(
            {},
            settings,
            providers.FixtureProvider({}),
            [],
            tmp_path / "rejected",
            mode="fixed-corpus",
        )


def test_normal_stage_exposes_web_only_for_verification_roles(tmp_path):
    settings = config.Settings(
        web_verification=True, information_cutoff="2026-09-12"
    )
    store = documents.SourceStore(tmp_path / "sources")
    for stage, role, allowed in (
        ("review", "review", True),
        ("recheck", "recheck", True),
        ("review-followup", "company", True),
        ("revision", "revision", False),
    ):
        provider = providers.FixtureProvider(
            {stage: {"content": "Fixture", "issues": []}}
        )
        runner = workflow.StageRunner(
            settings,
            provider,
            tools.EvidenceTools(store, settings, "verification"),
        )
        runner.run(
            stage,
            role,
            {"information_cutoff": settings.information_cutoff},
            tmp_path / stage,
        )
        first = json.loads(provider.calls[0].prompt)
        assert ("fetch_source" in first["tools"]) == allowed
        assert ("search_web" in first["tools"]) == allowed
