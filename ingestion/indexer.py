"""The one Chroma-touching module (04 §5, 02 §9.5).

One persistent collection per embedding signature, created with cosine
space explicitly (the 1.x default would be L2) and stamped with the
signature; the indexer refuses any chunk whose signature differs —
vectors from different configurations never share a space (04 §4.3).

Upserts are idempotent because chunk IDs are content-and-pipeline
derived; a preflight ``get`` makes idempotency *observable* by
splitting the result into ``upserted`` and ``already_present`` counts.
Superseded evidence is retired — marked ``active = false`` — never
deleted, so citations in past reports keep resolving (02 §13).
"""

import hashlib
import json

import chromadb
import chromadb.errors
import pydantic

from contracts import chunk as chunk_contract
from ingestion import embedder as embedder_module

#: Default on-disk location of the vector store (01 §7).
DEFAULT_PERSIST_PATH = "storage/chroma"

_BATCH_SIZE = 256

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


class SignatureMismatchError(Exception):
    """A chunk or collection carries the wrong embedding signature.

    Surfaced as ``EMBEDDING_FAILED`` at the tool boundary (04 §4.3).
    """


class IndexWriteError(Exception):
    """A batch write failed; the index was never left silently partial.

    Surfaced as ``INDEX_WRITE_FAILED`` at the tool boundary (04 §5).
    """


class IndexingResult(pydantic.BaseModel):
    """Observable counts for one indexing operation (04 §5)."""

    model_config = _MODEL_CONFIG

    upserted: int = pydantic.Field(default=0, ge=0)
    already_present: int = pydantic.Field(default=0, ge=0)
    retired: int = pydantic.Field(default=0, ge=0)


def collection_name_for(embedding_signature: str) -> str:
    """Derive the collection name for one embedding signature.

    Args:
      embedding_signature: The signature per 04 §4.3.

    Returns:
      ``evidence_<sig-hash8>`` — one collection per signature.
    """
    digest = hashlib.sha256(embedding_signature.encode("utf-8")).hexdigest()
    return f"evidence_{digest[:8]}"


def chunk_metadata(chunk: chunk_contract.DocumentChunk) -> dict:
    """Map one chunk to its Chroma metadata record (04 §5).

    Native types where Chroma 1.x supports them: ``warning_codes`` and
    ``heading_path`` as homogeneous string lists, filter scalars
    promoted (``page``, ``section``, ``ticker``, ...), and the full
    locator as one JSON string. ``None`` values are omitted — Chroma
    metadata has no null. The authoritative structured copy stays in
    SQLite (02 §12); Chroma holds what retrieval filters on.

    Args:
      chunk: The chunk to map.

    Returns:
      The metadata dict, with ``active`` set to True.
    """
    metadata: dict = {
        "document_id": chunk.document_id,
        "version_id": chunk.version_id,
        "parse_id": chunk.parse_id,
        "chunking_signature": chunk.chunking_signature,
        "schema_version": chunk.schema_version,
        "ordinal": chunk.ordinal,
        "locator": chunk.locator.model_dump_json(),
        "locator_tier": int(chunk.locator_tier),
        "token_count": chunk.token_count,
        "source_type": chunk.business.source_type.value,
        "active": True,
    }
    if chunk.heading_path:
        metadata["heading_path"] = list(chunk.heading_path)
    if chunk.warning_codes:
        metadata["warning_codes"] = [code.value for code in chunk.warning_codes]
    if chunk.segment is not None:
        metadata["segment"] = json.dumps(
            chunk.segment.model_dump(mode="json"), sort_keys=True
        )
    optional_scalars = {
        "section": chunk.section,
        "page": chunk.locator.page,
        "company": chunk.business.company,
        "ticker": chunk.business.ticker,
        "cik": chunk.business.cik,
        "document_type": chunk.business.document_type,
        "reporting_period": chunk.business.reporting_period,
        "published_at": (
            chunk.business.published_at.isoformat()
            if chunk.business.published_at
            else None
        ),
        "url": chunk.business.url,
    }
    for key, value in optional_scalars.items():
        if value is not None:
            metadata[key] = value
    return metadata


