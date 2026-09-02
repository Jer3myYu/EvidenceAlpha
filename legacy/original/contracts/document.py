"""The normalized document contract (03 §5).

Every successful parse converges on :class:`ParsedDocument`, whatever
adapter produced it. This module is part of the neutral ``contracts``
layer: it imports :mod:`contracts.quality` and nothing else in the
project, so the chunker, indexer, and retrieval can depend on these
types without depending on ``ingestion`` (01 §8).

Three invariants are enforced structurally rather than by convention:

* **The table grid invariant** (03 §5.3) — a table carries exactly
  ``n_rows * n_columns`` cell entries, each either an origin cell that
  owns its content and declares its spans or a covered placeholder
  pointing at the origin that subsumes it.
* **Canonical text** (03 §5.4) — a table or financial-fact block's
  ``text`` must equal the deterministic rendering of its payload, so the
  chunker never re-renders structure.
* **Payload/type agreement** — a block's payload class is fixed by its
  type, and text-only types carry no payload.
"""

import datetime
import enum
from typing import Any

import pydantic

from contracts import quality

#: Version of this ``ParsedDocument`` contract. Bump on any change that
#: alters the shape or meaning of the models below.
SCHEMA_VERSION = "1.1"

#: Canonical width of an SEC CIK, zero-padded (03 §5.2).
_CIK_DIGITS = 10

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


@enum.unique
class BlockType(enum.StrEnum):
    """Normalized block kinds (03 §5.3).

    ``page_break`` is deliberately absent: a page boundary is positional
    information and lives in the locator, not in a block that would
    become an empty chunk.
    """

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    KEY_VALUE = "key_value"
    FINANCIAL_FACT = "financial_fact"
    IMAGE_TEXT = "image_text"
    CODE = "code"


#: Block types whose content is fully carried by ``text``. These must
#: not carry a payload.
TEXT_ONLY_BLOCK_TYPES: frozenset[BlockType] = frozenset(
    {
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST,
        BlockType.IMAGE_TEXT,
        BlockType.CODE,
    }
)


@enum.unique
class ValueType(enum.StrEnum):
    """Conservative type assigned to a parsed table cell (03 §5.3)."""

    NUMBER = "number"
    PERCENT = "percent"
    DATE = "date"
    TEXT = "text"


@enum.unique
class UnitSource(enum.StrEnum):
    """Where a table's unit or scale was stated (03 §5.3)."""

    CAPTION = "caption"
    COLUMN_HEADER = "column_header"
    ROW_HEADER = "row_header"
    CELL = "cell"
    NONE = "none"


@enum.unique
class SourceClass(enum.StrEnum):
    """Trusted caller context asserted by ingestion (03 §3.1).

    This is what the caller declared about the artifact, never something
    the parser infers. Compare with :class:`SourceType`, which is what
    parsing concluded; a disagreement between the two is a meaningful
    signal about the acquisition, not about the parse.
    """

    SEC_FILING = "sec_filing"
    NEWS_ARTICLE = "news_article"
    IR_DOCUMENT = "ir_document"
    USER_UPLOAD = "user_upload"


@enum.unique
class SourceType(enum.StrEnum):
    """Normalized document class concluded during parsing (03 §5.2)."""

    SEC_FILING = "sec_filing"
    NEWS_ARTICLE = "news_article"
    IR_DOCUMENT = "ir_document"
    GENERIC_HTML = "generic_html"
    PDF_DOCUMENT = "pdf_document"
    WORD_DOCUMENT = "word_document"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    DELIMITED_DATA = "delimited_data"
    XBRL_INSTANCE = "xbrl_instance"
    XML_DOCUMENT = "xml_document"
    MARKDOWN_DOCUMENT = "markdown_document"
    PLAIN_TEXT = "plain_text"
    JSON_DOCUMENT = "json_document"
    IMAGE = "image"
    UNKNOWN = "unknown"


