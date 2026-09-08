"""Surviving work stays owned and admission-blocking until it ends.

C2 round 2, findings 1 and 2: admission ownership was split between
``crew.HUNG_CALLS`` (role calls only) and the runtime's semaphore
(worker sessions only), and neither survived coroutine unwinding, so a
retry, a same-runtime resume, the next Studio run and delivery could
all overtake an index write or a role call that was still running.
Every scenario here goes through a real entry point: the actual
worker and tool handler through the attempt's MCP server, the compiled
graph, ``scripts/industry_workflow.stream`` over SQLite, and
``studio.run_question``; only the SDK's session and the backend's
writes are replaced.

The regressions read the behaviour first (a session started over
surviving work, a report written over it) and the runtime's admission
record second, so on the previous candidate they fail on the behaviour.
"""

import asyncio
import functools
import threading
import time

import claude_agent_sdk
import industry_workflow
import mcp.types
import pytest
import studio
import test_industry_graph as fakes
import test_industry_sdk_children as sdk_tests
import test_industry_worker as worker_tests
from langgraph.checkpoint.memory import MemorySaver

from industry import budget
from industry import graph as graph_module
from industry import records
from industry import roles
from industry import sdk_children
from industry import state as state_module
from industry import worker
from research import crew
from research import persist
from research import web

STILL_LIVE = "still live"


ARGUMENTS = {
    "fetch_source": {"url": "https://a.example/x"},
    "search_web": {"query": "光掩模"},
}


def counting_query(backend, sessions, tools=()):
    """A session that makes one blocking tool call through the MCP server.

    The n-th session calls ``tools[n]`` (``fetch_source`` past the end)
    and notes how many of the backend's operations were active when it
    started: a session started over surviving work sees more than zero.
    """

    def query(prompt, options):
        del prompt

        async def messages():
            index = len(sessions)
            sessions.append(backend.active)
            name = tools[index] if index < len(tools) else "fetch_source"
            server = options.mcp_servers["research"]["instance"]
            handler = server.request_handlers[mcp.types.CallToolRequest]
            await handler(
                mcp.types.CallToolRequest(
                    method="tools/call",
                    params=mcp.types.CallToolRequestParams(
                        name=name, arguments=ARGUMENTS[name]
                    ),
                )
            )
            yield worker_tests.result_message()

        return messages()

    return query


class BlockingBackend(worker_tests.BlockingIndexBackend):
    """Index writes and web searches both block, counted together."""

    def __init__(self, seconds, durations=(), search_seconds=1.0):
        super().__init__(seconds, durations)
        self.search_seconds = search_seconds

    def search_web(self, query, max_results):
        del query, max_results
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.search_seconds)
        with self._lock:
            self.active -= 1
        return [web.WebResult(title="t", url="https://b.example/", snippet="s")]


def single_slot_runtime(*attempt_ids):
    runtime = budget.Runtime(records.Limits(concurrency=1))
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    for attempt_id in attempt_ids:
        meter.register(attempt_id, 24)
    return runtime


async def wait_for_write(backend):
    while not backend.writes:
        await asyncio.sleep(0.01)


async def wait_until_idle(backend):
    while backend.active:
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)  # the completion callbacks run on the loop


async def refused_then_admitted(runtime, backend, query, refused, admitted):
    """No session starts over the surviving write; one starts after it."""
    with pytest.raises(RuntimeError, match=STILL_LIVE):
        await worker.run_attempt(
            worker_tests.attempt_with(refused, 5), runtime, backend, query=query
        )
    await wait_until_idle(backend)
    assert not runtime.admission.live(), "the slot outlived the work"
    result = await worker.run_attempt(
        worker_tests.attempt_with(admitted, 5), runtime, backend, query=query
    )
    assert result.status == "done"


# --- the worker: every path out of the drain keeps the slot -------------


def test_an_interruption_during_the_ordinary_drain_keeps_the_slot():
    # C2 round 2, finding 1, path 1: the ordinary drain sat outside the
    # try, so a cancellation there escaped the handler, released the
    # slot, and a new session started over the write still running.
    runtime = single_slot_runtime("T2.1", "T2.2", "T2.3")
    backend = worker_tests.BlockingIndexBackend(1.0)
    sessions = []
    query = counting_query(backend, sessions)

    async def go():
        task = asyncio.create_task(
            worker.run_attempt(
                worker_tests.attempt_with("T2.1", 0.1),
                runtime,
                backend,
                query=query,
            )
        )
        await wait_for_write(backend)
        await asyncio.sleep(0.3)  # past the deadline: in the ordinary drain
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert backend.active == 1, "the scenario needs a surviving write"
        await refused_then_admitted(runtime, backend, query, "T2.2", "T2.3")

    asyncio.run(go())
    assert sessions == [0, 0], "a session started over the surviving write"


