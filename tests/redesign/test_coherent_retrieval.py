"""Deterministic contracts; no model inference or retrieval-quality claim."""

import copy
import json
import pathlib
import time

import pytest

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import protocol
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import reranking
from evidencealpha import retrieval
from evidencealpha import stage_context
from evidencealpha import tools
from evidencealpha import workflow


class InjectedScorer:
    """Deterministic scores assert control flow, not relevance."""

    def __init__(self):
        self.views = []
        self.closed = False

    def score(self, query, views, deadline):
        """Record original context and reverse lexical order."""
        assert query
        assert time.monotonic() < deadline
        self.views = views
        return [
            {"score": float(i), "pairs": 1, "status": "injected"}
            for i, _ in enumerate(views)
        ]

    def close(self):
        """Record release without a process."""
        self.closed = True


def passage(index, text):
    """Make generic immutable originals for payload tests."""
    return {
        "source_id": "source",
        "version": {"hash": "v1"},
        "chunk_id": f"c{index}",
        "text": text,
        "spans": [
            {
                "start": index * 10000,
                "end": index * 10000 + len(text),
                "page": 1,
            }
        ],
    }


def settle(state, item, qid=None):
    """Settle one complete reading bundle."""
    ref = reading.reference(item)
    state.settle(
        {
            **documents.group_passages([item]),
            "reading_blocks": [{"refs": [ref], "status": "complete_window"}],
        },
        qid,
    )
    return next(
        bid for bid, b in state.data["bundles"].items() if b["refs"] == [ref]
    )


def test_all_evidence_and_actual_request_accounting(tmp_path):
    """A fitting complete envelope has no passage-count gate."""
    state = stage_context.StageContext(
        tmp_path / "state.json", {"brief": "中文 research"}
    )
    state.settle(
        documents.group_passages([passage(i, f"原文 {i}") for i in range(103)])
    )
    prompt, view = state.request(
        'Quoted "instructions"', {}, "final_notes", 1, 100000
    )
    assert len(documents.ungroup_passages(view["settled_evidence"])) == 103
    measured = artifacts.read(tmp_path / "request-size.json")
    schema = protocol.encoded_schema(())
    assert json.loads(schema) == protocol.output_schema(())
    assert measured["application_utf8_bytes"] == len(prompt.encode()) + len(
        schema.encode()
    )
    assert measured["application_utf8_bytes"] <= 100000


def test_adequate_before_unassessed_and_arrival_independent(tmp_path):
    """Adequacy wins within task priority; original order never wins."""
    selected = []
    for label, order in [("forward", [0, 1, 2]), ("reverse", [2, 1, 0])]:
        state = stage_context.StageContext(
            tmp_path / label / "state.json", {"brief": "metrics"}
        )
        qid = next(iter(state.data["questions"]))
        ids = {}
        for i in order:
            ids[i] = settle(state, passage(i, chr(65 + i) * 2500), qid)
        state.update_coverage(
            [
                {
                    "question_id": qid,
                    "state": "supported",
                    "adequacy": "adequate",
                    "bundle_ids": [ids[2]],
                }
            ]
        )
        view = state.build(7000)
        chunks = {
            p.get("chunk_id")
            for p in documents.ungroup_passages(view["settled_evidence"])
        }
        assert "c2" in chunks
        assert len(chunks) < 3
        selected.append(chunks)
        assert view["settled_evidence"]["omitted_reference_count"]
    assert selected[0] == selected[1]


def test_coverage_is_provisional_atomic_and_reference_checked(tmp_path):
    """A fact plus qualifier is indivisible; returned results do not certify."""
    state = stage_context.StageContext(
        tmp_path / "state.json", {"brief": "comparison"}
    )
    qid = next(iter(state.data["questions"]))
    ids = [settle(state, passage(i, str(i) * 2500), qid) for i in range(2)]
    state.outcome(
        "search_evidence",
        {"query": "metric"},
        documents.group_passages([passage(0, "0" * 2500)]),
    )
    assert state.data["questions"][qid]["state"] == "unresolved"
    state.update_coverage(
        [
            {
                "question_id": qid,
                "state": "supported",
                "adequacy": "adequate",
                "bundle_ids": ids,
            }
        ]
    )
    before = copy.deepcopy(state.data)
    with pytest.raises(ValueError, match="unknown bundles"):
        state.update_coverage(
            [{"question_id": qid, "bundle_ids": ["invented"]}]
        )
    assert state.data == before
    view = state.build(5000)
    assert view["questions"][qid]["delivered_state"] != "supported"
    assert len(documents.ungroup_passages(state.data["evidence"])) == 2
    altered = passage(0, "X" * 2500)
    with pytest.raises(ValueError, match="changed"):
        state.settle(documents.group_passages([altered]))


