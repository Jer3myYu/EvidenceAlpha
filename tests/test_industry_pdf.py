"""The delivered report, rendered as a PDF.

Plan §4.47: typography runs after the delivery gate on exactly the
Markdown the gate approved. These pin the two things that make that
safe -- the PDF says what the Markdown says, and a formatting failure
costs the reader a formatted copy but never the report or its status --
plus the layout features an investor reads: the level callout, tables,
Chinese text, the numbered source list and page numbers.

The read-back checks here are the ones a GPT-6 review of `f495f8f`
showed were needed: independent per-line containment passed against a
renderer that clipped an oversized block, renumbered the source list,
dropped a dash-only table row, and appended invented text.
"""

import pathlib
import re

import pymupdf
import pytest

from industry import pdf

# ``div.callout``'s #fdf3e3 as PyMuPDF reports it: the one fill that
# marks an incomplete report's warning box, as opposed to the 1pt rules
# under each section heading.
CALLOUT_FILL = (0.9921568632125854, 0.9529411792755127, 0.8901960849761963)

REPORT = """# 光掩模产业调研

范围：global；模式：brief；信息截止：2026-09-09；报告状态：incomplete

> **不完整——部分研究报告，未经完整最终核验**
>
> the final review did not judge the draft consistent.
> 未纳入的部分: economics、barriers.

## 产业概览

光掩模是半导体光刻工艺的图形母版[1, 2]。上游为掩模基板供应[3]。

## 代表性企业对比

| 公司 | 环节 | 总部 | 关键限定说明 |
|---|---|---|---|
| HOYA | 掩模基板精加工 | 日本 | EUV份额33-40%来自证据强度较弱的片段[1] |
| 湖北菲利华 | 掩模基板原料 | 中国大陆 | 是否已覆盖精加工环节，证据自相矛盾[2] |

## 局限性

- [material] missing_evidence on Q4: 缺乏同一口径的财务指标。
  - execution ceiling: 4 repairs is the run's limit

## 来源

1. EUV Mask Blank Battle — https://semiengineering.com/euv-mask-blank
2. 菲利华石英玻璃 — https://www.feilihua.com/optics/info.aspx?itemid=2207
"""


def _text(data: bytes) -> str:
    """Every page's text, with the stamped footers removed.

    A paragraph that flows across a page break is otherwise interrupted
    by the page number drawn between the two halves.
    """
    with pymupdf.open("pdf", data) as doc:
        raw = "\n".join(page.get_text() for page in doc)
    raw = raw.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"(?m)^\d+ / \d+$", "", raw)


def _callout_boxes(data: bytes) -> list[tuple[int, float]]:
    """Every page carrying the callout's fill, with the box height."""
    found = []
    with pymupdf.open("pdf", data) as doc:
        for index, page in enumerate(doc):
            found += [
                (index, round(drawing["rect"].height, 1))
                for drawing in page.get_drawings()
                if drawing.get("fill") == CALLOUT_FILL
            ]
    return found


def _packed(text: str) -> str:
    """Text with every space removed, for order-preserving containment."""
    return re.sub(r"\s+", "", text)


def test_a_delivered_report_renders_to_a_readable_pdf() -> None:
    data = pdf.render_pdf(REPORT, title="t1")
    with pymupdf.open("pdf", data) as doc:
        assert doc.is_pdf
        assert doc.page_count >= 1


def test_every_line_of_the_delivered_markdown_reaches_the_page() -> None:
    """Rendering drops no substantive text, in the report's own order."""
    pdf.verify_complete(pdf.render_pdf(REPORT), REPORT)
    packed = _packed(_text(pdf.render_pdf(REPORT)))
    for line in REPORT.splitlines():
        stripped = line.strip().lstrip(">").strip().lstrip("#").strip()
        stripped = re.sub(r"^-\s+", "", stripped).replace("**", "")
        if not stripped or set(stripped) <= set("|-: "):
            continue
        wanted = _packed(stripped.strip("|").replace("|", ""))
        assert wanted in packed, line


