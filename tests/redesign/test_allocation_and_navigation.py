"""Offline timing and source-navigation regressions; never model calls."""

import json
import sys
from unittest import mock

import pymupdf
import pytest

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow


@pytest.mark.parametrize(
    "writing_only,call_cap,expected",
    [(False, 300, 300), (False, 600, 580), (True, 300, 300), (True, 600, 600)],
)
def test_unused_research_time_is_available_to_writing(
    tmp_path, writing_only, call_cap, expected
):
    """A protected reserve is not a maximum for either entry path."""
    clock = [100.0]
    requests = []

    class ScriptedProvider:
        """Return evidence after twenty simulated seconds, then notes."""

        def run(self, request):
            """Record the actual deadline passed through the runner."""
            requests.append(request)
            if not writing_only and len(requests) == 1:
                clock[0] += 20
                return providers.Result(
                    json.dumps(
                        {
                            "tool_calls": [
                                {
                                    "name": "calculate",
                                    "arguments": {
                                        "operation": "add",
                                        "values": ["1", "2"],
                                    },
                                }
                            ]
                        }
                    )
                )
            assert request.allowed_tools == ()
            return providers.Result('{"content":"Completed notes."}')

    settings = config.Settings(tool_rounds=2, invocation_seconds=call_cap)
    runner = workflow.StageRunner(
        settings,
        ScriptedProvider(),
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        runner.run(
            "company",
            "company",
            {},
            tmp_path / "run",
            seconds=600,
            final_notes_only=writing_only,
        )
    assert requests[-1].seconds == expected
    assert requests[-1].seconds > settings.final_writing_reserve_seconds
    assert requests[-1].deadline <= 700


def test_slow_call_gets_allowance_and_preserves_final_writing(tmp_path):
    """A slow first call uses 250 seconds; it does not consume the reserve."""
    clock = [100.0]
    requests = []

    class SlowProvider:
        """Simulate latency without manufacturing a timeout."""

        def run(self, request):
            """Continue only while the assigned deadline permits it."""
            requests.append(request)
            if len(requests) == 1:
                assert request.seconds == 300
                clock[0] += 250
                return providers.Result(
                    json.dumps(
                        {
                            "tool_calls": [
                                {
                                    "name": "calculate",
                                    "arguments": {
                                        "operation": "add",
                                        "values": ["1", "2"],
                                    },
                                }
                            ]
                        }
                    )
                )
            assert request.allowed_tools == ()
            assert request.seconds == 300
            clock[0] += 200
            return providers.Result(
                '{"content":"Finished within worker budget."}'
            )

    settings = config.Settings()
    runner = workflow.StageRunner(
        settings,
        SlowProvider(),
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    with mock.patch.object(
        workflow.time, "monotonic", side_effect=lambda: clock[0]
    ):
        runner.run("industry", "industry", {}, tmp_path / "run", seconds=600)
    assert len(requests) == 2
    assert clock[0] == 550


@pytest.mark.parametrize("writing_only", [False, True])
def test_enclosing_deadline_overrides_both_entry_paths(tmp_path, writing_only):
    """Protected downstream time cannot be borrowed by writing."""
    settings = config.Settings()
    provider = providers.FixtureProvider(
        {"company": {"content": "Partial scope."}}
    )
    runner = workflow.StageRunner(
        settings,
        provider,
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
    )
    with mock.patch.object(workflow.time, "monotonic", return_value=100):
        runner.run(
            "company",
            "company",
            {},
            tmp_path / "run",
            seconds=600,
            deadline=250,
            final_notes_only=writing_only,
        )
    assert provider.calls[0].seconds == 150
    assert provider.calls[0].allowed_tools == ()
    assert provider.calls[0].deadline_limit == "enclosing_deadline"


def test_ledger_limit_is_recorded_and_timeout_is_terminal(tmp_path):
    """Aggregate budget wins over a longer worker/call allowance."""
    ledger = budget.Ledger(tmp_path / "ledger.json")
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("isolated")
    with ledger.locked() as data:
        data["invocations"].append(
            {
                "id": "prior",
                "status": "complete",
                "provider": "codex",
                "reserved_seconds": 7180,
                "seconds": 7180,
                "observable_tokens": 0,
            }
        )
    requests = []

    class TimeoutProvider:
        """Surface a simulated terminal operational timeout."""

        def run(self, request):
            """No subsequent provider call may be admitted."""
            requests.append(request)
            assert request.seconds == 20
            raise providers.ProviderTimeout(
                "Provider deadline expired",
                request.deadline,
                request.deadline_limit,
            )

    settings = config.Settings()
    runner = workflow.StageRunner(
        settings,
        TimeoutProvider(),
        tools.EvidenceTools(
            documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
        ),
        ledger,
        attempt,
    )
    with mock.patch.object(workflow.time, "monotonic", return_value=100):
        with pytest.raises(workflow.ResearchHandoffError):
            runner.run("company", "company", {}, tmp_path / "run", seconds=600)
    assert len(requests) == 1
    assert requests[0].deadline_limit == "aggregate_invocation"
    failure = next(
        (tmp_path / "run").glob("stages/company/*/call-0/failure.json")
    )
    assert artifacts.read(failure)["ended_by"] == "aggregate_invocation"


def test_silent_process_can_complete_within_allowance(tmp_path):
    """No streamed output is not itself a stall or a timeout."""
    request = providers.Request(
        "offline",
        "",
        config.ModelSettings("codex", config.RUNTIME_MODEL),
        tmp_path,
        3,
    )
    events, status = providers.execute(
        [sys.executable, "-c", "import time; time.sleep(0.05)"], request
    )
    assert not events
    assert status == 0
    completed = json.loads(
        (tmp_path / "events.jsonl").read_text().splitlines()[-1]
    )
    assert completed["ended_by"] == "exit"
    assert completed["seconds"] >= 0.05


@pytest.mark.parametrize("legacy_order", [False, True])
def test_heading_navigation_reaches_complete_table_without_mutation(
    tmp_path, legacy_order
):
    """Follow heading -> units -> table over new and old PDF block order."""
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Revenue and costs")
    page.insert_text((50, 80), "Units: USD")
    for x in (50, 200, 300):
        page.draw_line((x, 100), (x, 190))
    for y in (100, 130, 160, 190):
        page.draw_line((50, y), (300, y))
    for x, y, text in [
        (60, 120, "Item"),
        (210, 120, "Amount"),
        (60, 150, "Sales"),
        (210, 150, "123"),
        (60, 180, "Total"),
        (210, 180, "123"),
    ]:
        page.insert_text((x, y), text)
    original = tmp_path / "report.pdf"
    pdf.save(original)
    pdf.close()
    # Exercise the old storage order without altering production parsing.
    blocks, warnings = documents._blocks(  # pylint: disable=protected-access
        original.read_bytes(), ".pdf"
    )
    assert [b["kind"] for b in blocks] == ["paragraph", "paragraph", "table"]
    if legacy_order:
        blocks = [b for b in blocks if b["kind"] == "table"] + [
            b for b in blocks if b["kind"] != "table"
        ]
    store = documents.SourceStore(tmp_path / "corpus")
    with mock.patch.object(
        documents, "_blocks", return_value=(blocks, warnings)
    ):
        source = store.ingest(original)
    before = artifacts.tree_hash(store.root)
    sid = source["id"]
    heading = store.search_evidence("Revenue", source_id=sid)[0]["chunk_id"]
    first = store.surrounding_passages(sid, heading, 1)
    units = next(p["chunk_id"] for p in first if "Units" in p["text"])
    result = store.surrounding_passages(sid, units, 1)
    assert any("Total" in p["text"] and "123" in p["text"] for p in result)
    assert len(store.surrounding_passages(sid, units, 0)) == 1
    assert artifacts.tree_hash(store.root) == before
