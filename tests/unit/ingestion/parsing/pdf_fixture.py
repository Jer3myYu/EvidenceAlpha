"""A small, deterministic digital-PDF fixture, built on demand.

The corpus's real PDFs live under gitignored working notes, so the
repository's own tests generate a two-page digital PDF with prose and
one ruled table. The geometry and text are fixed; the pinned-
determinism conformance check parses one generated file twice, so the
PDF library's embedded timestamps do not matter.
"""

import pymupdf

#: Table geometry: a ruled 4x3 grid.
_TABLE_ROWS = [
    ["Metric", "FY2025", "FY2024"],
    ["Revenue", "849,294", "866,951"],
    ["Gross profit", "299,830", "316,555"],
    ["Net income", "130,700", "132,900"],
]
_LEFT = 72.0
_TOP = 200.0
_ROW_HEIGHT = 24.0
_COLUMN_WIDTHS = [180.0, 90.0, 90.0]


def write_pdf(path: str) -> None:
    """Write the fixture PDF.

    Args:
      path: Destination file path.
    """
    pdf = pymupdf.open()
    first = pdf.new_page()
    first.insert_text(
        (72, 100),
        "Photomask fixture report for the parser test suite.",
        fontsize=11,
    )
    first.insert_text(
        (72, 130),
        "This page carries prose; the next carries a ruled table.",
        fontsize=11,
    )

    second = pdf.new_page()
    second.insert_text(
        (72, 100), "Selected financial data (in thousands).", fontsize=11
    )
    top = _TOP
    for row in _TABLE_ROWS:
        left = _LEFT
        for text, width in zip(row, _COLUMN_WIDTHS):
            rect = pymupdf.Rect(left, top, left + width, top + _ROW_HEIGHT)
            second.draw_rect(rect, color=(0, 0, 0), width=0.7)
            second.insert_text(
                (left + 4, top + _ROW_HEIGHT - 8), text, fontsize=9
            )
            left += width
        top += _ROW_HEIGHT

    pdf.set_metadata({})
    pdf.save(path, deflate=True)
    pdf.close()