def test_a_render_that_loses_text_is_refused_not_returned() -> None:
    """A block too tall to fit is clipped by the engine, silently.

    One oversized callout swallowed the end of the limitations block
    and still returned a two-page PDF. Delivery must get an error, not
    a report that is quietly short.
    """
    oversized = "> WARNING\n> " + "内容 " * 3000 + "END_OF_LIMITATIONS"
    with pytest.raises(pdf.IncompleteRender):
        pdf.render_pdf(oversized)


def test_reordered_or_invented_text_fails_verification() -> None:
    """The check is bidirectional: nothing moves and nothing is added."""
    rendered = pdf.render_pdf(REPORT)
    reordered = "\n\n".join(reversed(REPORT.split("\n\n")))
    with pytest.raises(pdf.IncompleteRender):
        pdf.verify_complete(rendered, reordered)
    shortened = "# 光掩模产业调研\n\n范围：global\n"
    with pytest.raises(pdf.IncompleteRender) as caught:
        pdf.verify_complete(rendered, shortened)
    assert "carries text the report does not" in str(caught.value)


def test_the_source_list_keeps_the_numbers_the_citations_point_at() -> None:
    """An ``<ol>``'s own counter would repoint every citation.

    ``[7]`` in the body means source 7. A list that renumbers from 1
    per block silently rewrites what the reader is being sent to.
    """
    sources = "## 来源\n\n2. Source two\n\n7. Source seven\n"
    packed = _packed(_text(pdf.render_pdf(sources)))
    assert "2.Sourcetwo" in packed
    assert "7.Sourceseven" in packed


def test_a_dash_only_row_is_data_not_a_second_header_rule() -> None:
    """Only the row under the header is the ``|---|`` separator."""
    table = "| a | b |\n|---|---|\n| - | - |\n| x | y |\n"
    data = pdf.render_pdf(table)
    pdf.verify_complete(data, table)
    assert _packed(_text(data)).count("-") == 2


def test_an_empty_edge_cell_does_not_shift_the_columns() -> None:
    """``strip("|")`` would eat the empty cell and move v2 under h1."""
    table = "| h1 | h2 |\n|---|---|\n|  | v2 |\n"
    assert pdf.markdown_to_html(table).count("<td>") == 2


def test_a_hostile_title_cannot_corrupt_the_document() -> None:
    """The file id is set through the trailer, not by byte surgery.

    Rewriting the first ``/ID`` found in the saved bytes hit the title
    string instead of the trailer and shifted every later offset.
    """
    data = pdf.render_pdf("# Test\n\nApproved text", title="/ID[<00><00>]")
    with pymupdf.open("pdf", data) as doc:
        assert not doc.is_repaired
        assert doc.metadata["title"] == "/ID[<00><00>]"


def test_chinese_text_is_embedded_not_dropped() -> None:
    """The bundled CJK face renders the body; no system font is needed."""
    data = pdf.render_pdf(REPORT)
    assert "光掩模是半导体光刻工艺的图形母版" in _packed(_text(data))
    with pymupdf.open("pdf", data) as doc:
        faces = {font[3] for page in doc for font in page.get_fonts()}
    assert any("Droid" in name for name in faces), faces


def test_a_table_keeps_its_cells_and_stays_inside_the_page() -> None:
    data = pdf.render_pdf(REPORT)
    packed = _packed(_text(data))
    for cell in ("HOYA", "掩模基板精加工", "湖北菲利华", "中国大陆"):
        assert cell in packed
    with pymupdf.open("pdf", data) as doc:
        for page in doc:
            for drawing in page.get_drawings():
                assert drawing["rect"].x1 <= page.rect.x1 + 1


def test_citations_and_the_numbered_source_list_survive() -> None:
    packed = _packed(_text(pdf.render_pdf(REPORT)))
    assert "[1,2]" in packed
    assert "https://semiengineering.com/euv-mask-blank" in packed
    assert "https://www.feilihua.com/optics/info.aspx?itemid=2207" in packed


def test_an_incomplete_report_shows_its_level_callout() -> None:
    """Level B: the reader cannot mistake it for a verified report."""
    data = pdf.render_pdf(REPORT)
    assert "不完整——部分研究报告，未经完整最终核验" in _packed(_text(data))
    boxes = _callout_boxes(data)
    assert boxes, "the callout is not painted"
    assert all(page == 0 for page, _ in boxes)


