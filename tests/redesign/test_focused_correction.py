"""Accumulated identity, original-reference and final-handoff regressions."""

import html
import json
import pathlib
from unittest import mock

import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import cli
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow

FIXTURE = (
    pathlib.Path(__file__).parents[1]
    / "fixtures/redesign/focused/originals.json"
)


def _corpus(tmp_path):
    saved = artifacts.read(FIXTURE)
    store = documents.SourceStore(tmp_path / "corpus")
    sources = {}
    for item in saved["sources"]:
        path = tmp_path / (item["company"] + ".html")
        path.write_text(
            "".join(
                "<p>" + html.escape(p["text"]) + "</p>"
                for p in item["passages"]
            )
        )
        source = store.ingest(path)
        identity = {
            key: {"value": item["company"], "chunk_id": "c0"}
            for key in ("title", "issuer")
        }
        artifacts.write(store.root / source["id"] / "identity.json", identity)
        sources[item["company"]] = source["id"]
    return store, sources, saved


def test_issuer_swaps_luxin_and_split_statement(tmp_path):
    """Saved originals remain attached to their issuer across search/open."""
    store, ids, saved = _corpus(tmp_path)
    evidence = tools.EvidenceTools(store, config.Settings(), "fixed-corpus")
    for name, source_id in ids.items():
        passages = evidence.call(
            "search_evidence", {"query": "营业收入", "source_id": source_id}
        )
        passages = documents.ungroup_passages(passages)
        assert passages
        assert all(
            p["issuer"]["value"] == name and p["source_id"] == source_id
            for p in passages
        )
    owner = saved["expected"]["luxin_issuer"]
    result = evidence.call(
        "search_evidence", {"query": "路芯", "source_id": ids[owner]}
    )
    result = documents.ungroup_passages(result)
    assert any("路芯" in p["text"] for p in result)
    assert all(p["issuer"]["value"] == owner for p in result)
    sid = ids[saved["expected"]["split_subject"]]
    tail = next(
        p
        for p in store.search_evidence("65nm", source_id=sid)
        if p["text"].startswith("实现量产")
    )
    window = evidence.call(
        "open_source",
        {"source_id": sid, "chunk_id": tail["chunk_id"], "surrounding": 1},
    )
    window = documents.ungroup_passages(window)
    assert saved["expected"]["split_status"] in "".join(
        p["text"] for p in window
    )
    assert len(window) <= 3
    canonical = store.open_source(sid)["text"]
    for passage in window:
        assert passage["text"] == "\n".join(
            canonical[s["start"] : s["end"]] for s in passage["spans"]
        )
        assert "bbox" not in json.dumps(passage)
    with pytest.raises(ValueError, match="0 to 2"):
        evidence.call(
            "open_source",
            {"source_id": sid, "chunk_id": "c0", "surrounding": 3},
        )


def test_document_issuer_is_not_statement_subject(tmp_path):
    """Metadata does not rewrite a quoted competitor into the publisher."""
    expected = artifacts.read(FIXTURE)["expected"]
    issuer, subject = (
        expected["third_party_document_issuer"],
        expected["third_party_subject"],
    )
    path = tmp_path / "third-party.html"
    path.write_text(
        f"<h1>{issuer}</h1><p>{subject} reported revenue of 42.</p>"
    )
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(path)["id"]
    artifacts.write(
        store.root / sid / "identity.json",
        {"issuer": {"value": issuer, "chunk_id": "c0"}},
    )
    passage = tools.EvidenceTools(
        store, config.Settings(), "fixed-corpus"
    ).call("search_evidence", {"query": "revenue", "source_id": sid})
    passage = documents.ungroup_passages(passage)[0]
    assert passage["issuer"]["value"] == issuer
    assert passage["text"] == f"{subject} reported revenue of 42."
    assert "subjects may differ" in passage["identity_scope"]


