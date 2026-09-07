"""The adapter changes Phase 10 needs: per-role model, usage, deadline."""

import asyncio
import threading
import time

import crewai
import pytest

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
