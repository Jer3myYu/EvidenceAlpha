"""One attempt as an SDK session: admission, failures, success."""

import asyncio
import functools
import threading
import time

import claude_agent_sdk
import mcp.types
import pytest
import test_industry_graph as fakes
from langgraph.checkpoint.memory import MemorySaver

from industry import budget
from industry import graph as graph_module
from industry import records
from industry import snapshots
from industry import tools
from industry import worker
from research import persist
from research import web

NOW = "2026-09-07T00:00:00+00:00"


class Backend:
    """A backend the fake session never reaches."""

    def search_web(self, query, max_results):
        del query, max_results
        return [web.WebResult(title="t", url="https://a.example/", snippet="s")]

    def fetch(self, url, source_id):
        raise AssertionError("not called")

    def index(self, version, canonical_url, chunks):
        raise AssertionError("not called")

    def search_documents(self, query, k, source_url):
        raise AssertionError("not called")


def work_input(kind="research", role="industry", references=()):
    attempt = records.Attempt(
        id="T2.1",
        task_id="T2",
        reserved=records.Reservation(turns=12, tool_calls=24, seconds=5),
        started_at=NOW,
    )
    task = records.Task(
        id="T2",
        kind=kind,
        role=role,
        objective="Map the upstream",
        scope="blanks",
    )
    return records.WorkerInput(
        thread_id="t",
        attempt=attempt,
        task=task,
        brief=records.Brief(
            industry="光掩模", constraints=["no price targets"]
        ),
        language="zh",
        references=list(references),
        allowance=records.Reservation(turns=12, tool_calls=24, seconds=5),
        model="claude-sonnet-5",
        prompt_version="10.2",
    )


def result_message(**overrides):
    fields = {
        "subtype": "success",
        "duration_ms": 10,
        "duration_api_ms": 5,
        "is_error": False,
        "num_turns": 3,
        "session_id": "s",
        "total_cost_usd": 0.01,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "result": "{}",
        "structured_output": {
            "summary": "done",
            "findings": [
                {
                    "statement": "HOYA supplies blanks",
                    "evidence_refs": ["E1"],
                    "material": True,
                    "questions": [3],
                    "topics": ["boundary"],
                }
            ],
            "gaps": ["no pricing"],
        },
    }
    fields.update(overrides)
    return claude_agent_sdk.ResultMessage(**fields)


