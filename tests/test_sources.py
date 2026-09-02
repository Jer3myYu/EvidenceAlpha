"""Phase 6.5 tests: stable source ids and label normalisation."""

from rag import models
from research import agent
from research import sources
from research import web


def normalize(*observations: str, registry=None):
    return sources.normalize_observations(list(observations), registry or {})


def ingested(url: str) -> str:
    return (
        f"Ingested 5 chunks from {url} into the local document collection. "
        "Use search_documents to retrieve from it."
    )


def test_same_round_local_label_for_different_files_gets_different_ids():
    texts, registry = normalize(
        "[D1] source: a.txt (distance 0.1000)\nAlpha.",
        "[D1] source: b.md (distance 0.2000)\nBeta.",
    )

    assert texts == [
        "[S1] source: a.txt (distance 0.1000)\nAlpha.",
        "[S2] source: b.md (distance 0.2000)\nBeta.",
    ]
    assert registry["S1"].local_document_id == "a.txt"
    assert registry["S2"].local_document_id == "b.md"
    assert registry["S1"].canonical_url is None


def test_same_canonical_url_across_web_ingest_and_documents_is_one_source():
    url = "https://kraneshares.com/humanoid-2026"
    texts, registry = normalize(
        f"[W1] Humanoid Robotics in 2026 - {url}\nSnippet.",
        ingested(url),
        f"[D1] source: {url} (distance 0.3746)\nChunk text.",
        f"[D2] source: {url} (page 3) (distance 0.5000)\nPage text.",
    )

    assert list(registry) == ["S1"]
    record = registry["S1"]
    assert record.canonical_url == url
    assert record.title == "Humanoid Robotics in 2026"
    assert record.seen_via == ("web", "ingest", "documents")
    assert texts[0].startswith("[S1] Humanoid Robotics in 2026 - ")
    assert texts[1] == ingested(url)
    assert texts[2].startswith("[S1] source: ") and texts[3].startswith(
        "[S1] source: "
    )


def test_bare_url_title_is_upgraded_when_a_web_title_arrives_later():
    url = "https://x.example/report.pdf"
    registry = normalize(
        f"[D1] source: {url} (page 1) (distance 0.4000)\nA.",
        f"[W1] Annual report - {url}\nB.",
    )[1]

    assert registry["S1"].title == "Annual report"
    assert registry["S1"].seen_via == ("documents", "web")


def test_repeated_local_document_across_rounds_and_pages_reuses_one_id():
    registry = normalize(
        "[D1] source: a.md (distance 0.1000)\nOne.",
        "[D2] source: r.pdf (page 1) (distance 0.3000)\nPage one.",
    )[1]
    texts, registry = normalize(
        "[D1] source: r.pdf (page 3) (distance 0.2000)\nPage three.",
        "[D2] source: a.md (distance 0.4000)\nOne again.",
        registry=registry,
    )

    assert list(registry) == ["S1", "S2"]
    assert texts == [
        "[S2] source: r.pdf (page 3) (distance 0.2000)\nPage three.",
        "[S1] source: a.md (distance 0.4000)\nOne again.",
    ]


def test_unprovable_identity_allocates_and_provable_identity_merges():
    registry = normalize(
        "[W1] A - https://a.com/x\n.",
        "[W1] B - https://a.com/x/\n.",
        "[W1] C - http://a.com/x\n.",
        "[W1] D - https://www.a.com/x\n.",
        "[W1] E - https://a.com/x?v=2\n.",
        "[W1] F - https://A.COM/x#top\n.",
        "[W1] G - HTTPS://a.com/x\n.",
    )[1]

    assert len(registry) == 5
    assert registry["S1"].canonical_url == "https://a.com/x"
    assert registry["S1"].seen_via == ("web",)
    assert sources.canonical_url("https://A.COM/x#top") == "https://a.com/x"
    assert sources.canonical_url("https://a.com/x/") == "https://a.com/x/"


def test_round_trip_through_the_formatters_changes_only_labels():
    chunks = [
        models.RetrievedChunk("Acme makes arms.", "a.txt", 0.1),
        models.RetrievedChunk("Page text.", "r.pdf (page 2)", 0.42),
        models.RetrievedChunk("Web chunk.", "https://h.example/a", 0.5),
    ]
    results = [
        web.WebResult("Humanoid Index", "https://h.example/a", "108 firms."),
        web.WebResult("Forbes - top list", "https://f.example/b", "16."),
    ]
    raw = [agent.format_chunks(chunks), agent.format_results(results)]

    texts, registry = normalize(*raw)

    restored = [
        texts[0]
        .replace("[S1]", "[D1]", 1)
        .replace("[S2]", "[D2]", 1)
        .replace("[S3]", "[D3]", 1),
        texts[1].replace("[S3]", "[W1]", 1).replace("[S4]", "[W2]", 1),
    ]
    assert restored == raw
    assert list(registry) == ["S1", "S2", "S3", "S4"]
    assert registry["S3"].seen_via == ("documents", "web")
    assert registry["S4"].title == "Forbes - top list"


def test_lines_that_only_resemble_headers_are_left_alone():
    body = (
        "[D1] source: a.txt (distance 0.1000)\n"
        "Quoted in the text: [D1] source: fake.txt (distance 0.1)\n"
        "[D2] source: no distance here\n"
        "[W1] Title without a url\n"
        "[W2] Title - ftp://not.http/x\n"
        "Ingested 3 chunks from https://x.example/p\n"
        "See [D1] and [W1] above."
    )

    texts, registry = normalize(body)

    assert texts[0].split("\n")[0] == "[S1] source: a.txt (distance 0.1000)"
    assert texts[0].split("\n")[1:] == body.split("\n")[1:]
    assert list(registry) == ["S1"]
    assert normalize("No passages found.", "No web results found.") == (
        ["No passages found.", "No web results found."],
        {},
    )
