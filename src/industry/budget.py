"""Budget accounting, admission rules, and the in-process run meter.

``ledger`` is the only accounting path: every tool-using attempt and
every single-call reservation (``single_calls``, written by the
reserve node that precedes each model node) counts once, as its
observed usage when it finished or as its reservation while it is
running, unknown, or failed without usage; ``usage_events`` carries
anything else a node reports. Routers, the CLI, and Studio all read this
function, so no two of them can disagree about what a run has spent.

The ``RunMeter`` bounds what is in flight inside one process: attempts
are registered when ``dispatch`` creates them, tool handlers ask it for
admission before doing work, and a worker whose attempt is not
registered (a replayed ``Send`` in a fresh process) does no work at all.
"""

import asyncio
import dataclasses
import math
import threading

from industry import records
from industry import state as state_module


@dataclasses.dataclass(frozen=True)
class Ledger:
    """What a run has consumed so far, conservatively.

    Attributes:
      turns: Model turns (observed, or reserved while unknown).
      tool_calls: Admitted tool executions (observed or reserved).
      task_executions: Attempts created.
      wall_clock_s: Sum of completed durations and reserved seconds.
      unknown_attempts: Attempts charged their reservation.
      cost_usd: Observed cost where the SDK exposed it, else ``None``.
      input_tokens: Observed input tokens.
      output_tokens: Observed output tokens.
    """

    turns: int
    tool_calls: int
    task_executions: int
    wall_clock_s: float
    unknown_attempts: int
    cost_usd: float | None
    input_tokens: int
    output_tokens: int


@dataclasses.dataclass(frozen=True)
class Remaining:
    """What the limits still allow, before reserves."""

    turns: int
    tool_calls: int
    task_executions: int
    seconds: float


def attempt_charge(attempt: records.Attempt) -> records.Usage:
    """Return what one attempt counts for: observed usage or reservation.

    An observed usage marked ``unknown`` (a transport failure exposed
    nothing) is informational only; the reservation is charged.
    """
    observed = attempt.observed
    if (
        attempt.status in ("done", "failed")
        and observed is not None
        and not observed.unknown
    ):
        return observed
    return records.Usage(
        turns=attempt.reserved.turns,
        tool_calls=attempt.reserved.tool_calls,
        duration_s=attempt.reserved.seconds,
        unknown=True,
    )


def ledger(state: state_module.IndustryState) -> Ledger:
    """Sum every attempt (once) and every single-call usage event."""
    total = records.Usage()
    unknown = 0
    attempts = state.get("attempts", {})
    for attempt in attempts.values():
        charge = attempt_charge(attempt)
        if charge.unknown:
            unknown += 1
        total = total + charge
    for call in state.get("single_calls", {}).values():
        charge = attempt_charge(call)
        if charge.unknown:
            unknown += 1
        total = total + charge
    for event in state.get("usage_events", []):
        total = total + event
    return Ledger(
        turns=total.turns,
        tool_calls=total.tool_calls,
        task_executions=len(attempts),
        wall_clock_s=total.duration_s,
        unknown_attempts=unknown,
        cost_usd=total.cost_usd,
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
    )


def remaining(
    state: state_module.IndustryState, limits: records.Limits
) -> Remaining:
    """What the limits still allow after the ledger, before reserves."""
    spent = ledger(state)
    return Remaining(
        turns=max(0, limits.model_calls - spent.turns),
        tool_calls=max(0, limits.tool_calls - spent.tool_calls),
        task_executions=max(0, limits.task_executions - spent.task_executions),
        seconds=max(0.0, limits.wall_clock_s - spent.wall_clock_s),
    )


def reservation_for(limits: records.Limits) -> records.Reservation:
    """The allowance one tool-using attempt is charged until observed."""
    return records.Reservation(
        turns=limits.max_turns,
        tool_calls=limits.tools_per_attempt,
        seconds=limits.task_timeout_s,
    )


def expected_task_s(
    state: state_module.IndustryState, limits: records.Limits
) -> float:
    """The longest observed attempt, or the configured expectation."""
    durations = [
        attempt.duration_s
        for attempt in state.get("attempts", {}).values()
        if attempt.duration_s is not None
    ]
    return max(durations) if durations else limits.expected_task_s


def dispatchable(
    state: state_module.IndustryState,
    limits: records.Limits,
    keep_acquisition_slot: bool,
) -> int:
    """How many attempts may start now within every limit and reserve.

    Args:
      state: The state before dispatch.
      limits: The run's limits.
      keep_acquisition_slot: Whether one task execution stays reserved
        for the verifier's acquisition (until the review has run once).

    Returns:
      The number of attempts whose reservations fit: task executions
      (minus the kept slot), turns after the model-call reserve, tool
      calls, and wall clock after the time reserve, where a wave of
      ``n`` attempts at the configured concurrency is expected to take
      ``ceil(n / concurrency) * expected_task_s``.
    """
    left = remaining(state, limits)
    executions = left.task_executions - (1 if keep_acquisition_slot else 0)
    turns = (left.turns - limits.model_call_reserve) // limits.max_turns
    tools = left.tool_calls // limits.tools_per_attempt
    seconds = left.seconds - limits.time_reserve_s
    expected = expected_task_s(state, limits)
    waves = math.floor(seconds / expected) if expected > 0 else 0
    by_time = waves * limits.concurrency
    return max(0, min(executions, turns, tools, by_time))


