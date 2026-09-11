"""Offline regressions from the failed company stage; no model calls."""

import copy
import html
import json
import pathlib
import sys
import threading
from unittest import mock

import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import stage_context
from evidencealpha import tools
from evidencealpha import workflow

FIXTURE = (
    pathlib.Path(__file__).parents[1]
    / "fixtures/redesign/focused/settled-company.json"
)


def _evidence(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Original evidence retained for final notes.")
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(path)["id"]
    evidence = tools.EvidenceTools(store, config.Settings(), "fixed-corpus")
    call = {
        "tool_calls": [
            {
                "name": "open_source",
                "arguments": {"source_id": sid, "chunk_id": "c0"},
            }
        ]
    }
    return evidence, call


@pytest.mark.parametrize("ledger_kind", ["ordinary", "diagnostic"])
@pytest.mark.parametrize("unexpected_cutoff", [False, True])
def test_early_transition_writes_but_timeout_stops(
    tmp_path, unexpected_cutoff, ledger_kind
):
    """Early completion writes; a timed-out call never auto-continues."""
    evidence, call = _evidence(tmp_path)
    clock = [100.0]
    requests = []
    invoke = evidence.call

    def slow_tool(*args, **kwargs):
        value = invoke(*args, **kwargs)
        if not unexpected_cutoff:
            clock[0] += 61.69
        return value

    evidence.call = slow_tool

    class ScriptedProvider:
        """Advance through the actual runner, with recorded call duration."""

        def run(self, request):
            """Request evidence, optionally hit its cutoff, then write."""
            requests.append(request)
            if len(requests) == 1:
                clock[0] += 10 if unexpected_cutoff else 30.21
                return providers.Result(json.dumps(call), {"output_tokens": 1})
            if unexpected_cutoff and len(requests) == 2:
                clock[0] = request.deadline
                raise providers.ProviderTimeout(
                    "Provider deadline expired", request.deadline
                )
            assert request.allowed_tools == ()
            assert json.loads(request.prompt)["phase"] == "final_notes"
            clock[0] += 20
            return providers.Result(
                json.dumps(
                    {"content": "Notes from settled originals; gaps disclosed."}
                ),
                {"output_tokens": 2},
            )

    if ledger_kind == "ordinary":
        ledger = budget.Ledger(tmp_path / "ledger.json")
        ledger.initialize()
    else:
        parent = tmp_path / "parent.json"
        artifacts.write(parent, {"status": "synthetic offline parent"})
        ledger = budget.DiagnosticLedger(tmp_path / "ledger.json")
        ledger.initialize_linked(parent)
    ledger.start()
    attempt = ledger.admit("isolated" if ledger_kind == "ordinary" else "A")
    runner = workflow.StageRunner(
        config.Settings(final_writing_reserve_seconds=65),
        ScriptedProvider(),
        evidence,
        ledger,
        attempt,
    )
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        if unexpected_cutoff:
            with pytest.raises(workflow.ResearchHandoffError) as failure:
                runner.run(
                    "company", "company", {}, tmp_path / "run", seconds=180
                )
            assert isinstance(
                failure.value.__cause__, providers.ProviderTimeout
            )
            assert len(requests) == 2
            assert [
                x["status"] for x in artifacts.read(ledger.path)["invocations"]
            ] == ["complete", "failed"]
            assert (
                artifacts.read(ledger.path)["invocations"][-1][
                    "observable_tokens"
                ]
                is None
            )
            assert (
                len(
                    documents.ungroup_passages(
                        failure.value.handoff["settled_evidence"]
                    )
                )
                == 1
            )
            return
        result = runner.run(
            "company", "company", {}, tmp_path / "run", seconds=180
        )
    assert result["output"]["content"].startswith("Notes from settled")
    assert len(requests) == (3 if unexpected_cutoff else 2)
    final_input = json.loads(
        json.loads(requests[-1].prompt)["messages"][1]["content"]
    )
    assert len(documents.ungroup_passages(final_input["settled_evidence"])) == 1
    assert len(json.loads(requests[-1].prompt)["messages"]) == 2
    folder = tmp_path / "run" / result["path"]
    transitions = [
        json.loads(l)
        for l in (folder / "events.jsonl").read_text().splitlines()
        if json.loads(l)["kind"] == "phase_transition"
    ]
    assert len(transitions) == 1
    assert transitions[0]["prior_call_seconds"] == pytest.approx(30.21)
    assert transitions[0]["evidence_remaining"] == pytest.approx(23.10)


@pytest.mark.parametrize(
    "failure",
    ["provider", "quota", "cancel", "outer", "other_deadline", "no_round"],
)
def test_other_failures_never_enter_writing(tmp_path, failure):
    """Do not recover on timeout wording, cancellation or smaller limits."""
    evidence, call = _evidence(tmp_path)
    clock = [100.0]
    requests = []

    class FailingProvider:
        """Reach a real failure after one settled original."""

        def run(self, request):
            """Return evidence once, then propagate the specified failure."""
            requests.append(request)
            if len(requests) == 1:
                return providers.Result(json.dumps(call))
            if failure == "provider":
                raise providers.ProviderError("Provider deadline expired")
            if failure == "quota":
                raise providers.QuotaExhausted("Quota exhausted")
            if failure == "cancel":
                raise providers.ProviderCancelled("Cancelled")
            clock[0] = 281 if failure == "outer" else request.deadline
            cutoff = (
                request.deadline - 1
                if failure == "other_deadline"
                else request.deadline
            )
            raise providers.ProviderTimeout("Provider deadline expired", cutoff)

    settings = config.Settings(
        tool_rounds=2 if failure == "no_round" else 8,
        final_writing_reserve_seconds=60,
    )
    runner = workflow.StageRunner(settings, FailingProvider(), evidence)
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        with pytest.raises(providers.ProviderError):
            runner.run("company", "company", {}, tmp_path / "run", seconds=180)
    assert len(requests) == 2
    assert not list((tmp_path / "run").glob("stages/company/*/call-2"))
    assert next(
        (tmp_path / "run").glob("stages/company/*/context-state.json")
    ).exists()


def test_balanced_recorded_distribution_and_omitted_references():
    """Early source saturation cannot erase later sources from the fallback."""
    fixture = artifacts.read(FIXTURE)
    passages = documents.ungroup_passages(fixture["settled_evidence"])
    assert [
        len(s["passages"]) for s in fixture["settled_evidence"]["sources"]
    ] == fixture["expected_distribution"]
    bounded = documents.evidence_handoff(passages, max_passages=12)
    assert [len(s["passages"]) for s in bounded["sources"]] == [4, 4, 4]
    assert len(bounded["omitted_passages"]) == 55

    def refs(values):
        return {(p["source_id"], p.get("chunk_id")) for p in values}

    selected = documents.ungroup_passages(bounded)
    assert refs(selected) | refs(bounded["omitted_passages"]) == refs(passages)
    assert not refs(selected) & refs(bounded["omitted_passages"])
    assert all(p["spans"] for p in bounded["omitted_passages"])
    assert "omitted" in " ".join(bounded["missing_information"])
    assert (
        len(documents.ungroup_passages(documents.evidence_handoff(passages)))
        == 67
    )
    tiny = documents.evidence_handoff(passages, max_characters=20)
    assert sum(len(p["text"]) for p in documents.ungroup_passages(tiny)) <= 20
    assert tiny["omitted_passages"]


def test_grouped_identity_preserves_bindings_and_reduces_bytes():
    """Identity appears once per source; text and every locator survive."""
    grouped = artifacts.read(FIXTURE)["settled_evidence"]
    flat = documents.ungroup_passages(grouped)
    assert documents.group_passages(flat) == grouped
    assert (
        len(json.dumps(grouped).encode()) < len(json.dumps(flat).encode()) * 0.6
    )
    for source in grouped["sources"]:
        for passage in source["passages"]:
            assert "issuer" not in passage
            assert passage["spans"] and passage["chunk_id"]
            assert source["source_id"]


def test_saved_broad_narrow_financial_query(tmp_path):
    """Reproduce financial row omission using saved original passages."""
    case = artifacts.read(FIXTURE)["query_case"]
    path = tmp_path / "query.html"
    path.write_text(
        "".join(
            "<p>" + html.escape(p["text"]) + "</p>" for p in case["passages"]
        )
    )
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(path)["id"]
    evidence = tools.EvidenceTools(store, config.Settings(), "fixed-corpus")
    for query in case["broad_queries"]:
        found = documents.ungroup_passages(
            evidence.call("search_evidence", {"query": query, "source_id": sid})
        )
        assert case["financial_text"] not in [p["text"] for p in found]
    narrow = documents.ungroup_passages(
        evidence.call(
            "search_evidence", {"query": case["narrow_query"], "source_id": sid}
        )
    )
    assert narrow[0]["text"] == case["financial_text"]
    assert {p["source_id"] for p in narrow} == {sid}


def test_saved_evidence_final_notes_only_cannot_research(tmp_path):
    """Exercise the proposed writing-only case with a fixture provider."""
    fixture = artifacts.read(FIXTURE)
    evidence, _ = _evidence(tmp_path)
    evidence.call = mock.Mock(
        side_effect=AssertionError("No research permitted")
    )
    provider = providers.FixtureProvider(
        {
            "company": {
                "content": "Fixture final notes only; not model validation."
            }
        }
    )
    result = workflow.StageRunner(config.Settings(), provider, evidence).run(
        "company",
        "company",
        {
            "brief": "Compare using saved originals only",
            "settled_evidence": fixture["settled_evidence"],
        },
        tmp_path / "run",
        final_notes_only=True,
        seconds=180,
    )
    assert result["output"]["content"]
    assert len(provider.calls) == 1
    assert provider.calls[0].allowed_tools == ()
    portable = json.loads(
        json.loads(provider.calls[0].prompt)["messages"][1]["content"]
    )
    assert len(documents.ungroup_passages(portable["settled_evidence"])) == 67
    evidence.call.assert_not_called()


def test_supervisor_timeout_and_cancellation_are_distinct(tmp_path):
    """Use local sleeping children, not a model, at the adapter boundary."""
    request = providers.Request(
        "offline",
        "",
        config.ModelSettings("codex", config.RUNTIME_MODEL),
        tmp_path / "timeout",
        0.1,
    )
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    with pytest.raises(providers.ProviderTimeout) as timeout:
        providers.execute(command, request)
    assert timeout.value.deadline > 0
    assert timeout.value.limit == "invocation_allowance"
    completed = json.loads(
        (request.workspace / "events.jsonl").read_text().splitlines()[-1]
    )
    assert completed["ended_by"] == timeout.value.limit
    request.workspace = tmp_path / "cancel"
    request.seconds = 5
    timer = threading.Timer(0.2, providers.cancel_all)
    timer.start()
    try:
        with pytest.raises(providers.ProviderCancelled):
            providers.execute(command, request)
    finally:
        timer.join()


def test_one_durable_context_retains_task_failures_and_versions(tmp_path):
    """Bound requests while retaining failed searches and bindings."""
    task = {
        "brief": "Compare only supported metrics",
        "task": {"question": "What is missing?"},
        "unresolved_questions": ["Unreported metric"],
    }
    state = stage_context.StageContext(tmp_path / "context-state.json", task)
    evidence = artifacts.read(FIXTURE)["settled_evidence"]
    state.settle(evidence)
    missing = {
        "query": "unreported metric",
        "source_id": evidence["sources"][0]["source_id"],
    }
    state.outcome("search_evidence", missing, {"sources": []})
    sizes = []
    for _ in range(20):
        state.settle(evidence)
        state.outcome("search_evidence", {"query": "reported metric"}, evidence)
        prompt, frame = state.request(
            "Original evidence only", {}, "evidence", 8, 60000
        )
        sizes.append(len(prompt.encode()))
        assert frame["brief"] == task["brief"]
        assert frame["task"] == task["task"]
        assert frame["unresolved_questions"] == task["unresolved_questions"]
    assert len(set(sizes[-5:])) == 1
    assert frame["context_record"] == str(state.path)
    assert frame["settled_evidence"]["full_evidence_record"] == str(state.path)
    assert frame["unsuccessful_queries"]["items"][0]["arguments"] == missing
    assert frame["unsuccessful_queries"]["items"][0]["status"] == "no_results"
    assert len(frame["recent_tool_outcomes"]) == 8
    restored = stage_context.StageContext(state.path, task)
    assert len(documents.ungroup_passages(restored.data["evidence"])) == 67
    _, final = restored.request(
        "Original evidence only", {}, "final_notes", 1, 60000
    )
    _, fallback = restored.request(
        "Original evidence only", {}, "final_notes", 0, 60000
    )
    assert final == fallback
    assert (
        final["settled_evidence"]["sources"][0]["version"]
        == evidence["sources"][0]["version"]
    )
    smaller_prompt, smaller = restored.request(
        "Original evidence only", {}, "final_notes", 1, 12000
    )
    assert len(smaller_prompt.encode()) <= 12000
    assert smaller["settled_evidence"]["omitted_reference_count"]
    assert (
        len(documents.ungroup_passages(artifacts.read(state.path)["evidence"]))
        == 67
    )
    changed = copy.deepcopy(evidence)
    changed["sources"][0]["version"]["text_hash"] = "different version"
    with pytest.raises(ValueError, match="changed|Conflicting"):
        restored.settle(changed)
    assert artifacts.read(state.path)["evidence"] == evidence


def test_source_share_does_not_let_large_first_passage_erase_other_sources():
    """Reserve source coverage under both character and count limits."""
    fixture = artifacts.read(FIXTURE)["settled_evidence"]
    passages = [
        documents.ungroup_passages({"sources": [source]})[0]
        for source in fixture["sources"]
    ]
    # Hypothetical size distribution exercises allocation, not company facts.
    passages[0]["text"] = "x" * 16000
    passages[1]["text"] = passages[2]["text"] = "small"
    result = documents.evidence_handoff(passages)
    assert len(result["sources"]) == 2
    assert (
        result["omitted_passages"][0]["source_id"] == passages[0]["source_id"]
    )
