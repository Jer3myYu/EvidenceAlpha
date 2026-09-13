"""Inventory transport inherits metadata without changing original evidence."""

import copy

from evidencealpha import stage_context


def test_identifying_passage_metadata_roundtrip(tmp_path):
    source = {
        "source_id": "source-1",
        "url": "https://example.test/document",
        "version": {"hash": "bytes", "text_hash": "text"},
        "hash": "bytes",
        "text_hash": "text",
    }
    passage = {
        **source,
        "text": "2025 revenue: 10 EUR. Pilot supply only.",
        "chunk_id": "c1",
        "spans": [{"start": 0, "end": 44, "page": 1}],
    }
    source["identifying_passage"] = passage
    task = {"sources": [source]}
    before = copy.deepcopy(task)
    context = stage_context.StageContext(tmp_path / "state.json", task)
    compact = context._fixed()["sources"][0]
    restored = {
        key: compact["identifying_passage"].get(key, compact.get(key))
        for key in passage
    }
    restored.update(
        hash=compact["version"]["hash"],
        text_hash=compact["version"]["text_hash"],
    )
    assert restored == passage
    assert task == before