def test_lost_handoff_retains_originals_without_transcript(tmp_path):
    """A provider timeout cannot erase already retrieved usable evidence."""
    store, ids, _ = _corpus(tmp_path)
    source_id = next(iter(ids.values()))
    provider = providers.FixtureProvider(
        {
            "company": [
                {
                    "tool_calls": [
                        {
                            "name": "open_source",
                            "arguments": {
                                "source_id": source_id,
                                "chunk_id": "c0",
                            },
                        }
                    ]
                },
                {"fixture_error": "timeout"},
            ]
        }
    )
    runner = workflow.StageRunner(
        config.Settings(final_writing_reserve_seconds=60),
        provider,
        tools.EvidenceTools(store, config.Settings(), "fixed-corpus"),
    )
    with pytest.raises(workflow.ResearchHandoffError) as failure:
        runner.run("company", "company", {}, tmp_path / "run", seconds=180)
    handoff = failure.value.handoff
    assert handoff["status"] == "unsynthesized_evidence"
    assert (
        documents.ungroup_passages(handoff["settled_evidence"])[0]["source_id"]
        == source_id
    )
    assert (
        documents.ungroup_passages(handoff["settled_evidence"])[0]["chunk_id"]
        == "c0"
    )
    assert "messages" not in handoff
    assert "output" not in handoff
    assert next(
        (tmp_path / "run").glob("stages/company/*/handoff.json")
    ).exists()


def test_revision_time_reserve_and_stripped_input(tmp_path):
    """Early revision writing receives unused evidence time."""
    clock = [100.0]
    requests = []

    class SlowProvider:
        """Advance a fake clock through actual runner transitions."""

        def run(self, request):
            """Use two evidence calls then deliver complete final content."""
            requests.append(request)
            if len(requests) < 3:
                clock[0] += 20
                return providers.Result(
                    json.dumps(
                        {
                            "tool_calls": [
                                {
                                    "name": "calculate",
                                    "arguments": {
                                        "operation": "add",
                                        "values": ["1", "2"],
                                    },
                                }
                            ]
                        }
                    )
                )
            clock[0] += 200
            return providers.Result(
                json.dumps(
                    {"content": "Report; unsupported objection rejected."}
                )
            )

    settings = config.Settings()
    runner = workflow.StageRunner(
        settings,
        SlowProvider(),
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    portable = workflow.revision_input(
        {
            "brief": "requirements",
            "draft": "draft",
            "sources": [],
            "notes": "redundant",
            "plan": "redundant",
            "gaps": {},
        },
        {"issues": []},
    )
    assert set(portable) == {
        "brief",
        "draft",
        "sources",
        "findings",
        "instruction",
    }
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        runner.run(
            "revision", "revision", portable, tmp_path / "run", seconds=300
        )
    assert [r.seconds for r in requests] == [120, 100, 260]
    assert requests[-1].allowed_tools == ()
    assert clock[0] <= 370


def test_material_objection_cannot_use_draft_label_as_support(tmp_path):
    """Missing/fabricated original references fail at the runner boundary."""
    store, ids, _ = _corpus(tmp_path)
    issue = {
        "severity": "material",
        "location": "table",
        "evidence": "Draft says issuer X",
        "impact": "wrong company",
        "suggestion": "reassign",
    }
    with pytest.raises(ValueError, match="original passages"):
        workflow.parse_output(
            json.dumps({"content": "Objection", "issues": [issue]}), "review"
        )
    issue["original_passages"] = [
        {
            "source_id": next(iter(ids.values())),
            "chunk_id": "c0",
            "quote": "A fabricated reassignment not in the original",
        }
    ]
    settings = config.Settings()
    runner = workflow.StageRunner(
        settings,
        providers.FixtureProvider(
            {"review": {"content": "Objection", "issues": [issue]}}
        ),
        tools.EvidenceTools(store, settings, "fixed-corpus"),
    )
    with pytest.raises(ValueError, match="absent from original"):
        runner.run("review", "review", {}, tmp_path / "run")


def test_additive_allowance_never_resets_or_retries(tmp_path):
    """Only A/B/C sequential admissions; failures stop the linked campaign."""
    parent = tmp_path / "exhausted.json"
    artifacts.write(parent, {"campaign_started": 1, "attempts": ["exhausted"]})
    before = parent.read_bytes()
    ledger = budget.DiagnosticLedger(tmp_path / "additive.json")
    ledger.initialize_linked(parent)
    ledger.start()
    with pytest.raises(budget.BudgetExceeded):
        ledger.admit("full")
    attempt = ledger.admit("A")
    reservation = ledger.reserve(attempt, "codex", 180)
    with pytest.raises(budget.BudgetExceeded):
        ledger.reserve(attempt, "codex", 1)
    ledger.settle(reservation, 1, "failed", {})
    ledger.finish(attempt, "failed")
    with pytest.raises(budget.BudgetExceeded):
        ledger.admit("B")
    assert parent.read_bytes() == before
    assert (
        artifacts.read(ledger.path)["invocations"][0]["observable_tokens"]
        is None
    )


def test_failed_worker_evidence_reaches_synthesis(tmp_path):
    """Workflow forwards the fallback but never presents it as final notes."""
    brief, provider, paths = cli.fixture(FIXTURE.parents[1] / "service.json")
    source_id = documents.SourceStore(tmp_path / "inventory").ingest(paths[0])[
        "id"
    ]
    provider.outputs["plan"]["tasks"] = [
        {"role": "company", "question": "Read evidence"}
    ]
    provider.outputs["research-0"] = [
        {
            "tool_calls": [
                {
                    "name": "open_source",
                    "arguments": {"source_id": source_id, "chunk_id": "c0"},
                }
            ]
        },
        {"fixture_error": "timeout"},
    ]
    workflow.run(brief, config.Settings(), provider, paths, tmp_path / "run")
    request = next(c for c in provider.calls if c.stage == "synthesis")
    portable = json.loads(request.prompt)["messages"][1]["content"]
    assert not portable["notes"]
    fallback = portable["unsynthesized_evidence"]["research-0"]
    assert fallback["status"] == "unsynthesized_evidence"
    assert (
        documents.ungroup_passages(fallback["settled_evidence"])[0]["source_id"]
        == source_id
    )


def test_revision_enclosing_deadline_cannot_be_extended(tmp_path):
    """A short remaining run gets immediate writing, not new evidence time."""
    clock = [100.0]
    provider = providers.FixtureProvider(
        {"revision": {"content": "Partial coverage disclosed"}}
    )
    runner = workflow.StageRunner(
        config.Settings(),
        provider,
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"),
            config.Settings(),
            "fixed-corpus",
        ),
    )
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        runner.run(
            "revision",
            "revision",
            {},
            tmp_path / "run",
            seconds=300,
            deadline=130,
        )
    assert provider.calls[0].allowed_tools == ()
    assert provider.calls[0].seconds == 30
    assert provider.calls[0].deadline == 130


