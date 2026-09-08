"""The admission authority itself: one bound, slots that outlive coroutines."""

import asyncio

import pytest

from industry import admission
from industry import tools


def run(coroutine):
    return asyncio.run(coroutine)


def test_role_calls_and_sessions_share_one_bound():
    authority = admission.Admission(2)

    async def scenario():
        role = await authority.acquire("role", "Research lead")
        session = await authority.acquire("session", "T2.1")
        assert authority.free == 0
        third = asyncio.create_task(authority.acquire("session", "T2.2"))
        await asyncio.sleep(0.05)
        assert not third.done(), "a third operation ran over the bound"
        role.release()
        slot = await asyncio.wait_for(third, 1)
        assert [s.label for s in authority.live()] == ["T2.1", "T2.2"]
        session.release()
        slot.release()
        assert not authority.live() and authority.free == 2

    run(scenario())


def test_a_survivor_blocks_every_admission_until_its_work_ends():
    authority = admission.Admission(2)

    async def scenario():
        slot = await authority.acquire("session", "T2.1", lambda: "1 write")
        work = asyncio.get_running_loop().create_future()
        slot.settle(work)  # the coroutine is gone, the work is not
        assert slot.survivor and authority.survivors() == [slot]
        with pytest.raises(admission.Blocked, match="T2.1 \\(1 write\\)"):
            await authority.acquire("role", "Analyst")
        with pytest.raises(admission.Blocked, match="still live"):
            authority.check()
        work.set_result(None)
        await asyncio.sleep(0)
        assert not authority.live()
        authority.check()
        (await authority.acquire("role", "Analyst")).release()

    run(scenario())


def test_a_waiter_is_refused_when_the_slot_it_waits_for_survives():
    authority = admission.Admission(1)

    async def scenario():
        first = await authority.acquire("session", "T2.1")
        waiting = asyncio.create_task(authority.acquire("session", "T2.2"))
        await asyncio.sleep(0.02)
        assert not waiting.done()
        first.settle(asyncio.get_running_loop().create_future())
        with pytest.raises(admission.Blocked):
            await asyncio.wait_for(waiting, 1)

    run(scenario())


def test_settling_ended_work_releases_at_once():
    authority = admission.Admission(1)

    async def scenario():
        slot = await authority.acquire("role", "Editor")
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        slot.settle(done)
        assert not slot.survivor and not authority.live()
        slot = await authority.acquire("role", "Editor")
        slot.settle(None)  # nothing was started
        assert not authority.live()
        slot.release()  # idempotent

    run(scenario())


def test_cancelling_a_wait_takes_nothing():
    authority = admission.Admission(1)

    async def scenario():
        held = await authority.acquire("session", "T2.1")
        waiting = asyncio.create_task(authority.acquire("session", "T2.2"))
        await asyncio.sleep(0.02)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        held.release()
        assert not authority.live() and authority.free == 1

    run(scenario())


def test_an_unbounded_authority_still_tracks_survivors():
    authority = admission.Admission(None)

    async def scenario():
        slots = [await authority.acquire("role", f"r{n}") for n in range(5)]
        assert authority.free is None
        slots[0].settle(asyncio.get_running_loop().create_future())
        with pytest.raises(admission.Blocked):
            await authority.acquire("role", "r6")
        for slot in slots[1:]:
            slot.release()

    run(scenario())


def test_outstanding_reports_idle_when_the_last_call_ends():
    outstanding = tools.Outstanding()
    release = asyncio.Event()

    async def scenario():
        assert (await outstanding.when_idle()) is None  # nothing running
        loop = asyncio.get_running_loop()
        gate = loop.run_in_executor(None, lambda: None)
        await gate
        started = asyncio.Event()

        def blocking():
            loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result()

        task = asyncio.create_task(outstanding.run(blocking))
        await started.wait()
        idle = outstanding.when_idle()
        assert not idle.done() and outstanding.running == 1
        assert "1 tool call" in outstanding.describe()
        release.set()
        await task
        await asyncio.wait_for(idle, 1)
        assert outstanding.running == 0

    run(scenario())
