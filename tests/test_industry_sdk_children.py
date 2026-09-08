"""What owning an SDK subprocess depends on, asserted against the SDK.

C2 round 3: ``SubprocessCLITransport.close()`` shields its terminate/kill
escalation with AnyIO, which does not hold against a raw asyncio
cancellation, so an interruption during cleanup leaves the CLI child
running while the attempt that started it reports and gives up its
admission slot.

``industry.sdk_children`` is the one place that reads the SDK's private
registry of live children, and it depends on three things the SDK does
not promise: the registry is where it is, ``ClaudeAgentOptions.env``
reaches the child's environment, and an interrupted ``close()`` leaves a
live child behind rather than reaping it. These tests run a real
transport against a stand-in CLI and assert all three, so an SDK upgrade
that changes any of them fails here -- loudly, at the boundary -- rather
than silently leaving a model process unowned in production.
"""

import asyncio
import contextlib
import gc
import os
import pathlib
import signal
import stat
import time

import claude_agent_sdk
import pytest
from claude_agent_sdk._internal.transport import subprocess_cli

from industry import sdk_children

# A stand-in for the Claude CLI: it answers the SDK's version probe and
# then does nothing at all -- no protocol, no exit on stdin EOF -- so the
# session always ends on its deadline and the child is still there for
# the transport's cleanup to escalate against.
PEER = """\
#!/usr/bin/env python3
import signal
import sys
import time

if "-v" in sys.argv or "--version" in sys.argv:
    print("2.99.0 (Claude Code)")
    raise SystemExit(0)
if "deaf" in sys.argv[0]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    time.sleep(0.5)
"""


def peer(tmp_path, name="fake_claude"):
    """A stand-in CLI executable; ``deaf`` ones ignore SIGTERM."""
    path = tmp_path / name
    path.write_text(PEER)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def options_for(cli, session_id):
    """The worker's own SDK options, pointed at the stand-in CLI."""
    return claude_agent_sdk.ClaudeAgentOptions(
        model="claude-sonnet-5",
        system_prompt="s",
        tools=[],
        max_turns=3,
        setting_sources=[],
        env={
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            **sdk_children.marked_env(session_id),
        },
        cli_path=str(cli),
    )


def arm(monkeypatch, grace=0.3, signals=0.3):
    """Skip the version probe and shorten the teardown's waits."""
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(sdk_children, "TEARDOWN_GRACE_S", grace)
    monkeypatch.setattr(sdk_children, "SIGNAL_GRACE_S", signals)


def marker_of(pid):
    """The session a running process is marked with, if any."""
    try:
        entries = (
            pathlib.Path(f"/proc/{pid}/environ")
            .read_bytes()
            .decode("utf-8", "replace")
            .split("\0")
        )
    except OSError:
        return None
    prefix = f"{sdk_children.MARKER}="
    for entry in entries:
        if entry.startswith(prefix):
            return entry[len(prefix) :]
    return None


async def marked_session(timeout=5.0):
    """The session id of some marked SDK child, once one is running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for child in list(sdk_children.registry()):
            if child.returncode is None:
                session = marker_of(child.pid)
                if session is not None:
                    return session
        await asyncio.sleep(0.02)
    raise AssertionError("no marked SDK child appeared")


async def wait_for_child(session_id, timeout=5.0):
    """Wait until this session's child is running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sdk_children.live(session_id):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"no SDK child appeared for {session_id}")


async def abandon(cli, session_id, deadline=0.3, into_cleanup=0.1):
    """Run a real session, then interrupt its cleanup the way C2r3-1 did.

    The consumption is cancelled on its deadline, which starts the
    transport's shielded close, and cancelled again once cleanup is
    under way: a raw asyncio cancellation the AnyIO shield does not
    defer.
    """

    async def consume():
        async for _ in claude_agent_sdk.query(
            prompt="hi", options=options_for(cli, session_id)
        ):
            pass

    task = asyncio.ensure_future(consume())
    await wait_for_child(session_id)
    try:
        await asyncio.wait_for(asyncio.shield(task), deadline)
    except asyncio.TimeoutError:
        pass
    task.cancel()
    await asyncio.sleep(into_cleanup)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


