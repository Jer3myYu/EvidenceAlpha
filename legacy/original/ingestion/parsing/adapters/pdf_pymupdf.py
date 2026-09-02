"""Digital-PDF adapter over PyMuPDF (03 §4.3, §14 step 7).

The PyMuPDF table spike (2026-08-15) confirmed real cell grids on the
golden filing — the Photronics 10-K income statement extracts as a
48x13 grid with correct values — so the route minimum stays
``table_fidelity >= GRID``.

Every block is anchored at ``page`` plus ``bounding_box`` (tier 1), and
pages are walked in order so the block sequence is monotonic in its
page dimension. Text that lies inside a detected table's bounding box
is not emitted again as a paragraph.

The route first computes the embedded-text metric of 03 §4.3 — the
same numbers as the gate's quality policy, so routing and gating can
never disagree. A document below it is a scanned PDF; that route is
not in the MVP profile, so the adapter refuses with
:class:`~ingestion.parsing.adapters.base.UnsupportedContent` naming
``scanned_pdf``, which the service reports as ``UNSUPPORTED_FORMAT``
without spending the fallback.
"""

import re
import statistics

import pymupdf

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector
from ingestion.parsing import gate as gate_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import base

#: The format name reported for an image-only PDF (03 §4.3).
_SCANNED_FORMAT = "scanned_pdf"


def _clean(text: str) -> str:
    """Collapse whitespace in extracted text."""
    return " ".join(text.split())


def has_sufficient_embedded_text(
    page_characters: list[int], policy: gate_module.QualityPolicy
) -> bool:
    """Decide the digital-versus-scanned split (03 §4.3).

    One shared predicate, driven by the versioned quality policy, so the
    OCR routing decision and the PDF quality gate use the same numbers.

    Args:
      page_characters: Extracted character count per page.
      policy: The quality policy in force.

    Returns:
      Whether the document has enough embedded text for a digital
      parse.
    """
    if not page_characters:
        return False
    median = statistics.median(page_characters)
    if median < policy.pdf_ocr_median_chars_per_page:
        return False
    sparse = sum(
        1
        for count in page_characters
        if count < policy.pdf_ocr_sparse_page_char_floor
    )
    return sparse / len(page_characters) <= policy.pdf_ocr_sparse_page_fraction


