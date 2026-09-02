"""Tests for the normalized document contract (03 §5)."""

import pydantic
import pytest

from contracts import document
from contracts import quality


def _origin(row, column, text, row_span=1, column_span=1, is_header=False):
    """Build an origin cell."""
    return document.TableCell(
        row=row,
        column=column,
        is_origin=True,
        row_span=row_span,
        column_span=column_span,
        raw_text=text,
        is_header=is_header,
    )


def _covered(row, column, origin):
    """Build a covered placeholder pointing at an origin."""
    return document.TableCell(
        row=row, column=column, is_origin=False, origin=origin
    )


def _simple_table():
    """Build a 2x2 table with no merges."""
    return document.TableBlock(
        n_rows=2,
        n_columns=2,
        header_rows=1,
        cells=[
            _origin(0, 0, "Segment", is_header=True),
            _origin(0, 1, "Revenue", is_header=True),
            _origin(1, 0, "A"),
            _origin(1, 1, "1,204"),
        ],
    )


class TestGridInvariant:
    """The grid invariant is enforced structurally (03 §5.3)."""

    def test_full_grid_is_accepted(self):
        """A fully addressed grid validates."""
        assert len(_simple_table().cells) == 4

    def test_missing_coordinate_is_rejected(self):
        """A grid short of one entry is not a table."""
        with pytest.raises(pydantic.ValidationError, match="expected 4"):
            document.TableBlock(
                n_rows=2,
                n_columns=2,
                cells=[_origin(0, 0, "a"), _origin(0, 1, "b")],
            )

    def test_duplicate_coordinate_is_rejected(self):
        """Two entries at one coordinate is not a table."""
        with pytest.raises(pydantic.ValidationError, match="duplicate"):
            document.TableBlock(
                n_rows=1,
                n_columns=2,
                cells=[
                    _origin(0, 0, "a"),
                    _origin(0, 0, "b"),
                ],
            )

    def test_merged_cell_round_trips(self):
        """A merged origin plus its covered placeholder validates."""
        table = document.TableBlock(
            n_rows=1,
            n_columns=2,
            cells=[
                _origin(0, 0, "Three Months Ended", column_span=2),
                _covered(0, 1, (0, 0)),
            ],
        )
        assert table.cells[1].origin == (0, 0)

    def test_covered_cell_pointing_at_a_non_origin_is_rejected(self):
        """A covered cell must point at a real origin."""
        with pytest.raises(pydantic.ValidationError, match="not an origin"):
            document.TableBlock(
                n_rows=1,
                n_columns=3,
                cells=[
                    _origin(0, 0, "a"),
                    _covered(0, 1, (0, 2)),
                    _covered(0, 2, (0, 0)),
                ],
            )

    def test_origin_spans_must_reach_the_cells_that_point_back(self):
        """Spans and placeholders must agree exactly."""
        with pytest.raises(pydantic.ValidationError, match="do not reach it"):
            document.TableBlock(
                n_rows=1,
                n_columns=2,
                cells=[
                    _origin(0, 0, "a"),
                    _covered(0, 1, (0, 0)),
                ],
            )

    def test_span_running_off_the_grid_is_rejected(self):
        """An origin cannot span a coordinate that does not exist."""
        with pytest.raises(pydantic.ValidationError, match="outside the grid"):
            document.TableBlock(
                n_rows=1,
                n_columns=1,
                cells=[_origin(0, 0, "a", column_span=2)],
            )

    def test_blank_is_not_the_same_as_covered(self):
        """A blank source cell is an origin with empty text."""
        table = document.TableBlock(
            n_rows=1,
            n_columns=2,
            cells=[_origin(0, 0, ""), _origin(0, 1, "x")],
        )
        assert table.cells[0].raw_text == ""
        assert table.cells[0].is_origin

    def test_covered_cell_may_not_carry_content(self):
        """Only origin cells hold content."""
        with pytest.raises(pydantic.ValidationError):
            document.TableCell(
                row=0,
                column=1,
                is_origin=False,
                origin=(0, 0),
                raw_text="x",
            )

    def test_origin_cell_must_carry_raw_text(self):
        """An origin cell with null text is not a cell."""
        with pytest.raises(pydantic.ValidationError, match="raw_text"):
            document.TableCell(row=0, column=0, is_origin=True)

    def test_row_header_columns_must_be_in_range(self):
        """A stub column outside the grid is rejected."""
        with pytest.raises(pydantic.ValidationError, match="outside"):
            document.TableBlock(
                n_rows=1,
                n_columns=1,
                row_header_columns=[3],
                cells=[_origin(0, 0, "a")],
            )


