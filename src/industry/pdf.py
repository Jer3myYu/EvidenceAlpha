"""Deterministic PDF rendering of the already-delivered Markdown report.

The delivered Markdown is the authoritative content. This module runs
**after** the delivery gate and renders exactly the string
``report.render`` produced -- it never reads run state, never calls a
model, and never decides what may be published. Its only job is
typography: the same words, on paged A4, in a shape an investor can
read.

The parser accepts the narrow Markdown subset ``report.render`` emits
(one H1, H2 sections, paragraphs, pipe tables, ``-`` bullets with one
level of nesting, the numbered source list, and the ``>`` callout that
states an incomplete report's level).

**Every non-blank input line reaches the page, or no PDF is produced.**
The layout engine silently clips a block it cannot fit -- a table cell
taller than the frame loses its tail -- so ``render_pdf`` reads its own
output back and raises ``IncompleteRender`` unless every fragment of
the delivered text is there, in order. Delivery treats that as it
treats any other rendering failure: the Markdown report stands.

Rendering uses PyMuPDF's Story engine, already a project dependency for
``PyMuPDFLoader``. Its bundled Droid Sans Fallback face covers the
Chinese body text, so the output does not depend on a system font.
"""

import hashlib
import html
import io
import os
import pathlib
import re
import tempfile

import pymupdf

from industry.report import REPORTS_DIR

# A4 with margins wide enough for a printed research note.
PAGE = pymupdf.paper_rect("a4")
MARGIN_X = 56.0
MARGIN_TOP = 58.0
MARGIN_BOTTOM = 64.0
FRAME = PAGE + (MARGIN_X, MARGIN_TOP, -MARGIN_X, -MARGIN_BOTTOM)
FOOTER_BASELINE = PAGE.y1 - 38.0

# Fixed metadata: two renders of one report produce identical bytes.
PRODUCER = "EvidenceAlpha industry research"

# Extraction turns these back into the glyphs the input carried.
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_FOOTER = re.compile(r"(?m)^\d+ / \d+$")
_BULLET = re.compile(r"^-\s+")
# The only mark the renderer itself puts on the page: a list bullet.
# Anything else between two fragments of delivered text is text the
# report does not contain.
_DECORATION = frozenset("\u2022")
_TABLE_RULE = re.compile(r"^\|[\s:|-]+\|$")
_ORDERED = re.compile(r"^(\d+)\.\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")

CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.55;
       color: #16191d; }
