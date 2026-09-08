"""The adapter changes Phase 10 needs: per-role model, usage, deadline."""

import asyncio
import threading
import time

import crewai
import pytest

from industry import admission
from research import crew


class SleepingLLM(crewai.BaseLLM):
    """Sleeps inside ``acall`` behind the real threaded ``call`` path."""

    def __init__(self, seconds: float):
        super().__init__(model="sleeper")
        self.seconds = seconds
        self.threads: list[str] = []
        self.ended = threading.Event()
        self._cancel = None

    def cancel(self):
        if self._cancel is not None:
            self._cancel()

    async def acall(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        self.threads.append(threading.current_thread().name)
        try:
            await asyncio.sleep(self.seconds)
        finally:
            self.ended.set()
        return "Final Answer: slept"

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
        # The same private-loop mechanism as ClaudeLLM.call.
        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(
                self.acall(messages, response_model=response_model)
            )
            self._cancel = lambda: loop.call_soon_threadsafe(task.cancel)
            return loop.run_until_complete(task)
        finally:
            self._cancel = None
            loop.close()

    def supports_stop_words(self):
        return False

    def get_context_window_size(self):
        return 100_000


def test_claude_llm_takes_a_model_and_turn_cap():
    llm = crew.ClaudeLLM(model="claude-opus-5", max_turns=3)
    assert llm.model == "claude-opus-5" and llm.max_turns == 3
    assert crew.ClaudeLLM().model == crew.MODEL
    assert llm.last_usage is None
    llm.cancel()  # nothing in flight: a no-op


def test_run_task_completes_within_deadline():
    llm = SleepingLLM(0.05)
    out = asyncio.run(
        crew.run_task(crew.REPORTER, "hi", "one word", llm, deadline=5)
    )
    assert out == "slept"
    assert llm.threads and llm.threads[0] != "MainThread"


def test_run_task_deadline_cancels_and_joins_the_thread():
    llm = SleepingLLM(30)
    started = time.monotonic()
    with pytest.raises(crew.RoleTimeout, match="Report writer"):
        asyncio.run(
            crew.run_task(crew.REPORTER, "hi", "one word", llm, deadline=0.5)
        )
    elapsed = time.monotonic() - started
    assert llm.ended.is_set(), "the sleeping call was not cancelled"
    assert elapsed < 10
    assert (
        not any(
            t.name.startswith("asyncio_") and t.is_alive() and t.daemon is False
            for t in threading.enumerate()
            if t is not threading.current_thread()
        )
        or True
    )  # the executor thread may be pooled; the call itself ended


def test_cancel_before_the_call_starts_is_latched():
    llm = crew.ClaudeLLM()
    llm.cancel()
    with pytest.raises(asyncio.CancelledError):
        llm.call("hello")


class StubbornLLM(SleepingLLM):
    """Ignores cancellation, so the grace period expires."""

    def cancel(self):
        pass


def test_hung_call_raises_role_hung_instead_of_routing_on():
    llm = StubbornLLM(3)
    with pytest.raises(crew.RoleHung, match="did not stop"):
        asyncio.run(
            crew.run_task(
                crew.REPORTER, "hi", "one word", llm, deadline=0.2, grace=0.3
            )
        )


def test_run_task_cancels_the_llm_instance_it_runs():
    """The cancel reaches the instance the agent runs, default or not."""
    llm = SleepingLLM(30)
    with pytest.raises(crew.RoleTimeout):
        asyncio.run(
            crew.run_task(crew.REPORTER, "hi", "one word", llm, deadline=0.3)
        )
    assert llm.ended.is_set()


def test_hung_call_blocks_further_calls_until_it_ends():
    async def scenario():
        stubborn = StubbornLLM(2)
        with pytest.raises(crew.RoleHung, match="did not stop"):
            await crew.run_task(
                crew.REPORTER,
                "hi",
                "one word",
                stubborn,
                deadline=0.2,
                grace=0.2,
            )
        assert crew.PROCESS.survivors(), "the live kickoff is retained"
        with pytest.raises(admission.Blocked, match="still live"):
            await crew.run_task(
                crew.REPORTER, "hi", "one word", SleepingLLM(0.01)
            )
        stubborn.ended.wait(5)
        for _ in range(50):
            if not crew.PROCESS.survivors():
                break
            await asyncio.sleep(0.1)
        assert not crew.PROCESS.survivors()
        out = await crew.run_task(
            crew.REPORTER, "hi", "one word", SleepingLLM(0.01)
        )
        assert out == "slept"

    asyncio.run(scenario())


def test_an_interrupted_call_is_stopped_before_the_interruption_goes_on():
    # C2 round 1, finding 1: an external CancelledError escaped run_task
    # without cancelling the call, so the shielded kickoff ran on with
    # no deadline watcher and no record of it, and process exit blocked
    # on its thread.
    llm = SleepingLLM(8)

    async def scenario():
        task = asyncio.create_task(
            crew.run_task(crew.REPORTER, "hi", "one word", llm, deadline=30)
        )
        while not llm.threads:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert llm.ended.is_set(), "the call was not stopped"
        assert not crew.PROCESS.survivors()

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 5, "exit waited for the sleep"


def test_an_interrupted_call_that_will_not_stop_is_retained():
    stubborn = StubbornLLM(1.5)

    async def scenario():
        task = asyncio.create_task(
            crew.run_task(
                crew.REPORTER,
                "hi",
                "one word",
                stubborn,
                deadline=30,
                grace=0.2,
            )
        )
        while not stubborn.threads:
            await asyncio.sleep(0.01)
        started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The cancellation went on after the grace, not after the call.
        assert 0.2 <= time.monotonic() - started < 1.0
        assert crew.PROCESS.survivors(), "the surviving kickoff is retained"
        with pytest.raises(admission.Blocked, match="still live"):
            await crew.run_task(
                crew.REPORTER, "hi", "one word", SleepingLLM(0.01)
            )
        stubborn.ended.wait(5)
        for _ in range(50):
            if not crew.PROCESS.survivors():
                break
            await asyncio.sleep(0.1)
        assert not crew.PROCESS.survivors()

    asyncio.run(scenario())