class ChromaIndexer:
    """Upserts and retires chunks in one Chroma collection (02 §9.5)."""

    def __init__(
        self,
        embedding_signature: str,
        path: str = DEFAULT_PERSIST_PATH,
        client: chromadb.api.ClientAPI | None = None,
    ) -> None:
        """Open (or create) the collection for one embedding signature.

        Args:
          embedding_signature: The signature this index accepts.
          path: Directory for the persistent client; ignored when a
            client is injected.
          client: A pre-built Chroma client — injected by tests.

        Raises:
          SignatureMismatchError: If the existing collection carries a
            different signature (a hash collision or hand-edited
            store); vectors never mix spaces.
        """
        self._signature = embedding_signature
        self._client = client or chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name_for(embedding_signature),
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_signature": embedding_signature},
        )
        stored = (self._collection.metadata or {}).get("embedding_signature")
        if stored != embedding_signature:
            raise SignatureMismatchError(
                f"collection {self._collection.name!r} carries signature "
                f"{stored!r}, not {embedding_signature!r}"
            )

    @property
    def collection(self) -> chromadb.api.models.Collection.Collection:
        """The underlying collection (read-only access for callers)."""
        return self._collection

    def upsert(
        self, chunks: list[embedder_module.EmbeddedChunk]
    ) -> IndexingResult:
        """Idempotently write embedded chunks (04 §5).

        Args:
          chunks: The embedded chunks; every one must carry this
            index's embedding signature.

        Returns:
          Counts of newly written and already-present chunk IDs.

        Raises:
          SignatureMismatchError: If any chunk was embedded under a
            different signature.
          IndexWriteError: If a batch write fails; no batch is ever
            silently partial.
        """
        for item in chunks:
            if item.embedding_signature != self._signature:
                raise SignatureMismatchError(
                    f"chunk {item.chunk.chunk_id} embedded under "
                    f"{item.embedding_signature!r}; this index requires "
                    f"{self._signature!r}"
                )
        upserted = 0
        already_present = 0
        for start in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[start : start + _BATCH_SIZE]
            ids = [item.chunk.chunk_id for item in batch]
            try:
                existing = set(self._collection.get(ids=ids, include=[])["ids"])
                self._collection.upsert(
                    ids=ids,
                    embeddings=[item.vector for item in batch],
                    documents=[item.chunk.citation_text for item in batch],
                    metadatas=[chunk_metadata(item.chunk) for item in batch],
                )
            except (chromadb.errors.ChromaError, ValueError) as error:
                raise IndexWriteError(
                    f"batch starting at chunk {start} failed: {error}"
                ) from error
            already_present += len(existing)
            upserted += len(ids) - len(existing)
        return IndexingResult(
            upserted=upserted, already_present=already_present
        )

    def retire_superseded(
        self,
        document_id: str,
        active_version_id: str,
        active_parse_id: str,
    ) -> int:
        """Deactivate all superseded records of one document (04 §5).

        Flips ``active`` to false on every record of ``document_id``
        except those matching the active ``(version_id, parse_id)``
        pair — one method covers both a re-parse and new source bytes.
        Nothing is deleted: citations in past reports keep resolving.

        Args:
          document_id: The logical document whose records to sweep.
          active_version_id: The version that remains active.
          active_parse_id: The parse that remains active.

        Returns:
          The number of records retired.

        Raises:
          IndexWriteError: If the metadata update fails.
        """
        found = self._collection.get(
            where={
                "$and": [
                    {"document_id": {"$eq": document_id}},
                    {"active": {"$eq": True}},
                ]
            },
            include=["metadatas"],
        )
        ids: list[str] = []
        metadatas: list[dict] = []
        for record_id, metadata in zip(found["ids"], found["metadatas"]):
            if (
                metadata.get("version_id") == active_version_id
                and metadata.get("parse_id") == active_parse_id
            ):
                continue
            retired = dict(metadata)
            retired["active"] = False
            ids.append(record_id)
            metadatas.append(retired)
        for start in range(0, len(ids), _BATCH_SIZE):
            try:
                self._collection.update(
                    ids=ids[start : start + _BATCH_SIZE],
                    metadatas=metadatas[start : start + _BATCH_SIZE],
                )
            except (chromadb.errors.ChromaError, ValueError) as error:
                raise IndexWriteError(
                    f"retirement update failed for {document_id}: {error}"
                ) from error
        return len(ids)