class PdfPymupdfAdapter:
    """Digital PDF text, tables, and coordinates over PyMuPDF."""

    name = "pdf_pymupdf"
    version = "1.0"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset(
            {
                document.BlockType.PARAGRAPH,
                document.BlockType.TABLE,
            }
        ),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=frozenset({quality.LocatorTier.ANCHORED}),
        page_fidelity=True,
        extraction_class=capabilities_module.ExtractionClass.RULE_BASED,
        determinism=capabilities_module.Determinism.PINNED,
        egress=capabilities_module.Egress.NONE,
    )

    def __init__(self, policy: gate_module.QualityPolicy | None = None) -> None:
        """Initialize the adapter.

        Args:
          policy: The quality policy whose OCR-routing thresholds apply;
            :data:`ingestion.parsing.gate.POLICY_V0` when omitted.
        """
        self._policy = policy or gate_module.POLICY_V0

    def supports(self, request: base.ParseRequest) -> bool:
        """Accept detected PDFs only.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          Whether this adapter serves the detected format.
        """
        return request.detection.format is detector.DetectedFormat.PDF

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Parse one digital PDF into normalized blocks.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          A ``BlockSequence`` raw result with page-anchored blocks.

        Raises:
          base.UnsupportedContent: If the embedded-text metric says the
            document is a scanned PDF (03 §4.3).
          base.AdapterError: If the PDF cannot be opened.
        """
        try:
            pdf = pymupdf.open(request.artifact.path)
        except (RuntimeError, ValueError, OSError) as error:
            raise base.AdapterError(f"cannot open PDF: {error}") from error
        try:
            return self._parse_open(pdf)
        finally:
            pdf.close()

    def _parse_open(self, pdf: pymupdf.Document) -> shapes.RawParseResult:
        """Parse an opened document."""
        page_characters = [
            len(page.get_text())
            for page in pdf  # pylint: disable=not-an-iterable
        ]
        if not has_sufficient_embedded_text(page_characters, self._policy):
            raise base.UnsupportedContent(
                _SCANNED_FORMAT,
                (
                    "the document has insufficient embedded text for a "
                    "digital parse and the scanned-PDF route is not in "
                    "the MVP profile (03 §2.1)"
                ),
            )

        builder = _PageWalker(self.name, self.version)
        for page in pdf:  # pylint: disable=not-an-iterable
            builder.walk_page(page)
        return shapes.RawParseResult(
            content=shapes.BlockSequence(blocks=builder.blocks),
            source_type=document.SourceType.PDF_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
            library_versions={"pymupdf": pymupdf.__version__},
            page_count=len(pdf),
            element_count=len(builder.blocks),
        )


class _PageWalker:
    """Accumulates page-anchored blocks in reading order."""

    def __init__(self, adapter_name: str, adapter_version: str) -> None:
        """Initialize the walker.

        Args:
          adapter_name: Name recorded in each block's provenance.
          adapter_version: Version recorded alongside it.
        """
        self.blocks: list[document.Block] = []
        self._extraction = document.BlockExtraction(
            adapter_name=adapter_name, adapter_version=adapter_version
        )

    def _append(
        self,
        block_type: document.BlockType,
        text: str,
        page_number: int,
        bbox: tuple[float, float, float, float],
        payload: document.TableBlock | None = None,
        block_warnings: list[document.ParseWarning] | None = None,
    ) -> None:
        """Append one block anchored at one page region."""
        extraction = self._extraction
        if block_warnings:
            extraction = extraction.model_copy(
                update={"warnings": list(block_warnings)}
            )
        self.blocks.append(
            document.Block(
                block_id=f"pdf-{len(self.blocks)}",
                type=block_type,
                text=text,
                payload=payload,
                locator=document.Locator(
                    page=page_number,
                    bounding_box=(
                        round(bbox[0], 2),
                        round(bbox[1], 2),
                        round(bbox[2], 2),
                        round(bbox[3], 2),
                    ),
                ),
                extraction=extraction,
            )
        )

    def walk_page(self, page: pymupdf.Page) -> None:
        """Emit table and paragraph blocks for one page, in page order.

        Blocks are gathered first and emitted sorted by their top edge,
        so the sequence reconstructs the page instead of listing every
        table before every paragraph (verifier finding F4, 2026-08-15).

        Text overlapping a table region is suppressed only when the
        grid actually captured it. ``find_tables`` regularly claims a
        bbox that covers the column-period headers without extracting
        them; dropping such text loses exactly the labels that give a
        financial column its meaning (verifier finding F1).

        Args:
          page: The page to walk.
        """
        page_number = page.number + 1
        staged: list[tuple[float, float, dict]] = []
        table_regions: list[tuple[pymupdf.Rect, str]] = []
        for table in page.find_tables().tables:
            grid = _build_grid(table)
            if grid is None:
                continue
            rendered = document.render_table_text(grid)
            table_regions.append(
                (pymupdf.Rect(table.bbox), _containment_key(rendered))
            )
            staged.append(
                (
                    table.bbox[1],
                    table.bbox[0],
                    {
                        "block_type": document.BlockType.TABLE,
                        "text": rendered,
                        "bbox": tuple(table.bbox),
                        "payload": grid,
                        "block_warnings": _grid_warnings(grid),
                    },
                )
            )

        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text, _, block_type = block
            if block_type != 0:
                continue
            cleaned = _clean(text)
            if not cleaned:
                continue
            rect = pymupdf.Rect(x0, y0, x1, y1)
            if self._captured_by_table(rect, cleaned, table_regions):
                continue
            staged.append(
                (
                    y0,
                    x0,
                    {
                        "block_type": document.BlockType.PARAGRAPH,
                        "text": cleaned,
                        "bbox": (x0, y0, x1, y1),
                    },
                )
            )

        for _, _, kwargs in sorted(staged, key=lambda item: (item[0], item[1])):
            self._append(page_number=page_number, **kwargs)

    @staticmethod
    def _captured_by_table(
        rect: pymupdf.Rect,
        cleaned: str,
        table_regions: list[tuple[pymupdf.Rect, str]],
    ) -> bool:
        """Return whether a text block is already inside a table grid.

        True only when the block mostly overlaps a table region **and**
        the grid's rendered content actually contains the block's text —
        otherwise the text would be lost, not deduplicated.
        """
        area = abs(rect.get_area())
        if area <= 0:
            return True
        key = _containment_key(cleaned)
        for region, table_key in table_regions:
            overlap = rect & region
            if abs(overlap.get_area()) / area < 0.5:
                continue
            if not key or key in table_key:
                return True
        return False


def _containment_key(text: str) -> str:
    """Reduce text to a whitespace- and pipe-free containment key.

    Used to decide whether a table's rendered grid already carries a
    page text block: cell boundaries insert pipes and spacing, so the
    comparison has to ignore both.
    """
    return "".join(char for char in text if not char.isspace() and char != "|")


#: A run of digits with grouping/decimal marks — two of these in one
#: cell while the rest of the row is empty is the collapsed-row smell.
_NUMBER_TOKEN = re.compile(r"\d[\d,.]*")


def _grid_warnings(grid: document.TableBlock) -> list[document.ParseWarning]:
    """Flag rows whose columns collapsed into a single cell.

    ``find_tables`` sometimes fails to split a borderless row into
    columns, leaving several figures in column 0 (verifier finding F2,
    2026-08-15). The values are intact but the structure is not, so the
    block carries ``TABLE_STRUCTURE_LOST`` into chunk metadata rather
    than looking indistinguishable from a clean grid.
    """
    by_row: dict[int, list[document.TableCell]] = {}
    for cell in grid.cells:
        by_row.setdefault(cell.row, []).append(cell)
    collapsed = 0
    for cells in by_row.values():
        filled = [cell for cell in cells if cell.raw_text]
        if len(filled) != 1:
            continue
        if len(_NUMBER_TOKEN.findall(filled[0].raw_text or "")) >= 2:
            collapsed += 1
    if not collapsed:
        return []
    return [
        document.ParseWarning(
            code=quality.WarningCode.TABLE_STRUCTURE_LOST,
            message=(
                f"{collapsed} of {grid.n_rows} rows were not split into "
                "columns; their figures sit in one cell"
            ),
        )
    ]


def _merge_split_parentheses(matrix: list[list[str | None]]) -> None:
    """Rejoin negative numbers split as ``(240`` and ``)`` cells.

    A mechanical repair of a common ``find_tables`` artifact (verifier
    finding F6): the closing parenthesis of a negative figure lands in
    its own cell, losing the sign unless the cells are read together.
    """
    for row in matrix:
        for index in range(1, len(row)):
            if row[index] is None or row[index].strip() != ")":
                continue
            for back in range(index - 1, -1, -1):
                previous = row[back]
                if previous is None or not previous.strip():
                    continue
                stripped = previous.strip()
                if stripped.startswith("(") and not stripped.endswith(")"):
                    row[back] = f"{stripped})"
                    row[index] = ""
                break


def _build_grid(table: "pymupdf.table.Table") -> document.TableBlock | None:
    """Convert one PyMuPDF table to the contract grid (03 §5.3).

    PyMuPDF reports a rectangular text matrix; a coordinate it could
    not attribute arrives as None and becomes an empty origin cell.
    Merge information is not reported, so every cell is a 1x1 origin —
    grid fidelity, not merged-span fidelity, which is what the route
    minimum requires.

    Args:
      table: The detected table.

    Returns:
      The grid, or None for a degenerate detection.
    """
    matrix = table.extract()
    if not matrix:
        return None
    _merge_split_parentheses(matrix)
    n_rows = len(matrix)
    n_columns = max(len(row) for row in matrix)
    if n_columns == 0:
        return None
    cells: list[document.TableCell] = []
    for row_index in range(n_rows):
        row = matrix[row_index]
        for column in range(n_columns):
            raw = row[column] if column < len(row) else None
            cells.append(
                document.TableCell(
                    row=row_index,
                    column=column,
                    is_origin=True,
                    row_span=1,
                    column_span=1,
                    raw_text=_clean(raw) if raw is not None else "",
                )
            )
    grid = document.TableBlock(
        n_rows=n_rows,
        n_columns=n_columns,
        cells=cells,
    )
    if not any(cell.raw_text for cell in grid.cells):
        return None
    return grid
