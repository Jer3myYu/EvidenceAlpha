"""SEC HTML adapter over lxml (03 §4.1, §14 step 5).

The in-house adapter foreseen by 03 §14 step 4's fallback clause, now
primary: the EdgarTools spike (2026-08-15) proved its offline HTML path
extracts Items, tables, and inline XBRL facts, but its document model
retains no source-DOM position, so no block it produces can carry the
tier-1 anchor the SEC route minimum requires (03 §3.5, §5.5). This
adapter walks the source DOM directly, so **every block carries the
``xpath`` of the element it came from** — an anchor any reader of the
source file can resolve.

What it extracts:

* narrative blocks — leaf ``div``/``p`` text in document order, with
  SEC Part/Item headings recognized by form-aware rules and carried
  into ``heading_path``;
* tables — full logical grids with rowspan/colspan resolved into the
  origin/covered model of 03 §5.3;
* inline XBRL — every ``ix:nonFraction`` fact as a ``financial_fact``
  block with the ixt numeric transform applied mechanically, and the
  ``dei:`` cover facts as business metadata. ``ix:nonNumeric`` facts
  are not emitted as blocks: their values are narrative that the
  paragraph walk already captures.

Hidden inline-XBRL machinery (``ix:hidden``, ``display:none``) is
excluded from the narrative walk but remains visible to fact and
metadata extraction, which is where those values actually live.
"""

import decimal
import re

import lxml.etree
import lxml.html

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector
from ingestion.parsing import shapes
from ingestion.parsing.adapters import base

#: Formats this adapter serves (03 §3.3).
_SEC_FORMATS = frozenset(
    {
        detector.DetectedFormat.SEC_INLINE_XBRL_HTML,
        detector.DetectedFormat.SEC_HTML,
    }
)

#: Tags whose subtrees carry no narrative content.
_SKIP_TAGS = frozenset({"script", "style", "ix:hidden", "ix:header"})

#: Block-level tags. An element with none of these below it is a leaf
#: block; an element that has them is a container to descend into.
_BLOCK_TAGS = frozenset(
    {"p", "div", "table", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
)

#: Explicit heading tags and their levels.
_HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}

#: Form-aware section rules (03 §14 step 4). SEC filings rarely use
#: ``h`` tags, so Part and Item headings are recognized from the text
#: of short leaf blocks.
_PART_PATTERN = re.compile(r"^part\s+[ivxlc]+\b", re.IGNORECASE)
_ITEM_PATTERN = re.compile(r"^item\s+\d+[a-z]?\s*[.:—-]?", re.IGNORECASE)

#: A heading is a short line, not a paragraph that happens to open with
#: a cross-reference to an Item.
_MAX_HEADING_CHARS = 120

#: Inline XBRL numeric transforms this adapter applies. Each is a
#: mechanical rule from the ixt registry, not an interpretation.
_NUMERIC_FORMATS = frozenset(
    {
        "ixt:num-dot-decimal",
        "ixt:numdotdecimal",
        "ixt-sec:numdotdecimal",
    }
)
_ZERO_FORMATS = frozenset(
    {"ixt:fixed-zero", "ixt:fixedzero", "ixt-sec:fixed-zero"}
)
_WORD_FORMATS = frozenset({"ixt-sec:numwordsen", "ixt:numwordsen"})

#: Vocabulary of the ``numwordsen`` transform (verifier F1).
_WORD_UNITS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_MAGNITUDES: dict[str, int] = {
    "thousand": 10**3,
    "million": 10**6,
    "billion": 10**9,
    "trillion": 10**12,
}

#: ``dei:`` concepts that populate business metadata (03 §5.2).
_DEI_COMPANY = "dei:entityregistrantname"
_DEI_CIK = "dei:entitycentralindexkey"
_DEI_FORM = "dei:documenttype"
_DEI_PERIOD = "dei:documentperiodenddate"
_DEI_TICKER = "dei:tradingsymbol"

_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)

