"""Tests for shared normalization (03 §5.4, §5.6)."""

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes
from ingestion.parsing.converters import common


def _capabilities(table_fidelity, extraction_class=None):
    """Build capabilities with a given table fidelity."""
    return capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.TABLE}),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=table_fidelity,
        locator_tiers=frozenset({quality.LocatorTier.ANCHORED}),
        extraction_class=(
            extraction_class or capabilities_module.ExtractionClass.RULE_BASED
        ),
    )


def _context(table_fidelity=None, extraction_class=None):
    """Build a conversion context."""
    return common.ConversionContext(
        parse_id="sha256:parse",
        adapter_name="stub",
        adapter_version="1.0",
        adapter_capabilities=_capabilities(
            table_fidelity or capabilities_module.TableFidelity.GRID,
            extraction_class,
        ),
    )


def _typed_table():
    """Build a one-cell table whose cell carries typing."""
    return document.TableBlock(
        n_rows=1,
        n_columns=1,
        cells=[
            document.TableCell(
                row=0,
                column=0,
                is_origin=True,
                raw_text="1,204",
                value=1204,
                value_type=document.ValueType.NUMBER,
            )
        ],
    )


class TestNormalizeText:
    """Deterministic mappings only (03 §5.6)."""

    def test_line_endings_are_normalized(self):
        """CRLF and CR both become LF."""
        assert common.normalize_text("a\r\nb\rc") == "a\nb\nc"

    def test_runs_of_whitespace_collapse(self):
        """Tabs and repeated spaces collapse within a line."""
        assert common.normalize_text("a  \t b") == "a b"

    def test_non_breaking_spaces_become_spaces(self):
        """Financial HTML is full of non-breaking spaces."""
        assert common.normalize_text("1,204\xa0USD") == "1,204 USD"

    def test_financial_notation_survives(self):
        """Parentheses, signs, and symbols are never stripped."""
        text = "$(1,204.50) -3.2% — net"
        assert common.normalize_text(text) == text

    def test_leading_and_trailing_blank_lines_are_removed(self):
        """Surrounding blank lines carry no meaning."""
        assert common.normalize_text("\n\nbody\n\n") == "body"


class TestBlockIds:
    """Stable IDs are a pure function of identity and position."""

    def test_the_same_inputs_give_the_same_id(self):
        """Re-running the pipeline reproduces block IDs."""
        locator = document.Locator(page=3)
        assert common.make_block_id(
            "sha256:p", 4, locator
        ) == common.make_block_id("sha256:p", 4, locator)

    def test_a_different_parse_id_gives_a_different_id(self):
        """A new manifest produces a new set of block IDs."""
        locator = document.Locator(page=3)
        assert common.make_block_id(
            "sha256:a", 4, locator
        ) != common.make_block_id("sha256:b", 4, locator)

    def test_a_different_position_gives_a_different_id(self):
        """Two blocks in one document never collide."""
        locator = document.Locator(page=3)
        assert common.make_block_id(
            "sha256:p", 4, locator
        ) != common.make_block_id("sha256:p", 5, locator)


class TestTableTyping:
    """The converter never infers a cell type (03 §3.6)."""

    def test_typing_is_stripped_below_typed_grid(self):
        """Undeclared typing is discarded, with a warning."""
        table, warnings = common.enforce_table_typing(
            _typed_table(), capabilities_module.TableFidelity.GRID
        )
        assert table.cells[0].value is None
        assert table.cells[0].value_type is None
        assert table.cells[0].raw_text == "1,204"
        assert warnings[0].code is quality.WarningCode.TABLE_TYPING_UNAVAILABLE

    def test_typing_survives_when_declared(self):
        """A typed_grid adapter keeps its types."""
        table, warnings = common.enforce_table_typing(
            _typed_table(), capabilities_module.TableFidelity.TYPED_GRID
        )
        assert table.cells[0].value == 1204
        assert not warnings

    def test_an_untyped_table_raises_no_warning(self):
        """Nothing to strip means nothing to report."""
        table = document.TableBlock(
            n_rows=1,
            n_columns=1,
            cells=[
                document.TableCell(
                    row=0, column=0, is_origin=True, raw_text="a"
                )
            ],
        )
        _, warnings = common.enforce_table_typing(
            table, capabilities_module.TableFidelity.GRID
        )
        assert not warnings


class TestBuildBlock:
    """Canonical text is rendered here, never taken from the adapter."""

    def test_table_text_is_rendered_from_the_payload(self):
        """A table's text comes from its grid (03 §5.4)."""
        block = common.build_block(
            context=_context(),
            ordinal=0,
            block_type=document.BlockType.TABLE,
            text="ignored entirely",
            locator=document.Locator(html_anchor="t1"),
            payload=_typed_table(),
        )
        assert block.text == document.render_table_text(block.payload)
        assert "1,204" in block.text

    def test_paragraph_text_is_normalized(self):
        """Text-bearing blocks are normalized, not re-rendered."""
        block = common.build_block(
            context=_context(),
            ordinal=0,
            block_type=document.BlockType.PARAGRAPH,
            text="a  \t b",
            locator=document.Locator(html_anchor="p1"),
        )
        assert block.text == "a b"

    def test_generative_extraction_is_marked_on_every_block(self):
        """A generative adapter's output is flagged (03 §3.8)."""
        block = common.build_block(
            context=_context(
                extraction_class=(
                    capabilities_module.ExtractionClass.GENERATIVE
                )
            ),
            ordinal=0,
            block_type=document.BlockType.PARAGRAPH,
            text="Revenue was 1,204.",
            locator=document.Locator(html_anchor="p1"),
        )
        codes = {warning.code for warning in block.extraction.warnings}
        assert quality.WarningCode.GENERATIVE_EXTRACTION in codes


class TestHeadingStack:
    """`heading_path` is enclosing headings, outermost first."""

    def test_nesting_builds_a_path(self):
        """A deeper heading extends the path."""
        stack = common.HeadingStack()
        stack.push(1, "Part I")
        stack.push(2, "Item 1")
        assert stack.path() == ["Part I", "Item 1"]

    def test_a_sibling_replaces_its_predecessor(self):
        """A same-level heading pops the previous one."""
        stack = common.HeadingStack()
        stack.push(1, "Part I")
        stack.push(2, "Item 1")
        stack.push(2, "Item 1A")
        assert stack.path() == ["Part I", "Item 1A"]

    def test_a_shallower_heading_unwinds(self):
        """Returning to an outer level drops the inner ones."""
        stack = common.HeadingStack()
        stack.push(1, "Part I")
        stack.push(2, "Item 1")
        stack.push(1, "Part II")
        assert stack.path() == ["Part II"]

    def test_a_format_without_headings_has_an_empty_path(self):
        """CSV, JSON, and spreadsheets simply never push."""
        assert common.HeadingStack().path() == []
