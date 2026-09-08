"""Studio tests: events, context windows, live-versus-replay agreement.

No model calls and no server: the industry graph runs with fake roles
and a fake worker on an in-memory checkpointer, the legacy replay reads
the real fixture thread, and the crew framing is captured from a real
CrewAI crew with a fake LLM.
"""

import asyncio
import json
import pathlib
from typing import Any

import crewai
import pydantic
import pytest
import studio
from langgraph.checkpoint.memory import MemorySaver

import test_industry_graph as fakes
from industry import budget
from industry import graph as graph_module
from industry import merge
from industry import quantities
from industry import records
from industry import roles
from industry import state as state_module
from research import crew
from research import persist
from research import workflow

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legacy_thread.db"


def run(coroutine):
    return asyncio.run(coroutine)


def make(tmp_path, saver=None):
    runtime = budget.Runtime(records.Limits(), reports_dir=str(tmp_path))
    api = fakes.FakeRoles()
    worker = fakes.FakeWorker()
    graph = graph_module.build_graph(
        runtime,
        backend=object(),
        api=api,
        worker_fn=worker,
        checkpointer=saver or MemorySaver(),
    )
    return runtime, graph


def test_encode_turns_records_into_json_data():
    brief = roles.default_brief("q")
    encoded = studio.encode({"brief": brief, "items": (1, "a"), "n": 2})
    assert encoded["brief"]["industry"] == "q" and encoded["items"] == [1, "a"]


def test_live_run_streams_attempt_events_and_nodes(tmp_path):
    runtime, graph = make(tmp_path)
    events = run(collect(studio.run(graph, runtime, "光掩模产业调研", "t1")))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "thread" and kinds[-1] == "end"
    nodes = [e for e in events if e["type"] == "node"]
    names = [e["node"] for e in nodes]
    assert names[:4] == ["reserve_scope", "scope", "dispatch", "run_task"]
    assert names[-1] == "deliver"
    attempts = [e for e in nodes if e["node"] == "run_task"]
    assert [e["attempt_id"] for e in attempts] == ["T1.1", "T2.1", "T3.1"]
    for event in nodes:
        assert "budget" in event and "limits" in event["budget"]
        assert isinstance(event["trace"], list)
    scope = nodes[1]
    assert scope["context"]["who"].startswith("Research lead")
    assert scope["context"]["reconstructed"] is True
    assert "光掩模产业调研" in scope["context"]["user"]
    assert scope["context"]["schema"]["title"] == "BriefOutput"
    attempt = attempts[1]
    assert attempt["context"]["who"].endswith("(Claude Agent SDK tool loop)")
    assert "Task T2" in attempt["context"]["user"]
    assert attempt["context"]["tools"] == list(studio.tools.TOOL_NAMES)
    dispatch = nodes[2]
    assert dispatch["context"]["who"] == studio.DETERMINISTIC
    deliver = nodes[-1]
    assert deliver["update"]["meta"]["report_status"] == "complete"
    assert deliver["budget"]["task_executions"] == 3


async def collect(stream):
    return [event async for event in stream]


def test_replay_rebuilds_the_same_events_as_the_live_run(tmp_path):
    saver = MemorySaver()
    runtime, graph = make(tmp_path, saver)
    live = run(collect(studio.run(graph, runtime, "光掩模产业调研", "t2")))
    live_nodes = [e for e in live if e["type"] == "node"]
    replay = run(studio.replay_industry(graph, "t2", runtime.limits))
    assert replay["version"] == state_module.WORKFLOW_VERSION
    assert replay["completed"] and replay["report_status"] == "complete"
    replayed = [e for e in replay["events"] if e["type"] == "node"]
    assert [e["node"] for e in replayed] == [e["node"] for e in live_nodes]
    for a, b in zip(live_nodes, replayed):
        assert a["attempt_id"] == b["attempt_id"]
        assert a["context"].get("user") == b["context"].get("user")
        assert a["state"] == b["state"]
    workers = [e for e in replayed if e["node"] == "run_task"]
    assert workers, "the replay shows tool-using attempts"
    for event in workers:
        # The session cap and the ledger reservation are shown apart.
        assert event["context"]["max_turns"] == runtime.limits.max_turns
        assert (
            event["context"]["reserved_turns"] == runtime.limits.attempt_turns()
        )


def test_legacy_thread_replays_read_only():
    async def scenario():
        async with persist.open_checkpointer(str(FIXTURE)) as saver:
            graph = workflow.build_graph(checkpointer=saver)
            snapshot = await persist.load_state(graph, "b29768d7")
            assert persist.thread_version(snapshot) is None
            return await studio.replay_legacy(saver, "b29768d7")

    payload = run(scenario())
    assert payload["version"] == "legacy" and payload["question"]
    nodes = [e["node"] for e in payload["events"]]
    assert nodes[0] == "plan" and "research" in nodes
    first = payload["events"][0]
    assert first["legacy"] is True
    assert first["context"]["who"].startswith("legacy thread")
    assert "research_plan" in first["state"]


def test_replay_of_an_unknown_thread_fails_clearly(tmp_path):
    runtime, graph = make(tmp_path)

    async def scenario():
        async with persist.open_checkpointer(str(FIXTURE)) as saver:
            try:
                await studio.replay_legacy(saver, "nope")
            except LookupError as error:
                return str(error)
        return None

    assert "nope" in run(scenario())
    assert (
        run(studio.replay_industry(graph, "missing", runtime.limits))["events"]
        == []
    )