async def forget(*sessions):
    """End and forget these sessions' children, inside the running loop.

    The transports are dropped while their loop is still open, so a
    deliberately abandoned child leaves no finalizer complaining at
    interpreter shutdown.
    """
    children = [c for s in sessions for c in sdk_children.live(s)]
    for child in children:
        with contextlib.suppress(OSError):
            child.kill()
    while any(child.returncode is None for child in children):
        await asyncio.sleep(0.02)
    registry = sdk_children.registry()
    for child in list(registry):
        if child.returncode is not None:
            registry.discard(child)
    children.clear()
    gc.collect()
    await asyncio.sleep(0)


@pytest.fixture(name="reaped")
def _reaped():
    """Leave no stand-in CLI behind, whatever the test asserted."""
    yield
    for child in list(sdk_children.registry()):
        if child.returncode is None and marker_of(child.pid) is not None:
            with contextlib.suppress(OSError):
                os.kill(child.pid, signal.SIGKILL)


def test_an_interrupted_sdk_cleanup_leaves_a_live_child_the_sdk_records(
    tmp_path, monkeypatch, reaped
):
    # The three facts the adapter rests on, in one real session: the
    # child carries the session's environment marker, an interrupted
    # close() leaves it running, and the SDK keeps the un-reaped child
    # in the registry this module reads.
    del reaped
    arm(monkeypatch, grace=30.0)
    cli = peer(tmp_path)

    async def go():
        await abandon(cli, "T2.1")
        alive = sdk_children.live("T2.1")
        assert alive, "the SDK reaped the child of an interrupted cleanup"
        child = alive[0]
        assert child.returncode is None
        assert child in sdk_children.registry()
        assert marker_of(child.pid) == "T2.1"
        # The mark names one session: a sibling never claims this child.
        assert not sdk_children.live("T2.2")
        pid = child.pid
        await forget("T2.1")
        return pid

    pid = asyncio.run(go())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_the_teardown_ends_a_child_the_sdk_left_running(
    tmp_path, monkeypatch, reaped
):
    # The remedy: the attempt takes the child over and the future it
    # settles on completes only once the process has really terminated.
    del reaped
    arm(monkeypatch, grace=0.3)
    cli = peer(tmp_path)

    async def go():
        await abandon(cli, "T2.1")
        alive = sdk_children.live("T2.1")
        assert alive, "the scenario needs a surviving subprocess"
        pid = alive[0].pid
        watch = sdk_children.Watch("T2.1")
        assert f"SDK subprocess {pid} still running" == watch.describe()
        ended = watch.close()
        assert not ended.done(), "released the slot over a live process"
        await asyncio.wait_for(ended, 5)
        assert alive[0].returncode is not None
        assert not sdk_children.live("T2.1")
        assert watch.describe() == ""
        await forget("T2.1")
        return pid

    pid = asyncio.run(go())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_child_that_ignores_sigterm_is_killed_and_only_then_released(
    tmp_path, monkeypatch, reaped
):
    # The escalation is the attempt's own, not the SDK's: a child that
    # ignores SIGTERM keeps the slot until SIGKILL has ended it.
    del reaped
    arm(monkeypatch, grace=0.3, signals=0.3)
    cli = peer(tmp_path, name="fake_claude--deaf")

    async def go():
        await abandon(cli, "T2.1")
        assert sdk_children.live("T2.1"), "the scenario needs a survivor"
        started = time.monotonic()
        ended = sdk_children.Watch("T2.1").close()
        await asyncio.wait_for(ended, 5)
        # The grace, then SIGTERM ignored for its own grace, then SIGKILL.
        assert time.monotonic() - started >= 0.6
        assert not sdk_children.live("T2.1")
        await forget("T2.1")

    asyncio.run(go())


def test_a_session_with_no_child_settles_at_once(monkeypatch):
    # The ordinary path: nothing was started, or the SDK reaped it, so
    # the slot is released without waiting for anything.
    arm(monkeypatch)

    async def go():
        ended = sdk_children.Watch("T2.1").close()
        assert ended.done()
        await ended

    asyncio.run(go())


def test_an_sdk_that_no_longer_records_its_children_is_refused(monkeypatch):
    # The compatibility check: an upgrade that moves or renames the
    # registry stops the program instead of silently owning nothing.
    monkeypatch.delattr(subprocess_cli, "_ACTIVE_CHILDREN")
    with pytest.raises(sdk_children.UnsupportedSDK, match="_ACTIVE_CHILDREN"):
        sdk_children.registry()
    monkeypatch.setattr(subprocess_cli, "_ACTIVE_CHILDREN", [], raising=False)
    with pytest.raises(sdk_children.UnsupportedSDK):
        sdk_children.Watch("T2.1")
