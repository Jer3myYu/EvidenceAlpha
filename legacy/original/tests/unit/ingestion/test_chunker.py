"""Unit tests for the chunker (04 §3, §8).

Pure and offline: every budget here is counted by the whitespace
counter (04 §3.4), so token arithmetic in the assertions is plain word
counting.
"""

import pydantic
import pytest

from contracts import chunk as chunk_contract
from contracts import document
from contracts import quality
from ingestion import chunker

_COUNTER = chunker.WhitespaceTokenCounter()


class _RenamedCounter(chunker.WhitespaceTokenCounter):
    """The same counting under a different name — a signature change."""

    @property
    def name(self) -> str:
        return "whitespace-2"


def _policy(max_tokens=10, min_tokens=3, overlap_tokens=3):
    """A small test policy; never the v0 label with v0's constants."""
    return chunker.ChunkPolicy(
        version="policy-test",
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        overlap_tokens=overlap_tokens,
    )


def _block(
    index,
    text,
    heading_path,
    block_type=document.BlockType.PARAGRAPH,
    payload=None,
    warnings=None,
    **locator_fields,
):
    """Build one admitted block with an anchored locator by default."""
    if not locator_fields:
        locator_fields = {"html_anchor": f"#anchor{index}"}
    return document.Block(
        block_id=f"blk_{index}",
        type=block_type,
        heading_path=heading_path,
        text=text,
        payload=payload,
        locator=document.Locator(element_index=index, **locator_fields),
        extraction=document.BlockExtraction(
            adapter_name="test",
            adapter_version="1.0",
            warnings=warnings or [],
        ),
    )


def _parsed(blocks, document_warnings=None, **source_overrides):
    """Build a parsed document around the given blocks."""
    source_fields = {
        "source_type": document.SourceType.SEC_FILING,
        "source_class": document.SourceClass.SEC_FILING,
        "canonical_url": "https://sec.example/filing.htm",
    }
    source_fields.update(source_overrides)
    return document.ParsedDocument(
        identity=document.DocumentIdentity(
            document_id="doc_1", version_id="ver_1", parse_id="prs_1"
        ),
        source=document.SourceInfo(**source_fields),
        business_metadata=document.BusinessMetadata(
            company="PHOTRONICS, INC.",
            ticker="PLAB",
            cik="810136",
            document_type="10-Q",
            reporting_period="Q2 FY2026",
        ),
        blocks=blocks,
        parse_quality=document.ParseQuality(
            verdict=quality.QualityVerdict.VALID,
            policy_version="quality-v0",
            warnings=document_warnings or [],
        ),
    )


def _table_block(index, heading_path, data_words, caption="Sales"):
    """Build a table block: one header row plus one row per entry."""
    n_rows = len(data_words) + 1
    cells = [
        document.TableCell(
            row=0, column=0, is_origin=True, raw_text="Metric", is_header=True
        ),
        document.TableCell(
            row=0, column=1, is_origin=True, raw_text="Value", is_header=True
        ),
    ]
    for row, (metric, value) in enumerate(data_words, start=1):
        cells.append(
            document.TableCell(
                row=row, column=0, is_origin=True, raw_text=metric
            )
        )
        cells.append(
            document.TableCell(
                row=row, column=1, is_origin=True, raw_text=value
            )
        )
    payload = document.TableBlock(
        caption=caption,
        n_rows=n_rows,
        n_columns=2,
        header_rows=1,
        cells=cells,
    )
    return _block(
        index,
        document.render_table_text(payload),
        heading_path,
        block_type=document.BlockType.TABLE,
        payload=payload,
    )


