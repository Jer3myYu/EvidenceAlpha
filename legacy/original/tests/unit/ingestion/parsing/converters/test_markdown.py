"""Tests for the ``MarkdownDocument`` converter (03 §3.6)."""

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes
from ingestion.parsing.converters import common
from ingestion.parsing.converters import markdown as markdown_converter

_CAPABILITIES = capabilities_module.AdapterCapabilities(
    block_types=frozenset(
        {
            document.BlockType.HEADING,
            document.BlockType.PARAGRAPH,
            document.BlockType.LIST,
            document.BlockType.TABLE,
            document.BlockType.CODE,
        }
    ),
    native_shape=shapes.NativeShape.MARKDOWN_DOCUMENT,
    table_fidelity=capabilities_module.TableFidelity.GRID,
    locator_tiers=frozenset({quality.LocatorTier.COARSE}),
    page_fidelity=True,
)


def _convert(markdown, page_map=None):
    """Convert markdown and return the blocks and the context."""
    context = common.ConversionContext(
        parse_id="sha256:parse",
        adapter_name="stub",
        adapter_version="1.0",
        adapter_capabilities=_CAPABILITIES,
    )
    blocks = markdown_converter.convert(
        shapes.MarkdownDocument(markdown=markdown, page_map=page_map),
        context,
    )
    return blocks, context


class TestStructure:
    """Markdown maps onto block types by fixed rules."""

    def test_atx_headings_build_a_heading_path(self):
        """Headings build `heading_path` for everything under them."""
        blocks, _ = _convert("# Part I\n\n## Item 1\n\nBusiness overview.\n")
        paragraph = blocks[-1]
        assert paragraph.type is document.BlockType.PARAGRAPH
        assert paragraph.heading_path == ["Part I", "Item 1"]

    def test_setext_headings_are_recognized(self):
        """Underlined headings work like ATX ones."""
        blocks, _ = _convert("Annual Report\n=============\n\nBody.\n")
        assert blocks[0].type is document.BlockType.HEADING
        assert blocks[0].text == "Annual Report"
        assert blocks[1].heading_path == ["Annual Report"]

    def test_fenced_code_becomes_a_code_block(self):
        """Fenced code is code, not a paragraph."""
        blocks, _ = _convert("```\nprint('x')\n```\n")
        assert blocks[0].type is document.BlockType.CODE
        assert "print" in blocks[0].text

    def test_list_items_group_into_one_block(self):
        """A run of items is one retrievable block, not many."""
        blocks, _ = _convert("- one\n- two\n- three\n")
        assert len(blocks) == 1
        assert blocks[0].type is document.BlockType.LIST
        assert blocks[0].text.splitlines() == ["one", "two", "three"]

    def test_paragraphs_break_on_blank_lines(self):
        """Two paragraphs stay two blocks."""
        blocks, _ = _convert("First para.\n\nSecond para.\n")
        assert len(blocks) == 2
        assert all(
            block.type is document.BlockType.PARAGRAPH for block in blocks
        )


class TestTables:
    """Pipe tables become a fully addressed grid."""

    def test_pipe_table_becomes_a_grid(self):
        """Header and body rows land in the right coordinates."""
        blocks, _ = _convert(
            "| Segment | Revenue |\n"
            "| --- | --- |\n"
            "| A | 1,204 |\n"
            "| B | 311 |\n"
        )
        table = blocks[0].payload
        assert blocks[0].type is document.BlockType.TABLE
        assert (table.n_rows, table.n_columns) == (3, 2)
        assert table.header_rows == 1
        assert len(table.cells) == 6
        assert table.cells[0].is_header

    def test_text_is_the_canonical_rendering(self):
        """The block's text is rendered from the grid, not copied."""
        blocks, _ = _convert("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        assert blocks[0].text == document.render_table_text(blocks[0].payload)

    def test_short_rows_pad_with_blank_origin_cells(self):
        """A ragged row keeps the grid fully addressed."""
        blocks, _ = _convert("| a | b |\n| --- | --- |\n| 1 |\n")
        table = blocks[0].payload
        assert len(table.cells) == 4
        padded = [
            cell for cell in table.cells if cell.row == 1 and cell.column == 1
        ][0]
        assert padded.is_origin
        assert padded.raw_text == ""

    def test_escaped_pipes_survive(self):
        """A pipe inside a cell is not a column separator."""
        blocks, _ = _convert(
            "| a | b |\n| --- | --- |\n" + r"| x\|y | 2 |" + "\n"
        )
        table = blocks[0].payload
        assert any(cell.raw_text == "x|y" for cell in table.cells)

    def test_the_converter_never_types_a_cell(self):
        """Typing comes from the adapter or not at all (03 §3.6)."""
        blocks, _ = _convert("| a |\n| --- |\n| 1,204 |\n")
        for cell in blocks[0].payload.cells:
            assert cell.value is None
            assert cell.value_type is None

    def test_a_pipe_line_without_a_delimiter_is_a_paragraph(self):
        """A table needs its delimiter row to be a table."""
        blocks, _ = _convert("| not | a table |\n")
        assert blocks[0].type is document.BlockType.PARAGRAPH


class TestPageMap:
    """A page map is what buys tier-2 locators (03 §3.6)."""

    def test_page_map_yields_page_locators(self):
        """Offsets map onto pages."""
        markdown = "First page text.\n\nSecond page text.\n"
        split = markdown.index("Second")
        blocks, _ = _convert(
            markdown,
            page_map=[
                shapes.PageSpan(page=1, start=0, end=split),
                shapes.PageSpan(page=2, start=split, end=len(markdown)),
            ],
        )
        assert blocks[0].locator.page == 1
        assert blocks[1].locator.page == 2
        assert blocks[1].locator_tier is quality.LocatorTier.COARSE

    def test_a_missing_page_map_is_reported(self):
        """The cap on locator tier is a document-level fact."""
        _, context = _convert("Body text.\n")
        codes = {warning.code for warning in context.warnings}
        assert quality.WarningCode.PAGE_MAP_MISSING in codes

    def test_without_a_page_map_a_lone_paragraph_is_diagnostic(self):
        """No page and no heading path means tier 3."""
        blocks, _ = _convert("Body text.\n")
        assert blocks[0].locator_tier is quality.LocatorTier.DIAGNOSTIC


def test_conversion_is_deterministic():
    """The same markdown converts to the same blocks every time."""
    markdown = "# T\n\nBody.\n\n| a |\n| --- |\n| 1 |\n"
    first, _ = _convert(markdown)
    second, _ = _convert(markdown)
    assert [block.model_dump_json() for block in first] == [
        block.model_dump_json() for block in second
    ]