h1 { font-size: 15.5pt; line-height: 1.35; margin: 0 0 2pt 0;
     color: #0f1419; }
h2 { font-size: 13pt; line-height: 1.35; margin: 16pt 0 5pt 0;
     color: #0f1419; border-bottom: 1pt solid #c8ced6; padding-bottom: 3pt; }
p { margin: 0 0 7pt 0; text-align: left; }
p.meta { font-size: 8.5pt; color: #5b6470; margin: 0 0 12pt 0; }
table.callout { width: 100%; border-spacing: 0; margin: 0 0 14pt 0; }
td.callout { background-color: #fdf3e3; border: 1pt solid #d9a441;
             padding: 8pt; }
p.callout-head { font-size: 11pt; margin: 0 0 5pt 0; color: #8a5a00; }
p.callout-line { font-size: 9pt; margin: 0 0 2pt 0; text-align: left; }
ul { margin: 0 0 8pt 0; padding-left: 14pt; }
li { margin: 0 0 4pt 0; text-align: left; }
li.sub { color: #4a525c; font-size: 9pt; }
p.numbered { font-size: 8.5pt; color: #333a42; margin: 0 0 3pt 0;
             padding-left: 18pt; text-indent: -18pt; text-align: left; }
/* No border-collapse anywhere: the Story engine repaints a collapsed
   table's cell backgrounds at the same coordinates on every later page.
   Separate borders are drawn thin so the doubled edge stays hairline. */
table { width: 100%; border-spacing: 0; margin: 2pt 0 10pt 0; }
th { background-color: #eef1f5; border: 0.4pt solid #a9b2bd; padding: 4pt;
     font-size: 8.5pt; text-align: left; }
td { border: 0.4pt solid #c2c9d2; padding: 4pt; font-size: 8.5pt;
     text-align: left; }
"""


class IncompleteRender(RuntimeError):
    """The rendered PDF does not carry all of the delivered text.

    Raised rather than returning a PDF that quietly drops a limitation
    or a table row: a report the reader cannot trust to be complete is
    worse than no formatted copy at all.
    """


def _inline(text: str) -> str:
    """Escape one line and keep ``**bold**`` as the only inline markup."""
    escaped = html.escape(text, quote=False)
    return _BOLD.sub(r"<b>\1</b>", escaped)


def _split_row(row: str) -> list[str]:
    """One pipe row's cells, without its two delimiting pipes.

    Only the outermost pair is a delimiter: ``strip("|")`` would eat an
    empty leading or trailing cell and shift every value one column.
    """
    inner = row.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _table_html(rows: list[str]) -> str:
    """Render the collected pipe-table lines, header row first.

    Only the row immediately under the header may be the ``|---|`` rule.
    A later row of dashes is data -- a table of placeholders would
    otherwise lose it silently.
    """
    kept = [
        row
        for index, row in enumerate(rows)
        if not (index == 1 and _TABLE_RULE.match(row.strip()))
    ]
    cells = [_split_row(row) for row in kept]
    if not cells:
        return ""
    width = max(len(row) for row in cells)
    out = ["<table>"]
    for index, row in enumerate(cells):
        padded = row + [""] * (width - len(row))
        tag = "th" if index == 0 else "td"
        out.append("<tr>")
        out += [f"<{tag}>{_inline(cell)}</{tag}>" for cell in padded]
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def markdown_to_html(markdown_text: str) -> str:
    """The delivered Markdown as the HTML the Story engine lays out.

    A line-driven reader for exactly the subset ``report.render``
    writes. Anything it does not recognise becomes a paragraph, so no
    input line is ever dropped.

    Args:
      markdown_text: The delivered report, verbatim.

    Returns:
      An HTML fragment carrying the same text, in the same order.
    """
    out: list[str] = []
    table: list[str] = []
    quote: list[str] = []
    bullets: list[str] = []
    ordered: list[str] = []
    seen_meta = False

    def flush() -> None:
        nonlocal table, quote, bullets, ordered
        if table:
            out.append(_table_html(table))
            table = []
        if quote:
            head, *rest = quote
            # A one-cell table, not a styled div: the Story engine
            # repaints a block element's background at the top of every
            # later page, and a table cell's background stays put.
            out.append('<table class="callout"><tr><td class="callout">')
            out.append(f'<p class="callout-head">{_inline(head)}</p>')
            out.extend(
                f'<p class="callout-line">{_inline(line)}</p>'
                for line in rest
                if line
            )
            out.append("</td></tr></table>")
            quote = []
        if bullets:
            out.append("<ul>" + "".join(bullets) + "</ul>")
            bullets = []
        if ordered:
            out.extend(ordered)
            ordered = []

    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("|"):
            if not table:
                flush()
            table.append(stripped)
            continue
        if stripped.startswith(">"):
            if not quote:
                flush()
            quote.append(stripped.lstrip(">").strip())
            continue
        if stripped.startswith("- "):
            if not bullets:
                flush()
            klass = ' class="sub"' if line.startswith("  ") else ""
            bullets.append(f"<li{klass}>{_inline(stripped[2:])}</li>")
            continue
        match = _ORDERED.match(stripped)
        if match:
            if not ordered:
                flush()
            # The literal number, never an ``<ol>``'s own counter: the
            # source list is what ``[3]`` in the body points at, and an
            # engine that restarts numbering would repoint every
            # citation in the report.
            ordered.append(
                f'<p class="numbered">{_inline(match.group(1))}. '
                f"{_inline(match.group(2))}</p>"
            )
            continue
        flush()
        if stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif not seen_meta and out and out[-1].startswith("<h1>"):
            out.append(f'<p class="meta">{_inline(stripped)}</p>')
            seen_meta = True
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
    flush()
    return "".join(out)


def _stamp_page_numbers(doc: pymupdf.Document) -> None:
    """Write ``n / total`` centred in each page's bottom margin."""
    total = doc.page_count
    for index, page in enumerate(doc, start=1):
        label = f"{index} / {total}"
        width = pymupdf.get_text_length(label, fontname="helv", fontsize=8.5)
        page.insert_text(
            (PAGE.x1 / 2 - width / 2, FOOTER_BASELINE),
            label,
            fontname="helv",
            fontsize=8.5,
            color=(0.42, 0.46, 0.51),
        )


def _set_file_id(doc: pymupdf.Document, markdown_text: str, title: str) -> None:
    """Give the document an identifier derived from what it contains.

    A PDF writer stamps a fresh random file identifier on every save,
    and that alone would stop identical input producing identical
    bytes. The digest is taken from the renderer's *inputs* rather than
    from the saved bytes, so it can be set through the document's own
    trailer -- rewriting raw bytes risked matching a ``/ID`` inside a
    compressed stream or a metadata string and corrupting the file.

    Args:
      doc: The document, before it is saved.
      markdown_text: The delivered report, verbatim.
      title: Also part of the document, so also part of the digest.
    """
    seed = f"{title}\x00{markdown_text}".encode()
    digest = hashlib.sha256(seed).hexdigest()[:32].upper()
    doc.xref_set_key(-1, "ID", f"[<{digest}><{digest}>]")


def _packed(text: str) -> str:
    """Text with all whitespace removed, for layout-independent search."""
    return re.sub(r"\s+", "", text)


def rendered_text(data: bytes) -> str:
    """Everything the PDF actually puts on its pages.

    The stamped page numbers come out too, and they sit between the two
    halves of any paragraph that flows across a break, so they are
    removed before the text is compared with its source.

    Args:
      data: The PDF bytes.

    Returns:
      The page text, footers dropped and ligatures expanded.
    """
    with pymupdf.open("pdf", data) as doc:
        raw = "\n".join(page.get_text() for page in doc)
    for ligature, plain in _LIGATURES.items():
        raw = raw.replace(ligature, plain)
    return _FOOTER.sub("", raw)


def expected_fragments(markdown_text: str) -> list[str]:
    """The pieces of delivered text a faithful rendering must show.

    One fragment per line, except a table row, which contributes one
    fragment per cell -- a row is laid out as separate cells and never
    reads back as one string. Markup that the renderer turns into
    typography rather than words (``#``, ``>``, ``**``, the bullet
    dash, the table rule) is dropped; a list's number is **kept**,
    because the source list is what the body's citations point at.

    Args:
      markdown_text: The delivered report, verbatim.

    Returns:
      The fragments, whitespace removed, in the order they must appear.
    """
    fragments: list[str] = []
    row = 0
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            # The same rule ``_table_html`` applies, so the two can
            # never disagree about which dashes are a separator and
            # which are a cell the reader must still see.
            if not (row == 1 and _TABLE_RULE.match(stripped)):
                fragments += _split_row(stripped)
            row += 1
            continue
        row = 0
        if not stripped:
            continue
        stripped = stripped.lstrip(">").strip().lstrip("#").strip()
        stripped = _BULLET.sub("", stripped).replace("**", "")
        fragments.append(stripped)
    return [packed for packed in map(_packed, fragments) if packed]


def verify_complete(data: bytes, markdown_text: str) -> None:
    """Raise unless the PDF is the delivered report and nothing else.

    Three things are checked by reading the finished pages back, and
    they are the three ways typography could change what was verified:
    nothing delivered is **missing** (the layout engine clips what it
    cannot fit and still reports success), nothing is **reordered**
    (text that survives but moves is not the report that was
    verified), and nothing is **added** -- the only mark the renderer
    contributes of its own is a list bullet.

    Args:
      data: The rendered PDF bytes.
      markdown_text: The delivered report, verbatim.

    Raises:
      IncompleteRender: If a fragment is missing or out of order.
    """
    page_text = _packed(rendered_text(data))
    cursor = 0
    between: list[str] = []
    for fragment in expected_fragments(markdown_text):
        found = page_text.find(fragment, cursor)
        if found < 0:
            missing = fragment[:60]
            raise IncompleteRender(
                f"the rendered PDF is missing, or reorders, {missing!r}"
            )
        between.append(page_text[cursor:found])
        cursor = found + len(fragment)
    between.append(page_text[cursor:])
    added = {char for chunk in between for char in chunk} - _DECORATION
    if added:
        unexpected = "".join(sorted(added))[:60]
        raise IncompleteRender(
            f"the rendered PDF carries text the report does not: "
            f"{unexpected!r}"
        )


def render_pdf(markdown_text: str, title: str = "") -> bytes:
    """Lay the delivered Markdown out as a paged PDF.

    Deterministic: the same Markdown renders to the same bytes, because
    the document carries fixed metadata, no timestamp, and an
    identifier derived from its own content.

    Args:
      markdown_text: The delivered report, verbatim.
      title: Document title for the PDF metadata; the visible title is
        always the report's own H1.

    Returns:
      The PDF bytes.

    Raises:
      IncompleteRender: If the laid-out pages do not carry every
        fragment of the delivered text, in order.
    """
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    try:
        story = pymupdf.Story(
            html=markdown_to_html(markdown_text), user_css=CSS
        )
        more = 1
        while more:
            device = writer.begin_page(PAGE)
            more, _ = story.place(FRAME)
            story.draw(device)
            writer.end_page()
    finally:
        writer.close()

    doc = pymupdf.open("pdf", buffer.getvalue())
    try:
        _stamp_page_numbers(doc)
        doc.set_metadata(
            {
                "title": title,
                "author": "",
                "subject": "",
                "keywords": "",
                "creator": PRODUCER,
                "producer": PRODUCER,
                "creationDate": "",
                "modDate": "",
            }
        )
        # Only the glyphs this report uses: a full CJK face embeds
        # ~1.8 MB, its subset ~140 KB.
        doc.subset_fonts()
        _set_file_id(doc, markdown_text, title)
        # ``no_new_id``: without it the writer refreshes the trailer's
        # second identifier on every save, which is the last thing
        # that would make two renders of one report differ.
        data = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
    finally:
        doc.close()
    verify_complete(data, markdown_text)
    return data


def write_pdf(
    thread_id: str, markdown_text: str, directory: str = REPORTS_DIR
) -> str:
    """Write the rendered PDF atomically beside the Markdown report.

    Rendering happens before the temporary file is created, so a
    refused render leaves nothing behind to clean up.

    Args:
      thread_id: Names the file, as it names the Markdown report.
      markdown_text: The delivered report, verbatim.
      directory: Where reports are written.

    Returns:
      The path written.
    """
    path = pathlib.Path(directory) / f"{thread_id}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = render_pdf(markdown_text, title=thread_id)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=".tmp-", suffix=".pdf", delete=False
    )
    try:
        try:
            handle.write(data)
        finally:
            handle.close()
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)
    return str(path)


def pdf_beside(report_path: str | None) -> str | None:
    """The rendered PDF for a Markdown report, when one was written.

    The PDF is never a separate record: it is the Markdown report's path
    with a ``.pdf`` suffix, so the CLI and the studio can offer it
    without the run state carrying a second field.

    Args:
      report_path: The delivered Markdown report's path, or ``None``.

    Returns:
      The PDF path if it exists on disk, else ``None``.
    """
    if not report_path:
        return None
    candidate = pathlib.Path(report_path).with_suffix(".pdf")
    return str(candidate) if candidate.is_file() else None


def discard_stale(thread_id: str, directory: str = REPORTS_DIR) -> str | None:
    """Delete a thread's PDF, so a failed render cannot leave a stale one.

    A rerun replaces the Markdown report first. If the PDF then fails to
    render, the previous run's PDF would still be sitting beside it, and
    ``pdf_beside`` would offer that older report -- different claims,
    possibly a different verification warning -- as this delivery's
    formatted copy.

    Args:
      thread_id: The thread whose PDF is now out of date.
      directory: Where reports are written.

    Returns:
      The path removed, or ``None`` if there was nothing to remove.
    """
    path = pathlib.Path(directory) / f"{thread_id}.pdf"
    try:
        path.unlink()
    except OSError:
        return None
    return str(path)
