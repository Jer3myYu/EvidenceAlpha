"""Measured report pagination using existing PyMuPDF HTML rendering."""

import pathlib
import re

import bs4
import fontTools.ttLib
import pymupdf

from evidencealpha import artifacts

CSS = """
@font-face {font-family: Report; src: url(fonts/regular-v5.otf);}
@font-face {font-family: Report; src: url(fonts/bold-v5.otf); font-weight: bold;}
body {font-family: Report; font-size: 10.5pt; line-height: 1.55;
      color: #303842; margin: 0;}
h1 {font-size: 21pt; color: #16334c; margin: 0 0 12pt;}
h2 {font-size: 14pt; color: #16334c; margin: 12pt 0 7pt;}
h3 {font-size: 11.5pt; color: #16334c; margin: 9pt 0 5pt;}
p {margin: 0 0 7pt;} li {margin-bottom: 4pt;}
a {color: #235d80;}
code {font-family: Report;}
"""


def fonts(folder: pathlib.Path) -> dict:
    """Extract installed Simplified Chinese faces for reproducible embedding."""
    target = folder / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    record = {}
    for weight, source in (
        ("regular", "NotoSansCJK-Regular.ttc"),
        ("bold", "NotoSansCJK-Bold.ttc"),
    ):
        path = pathlib.Path("/usr/share/fonts/opentype/noto") / source
        if not path.is_file():
            raise ValueError(f"Installed Chinese font unavailable: {path}")
        output = target / f"{weight}-v5.otf"
        if not output.exists():
            collection = fontTools.ttLib.TTCollection(path)
            try:
                face = next(
                    font
                    for font in collection.fonts
                    if font["name"].getDebugName(1) == "Noto Sans CJK SC"
                )
                # CJK OpenType alternate glyphs map to compatibility/PUA
                # characters in this renderer. Use nominal SC glyphs so PDF
                # extraction retains the original Unicode, including digits.
                if "GSUB" in face:
                    del face["GSUB"]
                nominal = {}
                for codepoint, glyph in sorted(
                    face.getBestCmap().items(),
                    key=lambda item: (
                        (
                            0
                            if item[0] < 128
                            else (
                                1
                                if 0x4E00 <= item[0] <= 0x9FFF
                                else 2 if 0x3400 <= item[0] <= 0x4DBF else 3
                            )
                        ),
                        item[0],
                    ),
                ):
                    nominal.setdefault(glyph, codepoint)
                for table in face["cmap"].tables:
                    if table.isUnicode() and hasattr(table, "cmap"):
                        table.cmap = {
                            k: v
                            for k, v in table.cmap.items()
                            if not 0xE000 <= k <= 0xF8FF and nominal.get(v) == k
                        }
                face.save(output)
            finally:
                collection.close()
        record[weight] = {
            "source": str(path),
            "file": str(output),
            "sha256": artifacts.digest(output.read_bytes()),
        }
    artifacts.write(target / "manifest.json", record)
    return record


