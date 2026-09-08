"""The CLI child processes the Claude Agent SDK starts, and whose they are.

The SDK runs each session in a ``claude`` subprocess and ends it in
``SubprocessCLITransport.close()``. That close is shielded with AnyIO
only, and an AnyIO shield defers only an AnyIO cancellation: a raw
asyncio cancellation -- ``asyncio.wait_for`` firing, a bare
``task.cancel()``, an interrupted run -- is still delivered at the next
await inside it, so an interruption during cleanup escapes the
terminate/kill escalation and leaves the child running. The SDK says so
itself, in that method's docstring, and keeps the un-reaped child in its
``_ACTIVE_CHILDREN`` registry for its ``atexit`` reaper -- which only
runs when this process exits.

That child is a live model session: the attempt's own work, no less than
the threads its tools started. This module is the one place in the
program that reads the SDK's registry, so the coupling to a private name
lives here and nowhere else. A session marks its child through the one
environment variable the SDK merges into the child's environment
(``MARKER``); ``live`` finds the marked children that are still running;
and ``Watch.close`` owns whatever is left after the session ended -- it
gives the SDK's own escalation its whole budget, repeats it itself if
the child is still there, and completes only once every marked child has
really gone. That completion is what the attempt's admission slot
settles on, so a cancelled cleanup keeps the slot rather than freeing it
over a model process that is still alive.

``registry`` states what this depends on and refuses to guess when it
does not hold; ``tests/test_industry_sdk_children.py`` asserts the same
things against the installed SDK, through a real transport, so an
upgrade that changes the registry, the environment merge, or the
cancellation behaviour of ``close()`` fails there rather than silently
leaving a child unowned.
"""

import asyncio
import os
import time
from typing import Any

from claude_agent_sdk._internal.transport import subprocess_cli

# The environment variable a session's options carry so its child can be
# told from every other SDK child of this process (a sibling attempt's,
# a role call's). The SDK merges ``ClaudeAgentOptions.env`` into the
# child's environment, and Linux exposes it at /proc/<pid>/environ.
MARKER = "EVIDENCE_ALPHA_SESSION"
# How long the SDK's own cleanup is given, once the session has ended,
# before this module escalates: its close() bounds every await it makes
# and needs about 20 s in the worst case (5 s graceful, 5 s after
# SIGTERM, 5 s after SIGKILL, 5 s for the stdin lock).
TEARDOWN_GRACE_S = 20.0
# How long each of this module's own signals is given to be obeyed.
SIGNAL_GRACE_S = 5.0
# The child's exit is reported by the loop's child watcher, not by
# whoever awaits it, so ``returncode`` is polled rather than waited on:
# the SDK's own close() may be awaiting the same process.
POLL_S = 0.05

# The teardowns still running, held so the loop does not collect a task
# nothing else refers to.
_RUNNING: set[asyncio.Task] = set()


class UnsupportedSDK(RuntimeError):
    """The installed SDK does not expose what this module reads.

    Raised instead of carrying on without it: not seeing the children
    would mean releasing an attempt's admission slot over a live model
    process, which is the defect this module exists to prevent.
    """


def registry() -> set:
    """The SDK's own record of the CLI children this process started.

    The one read of a private SDK name in this program, and the one
    check that it is still there.

    Raises:
      UnsupportedSDK: If the SDK no longer records its live children
        where this module reads them, or the environment of a running
        process cannot be read on this platform.
    """
    live_children = getattr(subprocess_cli, "_ACTIVE_CHILDREN", None)
    if not isinstance(live_children, set):
        raise UnsupportedSDK(
            "claude_agent_sdk no longer keeps its live CLI children in "
            "_internal.transport.subprocess_cli._ACTIVE_CHILDREN; an "
            "attempt cannot own the process it started."
        )
    if not os.path.isdir(f"/proc/{os.getpid()}"):
        raise UnsupportedSDK(
            "this platform has no /proc, so an SDK child cannot be "
            "matched to the session that started it."
        )
    return live_children


def marked_env(session_id: str) -> dict[str, str]:
    """The environment entry that marks one session's child as its own."""
    return {MARKER: session_id}


def _marked(pid: int, session_id: str) -> bool:
    """Whether the running process ``pid`` carries this session's mark."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as handle:
            entries = handle.read().decode("utf-8", "replace").split("\0")
    except OSError:
        # The child is gone, or on its way out: nothing to own.
        return False
    return f"{MARKER}={session_id}" in entries


def live(session_id: str) -> list[Any]:
    """The children of this session that are still running.

    A child the SDK reaped is dropped from its registry, and one that
    exited but was not dropped has a return code; neither is live. The
    rest are matched by their environment, so a sibling attempt's child
    and a role call's are never claimed here.
    """
    return [
        child
        for child in list(registry())
        if child.returncode is None and _marked(child.pid, session_id)
    ]


class Watch:
    """One session's claim on the SDK child it starts.

    Args:
      session_id: The attempt id the session's options are marked with.

    Raises:
      UnsupportedSDK: If the installed SDK cannot be watched.
    """

    def __init__(self, session_id: str) -> None:
        # Refuse a session whose child this program could not own.
        registry()
        self.session_id = session_id

    def live(self) -> list[Any]:
        """The session's children that are still running."""
        return live(self.session_id)

    def describe(self) -> str:
        """The surviving children in one phrase, or ``''`` when none."""
        running = self.live()
        if not running:
            return ""
        pids = ", ".join(str(child.pid) for child in running)
        return f"SDK subprocess {pids} still running"

    def close(self) -> asyncio.Future:
        """Own what is left of the session's child; done when it has gone.

        Synchronous on purpose. It is called from a ``finally`` that may
        already be unwinding a cancellation, so the teardown is started
        before any await can interrupt it, and it runs as its own task:
        neither a further cancellation of the caller nor the end of the
        caller's coroutine stops it.

        Returns:
          A future that completes once every child of this session has
          really terminated -- at once when none is running.
        """
        loop = asyncio.get_running_loop()
        ended = loop.create_future()
        children = self.live()
        if not children:
            ended.set_result(None)
            return ended
        task = asyncio.ensure_future(_end(children, ended))
        _RUNNING.add(task)
        task.add_done_callback(_RUNNING.discard)
        return ended


async def _exited(children: list[Any], seconds: float) -> bool:
    """Wait for every child to have a return code; ``False`` on timeout."""
    deadline = time.monotonic() + seconds
    while any(child.returncode is None for child in children):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_S)
    return True


async def _end(children: list[Any], ended: asyncio.Future) -> None:
    """Wait out the SDK's cleanup, then end what it left, then report.

    The future is resolved only once every child has terminated: while
    one is alive the slot settled on it stays held, which is the point.
    """
    if not await _exited(children, TEARDOWN_GRACE_S):
        for stop in ("terminate", "kill"):
            alive = [c for c in children if c.returncode is None]
            if not alive:
                break
            for child in alive:
                try:
                    getattr(child, stop)()
                except OSError:
                    # It exited between the check and the signal.
                    pass
            if await _exited(children, SIGNAL_GRACE_S):
                break
    while any(child.returncode is None for child in children):
        # Nothing left to escalate to; the slot is held until it goes.
        await asyncio.sleep(POLL_S)
    if not ended.done():
        ended.set_result(None)
