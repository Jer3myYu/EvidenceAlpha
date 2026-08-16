"""Golden tests for the digital-PDF adapter (03 §13).

Contract compliance lives in the shared conformance suite; these tests
pin **content** against the generated two-page fixture — a page
locator, the table's shape and a specific cell value, and coverage —
plus the scanned-PDF refusal, which is the route's one controlled
branch (03 §4.3).
"""

# pylint: disable=protected-access  # white-box tests of adapter internals

import os

import pymupdf
import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import gate as gate_module
from ingestion.parsing import service as service_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import pdf_pymupdf
from tests.unit.ingestion.parsing import pdf_fixture


def _artifact(path: str) -> shapes.AcquiredArtifact:
    """Build the artifact the ingestion service would hand over."""
    return shapes.AcquiredArtifact(
        path=path,
        content_hash="sha256:golden",
        size_bytes=os.path.getsize(path),
        document_id="doc_golden",
        version_id="sha256:golden-version",
        source_class=document.SourceClass.IR_DOCUMENT,
        filename=os.path.basename(path),
    )


@pytest.fixture(name="parsed")
def parsed_fixture(tmp_path):
    """Parse the generated fixture once."""
    path = str(tmp_path / "fixture.pdf")
    pdf_fixture.write_pdf(path)
    return service_module.ParserService().parse(_artifact(path))


class TestDigitalPdf:
    """The generated digital fixture (03 §13)."""

    def test_the_parse_is_valid(self, parsed):
        """Both pages emit and every gate check passes."""
        assert parsed.status is quality.QualityVerdict.VALID
        assert parsed.parser_used == "pdf_pymupdf"
        assert not parsed.parsed_document.parse_quality.rejected_blocks

    def test_page_coverage_is_exact(self, parsed):
        """Pages emitted equal the container page count (03 §7.1)."""
        assert parsed.metrics.pages == 2
        pages = {block.locator.page for block in parsed.parsed_document.blocks}
        assert pages == {1, 2}

    def test_the_table_grid_survives_with_values(self, parsed):
        """The ruled table arrives as a grid with a known cell."""
        tables = [
            block
            for block in parsed.parsed_document.blocks
            if block.type is document.BlockType.TABLE
        ]
        assert len(tables) == 1
        grid = tables[0].payload
        assert (grid.n_rows, grid.n_columns) == (4, 3)
        by_coordinate = {(cell.row, cell.column): cell for cell in grid.cells}
        assert by_coordinate[(1, 0)].raw_text == "Revenue"
        assert by_coordinate[(1, 1)].raw_text == "849,294"
        assert tables[0].locator.page == 2

    def test_every_block_is_page_anchored(self, parsed):
        """Every block carries page plus bounding box — tier 1."""
        for block in parsed.parsed_document.blocks:
            assert block.locator.page is not None
            assert block.locator.bounding_box is not None
            assert block.locator_tier is quality.LocatorTier.ANCHORED

    def test_table_text_is_not_duplicated_as_paragraphs(self, parsed):
        """Text inside the table region is not emitted twice."""
        paragraphs = [
            block.text
            for block in parsed.parsed_document.blocks
            if block.type is document.BlockType.PARAGRAPH
        ]
        assert not any("849,294" in text for text in paragraphs)


class TestScannedRefusal:
    """The route's controlled branch for image-only PDFs (03 §4.3)."""

    def test_an_image_only_pdf_is_refused_by_name(self, tmp_path):
        """Insufficient embedded text names ``scanned_pdf``, no retry."""
        path = str(tmp_path / "scanned.pdf")
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.draw_rect(
            pymupdf.Rect(100, 100, 400, 400), color=(0, 0, 0), width=2
        )
        pdf.save(path)
        pdf.close()
        result = service_module.ParserService().parse(_artifact(path))
        assert result.status is quality.QualityVerdict.FAILED
        assert result.error.code is shapes.ParserErrorCode.UNSUPPORTED_FORMAT
        assert "scanned_pdf" in result.error.message
        assert result.retry_with is shapes.RetryWith.NONE
        assert result.fallback_used is False

    def test_the_metric_is_shared_with_the_gate_policy(self):
        """Routing and gating read the same numbers (03 §4.3)."""
        policy = gate_module.POLICY_V0
        assert pdf_pymupdf.has_sufficient_embedded_text([500, 600, 700], policy)
        assert not pdf_pymupdf.has_sufficient_embedded_text([0, 0, 0], policy)
        assert not pdf_pymupdf.has_sufficient_embedded_text([], policy)
        sparse = [500] * 6 + [10] * 4
        assert not pdf_pymupdf.has_sufficient_embedded_text(sparse, policy)


class TestVerifierFindings:
    """Regressions for the 2026-08-15 adversarial verification round."""

    def test_split_parentheses_are_rejoined(self):
        """``(240`` and ``)`` in adjacent cells become ``(240)`` (F6)."""
        matrix = [["Interest expense", "(240", ")", None]]
        pdf_pymupdf._merge_split_parentheses(matrix)
        assert matrix[0] == ["Interest expense", "(240)", "", None]

    def test_a_closed_number_is_left_alone(self):
        """A stray ``)`` with no open number stays where it is."""
        matrix = [["(240)", ")", "x"]]
        pdf_pymupdf._merge_split_parentheses(matrix)
        assert matrix[0] == ["(240)", ")", "x"]

    def test_collapsed_rows_carry_a_structure_warning(self):
        """Several figures in one cell flag TABLE_STRUCTURE_LOST (F2)."""
        cells = [
            document.TableCell(
                row=0, column=0, is_origin=True, raw_text="Cash 95,909 42,184"
            ),
            document.TableCell(row=0, column=1, is_origin=True, raw_text=""),
        ]
        grid = document.TableBlock(n_rows=1, n_columns=2, cells=cells)
        warnings = pdf_pymupdf._grid_warnings(grid)
        assert [w.code for w in warnings] == [
            quality.WarningCode.TABLE_STRUCTURE_LOST
        ]

    def test_a_clean_row_raises_no_warning(self):
        """A properly split row is not flagged."""
        cells = [
            document.TableCell(
                row=0, column=0, is_origin=True, raw_text="Cash"
            ),
            document.TableCell(
                row=0, column=1, is_origin=True, raw_text="95,909"
            ),
        ]
        grid = document.TableBlock(n_rows=1, n_columns=2, cells=cells)
        assert not pdf_pymupdf._grid_warnings(grid)

    def test_text_the_grid_missed_is_not_dropped(self):
        """A page block overlapping a table region is only suppressed
        when the grid's rendering actually contains its text (F1)."""
        region = pymupdf.Rect(0, 0, 100, 100)
        walker = pdf_pymupdf._PageWalker("pdf_pymupdf", "1.0")
        captured = walker._captured_by_table(
            pymupdf.Rect(10, 10, 60, 30),
            "Revenue 849,294",
            [(region, pdf_pymupdf._containment_key("| Revenue | 849,294 |"))],
        )
        missed = walker._captured_by_table(
            pymupdf.Rect(10, 10, 60, 30),
            "October 31, 2023",
            [(region, pdf_pymupdf._containment_key("| Revenue | 849,294 |"))],
        )
        assert captured is True
        assert missed is False