class TestSections:
    """Effective-path boundaries (04 §3.1 rules 1–2)."""

    def test_a_heading_and_its_body_share_a_chunk(self):
        """The exclusive heading_path makes headings attach forward."""
        parsed = _parsed(
            [
                _block(
                    0,
                    "Item 1. Business",
                    [],
                    block_type=document.BlockType.HEADING,
                ),
                _block(1, "We make masks.", ["Item 1. Business"]),
            ]
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy())
        assert len(chunks) == 1
        assert chunks[0].block_ids == ["blk_0", "blk_1"]
        assert chunks[0].section == "Item 1. Business"
        assert chunks[0].heading_path == ["Item 1. Business"]

    def test_chunks_never_span_sections(self):
        """A path change is a boundary even under a roomy budget."""
        parsed = _parsed(
            [
                _block(0, "alpha text", ["Item 1."]),
                _block(1, "beta text", ["Item 2."]),
            ]
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=100))
        assert [chunk.section for chunk in chunks] == ["Item 1.", "Item 2."]
        assert [chunk.block_ids for chunk in chunks] == [["blk_0"], ["blk_1"]]

    def test_a_short_section_is_a_short_chunk(self):
        """Below min_tokens is fine when the section ended (rule 3)."""
        parsed = _parsed([_block(0, "tiny", ["Item 9."])])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(min_tokens=5))
        assert len(chunks) == 1
        assert chunks[0].token_count == 1

    def test_a_heading_only_section_yields_a_heading_chunk(self):
        """Rule 6's escape hatch: nothing else exists to attach."""
        parsed = _parsed(
            [
                _block(0, "PART I", [], block_type=document.BlockType.HEADING),
                _block(
                    1,
                    "Item 1. Business",
                    ["PART I"],
                    block_type=document.BlockType.HEADING,
                ),
                _block(2, "body words here", ["PART I", "Item 1. Business"]),
            ]
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy())
        assert len(chunks) == 2
        assert chunks[0].block_ids == ["blk_0"]
        assert chunks[0].section == "PART I"
        assert chunks[1].block_ids == ["blk_1", "blk_2"]
        assert chunks[1].heading_path == ["PART I", "Item 1. Business"]

    def test_an_empty_document_yields_no_chunks(self):
        """No blocks, no chunks — and no error."""
        assert not chunker.chunk(_parsed([]), _COUNTER, _policy())


class TestBudgets:
    """Accumulation and overlap (04 §3.1 rules 3–4)."""

    def test_a_section_splits_when_the_budget_fills(self):
        """Adding a block that would exceed max_tokens closes a chunk."""
        parsed = _parsed(
            [
                _block(0, "one two three four five", ["S"]),
                _block(1, "six seven eight nine ten", ["S"]),
            ]
        )
        chunks = chunker.chunk(
            parsed, _COUNTER, _policy(max_tokens=8, overlap_tokens=0)
        )
        assert [chunk.block_ids for chunk in chunks] == [["blk_0"], ["blk_1"]]

    def test_blocks_are_atomic_within_budget(self):
        """A block under max_tokens is never split (rule 5)."""
        parsed = _parsed([_block(0, "one two three four five", ["S"])])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=5))
        assert len(chunks) == 1
        assert chunks[0].segment is None

    def test_overlap_repeats_the_trailing_block(self):
        """The next chunk starts with the previous chunk's tail."""
        parsed = _parsed(
            [
                _block(0, "one two three four five", ["S"]),
                _block(1, "tail words", ["S"]),
                _block(2, "six seven eight nine", ["S"]),
            ]
        )
        chunks = chunker.chunk(
            parsed, _COUNTER, _policy(max_tokens=10, overlap_tokens=3)
        )
        assert len(chunks) == 2
        assert chunks[0].block_ids == ["blk_0", "blk_1"]
        assert chunks[1].block_ids == ["blk_1", "blk_2"]
        assert chunks[1].citation_text.startswith("tail words")

    def test_overlap_never_exceeds_its_token_budget(self):
        """A trailing block larger than overlap_tokens is not repeated."""
        parsed = _parsed(
            [
                _block(0, "one two three four five", ["S"]),
                _block(1, "six seven eight nine", ["S"]),
            ]
        )
        chunks = chunker.chunk(
            parsed, _COUNTER, _policy(max_tokens=6, overlap_tokens=3)
        )
        assert chunks[1].block_ids == ["blk_1"]

    def test_overlap_yields_to_the_max_budget(self):
        """Overlap is dropped rather than pushing a chunk over max."""
        parsed = _parsed(
            [
                _block(0, "one two three four", ["S"]),
                _block(1, "tail here", ["S"]),
                _block(2, "a b c d e f g h i", ["S"]),
            ]
        )
        chunks = chunker.chunk(
            parsed, _COUNTER, _policy(max_tokens=10, overlap_tokens=3)
        )
        assert chunks[0].block_ids == ["blk_0", "blk_1"]
        assert chunks[1].block_ids == ["blk_2"]

    def test_overlap_never_crosses_a_section(self):
        """Rule 4: repetition happens only within the same section."""
        parsed = _parsed(
            [
                _block(0, "one two", ["Item 1."]),
                _block(1, "three four", ["Item 2."]),
            ]
        )
        chunks = chunker.chunk(
            parsed, _COUNTER, _policy(max_tokens=10, overlap_tokens=5)
        )
        assert chunks[1].block_ids == ["blk_1"]

    def test_facts_pack_into_fact_dense_chunks(self):
        """Runs of financial facts group like any other block (rule 7)."""
        facts = []
        for index, value in enumerate((100, 200, 300)):
            payload = document.FinancialFact(
                concept="Revenue", value=value, unit="USD"
            )
            facts.append(
                _block(
                    index,
                    document.render_financial_fact_text(payload),
                    ["Facts"],
                    block_type=document.BlockType.FINANCIAL_FACT,
                    payload=payload,
                )
            )
        chunks = chunker.chunk(_parsed(facts), _COUNTER, _policy())
        assert len(chunks) == 1
        assert chunks[0].block_ids == ["blk_0", "blk_1", "blk_2"]