class Locator(pydantic.BaseModel):
    """A format-native pointer at a piece of content (03 §5.5).

    Locators are tiered rather than uniform, because adapters differ in
    how precisely they can point. ``element_index`` is diagnostic only
    and must never be the sole anchor for a citation: block sequences
    legitimately shift between parse manifests.
    """

    model_config = _MODEL_CONFIG

    html_anchor: str | None = None
    xpath: str | None = None
    page: int | None = pydantic.Field(default=None, ge=1)
    bounding_box: tuple[float, float, float, float] | None = None
    slide: int | None = pydantic.Field(default=None, ge=1)
    sheet: str | None = None
    cell_range: str | None = None
    line_start: int | None = pydantic.Field(default=None, ge=1)
    line_end: int | None = pydantic.Field(default=None, ge=1)
    element_index: int | None = pydantic.Field(default=None, ge=0)

    @pydantic.model_validator(mode="after")
    def _check_line_range(self) -> "Locator":
        """Reject a line range that ends before it starts."""
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must not precede line_start")
        return self

    def tier(self, has_heading_path: bool = False) -> quality.LocatorTier:
        """Return the locator tier this locator reaches (03 §5.5).

        Args:
          has_heading_path: Whether the owning block has a non-empty
            ``heading_path``. A heading path alone is a tier-2 signal,
            and it lives on the block rather than on the locator.

        Returns:
          The best tier the available fields support.
        """
        anchored = (
            self.html_anchor is not None
            or self.xpath is not None
            or (self.page is not None and self.bounding_box is not None)
            or (self.sheet is not None and self.cell_range is not None)
            or self.slide is not None
        )
        if anchored:
            return quality.LocatorTier.ANCHORED
        coarse = (
            self.page is not None
            or self.line_start is not None
            or self.line_end is not None
            or has_heading_path
        )
        if coarse:
            return quality.LocatorTier.COARSE
        return quality.LocatorTier.DIAGNOSTIC


class ParseWarning(pydantic.BaseModel):
    """One closed-enum warning, optionally pointed at a location."""

    model_config = _MODEL_CONFIG

    code: quality.WarningCode
    message: str
    locator: Locator | None = None


class TableCell(pydantic.BaseModel):
    """One entry in a table's fully addressed logical grid (03 §5.3).

    A cell is either an **origin** — it owns content and declares its
    spans — or a **covered** placeholder naming the origin that subsumes
    it. A blank cell that exists in the source is an origin with
    ``raw_text = ""``; only covered coordinates carry ``raw_text`` of
    ``None``.
    """

    model_config = _MODEL_CONFIG

    row: int = pydantic.Field(ge=0)
    column: int = pydantic.Field(ge=0)
    is_origin: bool
    row_span: int | None = pydantic.Field(default=None, ge=1)
    column_span: int | None = pydantic.Field(default=None, ge=1)
    origin: tuple[int, int] | None = None
    raw_text: str | None = None
    value: int | float | str | None = None
    value_type: ValueType | None = None
    is_header: bool = False
    locator: Locator | None = None

    @pydantic.model_validator(mode="before")
    @classmethod
    def _default_origin_spans(cls, data: Any) -> Any:
        """Default an origin cell's spans to 1 when unstated."""
        if isinstance(data, dict) and data.get("is_origin"):
            data = dict(data)
            data.setdefault("row_span", 1)
            data.setdefault("column_span", 1)
        return data

    @pydantic.model_validator(mode="after")
    def _check_origin_or_covered(self) -> "TableCell":
        """Enforce the origin/covered split on a single cell."""
        if self.is_origin:
            if self.origin is not None:
                raise ValueError("an origin cell must not name an origin")
            if self.row_span is None or self.column_span is None:
                raise ValueError("an origin cell must declare its spans")
            if self.raw_text is None:
                raise ValueError(
                    "an origin cell must carry raw_text; a blank source "
                    'cell is "", not null'
                )
            return self
        if self.origin is None:
            raise ValueError("a covered cell must name its origin")
        if self.row_span is not None or self.column_span is not None:
            raise ValueError("only an origin cell may declare spans")
        if self.raw_text is not None or self.value is not None:
            raise ValueError("a covered cell holds no content")
        if self.value_type is not None or self.is_header:
            raise ValueError("a covered cell holds no content")
        if self.origin == (self.row, self.column):
            raise ValueError("a covered cell cannot be its own origin")
        return self


