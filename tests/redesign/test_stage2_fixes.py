"""Regression checks for queued deadlines, SDK events and versioned caches."""

import dataclasses
import json
import pathlib
import sys
import threading
import time
from unittest import mock

import claude_agent_sdk
import jsonschema
import pymupdf
import pytest

from evidencealpha import claude_runner
from evidencealpha import cli
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import protocol
from evidencealpha import render
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
                clock[0] = 100.12
            else:
                active.wait(timeout=2)
                time.sleep(0.12)
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


def test_retired_embedding_fusion_is_explicitly_rejected(tmp_path):
    """Historical vector-score addition cannot silently enter the new path."""
    store = documents.SourceStore(tmp_path / "corpus", 80)
    with pytest.raises(ValueError, match="Embedding fusion"):
        store.search_evidence("query", embedding_model="local-test")


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
    assert documents.ungroup_passages(result)[0] == store.concise_passage(
        store.open_source(source["id"], "c0")
    )


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
        "coverage_updates": [],
        "stop_reason": None,
    }
    value = {
        **envelope,
        "tool_calls": [
            {
                "name": "search_evidence",
                "arguments": {
                    "query": "original",
                    "source_id": None,
                    "question_id": None,
                },
            }
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


def test_source_scope_excludes_competing_documents_before_top_k(tmp_path):
    """Source targeting cannot silently mix another issuer's matching rows."""
    store = documents.SourceStore(tmp_path / "corpus")
    first = tmp_path / "first.txt"
    first.write_text("revenue revenue revenue 2025")
    target = tmp_path / "target.txt"
    target.write_text("revenue 2024")
    store.ingest(first)
    source = store.ingest(target)
    evidence = tools.EvidenceTools(
        store,
        config.Settings(retrieval_mode="degraded_lexical"),
        "fixed-corpus",
    )
    explicit = evidence.call(
        "search_evidence", {"query": "revenue 2025", "source_id": source["id"]}
    )
    source_id = source["id"]
    inline = evidence.call(
        "search_evidence", {"query": f"source_id:{source_id} revenue 2025"}
    )
    assert explicit == inline
    assert {p["source_id"] for p in documents.ungroup_passages(explicit)} == {
        source["id"]
    }
    assert documents.ungroup_passages(explicit)[0]["text"] == "revenue 2024"


def test_last_round_returns_notes_instead_of_discarding_research(tmp_path):
    """A tool-heavy worker gets a final synthesis call within its round cap."""
    output = {
        "content": "Evidence gathered; unresolved coverage is explicit.",
        "tool_calls": [],
        "tasks": [],
        "figures": [],
        "issues": [],
        "coverage_updates": [],
        "stop_reason": None,
    }
    tool_output = {
        **output,
        "tool_calls": [
            {
                "name": "calculate",
                "arguments": {"operation": "add", "values": ["1", "2"]},
            }
        ],
    }
    provider = providers.FixtureProvider({"company": [tool_output, output]})
    settings = dataclasses.replace(config.Settings(), tool_rounds=2)
    evidence = tools.EvidenceTools(
        documents.SourceStore(tmp_path / "corpus"), settings, "fixed-corpus"
    )
    result = workflow.StageRunner(settings, provider, evidence).run(
        "company", "company", {}, tmp_path / "run"
    )
    assert result["output"] == output
    assert len(provider.calls) == 2
    last = provider.calls[-1]
    prompt = json.loads(last.prompt)
    assert prompt["remaining_calls"] == 1
    assert prompt["tools"] == {}
    assert last.allowed_tools == ()
    schema = protocol.output_schema(last.allowed_tools)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(output, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(tool_output, schema)


def test_source_inventory_carries_original_identifying_passage(tmp_path):
    """Workers see source identity evidence rather than anonymous hashes."""
    brief, provider, sources = cli.fixture(FIXTURES / "service.json")
    root = tmp_path / "run"
    workflow.run(brief, config.Settings(), provider, sources, root)
    request = next(c for c in provider.calls if c.stage == "plan")
    portable = json.loads(json.loads(request.prompt)["messages"][1]["content"])
    store = documents.SourceStore(root / "sources")
    for item in portable["sources"]:
        passage = item["identifying_passage"]
        assert passage == store.concise_passage(
            store.open_source(item["source_id"], passage["chunk_id"])
        )
        assert passage["spans"]
        assert "identifying aid" in request.prompt


def test_tall_figure_and_long_table_source_survive_pdf_layout(tmp_path):
    """Figures cannot collapse into the page remainder; hashes must wrap."""
    nodes = [f"Research stage {i}" for i in range(6)]
    render.figures(
        [
            {
                "kind": "diagram",
                "title": "Stages",
                "caption": "Stages in order",
                "source_ids": ["source"],
                "period": "fixture",
                "unit": "stage",
                "caveats": "Synthetic",
                "nodes": nodes,
                "edges": list(zip(nodes, nodes[1:])),
            }
        ],
        tmp_path,
        {"source"},
    )
    source_hash = "abcdef0123456789" * 4
    report = tmp_path / "report.md"
    report.write_text(
        ("Paragraph of introductory context.\n\n" * 24)
        + "![Stages](figures/figure-1.png)\n\n"
        + "| Company | Amount | Evidence |\n|---|---|---|\n"
        + f"| Example company | 123.45 | Original {source_hash} |\n"
    )
    result = render.export(report)
    assert result["pdf_status"] == "complete"
    with pymupdf.open(result["pdf"]) as pdf:
        images = [i for page in pdf for i in page.get_image_info()]
        assert len(images) == 1
        rect = pymupdf.Rect(images[0]["bbox"])
        assert rect.width > 80
        assert rect.height > 300
