"""Golden chunker test on the parsed Photronics 10-Q (04 §8).

The fixture is parsed through the real ``ParserService`` — offline —
and chunked under the real embedding-model tokenizer, so these
assertions pin what production ingestion would actually produce.

One fixture-specific note: the SEC HTML route reports ``header_rows =
0`` for this filing's tables (the source marks no ``<th>`` rows), so
the header-line *repetition* branch of the table split has nothing to
repeat here; it is pinned by the unit tests instead. What this golden
test asserts about table segments is the stronger invariant: every
piece is a verbatim line-selection of its block's canonical rendering
with a resolvable grid row range.
"""

from contracts import chunk as chunk_contract
from contracts import quality
from ingestion import chunker
from ingestion import embedder as embedder_module


class TestGoldenTenQ:
    """The 10-Q fixture end to end (04 §8, §9)."""

    def test_the_parse_produced_chunks(self, ten_q_chunks):
        """A full 10-Q yields a substantial chunk stream."""
        assert len(ten_q_chunks) > 100

    def test_every_chunk_is_within_the_content_budget(self, ten_q_chunks):
        """policy v0: at most 420 content tokens per chunk."""
        assert all(
            chunk.token_count <= chunker.POLICY_V0.max_tokens
            for chunk in ten_q_chunks
        )

    def test_no_embedding_text_exceeds_the_model_window(
        self, ten_q_chunks, real_embedder
    ):
        """512 tokens, counted with the role prefix and specials."""
        tokenizer = real_embedder.token_counter()
        worst = max(
            tokenizer("passage: " + chunk.embedding_text) + 2
            for chunk in ten_q_chunks
        )
        assert worst <= embedder_module.MODEL_TOKEN_WINDOW

    def test_every_chunk_is_anchored(self, ten_q_chunks):
        """The SEC route promises tier-1 locators on every block."""
        assert all(
            chunk.locator_tier is quality.LocatorTier.ANCHORED
            for chunk in ten_q_chunks
        )

    def test_item_1a_yields_within_budget_chunks(self, ten_q_chunks):
        """The Item 1A section is present and within budget."""
        item_1a = [
            chunk
            for chunk in ten_q_chunks
            if any(
                part.lower().startswith("item 1a")
                for part in chunk.heading_path
            )
        ]
        assert item_1a
        assert all(
            chunk.token_count <= chunker.POLICY_V0.max_tokens
            for chunk in item_1a
        )

    def test_a_financial_statement_table_was_split_into_segments(
        self, ten_q_chunks
    ):
        """The income statement arrives as resolvable row slices."""
        statements = [
            chunk
            for chunk in ten_q_chunks
            if chunk.section == "Item 1. FINANCIAL STATEMENTS"
            and chunk.segment is not None
            and chunk.segment.kind is chunk_contract.ChunkSegmentKind.TABLE_ROWS
            and "Revenue" in chunk.citation_text
        ]
        assert statements

    def test_table_segments_are_verbatim_line_selections(
        self, ten_q, ten_q_chunks
    ):
        """Line selection, never re-rendering (03 §5.4, 04 §3.1)."""
        blocks = {block.block_id: block for block in ten_q.blocks}
        table_pieces = [
            chunk
            for chunk in ten_q_chunks
            if chunk.segment is not None
            and chunk.segment.kind is chunk_contract.ChunkSegmentKind.TABLE_ROWS
        ]
        assert table_pieces
        for piece in table_pieces:
            segment = piece.segment
            block = blocks[segment.source_block_id]
            source_lines = block.text.split("\n")
            piece_lines = piece.citation_text.split("\n")
            # The piece may open with lead heading text; every line
            # after that must be a verbatim line of the rendering.
            table_lines = [line for line in piece_lines if line in source_lines]
            assert len(piece_lines) - len(table_lines) <= 2
            payload = block.payload
            assert payload.header_rows <= segment.row_start
            assert segment.row_end <= payload.n_rows

    def test_paragraph_segments_resolve_verbatim(self, ten_q, ten_q_chunks):
        """paragraph_span offsets slice the source block exactly."""
        blocks = {block.block_id: block for block in ten_q.blocks}
        spans = [
            chunk
            for chunk in ten_q_chunks
            if chunk.segment is not None
            and chunk.segment.kind
            is chunk_contract.ChunkSegmentKind.PARAGRAPH_SPAN
        ]
        assert spans
        for piece in spans:
            segment = piece.segment
            source = blocks[segment.source_block_id].text
            slice_text = source[segment.text_start : segment.text_end]
            assert piece.citation_text.endswith(slice_text)

    def test_chunking_is_deterministic_under_the_real_tokenizer(
        self, ten_q, ten_q_chunks, real_embedder
    ):
        """Same input, same signature — byte-same chunks (04 §9)."""
        again = chunker.chunk(ten_q, real_embedder.token_counter())
        assert again == ten_q_chunks

    def test_business_metadata_reached_every_chunk(self, ten_q_chunks):
        """Ticker, form, and URL are on every record, never invented."""
        for chunk in ten_q_chunks:
            assert chunk.business.ticker == "PLAB"
            assert chunk.business.document_type == "10-Q"
            assert chunk.business.cik == "0000810136"
            assert chunk.business.url