def test_a_second_interruption_during_the_drain_keeps_the_slot():
    # Path 2: a second cancellation interrupted the drain inside the
    # cancellation handler and left the slot free while the write ran.
    runtime = single_slot_runtime("T2.1", "T2.2", "T2.3")
    backend = worker_tests.BlockingIndexBackend(1.0)
    sessions = []
    query = counting_query(backend, sessions)

    async def go():
        task = asyncio.create_task(
            worker.run_attempt(
                worker_tests.attempt_with("T2.1", 5),
                runtime,
                backend,
                query=query,
            )
        )
        await wait_for_write(backend)
        task.cancel()  # the attempt drains, bounded by its grace
        await asyncio.sleep(0.2)
        started = time.monotonic()
        task.cancel()  # the second interruption cuts the drain short
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - started < 0.5, "the second cancel waited"
        assert backend.active == 1, "the scenario needs a surviving write"
        await refused_then_admitted(runtime, backend, query, "T2.2", "T2.3")

    asyncio.run(go())
    assert sessions == [0, 0], "a session started over the surviving write"


def test_a_write_that_outlives_the_interruption_grace_keeps_the_slot():
    # Path 3: the handler ignored drain's False return, so a write that
    # outlived the grace during an interruption was abandoned.
    runtime = single_slot_runtime("T2.1", "T2.2", "T2.3")
    backend = worker_tests.BlockingIndexBackend(1.0)
    sessions = []
    query = counting_query(backend, sessions)

    async def go():
        task = asyncio.create_task(
            worker.run_attempt(
                worker_tests.attempt_with("T2.1", 5),
                runtime,
                backend,
                query=query,
                grace=0.2,
            )
        )
        await wait_for_write(backend)
        started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The interruption went on after the grace, not after the write.
        assert 0.2 <= time.monotonic() - started < 0.8
        assert backend.active == 1, "the scenario needs a surviving write"
        await refused_then_admitted(runtime, backend, query, "T2.2", "T2.3")

    asyncio.run(go())
    assert sessions == [0, 0], "a session started over the surviving write"


def test_worker_hung_keeps_the_slot_until_the_work_ends():
    # Path 4: raising WorkerHung exited the semaphore block and released
    # the slot with no admission barrier while the work continued.
    runtime = single_slot_runtime("T2.1", "T2.2", "T2.3")
    backend = worker_tests.BlockingIndexBackend(1.0)
    sessions = []
    query = counting_query(backend, sessions)

    async def go():
        with pytest.raises(worker.WorkerHung):
            await worker.run_attempt(
                worker_tests.attempt_with("T2.1", 0.1),
                runtime,
                backend,
                query=query,
                grace=0.2,
            )
        assert backend.active == 1, "the scenario needs a surviving write"
        await refused_then_admitted(runtime, backend, query, "T2.2", "T2.3")

    asyncio.run(go())
    assert sessions == [0, 0], "a session started over the surviving write"


def test_a_queued_session_is_refused_when_the_slot_it_waits_for_survives():
    # A sibling waiting for the slot must not take the place of an
    # attempt whose work outlived its grace: it is woken and refused.
    runtime = single_slot_runtime("T2.1", "T2.2")
    backend = worker_tests.BlockingIndexBackend(1.0)
    sessions = []
    query = counting_query(backend, sessions)

    async def go():
        outcomes = await asyncio.gather(
            worker.run_attempt(
                worker_tests.attempt_with("T2.1", 0.1),
                runtime,
                backend,
                query=query,
                grace=0.2,
            ),
            worker.run_attempt(
                worker_tests.attempt_with("T2.2", 5),
                runtime,
                backend,
                query=query,
            ),
            return_exceptions=True,
        )
        assert sessions == [0], "the queued session started over the write"
        assert isinstance(outcomes[0], worker.WorkerHung)
        assert isinstance(outcomes[1], RuntimeError)
        assert STILL_LIVE in str(outcomes[1])
        await wait_until_idle(backend)
        assert not runtime.admission.live()

    asyncio.run(go())