class TestCanonicalRendering:
    """Canonical text is deterministic and byte-stable (03 §5.4)."""

    def test_table_renders_row_major_with_a_delimiter(self):
        """Header rows sit above the delimiter row."""
        assert document.render_table_text(_simple_table()) == (
            "| Segment | Revenue |\n" "| --- | --- |\n" "| A | 1,204 |"
        )

    def test_covered_coordinates_render_as_empty_fields(self):
        """A covered coordinate emits an empty field, not a repeat."""
        table = document.TableBlock(
            n_rows=1,
            n_columns=2,
            cells=[
                _origin(0, 0, "Three Months Ended", column_span=2),
                _covered(0, 1, (0, 0)),
            ],
        )
        assert document.render_table_text(table) == "| Three Months Ended |  |"

    def test_caption_and_unit_line_precede_the_grid(self):
        """A caption and a unit/scale line come first when known."""
        table = document.TableBlock(
            caption="Statements of Operations",
            n_rows=1,
            n_columns=1,
            cells=[_origin(0, 0, "1,204")],
            unit="USD",
            scale="millions",
            unit_source=document.UnitSource.CAPTION,
        )
        assert document.render_table_text(table).splitlines()[:2] == [
            "Statements of Operations",
            "Unit: USD; Scale: millions",
        ]

    def test_pipes_in_cells_are_escaped(self):
        """A pipe inside a cell cannot break the rendering."""
        table = document.TableBlock(
            n_rows=1,
            n_columns=1,
            cells=[_origin(0, 0, "a|b")],
        )
        assert document.render_table_text(table) == r"| a\|b |"

    def test_rendering_is_stable_across_equal_tables(self):
        """Two adapters seeing the same table produce one string."""
        assert document.render_table_text(
            _simple_table()
        ) == document.render_table_text(_simple_table())

    def test_financial_fact_rendering(self):
        """A fact renders as concept, value, unit, and period."""
        fact = document.FinancialFact(
            concept="us-gaap:Revenues",
            value=1204,
            unit="USD",
            period="2025-Q3",
        )
        assert (
            document.render_financial_fact_text(fact)
            == "us-gaap:Revenues: 1204 USD (2025-Q3)"
        )


class TestBlock:
    """Payload agreement and canonical text are enforced on Block."""

    def _extraction(self):
        """Build a minimal extraction record."""
        return document.BlockExtraction(
            adapter_name="test", adapter_version="1.0"
        )

    def test_table_text_must_be_the_canonical_rendering(self):
        """A table block cannot carry an arbitrary text field."""
        with pytest.raises(
            pydantic.ValidationError, match="canonical rendering"
        ):
            document.Block(
                block_id="b1",
                type=document.BlockType.TABLE,
                text="whatever the adapter felt like",
                payload=_simple_table(),
                locator=document.Locator(element_index=0),
                extraction=self._extraction(),
            )

    def test_text_only_block_carries_no_payload(self):
        """A paragraph with a payload is a contract violation."""
        with pytest.raises(
            pydantic.ValidationError, match="carries no payload"
        ):
            document.Block(
                block_id="b1",
                type=document.BlockType.PARAGRAPH,
                text="hello",
                payload=_simple_table(),
                locator=document.Locator(element_index=0),
                extraction=self._extraction(),
            )

    def test_table_block_requires_a_table_payload(self):
        """A table block without a grid is not a table block."""
        with pytest.raises(pydantic.ValidationError):
            document.Block(
                block_id="b1",
                type=document.BlockType.TABLE,
                text="",
                locator=document.Locator(element_index=0),
                extraction=self._extraction(),
            )

    def test_ocr_confidence_requires_ocr(self):
        """Confidence without OCR is meaningless and rejected."""
        with pytest.raises(pydantic.ValidationError, match="ocr_used"):
            document.BlockExtraction(
                adapter_name="t",
                adapter_version="1",
                ocr_confidence=0.9,
            )


