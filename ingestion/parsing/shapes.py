"""Data shapes crossing the parser boundary (03 §3.1, §3.6, §8.3).

Three groups live here, and they share a module because they are all
"what goes in and out of an adapter" rather than logic:

* :class:`AcquiredArtifact` — the parser's input contract. The parser
  acquires nothing: source policy, fetching, size limits, and hashing
  all happen in the ingestion service before ``parse`` is called
  (02 §4.5, §9.3).
* :class:`BlockSequence`, :class:`ElementList`, and
  :class:`MarkdownDocument` — the three native result shapes. An
  adapter returns whichever is closest to what its underlying parser
  natively produces, and the shared converters own the rest.
* :class:`RawParseResult`, plus the error and retry vocabulary the
  service reports.

This module imports only the ``contracts`` layer, so every other module
in the package can depend on it without a cycle.
"""

import datetime
import enum

import pydantic

from contracts import document

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


@enum.unique
class ParserErrorCode(enum.StrEnum):
    """Parser-reportable subset of the shared error enum (02 §15).

    The parser adds no private error vocabulary; these are exactly the
    codes 03 §8.2 permits it to return.

    ``ENCRYPTED_DOCUMENT`` is its own code rather than a flavour of
    ``PARSE_FAILED``: an encrypted file is detected before dispatch, does
    not consume the one permitted fallback, and needs a different source
    rather than a different parser (03 §8.1).
    """

    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    ENCRYPTED_DOCUMENT = "ENCRYPTED_DOCUMENT"
    PARSE_FAILED = "PARSE_FAILED"
    PARSE_QUALITY_TOO_LOW = "PARSE_QUALITY_TOO_LOW"
    PARSER_UNAVAILABLE = "PARSER_UNAVAILABLE"
    PARSER_EGRESS_DENIED = "PARSER_EGRESS_DENIED"
    PARSER_BUDGET_EXCEEDED = "PARSER_BUDGET_EXCEEDED"


@enum.unique
class RetryWith(enum.StrEnum):
    """What, if anything, would make a retry meaningful (03 §8.3).

    A bare ``retryable`` boolean is always misleading for a local
    adapter, because re-running the identical call cannot produce a
    different outcome. ``TRANSIENT`` exists only because remote adapters
    are admissible at all.
    """

    NONE = "none"
    LARGER_BUDGET = "larger_budget"
    DIFFERENT_SOURCE = "different_source"
    TRANSIENT = "transient"


@enum.unique
class OcrPolicy(enum.StrEnum):
    """Whether OCR may or must be used for this artifact (03 §3.1)."""

    DISABLED = "disabled"
    ALLOWED = "allowed"
    REQUIRED = "required"


class ParseLimits(pydantic.BaseModel):
    """Bounded-execution budget for one parse (03 §3.1, §8.1)."""

    model_config = _MODEL_CONFIG

    max_bytes: int = pydantic.Field(default=100 * 1024 * 1024, ge=1)
    max_pages: int | None = pydantic.Field(default=None, ge=1)
    wall_clock_seconds: float = pydantic.Field(default=120.0, gt=0.0)


class AcquiredArtifact(pydantic.BaseModel):
    """One already-acquired artifact, ready to parse (03 §3.1).

    The bytes are on local disk and are treated as read-only. Every
    field here was established by the ingestion service; the parser
    re-derives none of them and fetches nothing.
    """

    model_config = _MODEL_CONFIG

    path: str
    content_hash: str
    size_bytes: int = pydantic.Field(ge=0)
    document_id: str
    version_id: str
    source_class: document.SourceClass
    original_url: str | None = None
    canonical_url: str | None = None
    final_url: str | None = None
    filename: str | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = pydantic.Field(default_factory=dict)
    declared_media_type: str | None = None
    retrieved_at: datetime.datetime | None = None
    expected_source_type: document.SourceType | None = None
    limits: ParseLimits = pydantic.Field(default_factory=ParseLimits)
    ocr_policy: OcrPolicy = OcrPolicy.DISABLED


@enum.unique
class ElementKind(enum.StrEnum):
    """Canonical element kinds for the ``ElementList`` shape (03 §3.6).

    An element-based adapter maps its vendor's own kind strings onto
    this closed set. Mapping in the adapter rather than in the converter
    is what keeps the converter shared and deterministic.
    """

    TITLE = "title"
    HEADING = "heading"
    NARRATIVE_TEXT = "narrative_text"
    LIST_ITEM = "list_item"
    TABLE = "table"
    KEY_VALUE = "key_value"
    CODE = "code"
    IMAGE_TEXT = "image_text"


