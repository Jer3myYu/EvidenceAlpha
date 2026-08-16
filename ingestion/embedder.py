"""The pinned local embedding model behind two thin methods (04 §4).

One model, pinned by name **and** revision, wrapped so that no caller
can forget the E5 role prefixes: ``embed_documents`` prepends
``"passage: "`` to each chunk's embedding text, ``embed_query``
prepends ``"query: "``. Vectors are L2-normalized. The embedding
signature (04 §4.3) names the model, revision, prefix scheme, context
template, and normalization — any change to it is a new collection and
a full re-embed, never a silent mix of vector spaces.

The query half of this class satisfies
:class:`contracts.embedding.QueryEmbedder`; the application layer
constructs one embedder and injects it into both ingestion and
retrieval (04 §4.2). Model files are fetched once by
``scripts/init_db.py``; after that, loading and embedding are
network-free.
"""

from typing import Any

import pydantic

from contracts import chunk as chunk_contract
from ingestion import chunker

#: The pinned embedding model (04 §4.1): bilingual corpus from day one,
#: 768-d, CPU-viable, 512-token window.
MODEL_NAME = "intfloat/multilingual-e5-base"

#: The pinned model revision. Bumping it changes the embedding
#: signature and therefore requires a new collection and full re-embed.
MODEL_REVISION = "d128750597153bb5987e10b1c3493a34e5a4502a"

#: The E5 role-prefix scheme version (04 §4.3).
PREFIX_VERSION = "prefix-v1"

#: The embedding identity in force (04 §4.3). Stamped on the Chroma
#: collection at creation and on every :class:`EmbeddedChunk`.
EMBEDDING_SIGNATURE = (
    f"{MODEL_NAME}@{MODEL_REVISION}"
    f"|{PREFIX_VERSION}|{chunker.CONTEXT_PREFIX_VERSION}|norm-l2"
)

#: The model's hard input window, in tokens. The chunk budget is
#: derived from it (04 §3.5).
MODEL_TOKEN_WINDOW = 512

_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "
_BATCH_SIZE = 32

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


class EmbeddedChunk(pydantic.BaseModel):
    """A chunk with its vector, between embedder and indexer (04 §2).

    This type exists only on the ingestion path — retrieval never sees
    it, which is why it lives here and not in ``contracts/``.
    """

    model_config = _MODEL_CONFIG

    chunk: chunk_contract.DocumentChunk
    vector: list[float]
    embedding_signature: str


class ModelTokenCounter:
    """Counts content tokens with the embedding model's tokenizer.

    Special tokens are excluded: the counter budgets *content*, and
    the window margin in the chunk policy absorbs the model's own
    specials (04 §3.4–§3.5).
    """

    def __init__(self, tokenizer: Any) -> None:
        """Wrap one HuggingFace tokenizer.

        Args:
          tokenizer: The tokenizer of the pinned model.
        """
        self._tokenizer = tokenizer

    @property
    def name(self) -> str:
        """The counter name recorded in the chunking signature."""
        return "multilingual-e5-base"

    def __call__(self, text: str) -> int:
        """Return the number of content tokens in ``text``."""
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])


class SentenceTransformerEmbedder:
    """The one concrete embedder (04 §4).

    Implements :class:`contracts.embedding.QueryEmbedder` and adds the
    document half. No knobs beyond the device: model, revision,
    prefixes, batch size, and normalization are fixed by this module's
    constants, because every one of them is part of the vector space's
    identity.
    """

    def __init__(self, model: Any = None, device: str | None = None) -> None:
        """Load (or accept) the pinned model.

        Args:
          model: A pre-built model exposing ``encode`` and
            ``tokenizer`` — injected by unit tests; when omitted, the
            pinned ``sentence-transformers`` model is loaded from the
            local cache (downloading on first use only).
          device: Torch device override; auto-detected when omitted.
        """
        if model is None:
            # Imported here so that unit tests with a stub model never
            # pay the torch import, keeping them fast and offline.
            import sentence_transformers  # pylint: disable=import-outside-toplevel

            model = sentence_transformers.SentenceTransformer(
                MODEL_NAME, revision=MODEL_REVISION, device=device
            )
        self._model = model

    @property
    def signature(self) -> str:
        """The embedding signature this embedder produces (04 §4.3)."""
        return EMBEDDING_SIGNATURE

    def token_counter(self) -> chunker.TokenCounter:
        """Return the chunker's token counter for this model (04 §3.4)."""
        return ModelTokenCounter(self._model.tokenizer)

    def embed_documents(
        self, chunks: list[chunk_contract.DocumentChunk]
    ) -> list[EmbeddedChunk]:
        """Embed chunks for indexing.

        Args:
          chunks: The chunks to embed; their ``embedding_text`` gets
            the ``"passage: "`` role prefix.

        Returns:
          One :class:`EmbeddedChunk` per input, in order, each stamped
          with the embedding signature.
        """
        if not chunks:
            return []
        vectors = self._model.encode(
            [_PASSAGE_PREFIX + item.embedding_text for item in chunks],
            batch_size=_BATCH_SIZE,
            normalize_embeddings=True,
        )
        return [
            EmbeddedChunk(
                chunk=item,
                vector=[float(value) for value in vector],
                embedding_signature=EMBEDDING_SIGNATURE,
            )
            for item, vector in zip(chunks, vectors)
        ]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query string.

        Args:
          text: The raw query, without a role prefix; the ``"query: "``
            prefix is applied here so no caller can forget it.

        Returns:
          The L2-normalized query vector.
        """
        vectors = self._model.encode(
            [_QUERY_PREFIX + text],
            batch_size=_BATCH_SIZE,
            normalize_embeddings=True,
        )
        return [float(value) for value in vectors[0]]
