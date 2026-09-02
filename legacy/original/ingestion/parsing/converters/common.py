"""Normalization shared by every shape converter (03 §5.4, §5.6).

Block identity, text normalization, canonical rendering, and table
typing policy are written once here so that two adapters seeing the
same content produce the same blocks. That is the property that makes
switching vendors a comparable diff rather than a change in corpus
shape.

Normalization performs deterministic mappings only. It does not
summarize, translate, interpret financial meaning, or invent missing
metadata (03 §5.6).
"""

import hashlib
import unicodedata

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module

#: Version of the normalization rules in this module. Part of the
#: planned parse manifest, so changing a rule changes ``parse_id``.
NORMALIZER_VERSION = "1.0"

#: Whitespace characters normalized to a plain space, plus the
#: byte-order mark, which is removed. Deliberately short: collapsing
#: anything else risks destroying financial notation.
_SPACE_LIKE = {
    "\xa0": " ",  # no-break space
    "\u2007": " ",  # figure space
    "\u2009": " ",  # thin space
    "\u202f": " ",  # narrow no-break space
    "\ufeff": "",  # byte-order mark
}


def normalize_text(text: str) -> str:
    """Normalize block text without altering its meaning.

    Applies Unicode NFC composition, converts line endings to ``\\n``,
    maps non-breaking and thin spaces to a plain space, collapses runs
    of spaces and tabs, and strips trailing whitespace from each line.
    Parentheses, currency symbols, signs, and dashes are untouched:
    those carry financial meaning.

    Args:
      text: Raw text as the adapter produced it.

    Returns:
      The normalized text.
    """
    normalized = unicodedata.normalize("NFC", text)
    for source, target in _SPACE_LIKE.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in normalized.split("\n"):
        collapsed = " ".join(line.split())
        lines.append(collapsed)
    return "\n".join(lines).strip("\n")