def test_contextual_candidates_and_returned_blocks_are_distinct(tmp_path):
    """Only final reading blocks settle; all candidate context is original."""
    path = tmp_path / "source.txt"
    path.write_text(
        "\n\n".join(
            f"Revenue explanation {i}. Customer context." for i in range(80)
        )
    )
    store = documents.SourceStore(tmp_path / "corpus", chunk_characters=100)
    sid = store.ingest(path)["id"]
    scorer = InjectedScorer()
    settings = config.Settings(retrieval_limit=2)
    engine = retrieval.Retriever(store, settings, scorer)
    engine.trace_dir = tmp_path / "traces"
    result = engine.search("Revenue", sid, None, time.monotonic() + 30)
    assert result["candidate_count"] == 64
    assert len(result["reading_blocks"]) == 2
    assert len(scorer.views) == 64
    assert all(
        "Customer context." in v["passages"][0]["text"] for v in scorer.views
    )
    assert artifacts.read(pathlib.Path(result["trace"]))["pairs"] == 64
    engine.close()
    assert scorer.closed
    with pytest.raises(ValueError, match="Unknown source"):
        engine.search("Revenue", "missing", None, time.monotonic() + 30)


def test_unavailable_never_silently_uses_lexical(tmp_path):
    """A missing snapshot requires no imports, subprocess or model call."""
    path = tmp_path / "source.txt"
    path.write_text("Revenue and its cause.")
    store = documents.SourceStore(tmp_path / "corpus")
    store.ingest(path)
    engine = retrieval.Retriever(store, config.Settings())
    result = engine.search("Revenue", None, None, time.monotonic() + 30)
    assert result["retrieval_status"] == "reranker_unavailable"
    assert not result["passages"]
    assert engine.scorer.process is None
    degraded = retrieval.Retriever(
        store, config.Settings(retrieval_mode="degraded_lexical")
    )
    assert (
        degraded.search("Revenue", None, None, None)["retrieval_status"]
        == "degraded_lexical"
    )


def test_structural_window_units_continuations_and_version(tmp_path):
    """Rows retain context; oversized units cannot pretend to be complete."""
    path = tmp_path / "table.txt"
    path.write_text(
        "Units: millions.\n\n|Name|Revenue|\n"
        + "\n".join(f"|Company{i}|{i}|" for i in range(30))
    )
    store = documents.SourceStore(tmp_path / "corpus", chunk_characters=100)
    sid = store.ingest(path)["id"]
    result = reading.window(store, sid, "c10", characters=100)
    assert result["status"] == "partial_parent"
    assert result["association"] == "unknown"
    assert result["continuations"]
    assert any("Name" in p["text"] for p in result["passages"])
    other = reading.window(
        store, sid, continuation=result["continuations"][0], characters=100
    )
    assert other["passages"]
    cursor = json.loads(result["continuations"][0])
    cursor["version"]["hash"] = "wrong"
    with pytest.raises(ValueError, match="version"):
        reading.window(store, sid, continuation=json.dumps(cursor))
    assert (
        reading.window(store, sid, "c10", characters=1)["status"]
        == "oversized_unit"
    )


def test_budget_and_duplicate_cache_with_injected_scores(tmp_path):
    """Pairs and calls differ; cache hits do not consume neural pairs."""
    path = tmp_path / "source.txt"
    path.write_text("Revenue support.")
    store = documents.SourceStore(tmp_path / "corpus")
    store.ingest(path)
    engine = retrieval.Retriever(
        store, config.Settings(reranker_stage_pairs=2), InjectedScorer()
    )
    first = engine.search("Revenue", None, None, time.monotonic() + 30)
    assert first["passages"] and engine.pairs == 1
    engine.search("Revenue", None, None, time.monotonic() + 30)
    assert engine.pairs == 1
    assert (
        engine.search("support", None, None, time.monotonic() + 30)[
            "retrieval_status"
        ]
        == "reranker_pair_limit"
    )


