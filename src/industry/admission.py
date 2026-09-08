"""The one admission authority of a process: what model work is live.

Every model session this program starts -- a role call through the
CrewAI adapter and a tool-using worker session through the SDK alike --
takes a slot here before it starts and holds it until its work has
actually ended, the blocking calls its tools started included.
``Limits.concurrency`` bounds the slots, so roles and workers share one
bound, and the bound holds during cleanup and retry, not only in steady
state.

An entry leaves when the operation ends, never when the coroutine that
started it unwinds. A slot whose coroutine is torn away (an
interruption, a sibling's failure cancelling the superstep, a second
interruption during a drain) or whose cleanup outlived its grace is
*retained*: it stays held, marked a survivor, and is released by the
operation's own completion. While any survivor is live, nothing new is
admitted anywhere in the process -- not a retry in the same runtime,
not a resumed attempt, not the next Studio run, not delivery -- and the
caller gets ``Blocked``, which ends its run with the checkpoint intact
rather than starting work over something still running. Once the
survivor ends, admission is open again and a resume goes on.

The authority is per process (one ``budget.Runtime``), as the index lock
always was; two processes are outside its reach.
"""

import asyncio
import functools
from collections.abc import Callable
from typing import Any


def when_all(*pending: asyncio.Future | None) -> asyncio.Future | None:
    """One future for several ends, done once every one of them is.

    What an operation still holds is rarely one thing: a worker session
    owns both the threads its tools started and the SDK subprocess that
    ran it, and its slot ends with the last of them. ``None`` entries
    are ends that never began.

    Returns:
      A future completing when every given future has, or ``None`` when
      none was given -- which ``Slot.settle`` reads as "nothing to wait
      for".
    """
    waiting = [f for f in pending if f is not None and not f.done()]
    if not waiting:
        return None
    if len(waiting) == 1:
        return waiting[0]
    combined = asyncio.get_running_loop().create_future()
    left = set(range(len(waiting)))

    def ended(index: int, _: asyncio.Future) -> None:
        left.discard(index)
        if not left and not combined.done():
            combined.set_result(None)

    for index, future in enumerate(waiting):
        future.add_done_callback(functools.partial(ended, index))
    return combined


class Blocked(RuntimeError):
    """An operation that outlived its cancellation is still live.

    Raised by ``Admission.acquire`` and ``Admission.check`` instead of
    admitting anything while a survivor is held. It is not one call's
    deadline (``crew.RoleTimeout``, ``crew.RoleHung``): the graph does
    not degrade it, so the run stops resumably at the node that met it.
    """


class Slot:
    """One admitted operation and what it still holds.

    Attributes:
      kind: ``role`` or ``session``.
      label: The role's name or the attempt's id.
      survivor: ``True`` once the slot outlived the coroutine that took
        it and is now released by the work's own completion.
    """

    def __init__(
        self,
        authority: "Admission",
        kind: str,
        label: str,
        describe: Callable[[], str] | None,
    ) -> None:
        self._authority = authority
        self.kind = kind
        self.label = label
        self.survivor = False
        self._describe = describe
        self.held = True

    def describe(self) -> str:
        """The slot in one phrase, with what is still running if known."""
        text = f"{self.kind} {self.label}"
        if self._describe is not None:
            text += f" ({self._describe()})"
        return text

    def release(self) -> None:
        """Give the slot back; idempotent."""
        if not self.held:
            return
        self.held = False
        self._authority.forget(self)

    def settle(self, pending: Any) -> None:
        """Release now if the work has ended, else retain until it does.

        ``pending`` is the future of the operation's real end (a role's
        kickoff task, the worker's outstanding calls becoming idle and
        its SDK subprocess terminating -- ``when_all`` of both) or
        ``None`` when nothing was started. A slot that cannot be released
        here stays held as a survivor and is released by that future's
        completion, on this loop, whatever became of the caller.
        """
        if not self.held:
            return
        if pending is None or pending.done():
            self.release()
            return
        self.survivor = True
        pending.add_done_callback(lambda _: self.release())
        # Whoever waits for this slot must not keep waiting for it.
        self._authority.notify()


class Admission:
    """The slots of one process, shared by role calls and worker sessions.

    Args:
      concurrency: How many operations may hold a slot at once; ``None``
        for no bound (callers without a runtime, such as the Phase 6-9
        workflow, still get survivor tracking).
    """

    def __init__(self, concurrency: int | None) -> None:
        self.concurrency = concurrency
        self._held: list[Slot] = []
        self._waiters: list[asyncio.Future] = []

    def live(self) -> list[Slot]:
        """Every slot held now, owned or surviving."""
        return list(self._held)

    def survivors(self) -> list[Slot]:
        """The slots whose coroutines are gone and whose work is not."""
        return [slot for slot in self._held if slot.survivor]

    @property
    def free(self) -> int | None:
        """Slots not held; ``None`` when unbounded."""
        if self.concurrency is None:
            return None
        return max(0, self.concurrency - len(self._held))

    def check(self) -> None:
        """Raise ``Blocked`` if a survivor is live in this process."""
        survivors = self.survivors()
        if survivors:
            listed = ", ".join(slot.describe() for slot in survivors)
            raise Blocked(
                f"{len(survivors)} earlier operation(s) are still live after "
                f"their cancellation: {listed}; nothing new starts in this "
                "process until they end. The run stops with its checkpoint "
                "intact; resume it once they have ended."
            )

    async def acquire(
        self,
        kind: str,
        label: str,
        describe: Callable[[], str] | None = None,
    ) -> Slot:
        """Take a slot, waiting for one held by owned work if need be.

        The wait is bounded by the holders' own deadlines and graces: a
        holder that outlives its cleanup becomes a survivor, every
        waiter is woken, and each raises ``Blocked`` instead of taking
        its place. Cancellation while waiting takes nothing.
        """
        while True:
            self.check()
            if self.concurrency is None or len(self._held) < self.concurrency:
                slot = Slot(self, kind, label, describe)
                self._held.append(slot)
                return slot
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            finally:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)

    def forget(self, slot: Slot) -> None:
        """Drop a released slot and wake the waiters (called by ``Slot``)."""
        if slot in self._held:
            self._held.remove(slot)
        self.notify()

    def notify(self) -> None:
        """Wake every waiter so it re-checks the slots and the survivors."""
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