class Element(pydantic.BaseModel):
    """One flat typed element from an element-based adapter (03 §3.6)."""

    model_config = _MODEL_CONFIG

    kind: ElementKind
    text: str = ""
    heading_level: int | None = pydantic.Field(default=None, ge=1, le=9)
    locator: document.Locator = pydantic.Field(default_factory=document.Locator)
    table: document.TableBlock | None = None
    key: str | None = None

    @pydantic.model_validator(mode="after")
    def _check_kind_payload(self) -> "Element":
        """Reject an element whose payload contradicts its kind."""
        if self.kind is ElementKind.TABLE and self.table is None:
            raise ValueError("a table element requires a table grid")
        if self.kind is not ElementKind.TABLE and self.table is not None:
            raise ValueError("only a table element may carry a table grid")
        if self.kind is ElementKind.KEY_VALUE and self.key is None:
            raise ValueError("a key_value element requires a key")
        return self


class ElementList(pydantic.BaseModel):
    """Native shape: a flat list of typed elements (03 §3.6)."""

    model_config = _MODEL_CONFIG

    elements: list[Element] = pydantic.Field(default_factory=list)


class BlockSequence(pydantic.BaseModel):
    """Native shape: normalized blocks, produced directly (03 §3.6).

    Used by adapters with rich structural access. The converter still
    re-normalizes text and mints block IDs, so identity construction
    stays in one place.
    """

    model_config = _MODEL_CONFIG

    blocks: list[document.Block] = pydantic.Field(default_factory=list)


class PageSpan(pydantic.BaseModel):
    """One ``[start, end)`` character range mapped to a page."""

    model_config = _MODEL_CONFIG

    page: int = pydantic.Field(ge=1)
    start: int = pydantic.Field(ge=0)
    end: int = pydantic.Field(ge=0)

    @pydantic.model_validator(mode="after")
    def _check_range(self) -> "PageSpan":
        """Reject a span that ends before it starts."""
        if self.end < self.start:
            raise ValueError("page span end must not precede start")
        return self


class MarkdownDocument(pydantic.BaseModel):
    """Native shape: markdown plus an optional page map (03 §3.6).

    Without a page map the result reaches only tier 3, which every MVP
    route rejects — so a hosted adapter that cannot report pages is
    ineligible for the PDF route, visibly at startup rather than at
    citation time.
    """

    model_config = _MODEL_CONFIG

    markdown: str = ""
    page_map: list[PageSpan] | None = None


#: The three native shapes an adapter may return (03 §3.6).
NativeContent = BlockSequence | ElementList | MarkdownDocument


@enum.unique
class NativeShape(enum.StrEnum):
    """Which native shape an adapter returns (03 §3.6).

    Declared statically in :class:`AdapterCapabilities` rather than
    discovered from the output, because the planned parse manifest must
    name the converter version for the shape *before* parsing, and
    ``parse_id`` is computable up front (03 §5.1).
    """

    BLOCK_SEQUENCE = "block_sequence"
    ELEMENT_LIST = "element_list"
    MARKDOWN_DOCUMENT = "markdown_document"


def shape_of(content: NativeContent) -> NativeShape:
    """Return the native shape of an adapter's output.

    Args:
      content: One of the three native shapes.

    Returns:
      The matching :class:`NativeShape` member.

    Raises:
      TypeError: If the content is not a native shape.
    """
    if isinstance(content, BlockSequence):
        return NativeShape.BLOCK_SEQUENCE
    if isinstance(content, ElementList):
        return NativeShape.ELEMENT_LIST
    if isinstance(content, MarkdownDocument):
        return NativeShape.MARKDOWN_DOCUMENT
    raise TypeError(f"not a native result shape: {type(content).__name__}")


class RawParseResult(pydantic.BaseModel):
    """What an adapter hands back (03 §3.4).

    An adapter answers "what did the parser see". The converters,
    normalizer, and gate answer "what does the corpus get", which is
    what keeps a new vendor integration small.
    """

    model_config = _MODEL_CONFIG

    content: NativeContent
    source_type: document.SourceType
    business_metadata: document.BusinessMetadata = pydantic.Field(
        default_factory=document.BusinessMetadata
    )
    adapter_name: str
    adapter_version: str
    library_versions: dict[str, str] = pydantic.Field(default_factory=dict)
    warnings: list[document.ParseWarning] = pydantic.Field(default_factory=list)
    page_count: int | None = pydantic.Field(default=None, ge=0)
    element_count: int | None = pydantic.Field(default=None, ge=0)
    ocr_used: bool = False
    ocr_confidence: float | None = pydantic.Field(default=None, ge=0.0, le=1.0)
    extraction_seconds: float | None = pydantic.Field(default=None, ge=0.0)
    endpoint_host: str | None = None
    vendor_reported_version: str | None = None
