"""Immutable Chroma reference index; originals stay in SourceStore."""

import math
import pathlib
import typing

import chromadb
import chromadb.config

from evidencealpha import artifacts
from evidencealpha import documents
from evidencealpha import dense_runtime
from evidencealpha import embedding_chunks
from evidencealpha import preparation
from evidencealpha import retrieval


def corpus_signature(store: documents.SourceStore) -> dict:
    """Bind the complete eligible corpus to its structural metadata."""
    return {s["id"]: artifacts.digest(s) for s in store.sources()}


def bindings(store: documents.SourceStore) -> dict:
    """Resolve immutable chunk identities without storing another text copy."""
    result = {}
    for source in store.sources():
        for passage in store.iter_passages(source["id"]):
            metadata = {
                "source_id": source["id"],
                "chunk_id": passage["chunk_id"],
                "text_hash": artifacts.digest(passage["text"]),
                "spans_hash": artifacts.digest(passage["spans"]),
            }
            result[artifacts.digest(metadata)] = metadata
    return result


def unit_bindings(store: documents.SourceStore, units: dict) -> dict:
    """Verify unit content and resolve only source metadata into Chroma."""
    result = {}
    sources = {s["id"]: s for s in store.sources()}
    blocks_by_source = {
        key: {b["id"]: b for b in source["blocks"]}
        for key, source in sources.items()
    }
    chunks_by_source = {
        key: {c["id"] for c in source["chunks"]}
        for key, source in sources.items()
    }
    for identifier, unit in units.items():
        text = embedding_chunks.text_for(store, unit)
        if artifacts.digest(text) != unit["text_hash"]:
            raise ValueError("Embedding original changed")
        blocks = blocks_by_source[unit["source_id"]]
        for span in unit["spans"]:
            b = blocks[span["block_id"]]
            if not b["start"] <= span["start"] < span["end"] <= b["end"]:
                raise ValueError("Embedding unit escaped source block")
        if unit["chunk_id"] not in chunks_by_source[unit["source_id"]]:
            raise ValueError("Unknown original anchor")
        result[identifier] = {
            "source_id": unit["source_id"],
            "chunk_id": unit["chunk_id"],
            "text_hash": unit["text_hash"],
            "spans_hash": artifacts.digest(unit["spans"]),
        }
    return result


def vector(values: list[float], dimension: int) -> list[float]:
    """Reject incompatible, nonfinite or zero cosine vectors."""
    if len(values) != dimension or not all(math.isfinite(v) for v in values):
        raise ValueError("Invalid embedding dimension or nonfinite vector")
    if not any(v != 0 for v in values):
        raise ValueError("Zero embedding vector")
    return values


def _client(path: pathlib.Path):
    return chromadb.PersistentClient(
        path=str(path / "chroma"),
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )


def _contents(collection) -> tuple[dict, str]:
    data = collection.get(include=["metadatas", "embeddings"])
    rows = sorted(
        (
            identifier,
            metadata,
            embedding.tolist(),
        )
        for identifier, metadata, embedding in zip(
            data["ids"], data["metadatas"], data["embeddings"]
        )
    )
    return {row[0]: row[1] for row in rows}, artifacts.digest(rows)