class Pages:
    """Lay out complete blocks and measured rows without shrinking text."""

    def __init__(self, folder: pathlib.Path) -> None:
        fonts(folder)
        self.folder = folder
        self.document = pymupdf.open()
        self.archive = pymupdf.Archive(str(folder))
        self.page = self.document.new_page()
        self.y = 44.0
        self.bottom = 789.0
        self.width = 507.0
        self.table_pages = []

    def next_page(self) -> None:
        """Continue content inside the same page geometry."""
        self.page = self.document.new_page()
        self.y = 44.0

    def measure(self, content: str, width: float, css: str = "") -> float:
        """Measure HTML at its actual width with no scaling."""
        story = pymupdf.Story(content, user_css=CSS + css, archive=self.archive)
        more, rect = story.place(pymupdf.Rect(0, 0, width, 10000))
        if more:
            raise ValueError("Report block exceeds measurable height")
        return rect[3]

    def block(self, content: str, keep: float = 0) -> None:
        """Keep headings with following content and preserve block text."""
        height = self.measure(content, self.width) + 2
        if height > self.bottom - 44:
            raise ValueError("Report block exceeds one page; split its content")
        if self.y + height + keep > self.bottom:
            self.next_page()
        spare, scale = self.page.insert_htmlbox(
            pymupdf.Rect(44, self.y, 551, self.y + height),
            content,
            css=CSS,
            archive=self.archive,
            scale_low=1,
        )
        if spare < 0 or scale != 1:
            raise ValueError(
                "Measured report block did not fit without scaling"
            )
        self.y += height

    def table(self, table: bs4.Tag) -> None:
        """Draw continuous grids, repeat headers and keep complete rows."""
        rows = [
            r.find_all(["td", "th"], recursive=False)
            for r in table.find_all("tr")
        ]
        if not rows or not rows[0]:
            return
        count = len(rows[0])
        if any(len(row) != count for row in rows):
            raise ValueError("Report table has inconsistent columns")
        weights = []
        for col in range(count):
            lengths = sorted(len(r[col].get_text()) for r in rows)
            weights.append(max(5, min(26, lengths[len(lengths) // 2])))
        if count > 2:
            weights[0] = min(weights[0], 6)
        minimum = min(60, self.width / count * 0.8)
        extra = self.width - minimum * count
        widths = [minimum + extra * w / sum(weights) for w in weights]
        css = "body {font-size: 9.5pt; line-height: 1.45;} p {margin: 0;}"

        regular = pymupdf.Font(
            fontfile=str(self.folder / "fonts/regular-v5.otf")
        )
        bold = pymupdf.Font(fontfile=str(self.folder / "fonts/bold-v5.otf"))

        def cell_html(cell: bs4.Tag, available_width: float) -> str:
            wrapped = bs4.BeautifulSoup(cell.decode_contents(), "html.parser")
            font = bold if cell.name == "th" else regular

            def fit_word(match: re.Match) -> str:
                word = match[0]
                if font.text_length(word, fontsize=9.5) <= available_width:
                    return word
                parts, current = [], ""
                for character in word:
                    if (
                        current
                        and font.text_length(current + character, fontsize=9.5)
                        > available_width
                    ):
                        parts.append(current)
                        current = ""
                    current += character
                parts.append(current)
                return "\u200b".join(parts)

            for node in list(wrapped.find_all(string=True)):
                node.replace_with(
                    re.sub(r"[\x21-\x7e]{2,}", fit_word, str(node))
                )
            value = str(wrapped)
            return "<b>" + value + "</b>" if cell.name == "th" else value

        heights = [
            max(
                self.measure(cell_html(c, w - 12), w - 12, css)
                for c, w in zip(row, widths)
            )
            + 14
            for row in rows
        ]
        if any(h + heights[0] > self.bottom - 44 for h in heights[1:]):
            raise ValueError(
                "Table row too tall; move commentary to keyed notes"
            )

        def draw(index: int) -> None:
            x = 44.0
            h = heights[index]
            color = (
                (0.89, 0.93, 0.96)
                if index == 0
                else ((0.96, 0.97, 0.98) if index % 2 else (1, 1, 1))
            )
            for cell, width in zip(rows[index], widths):
                rect = pymupdf.Rect(x, self.y, x + width, self.y + h)
                self.page.draw_rect(
                    rect, color=(0.73, 0.77, 0.81), fill=color, width=0.45
                )
                numeric = bool(
                    re.fullmatch(
                        r"[\d\s.,%+−—–()（）-]+", cell.get_text().strip()
                    )
                )
                spare, scale = self.page.insert_htmlbox(
                    rect + (6, 6, -6, -6),
                    cell_html(cell, width - 12),
                    css=CSS
                    + css
                    + ("body {text-align: right;}" if numeric else ""),
                    archive=self.archive,
                    scale_low=1,
                )
                if spare < 0 or scale != 1:
                    raise ValueError(
                        f"Table cell did not fit: {width=}, {h=}, "
                        f"{cell.get_text()[:80]}"
                    )
                x += width
            self.y += h

        if self.y + sum(heights[:2]) > self.bottom:
            self.next_page()
        draw(0)
        pages = [self.page.number + 1]
        for index in range(1, len(rows)):
            # Avoid a single final row where two rows fit on a fresh page.
            needed = heights[index]
            if index == len(rows) - 2:
                pair = sum(heights[index:])
                if pair + heights[0] < self.bottom - 44:
                    needed = pair
            if self.y + needed > self.bottom:
                self.next_page()
                draw(0)
                pages.append(self.page.number + 1)
            draw(index)
        self.table_pages.append(pages)
        self.y += 10

    def finish(self) -> bytes:
        """Add page numbers and return a PDF with embedded fonts."""
        for i, page in enumerate(self.document):
            page.insert_font(
                fontname="Report",
                fontfile=str(self.folder / "fonts/regular-v5.otf"),
            )
            page.insert_text(
                (475, 818),
                f"{i + 1} / {len(self.document)}",
                fontsize=9,
                fontname="Report",
                color=(0.35, 0.4, 0.45),
            )
        return self.document.tobytes(garbage=4, deflate=True)


def pdf(soup: bs4.BeautifulSoup, folder: pathlib.Path) -> tuple[bytes, dict]:
    """Render Markdown HTML blocks, preserving live links and complete rows."""
    pages = Pages(folder)
    try:
        blocks = []
        for block in soup.children:
            if not isinstance(block, bs4.Tag):
                continue
            if block.name in ("ul", "ol"):
                start = int(block.get("start", 1))
                for index, item in enumerate(
                    block.find_all("li", recursive=False)
                ):
                    wrapper = bs4.BeautifulSoup("", "html.parser").new_tag(
                        block.name, attrs={**block.attrs, "style": "margin: 0;"}
                    )
                    if block.name == "ol":
                        wrapper["start"] = str(start + index)
                    wrapper.append(bs4.BeautifulSoup(str(item), "html.parser"))
                    blocks.append(wrapper)
            else:
                blocks.append(block)
        for i, block in enumerate(blocks):
            if block.name == "table":
                pages.table(block)
            else:
                keep = 2 if block.name in ("h1", "h2", "h3") else 0
                if keep:
                    for following in blocks[i + 1 :]:
                        if following.name not in ("h1", "h2", "h3"):
                            # Lists are split into complete items above. Reserve
                            # the next item's height, not the full list.
                            keep += (
                                90
                                if following.name == "table"
                                else pages.measure(str(following), pages.width)
                                + 2
                            )
                            break
                        keep += pages.measure(str(following), pages.width)
                elif block.name == "p" and block.get_text().rstrip().endswith(
                    ("：", ":")
                ):
                    keep = 45
                pages.block(str(block), keep)
        return pages.finish(), {"table_pages": pages.table_pages}
    finally:
        pages.document.close()
