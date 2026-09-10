"""Actual session boundaries and resume-safe elapsed accounting."""

import asyncio
import types

import aiosqlite
import claude_agent_sdk
import pytest

from industry import admission
from industry import budget
from industry import records
from industry import timing
from research import crew


def test_queue_invocation_and_survivor_end_are_distinct():
    async def scenario():
        authority = admission.Admission(1)
        holder = await authority.acquire("session", "holder")
        entered = asyncio.Event()
        end = asyncio.get_running_loop().create_future()

        async def waiting():
            with admission.capture_timing() as measured:
                entered.set()
                slot = await authority.acquire("session", "queued")
                slot.invoked()
                slot.settle(end)
            return measured

        waiter = asyncio.create_task(waiting())
        await entered.wait()
        await asyncio.sleep(0.01)
        assert not waiter.done()
        holder.release()
        measured = await waiter
        assert measured["queued_at"] < measured["invoked_at"]
        assert "finished_at" not in measured
        assert authority.survivors()
        end.set_result(None)
        await asyncio.sleep(0)
        assert measured["invoked_at"] <= measured["finished_at"]
        assert not authority.live()

    asyncio.run(scenario())


def test_unknown_session_end_never_becomes_observed_duration():
    attempt = records.Attempt(
        id="review.1",
        task_id="review",
        started_at="2026-09-10T00:00:00+00:00",
        reserved=records.Reservation(turns=10, tool_calls=0, seconds=480),
        queued_at="2026-09-10T00:10:00+00:00",
        invoked_at="2026-09-10T00:10:05+00:00",
    )
    state = {"single_calls": {attempt.id: attempt}}
    measured = budget.invocation_timing(state)
    assert measured["session_queue_s"] == 5
    assert measured["invocation_session_s"] == 0
    assert not measured["invocation_timing_complete"]
    assert budget.ledger(state).wall_clock_s == 480


def test_run_intervals_separate_known_pause_from_unknown_end(tmp_path):
    async def scenario():
        async with aiosqlite.connect(tmp_path / "timing.db") as connection:
            async with timing.invocation(connection, "thread"):
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.01)
            async with timing.invocation(connection, "thread"):
                await asyncio.sleep(0.01)
            measured = await timing.summary(connection, "thread")
            assert measured["intervals"] == 2
            assert measured["active_elapsed_s"] >= 0.02
            assert measured["timing_complete"]
            # Force an older hard-killed interval. Its end cannot be
            # inferred from the next checkpoint or counted as a pause.
            await connection.execute(
                "INSERT INTO industry_invocations VALUES (?, ?, ?, NULL, NULL)",
                ("crashed", "thread", "2026-01-01T00:00:00+00:00"),
            )
            measured = await timing.summary(connection, "thread")
            assert measured["unknown_intervals"] == 1
            assert not measured["timing_complete"]
            assert measured["paused_s"] < 1

    asyncio.run(scenario())


def test_controlled_interruption_closes_only_its_own_interval(tmp_path):
    async def scenario():
        async with aiosqlite.connect(tmp_path / "timing.db") as connection:
            try:
                async with timing.invocation(connection, "thread"):
                    raise asyncio.CancelledError
            except asyncio.CancelledError:
                pass
            measured = await timing.summary(connection, "thread")
            assert measured["timing_complete"]
            assert measured["unknown_intervals"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("enter_sdk", [False, True])
def test_role_timing_measures_sdk_entry_not_kickoff(monkeypatch, enter_sdk):
    async def scenario():
        llm = crew.ClaudeLLM()
        cancelled = asyncio.Event()
        calls = []

        async def query(**kwargs):
            del kwargs
            calls.append("sdk")
            yield claude_agent_sdk.ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="offline",
                result="done",
                total_cost_usd=0.0,
                usage={},
            )

        async def kickoff(_self):
            if not enter_sdk:
                await cancelled.wait()
                return types.SimpleNamespace(tasks_output=[])
            await asyncio.sleep(0.03)
            value = await llm.acall("offline")
            return types.SimpleNamespace(
                tasks_output=[types.SimpleNamespace(raw=value)]
            )

        monkeypatch.setattr(claude_agent_sdk, "query", query)
        monkeypatch.setattr(crew.crewai.Crew, "akickoff", kickoff)
        monkeypatch.setattr(llm, "cancel", cancelled.set)
        with admission.capture_timing() as measured:
            call = crew.run_task(
                crew.REPORTER,
                "offline",
                "text",
                llm,
                deadline=1 if enter_sdk else 0.01,
                grace=1,
                admission=admission.Admission(1),
            )
            if enter_sdk:
                await call
            else:
                with pytest.raises(crew.RoleTimeout):
                    await call
        attempt = records.Attempt(
            id="write.1",
            task_id="write",
            started_at=records.now_iso(),
            reserved=records.Reservation(turns=10, tool_calls=0, seconds=480),
            observed=records.Usage(unknown=not enter_sdk),
            **measured,
        )
        result = budget.invocation_timing(
            {"single_calls": {attempt.id: attempt}}
        )
        assert len(calls) == int(enter_sdk) == result["invoked_sessions"]
        assert result["invocation_timing_complete"]
        assert measured["queued_at"] <= measured["admitted_at"]
        assert measured["admitted_at"] <= measured["kickoff_at"]
        if enter_sdk:
            assert measured["kickoff_at"] < measured["invoked_at"]
            assert measured["invoked_at"] <= measured["finished_at"]
        else:
            assert "invoked_at" not in measured

    asyncio.run(scenario())