#: Caps that keep a hostile table from expanding the grid unboundedly.
_MAX_SPAN = 1_000
_MAX_GRID_CELLS = 1_000_000


def _clean(text: str) -> str:
    """Collapse whitespace in extracted text."""
    return " ".join(text.split())


def _is_hidden(element: lxml.etree._Element) -> bool:
    """Return whether an element is invisible in the rendered filing."""
    if not isinstance(element.tag, str):
        return True
    if element.tag in _SKIP_TAGS:
        return True
    style = element.get("style")
    return bool(style and _DISPLAY_NONE.search(style))


def _has_block_descendant(element: lxml.etree._Element) -> bool:
    """Return whether any block-level tag sits below an element."""
    for child in element.iterdescendants():
        if isinstance(child.tag, str) and child.tag in _BLOCK_TAGS:
            return True
    return False


class _FactIndex:
    """Inline XBRL contexts, units, and facts, indexed once per parse."""

    def __init__(self, root: lxml.etree._Element) -> None:
        """Index the document's inline XBRL structures.

        Args:
          root: The parsed document root.
        """
        self.periods: dict[str, str] = {}
        self.dimensions: dict[str, dict[str, str]] = {}
        self.units: dict[str, str] = {}
        self.dei: dict[str, str] = {}
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            if element.tag == "xbrli:context":
                self._index_context(element)
            elif element.tag == "xbrli:unit":
                self._index_unit(element)
            elif element.tag == "ix:nonnumeric":
                name = (element.get("name") or "").lower()
                if name.startswith("dei:") and name not in self.dei:
                    self.dei[name] = _clean(element.text_content())

    def _index_context(self, element: lxml.etree._Element) -> None:
        """Record one context's period and explicit dimensions."""
        context_id = element.get("id")
        if not context_id:
            return
        instant = start = end = None
        dimensions: dict[str, str] = {}
        for child in element.iterdescendants():
            if not isinstance(child.tag, str):
                continue
            if child.tag == "xbrli:instant":
                instant = _clean(child.text_content())
            elif child.tag == "xbrli:startdate":
                start = _clean(child.text_content())
            elif child.tag == "xbrli:enddate":
                end = _clean(child.text_content())
            elif child.tag == "xbrldi:explicitmember":
                dimension = child.get("dimension")
                if dimension:
                    dimensions[dimension] = _clean(child.text_content())
        if instant:
            self.periods[context_id] = instant
        elif start and end:
            self.periods[context_id] = f"{start}/{end}"
        if dimensions:
            self.dimensions[context_id] = dimensions

    def _index_unit(self, element: lxml.etree._Element) -> None:
        """Record one unit as a readable measure string."""
        unit_id = element.get("id")
        if not unit_id:
            return
        measures = [
            _clean(child.text_content()).rsplit(":", 1)[-1]
            for child in element.iterdescendants()
            if isinstance(child.tag, str) and child.tag == "xbrli:measure"
        ]
        if measures:
            self.units[unit_id] = "/".join(measures)


def _words_to_number(text: str) -> decimal.Decimal | None:
    """Decode an ``ixt-sec:numwordsen`` value (verifier F1, 2026-08-15).

    ``numwordsen`` is a mechanical transform from the SEC's ixt
    registry, so decoding it is normalization, not interpretation. The
    accumulator handles the vocabulary the registry defines — units,
    tens, and magnitude words, joined by spaces, hyphens, or ``and`` —
    and returns None for anything outside it, which keeps the raw text.

    Args:
      text: The cleaned word-form value, e.g. ``twenty-five million``.

    Returns:
      The decoded number, or None when a token is not a number word.
    """
    tokens = [
        token
        for token in re.split(r"[\s-]+", text.lower())
        if token and token != "and"
    ]
    if not tokens:
        return None
    if tokens in (["no"], ["none"]):
        return decimal.Decimal(0)
    total = decimal.Decimal(0)
    current = decimal.Decimal(0)
    for token in tokens:
        if token in _WORD_UNITS:
            current += _WORD_UNITS[token]
        elif token == "hundred":
            current = (current or decimal.Decimal(1)) * 100
        elif token in _WORD_MAGNITUDES:
            total += (current or decimal.Decimal(1)) * _WORD_MAGNITUDES[token]
            current = decimal.Decimal(0)
        else:
            return None
    return total + current


