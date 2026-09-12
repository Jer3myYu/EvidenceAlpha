"""Real Chroma contract trial; injected vectors are not model evaluation."""

import dataclasses
import pathlib
import time

import pytest

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import reading
from evidencealpha import retrieval
from evidencealpha import stage_context
from evidencealpha import tools

vector_index = pytest.importorskip(
    "evidencealpha.vector_index", exc_type=ImportError
)

SIGNATURE = {
    "model": "deterministic-fixture-only",
    "revision": "1",
    "dimension": 3,
    "input_policy": "hand-assigned-vectors-no-neural-inference",
    "normalization": "unit",
}


class Scorer:
    """Inject order-preserving scores through the normal reading pipeline."""

    def score(self, query, views, deadline):
        """Score without a model call."""
        assert query and time.monotonic() < deadline
        return [
            {"score": float(len(views) - i), "pairs": 1}
            for i in range(len(views))
        ]

    def close(self):
        """No worker is started."""


@pytest.fixture(name="prepared")
def prepared_fixture(tmp_path):
    """Build a disposable three-source index with exact known originals."""
    store = documents.SourceStore(tmp_path / "sources")
    texts = [
        "# Operations\n\nCapacity ramp remains under customer validation.",
        "# Finance\n\nRevenue was 12 million USD for FY2025, consolidated.",
        "# Delivery\n\nProducts are sampled; mass production is not claimed.",
    ]
    ids = []
    for i, text in enumerate(texts):
        path = tmp_path / f"source-{i}.md"
        path.write_text(text)
        ids.append(store.ingest(path)["id"])
    vectors = {
        identifier: [float(meta["source_id"] == source) for source in ids]
        for identifier, meta in vector_index.bindings(store).items()
    }
    path = tmp_path / "index"
    vector_index.ReferenceIndex.build(path, store, SIGNATURE, vectors)
    return store, path, ids


def test_persistent_trial_and_normal_handoff(prepared, tmp_path):
    """Dense-only candidates reach real structural reading and settlement."""
    started = time.monotonic()
    store, path, ids = prepared
    index = vector_index.ReferenceIndex(path, store, SIGNATURE)
    stored = index.collection.get(include=["documents"])
    assert all(document is None for document in stored["documents"])
    scoped = index.query([0.0, 1.0, 0.0], ids[0], 64)
    assert scoped and all(p["passage"]["source_id"] == ids[0] for p in scoped)
    # An unmatched token ensures this case actually exercises dense nomination.
    query = "zzzzzz"
    assert retrieval.candidates(store, query, None, 64) == []
    hybrid = vector_index.HybridCandidates(index, lambda _: [0.0, 1.0, 0.0])
    engine = retrieval.Retriever(
        store, config.Settings(), Scorer(), candidate_provider=hybrid
    )
    engine.trace_dir = tmp_path / "retrieval"
    try:
        source_tools = tools.EvidenceTools(store, config.Settings(), "fixture")
        source_tools.retriever.close()
        source_tools.retriever = engine
        result = source_tools.call(
            "search_evidence",
            {"query": query, "question_id": "q1"},
            time.monotonic() + 30,
        )
    finally:
        engine.close()
    state = stage_context.StageContext(
        tmp_path / "context-state.json",
        {"questions": [{"id": "q1", "question": query}]},
    )
    state.settle(result, "q1")
    actual = documents.ungroup_passages(state.data["evidence"])
    assert actual
    _, writing = state.request(
        "Write sourced notes", {}, "final_notes", 1, 100000
    )
    selected = documents.ungroup_passages(writing["settled_evidence"])

    # Writing deterministically reorders and compacts metadata. Compare exact
    # evidence identity, source, text, spans and chunk bindings, not list order.
    def evidence_map(passages):
        fields = ("source_id", "version", "url", "text", "spans")
        return {
            reading.reference(p): {
                **{k: p.get(k) for k in fields},
                "chunk_refs": [
                    (
                        r["chunk_id"],
                        [
                            (s["start"], s["end"], s.get("page"))
                            for s in r["spans"]
                        ],
                    )
                    for r in p["chunk_refs"]
                ],
            }
            for p in passages
        }

    assert evidence_map(selected) == evidence_map(actual)
    assert any("12 million USD" in p["text"] for p in actual)
    for passage in actual:
        full = store.open_source(passage["source_id"])["text"]
        for span in passage["spans"]:
            assert full[span["start"] : span["end"]] in passage["text"]
    trace = artifacts.read(pathlib.Path(result["trace"]))
    assert all("candidate_provenance" in c for c in trace["candidates"])
    artifacts.write(
        tmp_path / "TRIAL.json",
        {
            "validation": "Real Chroma query; injected vectors/scorer",
            "index": index.manifest,
            "returned_sources": sorted({p["source_id"] for p in actual}),
            "source_texts_in_chroma": False,
            "original_spans_preserved": True,
            "stage_context_settled": True,
            "writing_selection_preserved": True,
            "seconds_query_through_settlement": time.monotonic() - started,
            "neural_inference": False,
        },
    )


def test_reject_incomplete_signature_and_changed_index(prepared, tmp_path):
    """Never accept a partial build or altered index as a ready snapshot."""
    store, path, _ = prepared
    with pytest.raises(FileNotFoundError):
        vector_index.ReferenceIndex(tmp_path / "absent", store, SIGNATURE)
    with pytest.raises(ValueError, match="signature"):
        vector_index.ReferenceIndex(path, store, {**SIGNATURE, "revision": "2"})
    index = vector_index.ReferenceIndex(path, store, SIGNATURE)
    identifier = index.collection.get()["ids"][0]
    index.collection.update(ids=[identifier], embeddings=[[0.5, 0.5, 0.5]])
    with pytest.raises(ValueError, match="contents"):
        vector_index.ReferenceIndex(path, store, SIGNATURE)


def test_reject_changed_sources_and_invalid_scope(prepared):
    """Filters apply before ranking; changed originals fail closed."""
    store, path, ids = prepared
    index = vector_index.ReferenceIndex(path, store, SIGNATURE)
    with pytest.raises(ValueError, match="scope"):
        index.query([1.0, 0.0, 0.0], "not-authorized", 2)
    with pytest.raises(ValueError, match="dimension"):
        index.query([1.0], None, 2)
    source = store.open_source(ids[0])["source"]
    (store.root / ids[0] / source["text_path"]).write_text("modified")
    with pytest.raises(ValueError, match="changed"):
        index.query([1.0, 0.0, 0.0], ids[0], 2)


def test_lexical_default_and_cancellation(prepared):
    """Default candidate behavior is unchanged and checks propagate."""
    store, path, _ = prepared
    settings = dataclasses.replace(config.Settings(), retrieval_limit=2)
    engine = retrieval.Retriever(store, settings, Scorer())
    assert engine.candidate_provider is retrieval.candidates
    explicit = retrieval.Retriever(
        store, settings, Scorer(), candidate_provider=retrieval.candidates
    )
    deadline = time.monotonic() + 30
    try:
        assert engine.search(
            "Revenue", None, None, deadline
        ) == explicit.search("Revenue", None, None, deadline)
    finally:
        explicit.close()
    index = vector_index.ReferenceIndex(path, store, SIGNATURE)

    def cancelled():
        raise TimeoutError("cancelled trial")

    with pytest.raises(TimeoutError, match="cancelled"):
        index.query([1.0, 0.0, 0.0], None, 2, cancelled)
    engine.close()