def test_false_luxin_objection_can_be_contested(tmp_path):
    """The revision boundary permits a supported rejection of bad findings."""
    store, ids, saved = _corpus(tmp_path)
    expected = saved["expected"]
    sid = ids[expected["luxin_issuer"]]
    passage = next(
        p
        for p in store.search_evidence("路芯", source_id=sid)
        if "路芯" in p["text"]
    )
    rejected = expected["revision_rejection"].format(
        source_id=sid, chunk_id=passage["chunk_id"]
    )
    provider = providers.FixtureProvider(
        {
            "revision": [
                {
                    "tool_calls": [
                        {
                            "name": "open_source",
                            "arguments": {
                                "source_id": sid,
                                "chunk_id": passage["chunk_id"],
                            },
                        }
                    ]
                },
                {"content": rejected},
            ]
        }
    )
    settings = config.Settings()
    runner = workflow.StageRunner(
        settings, provider, tools.EvidenceTools(store, settings, "fixed-corpus")
    )
    portable = workflow.revision_input(
        {"brief": "Preserve supported ownership", "draft": "Preserved draft"},
        {"content": expected["false_luxin_objection"]},
    )
    result = runner.run(
        "revision", "revision", portable, tmp_path / "run", seconds=300
    )
    assert result["output"]["content"] == rejected
    tool_reply = json.loads(provider.calls[1].prompt)["messages"][-1][
        "content"
    ]["settled_evidence"]
    tool_reply = documents.ungroup_passages(tool_reply)[0]
    assert tool_reply["issuer"]["value"] == expected["luxin_issuer"]
    assert tool_reply["text"] == passage["text"]
