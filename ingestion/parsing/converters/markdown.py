"""``MarkdownDocument`` to normalized blocks (03 §3.6).

LLM-based services — LlamaParse and most hosted parsers — return
markdown. Integrating one becomes "call the service, hand back its
markdown and page map", with no knowledge of ``TableBlock``,
``heading_path``, or ID construction.

The mapping rules are fixed here rather than being per-vendor folklore:

* ATX and setext headings become ``heading`` blocks and build
  ``heading_path`` for everything under them;
* pipe tables become ``TableBlock`` at grid fidelity, and cells are
  typed only when the adapter declared ``typed_grid`` and supplied the
  types — this converter never infers one;
* fenced code becomes ``code``, lists become ``list``, and everything
  else becomes ``paragraph``;
* a page map yields tier-2 page locators. Without one the result reaches
  only tier 3, and a route needing pages rejects the adapter at startup
  through ``page_fidelity`` rather than at citation time.
"""

import re

from contracts import document
from contracts import quality
from ingestion.parsing import shapes
from ingestion.parsing.converters import common

#: Version of this converter. Part of the planned parse manifest.
CONVERTER_VERSION = "markdown/1.0"

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_UNDERLINE = re.compile(r"^(=+|-{2,})\s*$")
_FENCE = re.compile(r"^\s*(```+|~~~+)(.*)$")
_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*$")
_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


class _Line:
    """One source line with the character offset it starts at."""

    def __init__(self, text: str, offset: int) -> None:
        """Initialize the line.

        Args:
          text: The line's text, without its terminator.
          offset: The line's zero-based character offset.
        """
        self.text = text
        self.offset = offset


def _split_lines(markdown: str) -> list[_Line]:
    """Split markdown into lines that remember their offsets."""
    lines: list[_Line] = []
    offset = 0
    for raw in markdown.split("\n"):
        lines.append(_Line(raw, offset))
        offset += len(raw) + 1
    return lines