def test_a_withheld_report_shows_its_own_callout() -> None:
    """Level C: diagnostics only, and the body is not there to render."""
    withheld = REPORT.replace(
        "**不完整——部分研究报告，未经完整最终核验**",
        "**不完整——正文已保留未发布，仅提供诊断信息**",
    )
    packed = _packed(_text(pdf.render_pdf(withheld)))
    assert "正文已保留未发布，仅提供诊断信息" in packed


def test_a_verified_report_carries_no_callout() -> None:
    """Level A: ``report._label_lines`` emits no quote, so none is drawn."""
    verified = "\n".join(
        line for line in REPORT.splitlines() if not line.startswith(">")
    )
    data = pdf.render_pdf(verified)
    assert "不完整" not in _text(data)
    assert not _callout_boxes(
        data
    ), "a verified report drew an incomplete-report callout"


def test_a_long_report_pages_and_numbers_every_page() -> None:
    long_report = (
        REPORT
        + "\n"
        + "\n\n".join(
            f"## 第{n}节\n\n" + "光掩模产业的分析段落。" * 40 for n in range(12)
        )
    )
    data = pdf.render_pdf(long_report)
    with pymupdf.open("pdf", data) as doc:
        assert doc.page_count > 3
        total = doc.page_count
        for index, page in enumerate(doc, start=1):
            assert f"{index} / {total}" in page.get_text()


def test_a_page_break_never_repeats_a_background_on_later_pages() -> None:
    """The callout is drawn once, where it belongs (Story bleeds them)."""
    long_report = (
        REPORT
        + "\n"
        + "\n\n".join(
            f"## 第{n}节\n\n" + "光掩模产业的分析段落。" * 40 for n in range(12)
        )
    )
    later = [
        page for page, _ in _callout_boxes(pdf.render_pdf(long_report)) if page
    ]
    assert not later, f"callout background repeated on pages {later}"


def test_the_same_report_renders_to_the_same_bytes() -> None:
    """No timestamp, no random file id: rendering is deterministic."""
    assert pdf.render_pdf(REPORT, title="t") == pdf.render_pdf(
        REPORT, title="t"
    )


def test_write_pdf_creates_the_file_beside_the_markdown(
    tmp_path: pathlib.Path,
) -> None:
    written = pdf.write_pdf("abc123", REPORT, str(tmp_path))
    assert written == str(tmp_path / "abc123.pdf")
    assert (tmp_path / "abc123.pdf").is_file()
    assert (tmp_path / "abc123.pdf").read_bytes().startswith(b"%PDF")
    assert not list(tmp_path.glob(".tmp-*")), "a temporary file was left behind"


def test_pdf_beside_finds_the_pdf_only_when_it_exists(
    tmp_path: pathlib.Path,
) -> None:
    markdown = tmp_path / "abc123.md"
    markdown.write_text(REPORT, encoding="utf-8")
    assert pdf.pdf_beside(str(markdown)) is None
    assert pdf.pdf_beside(None) is None
    pdf.write_pdf("abc123", REPORT, str(tmp_path))
    assert pdf.pdf_beside(str(markdown)) == str(tmp_path / "abc123.pdf")


def test_markdown_is_rendered_even_when_it_is_not_markdown() -> None:
    """An unrecognised line becomes a paragraph; nothing is dropped."""
    odd = "plain line\n<b>not markup</b>\n\t indented\n"
    packed = _packed(_text(pdf.render_pdf(odd)))
    assert "plainline" in packed
    assert "<b>notmarkup</b>" in packed, "HTML in the report was not escaped"
    assert "indented" in packed


def test_an_empty_report_still_produces_a_pdf() -> None:
    with pymupdf.open("pdf", pdf.render_pdf("")) as doc:
        assert doc.page_count == 1


@pytest.mark.parametrize("title", ["", "372eca30"])
def test_the_pdf_carries_fixed_metadata(title: str) -> None:
    with pymupdf.open("pdf", pdf.render_pdf(REPORT, title=title)) as doc:
        assert doc.metadata["title"] == title
        assert doc.metadata["producer"] == pdf.PRODUCER
        assert not doc.metadata["creationDate"]
