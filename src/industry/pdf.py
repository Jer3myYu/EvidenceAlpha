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
states an incomplete report's level). Every non-blank input line
reaches the page: ``markdown_text`` in, the same text out.

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

_FILE_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")
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
ol { margin: 0 0 8pt 0; padding-left: 18pt; }
ol li { font-size: 8.5pt; color: #333a42; margin: 0 0 3pt 0; }
/* No border-collapse anywhere: the Story engine repaints a collapsed
   table's cell backgrounds at the same coordinates on every later page.
   Separate borders are drawn thin so the doubled edge stays hairline. */
table { width: 100%; border-spacing: 0; margin: 2pt 0 10pt 0; }
th { background-color: #eef1f5; border: 0.4pt solid #a9b2bd; padding: 4pt;
     font-size: 8.5pt; text-align: left; }
td { border: 0.4pt solid #c2c9d2; padding: 4pt; font-size: 8.5pt;
     text-align: left; }
"""


def _inline(text: str) -> str:
    """Escape one line and keep ``**bold**`` as the only inline markup."""
    escaped = html.escape(text, quote=False)
    return _BOLD.sub(r"<b>\1</b>", escaped)


def _table_html(rows: list[str]) -> str:
    """Render the collected pipe-table lines, header row first."""
    cells = [
        [cell.strip() for cell in row.strip().strip("|").split("|")]
        for row in rows
        if not _TABLE_RULE.match(row.strip())
    ]
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
            out.append("<ol>" + "".join(ordered) + "</ol>")
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
            ordered.append(f"<li>{_inline(match.group(2))}</li>")
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


def _fixed_file_id(data: bytes, title: str) -> bytes:
    """Replace the trailer's random ``/ID`` with a content-derived one.

    A PDF writer stamps a fresh random file identifier on every save,
    which is the one thing that would stop identical input producing
    identical bytes. Deriving it from the content keeps the identifier
    meaningful -- two files with the same id hold the same report -- and
    makes the renderer reproducible.

    Args:
      data: The saved PDF bytes.
      title: Mixed into the digest, as it is part of the document.

    Returns:
      ``data`` with a deterministic identifier, unchanged in length.
    """
    match = _FILE_ID.search(data)
    if match is None:
        return data
    head, tail = data[: match.start()], data[match.end() :]
    digest = (
        hashlib.sha256(head + tail + title.encode())
        .hexdigest()[:32]
        .upper()
        .encode()
    )
    return head + b"/ID[<" + digest + b"><" + digest + b">]" + tail


def render_pdf(markdown_text: str, title: str = "") -> bytes:
    """Lay the delivered Markdown out as a paged PDF.

    Deterministic: the same Markdown renders to the same bytes, because
    the document carries fixed metadata and no timestamp.

    Args:
      markdown_text: The delivered report, verbatim.
      title: Document title for the PDF metadata; the visible title is
        always the report's own H1.

    Returns:
      The PDF bytes.
    """
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=markdown_to_html(markdown_text), user_css=CSS)
    more = 1
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(FRAME)
        story.draw(device)
        writer.end_page()
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
        return _fixed_file_id(doc.tobytes(garbage=3, deflate=True), title)
    finally:
        doc.close()


def write_pdf(
    thread_id: str, markdown_text: str, directory: str = REPORTS_DIR
) -> str:
    """Write the rendered PDF atomically beside the Markdown report.

    Args:
      thread_id: Names the file, as it names the Markdown report.
      markdown_text: The delivered report, verbatim.
      directory: Where reports are written.

    Returns:
      The path written.
    """
    path = pathlib.Path(directory) / f"{thread_id}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=".tmp-", suffix=".pdf", delete=False
    )
    try:
        handle.write(render_pdf(markdown_text, title=thread_id))
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
