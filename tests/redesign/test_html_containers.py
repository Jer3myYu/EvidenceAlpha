"""HTML evidence in ordinary containers must survive ingestion once."""

from evidencealpha import documents


def test_html_containers_preserve_context_once():
    blocks, _ = documents._blocks(
        "<html><body><nav>menu</nav><div><h2>产品</h2>"
        "<div>支持 <b>100G</b> 接口，仍在验证。</div>"
        "<section>收入单位：万元<table><tr><th>期间</th><th>收入</th>"
        "</tr><tr><td>2025</td><td>12</td></tr></table>"
        "<p>指公司收入，不是客户收入。</p></section></div>"
        "<script>secret</script></body></html>".encode(),
        ".html",
    )
    assert [b["text"] for b in blocks] == [
        "产品",
        "支持 100G 接口，仍在验证。",
        "收入单位：万元",
        "期间 | 收入\n2025 | 12",
        "指公司收入，不是客户收入。",
    ]
    assert blocks[0]["kind"] == "heading"
    assert blocks[3]["kind"] == "table"


def test_layout_table_does_not_duplicate_nested_article():
    blocks, _ = documents._blocks(
        b"<table><tbody><tr><td><h1>Article</h1><p>Context.</p>"
        b"<table><tr><td>Period</td><td>Value</td></tr>"
        b"<tr><td>2025</td><td>12</td></tr></table>"
        b"<p>Qualification.</p></td></tr></tbody></table>",
        ".html",
    )
    assert [b["text"] for b in blocks] == [
        "Article",
        "Context.",
        "Period | Value\n2025 | 12",
        "Qualification.",
    ]
