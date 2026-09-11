"""Regression checks for queued deadlines, SDK events and versioned caches."""

import dataclasses
import json
import pathlib
import sys
import threading
import time
import types
from unittest import mock

import claude_agent_sdk
import jsonschema
import numpy
import pytest

from evidencealpha import claude_runner
from evidencealpha import cli
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import protocol
from evidencealpha import workflow
from evidencealpha import tools

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures" / "redesign"


@pytest.mark.parametrize("fake_clock", [True, False])
def test_research_queue_shares_deadline_and_writer_runs(tmp_path, fake_clock):
    """Queued tasks cannot spend a fresh phase; active calls share its end."""
    brief, fixture, sources = cli.fixture(FIXTURES / "service.json")
    fixture.outputs["plan"]["tasks"] = [
        {"role": "company", "question": str(index)} for index in range(5)
    ]
    clock = [100.0]
    active = threading.Barrier(2)
    limits = []
    started = time.monotonic()
    original = fixture.run

    def respond(request):
        if request.stage.startswith("research-"):
            limits.append(request.seconds)
            if fake_clock:
                clock[0] += request.seconds
            else:
                active.wait(timeout=2)
                time.sleep(request.seconds)
            raise providers.ProviderError("Provider deadline expired")
        return original(request)

    fixture.run = respond
    settings = dataclasses.replace(
        config.Settings(),
        workers=1 if fake_clock else 2,
        stage_allocations=(120, 0.12, 480, 240, 120, 120),
    )
    with mock.patch.object(
        workflow.time,
        "monotonic",
        side_effect=(lambda: clock[0]) if fake_clock else time.monotonic,
    ):
        result = workflow.run(
            brief, settings, fixture, sources, tmp_path / "run"
        )
    assert result["status"] == "reviewed"
    assert len(limits) == (1 if fake_clock else 2)
    assert max(limits) <= 0.12 + 1e-9
    assert len(result["research_gaps"]) == 5
    assert any(call.stage == "synthesis" for call in fixture.calls)
    if not fake_clock:
        assert time.monotonic() - started < 5


@pytest.mark.parametrize(
    "status,window,exhausted",
    [
        ("rejected", "five_hour", True),
        ("rejected", "seven_day", True),
        ("allowed_warning", "five_hour", False),
        ("rejected", None, False),
    ],
)
def test_sdk_quota_event_crosses_runner_adapter_boundary(
    tmp_path,
    status,
    window,
    exhausted,
):
    """Real SDK dataclasses serialize to the adapter's exact input schema."""
    event = claude_agent_sdk.RateLimitEvent(
        rate_limit_info=claude_agent_sdk.RateLimitInfo(
            status=status,
            rate_limit_type=window,
        ),
        uuid="test",
        session_id="test",
    )
    wire = json.loads(json.dumps(claude_runner.normalize(event)))
    wire.append(
        {
            "kind": "result",
            "is_error": True,
            "subtype": "error",
            "usage": {"output_tokens": 7},
        }
    )
    request = providers.Request(
        "plan",
        "test",
        config.ModelSettings("claude", "claude-fixture"),
        tmp_path,
        1,
    )
    with mock.patch.object(providers, "execute", return_value=(wire, 1)):
        with pytest.raises(providers.ProviderError) as failure:
            providers.ClaudeProvider().run(request)
    assert isinstance(failure.value, providers.QuotaExhausted) == exhausted
    assert failure.value.usage == {"output_tokens": 7}


def test_source_cache_reads_original_once_and_detects_mutation(tmp_path):
    """Repeated chunks share validated bytes; changed originals fail closed."""
    store = documents.SourceStore(tmp_path / "corpus", 80)
    source = store.ingest(FIXTURES / "service.html")
    original = pathlib.Path.read_bytes
    reads = []

    def read(path):
        reads.append(path.name)
        return original(path)

    with mock.patch.object(pathlib.Path, "read_bytes", read):
        store.search_evidence("revenue")
        store.search_evidence("service")
    assert reads.count("original.html") == 1
    path = store.root / source["id"] / "original.html"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed in place"):
        store.search_evidence("service")


