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


def test_span_table_roundtrip_preserves_bindings():
    from evidencealpha import documents

    passages = []
    for index in range(30):
        spans = [
            {"start": 10000, "end": 10080, "page": 12},
            {
                "start": 11000 + index * 10,
                "end": 11009 + index * 10,
                "page": 12,
            },
        ]
        passages.append(
            {
                "source_id": "s",
                "version": {"hash": "v"},
                "text": f"Original row {index}",
                "spans": spans,
                "chunk_refs": [{"chunk_id": f"c{index}", "spans": spans}],
            }
        )
    original = documents.group_passages(passages)
    compact = documents.compact_passages(original)
    assert any("span_table" in s for s in compact["sources"])
    assert documents.ungroup_passages(compact) == documents.ungroup_passages(
        original
    )
    assert documents.ungroup_passages(
        documents.compact_passages(compact)
    ) == documents.ungroup_passages(original)


def test_explicit_source_aliases_do_not_follow_inventory_order():
    from evidencealpha import presentation

    first, second = "a" * 64, "b" * 64
    body = "Fact [S1:c3]. Both [S2:c4-c5].\n\n" + (
        "- **S1**：Document B, `bbbbbbbb…bbbb`.\n"
        "- **S2**：Documents A/B, `aaaaaaaa…aaaa` / `bbbbbbbb…bbbb`.\n"
    )
    resolved, mapping = presentation.resolve_declared_sources(
        body, [first, second]
    )
    assert f"Fact [{second}:c3]" in resolved
    assert f"[{first}:c4-c5；{second}:c4-c5]" in resolved
    assert mapping["S1"] == [second]
