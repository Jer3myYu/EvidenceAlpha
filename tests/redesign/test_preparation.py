"""Preparation cache isolation and cancellation without model inference."""

import json
import time

import pytest

from evidencealpha import config
from evidencealpha import documents
from evidencealpha import preparation
from evidencealpha import reading
from evidencealpha import reranking
from evidencealpha import retrieval


class ForbiddenScorer:
    """Fail if cancelled preparation reaches inference."""

    def score(self, query, views, deadline):
        """Never perform inference in this fixture."""
        raise AssertionError("Scorer must not be admitted")

    def close(self):
        """No process to close."""


@pytest.fixture(name="source")
def original_source(tmp_path):
    """Small original with whole rows and paragraph context."""
    path = tmp_path / "source.html"
    path.write_text(
        "<h1>Original</h1><p>Revenue grew because demand rose.</p>"
        "<table><tr><th>Year</th><th>Revenue USD</th></tr>"
        "<tr><td>2025</td><td>100</td></tr></table>"
    )
    store = documents.SourceStore(tmp_path / "corpus")
    data = store.ingest(path)
    return store, data["id"]


def test_reading_cache_returns_independent_bindings(source):
    """Returned metadata mutations cannot poison subsequent original views."""
    store, sid = source
    expected = reading.window(store, sid, "c0")
    changed = reading.window(store, sid, "c0")
    changed["passages"][0]["chunk_refs"][0]["spans"][0]["start"] = -10
    assert reading.window(store, sid, "c0") == expected
    index = store.reading_index(sid, 8000)
    with pytest.raises(TypeError):
        index.chunk_focus["c0"] = -10


def test_source_metadata_revalidation(source):
    """Changed source metadata cannot leave a stale structural index active."""
    store, sid = source
    old = store.reading_index(sid, 8000)
    path = store.root / sid / "source.json"
    data = json.loads(path.read_text())
    data["blocks"][0]["page"] = 99
    path.write_text(json.dumps(data))
    assert store.reading_index(sid, 8000) is not old
    assert reading.window(store, sid, "c0")["original_page"]["page"] == 99


def test_deadline_before_source_work(source):
    """Expired preparation does not admit a scorer or spend pair allowance."""
    store, sid = source
    runner = retrieval.Retriever(store, config.Settings(), ForbiddenScorer())
    result = runner.search("Revenue", sid, None, time.monotonic() - 1)
    assert result["error"] == "reranker_deadline"
    assert runner.pairs == 0


def test_global_cancel_during_candidate_work(source, monkeypatch):
    """Cancellation reaches preparation before a neural child exists."""
    store, sid = source
    original = store.iter_passages

    def interrupt(source_id, check):
        for item in original(source_id, check):
            reranking.cancel_all()
            yield item

    monkeypatch.setattr(store, "iter_passages", interrupt)
    runner = retrieval.Retriever(store, config.Settings(), ForbiddenScorer())
    result = runner.search("Revenue", sid, None, None)
    assert result["error"] == "reranker_cancelled"
    assert runner.pairs == 0


def test_interrupted_index_is_not_cached(source):
    """Discard partial indexes; later reads remain complete."""
    store, sid = source
    calls = 0

    def interrupt():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise preparation.Stopped("reranker_deadline")

    with pytest.raises(preparation.Stopped):
        store.reading_index(sid, 8000, interrupt)
    assert reading.window(store, sid, "c0")["passages"]