class ReferenceIndex:
    """Read a ready index; no update/delete or automatic embedding path."""

    @staticmethod
    def build(
        path: pathlib.Path,
        store: documents.SourceStore,
        signature: dict,
        vectors: dict[str, list[float]],
        units: dict | None = None,
    ) -> dict:
        """Publish only a complete new build from explicitly supplied vectors.

        Args:
            path: New output directory; existing directories are rejected.
            store: Authoritative original corpus.
            signature: Explicit embedding model, revision and input contract.
            vectors: One vector per ID returned by bindings().

        Returns:
            The published ready manifest.
        """
        required = {"model", "revision", "dimension", "input_policy"}
        if not required <= signature.keys() or any(
            not signature[key] for key in required
        ):
            raise ValueError("Incomplete embedding signature")
        dimension = signature["dimension"]
        if not isinstance(dimension, int) or dimension < 1:
            raise ValueError("Invalid embedding dimension")
        expected = (
            unit_bindings(store, units)
            if units is not None
            else bindings(store)
        )
        if not expected or expected.keys() != vectors.keys():
            raise ValueError("Embedding coverage does not match corpus")
        for values in vectors.values():
            vector(values, dimension)
        initial = corpus_signature(store)
        path.mkdir(parents=True, exist_ok=False)
        artifacts.write(path / "building.json", {"signature": signature})
        client = _client(path)
        collection = client.create_collection(
            "original_chunks",
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )
        ids = sorted(expected)
        for offset in range(0, len(ids), 128):
            batch = ids[offset : offset + 128]
            collection.add(
                ids=batch,
                embeddings=[vectors[i] for i in batch],
                metadatas=[expected[i] for i in batch],
            )
        actual, digest = _contents(collection)
        if actual != expected or corpus_signature(store) != initial:
            raise ValueError("Index build/source validation failed")
        if units is not None:
            artifacts.write(path / "units.json", units)
        manifest = {
            "schema": 2 if units is not None else 1,
            "units_hash": (
                artifacts.digest(units) if units is not None else None
            ),
            "status": "ready",
            "signature": signature,
            "metric": "cosine",
            "chroma_version": chromadb.__version__,
            "corpus": initial,
            "count": len(expected),
            "index_digest": digest,
        }
        artifacts.write(path / "ready.json", manifest)
        return manifest

    def __init__(
        self, path: pathlib.Path, store: documents.SourceStore, signature: dict
    ) -> None:
        self.store = store
        self.manifest = artifacts.read(path / "ready.json")
        if (
            self.manifest["status"] != "ready"
            or self.manifest["signature"] != signature
            or self.manifest["chroma_version"] != chromadb.__version__
            or self.manifest["corpus"] != corpus_signature(store)
        ):
            raise ValueError("Index signature, version or corpus mismatch")
        if not (path / "chroma" / "chroma.sqlite3").is_file():
            raise ValueError("Published Chroma database missing")
        self.client = _client(path)
        self.collection = self.client.get_collection(
            "original_chunks", embedding_function=None
        )
        self.units = (
            artifacts.read(path / "units.json")
            if self.manifest["schema"] == 2
            else None
        )
        if (
            self.units is not None
            and artifacts.digest(self.units) != self.manifest["units_hash"]
        ):
            raise ValueError("Embedding unit manifest changed")
        expected = (
            unit_bindings(store, self.units)
            if self.units is not None
            else bindings(store)
        )
        actual, digest = _contents(self.collection)
        if (
            actual != expected
            or digest != self.manifest["index_digest"]
            or len(actual) != self.manifest["count"]
        ):
            raise ValueError("Index contents changed or incomplete")
        self.expected = expected

    def query(
        self,
        embedding: list[float],
        source_id: str | None,
        limit: int,
        check: typing.Callable[[], None] = preparation.noop,
    ) -> list[dict]:
        """Query scoped vectors and rehydrate validated original passages."""
        check()
        if limit < 1:
            raise ValueError("Candidate limit must be positive")
        if corpus_signature(self.store) != self.manifest["corpus"]:
            raise ValueError("Corpus changed after index admission")
        if source_id and source_id not in self.manifest["corpus"]:
            raise ValueError("Unknown source scope")
        count = sum(
            source_id is None or m["source_id"] == source_id
            for m in self.expected.values()
        )
        if not count:
            return []
        arguments = {"where": {"source_id": source_id}} if source_id else {}
        data = self.collection.query(
            query_embeddings=[
                vector(embedding, self.manifest["signature"]["dimension"])
            ],
            n_results=min(count, limit),
            include=["metadatas", "distances"],
            **arguments,
        )
        check()
        result = []
        for identifier, meta, distance in zip(
            data["ids"][0], data["metadatas"][0], data["distances"][0]
        ):
            if self.expected.get(identifier) != meta or (
                source_id and meta["source_id"] != source_id
            ):
                raise ValueError("Unexpected vector reference")
            passage = self.store.open_source(
                meta["source_id"], meta["chunk_id"]
            )
            if not math.isfinite(distance):
                raise ValueError("Nonfinite vector distance")
            if self.units is not None:
                unit = self.units[identifier]
                text = embedding_chunks.text_for(self.store, unit)
                if artifacts.digest(text) != meta["text_hash"]:
                    raise ValueError("Embedding unit original changed")
                result.append(
                    {
                        "passage": passage,
                        "dense_distance": distance,
                        "embedding_unit": unit,
                        "unit_id": identifier,
                    }
                )
                continue
            if (
                artifacts.digest(passage["text"]) != meta["text_hash"]
                or artifacts.digest(passage["spans"]) != meta["spans_hash"]
                or not math.isfinite(distance)
            ):
                raise ValueError("Vector/source binding changed")
            result.append({"passage": passage, "dense_distance": distance})
            check()
        return result


class HybridCandidates:
    """Injectable equal-weight rank fusion before the existing reading path."""

    def __init__(
        self,
        index: ReferenceIndex,
        embed_query: typing.Callable[[str], list[float]],
    ) -> None:
        self.index = index
        self.embed_query = embed_query

    def __call__(
        self,
        store: documents.SourceStore,
        query: str,
        source_id: str | None,
        limit: int,
        check: typing.Callable[[], None],
    ) -> list[dict]:
        """Merge bounded branches, retaining their provenance in one trace."""
        if store is not self.index.store:
            raise ValueError("Candidate provider uses another source store")
        lexical = retrieval.candidates(store, query, source_id, limit, check)
        check()
        dense = self.index.query(
            self.embed_query(query), source_id, limit, check
        )
        resolved = [
            {
                "passage": item["passage"],
                "distance": item["dense_distance"],
                "unit": item.get("embedding_unit"),
                "unit_id": item.get("unit_id"),
            }
            for item in dense
        ]
        return dense_runtime.fuse(
            store,
            lexical,
            resolved,
            limit,
            artifacts.digest(self.index.manifest),
            check,
        )