def _numeric_value(
    text: str, element: lxml.etree._Element
) -> int | float | str | None:
    """Apply the declared ixt transform to a fact's text.

    Only mechanical transforms from the ixt registry are applied —
    comma removal, word-form decoding, scale, and sign — and the
    arithmetic runs in :class:`decimal.Decimal`, because binary floats
    turn ``16.6 x 10^6`` into ``16600000.000000002`` in what 03 §5.4
    hands to the user as citation text (verifier F2, 2026-08-15).
    Anything else keeps the raw text: normalization never interprets
    (03 §5.6).

    Args:
      text: The fact element's cleaned text.
      element: The ``ix:nonFraction`` element, for its attributes.

    Returns:
      The transformed number, the raw text, or None for an empty fact.
    """
    fact_format = (element.get("format") or "").lower()
    if fact_format in _ZERO_FORMATS:
        return 0
    if not text:
        return None
    if fact_format in _WORD_FORMATS:
        number = _words_to_number(text)
        if number is None:
            return text
    elif fact_format in _NUMERIC_FORMATS:
        try:
            number = decimal.Decimal(text.replace(",", "").replace(" ", ""))
        except decimal.InvalidOperation:
            return text
    else:
        return text
    scale = element.get("scale")
    if scale is not None:
        try:
            number = number.scaleb(int(scale))
        except (ValueError, decimal.InvalidOperation):
            return text
    if element.get("sign") == "-":
        number = -number
    if number == number.to_integral_value():
        return int(number)
    return float(number)


