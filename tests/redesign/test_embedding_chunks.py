"""Structure/token chunk contracts; injected vectors are not model quality."""

import dataclasses
import time

import pytest

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import dense_runtime
from evidencealpha import documents
from evidencealpha import embedding_chunks
from evidencealpha import preparation
from evidencealpha import reading
from evidencealpha import retrieval
from evidencealpha import vector_index


def test_units_preserve_originals_and_dense_context(tmp_path, monkeypatch):
    """New chunks recover long originals through normal candidate selection."""
    source = tmp_path / "source.md"
    source.write_text(
        "# Capacity\n\n"
        + "Validation remains ongoing. " * 15
        + "\n\n| Period | Revenue (USD million) |\n|---|---|\n| FY2025 | 12 |"
    )
    store = documents.SourceStore(tmp_path / "sources")
    sid = store.ingest(source)["id"]
    before = artifacts.tree_hash(store.root)
    units = embedding_chunks.build_units(store, len, 100, preparation.noop)
    assert units and all(
        len(embedding_chunks.text_for(store, u)) <= 100 for u in units.values()
    )
    for block in store.open_source(sid)["source"]["blocks"]:
        original = store.reading_index(sid, 8000).text
        covered = {
            i
            for u in units.values()
            for s in u["spans"]
            if s["block_id"] == block["id"]
            for i in range(s["start"], s["end"])
        }
        assert all(
            i in covered
            for i in range(block["start"], block["end"])
            if not original[i].isspace()
        )
    unit = next(u for u in units.values() if u["kind"] == "paragraph")
    view = reading.window(store, sid, unit["chunk_id"], characters=8000)
    expanded = embedding_chunks.extend_reading(
        store, unit, view, 8000, preparation.noop
    )
    for span in unit["spans"]:
        assert any(
            p["spans"][0]["start"] <= span["start"]
            and p["spans"][0]["end"] >= span["end"]
            for p in expanded["passages"]
        )
    signature = {
        "model": "fixture",
        "revision": "fixture",
        "dimension": 2,
        "input_policy": embedding_chunks.VERSION,
    }
    path = tmp_path / "index"
    vector_index.ReferenceIndex.build(
        path, store, signature, {k: [1.0, 0.0] for k in units}, units
    )
    reopened = vector_index.ReferenceIndex(path, store, signature)
    hits = reopened.query([1.0, 0.0], sid, 10)
    assert hits and all(h["embedding_unit"] for h in hits)
    assert artifacts.tree_hash(store.root) == before

    def worker(*args, **kwargs):
        del args, kwargs
        return {
            "hits": [
                {
                    "source_id": sid,
                    "chunk_id": unit["chunk_id"],
                    "unit": unit,
                    "unit_id": artifacts.digest(unit),
                    "distance": 0.0,
                }
            ],
            "metrics": {},
            "supervision": {},
            "index_hash": "fixture",
        }

    monkeypatch.setattr(dense_runtime, "supervised", worker)
    settings = dataclasses.replace(
        config.Settings(),
        vector_index_path=str(path),
        dense_model_path="fixture",
        dense_model_revision="a" * 40,
        retrieval_mode="degraded_lexical",
    )
    engine = retrieval.Retriever(store, settings)
    try:
        result = engine.search("zzzzzzz", None, None, time.monotonic() + 30)
        assert result["passages"]
        assert any("Validation" in p["text"] for p in result["passages"])
    finally:
        engine.close()


def test_supervisor_cancels_without_starting_model(tmp_path):
    """Expired admission launches no model and leaves no child."""
    with pytest.raises(preparation.Stopped):
        dense_runtime.supervised(
            {},
            "not-a-python",
            time.monotonic() + 1,
            1,
            lambda: (_ for _ in ()).throw(preparation.Stopped("cancelled")),
            tmp_path,
        )


def test_running_worker_is_reaped_on_deadline(tmp_path, monkeypatch):
    """Exercise actual child termination without loading a neural model."""
    import subprocess
    import sys

    processes = []
    real_popen = subprocess.Popen

    def sleeper(*args, **kwargs):
        del args
        process = real_popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(dense_runtime.subprocess, "Popen", sleeper)
    with pytest.raises(TimeoutError, match="deadline"):
        dense_runtime.supervised(
            {},
            sys.executable,
            time.monotonic() + 0.2,
            8 * 1024**3,
            record_dir=tmp_path,
        )
    assert len(processes) == 1 and processes[0].poll() is not None
