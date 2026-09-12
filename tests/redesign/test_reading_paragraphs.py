"""Recover bounded visual paragraphs without changing original spans."""

import json

# pylint: disable=protected-access

from evidencealpha import documents
from evidencealpha import reading


def test_indented_pdf_paragraph_keeps_continuation_lines(tmp_path):
    """A source parsed into lines still delivers a whole financial paragraph."""
    path = tmp_path / "original.html"
    lines = [
        "Section",
        "Revenue grew.",
        "Profit followed because demand",
        "rose.",
        "Next section",
    ]
    path.write_text("".join(f"<p>{line}</p>" for line in lines))
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(path)["id"]
    metadata = store.root / sid / "source.json"
    source = json.loads(metadata.read_text())
    for i, block in enumerate(source["blocks"]):
        block["page"] = 1
        block["bbox"] = [
            110 if i == 1 else 85,
            i * 23,
            505 if i in (1, 2, 3) else 200,
            i * 23 + 12,
        ]
    metadata.write_text(json.dumps(source))
    result = reading.window(store, sid, "c1", surrounding=0)
    assert [p["text"] for p in result["passages"]] == lines[1:4]
    assert result["status"] == "complete_window"
    for passage in result["passages"]:
        for ref in passage["chunk_refs"]:
            original = store.open_source(sid, ref["chunk_id"])
            assert original["text"] == passage["text"]


def test_paragraph_does_not_cross_page_or_column():
    """Geometric ambiguity remains a boundary, not inferred continuity."""
    a = {
        "kind": "paragraph",
        "page": 1,
        "bbox": [80, 10, 300, 22],
        "start": 0,
        "end": 1,
    }
    b = {
        "kind": "paragraph",
        "page": 2,
        "bbox": [80, 33, 300, 45],
        "start": 2,
        "end": 3,
    }
    assert not reading._same_paragraph(
        a, b, "a b"
    )  # pylint: disable=protected-access
    b.update(page=1, bbox=[320, 10, 540, 22])
    assert not reading._same_paragraph(
        a, b, "a b"
    )  # pylint: disable=protected-access
