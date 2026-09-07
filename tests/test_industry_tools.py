"""The per-attempt tools: admission, evidence collection, observations."""

import asyncio

import pytest

from industry import budget
from industry import records
from industry import snapshots
from industry import tools
from research import web


class FakeBackend:
    """Canned hits; records what was fetched and indexed."""

    def __init__(self):
        self.fetched = []
        self.indexed = []
        self.fail_fetch = None

    def search_web(self, query, max_results):
        del query
        return [
            web.WebResult(
                title="HOYA share",
                url="https://a.example/x?b=1#frag",
                snippet="HOYA 60%",
            ),
            web.WebResult(
                title="Mirror", url="https://b.example/y", snippet="copy"
            ),
        ][:max_results]

    def fetch(self, url, source_id):
        if self.fail_fetch:
            raise self.fail_fetch
        self.fetched.append((url, source_id))
        version = records.SourceVersion(
            id="v1",
            source_id=source_id,
            content_hash="h",
            blob_path="b.html",
            meta_path="m",
            final_url=url,
            content_type="text/html",
            size=10,
            retrieved_at="2026-09-07T00:00:00+00:00",
            extraction_version="v2",
        )
        chunks = [
            snapshots.Chunk(
                0, "HOYA supplies blanks.", "Market", None, "text", ()
            ),
            snapshots.Chunk(
                1,
                "[table]\na | b",
                "Market",
                None,
                "table",
                ("table_merged_cells",),
            ),
        ]
        return version, chunks, "https://a.example/x?b=1"

    def index(self, version, canonical_url, chunks):
        self.indexed.append((version.id, canonical_url, len(chunks)))
        return len(chunks)

    def search_documents(self, query, k, source_url):
        del query, k
        if source_url == "https://none.example/":
            return []
        return [
            snapshots.Hit(
                "HOYA supplies blanks.",
                {
                    "source": "https://a.example/x?b=1",
                    "source_version_id": "v1",
                    "section": "Market",
                    "chunk_index": 0,
                    "page": -1,
                    "kind": "text",
                    "limitations": "",
                },
                0.21,
            ),
            snapshots.Hit(
                "[table]\na | b",
                {
                    "source": "https://a.example/x?b=1",
                    "source_version_id": "v1",
                    "section": "Market",
                    "chunk_index": 1,
                    "page": 3,
                    "kind": "table",
                    "limitations": "table_merged_cells",
                },
                0.55,
            ),
        ]


def handlers(tool_list):
    """Map tool name to handler."""
    return {item.name: item.handler for item in tool_list}


def setup(global_tools=10, per_attempt=10):
    meter = budget.RunMeter(global_tools)
    meter.register("T2.1", per_attempt)
    collector = tools.Collector("T2.1", "T2")
    backend = FakeBackend()
    _, allowed, tool_list = tools.build_tools(
        collector, meter, backend, asyncio.Lock()
    )
    return meter, collector, backend, handlers(tool_list), allowed


def run(coro):
    return asyncio.run(coro)


def text_of(result):
    return result["content"][0]["text"]


def test_allowed_tool_names():
    _, _, _, found, allowed = setup()
    assert set(found) == {"search_web", "search_documents", "fetch_source"}
    assert allowed == [
        "mcp__research__search_web",
        "mcp__research__search_documents",
        "mcp__research__fetch_source",
    ]


def test_search_web_collects_snippets_as_leads():
    _, collector, _, found, _ = setup()
    out = text_of(run(found["search_web"]({"query": "HOYA", "max_results": 2})))
    assert "[E1] HOYA share - https://a.example/x?b=1#frag" in out
    assert collector.web_searches == 1 and len(collector.evidence) == 2
    first = collector.evidence[0]
    assert first.kind == "snippet" and first.limitations == [
        "search_snippet_only"
    ]
    assert (
        collector.sources[first.source_id].canonical_url
        == "https://a.example/x?b=1"
    )
    assert collector.sources[first.source_id].kind == "web_search"


def test_fetch_then_search_documents_yields_passages_with_versions():
    _, collector, backend, found, _ = setup()
    out = text_of(
        run(found["fetch_source"]({"url": "https://a.example/x?b=1#frag"}))
    )
    assert (
        "version v1" in out and "2 chunks" in out and "Sections: Market" in out
    )
    assert "source_url='https://a.example/x?b=1'" in out
    assert backend.fetched == [("https://a.example/x?b=1#frag", "S1")]
    assert backend.indexed == [("v1", "https://a.example/x?b=1", 2)]
    assert collector.fetches == 1 and "v1" in collector.versions
    out = text_of(
        run(
            found["search_documents"](
                {"query": "blanks", "source_url": "https://a.example/x?b=1"}
            )
        )
    )
    assert "[E1]" in out and "distance 0.210 (uncalibrated)" in out
    assert "[E2]" in out and "page 3" in out
    passage, table = collector.evidence
    assert passage.kind == "passage" and passage.source_version_id == "v1"
    assert table.kind == "table" and table.limitations == ["table_merged_cells"]
    assert passage.source_id == table.source_id == "S1"
    assert collector.sources["S1"].kind == "web_page"


