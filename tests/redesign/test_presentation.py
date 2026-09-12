"""Focused presentation preservation and wall-only admission checks."""

import time

import pymupdf
import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import presentation
from evidencealpha import render


def test_tables_repeat_headers_and_preserve_links_fonts_text(tmp_path):
    """A long table keeps Chinese, values and live links on every page."""
    path = tmp_path / "report.md"
    rows = [
        f"| 龙图公司{i} | {i}.25 | 单片验证供货；成套仍在送样，未升级为量产。 |"
        for i in range(26)
    ]
    path.write_text(
        "# 中文报告\n\n| 公司 | 收入 | 状态 |\n|---|---:|---|\n"
        + "\n".join(rows)
        + "\n\n[原始报告](https://example.org/report)\n"
    )
    result = render.export(path)
    assert result["pdf_status"] == "complete", result
    with pymupdf.open(result["pdf"]) as document:
        assert len(document) > 1
        for page in document:
            if "单片验证供货" in page.get_text():
                assert "收入" in page.get_text()
        assert any(page.get_links() for page in document)
        assert all(
            "Noto Sans CJK SC" in font[3]
            for page in document
            for font in page.get_fonts()
        )
        text = "".join(page.get_text() for page in document)
        assert all(f"{i}.25" in text for i in range(26))


def test_table_notes_keep_support_and_commentary():
    """Moving citations retains qualifiers and original source locators."""
    body = "| 公司 | 状态 |\n|---|---|\n| 示例 | 单片供货；成套送样 [S2 c45–c47] |\n"
    result = presentation.table_notes(body)
    assert "单片供货；成套送样" in result
    assert result.count("[S2 c45–c47]") == 1
    assert "注 T1.1" in result


def test_wall_only_calls_retain_concurrency_and_deadline(tmp_path):
    """No call quota means null, while concurrency and expiry still reject."""
    ledger = budget.ExecutionLedger(
        tmp_path / "ledger.json", config.Settings(command_calls=None)
    )
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("full")
    record = ledger.reserve(attempt, "codex", 10)
    with pytest.raises(budget.BudgetExceeded, match="concurrency"):
        ledger.reserve(attempt, "codex", 10)
    ledger.settle(record, 1, "complete", {"output_tokens": 1000000})
    # pylint: disable=protected-access
    assert ledger._check(artifacts.read(ledger.path)) > 0
    data = artifacts.read(ledger.path)
    data["campaign_started"] = time.time() - 999999
    with pytest.raises(budget.BudgetExceeded, match="window exhausted"):
        ledger._check(data)