class SecHtmlLxmlAdapter:
    """SEC HTML and inline XBRL over lxml (03 §4.1)."""

    name = "sec_html_lxml"
    version = "1.1"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset(
            {
                document.BlockType.HEADING,
                document.BlockType.PARAGRAPH,
                document.BlockType.LIST,
                document.BlockType.TABLE,
                document.BlockType.FINANCIAL_FACT,
            }
        ),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=frozenset({quality.LocatorTier.ANCHORED}),
        page_fidelity=False,
        extraction_class=capabilities_module.ExtractionClass.RULE_BASED,
        determinism=capabilities_module.Determinism.PINNED,
        egress=capabilities_module.Egress.NONE,
    )

    def supports(self, request: base.ParseRequest) -> bool:
        """Accept the SEC HTML family only.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          Whether this adapter serves the detected format.
        """
        return request.detection.format in _SEC_FORMATS

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Parse one SEC filing into normalized blocks.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          A ``BlockSequence`` raw result with SEC business metadata.

        Raises:
          base.AdapterError: If the HTML cannot be parsed at all.
        """
        try:
            tree = lxml.html.parse(request.artifact.path)
        except (OSError, lxml.etree.ParserError) as error:
            raise base.AdapterError(f"cannot parse HTML: {error}") from error
        root = tree.getroot()
        if root is None:
            raise base.AdapterError("the document has no root element")
        body = root.body if root.body is not None else root

        facts = _FactIndex(root)
        builder = _BlockBuilder(tree, facts, self.name, self.version)
        builder.walk(body)
        builder.emit_facts(root)

        return shapes.RawParseResult(
            content=shapes.BlockSequence(blocks=builder.blocks),
            source_type=document.SourceType.SEC_FILING,
            business_metadata=document.BusinessMetadata(
                company=facts.dei.get(_DEI_COMPANY) or None,
                ticker=facts.dei.get(_DEI_TICKER) or None,
                cik=facts.dei.get(_DEI_CIK) or None,
                document_type=facts.dei.get(_DEI_FORM) or None,
                reporting_period=facts.dei.get(_DEI_PERIOD) or None,
            ),
            adapter_name=self.name,
            adapter_version=self.version,
            library_versions={
                "lxml": lxml.etree.__version__,
            },
            warnings=builder.warnings,
            element_count=len(builder.blocks),
        )


class _BlockBuilder:
    """Accumulates blocks from one walk of the source DOM."""

    def __init__(
        self,
        tree: lxml.etree._ElementTree,
        facts: _FactIndex,
        adapter_name: str,
        adapter_version: str,
    ) -> None:
        """Initialize the builder.

        Args:
          tree: The parsed document tree, for ``getpath`` anchors.
          facts: The document's inline XBRL index.
          adapter_name: Name recorded in each block's provenance.
          adapter_version: Version recorded alongside it.
        """
        self.blocks: list[document.Block] = []
        self.warnings: list[document.ParseWarning] = []
        self._tree = tree
        self._facts = facts
        self._extraction = document.BlockExtraction(
            adapter_name=adapter_name, adapter_version=adapter_version
        )
        self._headings: list[tuple[int, str]] = []
        #: Document order of every element, so facts emitted in a
        #: separate pass can be attributed to the section that encloses
        #: them (verifier F4, 2026-08-15).
        self._order: dict[lxml.etree._Element, int] = {
            child: index for index, child in enumerate(tree.getroot().iter())
        }
        #: ``(document order of heading element, heading_path there)``,
        #: appended as the walk records headings — ascending by order.
        self._heading_marks: list[tuple[int, list[str]]] = []

    def _locator(self, element: lxml.etree._Element) -> document.Locator:
        """Build the tier-1 locator for one source element."""
        return document.Locator(
            xpath=self._tree.getpath(element),
            html_anchor=element.get("id"),
        )

    def _path(self) -> list[str]:
        """Return the enclosing headings, outermost first."""
        return [text for _, text in self._headings]

    def _push_heading(
        self, level: int, text: str, element: lxml.etree._Element
    ) -> list[str]:
        """Record a heading, popping deeper or equal levels.

        Returns:
          The heading's *enclosing* path — the stack after popping
          peers, before the heading itself. 03 §5.3 defines
          ``heading_path`` as enclosing headings, so a heading block
          carries this exclusive path (adapter 1.1; the 1.0 behavior
          was self-inclusive and disagreed with the shared markdown
          converter).
        """
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        enclosing = self._path()
        self._headings.append((level, text))
        order = self._order.get(element)
        if order is not None:
            self._heading_marks.append((order, self._path()))
        return enclosing

    def _path_at(self, element: lxml.etree._Element) -> list[str]:
        """Return the heading path enclosing an element's position.

        The last heading recorded at or before the element in document
        order — how a fact emitted in the second pass learns which Item
        it sits in (verifier F4).
        """
        order = self._order.get(element)
        if order is None:
            return []
        path: list[str] = []
        for mark_order, mark_path in self._heading_marks:
            if mark_order > order:
                break
            path = mark_path
        return path

    def _append(
        self,
        block_type: document.BlockType,
        text: str,
        element: lxml.etree._Element,
        payload: document.TableBlock | document.FinancialFact | None = None,
        heading_path: list[str] | None = None,
    ) -> None:
        """Append one block anchored at one source element."""
        self.blocks.append(
            document.Block(
                block_id=f"sec-{len(self.blocks)}",
                type=block_type,
                heading_path=(
                    self._path() if heading_path is None else heading_path
                ),
                text=text,
                payload=payload,
                locator=self._locator(element),
                extraction=self._extraction,
            )
        )

    def walk(self, element: lxml.etree._Element) -> None:
        """Emit blocks for one element and its subtree, in order."""
        if _is_hidden(element):
            return
        tag = element.tag
        if tag == "table":
            self._emit_table(element)
            return
        if tag in ("ul", "ol"):
            self._emit_list(element)
            return
        if tag in _HEADING_LEVELS:
            text = _clean(element.text_content())
            if text:
                enclosing = self._push_heading(
                    _HEADING_LEVELS[tag], text, element
                )
                self._append(
                    document.BlockType.HEADING,
                    text,
                    element,
                    heading_path=enclosing,
                )
            return
        if not _has_block_descendant(element):
            self._emit_leaf(element)
            return
        for child in element:
            if isinstance(child.tag, str):
                self.walk(child)

    def _emit_leaf(self, element: lxml.etree._Element) -> None:
        """Emit one leaf block, recognizing Part/Item headings."""
        text = _clean(element.text_content())
        if not text:
            return
        level = self._heading_level(text)
        if level is not None:
            enclosing = self._push_heading(level, text, element)
            self._append(
                document.BlockType.HEADING,
                text,
                element,
                heading_path=enclosing,
            )
            return
        self._append(document.BlockType.PARAGRAPH, text, element)

    @staticmethod
    def _heading_level(text: str) -> int | None:
        """Return the section level of a Part or Item heading, if any."""
        if len(text) > _MAX_HEADING_CHARS:
            return None
        if _PART_PATTERN.match(text):
            return 1
        if _ITEM_PATTERN.match(text):
            return 2
        return None

    def _emit_list(self, element: lxml.etree._Element) -> None:
        """Emit one ``ul``/``ol`` as a single list block."""
        items = [
            _clean(item.text_content())
            for item in element.iterdescendants()
            if isinstance(item.tag, str) and item.tag == "li"
        ]
        items = [item for item in items if item]
        if not items:
            return
        self._append(
            document.BlockType.LIST,
            "\n".join(f"- {item}" for item in items),
            element,
        )

    def _emit_table(self, element: lxml.etree._Element) -> None:
        """Emit one table as a full logical grid (03 §5.3).

        A table whose spans cannot form a legal grid — overlapping
        claims from malformed HTML — is preserved as a paragraph with
        ``TABLE_STRUCTURE_LOST``, never dropped silently and never
        allowed to crash the parse.

        Filing generators wrap each Part and Item heading in a small
        layout table, so a table whose entire text is a section heading
        is emitted as the heading it is, not as a one-cell grid.
        """
        text = _clean(element.text_content())
        level = self._heading_level(text)
        if level is not None:
            enclosing = self._push_heading(level, text, element)
            self._append(
                document.BlockType.HEADING,
                text,
                element,
                heading_path=enclosing,
            )
            return
        try:
            table = _build_grid(element)
        except ValueError:
            table = None
        if table is not None:
            self._append(
                document.BlockType.TABLE,
                document.render_table_text(table),
                element,
                payload=table,
            )
            return
        if not text:
            return
        self.warnings.append(
            document.ParseWarning(
                code=quality.WarningCode.TABLE_STRUCTURE_LOST,
                message=(
                    "one table's structure could not be preserved and was "
                    "kept as plain text"
                ),
                locator=self._locator(element),
            )
        )
        self._append(document.BlockType.PARAGRAPH, text, element)

    def emit_facts(self, root: lxml.etree._Element) -> None:
        """Emit every ``ix:nonFraction`` fact as a block (03 §14).

        Facts come last, in document order, each anchored at the exact
        inline element that carries the value — including facts inside
        ``ix:hidden``, which are real values a reader can verify in the
        source even though the browser does not render them.

        Args:
          root: The parsed document root.
        """
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            if element.tag != "ix:nonfraction":
                continue
            concept = element.get("name")
            if not concept:
                continue
            context_ref = element.get("contextref")
            unit_ref = element.get("unitref")
            fact = document.FinancialFact(
                concept=concept,
                value=_numeric_value(_clean(element.text_content()), element),
                unit=(self._facts.units.get(unit_ref) if unit_ref else None),
                period=(
                    self._facts.periods.get(context_ref)
                    if context_ref
                    else None
                ),
                context_ref=context_ref,
                dimensions=(
                    self._facts.dimensions.get(context_ref, {})
                    if context_ref
                    else {}
                ),
                decimals=element.get("decimals"),
            )
            self._append(
                document.BlockType.FINANCIAL_FACT,
                document.render_financial_fact_text(fact),
                element,
                payload=fact,
                heading_path=self._path_at(element),
            )


def _table_rows(element: lxml.etree._Element) -> list[lxml.etree._Element]:
    """Return a table's own rows, ignoring nested tables."""
    rows = []
    for row in element.iterdescendants():
        if not isinstance(row.tag, str) or row.tag != "tr":
            continue
        ancestor = row.getparent()
        owner = None
        while ancestor is not None:
            if isinstance(ancestor.tag, str) and ancestor.tag == "table":
                owner = ancestor
                break
            ancestor = ancestor.getparent()
        if owner is element:
            rows.append(row)
    return rows


