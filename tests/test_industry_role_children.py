"""C2r4-1: role ownership includes real SDK children and their private loop.

A local CLI drives the installed SDK and actual CrewAI adapter. The slow
case keeps the SDK's unchanged 60-second initialization timeout and the
ordinary 61-second role deadline; no injected cancellation starts it.
"""

import asyncio
import contextlib
import functools
import os
import signal
import threading
import time

import claude_agent_sdk
import industry_workflow
import pytest
import studio
import test_industry_lifetime as lifetime
import test_industry_sdk_children as sdk_tests
import test_industry_worker as worker_tests

from industry import admission
from industry import budget
from industry import graph
from industry import records
from industry import sdk_children
from industry import state
from industry import worker
from research import crew
from research import persist


class RolePeer:
    """Observe the real first role session; answer later sessions locally."""

    def __init__(
        self, tmp_path, monkeypatch, mode="error", grace=2, hang_cleanup=False
    ):
        sdk_tests.arm(monkeypatch, grace=grace)
        self.cli = sdk_tests.peer(tmp_path)
        if mode == "error":
            self.cli.write_text(
                sdk_tests.PEER.replace(
                    "while True:",
                    "import json\n"
                    "request = json.loads(sys.stdin.readline())\n"
                    'print(json.dumps({"type": "control_response",\n'
                    '    "response": {\n'
                    '    "subtype": "error",\n'
                    '    "request_id": request["request_id"],\n'
                    '    "error": "local failure"}}), flush=True)\n'
                    "while True:",
                )
            )
        self.cleaning = threading.Event()
        self.consumed = threading.Event()
        self.loop = None
        self.session = None
        self.mark_supplied = False
        self.starts = []
        self.cleanup_at = None
        self.started_at = None
        query = claude_agent_sdk.query
        close = sdk_tests.subprocess_cli.SubprocessCLITransport.close

        async def observed_close(transport):
            if not self.cleaning.is_set():
                self.cleanup_at = time.monotonic()
                self.cleaning.set()
            if hang_cleanup:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    # Model SDK cleanup that does not return on the role's
                    # cancellation. Only independent escalation ends it.
                    while self.live():
                        await asyncio.sleep(0.02)
            await close(transport)

        async def local_query(*, prompt, options):
            self.starts.append(bool(self.session and self.live()))
            if self.session is None:
                self.loop = asyncio.get_running_loop()
                self.mark_supplied = sdk_children.MARKER in options.env
                # Observation only on the pre-fix candidate, which supplied
                # no mark. The marker contract is asserted separately.
                options.env.setdefault(sdk_children.MARKER, "c2r4-role")
                self.session = options.env[sdk_children.MARKER]
                options.cli_path = str(self.cli)
                self.started_at = time.monotonic()
                try:
                    async for message in query(prompt=prompt, options=options):
                        yield message
                finally:
                    self.consumed.set()
            else:
                properties = (
                    (options.output_format or {})
                    .get("schema", {})
                    .get("properties", {})
                )
                output = (
                    {"industry": "光掩模"} if "industry" in properties else {}
                )
                yield worker_tests.result_message(
                    structured_output=output, result="answer"
                )

        monkeypatch.setattr(claude_agent_sdk, "query", local_query)
        monkeypatch.setattr(
            sdk_tests.subprocess_cli.SubprocessCLITransport,
            "close",
            observed_close,
        )
        monkeypatch.setattr(crew, "CANCEL_GRACE_SECONDS", 0.2)
        monkeypatch.setattr(studio.web, "api_key", lambda: "fake")

    def live(self):
        """The first role's children still executing."""
        return sdk_children.live(self.session) if self.session else []

    async def wait_cleaning(self):
        """Wait for a signal from CrewAI's worker thread."""
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, self.cleaning.wait, 65)
        await sdk_tests.wait_for_child(self.session)

    async def released(self, runtime):
        """The child and kickoff both end, then admission releases."""
        async with asyncio.timeout(8):
            while runtime.admission.live():
                await asyncio.sleep(0.02)
        assert not self.live()
        assert self.loop.is_closed()
        await sdk_tests.forget(self.session)

    async def reap(self, runtime):
        """Leave no child behind even when running on the broken candidate."""
        for child in self.live():
            with contextlib.suppress(OSError):
                os.kill(child.pid, signal.SIGKILL)
        if runtime.admission.live():
            await self.released(runtime)
        elif self.loop is not None and not self.loop.is_closed():
            await sdk_tests.forget(self.session)

    def compiled(self, runtime, saver):
        """Default LiveRoles, real worker handlers, local model responses."""
        backend = worker_tests.BlockingIndexBackend(0.01)
        fake = lifetime.counting_query(backend, [])

        def worker_query(prompt, options):
            self.starts.append(bool(self.live()))
            return fake(prompt, options)

        return graph.build_graph(
            runtime,
            backend=backend,
            worker_fn=functools.partial(worker.run_attempt, query=worker_query),
            checkpointer=saver,
        )


