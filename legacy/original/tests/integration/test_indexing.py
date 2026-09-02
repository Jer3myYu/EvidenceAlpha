"""Indexer behavior against a real (temporary) Chroma store (04 §8).

These tests use small synthetic chunks — the model is not needed to
prove upsert idempotency, retirement, signature refusal, or the
cosine configuration.
"""

import chromadb
import pytest

from contracts import chunk as chunk_contract
from contracts import document
from contracts import quality
from ingestion import embedder as embedder_module
from ingestion import indexer as indexer_module

_SIGNATURE = "test-model@rev0|prefix-v1|ctx-v1|norm-l2"


def _chunk(ordinal, parse_id="prs_1", version_id="ver_1"):
    """A small synthetic chunk with pipeline-distinct identity."""
    return chunk_contract.DocumentChunk(
        chunk_id=f"chk_{version_id}_{parse_id}_{ordinal}",
        document_id="doc_1",
        version_id=version_id,
        parse_id=parse_id,
        chunking_signature="chunk-1.0|policy-v0|counter:test",
        ordinal=ordinal,
        citation_text=f"Fact number {ordinal}.",
        embedding_text=f"ACME | 10-Q\nFact number {ordinal}.",
        block_ids=[f"blk_{parse_id}_{ordinal}"],
        section="Item 1.",
        heading_path=["Item 1."],
        locator=document.Locator(html_anchor=f"#a{ordinal}"),
        locator_tier=quality.LocatorTier.ANCHORED,
        warning_codes=[],
        token_count=3,
        business=chunk_contract.ChunkBusiness(
            source_type=document.SourceType.SEC_FILING
        ),
    )


def _embedded(ordinal, parse_id="prs_1", version_id="ver_1", sig=_SIGNATURE):
    """Wrap a synthetic chunk with a small deterministic vector."""
    return embedder_module.EmbeddedChunk(
        chunk=_chunk(ordinal, parse_id=parse_id, version_id=version_id),
        vector=[1.0, float(ordinal % 7), 0.5, 0.0],
        embedding_signature=sig,
    )


@pytest.fixture(name="indexer")
def indexer_fixture(tmp_path):
    """A fresh indexer over a temporary persistent store."""
    client = chromadb.PersistentClient(path=str(tmp_path))
    return indexer_module.ChromaIndexer(_SIGNATURE, client=client)


class TestUpsert:
    """Idempotent and observable (04 §5)."""

    def test_the_collection_uses_cosine_space(self, indexer):
        """The 1.x default would be L2; cosine is set explicitly."""
        hnsw = indexer.collection.configuration_json.get("hnsw") or {}
        assert hnsw.get("space") == "cosine"
        assert indexer.collection.metadata["embedding_signature"] == _SIGNATURE

    def test_a_second_run_reports_every_chunk_already_present(self, indexer):
        """02 §13's reuse shortcut is checkable, not assumed."""
        batch = [_embedded(index) for index in range(5)]
        first = indexer.upsert(batch)
        assert first.upserted == 5
        assert first.already_present == 0
        second = indexer.upsert(batch)
        assert second.upserted == 0
        assert second.already_present == 5
        assert indexer.collection.count() == 5

    def test_a_foreign_signature_is_refused_loudly(self, indexer):
        """Vectors from different configurations never mix (04 §4.3)."""
        foreign = _embedded(0, sig="other-model@rev9|prefix-v1|ctx-v1|norm-l2")
        with pytest.raises(indexer_module.SignatureMismatchError):
            indexer.upsert([foreign])
        assert indexer.collection.count() == 0

    def test_different_signatures_get_different_collections(self, tmp_path):
        """One collection per embedding signature (04 §5)."""
        client = chromadb.PersistentClient(path=str(tmp_path))
        first = indexer_module.ChromaIndexer(_SIGNATURE, client=client)
        second = indexer_module.ChromaIndexer(
            "test-model@rev1|prefix-v1|ctx-v1|norm-l2", client=client
        )
        assert first.collection.name != second.collection.name


class TestRetirement:
    """Deferred marking, never deletion (02 §13, 04 §5)."""

    def _active_ids(self, indexer):
        found = indexer.collection.get(
            where={
                "$and": [
                    {"document_id": {"$eq": "doc_1"}},
                    {"active": {"$eq": True}},
                ]
            }
        )
        return set(found["ids"])

    def test_a_reparse_retires_the_previous_parse(self, indexer):
        """Same bytes, new parse manifest → old parse goes inactive."""
        indexer.upsert([_embedded(index) for index in range(3)])
        indexer.upsert(
            [_embedded(index, parse_id="prs_2") for index in range(3)]
        )
        retired = indexer.retire_superseded("doc_1", "ver_1", "prs_2")
        assert retired == 3
        assert self._active_ids(indexer) == {
            f"chk_ver_1_prs_2_{index}" for index in range(3)
        }
        # Nothing was deleted: citations in past reports still resolve.
        assert indexer.collection.count() == 6

    def test_a_new_version_retires_the_previous_version(self, indexer):
        """New source bytes → the old version's records go inactive."""
        indexer.upsert([_embedded(index) for index in range(2)])
        indexer.upsert(
            [
                _embedded(index, parse_id="prs_9", version_id="ver_2")
                for index in range(2)
            ]
        )
        retired = indexer.retire_superseded("doc_1", "ver_2", "prs_9")
        assert retired == 2
        assert self._active_ids(indexer) == {
            f"chk_ver_2_prs_9_{index}" for index in range(2)
        }

    def test_retirement_is_idempotent(self, indexer):
        """A second sweep finds nothing active to retire."""
        indexer.upsert([_embedded(index) for index in range(2)])
        indexer.upsert([_embedded(0, parse_id="prs_2")])
        assert indexer.retire_superseded("doc_1", "ver_1", "prs_2") == 2
        assert indexer.retire_superseded("doc_1", "ver_1", "prs_2") == 0

    def test_retirement_touches_only_the_named_document(self, indexer):
        """Another document's records are out of scope."""
        indexer.upsert([_embedded(index) for index in range(2)])
        other = _embedded(7, parse_id="prs_7")
        other = other.model_copy(
            update={
                "chunk": other.chunk.model_copy(
                    update={
                        "document_id": "doc_2",
                        "chunk_id": "chk_other_7",
                    }
                )
            }
        )
        indexer.upsert([other])
        indexer.retire_superseded("doc_1", "ver_1", "prs_nonexistent")
        found = indexer.collection.get(ids=["chk_other_7"])
        assert found["metadatas"][0]["active"] is True