def test_embedding_index_is_reused_and_invalidated_by_new_source(tmp_path):
    """Only queries are embedded again until corpus membership changes."""
    store = documents.SourceStore(tmp_path / "corpus", 80)
    store.ingest(FIXTURES / "service.html")
    batches = []

    class Encoder:
        """Offline instrumented embedding boundary."""

        def encode(self, texts, **_kwargs):
            """Return deterministic vectors and retain invocation shapes."""
            batches.append(texts)
            return numpy.ones((len(texts), 2))

    constructor = mock.Mock(return_value=Encoder())
    module = types.SimpleNamespace(SentenceTransformer=constructor)
    with mock.patch.dict(sys.modules, {"sentence_transformers": module}):
        store.search_evidence("first", embedding_model="local-test")
        store.search_evidence("second", embedding_model="local-test")
        store.ingest(FIXTURES / "manufacturing.html")
        store.search_evidence("third", embedding_model="local-test")
    assert constructor.call_count == 1
    assert [len(batch) for batch in batches][1:3] == [1, 1]
    assert len(batches) == 5
    assert len(batches[3]) > len(batches[0])


def test_research_leaves_downstream_time_when_plan_is_slow(tmp_path):
    """A nearly spent plan cannot consume the reserved delivery interval."""
    brief, fixture, sources = cli.fixture(FIXTURES / "service.json")
    fixture.outputs["plan"]["tasks"] = [
        {"role": "company", "question": "Must expire before admission"}
    ]
    result = workflow.run(
        brief,
        config.Settings(),
        fixture,
        sources,
        tmp_path / "run",
        campaign_attempt={"deadline": time.time() + 1080},
    )
    assert result["status"] == "reviewed"
    assert result["research_phase"]["seconds"] == 0
    assert not any(c.stage.startswith("research-") for c in fixture.calls)


def test_slow_acquisition_is_killed_at_worker_deadline(tmp_path):
    """Socket retries/parsing cannot hold the worker past its deadline."""
    ledger = budget.Ledger(tmp_path / "budget.json")
    ledger.initialize()
    ledger.start()
    evidence = tools.EvidenceTools(
        documents.SourceStore(tmp_path / "sources"),
        config.Settings(),
        "live",
        ledger,
    )
    execute = providers.execute

    def slow_tool(command, request):
        del command
        return execute(
            [
                sys.executable,
                "-c",
                "import time; print('partial',flush=True); time.sleep(60)",
            ],
            request,
        )

    started = time.monotonic()
    with mock.patch.object(providers, "execute", slow_tool):
        with pytest.raises(providers.ProviderError, match="deadline"):
            evidence.call(
                "fetch_source",
                {"url": "https://example.org"},
                deadline=started + 0.3,
            )
    assert time.monotonic() - started < 2
    assert (
        next((tmp_path / "tools").glob("*/raw.jsonl")).read_text()
        == "partial\n"
    )


def test_html_crlf_is_reopened_without_changing_canonical_spans(tmp_path):
    """Real service HTML can contain embedded CRLF in paragraph text."""
    path = tmp_path / "source.html"
    path.write_bytes(b"<p>Annual\r\nRevenue 2025</p>")
    store = documents.SourceStore(tmp_path / "corpus")
    source = store.ingest(path)
    text = store.open_source(source["id"])["text"]
    assert "\r\n" in text
    passage = store.search_evidence("Revenue")[0]
    assert passage["text"] == "\n".join(
        text[s["start"] : s["end"]] for s in passage["spans"]
    )


def test_large_source_tool_requires_original_chunks_without_truncation(
    tmp_path,
):
    """Annual reports cannot silently overflow a model's portable transcript."""
    store = documents.SourceStore(tmp_path / "corpus", chunk_characters=80)
    source = store.ingest(FIXTURES / "service.html")
    settings = dataclasses.replace(config.Settings(), source_open_characters=40)
    evidence = tools.EvidenceTools(store, settings, "fixed-corpus")
    with pytest.raises(ValueError, match="No source text has been truncated"):
        evidence.call("open_source", {"source_id": source["id"]})
    result = evidence.call(
        "open_source", {"source_id": source["id"], "chunk_id": "c0"}
    )
    assert result == store.open_source(source["id"], "c0")


def test_strict_output_schema_preserves_roles_and_limits_tool_names():
    """Strict framing rejects malformed control shapes before dispatch."""
    schema = protocol.output_schema(("search_evidence", "open_source"))
    jsonschema.Draft202012Validator.check_schema(schema)
    envelope = {
        "content": "",
        "tool_calls": [],
        "tasks": [],
        "figures": [],
        "issues": [],
    }
    value = {
        **envelope,
        "tool_calls": [
            {"name": "search_evidence", "arguments": {"query": "original"}}
        ],
    }
    jsonschema.validate(value, schema)
    assert workflow.parse_output(json.dumps(value), "review") == value
    value["tool_calls"][0]["name"] = "search_web"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, schema)
    for path in FIXTURES.glob("*.json"):
        for output in json.loads(path.read_text())["outputs"].values():
            if isinstance(output, dict):
                jsonschema.validate(
                    {**envelope, **output}, protocol.output_schema()
                )
