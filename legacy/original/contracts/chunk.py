"""The chunk contract (04 §2, §10).

:class:`DocumentChunk` is what retrieval filters on and what citations
resolve through, so it lives in the neutral ``contracts`` layer:
``ingestion/`` produces it, ``retrieval/`` consumes it, and neither
imports the other (01 §8). This module imports :mod:`contracts.document`
and :mod:`contracts.quality` and nothing else in the project.

Two rules from 04 are enforced structurally rather than by convention:

* **Citation text is evidence** — it must be non-empty, and by 04 §3.1
  it is always verbatim canonical block text (or a verbatim slice of
  one block, resolved by ``segment``), never re-rendered.
* **Warnings are metadata** — ``warning_codes`` is normalized to a
  sorted, deduplicated list so equal chunks serialize identically.
"""

import datetime
import enum

import pydantic

from contracts import document
from contracts import quality

#: Version of this chunk contract. Bump on any change that alters the
#: shape or meaning of the models below.
CHUNK_SCHEMA_VERSION = "1.0"

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


@enum.unique
class ChunkSegmentKind(enum.StrEnum):
    """How a sub-block slice addresses its source block (04 §2.2)."""

    PARAGRAPH_SPAN = "paragraph_span"
    TABLE_ROWS = "table_rows"


class ChunkSegment(pydantic.BaseModel):
    """The sub-block slice a split chunk cites (04 §2.2).

    A segment appears only when 04 §3.1's two oversize rules split a
    single block. Exactly the fields of its kind are set:

    * ``paragraph_span`` carries ``[text_start, text_end)`` character
      offsets into the source block's canonical text;
    * ``table_rows`` carries ``[row_start, row_end)`` **grid** row
      indices of the cited data rows — indices address the table
      payload's logical grid, so a piece that starts at the first data
      row of a one-header-row table has ``row_start = 1``.
    """

    model_config = _MODEL_CONFIG

    source_block_id: str
    kind: ChunkSegmentKind
    text_start: int | None = pydantic.Field(default=None, ge=0)
    text_end: int | None = pydantic.Field(default=None, ge=0)
    row_start: int | None = pydantic.Field(default=None, ge=0)
    row_end: int | None = pydantic.Field(default=None, ge=0)

    @pydantic.model_validator(mode="after")
    def _check_kind_fields(self) -> "ChunkSegment":
        """Require exactly the fields of the declared kind."""
        if self.kind is ChunkSegmentKind.PARAGRAPH_SPAN:
            set_pair = (self.text_start, self.text_end)
            unset_pair = (self.row_start, self.row_end)
        else:
            set_pair = (self.row_start, self.row_end)
            unset_pair = (self.text_start, self.text_end)
        if set_pair[0] is None or set_pair[1] is None:
            raise ValueError(
                f"a {self.kind.value} segment must set its offset pair"
            )
        if unset_pair != (None, None):
            raise ValueError(
                f"a {self.kind.value} segment sets only its own offsets"
            )
        if set_pair[1] <= set_pair[0]:
            raise ValueError("a segment's end must exceed its start")
        return self


class ChunkBusiness(pydantic.BaseModel):
    """Business metadata copied onto a chunk (04 §2).

    Every value is copied from the parsed document's
    ``business_metadata`` and ``source`` — never invented (03 §5.6).
    ``url`` is the source's ``canonical_url``, else ``original_url``,
    else None.
    """

    model_config = _MODEL_CONFIG

    company: str | None = None
    ticker: str | None = None
    cik: str | None = None
    document_type: str | None = None
    reporting_period: str | None = None
    published_at: datetime.datetime | None = None
    source_type: document.SourceType
    url: str | None = None


class DocumentChunk(pydantic.BaseModel):
    """One retrievable, citable unit of a parsed document (04 §2).

    ``citation_text`` is what users see and is verbatim canonical block
    text; ``embedding_text`` prepends the deterministic context prefix
    (04 §3.3) and is what gets embedded. ``chunk_id`` derives from the
    parse identity and the chunking signature (04 §2.1), so a re-parse
    or a chunking-rule change mints new IDs rather than overwriting old
    ones.
    """

    model_config = _MODEL_CONFIG

    chunk_id: str
    document_id: str
    version_id: str
    parse_id: str
    chunking_signature: str
    ordinal: int = pydantic.Field(ge=0)
    citation_text: str
    embedding_text: str
    block_ids: list[str]
    segment: ChunkSegment | None = None
    section: str | None
    heading_path: list[str]
    locator: document.Locator
    locator_tier: quality.LocatorTier
    warning_codes: list[quality.WarningCode]
    token_count: int = pydantic.Field(ge=0)
    business: ChunkBusiness
    schema_version: str = CHUNK_SCHEMA_VERSION

    @pydantic.field_validator("citation_text")
    @classmethod
    def _check_citation_text(cls, value: str) -> str:
        """Reject citation text that is empty after stripping."""
        if not value.strip():
            raise ValueError("citation_text must be non-empty")
        return value

    @pydantic.field_validator("block_ids")
    @classmethod
    def _check_block_ids(cls, value: list[str]) -> list[str]:
        """Reject an empty or duplicated member-block list."""
        if not value:
            raise ValueError("a chunk must have at least one member block")
        if len(set(value)) != len(value):
            raise ValueError("block_ids must be unique within a chunk")
        return value

    @pydantic.field_validator("warning_codes")
    @classmethod
    def _normalize_warning_codes(
        cls, value: list[quality.WarningCode]
    ) -> list[quality.WarningCode]:
        """Sort and deduplicate warning codes (04 §2)."""
        return sorted(set(value))