# --- the compiled graph: siblings, retry, same-runtime resume ------------


def three_independent_tasks():
    api = fakes.FakeRoles()
    api.plans = [
        roles.TaskPlan(
            tasks=[
                roles.TaskSpec(key=key, role="industry", objective=key)
                for key in ("a", "b", "c")
            ]
        )
    ]
    return api


def test_a_hung_sibling_blocks_the_queued_session_and_the_resume(tmp_path):
    # C2 round 2, finding 1, the sibling case: at concurrency 2 one
    # worker raised WorkerHung, a queued third session started while
    # both operations were still running, and the sibling's drain was
    # cut short with its slot free. Then the same runtime resumed and
    # delivered over the surviving writes.
    limits = records.Limits(concurrency=2, task_timeout_s=0.15)
    runtime = budget.Runtime(limits, reports_dir=str(tmp_path / "reports"))
    # T1's write ends before its deadline; in the wave, one sibling's
    # index write and the other's web search outlive the grace (the
    # index lock would keep a second write from starting at all);
    # everything after that is quick.
    backend = BlockingBackend(0.05, [0.05, 1.0], search_seconds=1.0)
    sessions = []
    query = counting_query(
        backend, sessions, ["fetch_source", "fetch_source", "search_web"]
    )
    compiled = graph_module.build_graph(
        runtime,
        backend=backend,
        api=three_independent_tasks(),
        worker_fn=functools.partial(worker.run_attempt, query=query, grace=0.3),
        checkpointer=MemorySaver(),
    )
    thread = "siblings-1"

    async def go():
        config = persist.thread_config(thread)
        runtime.begin(thread)
        with pytest.raises(RuntimeError):
            await compiled.ainvoke(
                graph_module.initial_state("q", limits), config
            )
        assert backend.active == 2, "the scenario needs two surviving writes"
        # Only T1 and the two admitted siblings ever started a session;
        # the queued third never did.
        assert sessions == [0, 0, 0], "a session started over surviving work"
        snapshot = await persist.load_industry_state(
            compiled, thread, state_module.WORKFLOW_VERSION
        )
        assert set(snapshot.next) == {"run_task"}
        # A resume in the same runtime while the writes survive starts
        # nothing and delivers nothing.
        runtime.begin(thread)
        with pytest.raises(RuntimeError, match=STILL_LIVE):
            await compiled.ainvoke(
                None, persist.resume_config(thread, snapshot)
            )
        assert sessions == [0, 0, 0], "the resume started a session"
        assert not (tmp_path / "reports").exists(), "delivered over it"
        assert len(runtime.admission.survivors()) == 2
        await wait_until_idle(backend)
        assert not runtime.admission.live()
        snapshot = await persist.load_industry_state(
            compiled, thread, state_module.WORKFLOW_VERSION
        )
        runtime.begin(thread)
        return await compiled.ainvoke(
            None, persist.resume_config(thread, snapshot)
        )

    final = asyncio.run(go())
    assert final["meta"].execution_status == "completed"
    assert backend.active == 0 and backend.peak <= 2
    assert all(active == 0 for active in sessions)
    spent = budget.ledger(final)
    # The two hung attempts and the never-started third are each charged
    # their reservation; the blocked resume's fresh attempts as well.
    assert spent.unknown_attempts >= 3