class TableBlock(pydantic.BaseModel):
    """The payload of a ``table`` block (03 §5.3).

    The grid is fully addressed: for every coordinate in
    ``n_rows x n_columns`` there is exactly one entry, and each entry is
    either an origin cell or a covered placeholder pointing at the
    origin that subsumes it. Nothing else is legal, which is what makes
    the canonical rendering in :func:`render_table_text` deterministic.
    """

    model_config = _MODEL_CONFIG

    caption: str | None = None
    n_rows: int = pydantic.Field(ge=0)
    n_columns: int = pydantic.Field(ge=0)
    header_rows: int = pydantic.Field(default=0, ge=0)
    row_header_columns: list[int] = pydantic.Field(default_factory=list)
    cells: list[TableCell] = pydantic.Field(default_factory=list)
    unit: str | None = None
    scale: str | None = None
    unit_source: UnitSource = UnitSource.NONE

    @pydantic.model_validator(mode="after")
    def _check_grid_invariant(self) -> "TableBlock":
        """Enforce the table grid invariant (03 §5.3)."""
        if self.header_rows > self.n_rows:
            raise ValueError("header_rows exceeds n_rows")
        for column in self.row_header_columns:
            if not 0 <= column < self.n_columns:
                raise ValueError(
                    f"row_header_columns entry {column} is outside the grid"
                )
        if len(set(self.row_header_columns)) != len(self.row_header_columns):
            raise ValueError("row_header_columns contains a duplicate")

        expected = self.n_rows * self.n_columns
        if len(self.cells) != expected:
            raise ValueError(
                f"grid invariant: expected {expected} cell entries "
                f"({self.n_rows} x {self.n_columns}), got {len(self.cells)}"
            )
        by_coordinate: dict[tuple[int, int], TableCell] = {}
        for cell in self.cells:
            coordinate = (cell.row, cell.column)
            if coordinate in by_coordinate:
                raise ValueError(
                    f"grid invariant: duplicate entry at {coordinate}"
                )
            if cell.row >= self.n_rows:
                raise ValueError(f"cell row {cell.row} is outside the grid")
            if cell.column >= self.n_columns:
                raise ValueError(
                    f"cell column {cell.column} is outside the grid"
                )
            by_coordinate[coordinate] = cell

        self._check_spans(by_coordinate)
        return self

    def _check_spans(
        self, by_coordinate: dict[tuple[int, int], TableCell]
    ) -> None:
        """Check that spans and covered placeholders agree exactly."""
        claimed: dict[tuple[int, int], tuple[int, int]] = {}
        for coordinate, cell in by_coordinate.items():
            if not cell.is_origin:
                continue
            row, column = coordinate
            for offset_row in range(row, row + (cell.row_span or 1)):
                for offset_col in range(
                    column, column + (cell.column_span or 1)
                ):
                    covered = (offset_row, offset_col)
                    if covered == coordinate:
                        continue
                    if covered not in by_coordinate:
                        raise ValueError(
                            f"grid invariant: origin {coordinate} spans "
                            f"{covered}, which is outside the grid"
                        )
                    claimed[covered] = coordinate

        for coordinate, cell in by_coordinate.items():
            if cell.is_origin:
                if coordinate in claimed:
                    raise ValueError(
                        f"grid invariant: origin {coordinate} is also "
                        f"covered by {claimed[coordinate]}"
                    )
                continue
            if cell.origin not in by_coordinate:
                raise ValueError(
                    f"grid invariant: covered cell {coordinate} points at "
                    f"{cell.origin}, which is not a cell"
                )
            if not by_coordinate[cell.origin].is_origin:
                raise ValueError(
                    f"grid invariant: covered cell {coordinate} points at "
                    f"{cell.origin}, which is not an origin"
                )
            if claimed.get(coordinate) != cell.origin:
                raise ValueError(
                    f"grid invariant: covered cell {coordinate} points at "
                    f"{cell.origin}, whose spans do not reach it"
                )


class FinancialFact(pydantic.BaseModel):
    """The payload of a ``financial_fact`` block (03 §4.6)."""

    model_config = _MODEL_CONFIG

    concept: str
    value: int | float | str | None = None
    unit: str | None = None
    period: str | None = None
    context_ref: str | None = None
    dimensions: dict[str, str] = pydantic.Field(default_factory=dict)
    decimals: str | None = None


class KeyValuePair(pydantic.BaseModel):
    """The payload of a ``key_value`` block (03 §5.3).

    Retained for cover-page fields, XBRL context summaries, and
    spreadsheet label/value regions.
    """

    model_config = _MODEL_CONFIG

    key: str
    value: str | None = None


def _escape_cell(text: str) -> str:
    """Escape a cell's text for a single pipe-table field."""
    collapsed = text.replace("\r\n", " ").replace("\n", " ")
    collapsed = collapsed.replace("\r", " ")
    return collapsed.replace("|", r"\|").strip()