def _split_row(line: str) -> list[str]:
    """Split one pipe-table row into its unescaped fields."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    fields = _UNESCAPED_PIPE.split(stripped)
    return [field.replace(r"\|", "|").strip() for field in fields]


def _page_for_offset(
    offset: int, page_map: list[shapes.PageSpan] | None
) -> int | None:
    """Return the page containing a character offset, if known."""
    if not page_map:
        return None
    for span in page_map:
        if span.start <= offset < span.end:
            return span.page
    return None


def _locator(
    offset: int,
    element_index: int,
    page_map: list[shapes.PageSpan] | None,
) -> document.Locator:
    """Build a locator for content starting at an offset."""
    return document.Locator(
        page=_page_for_offset(offset, page_map),
        element_index=element_index,
    )


def _build_table(rows: list[list[str]]) -> document.TableBlock:
    """Build a fully addressed grid from pipe-table rows.

    Markdown has no merged cells, so every coordinate is an origin cell
    spanning 1x1 and the grid invariant holds by construction. Short
    rows are padded with blank origin cells — a blank cell that exists
    in the source is ``raw_text = ""``, never a covered placeholder.
    """
    n_columns = max((len(row) for row in rows), default=0)
    cells: list[document.TableCell] = []
    for row_index, row in enumerate(rows):
        for column in range(n_columns):
            raw = row[column] if column < len(row) else ""
            cells.append(
                document.TableCell(
                    row=row_index,
                    column=column,
                    is_origin=True,
                    row_span=1,
                    column_span=1,
                    raw_text=raw,
                    is_header=row_index == 0,
                )
            )
    return document.TableBlock(
        n_rows=len(rows),
        n_columns=n_columns,
        header_rows=1 if rows else 0,
        cells=cells,
    )


class _Parser:
    """Walks markdown lines and emits normalized blocks."""

    def __init__(
        self,
        markdown_document: shapes.MarkdownDocument,
        context: common.ConversionContext,
    ) -> None:
        """Initialize the parser.

        Args:
          markdown_document: The markdown and optional page map.
          context: The conversion context.
        """
        self._lines = _split_lines(markdown_document.markdown)
        self._page_map = markdown_document.page_map
        self._context = context
        self._headings = common.HeadingStack()
        self._blocks: list[document.Block] = []
        self._index = 0

    def run(self) -> list[document.Block]:
        """Parse the whole document.

        Returns:
          Normalized blocks in document order.
        """
        while self._index < len(self._lines):
            line = self._lines[self._index]
            if not line.text.strip():
                self._index += 1
                continue
            if self._take_fenced_code(line):
                continue
            if self._take_atx_heading(line):
                continue
            if self._take_setext_heading(line):
                continue
            if self._take_table(line):
                continue
            if self._take_list(line):
                continue
            self._take_paragraph(line)
        return self._blocks

    def _emit(
        self,
        block_type: document.BlockType,
        text: str,
        offset: int,
        payload: document.TableBlock | None = None,
    ) -> None:
        """Append one block built from the shared normalizer."""
        self._blocks.append(
            common.build_block(
                context=self._context,
                ordinal=len(self._blocks),
                block_type=block_type,
                text=text,
                locator=_locator(offset, len(self._blocks), self._page_map),
                heading_path=self._headings.path(),
                payload=payload,
            )
        )

    def _take_fenced_code(self, line: _Line) -> bool:
        """Consume a fenced code block, if one starts here."""
        match = _FENCE.match(line.text)
        if not match:
            return False
        fence = match.group(1)
        body: list[str] = []
        self._index += 1
        while self._index < len(self._lines):
            current = self._lines[self._index].text
            if current.strip().startswith(fence):
                self._index += 1
                break
            body.append(current)
            self._index += 1
        self._emit(document.BlockType.CODE, "\n".join(body), line.offset)
        return True

    def _take_atx_heading(self, line: _Line) -> bool:
        """Consume an ATX heading, if one starts here."""
        match = _ATX_HEADING.match(line.text)
        if not match:
            return False
        text = common.normalize_text(match.group(2))
        self._emit(document.BlockType.HEADING, text, line.offset)
        self._headings.push(len(match.group(1)), text)
        self._index += 1
        return True

    def _take_setext_heading(self, line: _Line) -> bool:
        """Consume a setext heading, if one starts here."""
        if self._index + 1 >= len(self._lines):
            return False
        underline = self._lines[self._index + 1].text
        if not _SETEXT_UNDERLINE.match(underline):
            return False
        if _LIST_ITEM.match(line.text) or _TABLE_ROW.match(line.text):
            return False
        level = 1 if underline.strip().startswith("=") else 2
        text = common.normalize_text(line.text)
        self._emit(document.BlockType.HEADING, text, line.offset)
        self._headings.push(level, text)
        self._index += 2
        return True

    def _take_table(self, line: _Line) -> bool:
        """Consume a pipe table, if one starts here."""
        if not _TABLE_ROW.match(line.text):
            return False
        if self._index + 1 >= len(self._lines):
            return False
        if not _TABLE_DELIMITER.match(self._lines[self._index + 1].text):
            return False
        rows = [_split_row(line.text)]
        self._index += 2
        while self._index < len(self._lines):
            current = self._lines[self._index].text
            if not _TABLE_ROW.match(current):
                break
            rows.append(_split_row(current))
            self._index += 1
        self._emit(
            document.BlockType.TABLE,
            "",
            line.offset,
            payload=_build_table(rows),
        )
        return True

    def _take_list(self, line: _Line) -> bool:
        """Consume a run of list items, if one starts here."""
        match = _LIST_ITEM.match(line.text)
        if not match:
            return False
        items = [match.group(2)]
        self._index += 1
        while self._index < len(self._lines):
            current = _LIST_ITEM.match(self._lines[self._index].text)
            if not current:
                break
            items.append(current.group(2))
            self._index += 1
        self._emit(document.BlockType.LIST, "\n".join(items), line.offset)
        return True

    def _take_paragraph(self, line: _Line) -> None:
        """Consume a paragraph up to the next structural boundary."""
        body = [line.text]
        self._index += 1
        while self._index < len(self._lines):
            current = self._lines[self._index]
            if not current.text.strip():
                break
            if (
                _ATX_HEADING.match(current.text)
                or _FENCE.match(current.text)
                or _LIST_ITEM.match(current.text)
                or _TABLE_ROW.match(current.text)
                or _SETEXT_UNDERLINE.match(current.text)
            ):
                break
            body.append(current.text)
            self._index += 1
        self._emit(document.BlockType.PARAGRAPH, "\n".join(body), line.offset)


def convert(
    markdown_document: shapes.MarkdownDocument,
    context: common.ConversionContext,
) -> list[document.Block]:
    """Convert a markdown document into normalized blocks.

    Args:
      markdown_document: The markdown and optional page map the adapter
        returned.
      context: The conversion context. A missing page map is recorded on
        the context's warning sink, because it caps every block at
        tier 3 and that is a document-level fact.

    Returns:
      Normalized blocks in document order.
    """
    if markdown_document.page_map is None:
        context.warnings.append(
            document.ParseWarning(
                code=quality.WarningCode.PAGE_MAP_MISSING,
                message=(
                    "no page map supplied; page locators are unavailable "
                    "and blocks reach tier 3 unless a heading path applies"
                ),
            )
        )
    return _Parser(markdown_document, context).run()