def test_a_same_runtime_resume_over_a_surviving_write_is_refused(tmp_path):
    # C2 round 2, finding 1, the CLI/SQLite reproduction: the streaming
    # run was cancelled during its timed-out attempt's drain, and a
    # resume of that checkpoint in the same runtime started fresh SDK
    # attempts and delivered while the earlier write was still active.
    backend = worker_tests.BlockingIndexBackend(0.05, [1.0])
    sessions = []
    query = counting_query(backend, sessions)

    async def scenario():
        path = str(tmp_path / "resume.db")
        thread = "resume-1"
        async with persist.open_checkpointer(path) as saver:
            limits = records.Limits(concurrency=1, task_timeout_s=0.15)
            runtime = budget.Runtime(
                limits, reports_dir=str(tmp_path / "reports")
            )
            compiled = graph_module.build_graph(
                runtime,
                backend=backend,
                api=fakes.FakeRoles(),
                worker_fn=functools.partial(worker.run_attempt, query=query),
                checkpointer=saver,
            )
            config = persist.thread_config(thread)
            runtime.begin(thread)
            payload = graph_module.initial_state("q", limits)
            task = asyncio.create_task(
                industry_workflow.stream(compiled, payload, config, runtime)
            )
            await wait_for_write(backend)
            await asyncio.sleep(0.3)  # past the deadline: in the drain
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert backend.active == 1, "the scenario needs a surviving write"
            snapshot = await persist.load_industry_state(
                compiled, thread, state_module.WORKFLOW_VERSION
            )
            assert tuple(snapshot.next) == ("run_task",)
            runtime.begin(thread)
            with pytest.raises(RuntimeError, match=STILL_LIVE):
                await industry_workflow.stream(
                    compiled,
                    None,
                    persist.resume_config(thread, snapshot),
                    runtime,
                )
            assert sessions == [0], "the resume started a session"
            assert not (tmp_path / "reports").exists(), "delivered over it"
            await wait_until_idle(backend)
            snapshot = await persist.load_industry_state(
                compiled, thread, state_module.WORKFLOW_VERSION
            )
            runtime.begin(thread)
            return await industry_workflow.stream(
                compiled, None, persist.resume_config(thread, snapshot), runtime
            )

    final = asyncio.run(scenario())
    assert final["meta"].execution_status == "completed"
    assert backend.active == 0 and backend.peak == 1
    assert all(active == 0 for active in sessions)
    assert budget.ledger(final).unknown_attempts >= 1


# --- Studio's next run ---------------------------------------------------


class FakeRequest:
    """Only what run_question reads."""

    def __init__(self, app):
        self.query_params = {"question": "q"}
        self.app = app


class App:
    pass


def studio_app(graph, runtime):
    app = App()
    app.state = App()
    app.state.graph = graph
    app.state.runtime = runtime
    app.state.lock = asyncio.Lock()
    return app


def decoded(frame):
    return studio.json.loads(frame.split("data: ", 1)[1])


async def frames_of(response):
    return [decoded(f) async for f in aiter(response.body_iterator)]


def test_the_next_studio_run_is_refused_over_a_surviving_write(
    tmp_path, monkeypatch
):
    # C2 round 2, finding 1, the Studio reproduction: after a WorkerHung
    # Studio released its lock, and the next run_question started two
    # worker sessions and wrote its report while the earlier index write
    # was still running, at concurrency 1.
    monkeypatch.setattr(studio.web, "api_key", lambda: "fake")
    limits = records.Limits(concurrency=1, task_timeout_s=0.15)
    runtime = budget.Runtime(limits, reports_dir=str(tmp_path / "reports"))
    backend = worker_tests.BlockingIndexBackend(0.05, [1.0])
    sessions = []
    query = counting_query(backend, sessions)
    graph = graph_module.build_graph(
        runtime,
        backend=backend,
        api=fakes.FakeRoles(),
        worker_fn=functools.partial(worker.run_attempt, query=query, grace=0.2),
        checkpointer=MemorySaver(),
    )
    app = studio_app(graph, runtime)

    async def go():
        first = await frames_of(await studio.run_question(FakeRequest(app)))
        assert first[-1]["type"] == "error" and "WorkerHung" in str(first[-1])
        assert backend.active == 1, "the scenario needs a surviving write"
        assert not app.state.lock.locked()
        second = await frames_of(await studio.run_question(FakeRequest(app)))
        assert sessions == [0], "the next run started a session over it"
        assert not (tmp_path / "reports").exists(), "delivered over it"
        assert [f["type"] for f in second] == ["error"]
        assert STILL_LIVE in second[0]["message"]
        await wait_until_idle(backend)
        third = await frames_of(await studio.run_question(FakeRequest(app)))
        return third

    third = asyncio.run(go())
    assert third[0]["type"] == "thread" and third[-1]["type"] == "end"
    assert all(active == 0 for active in sessions)


class StubbornSdk(crew.ClaudeLLM):
    """The real adapter whose SDK stream ignores cancellation.

    ``call`` runs ``acall`` on a private loop in CrewAI's worker thread,
    so the start is signalled with a threading event.
    """

    def __init__(self, seconds):
        super().__init__()
        self.seconds = seconds
        self.started = threading.Event()
        self.ended = False

    def cancel(self):
        pass

    async def acall(self, messages, *args, **kwargs):
        del messages
        self.started.set()
        try:
            await asyncio.sleep(self.seconds)
        finally:
            self.ended = True
        model = kwargs.get("response_model") or (
            args[5] if len(args) > 5 else None
        )
        if model is None:
            return "Final Answer: slept"
        # The smallest valid output of any role: only the brief needs a
        # field, so the whole run can go through the real roles.
        return (
            model(industry="光掩模") if model is roles.BriefOutput else model()
        )

    async def wait_started(self):
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, self.started.wait, 5)