def _row_cells(row: lxml.etree._Element) -> list[lxml.etree._Element]:
    """Return a row's direct cells."""
    return [
        cell
        for cell in row
        if isinstance(cell.tag, str) and cell.tag in ("td", "th")
    ]


def _span(cell: lxml.etree._Element, attribute: str) -> int:
    """Return a clamped, defaulted span attribute."""
    raw = cell.get(attribute)
    try:
        value = int(raw) if raw is not None else 1
    except ValueError:
        value = 1
    return max(1, min(value, _MAX_SPAN))


def _build_grid(element: lxml.etree._Element) -> document.TableBlock | None:
    """Build the fully addressed logical grid for one HTML table.

    Follows the HTML table model: each cell lands at the first free
    column of its row, and rowspan/colspan claim the covered
    coordinates. Ragged rows are padded with empty origin cells so the
    grid stays fully addressed (03 §5.3).

    Args:
      element: The ``table`` element.

    Returns:
      The grid, or None for a table with no rows or no content.
    """
    rows = _table_rows(element)
    if not rows:
        return None

    occupied: dict[tuple[int, int], document.TableCell] = {}
    n_columns = 0
    header_rows = 0
    header_streak = True
    for row_index, row in enumerate(rows):
        cells = _row_cells(row)
        all_header = bool(cells)
        column = 0
        for cell in cells:
            while (row_index, column) in occupied:
                column += 1
            row_span = _span(cell, "rowspan")
            column_span = _span(cell, "colspan")
            if (row_index + row_span) * (column + column_span) > (
                _MAX_GRID_CELLS
            ):
                return None
            is_header = cell.tag == "th"
            all_header = all_header and is_header
            occupied[(row_index, column)] = document.TableCell(
                row=row_index,
                column=column,
                is_origin=True,
                row_span=row_span,
                column_span=column_span,
                raw_text=_clean(cell.text_content()),
                is_header=is_header,
            )
            for covered_row in range(row_index, row_index + row_span):
                for covered_col in range(column, column + column_span):
                    coordinate = (covered_row, covered_col)
                    if coordinate == (row_index, column):
                        continue
                    occupied.setdefault(
                        coordinate,
                        document.TableCell(
                            row=covered_row,
                            column=covered_col,
                            is_origin=False,
                            origin=(row_index, column),
                        ),
                    )
            column += column_span
        n_columns = max(n_columns, column)
        if header_streak and all_header:
            header_rows = row_index + 1
        else:
            header_streak = False

    n_rows = max(row for row, _ in occupied) + 1 if occupied else 0
    if n_rows == 0 or n_columns == 0:
        return None
    cells: list[document.TableCell] = []
    for row_index in range(n_rows):
        for column in range(n_columns):
            cell = occupied.get((row_index, column))
            if cell is None:
                cell = document.TableCell(
                    row=row_index,
                    column=column,
                    is_origin=True,
                    row_span=1,
                    column_span=1,
                    raw_text="",
                )
            cells.append(cell)

    caption = None
    for child in element:
        if isinstance(child.tag, str) and child.tag == "caption":
            caption = _clean(child.text_content()) or None
            break
    return document.TableBlock(
        caption=caption,
        n_rows=n_rows,
        n_columns=n_columns,
        header_rows=header_rows,
        cells=cells,
    )