class TestOversizedParagraph:
    """The paragraph_span oversize rule (04 §3.1 rule 5, §2.2)."""

    def test_pieces_are_verbatim_offset_slices(self):
        """Each piece's citation is text[start:end] of the source."""
        text = "w1 w2 w3 w4 w5\nw6 w7 w8 w9 w10\nw11 w12"
        parsed = _parsed([_block(0, text, ["S"])])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=8))
        assert len(chunks) == 2
        for piece in chunks:
            segment = piece.segment
            assert segment is not None
            assert segment.kind is (
                chunk_contract.ChunkSegmentKind.PARAGRAPH_SPAN
            )
            assert segment.source_block_id == "blk_0"
            assert piece.citation_text == (
                text[segment.text_start : segment.text_end]
            )
        assert chunks[0].citation_text == "w1 w2 w3 w4 w5"
        assert chunks[1].citation_text == "w6 w7 w8 w9 w10\nw11 w12"

    def test_an_oversized_line_splits_at_sentences(self):
        """Line first, then sentence boundaries."""
        text = "First one here. Second two here. Third three here."
        parsed = _parsed([_block(0, text, ["S"])])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=4))
        assert [piece.citation_text for piece in chunks] == [
            "First one here.",
            "Second two here.",
            "Third three here.",
        ]

    def test_line_locators_narrow_to_the_piece(self):
        """Line ranges shrink mechanically by counting newlines."""
        text = "w1 w2 w3 w4 w5\nw6 w7 w8 w9 w10\nw11 w12"
        parsed = _parsed([_block(0, text, ["S"], line_start=10, line_end=12)])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=8))
        assert (chunks[0].locator.line_start, chunks[0].locator.line_end) == (
            10,
            10,
        )
        assert (chunks[1].locator.line_start, chunks[1].locator.line_end) == (
            11,
            12,
        )

    def test_a_heading_attaches_to_the_first_piece(self):
        """Rule 6: a heading opens the chunk, never stands alone."""
        text = "w1 w2 w3 w4 w5\nw6 w7 w8 w9 w10"
        parsed = _parsed(
            [
                _block(
                    0, "Item 7A.", [], block_type=document.BlockType.HEADING
                ),
                _block(1, text, ["Item 7A."]),
            ]
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=7))
        assert len(chunks) == 2
        assert chunks[0].block_ids == ["blk_0", "blk_1"]
        assert chunks[0].citation_text == "Item 7A.\n\nw1 w2 w3 w4 w5"
        assert chunks[0].segment is not None
        assert chunks[1].block_ids == ["blk_1"]


