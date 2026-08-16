"""Unit tests for the embedder wrapper (04 §4, §8).

Offline and pure: a stub model stands in for sentence-transformers, so
these tests check the wrapper's own obligations — role prefixes,
signature stamping, and the token counter — not the model.
"""

from contracts import chunk as chunk_contract
from contracts import document
from contracts import embedding
from contracts import quality
from ingestion import chunker
from ingestion import embedder


class _StubTokenizer:
    """Counts words; records whether specials were requested."""

    def __call__(self, text, add_special_tokens=True):
        extra = [0, 0] if add_special_tokens else []
        return {"input_ids": [1] * len(text.split()) + extra}


class _StubModel:
    """Records what was encoded and returns constant vectors."""

    def __init__(self):
        self.encoded: list[list[str]] = []
        self.tokenizer = _StubTokenizer()

    def encode(self, texts, batch_size=None, normalize_embeddings=None):
        del batch_size, normalize_embeddings
        self.encoded.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]


def _chunk(ordinal=0):
    """A minimal valid chunk to embed."""
    return chunk_contract.DocumentChunk(
        chunk_id=f"chk_{ordinal}",
        document_id="doc_1",
        version_id="ver_1",
        parse_id="prs_1",
        chunking_signature="chunk-1.0|policy-v0|counter:whitespace",
        ordinal=ordinal,
        citation_text="Revenue was $100.",
        embedding_text="ACME | 10-Q\nRevenue was $100.",
        block_ids=[f"blk_{ordinal}"],
        section="Item 1.",
        heading_path=["Item 1."],
        locator=document.Locator(html_anchor="#a"),
        locator_tier=quality.LocatorTier.ANCHORED,
        warning_codes=[],
        token_count=4,
        business=chunk_contract.ChunkBusiness(
            source_type=document.SourceType.SEC_FILING
        ),
    )


class TestPrefixes:
    """The embedder owns the E5 role prefixes (04 §4.1)."""

    def test_documents_get_the_passage_prefix(self):
        """No caller can forget ``passage: ``."""
        model = _StubModel()
        wrapper = embedder.SentenceTransformerEmbedder(model=model)
        wrapper.embed_documents([_chunk()])
        assert model.encoded == [["passage: ACME | 10-Q\nRevenue was $100."]]

    def test_queries_get_the_query_prefix(self):
        """No caller can forget ``query: ``."""
        model = _StubModel()
        wrapper = embedder.SentenceTransformerEmbedder(model=model)
        wrapper.embed_query("what was revenue?")
        assert model.encoded == [["query: what was revenue?"]]

    def test_an_empty_batch_never_touches_the_model(self):
        """Embedding nothing is a no-op, not a model call."""
        model = _StubModel()
        wrapper = embedder.SentenceTransformerEmbedder(model=model)
        assert wrapper.embed_documents([]) == []
        assert not model.encoded


class TestSignature:
    """The embedding identity (04 §4.3)."""

    def test_the_signature_names_every_identity_component(self):
        """Model, revision, prefix scheme, context version, norm."""
        wrapper = embedder.SentenceTransformerEmbedder(model=_StubModel())
        assert wrapper.signature == (
            f"{embedder.MODEL_NAME}@{embedder.MODEL_REVISION}"
            f"|prefix-v1|{chunker.CONTEXT_PREFIX_VERSION}|norm-l2"
        )

    def test_every_embedded_chunk_is_stamped(self):
        """The signature travels with each vector to the indexer."""
        wrapper = embedder.SentenceTransformerEmbedder(model=_StubModel())
        [embedded] = wrapper.embed_documents([_chunk()])
        assert embedded.embedding_signature == wrapper.signature
        assert embedded.chunk == _chunk()
        assert embedded.vector == [1.0, 0.0, 0.0]

    def test_the_embedder_satisfies_the_neutral_protocol(self):
        """Retrieval types against contracts.embedding only (04 §4.2)."""
        wrapper = embedder.SentenceTransformerEmbedder(model=_StubModel())
        assert isinstance(wrapper, embedding.QueryEmbedder)


class TestTokenCounter:
    """The model tokenizer as the chunker's counter (04 §3.4)."""

    def test_it_counts_content_tokens_without_specials(self):
        """Budgets are over content; the margin absorbs specials."""
        wrapper = embedder.SentenceTransformerEmbedder(model=_StubModel())
        counter = wrapper.token_counter()
        assert counter("one two three") == 3

    def test_its_name_is_stable_for_the_chunking_signature(self):
        """The counter name is part of every chunk ID."""
        wrapper = embedder.SentenceTransformerEmbedder(model=_StubModel())
        assert wrapper.token_counter().name == "multilingual-e5-base"