def admit_single_call(
    state: state_module.IndustryState, limits: records.Limits, node: str
) -> int:
    """Return the ``max_turns`` a single-call node may use now, or 0.

    Intermediate nodes need a full call's turns left after the
    model-call reserve and some wall clock left after the time reserve;
    the reserved nodes (``write``, ``final_review``) may spend the
    reserve itself. A result of 0 means the node is skipped.
    """
    left = remaining(state, limits)
    if node in state_module.RESERVED_NODES:
        if left.seconds <= 0:
            return 0
        return min(limits.single_call_turns, left.turns)
    if left.seconds - limits.time_reserve_s <= 0:
        return 0
    allowed = min(
        limits.single_call_turns, left.turns - limits.model_call_reserve
    )
    return allowed if allowed >= limits.single_call_turns else 0


class RunMeter:
    """Concurrency-safe in-flight allowance of one thread in one process.

    Registered attempts each hold a tool allowance; ``admit`` takes one
    admitted execution from the attempt and from the global remainder,
    or refuses. Refusals are counted per attempt so the worker can
    report them as ``denied_tool_calls``.
    """

    def __init__(self, global_tool_calls: int) -> None:
        self._lock = threading.Lock()
        self._global = max(0, global_tool_calls)
        self._allowance: dict[str, int] = {}
        self._admitted: dict[str, int] = {}
        self._denied: dict[str, int] = {}

    def register(self, attempt_id: str, tool_allowance: int) -> None:
        """Admit an attempt with its per-attempt tool allowance."""
        with self._lock:
            self._allowance[attempt_id] = max(0, tool_allowance)
            self._admitted.setdefault(attempt_id, 0)
            self._denied.setdefault(attempt_id, 0)

    def is_admitted(self, attempt_id: str) -> bool:
        """Whether ``dispatch`` in this process registered the attempt."""
        with self._lock:
            return attempt_id in self._allowance

    def admit(self, attempt_id: str) -> bool:
        """Take one tool execution for the attempt; ``False`` if refused."""
        with self._lock:
            if self._allowance.get(attempt_id, 0) <= 0 or self._global <= 0:
                self._denied[attempt_id] = self._denied.get(attempt_id, 0) + 1
                return False
            self._allowance[attempt_id] -= 1
            self._global -= 1
            self._admitted[attempt_id] += 1
            return True

    def counts(self, attempt_id: str) -> tuple[int, int]:
        """Return ``(admitted, denied)`` executions of the attempt."""
        with self._lock:
            return (
                self._admitted.get(attempt_id, 0),
                self._denied.get(attempt_id, 0),
            )

    @property
    def global_remaining(self) -> int:
        """Tool executions still admissible across every attempt."""
        with self._lock:
            return self._global


class Runtime:
    """Per-process, non-checkpointed resources of a compiled graph.

    Attributes:
      limits: The limits every thread on this graph runs under.
      semaphore: Bounds the tool-using SDK sessions in flight.
      index_lock: Serializes writes to the vector index.
    """

    def __init__(self, limits: records.Limits | None = None) -> None:
        self.limits = limits or records.Limits()
        self.semaphore = asyncio.Semaphore(self.limits.concurrency)
        self.index_lock = asyncio.Lock()
        self._meters: dict[str, RunMeter] = {}

    def begin(self, thread_id: str) -> None:
        """Start an invocation: every earlier admission of the thread is void.

        Called by each entry point (CLI, Studio) before ``ainvoke`` or
        ``astream``, for a new run and for a resume alike, so a ``Send``
        replayed from an earlier invocation finds no admitted attempt,
        even in the same process (§4.6b of the plan).
        """
        self._meters.pop(thread_id, None)

    def new_meter(
        self, thread_id: str, state: state_module.IndustryState
    ) -> RunMeter:
        """Create (or replace) the thread's meter from the ledger."""
        left = remaining(state, self.limits)
        meter = RunMeter(left.tool_calls)
        self._meters[thread_id] = meter
        return meter

    def meter_for(self, thread_id: str) -> RunMeter | None:
        """The thread's meter, or ``None`` when this process made none."""
        return self._meters.get(thread_id)

    def drop(self, thread_id: str) -> None:
        """Forget the thread's meter once its wave has been merged."""
        self._meters.pop(thread_id, None)