class TestOversizedTable:
    """The table_rows oversize rule (04 §3.1 rule 5, §2.2)."""

    def test_pieces_repeat_headers_and_record_row_ranges(self):
        """Every piece reads as a table and resolves its rows."""
        table = _table_block(
            0, ["S"], [("a1", "b1"), ("a2", "b2"), ("a3", "b3")]
        )
        parsed = _parsed([table])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=20))
        assert len(chunks) == 3
        lines = table.text.split("\n")
        head = "\n".join(lines[:3])  # caption, header row, delimiter
        for index, piece in enumerate(chunks):
            assert piece.citation_text == f"{head}\n{lines[3 + index]}"
            segment = piece.segment
            assert segment is not None
            assert segment.kind is chunk_contract.ChunkSegmentKind.TABLE_ROWS
            # Grid row indices: one header row, so data starts at row 1.
            assert (segment.row_start, segment.row_end) == (
                1 + index,
                2 + index,
            )

    def test_piece_lines_are_verbatim_lines_of_the_rendering(self):
        """Line selection, never re-rendering (03 §5.4)."""
        table = _table_block(0, ["S"], [("a1", "b1"), ("a2", "b2")])
        parsed = _parsed([table])
        chunks = chunker.chunk(parsed, _COUNTER, _policy(max_tokens=17))
        source_lines = set(table.text.split("\n"))
        for piece in chunks:
            assert set(piece.citation_text.split("\n")) <= source_lines


class TestIdentity:
    """Chunk IDs and signature visibility (04 §2.1, §3.5, §9)."""

    def _parsed(self):
        return _parsed(
            [
                _block(0, "Item 1.", [], block_type=document.BlockType.HEADING),
                _block(1, "one two three four five", ["Item 1."]),
                _block(2, "six seven eight nine ten", ["Item 1."]),
            ]
        )

    def test_chunking_is_deterministic(self):
        """Same input, same signature — byte-same chunks and IDs."""
        first = chunker.chunk(self._parsed(), _COUNTER, _policy())
        second = chunker.chunk(self._parsed(), _COUNTER, _policy())
        assert first == second

    def test_a_counter_change_changes_every_chunk_id(self):
        """The counter name is part of the chunking signature."""
        original = chunker.chunk(self._parsed(), _COUNTER, _policy())
        renamed = chunker.chunk(self._parsed(), _RenamedCounter(), _policy())
        assert [c.citation_text for c in original] == [
            c.citation_text for c in renamed
        ]
        assert not {c.chunk_id for c in original} & {
            c.chunk_id for c in renamed
        }

    def test_a_policy_version_change_changes_every_chunk_id(self):
        """Re-chunking is expressible, never silent (04 §3.5)."""
        policy_a = _policy()
        policy_b = chunker.ChunkPolicy(
            version="policy-test-2",
            max_tokens=policy_a.max_tokens,
            min_tokens=policy_a.min_tokens,
            overlap_tokens=policy_a.overlap_tokens,
        )
        ids_a = {
            c.chunk_id
            for c in chunker.chunk(self._parsed(), _COUNTER, policy_a)
        }
        ids_b = {
            c.chunk_id
            for c in chunker.chunk(self._parsed(), _COUNTER, policy_b)
        }
        assert not ids_a & ids_b

    def test_the_signature_format_is_the_specified_one(self):
        """04 §3.5 fixes the format exactly."""
        assert (
            chunker.make_chunking_signature(chunker.POLICY_V0, _COUNTER)
            == "chunk-1.0|policy-v0|counter:whitespace"
        )

    def test_v0_constants_cannot_drift_silently(self):
        """Changed constants under the v0 label are refused."""
        with pytest.raises(pydantic.ValidationError):
            chunker.ChunkPolicy(max_tokens=999)

    def test_ordinals_are_sequential(self):
        """Ordinals are the chunk's position within the parse."""
        chunks = chunker.chunk(self._parsed(), _COUNTER, _policy())
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))


