"""Tests for the chunk contract (04 §2, §10)."""

import pydantic
import pytest

from contracts import chunk
from contracts import document
from contracts import quality


def _segment(**overrides):
    """A valid paragraph_span segment unless overridden."""
    fields = {
        "source_block_id": "blk_1",
        "kind": chunk.ChunkSegmentKind.PARAGRAPH_SPAN,
        "text_start": 0,
        "text_end": 10,
    }
    fields.update(overrides)
    return chunk.ChunkSegment(**fields)


def _chunk(**overrides):
    """A valid chunk unless overridden."""
    fields = {
        "chunk_id": "chk_1",
        "document_id": "doc_1",
        "version_id": "ver_1",
        "parse_id": "prs_1",
        "chunking_signature": "chunk-1.0|policy-v0|counter:whitespace",
        "ordinal": 0,
        "citation_text": "Revenue was $100.",
        "embedding_text": "ACME | 10-Q\nRevenue was $100.",
        "block_ids": ["blk_1"],
        "section": "Item 1.",
        "heading_path": ["Item 1."],
        "locator": document.Locator(html_anchor="#a"),
        "locator_tier": quality.LocatorTier.ANCHORED,
        "warning_codes": [],
        "token_count": 4,
        "business": chunk.ChunkBusiness(
            source_type=document.SourceType.SEC_FILING
        ),
    }
    fields.update(overrides)
    return chunk.DocumentChunk(**fields)


class TestChunkSegment:
    """Exactly the fields of a segment's kind are set (04 §2.2)."""

    def test_a_paragraph_span_carries_text_offsets(self):
        """The valid case round-trips."""
        segment = _segment()
        assert segment.text_start == 0
        assert segment.row_start is None

    def test_a_table_rows_segment_carries_row_indices(self):
        """The valid case round-trips."""
        segment = _segment(
            kind=chunk.ChunkSegmentKind.TABLE_ROWS,
            text_start=None,
            text_end=None,
            row_start=1,
            row_end=5,
        )
        assert segment.row_start == 1

    def test_a_paragraph_span_missing_offsets_is_rejected(self):
        """A kind without its own offset pair is unresolvable."""
        with pytest.raises(pydantic.ValidationError):
            _segment(text_end=None)

    def test_mixed_kind_fields_are_rejected(self):
        """A segment may not carry the other kind's offsets."""
        with pytest.raises(pydantic.ValidationError):
            _segment(row_start=1, row_end=2)

    def test_an_empty_span_is_rejected(self):
        """End must exceed start — a segment cites something."""
        with pytest.raises(pydantic.ValidationError):
            _segment(text_start=5, text_end=5)

    def test_a_reversed_row_range_is_rejected(self):
        """End must exceed start for row ranges too."""
        with pytest.raises(pydantic.ValidationError):
            _segment(
                kind=chunk.ChunkSegmentKind.TABLE_ROWS,
                text_start=None,
                text_end=None,
                row_start=5,
                row_end=2,
            )


class TestDocumentChunk:
    """The chunk-level invariants (04 §10)."""

    def test_a_valid_chunk_is_frozen(self):
        """Chunks are immutable evidence."""
        item = _chunk()
        with pytest.raises(pydantic.ValidationError):
            item.ordinal = 1

    def test_blank_citation_text_is_rejected(self):
        """Citation text is evidence and must be non-empty."""
        with pytest.raises(pydantic.ValidationError):
            _chunk(citation_text="   \n ")

    def test_empty_block_ids_are_rejected(self):
        """A chunk cites at least one block."""
        with pytest.raises(pydantic.ValidationError):
            _chunk(block_ids=[])

    def test_duplicate_block_ids_are_rejected(self):
        """Member blocks are unique within a chunk."""
        with pytest.raises(pydantic.ValidationError):
            _chunk(block_ids=["blk_1", "blk_1"])

    def test_warning_codes_are_sorted_and_deduplicated(self):
        """Equal chunks must serialize identically (04 §2)."""
        item = _chunk(
            warning_codes=[
                quality.WarningCode.TABLE_STRUCTURE_LOST,
                quality.WarningCode.COVERAGE_BELOW_THRESHOLD,
                quality.WarningCode.TABLE_STRUCTURE_LOST,
            ]
        )
        assert item.warning_codes == [
            quality.WarningCode.COVERAGE_BELOW_THRESHOLD,
            quality.WarningCode.TABLE_STRUCTURE_LOST,
        ]

    def test_an_unknown_field_is_rejected(self):
        """The contract is closed — extra fields are drift."""
        with pytest.raises(pydantic.ValidationError):
            _chunk(summary="an LLM wrote this")

    def test_schema_version_defaults_to_the_module_constant(self):
        """Chunks carry the contract version they were built under."""
        assert _chunk().schema_version == chunk.CHUNK_SCHEMA_VERSION