class TestLocatorTiers:
    """Locators are tiered by how precisely they point (03 §5.5)."""

    def test_html_anchor_is_tier_one(self):
        """An anchor is an anchored locator."""
        locator = document.Locator(html_anchor="item1a")
        assert locator.tier() is quality.LocatorTier.ANCHORED

    def test_page_and_bbox_is_tier_one(self):
        """A page plus a bounding box is anchored."""
        locator = document.Locator(
            page=18, bounding_box=(72.1, 110.0, 510.8, 244.2)
        )
        assert locator.tier() is quality.LocatorTier.ANCHORED

    def test_page_alone_is_tier_two(self):
        """A page number alone is coarse."""
        assert document.Locator(page=18).tier() is quality.LocatorTier.COARSE

    def test_heading_path_alone_is_tier_two(self):
        """A heading path alone lifts a block to coarse."""
        locator = document.Locator(element_index=4)
        assert locator.tier() is quality.LocatorTier.DIAGNOSTIC
        assert locator.tier(has_heading_path=True) is quality.LocatorTier.COARSE

    def test_element_index_alone_is_diagnostic(self):
        """An element index is never a citation anchor."""
        assert (
            document.Locator(element_index=42).tier()
            is quality.LocatorTier.DIAGNOSTIC
        )

    def test_empty_locator_is_diagnostic(self):
        """A locator with nothing in it points nowhere useful."""
        assert document.Locator().tier() is quality.LocatorTier.DIAGNOSTIC

    def test_line_range_must_not_invert(self):
        """A line range that ends before it starts is rejected."""
        with pytest.raises(pydantic.ValidationError):
            document.Locator(line_start=10, line_end=2)


class TestCik:
    """A CIK is stored in one canonical form (03 §5.2)."""

    @pytest.mark.parametrize(
        "raw",
        ["320193", "0000320193", "CIK0000320193", "cik-320193", "320 193"],
    )
    def test_accepted_forms_normalize_to_ten_digits(self, raw):
        """Two adapters reporting one filer produce one string."""
        metadata = document.BusinessMetadata(cik=raw)
        assert metadata.cik == "0000320193"

    def test_an_integer_is_accepted(self):
        """APIs that hand back a number are handled."""
        assert document.BusinessMetadata(cik=320193).cik == "0000320193"

    def test_absent_stays_absent(self):
        """Normalization never invents metadata (03 §5.6)."""
        assert document.BusinessMetadata().cik is None
        assert document.BusinessMetadata(cik="   ").cik is None

    def test_a_non_numeric_cik_is_rejected(self):
        """Storing a company name in the CIK field fails loudly."""
        with pytest.raises(pydantic.ValidationError, match="not a number"):
            document.BusinessMetadata(cik="Apple Inc.")

    def test_an_oversized_cik_is_rejected(self):
        """More than ten digits is not a CIK."""
        with pytest.raises(pydantic.ValidationError, match="more than"):
            document.BusinessMetadata(cik="123456789012")

    def test_cik_is_optional_for_non_sec_documents(self):
        """Most documents have no filer; the gate requires it, not this."""
        metadata = document.BusinessMetadata(company="Some Publisher")
        assert metadata.cik is None


def test_block_ids_must_be_unique_in_a_document():
    """Two blocks cannot share an ID."""
    extraction = document.BlockExtraction(adapter_name="t", adapter_version="1")
    block = document.Block(
        block_id="same",
        type=document.BlockType.PARAGRAPH,
        text="hello",
        locator=document.Locator(element_index=0),
        extraction=extraction,
    )
    with pytest.raises(pydantic.ValidationError, match="unique"):
        document.ParsedDocument(
            identity=document.DocumentIdentity(
                document_id="d", version_id="v", parse_id="p"
            ),
            source=document.SourceInfo(
                source_type=document.SourceType.PLAIN_TEXT,
                source_class=document.SourceClass.USER_UPLOAD,
            ),
            blocks=[block, block],
            parse_quality=document.ParseQuality(
                verdict=quality.QualityVerdict.VALID,
                policy_version="v0",
            ),
        )