def role_call_runtime(tmp_path, monkeypatch, llms, concurrency=1):
    """A runtime for the graph's own default roles (the real LiveRoles).

    Only the LLM behind the adapter is replaced: the listed ones serve
    the first calls in order, every later call gets a quick one.
    """
    monkeypatch.setattr(crew, "CANCEL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(
        roles,
        "llm_for",
        lambda role, max_turns: llms.pop(0) if llms else StubbornSdk(0.01),
    )
    limits = records.Limits(concurrency=concurrency)
    return budget.Runtime(limits, reports_dir=str(tmp_path / "reports"))


def test_the_next_studio_run_is_refused_over_a_retained_role_call(
    tmp_path, monkeypatch
):
    # C2 round 2, finding 2: an interrupted Studio run retained a live
    # Lead call; the next run's CrewAI calls were refused, but the graph
    # degraded that RoleHung and admitted a worker SDK session -- two
    # live model sessions at concurrency 1 -- and delivered over it.
    monkeypatch.setattr(studio.web, "api_key", lambda: "fake")
    stubborn = StubbornSdk(1.5)
    runtime = role_call_runtime(tmp_path, monkeypatch, [stubborn])
    backend = worker_tests.BlockingIndexBackend(0.05)
    sessions = []
    query = counting_query(backend, sessions)
    graph = graph_module.build_graph(
        runtime,
        backend=backend,
        worker_fn=functools.partial(worker.run_attempt, query=query),
        checkpointer=MemorySaver(),
    )
    app = studio_app(graph, runtime)

    async def go():
        first = await studio.run_question(FakeRequest(app))
        seen = []

        async def consume():
            async for frame in aiter(first.body_iterator):
                seen.append(decoded(frame)["type"])

        consumer = asyncio.create_task(consume())
        await stubborn.wait_started()
        consumer.cancel()  # the client goes away during the Lead call
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert seen[:2] == ["thread", "node"] and "end" not in seen
        assert not stubborn.ended, "the scenario needs a live role call"
        assert not app.state.lock.locked()
        second = await frames_of(await studio.run_question(FakeRequest(app)))
        assert not sessions, "a worker session started over the role call"
        assert not (tmp_path / "reports").exists(), "delivered over it"
        assert [f["type"] for f in second] == ["error"]
        assert STILL_LIVE in second[0]["message"]
        assert runtime.admission.survivors()
        while runtime.admission.live():
            await asyncio.sleep(0.05)
        assert stubborn.ended

    asyncio.run(go())


def test_two_model_sessions_never_run_at_once_at_concurrency_one(
    tmp_path, monkeypatch
):
    # The same finding through the CLI's streaming function and a
    # same-runtime resume of the interrupted thread: the retained Lead
    # call must block the worker SDK entry point, not only crew.run_task,
    # and the resume must go on once the call has ended.
    stubborn = StubbornSdk(1.5)
    runtime = role_call_runtime(tmp_path, monkeypatch, [stubborn])
    backend = worker_tests.BlockingIndexBackend(0.05)
    sessions = []
    query = counting_query(backend, sessions)

    async def scenario():
        path = str(tmp_path / "two.db")
        thread = "two-1"
        async with persist.open_checkpointer(path) as saver:
            compiled = graph_module.build_graph(
                runtime,
                backend=backend,
                worker_fn=functools.partial(worker.run_attempt, query=query),
                checkpointer=saver,
            )
            config = persist.thread_config(thread)
            runtime.begin(thread)
            payload = graph_module.initial_state("q", runtime.limits)
            task = asyncio.create_task(
                industry_workflow.stream(compiled, payload, config, runtime)
            )
            await stubborn.wait_started()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not stubborn.ended, "the scenario needs a live role call"

            async def resume():
                snapshot = await persist.load_industry_state(
                    compiled, thread, state_module.WORKFLOW_VERSION
                )
                assert tuple(snapshot.next) == ("scope",)
                resumed = persist.resume_config(thread, snapshot)
                await compiled.aupdate_state(
                    resumed,
                    graph_module.resume_updates(
                        snapshot.values, "scope", runtime.limits
                    ),
                    as_node="reserve_scope",
                )
                runtime.begin(thread)
                return await industry_workflow.stream(
                    compiled, None, resumed, runtime
                )

            with pytest.raises(RuntimeError, match=STILL_LIVE):
                await resume()
            assert not sessions, "a worker session started over the call"
            assert not stubborn.ended, "the refusal waited for the call"
            while runtime.admission.live():
                await asyncio.sleep(0.05)
            return await resume()

    final = asyncio.run(scenario())
    assert final["meta"].execution_status == "completed"
    assert final["brief"].industry == "光掩模"
    assert sessions and all(active == 0 for active in sessions)
    # The interrupted call and the refused resume each keep their
    # reservation charged; the third call is the one that answered.
    calls = final["single_calls"]
    assert [calls[f"scope.{n}"].status for n in (1, 2)] == ["unknown"] * 2
    assert "scope.3" in calls and "scope.4" not in calls