class RecordingLLM(crewai.BaseLLM):
    """Returns a canned model and records what CrewAI sent."""

    def __init__(self, output: type[pydantic.BaseModel]):
        super().__init__(model="fake")
        self.output = output
        self.messages: list[Any] = []

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        del tools, callbacks, available_functions, from_task, from_agent
        self.messages.append(messages)
        return self.output.model_validate(
            {"coverage": [], "beginner_usefulness": "", "missing": []}
        )

    def supports_stop_words(self):
        return False

    def get_context_window_size(self):
        return 100_000


def test_role_context_matches_what_crewai_really_sends():
    state = {
        "brief": roles.default_brief("q"),
        "claims": {},
        "map": records.IndustryMap(),
    }
    context = studio.role_context("assess_coverage", state, records.Limits())
    llm = RecordingLLM(records.LeadAssessment)
    run(
        crew.run_task(
            roles.ROLE_FOR["assess_coverage"],
            roles.coverage_description(state),
            roles.EXPECTED["assess_coverage"],
            llm,
        )
    )
    system, user = crew.split_messages(llm.messages[0])
    assert system == context["system"]
    assert user == context["user"]


def test_sse_frames_one_event_per_message():
    assert studio.sse({"type": "end"}) == 'data: {"type": "end"}\n\n'


SCHEMA2 = (
    pathlib.Path(__file__).parent / "fixtures" / "phase10_schema2_thread.db"
)


def test_a_thread_of_another_record_schema_replays_as_recorded(monkeypatch):
    # No stored data becomes unreadable (plan revision 22 §4.28): a
    # Phase 10 thread written under schema 2, whose RunMeta and records
    # come back as raw mappings, is listed under its own workflow and
    # schema and replayed as history -- without admission, arithmetic,
    # citability or a rebuilt context window.
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("history is never re-interpreted")

    monkeypatch.setattr(merge, "citable", forbidden)
    monkeypatch.setattr(merge, "calculation_current", forbidden)
    monkeypatch.setattr(quantities, "admit", forbidden)
    monkeypatch.setattr(quantities, "verify_binding", forbidden)
    monkeypatch.setattr(studio, "context_for", forbidden)

    async def scenario():
        async with persist.open_checkpointer(str(SCHEMA2)) as saver:
            graph = graph_module.build_graph(
                budget.Runtime(records.Limits()),
                backend=object(),
                api=fakes.FakeRoles(),
                worker_fn=fakes.FakeWorker(),
                checkpointer=saver,
            )
            snapshot = await persist.load_state(graph, "d201db8c")
            assert persist.thread_version(snapshot) == (
                state_module.WORKFLOW_VERSION
            )
            assert persist.recorded_meta(snapshot.values, "schema_version") == 2
            assert isinstance(snapshot.values["meta"], dict)
            with pytest.raises(persist.LegacyThreadError, match="schema 2"):
                await persist.load_industry_state(
                    graph, "d201db8c", state_module.WORKFLOW_VERSION
                )
            payload = await studio.replay_industry(
                graph, "d201db8c", studio.recorded_limits(snapshot.values), 2
            )
            summary = studio.thread_summary("d201db8c", "t", snapshot.values)
            return payload, summary

    payload, summary = run(scenario())
    assert payload["historical"] == 2 and payload["schema"] == 2
    assert payload["version"] == state_module.WORKFLOW_VERSION
    nodes = [e for e in payload["events"] if e["type"] == "node"]
    assert nodes, "the recorded checkpoints become events"
    for event in nodes:
        assert event["context"]["who"].startswith("historical thread")
        assert "record schema 2" in event["trace"][0]
        json.dumps(event)  # everything is encoded, mappings included
    assert summary["version"] == state_module.WORKFLOW_VERSION
    assert summary["schema"] == 2 and summary["thread_id"] == "d201db8c"


def test_a_second_live_run_is_refused_and_never_queued(tmp_path, monkeypatch):
    # The check read lock.locked() before the streaming body took the
    # lock, so two requests that arrived together both passed it and
    # the second waited for the first instead of being refused.
    runtime, graph = make(tmp_path)
    monkeypatch.setattr(studio.web, "api_key", lambda: "fake")

    class FakeRequest:
        """Only what run_question reads."""

        def __init__(self, app):
            self.query_params = {"question": "q"}
            self.app = app

    class App:
        pass

    app = App()
    app.state = App()
    app.state.graph = graph
    app.state.runtime = runtime
    app.state.lock = asyncio.Lock()

    async def both():
        first = await studio.run_question(FakeRequest(app))
        second = await studio.run_question(FakeRequest(app))
        # Both response bodies exist before either has been read: this
        # is the moment the old check had already run for both.
        started = aiter(first.body_iterator)
        opening = await anext(started)

        async def drain():
            return [frame async for frame in aiter(second.body_iterator)]

        # The refusal has to come back without the first run being
        # driven any further: a second run that merely waits for the
        # lock never answers here.
        queued = await asyncio.wait_for(drain(), 5)
        rest = [frame async for frame in started]
        return opening, queued, rest

    opening, queued, rest = run(both())
    assert json.loads(opening.split("data: ", 1)[1])["type"] == "thread"
    assert len(queued) == 1
    refusal = json.loads(queued[0].split("data: ", 1)[1])
    assert refusal == {"type": "error", "message": studio.BUSY}
    events = [json.loads(f.split("data: ", 1)[1]) for f in rest]
    assert not any(e["type"] == "error" for e in events)
    assert any(e.get("node") == "deliver" for e in events)