def test_search_documents_without_hits_says_so():
    _, _, _, found, _ = setup()
    out = text_of(
        run(
            found["search_documents"](
                {"query": "x", "source_url": "https://none.example/"}
            )
        )
    )
    assert out.startswith("No passages found in https://none.example/")


def test_fetch_refusal_and_failure_are_observations():
    _, collector, backend, found, _ = setup()
    backend.fail_fetch = snapshots.UnsafeTarget("10.0.0.1 is not public")
    out = text_of(run(found["fetch_source"]({"url": "http://internal/x"})))
    assert out.startswith("fetch refused or failed: 10.0.0.1")
    backend.fail_fetch = RuntimeError("boom")
    out = text_of(run(found["fetch_source"]({"url": "https://a.example/z"})))
    assert out.startswith("fetch_source failed: RuntimeError: boom")
    assert collector.fetches == 0 and not collector.versions


def test_meter_refuses_when_allowance_is_spent():
    meter, collector, _, found, _ = setup(global_tools=10, per_attempt=1)
    assert "[E1]" in text_of(run(found["search_web"]({"query": "q"})))
    out = text_of(run(found["search_web"]({"query": "q"})))
    assert out == tools.BUDGET_EXHAUSTED
    assert meter.counts("T2.1") == (1, 1) and collector.web_searches == 1
    meter2, _, _, found2, _ = setup(global_tools=0, per_attempt=5)
    assert (
        text_of(run(found2["fetch_source"]({"url": "https://a.example/x"})))
        == tools.BUDGET_EXHAUSTED
    )
    assert meter2.counts("T2.1") == (0, 1)


def test_bands_come_from_the_calibration_table_only():
    assert tools.band(0.2, "zh", "zh") == "strong"
    assert tools.band(0.45, "zh", "zh") == "weak"
    assert tools.band(0.9, "zh", "zh") == "doubtful"
    assert tools.band(0.2, "fr", "zh") == "uncalibrated"
    assert tools.band(0.2, "en", "") == "uncalibrated"


class FakeVectorStore:
    """Enough of Chroma for the fixture backend: upsert and search."""

    def __init__(self):
        self.docs = {}

    def add_documents(self, documents, ids):
        for doc, doc_id in zip(documents, ids):
            self.docs[doc_id] = doc

    def similarity_search_with_score(self, query, k, **kwargs):
        del query
        where = kwargs.get("filter")
        hits = []
        for doc in self.docs.values():
            if where and doc.metadata.get("source") != where["source"]:
                continue
            hits.append((doc, 0.3 if "HOYA" in doc.page_content else 0.6))
        return sorted(hits, key=lambda h: h[1])[:k]


def test_fixture_backend_serves_only_the_recorded_pages(tmp_path):
    page = (
        b"<html><body><h1>Blanks</h1><p>HOYA supplies EUV mask blanks to "
        b"leading foundries worldwide.</p></body></html>"
    )
    other = (
        b"<html><body><h1>Other</h1><p>An unrelated page about coffee "
        b"shops and their rent.</p></body></html>"
    )
    (tmp_path / "a.html").write_bytes(page)
    (tmp_path / "b.html").write_bytes(other)
    import json  # pylint: disable=import-outside-toplevel

    (tmp_path / "sources.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://a.example/x",
                    "blob": "a.html",
                    "content_type": "text/html",
                    "status": 200,
                },
                {
                    "url": "https://b.example/y",
                    "blob": "b.html",
                    "content_type": "text/html",
                    "status": 200,
                },
                {
                    "url": "https://c.example/z",
                    "blob": "c.html",
                    "content_type": "text/html",
                    "status": 403,
                },
            ]
        )
    )
    store = FakeVectorStore()
    backend = tools.FixtureBackend(
        str(tmp_path), store, str(tmp_path / "sources")
    )
    assert set(backend.pages) == {"https://a.example/x", "https://b.example/y"}
    assert len(store.docs) == 2
    hits = backend.search_web("HOYA blanks", 5)
    assert hits[0].url == "https://a.example/x" and "HOYA" in hits[0].snippet
    version, chunks, canonical = backend.fetch("https://a.example/x", "S1")
    assert (
        canonical == "https://a.example/x"
        and version.chunk_count == len(chunks) == 1
    )
    with pytest.raises(snapshots.FetchError, match="not in the fixture"):
        backend.fetch("https://c.example/z", "S1")
    with pytest.raises(snapshots.FetchError):
        backend.fetch("https://live.example/", "S1")
    docs = backend.search_documents("blanks", 5, "https://a.example/x")
    assert len(docs) == 1 and "HOYA" in docs[0].text
