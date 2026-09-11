"""Original-source fidelity, structural retrieval and fixed-corpus tools."""

import pathlib

import pytest

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import render
from evidencealpha import tools

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures" / "redesign"


def test_chinese_table_locations_and_context(tmp_path):
    """Headers."""
    store = documents.SourceStore(tmp_path, chunk_characters=80)
    source = store.ingest(FIXTURES / "manufacturing.html")
    found = store.search_evidence("第三方 2025半年 万元")
    assert any("第三方" in p["text"] for p in found)
    assert any(
        "2025半年" in p["text"] and "收入（万元）" in p["text"] for p in found
    )
    canonical = store.open_source(source["id"])["text"]
    for passage in found:
        assert passage["text"] == "\n".join(
            canonical[s["start"] : s["end"]] for s in passage["spans"]
        )
    store.add_context(
        source["id"],
        "Generated navigation only",
        ["b0"],
        {"model": "fixture"},
        "test",
    )
    passage = store.open_source(source["id"], "c0")
    assert passage["generated_context"] == "Generated navigation only"
    assert "Generated" not in passage["text"]
    with pytest.raises(ValueError, match="unknown original blocks"):
        store.add_context(source["id"], "bad", ["invented"], {}, "test")


def test_source_mutation_and_path_escape_rejected(tmp_path):
    """Saved source versions are immutable, including original bytes."""
    store = documents.SourceStore(tmp_path)
    source = store.ingest(FIXTURES / "service.html")
    with pytest.raises(ValueError, match="escapes"):
        store.open_source("../outside")
    (tmp_path / source["id"] / "text.txt").write_text("changed")
    with pytest.raises(ValueError, match="changed in place"):
        store.open_source(source["id"])


def test_pdf_chinese_extraction_has_page_and_bbox(tmp_path):
    """Digital Chinese PDF extraction reports canonical Unicode."""
    markdown = tmp_path / "sample.md"
    markdown.write_text(
        "# 中文来源样本\n\n期间：2025全年。单位：万元。\n\n|主体|收入|\n|---|---|\n|甲|120|\n"
    )
    result = render.export(markdown)
    assert result["pdf_status"] == "complete"
    store = documents.SourceStore(tmp_path / "corpus")
    source = store.ingest(markdown.with_suffix(".pdf"))
    passage = store.search_evidence("2025全年")[0]
    assert passage["spans"][0]["page"] == 1
    assert len(passage["spans"][0]["bbox"]) == 4
    assert "Unicode" in passage["spans"][0]["basis"]
    assert source["warnings"]


def test_fixed_corpus_and_exact_trace_replay(tmp_path):
    """External acquisition is rejected at dispatch."""
    evidence = tools.EvidenceTools(
        documents.SourceStore(tmp_path), config.Settings(), "fixed-corpus"
    )
    with pytest.raises(ValueError, match="unavailable"):
        evidence.call("fetch_source", {"url": "https://example.org"})
    trace = artifacts.TraceReplay(
        [
            {
                "name": "open_source",
                "arguments": {"id": "one"},
                "sources": {"one": "v1"},
                "result": "original",
            }
        ]
    )
    assert trace.call("open_source", {"id": "one"}, {"one": "v1"}) == "original"
    with pytest.raises(ValueError, match="Replay miss"):
        trace.call("open_source", {"id": "one"}, {"one": "v2"})
    assert (
        evidence.call(
            "calculate", {"operation": "divide", "values": ["1", "4"]}
        )["result"]
        == "0.25"
    )


def test_missing_asset_never_modifies_markdown(tmp_path):
    """Renderer errors retain the canonical report."""
    path = tmp_path / "report.md"
    original = "# Report\n\n![missing](figures/missing.png)\n"
    path.write_text(original)
    with pytest.raises(ValueError, match="Missing report asset"):
        render.export(path)
    assert path.read_text() == original


def test_extraction_failure_preserves_original_bytes(tmp_path):
    """Unparseable downloaded sources remain available for parser debugging."""
    source = tmp_path / "empty.html"
    source.write_bytes(b"<html></html>")
    store = documents.SourceStore(tmp_path / "corpus")
    with pytest.raises(ValueError, match="No extractable text"):
        store.ingest(source)
    assert (
        next(store.root.glob("*/original.html")).read_bytes()
        == source.read_bytes()
    )
    assert next(store.root.glob("*/extraction-failure.json")).exists()