def render_table_text(table: TableBlock) -> str:
    """Render a table to its canonical text form (03 §5.4).

    The rendering walks the logical grid in row-major order: an origin
    cell emits its ``raw_text`` at its own coordinate and a covered
    coordinate emits an empty field. Because the grid invariant fixes
    exactly one entry per coordinate, two adapters that see the same
    table produce the same string.

    A caption, when present, precedes the grid, followed by a unit and
    scale line when either is known. A delimiter row is emitted after
    the header rows only when there are header rows.

    Args:
      table: The table payload to render.

    Returns:
      The canonical rendering, with no trailing newline.
    """
    lines: list[str] = []
    if table.caption:
        lines.append(_escape_cell(table.caption))
    unit_parts: list[str] = []
    if table.unit:
        unit_parts.append(f"Unit: {table.unit}")
    if table.scale:
        unit_parts.append(f"Scale: {table.scale}")
    if unit_parts:
        lines.append("; ".join(unit_parts))

    by_coordinate = {(cell.row, cell.column): cell for cell in table.cells}
    for row in range(table.n_rows):
        fields: list[str] = []
        for column in range(table.n_columns):
            cell = by_coordinate[(row, column)]
            raw = cell.raw_text if cell.is_origin else None
            fields.append(_escape_cell(raw) if raw is not None else "")
        lines.append("| " + " | ".join(fields) + " |")
        if table.header_rows and row == table.header_rows - 1:
            lines.append("| " + " | ".join(["---"] * table.n_columns) + " |")
    return "\n".join(lines)


def render_financial_fact_text(fact: FinancialFact) -> str:
    """Render a financial fact to its canonical text form (03 §5.4).

    Args:
      fact: The fact payload to render.

    Returns:
      A deterministic ``concept: value unit (period)`` rendering, with
      the unit and period omitted when unknown.
    """
    value = "null" if fact.value is None else str(fact.value)
    rendered = f"{fact.concept}: {value}"
    if fact.unit:
        rendered = f"{rendered} {fact.unit}"
    if fact.period:
        rendered = f"{rendered} ({fact.period})"
    return rendered


class BlockExtraction(pydantic.BaseModel):
    """Provenance of one block: who produced it and how (03 §5.3)."""

    model_config = _MODEL_CONFIG

    adapter_name: str
    adapter_version: str
    ocr_used: bool = False
    ocr_confidence: float | None = pydantic.Field(default=None, ge=0.0, le=1.0)
    warnings: list[ParseWarning] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _check_ocr_confidence(self) -> "BlockExtraction":
        """Reject an OCR confidence reported without OCR."""
        if self.ocr_confidence is not None and not self.ocr_used:
            raise ValueError("ocr_confidence requires ocr_used to be true")
        return self


class Block(pydantic.BaseModel):
    """One normalized unit of document content (03 §5.3).

    Every block carries a canonical ``text`` rendering produced by the
    parser. For a table or a financial fact that rendering is fixed by
    the payload and checked here, so the chunker can slice and select
    without ever re-rendering structure.
    """

    model_config = _MODEL_CONFIG

    block_id: str
    type: BlockType
    heading_path: list[str] = pydantic.Field(default_factory=list)
    text: str
    payload: TableBlock | FinancialFact | KeyValuePair | None = None
    locator: Locator
    extraction: BlockExtraction

    @pydantic.model_validator(mode="after")
    def _check_payload_and_text(self) -> "Block":
        """Enforce payload/type agreement and canonical text."""
        if self.type in TEXT_ONLY_BLOCK_TYPES:
            if self.payload is not None:
                raise ValueError(
                    f"a {self.type.value} block carries no payload"
                )
            return self
        if self.type is BlockType.TABLE:
            if not isinstance(self.payload, TableBlock):
                raise ValueError("a table block requires a TableBlock payload")
            expected = render_table_text(self.payload)
        elif self.type is BlockType.FINANCIAL_FACT:
            if not isinstance(self.payload, FinancialFact):
                raise ValueError(
                    "a financial_fact block requires a FinancialFact payload"
                )
            expected = render_financial_fact_text(self.payload)
        else:
            if not isinstance(self.payload, KeyValuePair):
                raise ValueError(
                    "a key_value block requires a KeyValuePair payload"
                )
            return self
        if self.text != expected:
            raise ValueError(
                f"a {self.type.value} block's text must be its canonical "
                "rendering (03 §5.4)"
            )
        return self

    @property
    def locator_tier(self) -> quality.LocatorTier:
        """Return the tier this block's locator reaches (03 §5.5)."""
        return self.locator.tier(has_heading_path=bool(self.heading_path))


class RejectedBlock(pydantic.BaseModel):
    """A block refused admission, kept for diagnosis (03 §7.4)."""

    model_config = _MODEL_CONFIG

    block: Block
    reason: quality.BlockRejectionReason
    detail: str | None = None