def test_separate_tool_free_completion_and_finite_tool_budget(tmp_path):
    """Research completion transitions, never skips reserved final writing."""
    settings = config.Settings(tool_rounds=3)
    provider = providers.FixtureProvider(
        {
            "company": [
                {"content": "Exploration done"},
                {"content": "Final notes"},
            ]
        }
    )
    runner = workflow.StageRunner(
        settings,
        provider,
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    result = runner.run(
        "company", "company", {"brief": "research"}, tmp_path / "run"
    )
    assert result["output"]["content"] == "Final notes"
    assert len(provider.calls) == 2
    assert provider.calls[-1].allowed_tools == ()


def test_fixed_metadata_overflow_before_call(tmp_path):
    """Original evidence and required questions cannot be silently truncated."""
    state = stage_context.StageContext(
        tmp_path / "state.json", {"brief": "X" * 5000}
    )
    with pytest.raises(ValueError, match="Task"):
        state.request("instructions", {}, "final_notes", 1, 1000)


def sleeping_worker(connection, settings):
    """A non-model child for supervisor tests."""
    del settings
    connection.recv()
    time.sleep(2)
    connection.close()


@pytest.mark.parametrize("failure", ["deadline", "resource", "cancelled"])
def test_local_supervisor_reaps_injected_non_model_child(monkeypatch, failure):
    """Exercise process cleanup with a Python sleeper, not inference."""
    import threading  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(reranking, "_worker", sleeping_worker)
    monkeypatch.setattr(reranking.LocalReranker, "_snapshot", lambda self: None)
    settings = config.Settings(
        reranker_memory_bytes=1 if failure == "resource" else 8 * 1024**3
    )
    scorer = reranking.LocalReranker(settings)
    timer = threading.Timer(0.15, scorer.cancelled.set)
    if failure == "cancelled":
        timer.start()
    try:
        with pytest.raises(reranking.RerankerError, match=failure):
            scorer.score(
                "query",
                [],
                time.monotonic() + (0.15 if failure == "deadline" else 3),
            )
    finally:
        if failure == "cancelled":
            timer.join()
        scorer.close()
    assert scorer.process is None and scorer.connection is None


def test_bounded_reranker_context_never_token_truncates():
    """Count injection exercises sentence windows and explicit oversize."""
    text = (
        "A context sentence. " * 20
        + "The subject supplies the product. "
        + "A qualifier remains. " * 20
    )
    focus = text.index("The subject")
    view = {
        "passages": [{"text": text, "spans": [{"start": 0, "end": len(text)}]}],
        "focus": focus,
        "identity_text": "Original document",
    }
    windows = reranking.bounded_views(
        "product", view, lambda q, t: len(q) + len(t), 200
    )
    assert 1 <= len(windows) <= 2
    assert all("The subject supplies the product." in w for w in windows)
    assert all(len(w) + 7 <= 200 for w in windows)
    assert not reranking.bounded_views(
        "product", view, lambda q, t: len(q) + len(t), 10
    )


def test_stage_tool_cap_and_new_schema(tmp_path):
    """Excess tool requests cannot multiply the stage allowance."""
    import jsonschema  # pylint: disable=import-outside-toplevel

    settings = config.Settings(stage_tool_limit=1, tool_rounds=4)
    call = {
        "name": "calculate",
        "arguments": {"operation": "add", "values": ["1", "2"]},
    }
    provider = providers.FixtureProvider(
        {"company": [{"tool_calls": [call, call]}, {"content": "Notes"}]}
    )
    runner = workflow.StageRunner(
        settings,
        provider,
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    result = runner.run("company", "company", {}, tmp_path / "run")
    usage = artifacts.read(
        tmp_path / "run" / result["path"] / "work-usage.json"
    )
    assert (
        usage["tool_executions"] == 1 and usage["stop_reason"] == "tool_limit"
    )
    envelope = {
        "content": "",
        "tool_calls": [],
        "tasks": [],
        "figures": [],
        "issues": [],
        "coverage_updates": [],
        "stop_reason": None,
    }
    jsonschema.validate(envelope, protocol.output_schema(()))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**envelope, "tool_calls": [call]}, protocol.output_schema(())
        )


def test_conflict_bundle_cannot_lose_one_side(tmp_path):
    """Pressure cannot turn conflict into a solitary supported side."""
    state = stage_context.StageContext(
        tmp_path / "state.json", {"brief": "two interpretations"}
    )
    qid = next(iter(state.data["questions"]))
    ids = [settle(state, passage(i, str(i) * 3000), qid) for i in range(2)]
    state.update_coverage(
        [
            {
                "question_id": qid,
                "state": "conflicting",
                "adequacy": "adequate",
                "bundle_ids": ids,
            }
        ]
    )
    limited = state.build(6000)
    assert limited["questions"][qid]["delivered_state"] != "supported"
    assert not documents.ungroup_passages(limited["settled_evidence"])


def test_stage_local_retrievers_do_not_share_counters(tmp_path):
    """Sequential workers on a runner get independent evidence work records."""
    settings = config.Settings(tool_rounds=2)
    provider = providers.FixtureProvider(
        {"one": {"content": "one"}, "two": {"content": "two"}}
    )
    evidence = tools.EvidenceTools(
        documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
    )
    runner = workflow.StageRunner(settings, provider, evidence)
    runner.run("one", "company", {}, tmp_path / "run", final_notes_only=True)
    runner.run("two", "company", {}, tmp_path / "run", final_notes_only=True)
    assert evidence.retriever.trace_dir is None
    assert evidence.retriever.pairs == 0
