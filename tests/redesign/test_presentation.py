"""Focused presentation preservation and wall-only admission checks."""

import time

import pymupdf
import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import presentation
from evidencealpha import render
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow
import json


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


def test_normal_stage_accepts_unlimited_call_telemetry(tmp_path):
    """The actual prompt path serializes no quota without arithmetic on null."""
    settings = config.Settings(
        command_calls=None, workers=1, writer_context_tokens=258400
    )
    ledger = budget.ExecutionLedger(tmp_path / "ledger.json", settings)
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("full")
    provider = providers.FixtureProvider(
        {"plan": {"content": "Plan", "tasks": []}}
    )
    store = documents.SourceStore(tmp_path / "sources")
    runner = workflow.StageRunner(
        settings,
        provider,
        tools.EvidenceTools(store, settings, "fixed-corpus", ledger),
        ledger,
        attempt,
    )
    result = runner.run(
        "plan", "plan", {"brief": "Industry overview"}, tmp_path / "run"
    )
    assert result["output"]["content"] == "Plan"
    assert json.loads(provider.calls[0].prompt)["remaining_calls"] is None
    assert artifacts.read(ledger.path)["invocations"][0]["status"] == "complete"


def test_revision_rebinds_figures_and_preserves_chinese_citations(tmp_path):
    """Prior draft images stay in place; punctuation cannot split citations."""
    store = documents.SourceStore(tmp_path / "sources")
    source = tmp_path / "original.txt"
    source.write_text("Original revenue: 1.25 million in 2025.")
    captured = store.ingest(source, "https://example.org/original")
    value = {
        "content": "# Report\n\n报告日期：2026-09-12 · 信息截止：2026-09-12\n\n"
        "![Comparison](draft/figures/figure-1.png)\n\n"
        "**Name。**Explanation\n\n**A**说明。**B**说明。\n\n"
        "| Company | Status |\n|---|---|\n| Example | "
        + "完整状态说明" * 18
        + "【年报，c1；投资者记录，c2】；单片供货，成套仍送样 |\n",
        "figures": [
            {
                "kind": "bar",
                "title": "Comparison",
                "caption": "Comparable revenue",
                "source_ids": [captured["id"]],
                "period": "2025",
                "unit": "million",
                "caveats": "Scope",
                "labels": ["Example"],
                "values": [1.25],
            }
        ],
    }
    # pylint: disable=protected-access
    path = workflow._prepare_report(
        value, tmp_path, store, "revised.md", "2026-09-12"
    )
    text = path.read_text()
    assert text.count("![Comparison]") == 1
    assert "draft/figures" not in text
    assert "revised/figures/figure-1.png" in text
    assert text.count("报告日期：") == 1
    assert text.count("【年报，c1；投资者记录，c2】") == 1
    assert "成套仍送样" in text
    assert text.count("图 1：") == 1
    assert "**Name**。Explanation" in text
    assert "**A**说明。**B**说明。" in text