def test_role_initialization_cleanup_meets_ordinary_deadline(
    tmp_path, monkeypatch
):
    probe = RolePeer(tmp_path, monkeypatch, mode="silent")
    runtime = budget.Runtime(
        records.Limits(concurrency=1, single_call_timeout_s=61),
        reports_dir=str(tmp_path / "reports"),
    )
    compiled = probe.compiled(runtime, lifetime.MemorySaver())
    app = lifetime.studio_app(compiled, runtime)

    async def go():
        try:
            frames = await lifetime.frames_of(
                await studio.run_question(lifetime.FakeRequest(app))
            )
            assert probe.cleanup_at - probe.started_at >= 60
            assert (
                probe.consumed.is_set()
            ), "deadline must interrupt SDK cleanup"
            assert probe.live(), "scenario needs the surviving child"
            assert probe.starts == [False], "a session overtook the child"
            assert frames[-1]["type"] == "error"
            assert "still live" in frames[-1]["message"]
            assert not (tmp_path / "reports").exists()
            assert not probe.loop.is_closed()
            assert (
                "SDK subprocess" in runtime.admission.survivors()[0].describe()
            )
            await probe.released(runtime)
            recovered = await lifetime.frames_of(
                await studio.run_question(lifetime.FakeRequest(app))
            )
            assert recovered[-1]["type"] == "end"
            assert not any(probe.starts)
        finally:
            await probe.reap(runtime)

    asyncio.run(go())


