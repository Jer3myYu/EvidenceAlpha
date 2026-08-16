"""The MVP vertical slice, minus the agent (04 §8).

Parse → chunk → embed → index → query: a paraphrased question about
Q2 FY2026 revenue must bring back the answer-bearing chunk with its
locator, section, and metadata intact. Everything runs offline once
the model is cached.
"""

import chromadb
import pytest

from contracts import document
from ingestion import indexer as indexer_module

_QUESTION = (
    "How much revenue did Photronics generate in the second fiscal "
    "quarter of 2026, and how did it change?"
)

#: The filing's own words answering the question (MD&A, Item 2).
_ANSWER_PHRASE = "Revenue in Q2 FY26 was $209.9 million"


@pytest.fixture(name="corpus_indexer", scope="module")
def corpus_indexer_fixture(tmp_path_factory, real_embedder, ten_q_embedded):
    """Index the embedded golden 10-Q into a temporary store."""
    client = chromadb.PersistentClient(
        path=str(tmp_path_factory.mktemp("chroma"))
    )
    indexer = indexer_module.ChromaIndexer(
        real_embedder.signature, client=client
    )
    result = indexer.upsert(ten_q_embedded)
    assert result.upserted == len(ten_q_embedded)
    return indexer


class TestVerticalSlice:
    """Evidence out matches evidence in (04 §9)."""

    def test_a_paraphrased_question_retrieves_the_answer(
        self, corpus_indexer, real_embedder
    ):
        """The chunk stating the Q2 FY2026 revenue is a top hit."""
        query_vector = real_embedder.embed_query(_QUESTION)
        found = corpus_indexer.collection.query(
            query_embeddings=[query_vector],
            n_results=5,
            include=["documents", "metadatas"],
        )
        documents = found["documents"][0]
        hits = [
            index
            for index, text in enumerate(documents)
            if _ANSWER_PHRASE in text
        ]
        assert hits, "answer chunk not in the top 5"
        metadata = found["metadatas"][0][hits[0]]
        # Locator, section, and provenance survived the round trip.
        locator = document.Locator.model_validate_json(metadata["locator"])
        assert locator.html_anchor or locator.xpath
        assert metadata["section"].startswith("Item 2.")
        assert metadata["locator_tier"] == 1
        assert metadata["active"] is True
        assert metadata["ticker"] == "PLAB"
        assert metadata["document_type"] == "10-Q"
        assert metadata["parse_id"]
        assert metadata["chunking_signature"].startswith("chunk-1.0|")

    def test_the_top_hits_are_financial_sections(
        self, corpus_indexer, real_embedder
    ):
        """A revenue question lands in the filing's financial parts."""
        query_vector = real_embedder.embed_query(_QUESTION)
        found = corpus_indexer.collection.query(
            query_embeddings=[query_vector],
            n_results=5,
            include=["metadatas"],
        )
        for metadata in found["metadatas"][0]:
            assert metadata["section"].startswith(("Item 1.", "Item 2."))

    def test_citation_text_is_returned_verbatim(
        self, corpus_indexer, ten_q_embedded
    ):
        """The stored document is the chunk's citation text, exactly."""
        sample = ten_q_embedded[0]
        found = corpus_indexer.collection.get(
            ids=[sample.chunk.chunk_id], include=["documents"]
        )
        assert found["documents"][0] == sample.chunk.citation_text
