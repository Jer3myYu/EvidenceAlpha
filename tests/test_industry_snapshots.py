"""Safe fetch, immutable snapshots, extraction, chunking, versioned index."""

import dataclasses
import json
import pathlib

import pytest

from industry import records
from industry import snapshots


def resolver_for(mapping):
    def resolve(host):
        return mapping[host]

    return resolve


class FakeResponse:
    """A streamed response with a status, headers, and a body."""

    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    """Serves canned responses by URL and records the calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        return self.routes[url]


PUBLIC = {"example.com": ["93.184.216.34"], "mirror.example": ["93.184.216.35"]}


@pytest.mark.parametrize(
    "url,hosts",
    [
        ("http://127.0.0.1/x", {}),
        ("http://10.0.0.5/x", {}),
        ("http://[::1]/x", {}),
        ("http://169.254.169.254/latest", {}),
        ("http://internal.corp/x", {"internal.corp": ["192.168.1.9"]}),
        (
            "http://both.example/x",
            {"both.example": ["93.184.216.34", "10.1.1.1"]},
        ),
        ("ftp://example.com/x", {}),
        ("file:///etc/passwd", {}),
    ],
)
def test_unsafe_targets_are_refused(url, hosts):
    with pytest.raises(snapshots.UnsafeTarget):
        snapshots.check_url(url, resolver_for(hosts))


def test_redirect_hops_are_checked_and_bounded():
    routes = {
        "https://example.com/a": FakeResponse(302, {"location": "/b"}),
        "https://example.com/b": FakeResponse(
            302, {"location": "http://internal.corp/c"}
        ),
    }
    session = FakeSession(routes)
    hosts = {**PUBLIC, "internal.corp": ["10.0.0.1"]}
    with pytest.raises(snapshots.UnsafeTarget):
        snapshots.fetch("https://example.com/a", session, resolver_for(hosts))
    loop = {
        f"https://example.com/{i}": FakeResponse(302, {"location": f"/{i + 1}"})
        for i in range(6)
    }
    with pytest.raises(snapshots.FetchError, match="redirects"):
        snapshots.fetch(
            "https://example.com/0", FakeSession(loop), resolver_for(PUBLIC)
        )


def test_size_cap_and_http_errors():
    big = FakeResponse(200, {"content-type": "text/html"}, b"x" * 300)
    session = FakeSession({"https://example.com/big": big})
    with pytest.raises(snapshots.FetchError, match="cap"):
        snapshots.fetch(
            "https://example.com/big",
            session,
            resolver_for(PUBLIC),
            max_bytes=200,
        )
    assert big.closed
    session = FakeSession({"https://example.com/404": FakeResponse(404)})
    with pytest.raises(snapshots.FetchError, match="HTTP 404"):
        snapshots.fetch(
            "https://example.com/404", session, resolver_for(PUBLIC)
        )


HTML = b"""<html><head><title>T</title><script>alert(1)</script></head><body>
<nav>menu menu menu menu menu menu</nav>
<h1>Photomask blanks</h1>
<p>HOYA supplies EUV mask blanks to leading foundries worldwide.</p>
<h2>Market share</h2>
<table><tr><th>Company</th><th>Share</th></tr><tr><td>HOYA</td><td>60%</td></tr>
<tr><td colspan="2">AGC 16%</td></tr></table>
<ul><li>Shin-Etsu holds about twenty percent of the market.</li></ul>
</body></html>"""


def test_html_extraction_keeps_headings_tables_and_flags():
    blocks = snapshots.extract_html(HTML)
    kinds = [(b.kind, b.section) for b in blocks]
    assert ("text", "Photomask blanks") in kinds
    table = [b for b in blocks if b.kind == "table"][0]
    assert table.section == "Market share"
    assert "Company | Share" in table.text and "HOYA | 60%" in table.text
    assert "table_merged_cells" in table.limitations
    assert "table_unequal_rows" in table.limitations
    assert not any("alert" in b.text or "menu" in b.text for b in blocks)
    assert any("Shin-Etsu" in b.text for b in blocks)


def test_text_extraction_and_chunking_respect_blocks():
    text = b"# Intro\n\n" + b"a" * 1000 + b"\n\n## Next\n\nshort paragraph here"
    blocks = snapshots.extract_text(text)
    assert [b.section for b in blocks] == ["Intro", "Next"]
    chunks = snapshots.chunk_blocks(blocks, size=400, overlap=50)
    assert all(len(c.text) <= 400 for c in chunks)
    assert (
        chunks[-1].section == "Next"
        and chunks[-1].text == "short paragraph here"
    )
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert (
        snapshots.language_of("光掩模") == "zh"
        and snapshots.language_of("mask") == "en"
    )


def fetched(url, body, content_type="text/html"):
    return snapshots.Fetched(
        url=url,
        final_url=url,
        content_type=content_type,
        content=body,
        retrieved_at="2026-09-07T00:00:00+00:00",
    )


def test_snapshot_is_content_addressed_and_metadata_immutable(tmp_path):
    root = str(tmp_path / "sources")
    first = snapshots.store_snapshot(
        fetched("https://example.com/a", HTML), "S1", root
    )
    blob = pathlib.Path(first.blob_path)
    assert blob.exists() and blob.suffix == ".html"
    meta = json.loads(pathlib.Path(first.meta_path).read_text(encoding="utf-8"))
    assert (
        meta["canonical_url"] == "https://example.com/a"
        and meta["id"] == first.id
    )
    assert "source_id" not in meta, "attempt-local ids stay out of the record"
    assert meta["chunk_count"] == 0 and meta["publisher"] is None
    # Same URL, same bytes: same version, nothing rewritten.
    blob_mtime = blob.stat().st_mtime_ns
    again = snapshots.store_snapshot(
        fetched("https://example.com/a", HTML), "S1", root
    )
    assert again.id == first.id and blob.stat().st_mtime_ns == blob_mtime
    # Same URL, different bytes: a new version, the old blob untouched.
    changed = snapshots.store_snapshot(
        fetched("https://example.com/a", HTML + b"<!-- v2 -->"), "S1", root
    )
    assert changed.id != first.id and changed.content_hash != first.content_hash
    assert blob.exists() and pathlib.Path(changed.blob_path).exists()
    # Different URL, same bytes: shared blob, separate metadata.
    mirror = snapshots.store_snapshot(
        fetched("https://mirror.example/b", HTML), "S2", root
    )
    assert (
        mirror.blob_path == first.blob_path
        and mirror.meta_path != first.meta_path
    )
    assert len(list((tmp_path / "sources" / "versions").iterdir())) == 3
    assert len(list((tmp_path / "sources" / "blobs").iterdir())) == 2


def test_pdf_is_detected_by_magic_bytes():
    assert snapshots.is_pdf(
        "application/octet-stream", "https://x/y", b"%PDF-1.7 ..."
    )
    assert snapshots.is_pdf("", "https://x/y.PDF", b"")
    assert not snapshots.is_pdf("text/html", "https://x/y", b"<html>")


class FakeStore:
    """Records upserted documents by id."""

    def __init__(self):
        self.docs = {}

    def add_documents(self, documents, ids):
        for doc, doc_id in zip(documents, ids):
            self.docs[doc_id] = doc


def test_index_version_upserts_by_version_and_index():
    store = FakeStore()
    version = records.SourceVersion(
        id="v1",
        source_id="S1",
        content_hash="h",
        blob_path="b",
        meta_path="m",
        final_url="u",
        content_type="text/html",
        size=1,
        retrieved_at="2026-09-07T00:00:00+00:00",
        extraction_version="v2",
    )
    chunks = snapshots.chunk_blocks(snapshots.extract_html(HTML))
    count = snapshots.index_version(
        store, version, "https://example.com/a", chunks
    )
    assert count == len(chunks) and set(store.docs) == {
        f"v1:{i}" for i in range(count)
    }
    table_doc = [
        d for d in store.docs.values() if d.metadata["kind"] == "table"
    ][0]
    assert (
        table_doc.metadata["limitations"]
        == "table_merged_cells,table_unequal_rows"
    )
    assert table_doc.metadata["section"] == "Market share"
    assert table_doc.metadata["source_version_id"] == "v1"
    # Indexing again (a retry or a resume) changes nothing.
    snapshots.index_version(store, version, "https://example.com/a", chunks)
    assert len(store.docs) == count


HTML_META = b"".join(
    [
        b'<html><head><meta property="og:site_name" content="Sina Finance">',
        b'<meta property="article:published_time" ',
        b'content="2025-05-19T08:00:00+08:00"></head><body><h1>T</h1>',
        b"<p>Body text long enough to be a block here.</p></body></html>",
    ]
)


def test_html_metadata_and_acquire_bytes_record_publisher_and_count(tmp_path):
    publisher, published = snapshots.html_metadata(HTML_META)
    assert publisher == "Sina Finance" and published.startswith("2025-05-19")
    assert snapshots.html_metadata(
        b"<html><body><time datetime='2024-01-02'>x</time></body></html>"
    ) == (None, "2024-01-02")
    session = FakeSession(
        {
            "https://example.com/m": FakeResponse(
                200, {"content-type": "text/html"}, HTML_META
            )
        }
    )
    version, chunks = snapshots.acquire_bytes(
        "https://example.com/m",
        "S1",
        str(tmp_path),
        session,
        resolver_for(PUBLIC),
    )
    assert version.chunk_count == len(chunks) == 1
    assert snapshots.read_metadata(version) == (
        "Sina Finance",
        "2025-05-19T08:00:00+08:00",
    )


def test_ingest_local_snapshots_and_indexes_a_file(tmp_path):
    document = tmp_path / "note.md"
    document.write_text(
        "# Intro\n\nAcme makes robots for warehouses.", encoding="utf-8"
    )
    store = FakeStore()
    version, count = snapshots.ingest_local(
        str(document), store, str(tmp_path / "sources")
    )
    assert count == 1 and version.chunk_count == 1
    assert version.final_url.startswith(
        "file://"
    ) and version.final_url.endswith("note.md")
    assert pathlib.Path(version.blob_path).exists()
    assert list(store.docs.values())[0].metadata["section"] == "Intro"
    with pytest.raises(ValueError, match="Unsupported"):
        snapshots.ingest_local(str(tmp_path / "x.docx"), store, str(tmp_path))


def test_a_refetch_reports_the_recorded_version_not_the_new_fetch(tmp_path):
    # C1 round 1, finding 6: the metadata file was never rewritten, but
    # the returned version carried the new fetch's retrieval time,
    # content type and chunk count, and index_version stamped those
    # onto the chunks already indexed under that version id.
    root = str(tmp_path / "sources")
    first = snapshots.store_snapshot(
        fetched("https://example.com/a", HTML), "S1", root, chunk_count=7
    )
    later = dataclasses.replace(
        fetched("https://example.com/a", HTML),
        retrieved_at="2026-10-01T00:00:00+00:00",
        content_type="text/plain",
    )
    again = snapshots.store_snapshot(later, "S2", root, chunk_count=0)
    assert again.id == first.id
    assert again.retrieved_at == first.retrieved_at
    assert again.content_type == first.content_type
    assert again.extraction_version == first.extraction_version
    assert again.chunk_count == first.chunk_count == 7
    # The registry id of the source stays attempt-local.
    assert again.source_id == "S2"
    recorded = json.loads(
        pathlib.Path(first.meta_path).read_text(encoding="utf-8")
    )
    assert recorded["retrieved_at"] == first.retrieved_at
    assert recorded["content_type"] == "text/html"


def test_recorded_bytes_are_read_again_the_way_they_were_read(tmp_path):
    # C1 round 2, finding 4: extraction ran before the stored metadata
    # was consulted, so the same bytes served as text/plain re-extracted
    # under the existing version id and replaced its chunks with raw
    # HTML, leaving them inconsistent with its recorded content type.
    fragment = b"<h2>Market</h2><p>HOYA supplies blanks.</p><p>AGC follows.</p>"
    root = str(tmp_path / "sources")

    def acquire(source_id, content_type):
        return snapshots.acquire_bytes(
            "https://example.com/a",
            source_id,
            root,
            session=FakeSession(
                {
                    "https://example.com/a": FakeResponse(
                        200, {"content-type": content_type}, fragment
                    )
                }
            ),
            resolver=resolver_for(PUBLIC),
        )

    first, chunks = acquire("S1", "text/html")
    assert first.content_type.startswith("text/html")
    assert chunks[0].text == "HOYA supplies blanks."
    assert chunks[0].section == "Market"
    again, later = acquire("S2", "text/plain")
    assert again.id == first.id
    assert again.content_type == first.content_type
    assert again.chunk_count == first.chunk_count
    # Read as text/plain the same bytes would chunk as raw markup under
    # the very same chunk ids; the recorded interpretation governs.
    assert [c.text for c in later] == [c.text for c in chunks]
    assert [c.section for c in later] == [c.section for c in chunks]
    assert [c.index for c in later] == [c.index for c in chunks]
    assert "<p>" not in later[0].text
    # The registry id of the source stays attempt-local.
    assert again.source_id == "S2"
