"""Unit tests for the indexer's pure parts (04 §5, §8).

Everything that touches a real Chroma store is in
``tests/integration/``; these tests cover the metadata mapping and the
collection-name derivation, which are pure functions.
"""

import datetime
import json

from contracts import chunk as chunk_contract
from contracts import document
from contracts import quality
from ingestion import indexer


def _chunk(**overrides):
    """A representative chunk with every optional field populated."""
    fields = {
        "chunk_id": "chk_1",
        "document_id": "doc_1",
        "version_id": "ver_1",
        "parse_id": "prs_1",
        "chunking_signature": "chunk-1.0|policy-v0|counter:e5",
        "ordinal": 3,
        "citation_text": "Revenue was $100.",
        "embedding_text": "ACME | 10-Q\nRevenue was $100.",
        "block_ids": ["blk_1", "blk_2"],
        "section": "Item 1.",
        "heading_path": ["PART I", "Item 1."],
        "locator": document.Locator(html_anchor="#a", page=7),
        "locator_tier": quality.LocatorTier.ANCHORED,
        "warning_codes": [
            quality.WarningCode.TABLE_STRUCTURE_LOST,
            quality.WarningCode.SEC_SECTIONS_MISSING,
        ],
        "token_count": 4,
        "business": chunk_contract.ChunkBusiness(
            company="PHOTRONICS, INC.",
            ticker="PLAB",
            cik="0000810136",
            document_type="10-Q",
            reporting_period="Q2 FY2026",
            published_at=datetime.datetime(
                2026, 6, 9, tzinfo=datetime.timezone.utc
            ),
            source_type=document.SourceType.SEC_FILING,
            url="https://sec.example/filing.htm",
        ),
    }
    fields.update(overrides)
    return chunk_contract.DocumentChunk(**fields)


class TestChunkMetadata:
    """The chunk → Chroma metadata mapping (04 §5)."""

    def test_filter_scalars_are_promoted(self):
        """page, section, ticker, period, active, tier — all flat."""
        metadata = indexer.chunk_metadata(_chunk())
        assert metadata["page"] == 7
        assert metadata["section"] == "Item 1."
        assert metadata["ticker"] == "PLAB"
        assert metadata["document_type"] == "10-Q"
        assert metadata["reporting_period"] == "Q2 FY2026"
        assert metadata["active"] is True
        assert metadata["locator_tier"] == 1
        assert metadata["published_at"] == "2026-06-09T00:00:00+00:00"

    def test_lists_stay_native_string_lists(self):
        """warning_codes and heading_path are filterable arrays."""
        metadata = indexer.chunk_metadata(_chunk())
        assert metadata["heading_path"] == ["PART I", "Item 1."]
        assert metadata["warning_codes"] == [
            "SEC_SECTIONS_MISSING",
            "TABLE_STRUCTURE_LOST",
        ]

    def test_the_locator_round_trips_through_its_json_field(self):
        """The full locator is one JSON string field."""
        item = _chunk()
        metadata = indexer.chunk_metadata(item)
        restored = document.Locator.model_validate_json(metadata["locator"])
        assert restored == item.locator

    def test_a_segment_round_trips_through_its_json_field(self):
        """A split chunk's slice survives the store."""
        item = _chunk(
            segment=chunk_contract.ChunkSegment(
                source_block_id="blk_1",
                kind=chunk_contract.ChunkSegmentKind.TABLE_ROWS,
                row_start=1,
                row_end=4,
            ),
        )
        metadata = indexer.chunk_metadata(item)
        restored = chunk_contract.ChunkSegment.model_validate(
            json.loads(metadata["segment"])
        )
        assert restored == item.segment

    def test_missing_values_are_omitted_not_null(self):
        """Chroma metadata has no null; absence means unknown."""
        bare = _chunk(
            section=None,
            heading_path=[],
            warning_codes=[],
            locator=document.Locator(html_anchor="#a"),
            business=chunk_contract.ChunkBusiness(
                source_type=document.SourceType.PDF_DOCUMENT
            ),
        )
        metadata = indexer.chunk_metadata(bare)
        for absent in (
            "section",
            "page",
            "company",
            "ticker",
            "cik",
            "document_type",
            "reporting_period",
            "published_at",
            "url",
            "heading_path",
            "warning_codes",
            "segment",
        ):
            assert absent not in metadata
        assert metadata["source_type"] == "pdf_document"

    def test_identity_fields_support_retirement(self):
        """retire_superseded matches on these exact fields."""
        metadata = indexer.chunk_metadata(_chunk())
        assert metadata["document_id"] == "doc_1"
        assert metadata["version_id"] == "ver_1"
        assert metadata["parse_id"] == "prs_1"


class TestCollectionName:
    """One collection per embedding signature (04 §4.3, §5)."""

    def test_the_name_is_a_stable_signature_hash(self):
        """Same signature, same collection — every time."""
        name = indexer.collection_name_for("model@rev|prefix-v1")
        assert name == indexer.collection_name_for("model@rev|prefix-v1")
        assert name.startswith("evidence_")
        assert len(name) == len("evidence_") + 8

    def test_different_signatures_never_share_a_collection(self):
        """A changed configuration cannot mix vector spaces."""
        assert indexer.collection_name_for(
            "model@rev1|prefix-v1"
        ) != indexer.collection_name_for("model@rev2|prefix-v1")