class TestMetadata:
    """Warnings, locators, and business metadata (04 §2)."""

    def test_document_warnings_reach_every_chunk(self):
        """A chunk from a partial parse is visibly from one."""
        parsed = _parsed(
            [
                _block(0, "alpha", ["A"]),
                _block(1, "beta", ["B"]),
            ],
            document_warnings=[
                document.ParseWarning(
                    code=quality.WarningCode.SEC_SECTIONS_MISSING,
                    message="Item 3 not found",
                )
            ],
        )
        for item in chunker.chunk(parsed, _COUNTER, _policy()):
            assert (
                quality.WarningCode.SEC_SECTIONS_MISSING in item.warning_codes
            )

    def test_block_warnings_union_sorted_and_deduplicated(self):
        """Member warnings merge with document warnings, sorted."""
        shared = document.ParseWarning(
            code=quality.WarningCode.TABLE_STRUCTURE_LOST, message="x"
        )
        parsed = _parsed(
            [
                _block(0, "alpha", ["A"], warnings=[shared]),
                _block(
                    1,
                    "beta",
                    ["A"],
                    warnings=[
                        shared,
                        document.ParseWarning(
                            code=quality.WarningCode.ENCODING_FALLBACK_USED,
                            message="y",
                        ),
                    ],
                ),
            ],
            document_warnings=[shared],
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy())
        assert chunks[0].warning_codes == [
            quality.WarningCode.ENCODING_FALLBACK_USED,
            quality.WarningCode.TABLE_STRUCTURE_LOST,
        ]

    def test_the_locator_is_the_first_members_verbatim(self):
        """And the tier is the worst tier among members."""
        parsed = _parsed(
            [
                _block(0, "alpha words", ["A"], html_anchor="#first"),
                _block(1, "beta words", ["A"], line_start=4, line_end=5),
            ]
        )
        chunks = chunker.chunk(parsed, _COUNTER, _policy())
        assert chunks[0].locator.html_anchor == "#first"
        assert chunks[0].locator_tier is quality.LocatorTier.COARSE

    def test_business_metadata_is_copied_never_invented(self):
        """Company, ticker, CIK, and the canonical URL come through."""
        chunks = chunker.chunk(
            _parsed([_block(0, "alpha", ["A"])]), _COUNTER, _policy()
        )
        business = chunks[0].business
        assert business.company == "PHOTRONICS, INC."
        assert business.ticker == "PLAB"
        assert business.cik == "0000810136"
        assert business.url == "https://sec.example/filing.htm"

    def test_the_url_falls_back_to_the_original(self):
        """canonical_url, else original_url, else None (04 §2)."""
        chunks = chunker.chunk(
            _parsed(
                [_block(0, "alpha", ["A"])],
                canonical_url=None,
                original_url="https://origin.example/a",
            ),
            _COUNTER,
            _policy(),
        )
        assert chunks[0].business.url == "https://origin.example/a"

    def test_the_context_prefix_is_metadata_not_citation(self):
        """Users see the filing's own words only (04 §3.3)."""
        chunks = chunker.chunk(
            _parsed([_block(0, "alpha beta", ["Item 1A.", "Overview"])]),
            _COUNTER,
            _policy(),
        )
        item = chunks[0]
        assert item.citation_text == "alpha beta"
        assert item.embedding_text == (
            "PHOTRONICS, INC. (PLAB) | 10-Q Q2 FY2026 | "
            "Item 1A. > Overview\nalpha beta"
        )

    def test_token_count_is_the_counters_content_count(self):
        """token_count records the counter in force over the citation."""
        chunks = chunker.chunk(
            _parsed([_block(0, "one two three", ["A"])]),
            _COUNTER,
            _policy(),
        )
        assert chunks[0].token_count == 3