class ParseMetrics(pydantic.BaseModel):
    """Counts describing one parse outcome (03 §8.3)."""

    model_config = _MODEL_CONFIG

    pages: int | None = pydantic.Field(default=None, ge=0)
    blocks_emitted: int = pydantic.Field(default=0, ge=0)
    blocks_admitted: int = pydantic.Field(default=0, ge=0)
    characters: int = pydantic.Field(default=0, ge=0)
    tables: int = pydantic.Field(default=0, ge=0)
    ocr_pages: int = pydantic.Field(default=0, ge=0)


class ParseQuality(pydantic.BaseModel):
    """The gate's verdict on one document (03 §7).

    The verdict is per document; admission is per block. Rejected blocks
    are persisted with their reason and are never chunked.
    """

    model_config = _MODEL_CONFIG

    verdict: quality.QualityVerdict
    policy_version: str
    warnings: list[ParseWarning] = pydantic.Field(default_factory=list)
    metrics: ParseMetrics = pydantic.Field(default_factory=ParseMetrics)
    rejected_blocks: list[RejectedBlock] = pydantic.Field(default_factory=list)


class DocumentIdentity(pydantic.BaseModel):
    """The four identities a parsed document carries (03 §5.1)."""

    model_config = _MODEL_CONFIG

    document_id: str
    version_id: str
    parse_id: str
    schema_version: str = SCHEMA_VERSION


class SourceInfo(pydantic.BaseModel):
    """Where the artifact came from (03 §5.2).

    ``source_class`` is what the caller asserted; ``source_type`` is
    what parsing concluded. They are distinct fields because a
    disagreement between them is a meaningful signal.
    """

    model_config = _MODEL_CONFIG

    source_type: SourceType
    source_class: SourceClass
    original_url: str | None = None
    canonical_url: str | None = None
    filename: str | None = None
    retrieved_at: datetime.datetime | None = None


class BusinessMetadata(pydantic.BaseModel):
    """Normalized business facts about the document (03 §5.2).

    Normalization never invents missing metadata: an unavailable value
    is explicitly ``None`` (03 §5.6).

    ``cik`` is optional here because most documents are not SEC filings.
    The quality gate is what requires it for a filing (03 §7.3); the
    contract's job is only to guarantee that when it is present it is
    the canonical zero-padded ten-digit form, so that two adapters
    reporting the same filer produce the same string.
    """

    model_config = _MODEL_CONFIG

    company: str | None = None
    ticker: str | None = None
    cik: str | None = None
    document_type: str | None = None
    reporting_period: str | None = None
    published_at: datetime.datetime | None = None

    @pydantic.field_validator("cik", mode="before")
    @classmethod
    def _normalize_cik(cls, value: Any) -> Any:
        """Normalize a CIK to its zero-padded ten-digit form.

        Accepts the forms filings and APIs actually use — ``320193``,
        ``0000320193``, ``CIK0000320193`` — and rejects anything that is
        not a CIK rather than silently storing it.

        Args:
          value: The raw CIK as the adapter extracted it.

        Returns:
          Ten digits with leading zeros, or None when absent.

        Raises:
          ValueError: If the value is not a CIK.
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.upper().startswith("CIK"):
            text = text[3:].lstrip("-: ")
        digits = text.replace("-", "").replace(" ", "")
        if not digits.isdigit():
            raise ValueError(f"cik {value!r} is not a number")
        if len(digits) > _CIK_DIGITS:
            raise ValueError(
                f"cik {value!r} has more than {_CIK_DIGITS} digits"
            )
        return digits.zfill(_CIK_DIGITS)


class ParsedDocument(pydantic.BaseModel):
    """One artifact, normalized (03 §5.2).

    ``blocks`` holds the admitted blocks only. Anything the gate refused
    is in ``parse_quality.rejected_blocks`` with its reason.
    """

    model_config = _MODEL_CONFIG

    identity: DocumentIdentity
    source: SourceInfo
    business_metadata: BusinessMetadata = pydantic.Field(
        default_factory=BusinessMetadata
    )
    blocks: list[Block] = pydantic.Field(default_factory=list)
    parse_quality: ParseQuality

    @pydantic.model_validator(mode="after")
    def _check_unique_block_ids(self) -> "ParsedDocument":
        """Reject a document whose block IDs are not unique."""
        seen = {block.block_id for block in self.blocks}
        if len(seen) != len(self.blocks):
            raise ValueError("block_id values must be unique in a document")
        return self