def make_block_id(
    parse_id: str, ordinal: int, locator: document.Locator
) -> str:
    """Build a stable block ID (03 §5.6).

    The ID is a pure function of the parse identity, the block's
    position, and its locator, so re-running the same pipeline over the
    same bytes reproduces it exactly.

    Args:
      parse_id: The parse identity, computable before parsing (03 §5.1).
      ordinal: The block's zero-based position in the document.
      locator: The block's locator.

    Returns:
      A ``blk_``-prefixed stable identifier.
    """
    payload = "|".join(
        [
            parse_id,
            str(ordinal),
            locator.model_dump_json(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"blk_{digest[:16]}"


def enforce_table_typing(
    table: document.TableBlock,
    table_fidelity: capabilities_module.TableFidelity,
) -> tuple[document.TableBlock, list[document.ParseWarning]]:
    """Strip cell typing an adapter did not declare (03 §3.6).

    Cells are typed only when the adapter declared ``typed_grid`` and
    supplied the types. The converter never infers a type: inferring one
    would make two adapters over the same table disagree, and would put
    financial interpretation in shared code.

    Args:
      table: The table as the adapter produced it.
      table_fidelity: The fidelity the adapter declared.

    Returns:
      The table with typing removed when undeclared, and any warning
      that removal produced.
    """
    if table_fidelity >= capabilities_module.TableFidelity.TYPED_GRID:
        return table, []
    typed = [
        cell
        for cell in table.cells
        if cell.value is not None or cell.value_type is not None
    ]
    if not typed:
        return table, []
    stripped = [
        (
            cell.model_copy(update={"value": None, "value_type": None})
            if cell.is_origin
            else cell
        )
        for cell in table.cells
    ]
    warning = document.ParseWarning(
        code=quality.WarningCode.TABLE_TYPING_UNAVAILABLE,
        message=(
            f"discarded typing on {len(typed)} cells: the adapter declared "
            f"table_fidelity={table_fidelity.name}, not TYPED_GRID"
        ),
    )
    return table.model_copy(update={"cells": stripped}), [warning]


class ConversionContext:
    """Everything a converter needs beyond the adapter's own output.

    Carries a mutable warning sink, because conversion legitimately
    produces warnings — discarded cell typing, a missing page map — that
    belong to the document rather than to one block.
    """

    def __init__(
        self,
        parse_id: str,
        adapter_name: str,
        adapter_version: str,
        adapter_capabilities: capabilities_module.AdapterCapabilities,
        ocr_used: bool = False,
        ocr_confidence: float | None = None,
    ) -> None:
        """Initialize the context.

        Args:
          parse_id: The parse identity, known before parsing.
          adapter_name: Name of the adapter that produced the output.
          adapter_version: Version of that adapter.
          adapter_capabilities: What that adapter declared.
          ocr_used: Whether the adapter used OCR.
          ocr_confidence: OCR confidence when OCR was used.
        """
        self.parse_id = parse_id
        self.adapter_name = adapter_name
        self.adapter_version = adapter_version
        self.capabilities = adapter_capabilities
        self.ocr_used = ocr_used
        self.ocr_confidence = ocr_confidence
        self.warnings: list[document.ParseWarning] = []

    def extraction(
        self, block_warnings: list[document.ParseWarning] | None = None
    ) -> document.BlockExtraction:
        """Build the provenance record carried by one block.

        Args:
          block_warnings: Warnings specific to this block.

        Returns:
          The block's extraction provenance.
        """
        warnings = list(block_warnings or [])
        if (
            self.capabilities.extraction_class
            is capabilities_module.ExtractionClass.GENERATIVE
        ):
            warnings.append(
                document.ParseWarning(
                    code=quality.WarningCode.GENERATIVE_EXTRACTION,
                    message=(
                        "produced by a generative adapter; content must be "
                        "grounded before it can become verified evidence"
                    ),
                )
            )
        return document.BlockExtraction(
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            ocr_used=self.ocr_used,
            ocr_confidence=self.ocr_confidence if self.ocr_used else None,
            warnings=warnings,
        )


def build_block(
    context: ConversionContext,
    ordinal: int,
    block_type: document.BlockType,
    text: str,
    locator: document.Locator,
    heading_path: list[str] | None = None,
    payload: (
        document.TableBlock
        | document.FinancialFact
        | document.KeyValuePair
        | None
    ) = None,
    block_warnings: list[document.ParseWarning] | None = None,
) -> document.Block:
    """Assemble one contract block from converter output.

    The canonical ``text`` of a table or financial fact is rendered
    here, never taken from the adapter, so the rendering is identical
    whichever shape the adapter returned (03 §5.4).

    Args:
      context: The conversion context.
      ordinal: The block's zero-based position in the document.
      block_type: The normalized block type.
      text: Text for text-bearing types; ignored for table and
        financial-fact blocks, whose text is rendered from the payload.
      locator: The block's locator.
      heading_path: Enclosing headings, outermost first.
      payload: The type-specific payload, if any.
      block_warnings: Warnings specific to this block.

    Returns:
      A validated :class:`contracts.document.Block`.

    Raises:
      ValueError: If the payload does not match the block type.
    """
    warnings = list(block_warnings or [])
    if block_type is document.BlockType.TABLE:
        if not isinstance(payload, document.TableBlock):
            raise ValueError("a table block requires a TableBlock payload")
        payload, typing_warnings = enforce_table_typing(
            payload, context.capabilities.table_fidelity
        )
        warnings.extend(typing_warnings)
        rendered = document.render_table_text(payload)
    elif block_type is document.BlockType.FINANCIAL_FACT:
        if not isinstance(payload, document.FinancialFact):
            raise ValueError(
                "a financial_fact block requires a FinancialFact payload"
            )
        rendered = document.render_financial_fact_text(payload)
    else:
        rendered = normalize_text(text)

    return document.Block(
        block_id=make_block_id(context.parse_id, ordinal, locator),
        type=block_type,
        heading_path=list(heading_path or []),
        text=rendered,
        payload=payload,
        locator=locator,
        extraction=context.extraction(warnings),
    )


class HeadingStack:
    """Builds ``heading_path`` from a stream of levelled headings.

    Formats with no heading structure — CSV, JSON, spreadsheets — simply
    never push, so every block gets an empty path, which is what the
    contract specifies (03 §5.3).
    """

    def __init__(self) -> None:
        """Initialize an empty stack."""
        self._entries: list[tuple[int, str]] = []

    def push(self, level: int, text: str) -> None:
        """Record a heading at the given level.

        Args:
          level: The heading level, 1 being outermost.
          text: The heading's normalized text.
        """
        while self._entries and self._entries[-1][0] >= level:
            self._entries.pop()
        self._entries.append((level, text))

    def path(self) -> list[str]:
        """Return the enclosing headings, outermost first."""
        return [text for _, text in self._entries]
