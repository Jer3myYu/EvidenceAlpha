"""Paginate complete list items while retaining numbering and original text."""

from unittest import mock

import bs4

from evidencealpha import layout


def test_heading_reserves_first_list_item_and_preserves_numbering(
    monkeypatch, tmp_path
):
    pages = mock.Mock()
    pages.width = 500
    pages.table_pages = []
    pages.measure.side_effect = lambda content, width: len(content)
    pages.finish.return_value = b"pdf"
    monkeypatch.setattr(layout, "Pages", lambda folder: pages)
    soup = bs4.BeautifulSoup(
        '<h2>Terms</h2><ol start="4"><li>First original 10 EUR.</li>'
        "<li>Second original: prototype, not production.</li></ol>",
        "html.parser",
    )
    payload, _ = layout.pdf(soup, tmp_path)
    assert payload == b"pdf"
    calls = pages.block.call_args_list
    assert len(calls) == 3
    first, second = calls[1].args[0], calls[2].args[0]
    assert 'start="4"' in first and 'start="5"' in second
    assert "First original 10 EUR." in first
    assert "Second original: prototype, not production." in second
    assert calls[0].args[1] == len(first) + 4
