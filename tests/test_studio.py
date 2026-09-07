"""Studio tests: events, context windows, live-versus-replay agreement.

No model calls and no server: the industry graph runs with fake roles
and a fake worker on an in-memory checkpointer, the legacy replay reads
the real fixture thread, and the crew framing is captured from a real
CrewAI crew with a fake LLM.
"""

import asyncio
import pathlib
from typing import Any

import crewai
import pydantic
import studio
from langgraph.checkpoint.memory import MemorySaver

import test_industry_graph as fakes
from industry import budget
from industry import graph as graph_module
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