# --- the SDK's own subprocess: C2 round 3 --------------------------------


def sdk_then_fake(cli, backend, sessions, tools=()):
    """The real SDK for the first session, the counting fake after it.

    The first session runs through the installed SDK and its transport,
    against a stand-in CLI that never answers, so it ends on its
    deadline with the child still running; every later session is the
    ordinary fake, so the run can go on to delivery.
    """
    fake = counting_query(backend, sessions, tools)
    calls = []

    def query(prompt, options):
        calls.append(prompt)
        if len(calls) == 1:
            options.cli_path = str(cli)
            return claude_agent_sdk.query(prompt=prompt, options=options)
        return fake(prompt, options)

    return query


def test_an_interruption_during_sdk_cleanup_keeps_the_slot(
    tmp_path, monkeypatch
):
    # C2 round 3, finding 1: the attempt settled its slot on the tool
    # threads alone. The SDK's transport cleanup shields with AnyIO,
    # which a raw asyncio cancellation still interrupts, so a
    # cancellation during cleanup left the CLI subprocess running with
    # the slot free, and the next session started over it at
    # concurrency 1.
    sdk_tests.arm(monkeypatch, grace=1.5)
    cli = sdk_tests.peer(tmp_path)
    runtime = single_slot_runtime("T2.1", "T2.2", "T2.3")
    backend = worker_tests.BlockingIndexBackend(0.05)
    sessions = []
    query = sdk_then_fake(cli, backend, sessions)

    async def go():
        task = asyncio.create_task(
            worker.run_attempt(
                worker_tests.attempt_with("T2.1", 0.3),
                runtime,
                backend,
                query=query,
            )
        )
        await sdk_tests.wait_for_child("T2.1")
        await asyncio.sleep(0.5)  # past the deadline: in the SDK cleanup
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sdk_children.live("T2.1"), "needs a surviving subprocess"
        with pytest.raises(RuntimeError, match=STILL_LIVE):
            await worker.run_attempt(
                worker_tests.attempt_with("T2.2", 5),
                runtime,
                backend,
                query=query,
            )
        assert not sessions, "a session started over the subprocess"
        survivors = runtime.admission.survivors()
        assert len(survivors) == 1, "the slot outlived nothing"
        assert "SDK subprocess" in survivors[0].describe()
        # The teardown the attempt started ends the child, and only then
        # is the slot given back.
        while runtime.admission.live():
            await asyncio.sleep(0.05)
        assert not sdk_children.live("T2.1")
        result = await worker.run_attempt(
            worker_tests.attempt_with("T2.3", 5), runtime, backend, query=query
        )
        assert result.status == "done"
        await sdk_tests.forget("T2.1")

    asyncio.run(go())
    assert sessions == [0], "the admitted session ran over surviving work"