def fake_query(messages, delay=0.0, raise_error=None):
    captured = {}

    async def query(prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        if raise_error is not None:
            raise raise_error
        for message in messages:
            if delay:
                await asyncio.sleep(delay)
            yield message

    return query, captured


def runtime_with_admission(admit=True):
    runtime = budget.Runtime(records.Limits())
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    if admit:
        meter.register("T2.1", 24)
    return runtime


def run(work, query, runtime):
    return asyncio.run(
        worker.run_attempt(work, runtime, Backend(), query=query)
    )


def test_unadmitted_attempt_does_no_work():
    query, captured = fake_query([result_message()])
    out = run(work_input(), query, runtime_with_admission(admit=False))
    assert out.status == "unknown" and out.usage.unknown
    assert "not admitted" in out.error and not captured
    out = run(work_input(), query, budget.Runtime())  # no meter at all
    assert out.status == "unknown" and not captured


def test_success_builds_the_session_and_result():
    reference = records.Reference(
        evidence=records.Evidence(
            id="E9",
            source_id="S4",
            source_version_id="v4",
            excerpt="Prior passage",
            locator="p2",
            kind="passage",
            extraction="html_text",
            task_id="T1",
            retrieved_at=NOW,
        ),
        source_title="Earlier report",
        source_url="https://earlier.example/report",
        version_date="2026-09-01",
    )
    assistant = claude_agent_sdk.AssistantMessage(
        content=[
            claude_agent_sdk.ToolUseBlock(
                id="1", name="mcp__research__search_web", input={"query": "q"}
            )
        ],
        model="claude-sonnet-5",
    )
    query, captured = fake_query([assistant, assistant, result_message()])
    events = []
    work = work_input(references=[reference])
    out = asyncio.run(
        worker.run_attempt(
            work,
            runtime_with_admission(),
            Backend(),
            query=query,
            on_event=events.append,
        )
    )
    assert out.status == "done"
    assert out.findings[0].statement == "HOYA supplies blanks"
    assert out.gaps == ["no pricing"] and out.map is None
    # The reference became local evidence E1 with its own source.
    assert (
        out.evidence[0].id == "E1"
        and out.evidence[0].excerpt == "Prior passage"
    )
    assert out.sources[0].title == "Earlier report"
    assert out.sources[0].canonical_url == "https://earlier.example/report"
    assert out.usage.turns == 3 and out.usage.input_tokens == 100
    assert out.usage.cost_usd == 0.01 and not out.usage.unknown
    options = captured["options"]
    assert options.max_turns == 12 and options.model == "claude-sonnet-5"
    assert options.allowed_tools == [
        "mcp__research__search_web",
        "mcp__research__search_documents",
        "mcp__research__fetch_source",
    ]
    assert options.output_format["schema"]["title"] == "TaskOutput"
    assert options.setting_sources == []
    prompt = captured["prompt"]
    assert "Task T2 (research, role industry): Map the upstream" in prompt
    assert "[E1] Earlier report | p2 | 2026-09-01\nPrior passage" in prompt
    assert "at most 12 tool-using exchanges and 24 tool calls" in prompt
    assert "no price targets" in prompt
    assert events and all(e["attempt_id"] == "T2.1" for e in events)
    assert (
        events[0]["event"] == "tool_use" and events[0]["tool"] == "search_web"
    )


def test_map_task_prompts_for_a_map_and_fails_without_one():
    query, captured = fake_query([result_message()])
    out = run(work_input(kind="map"), query, runtime_with_admission())
    assert (
        out.status == "failed"
        and out.error == "schema: map task returned no map"
    )
    assert "initial industry map task" in captured["options"].system_prompt
    assert (
        "Focus: products, the value chain" in captured["options"].system_prompt
    )
    query, _ = fake_query(
        [
            result_message(
                structured_output={
                    "summary": "m",
                    "map": {
                        "segments": [
                            {
                                "key": "u",
                                "name": "基板",
                                "stage": "upstream",
                                "description": "",
                                "evidence_refs": ["E1"],
                            }
                        ],
                        "boundary_note": "b",
                    },
                }
            )
        ]
    )
    out = run(work_input(kind="map"), query, runtime_with_admission())
    assert out.status == "done" and out.map.segments[0].name == "基板"


def test_transport_failure_is_unknown_usage_and_not_retried():
    query, captured = fake_query(
        [], raise_error=claude_agent_sdk.CLIConnectionError("gone")
    )
    out = run(work_input(), query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith(
        "transport: CLIConnectionError"
    )
    assert out.usage.unknown and out.usage.turns == 0
    assert "options" in captured  # exactly one session was started


def test_schema_failure_keeps_observed_usage():
    query, _ = fake_query(
        [
            result_message(
                is_error=True,
                structured_output=None,
                errors=["Failed to provide valid structured output"],
            )
        ]
    )
    out = run(work_input(), query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith("schema:")
    assert out.usage.turns == 3 and not out.usage.unknown
    query, _ = fake_query([result_message(structured_output={"summary": 1})])
    out = run(work_input(), query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith("schema:")


def test_timeout_ends_the_attempt():
    assistant = claude_agent_sdk.AssistantMessage(
        content=[claude_agent_sdk.TextBlock(text="thinking")], model="m"
    )
    query, _ = fake_query([assistant, assistant, result_message()], delay=3)
    work = work_input()
    work = work.model_copy(
        update={
            "allowance": records.Reservation(
                turns=12, tool_calls=24, seconds=0.5
            )
        }
    )
    out = run(work, query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith(
        "timeout: no result within 0 s"
    )
    assert out.usage.unknown  # no turn was observed before the deadline


def test_role_focus_and_language_in_prompts():
    query, captured = fake_query([result_message()])
    run(work_input(role="company"), query, runtime_with_admission())
    assert "comparable business profiles" in captured["options"].system_prompt
    assert "Language of statements: zh" in captured["prompt"]
    with pytest.raises(KeyError):
        worker.system_prompt(
            work_input().model_copy(
                update={
                    "task": work_input().task.model_copy(
                        update={"role": "nobody"}
                    )
                }
            )
        )


def test_timeout_after_partial_output_is_unknown_usage():
    assistant = claude_agent_sdk.AssistantMessage(
        content=[claude_agent_sdk.TextBlock(text="partial")], model="m"
    )
    query, _ = fake_query([assistant, result_message()], delay=1.0)
    work = work_input().model_copy(
        update={
            "allowance": records.Reservation(
                turns=12, tool_calls=24, seconds=1.5
            )
        }
    )
    out = run(work, query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith("timeout")
    assert out.usage.unknown, "an assistant message is not authoritative usage"
    charged = budget.attempt_charge(
        work.attempt.model_copy(
            update={"status": "failed", "observed": out.usage}
        )
    )
    assert charged.turns == 12 and charged.unknown


def test_reference_version_is_registered_in_the_collector():
    version = records.SourceVersion(
        id="v4",
        source_id="S4",
        content_hash="h",
        blob_path="b",
        meta_path="m",
        final_url="u",
        content_type="text/html",
        size=1,
        retrieved_at=NOW,
        extraction_version="v2",
    )
    layout = records.TableLayout(
        cells=[records.TableCell(text="Prior", row=0, col=0, start=8, end=13)]
    )
    reference = records.Reference(
        evidence=records.Evidence(
            id="E9",
            source_id="S4",
            source_version_id="v4",
            excerpt="[table]\nPrior",
            locator="p2",
            kind="table",
            extraction="html_text",
            task_id="T1",
            retrieved_at=NOW,
            table=layout,
        ),
        source_title="Earlier report",
        source_url="https://earlier.example/report",
        version=version,
    )
    query, _ = fake_query([result_message()])
    out = run(
        work_input(references=[reference]), query, runtime_with_admission()
    )
    assert out.source_versions[0].id == "v4"
    assert out.source_versions[0].source_id == out.sources[0].id
    # A copied reference keeps the layout the extractor recorded.
    assert out.evidence[0].table == layout


def test_result_error_is_classified_and_its_usage_recovered():
    exhausted = claude_agent_sdk.ResultError(
        "Failed to provide valid structured output after 5 attempts",
        data={
            "subtype": "error_during_execution",
            "num_turns": 13,
            "usage": {"input_tokens": 9, "output_tokens": 4},
            "total_cost_usd": 0.2,
        },
        exit_code=1,
    )
    label, usage = worker.classify_result_error(exhausted)
    assert label.startswith("schema:") and usage.turns == 13
    api_error = claude_agent_sdk.ResultError(
        "overloaded",
        data={
            "subtype": "error",
            "terminal_reason": "api_error",
            "num_turns": 2,
        },
        exit_code=1,
    )
    label, usage = worker.classify_result_error(api_error)
    assert label.startswith("transport:") and usage.turns == 2
    query, _ = fake_query([], raise_error=exhausted)
    out = run(work_input(), query, runtime_with_admission())
    assert out.status == "failed" and out.error.startswith(
        "schema: ResultError"
    )
    assert out.usage.turns == 13 and not out.usage.unknown


def test_sdk_max_turns_is_the_session_cap_not_the_reservation():
    work = work_input()
    work = work.model_copy(
        update={
            "allowance": records.Reservation(
                turns=34, tool_calls=24, seconds=5
            ),
            "max_turns": 12,
        }
    )
    options = worker.options_for(work, "system", object(), [])
    assert options.max_turns == 12
    assert "at most 12 tool-using exchanges" in worker.user_prompt(
        work, tools.Collector("T2.1", "T2")
    )


def test_waiting_for_a_session_slot_is_not_charged_as_execution():
    # C0 round 13, finding 4: the duration timer started before the
    # semaphore, so a queued attempt was charged its wait.
    runtime = budget.Runtime(records.Limits(concurrency=1))
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    meter.register("T2.1", 24)
    meter.register("T2.2", 24)
    delay = 0.3

    async def go():
        runs = []
        for aid in ("T2.1", "T2.2"):
            work = work_input()
            work = work.model_copy(
                update={"attempt": work.attempt.model_copy(update={"id": aid})}
            )
            query, _ = fake_query([result_message()], delay=delay)
            runs.append(
                worker.run_attempt(work, runtime, Backend(), query=query)
            )
        return await asyncio.gather(*runs)

    started = time.monotonic()
    first, second = asyncio.run(go())
    elapsed = time.monotonic() - started
    assert elapsed >= 2 * delay  # one slot: they really ran in sequence
    assert first.status == "done" and second.status == "done"
    for out in (first, second):
        assert delay <= out.usage.duration_s < 2 * delay


def test_no_more_sessions_run_at_once_than_the_limit_allows():
    # The brief's bound is two concurrent tool-using SDK sessions. The
    # suite proved one slot serializes two attempts; this proves the
    # bound itself holds when a wave is larger than it.
    limits = records.Limits(concurrency=2)
    runtime = budget.Runtime(limits)
    attempt_ids = [f"T2.{n}" for n in range(1, 6)]
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    for attempt_id in attempt_ids:
        meter.register(attempt_id, 24)
    live = 0
    peak = 0

    def counting_query(prompt, options):
        del prompt, options

        async def messages():
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            try:
                await asyncio.sleep(0.05)
                yield result_message()
            finally:
                live -= 1

        return messages()

    async def go():
        runs = []
        for attempt_id in attempt_ids:
            work = work_input()
            work = work.model_copy(
                update={
                    "attempt": work.attempt.model_copy(
                        update={"id": attempt_id}
                    )
                }
            )
            runs.append(
                worker.run_attempt(
                    work, runtime, Backend(), query=counting_query
                )
            )
        return await asyncio.gather(*runs)

    results = asyncio.run(go())
    assert [r.status for r in results] == ["done"] * len(attempt_ids)
    assert peak == limits.concurrency
    assert live == 0


class BlockingIndexBackend:
    """A backend whose index write blocks for a while, counted.

    ``durations`` are taken in order by the first writes; later writes
    block for ``seconds``.
    """

    def __init__(self, seconds, durations=()):
        self.seconds = seconds
        self.durations = list(durations)
        self.active = 0
        self.peak = 0
        self.writes = 0
        self._lock = threading.Lock()

    def search_web(self, query, max_results):
        raise AssertionError("not called")

    def fetch(self, url, source_id):
        version = records.SourceVersion(
            id="v1",
            source_id=source_id,
            content_hash="h",
            blob_path="b.html",
            meta_path="m",
            final_url=url,
            content_type="text/html",
            size=10,
            retrieved_at=NOW,
            extraction_version="v3",
        )
        chunks = [
            snapshots.Chunk(
                0, "HOYA supplies blanks.", "Market", None, "text", ()
            )
        ]
        return version, chunks, url

    def index(self, version, canonical_url, chunks):
        del version, canonical_url
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.writes += 1
            seconds = self.durations.pop(0) if self.durations else self.seconds
        time.sleep(seconds)
        with self._lock:
            self.active -= 1
        return len(chunks)

    def search_documents(self, query, k, source_url):
        del query, k, source_url
        return []


def fetching_query(prompt, options):
    """A session that calls fetch_source through the attempt's MCP server."""
    del prompt

    async def messages():
        server = options.mcp_servers["research"]["instance"]
        handler = server.request_handlers[mcp.types.CallToolRequest]
        await handler(
            mcp.types.CallToolRequest(
                method="tools/call",
                params=mcp.types.CallToolRequestParams(
                    name="fetch_source",
                    arguments={"url": "https://a.example/x"},
                ),
            )
        )
        yield result_message()

    return messages()


def attempt_with(aid, seconds):
    work = work_input()
    return work.model_copy(
        update={
            "attempt": work.attempt.model_copy(update={"id": aid}),
            "allowance": records.Reservation(
                turns=12, tool_calls=24, seconds=seconds
            ),
        }
    )


def test_a_timed_out_attempt_owns_its_index_write_until_it_ends():
    # C2 round 1, finding 2: cancelling the await of the index thread
    # did not stop the thread, yet the handler released the index lock
    # and the worker released the slot and reported its duration; the
    # retry then wrote to the index beside the write still running.
    runtime = budget.Runtime(records.Limits(concurrency=1))
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    meter.register("T2.1", 24)
    meter.register("T2.2", 24)
    backend = BlockingIndexBackend(0.6)

    async def go():
        first = await worker.run_attempt(
            attempt_with("T2.1", 0.15), runtime, backend, query=fetching_query
        )
        assert backend.active == 0, "returned while its write ran"
        second = await worker.run_attempt(
            attempt_with("T2.2", 5), runtime, backend, query=fetching_query
        )
        return first, second

    first, second = asyncio.run(go())
    assert first.status == "failed" and first.error.startswith("timeout")
    assert second.status == "done"
    assert backend.peak == 1, "two index writes ran at once"
    assert first.usage.duration_s >= 0.6, "the write outlived the charge"
    assert not runtime.index_lock.locked()


def test_a_write_that_outlives_the_grace_stops_the_run_resumably():
    runtime = budget.Runtime(records.Limits(concurrency=1))
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    meter.register("T2.1", 24)
    backend = BlockingIndexBackend(0.8)

    async def go():
        with pytest.raises(worker.WorkerHung, match="still running"):
            await worker.run_attempt(
                attempt_with("T2.1", 0.1),
                runtime,
                backend,
                query=fetching_query,
                grace=0.2,
            )
        # No result was reported and the write is still serialized:
        # the lock is held until the thread ends.
        assert backend.active == 1 and runtime.index_lock.locked()
        while backend.active:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)
        assert not runtime.index_lock.locked()

    asyncio.run(go())


def test_an_interrupted_attempt_waits_for_its_write():
    runtime = budget.Runtime(records.Limits(concurrency=1))
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    meter.register("T2.1", 24)
    backend = BlockingIndexBackend(0.5)

    async def go():
        task = asyncio.create_task(
            worker.run_attempt(
                attempt_with("T2.1", 5), runtime, backend, query=fetching_query
            )
        )
        while not backend.writes:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The interruption went on only once the write had ended.
        assert backend.active == 0 and backend.writes == 1
        assert not runtime.index_lock.locked()
        assert not runtime.admission.live(), "the slot outlived the work"

    asyncio.run(go())


def test_the_run_never_delivers_over_a_surviving_write(tmp_path):
    # Through the compiled graph with the real worker and tools: every
    # attempt times out inside its index write, is retried once, and
    # the run delivers incomplete, never while a write is running and
    # never with a write uncharged.
    limits = records.Limits(concurrency=1, task_timeout_s=0.15)
    runtime = budget.Runtime(limits, reports_dir=str(tmp_path / "reports"))
    backend = BlockingIndexBackend(0.4)
    compiled = graph_module.build_graph(
        runtime,
        backend=backend,
        api=fakes.FakeRoles(),
        worker_fn=functools.partial(worker.run_attempt, query=fetching_query),
        checkpointer=MemorySaver(),
    )

    async def go():
        config = persist.thread_config("write-1")
        runtime.begin("write-1")
        return await compiled.ainvoke(
            graph_module.initial_state("q", limits), config
        )

    state = asyncio.run(go())
    assert state["meta"].execution_status == "completed"
    assert backend.active == 0, "delivered over a surviving write"
    assert backend.peak == 1, "two index writes ran at once"
    assert backend.writes >= 2
    assert all(a.status == "failed" for a in state["attempts"].values())
    assert budget.ledger(state).wall_clock_s >= backend.writes * 0.4
