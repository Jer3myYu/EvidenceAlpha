"""Admission persistence, quota substitution and process-group cancellation."""

import json
import pathlib
import sys

import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow


def _ledger(tmp_path):
    ledger = budget.Ledger(tmp_path / "budget.json")
    ledger.initialize()
    return ledger


def test_stage_boundary_and_cumulative_failed_admissions(tmp_path):
    """Stage 1 cannot admit charged Stage 2 work."""
    ledger = _ledger(tmp_path)
    with pytest.raises(
        budget.BudgetExceeded, match="not been explicitly started"
    ):
        ledger.admit("isolated")
    ledger.start()
    for _ in range(10):
        attempt = ledger.admit("isolated")
        ledger.finish(attempt, "failed")
    ledger.initialize()
    with pytest.raises(budget.BudgetExceeded, match="Attempt allowance"):
        ledger.admit("isolated")
    assert len(artifacts.read(ledger.path)["attempts"]) == 10


def test_reservations_and_unknown_usage_are_preserved(tmp_path):
    """Concurrent invocation time is summed; unknown tokens stay unknown."""
    ledger = _ledger(tmp_path)
    ledger.start()
    attempt = ledger.admit("isolated")
    first = ledger.reserve(attempt, "codex", 20)
    second = ledger.reserve(attempt, "codex", 30)
    ledger.settle(first, 4, "failed")
    data = artifacts.read(ledger.path)
    assert data["invocations"][0]["observable_tokens"] is None
    assert data["invocations"][1]["reserved_seconds"] == 30
    with pytest.raises(ValueError, match="already settled"):
        ledger.settle(first, 4, "complete")
    ledger.settle(
        second,
        5,
        "complete",
        {
            "output_tokens": 10,
            "reasoning_tokens": 3,
            "reasoning_in_output": True,
        },
    )
    assert (
        artifacts.read(ledger.path)["invocations"][1]["observable_tokens"] == 10
    )


def test_full_reports_are_sequential_and_claude_caps_are_subsets(tmp_path):
    """No parallel full report or additive probe allowance."""
    ledger = _ledger(tmp_path)
    ledger.start()
    attempt = ledger.admit("full")
    with pytest.raises(budget.BudgetExceeded, match="already running"):
        ledger.admit("full")
    ledger.finish(attempt, "failed")
    for _ in range(3):
        attempt = ledger.admit("claude", "claude")
        assert attempt["deadline"] - attempt["started"] <= 121
        ledger.finish(attempt, "failed")
    with pytest.raises(budget.BudgetExceeded, match="sub-budget"):
        ledger.admit("claude", "claude")


def test_explicit_quota_fallback_retains_portable_inputs_and_accounting(
    tmp_path,
):
    """A fresh GPT call follows a failed Claude fixture within the same
    deadline.
    """
    ledger = _ledger(tmp_path)
    ledger.start()
    attempt = ledger.admit("claude", "claude")
    settings = config.Settings(
        profile="preferred", claude_model="claude-fixture"
    )
    fixture = providers.FixtureProvider(
        {"plan": [{"fixture_error": "quota"}, {"content": "Plan", "tasks": []}]}
    )
    runner = workflow.StageRunner(
        settings,
        fixture,
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "sources"),
            settings,
            "fixed-corpus",
        ),
        ledger,
        attempt,
    )
    result = runner.run("plan", "plan", {"brief": "frozen"}, tmp_path)
    assert result["output"]["content"] == "Plan"
    assert [call.settings.provider for call in fixture.calls] == [
        "claude",
        "codex",
    ]
    first, fallback = [json.loads(call.prompt) for call in fixture.calls]
    assert first["messages"] == fallback["messages"]
    assert first["tools"] == fallback["tools"]
    assert fallback["remaining_calls"] == first["remaining_calls"] - 1
    data = artifacts.read(ledger.path)
    assert data["claude_disabled"]
    assert [x["status"] for x in data["invocations"]] == ["failed", "complete"]


def test_process_timeout_preserves_raw_and_terminates_children(tmp_path):
    """Deadline kills a process group and retains partial observable output."""
    code = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(60)']); "
        "print(p.pid,flush=True); time.sleep(60)"
    )
    request = providers.Request(
        "test",
        "",
        config.ModelSettings("codex", config.REHEARSAL_MODEL),
        tmp_path,
        0.3,
    )
    with pytest.raises(providers.ProviderError, match="deadline"):
        providers.execute([sys.executable, "-c", code], request)
    pid = int((tmp_path / "raw.jsonl").read_text().strip())
    status = pathlib.Path(f"/proc/{pid}/status")
    # A killed grandchild can remain a zombie briefly until init reaps it.
    try:
        state = status.read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return  # Already reaped, including during the read.
    assert "State:\tZ" in state
    assert (tmp_path / "events.jsonl").exists()