def test_a_same_runtime_resume_over_a_surviving_subprocess_is_refused(
    tmp_path, monkeypatch
):
    # The same defect through the CLI's streaming function and SQLite:
    # the run is interrupted while the SDK's cleanup is under way, and
    # the resume in the same runtime must start no session and deliver
    # no report while that subprocess is alive.
    sdk_tests.arm(monkeypatch, grace=1.5)
    cli = sdk_tests.peer(tmp_path)
    backend = worker_tests.BlockingIndexBackend(0.05)
    sessions = []
    query = sdk_then_fake(cli, backend, sessions)

    async def scenario():
        path = str(tmp_path / "sdk-resume.db")
        thread = "sdk-resume-1"
        async with persist.open_checkpointer(path) as saver:
            limits = records.Limits(concurrency=1, task_timeout_s=0.3)
            runtime = budget.Runtime(
                limits, reports_dir=str(tmp_path / "reports")
            )
            compiled = graph_module.build_graph(
                runtime,
                backend=backend,
                api=fakes.FakeRoles(),
                worker_fn=functools.partial(worker.run_attempt, query=query),
                checkpointer=saver,
            )
            config = persist.thread_config(thread)
            runtime.begin(thread)
            payload = graph_module.initial_state("q", limits)
            task = asyncio.create_task(
                industry_workflow.stream(compiled, payload, config, runtime)
            )
            session = await sdk_tests.marked_session()
            await asyncio.sleep(0.5)  # past the deadline: in the cleanup
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sdk_children.live(session), "needs a live subprocess"
            snapshot = await persist.load_industry_state(
                compiled, thread, state_module.WORKFLOW_VERSION
            )
            assert tuple(snapshot.next) == ("run_task",)
            runtime.begin(thread)
            with pytest.raises(RuntimeError, match=STILL_LIVE):
                await industry_workflow.stream(
                    compiled,
                    None,
                    persist.resume_config(thread, snapshot),
                    runtime,
                )
            assert not sessions, "the resume started a session"
            assert not (tmp_path / "reports").exists(), "delivered over it"
            while runtime.admission.live():
                await asyncio.sleep(0.05)
            assert not sdk_children.live(session)
            snapshot = await persist.load_industry_state(
                compiled, thread, state_module.WORKFLOW_VERSION
            )
            runtime.begin(thread)
            final = await industry_workflow.stream(
                compiled, None, persist.resume_config(thread, snapshot), runtime
            )
            await sdk_tests.forget(session)
            return final

    final = asyncio.run(scenario())
    assert final["meta"].execution_status == "completed"
    assert sessions and all(active == 0 for active in sessions)


def test_the_next_studio_run_is_refused_over_a_surviving_subprocess(
    tmp_path, monkeypatch
):
    # And through Studio: the client goes away while the SDK's cleanup
    # is under way, and the next question must be refused rather than
    # start worker sessions and write a report over the live subprocess.
    monkeypatch.setattr(studio.web, "api_key", lambda: "fake")
    sdk_tests.arm(monkeypatch, grace=1.5)
    cli = sdk_tests.peer(tmp_path)
    limits = records.Limits(concurrency=1, task_timeout_s=0.3)
    runtime = budget.Runtime(limits, reports_dir=str(tmp_path / "reports"))
    backend = worker_tests.BlockingIndexBackend(0.05)
    sessions = []
    query = sdk_then_fake(cli, backend, sessions)
    graph = graph_module.build_graph(
        runtime,
        backend=backend,
        api=fakes.FakeRoles(),
        worker_fn=functools.partial(worker.run_attempt, query=query),
        checkpointer=MemorySaver(),
    )
    app = studio_app(graph, runtime)

    async def go():
        first = await studio.run_question(FakeRequest(app))
        seen = []

        async def consume():
            async for frame in aiter(first.body_iterator):
                seen.append(decoded(frame)["type"])

        consumer = asyncio.create_task(consume())
        session = await sdk_tests.marked_session()
        await asyncio.sleep(0.5)  # past the deadline: in the cleanup
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert "end" not in seen
        assert sdk_children.live(session), "needs a live subprocess"
        assert not app.state.lock.locked()
        second = await frames_of(await studio.run_question(FakeRequest(app)))
        assert not sessions, "the next run started a session over it"
        assert not (tmp_path / "reports").exists(), "delivered over it"
        assert [f["type"] for f in second] == ["error"]
        assert STILL_LIVE in second[0]["message"]
        assert "SDK subprocess" in second[0]["message"]
        while runtime.admission.live():
            await asyncio.sleep(0.05)
        assert not sdk_children.live(session)
        third = await frames_of(await studio.run_question(FakeRequest(app)))
        await sdk_tests.forget(session)
        return third

    third = asyncio.run(go())
    assert third[0]["type"] == "thread" and third[-1]["type"] == "end"
    assert sessions and all(active == 0 for active in sessions)