@pytest.mark.parametrize("entry", ["cli", "studio"])
def test_role_child_blocks_resume_next_run_workers_and_delivery(
    tmp_path, monkeypatch, entry
):
    probe = RolePeer(tmp_path, monkeypatch)
    runtime = budget.Runtime(
        records.Limits(concurrency=1, single_call_timeout_s=3),
        reports_dir=str(tmp_path / "reports"),
    )

    async def go():
        async with persist.open_checkpointer(
            str(tmp_path / "role.db")
        ) as saver:
            compiled = probe.compiled(runtime, saver)
            app = lifetime.studio_app(compiled, runtime)
            thread = "role-resume"
            config = persist.thread_config(thread)
            runtime.begin(thread)
            task = asyncio.create_task(
                industry_workflow.stream(
                    compiled,
                    graph.initial_state("q", runtime.limits),
                    config,
                    runtime,
                )
            )
            try:
                await probe.wait_cleaning()
                await asyncio.sleep(0.1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert probe.live()
                snapshot = await persist.load_industry_state(
                    compiled, thread, state.WORKFLOW_VERSION
                )
                assert tuple(snapshot.next) == ("scope",)

                async def resume():
                    saved = await persist.load_industry_state(
                        compiled, thread, state.WORKFLOW_VERSION
                    )
                    resumed = persist.resume_config(thread, saved)
                    await compiled.aupdate_state(
                        resumed,
                        graph.resume_updates(
                            saved.values, "scope", runtime.limits
                        ),
                        as_node="reserve_scope",
                    )
                    runtime.begin(thread)
                    return await industry_workflow.stream(
                        compiled, None, resumed, runtime
                    )

                if entry == "cli":
                    with pytest.raises(
                        admission.Blocked, match="SDK subprocess"
                    ):
                        await resume()
                else:
                    frames = await lifetime.frames_of(
                        await studio.run_question(lifetime.FakeRequest(app))
                    )
                    assert [f["type"] for f in frames] == ["error"]
                    assert "SDK subprocess" in frames[0]["message"]
                assert probe.starts == [False]
                assert not (tmp_path / "reports").exists()
                # Exercise the worker's own admission and the actual delivery
                # node even when no further role call would be reserved.
                runtime.new_meter("t", {}).register("T2.1", 24)
                with pytest.raises(admission.Blocked, match="SDK subprocess"):
                    await worker.run_attempt(
                        worker_tests.attempt_with("T2.1", 5),
                        runtime,
                        worker_tests.Backend(),
                        query=lambda **kw: pytest.fail("worker admitted"),
                    )
                with pytest.raises(admission.Blocked, match="SDK subprocess"):
                    await compiled.nodes["deliver"].ainvoke(
                        snapshot.values, config
                    )
                assert not probe.loop.is_closed()
                await probe.released(runtime)
                final = await resume()
                assert final["meta"].execution_status == "completed"
                frames = await lifetime.frames_of(
                    await studio.run_question(lifetime.FakeRequest(app))
                )
                assert frames[-1]["type"] == "end"
                assert not any(probe.starts)
            finally:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                await probe.reap(runtime)

    asyncio.run(go())


@pytest.mark.parametrize("ending", ["failure", "timeout", "second_cancel"])
def test_role_teardown_owns_its_loop_through_every_exit(
    tmp_path, monkeypatch, ending
):
    probe = RolePeer(
        tmp_path,
        monkeypatch,
        mode="silent" if ending == "timeout" else "error",
        grace=0.3,
    )
    runtime = budget.Runtime(records.Limits(concurrency=1))
    llm = crew.ClaudeLLM()

    async def go():
        task = asyncio.create_task(
            crew.run_task(
                crew.REPORTER,
                "hi",
                "text",
                llm,
                deadline=0.3 if ending == "timeout" else 30,
                grace=2 if ending == "timeout" else 0.2,
                admission=runtime.admission,
            )
        )
        try:
            await probe.wait_cleaning()
            if ending == "second_cancel":
                task.cancel()
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                # Cancellation directed at the adapter again cannot cancel
                # the teardown running after its consumption task ended.
                llm.cancel()
                llm.cancel()
                assert probe.live()
                assert runtime.admission.survivors()
                assert not probe.loop.is_closed()
            else:
                # The installed SDK raises a plain Exception for a valid
                # initialization-error response; preserve that exact error.
                error = crew.RoleTimeout if ending == "timeout" else Exception
                message = "exceeded" if ending == "timeout" else "local failure"
                with pytest.raises(error, match=message):
                    await task
            await probe.released(runtime)
            assert probe.mark_supplied
            out = await crew.run_task(
                crew.REPORTER, "again", "text", admission=runtime.admission
            )
            assert out == "answer"
            assert not runtime.admission.live()
        finally:
            await probe.reap(runtime)

    asyncio.run(go())


def test_role_retains_ownership_after_every_signal_grace(tmp_path, monkeypatch):
    # Model a child that cannot be reaped even after SIGKILL. Suppress
    # signals at the process seam, then really kill it to prove recovery.
    probe = RolePeer(tmp_path, monkeypatch, grace=0.1)
    monkeypatch.setattr(sdk_children, "SIGNAL_GRACE_S", 0.1)
    runtime = budget.Runtime(records.Limits(concurrency=1))
    signals = []

    async def go():
        task = asyncio.create_task(
            crew.run_task(
                crew.REPORTER,
                "hi",
                "text",
                deadline=30,
                grace=0.05,
                admission=runtime.admission,
            )
        )
        try:
            await probe.wait_cleaning()
            child = probe.live()[0]
            monkeypatch.setattr(
                child, "terminate", lambda: signals.append("terminate")
            )
            monkeypatch.setattr(child, "kill", lambda: signals.append("kill"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with asyncio.timeout(3):
                while "kill" not in signals:
                    await asyncio.sleep(0.02)
            await asyncio.sleep(0.2)
            assert child.returncode is None
            assert not probe.loop.is_closed()
            with pytest.raises(admission.Blocked, match="SDK subprocess"):
                await crew.run_task(
                    crew.REPORTER, "retry", "text", admission=runtime.admission
                )
            os.kill(child.pid, signal.SIGKILL)
            await probe.released(runtime)
            assert (
                await crew.run_task(
                    crew.REPORTER, "retry", "text", admission=runtime.admission
                )
                == "answer"
            )
        finally:
            await probe.reap(runtime)

    asyncio.run(go())


def test_successful_role_reaps_child_before_closing_private_loop(
    tmp_path, monkeypatch
):
    probe = RolePeer(tmp_path, monkeypatch, mode="silent")
    # A valid initialization response, then one text result. Exit on EOF,
    # giving the SDK its normal successful teardown with no backstop.
    code = sdk_tests.PEER.split("while True:", maxsplit=1)[0] + """
import json
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "control_response", "response": {
    "subtype": "success", "request_id": request["request_id"],
    "response": {}}}), flush=True)
sys.stdin.readline()
print(json.dumps({"type": "result", "subtype": "success", "duration_ms": 1,
    "duration_api_ms": 1, "is_error": False, "num_turns": 1,
    "session_id": "local", "result": "answer"}), flush=True)
sys.stdin.read()
"""
    probe.cli.write_text(code)
    runtime = budget.Runtime(records.Limits(concurrency=1))

    async def go():
        try:
            assert (
                await crew.run_task(
                    crew.REPORTER,
                    "hi",
                    "text",
                    deadline=30,
                    admission=runtime.admission,
                )
                == "answer"
            )
            assert probe.mark_supplied
            assert not runtime.admission.live()
            await probe.released(runtime)
        finally:
            await probe.reap(runtime)

    asyncio.run(go())


def test_role_cancellation_escalates_even_if_sdk_cleanup_hangs(
    tmp_path, monkeypatch
):
    probe = RolePeer(tmp_path, monkeypatch, grace=0.5, hang_cleanup=True)
    runtime = budget.Runtime(records.Limits(concurrency=1))

    async def go():
        try:
            with pytest.raises(crew.RoleHung):
                await crew.run_task(
                    crew.REPORTER,
                    "hi",
                    "text",
                    deadline=0.3,
                    grace=0.05,
                    admission=runtime.admission,
                )
            assert probe.cleaning.is_set()
            assert not probe.consumed.is_set()
            assert probe.live()
            assert runtime.admission.survivors()
            assert not probe.loop.is_closed()
            # No second cancellation is needed to free the stuck cleanup.
            await probe.released(runtime)
            assert probe.consumed.is_set()
        finally:
            await probe.reap(runtime)

    asyncio.run(go())
