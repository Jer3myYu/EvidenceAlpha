"""Budget accounting, admission rules, and the in-process run meter.

``ledger`` is the only accounting path: every tool-using attempt and
every single-call reservation (``single_calls``, written by the
reserve node that precedes each model node) counts once, as its
observed usage when it finished or as its reservation while it is
running, unknown, or failed without usage. Nothing else is charged:
there is no second accounting path. Routers, the CLI, and Studio all read this
function, so no two of them can disagree about what a run has spent.

The ``RunMeter`` bounds what is in flight inside one process: attempts
are registered when ``dispatch`` creates them, tool handlers ask it for
admission before doing work, and a worker whose attempt is not
registered (a replayed ``Send`` in a fresh process) does no work at all.
What may be *live* at all -- role calls and worker sessions against
``Limits.concurrency``, and the work that outlived its cancellation --
is the ``Runtime``'s ``admission`` (``industry.admission``), the one
authority both model entry points consult.
"""

import asyncio
import dataclasses
import datetime
import math
import threading
from typing import Any

from industry import admission as admission_module
from industry import merge
from industry import records
from industry import state as state_module


def invocation_timing(state: state_module.IndustryState) -> dict[str, Any]:
    """Measure actual invocation and queue time without changing charges."""
    attempts = list(state.get("attempts", {}).values()) + list(
        state.get("single_calls", {}).values()
    )
    invoked = 0
    seconds = 0.0
    queue = 0.0
    unknown = 0
    for attempt in attempts:
        if attempt.reserved.held:
            continue
        if not attempt.invoked_at:
            if attempt.admitted_at and attempt.finished_at:
                # The owner ended before reaching the SDK.
                continue
            # Released, unused reservations are not model invocations.
            if attempt.observed is None or attempt.observed.turns:
                unknown += 1
            continue
        invoked += 1
        start = datetime.datetime.fromisoformat(attempt.invoked_at)
        if attempt.queued_at:
            wait = (
                start - datetime.datetime.fromisoformat(attempt.queued_at)
            ).total_seconds()
            queue += max(0.0, wait)
            unknown += int(wait < 0)
        else:
            unknown += 1
        if attempt.finished_at:
            duration = (
                datetime.datetime.fromisoformat(attempt.finished_at) - start
            ).total_seconds()
            seconds += max(0.0, duration)
            unknown += int(duration < 0)
        else:
            unknown += 1
    return {
        "invoked_sessions": invoked,
        "invocation_session_s": round(seconds, 3),
        "session_queue_s": round(queue, 3),
        "unknown_session_timings": unknown,
        "invocation_timing_complete": not unknown,
    }


@dataclasses.dataclass(frozen=True)
class Ledger:
    """What a run has consumed so far, conservatively.

    Attributes:
      turns: Model turns (observed, or reserved while unknown).
      tool_calls: Admitted tool executions (observed or reserved).
      task_executions: Attempts created.
      wall_clock_s: **Charged** seconds: observed where an execution
        reported, reserved where it did not. This is what admission
        spends against ``Limits.wall_clock_s`` and it is neither elapsed
        time nor a sum of observed durations -- an uninvoked held
        final-review reservation contributes its full allowance here
        with no execution behind it (plan D-U15).
      observed_session_s: The sum of durations executions actually
        reported. Accumulated session time, not elapsed launch time:
        with two concurrent workers it exceeds the wall clock, and with
        held reservations it is smaller than ``wall_clock_s``.
      unknown_attempts: Attempts charged their reservation.
      cost_usd: Observed cost where the SDK exposed it, else ``None``.
      cost_complete: Whether every counted execution exposed a cost. A
        missing cost is unknown, and ``cost_usd`` under a false flag is
        a subtotal rather than a total.
      usage_complete: Whether every counted execution exposed the cache
        categories too. Run 7's totals are cost-complete and
        usage-incomplete: the $9.19 is a real SDK estimate, and the 144
        input tokens behind it are not the context volume.
      input_tokens: Observed ordinary input tokens; not context volume.
      output_tokens: Observed output tokens.
      cache_creation_input_tokens: Observed cache writes.
      cache_read_input_tokens: Observed cache reads.
    """

    turns: int
    tool_calls: int
    task_executions: int
    wall_clock_s: float
    unknown_attempts: int
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    observed_session_s: float = 0.0
    cost_complete: bool = True
    usage_complete: bool = True
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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
    # Turns and tool calls are unknown, so the reservation stands; the
    # wall clock is measured locally and is charged as observed when the
    # attempt recorded it (an attempt that never reported keeps the
    # reserved seconds).
    measured = (
        observed.duration_s
        if observed is not None and observed.duration_s > 0
        else attempt.reserved.seconds
    )
    return records.Usage(
        turns=attempt.reserved.turns,
        tool_calls=attempt.reserved.tool_calls,
        duration_s=measured,
        unknown=True,
    )


def ledger(state: state_module.IndustryState) -> Ledger:
    """Sum every attempt (once) and every single-call usage event.

    Two different measures come out of the same walk: what the run is
    *charged* (``wall_clock_s``, which admission spends) and what it was
    *observed* to consume (``observed_session_s``). Conflating them is
    what let 5,038 elapsed seconds, 5,014.607 accumulated session
    seconds and a field named ``wall_clock_s`` all read as one number.
    """
    total = records.Usage()
    unknown = 0
    observed_seconds = 0.0
    costed = counted = captured = 0
    attempts = state.get("attempts", {})
    executions = list(attempts.values()) + list(
        state.get("single_calls", {}).values()
    )
    for execution in executions:
        charge = attempt_charge(execution)
        if charge.unknown:
            unknown += 1
        total = total + charge
        observed = execution.observed
        if observed is not None and observed.duration_s > 0:
            # A transport failure that reported no tokens still ran for
            # a measured time. Excluding it understated observed session
            # time exactly where a run was going wrong (U1-N05).
            observed_seconds += observed.duration_s
        if observed is not None and not observed.unknown:
            counted += 1
            if observed.cost_usd is not None:
                costed += 1
            if observed.complete:
                captured += 1
    return Ledger(
        turns=total.turns,
        tool_calls=total.tool_calls,
        task_executions=len(attempts),
        wall_clock_s=total.duration_s,
        unknown_attempts=unknown,
        cost_usd=total.cost_usd,
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        observed_session_s=round(observed_seconds, 3),
        # A run with an unobserved execution has no complete cost, and
        # a subtotal presented as a total is how "50% cheaper" gets
        # claimed from an incomplete measurement.
        cost_complete=unknown == 0 and costed == counted,
        usage_complete=unknown == 0 and captured == counted,
        cache_creation_input_tokens=total.cache_creation_input_tokens,
        cache_read_input_tokens=total.cache_read_input_tokens,
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
        turns=limits.attempt_turns(),
        tool_calls=limits.tools_per_attempt,
        seconds=limits.task_timeout_s,
    )


# The intermediate single calls that must still run after each stage,
# in pipeline order; ``write`` and ``final_review`` live in the reserves.
DOWNSTREAM_CALLS = {
    "scope": (
        "prepare_tasks",
        "analyze",
        "assess_coverage",
        "audit_findings",
    ),
    "prepare_tasks": ("analyze", "assess_coverage", "audit_findings"),
    "research": ("analyze", "assess_coverage", "audit_findings"),
    "review": ("analyze", "assess_coverage", "audit_findings"),
    "analyze": ("assess_coverage", "audit_findings"),
    # The pre-draft audit is a stage every route must still reach, so
    # every earlier stage keeps room for it. Without this, assessment
    # could take the last discretionary call and the analysis would go
    # to the Editor unjudged (U1-N03).
    "assess_coverage": ("audit_findings",),
    "audit_findings": (),
}


def review_batches(
    state: state_module.IndustryState, limits: records.Limits
) -> int:
    """How many review batches the unreviewed material claims need.

    ``merge.outstanding_review`` is the same selection ``graph.
    reviewable`` uses, so a deferred claim does not inflate the reserve
    for a batch the reviewer could not take (plan D-U2).
    """
    relationships = state.get("relationships", {})
    unreviewed = len(
        merge.outstanding_review(
            state.get("claims", {}),
            relationships,
            state.get("calculations", {}),
        )
    )
    return -(-unreviewed // limits.review_batch)


def repair_reservation_for(limits: records.Limits) -> records.Reservation:
    """What one repair attempt is charged (plan revision 39 §4.46.1).

    A repair opens an original its claim already names; it is not a
    research session, and reserving one as though it were is what kept
    every repair unaffordable. Turns and tools are unchanged: the
    8-exchange experiment failed with ``error_max_turns``.
    """
    return records.Reservation(
        turns=limits.attempt_turns(),
        tool_calls=limits.tools_per_attempt,
        seconds=limits.repair_timeout_s,
    )


def repair_pair_cost(limits: records.Limits) -> tuple[float, int]:
    """The seconds and turns one repair *and* its review together take."""
    return (
        limits.repair_timeout_s + limits.single_call_timeout_s,
        limits.attempt_turns() + limits.single_call_reserved(),
    )


def repair_window_open(state: state_module.IndustryState) -> bool:
    """Whether one repair pair is still earmarked for this run."""
    return state.get("repair_window", "open") == "open"


def repair_earmark(
    state: state_module.IndustryState, limits: records.Limits
) -> tuple[float, int]:
    """The seconds and turns held back for one repair pair, if any.

    An earmark of existing capacity, never new budget and never a
    charge: it stops broad dispatch and ordinary review from spending
    the last repair opportunity (plan revision 39 §4.46.3). It is gone
    once a pair has been admitted or the window has closed.
    """
    if not repair_window_open(state):
        return 0.0, 0
    return repair_pair_cost(limits)


def admit_repair_pair(
    state: state_module.IndustryState, limits: records.Limits
) -> int:
    """The review turns a repair may hold, or 0 if the pair does not fit.

    Both halves or neither. The pair is admitted from what is free
    after the delivery reserve and the downstream provisions -- its own
    earmark included, since this call is what spends it -- so a repair
    can never be funded out of what write, final review, analysis or
    coverage are keeping.
    """
    left = remaining(state, limits)
    seconds, turns = repair_pair_cost(limits)
    keep_s, keep_turns = pipeline_reserve(state, limits, "review")
    keep_s -= repair_earmark(state, limits)[0]
    keep_turns -= repair_earmark(state, limits)[1]
    fits = (
        left.seconds - limits.time_reserve_s - keep_s >= seconds
        and left.turns - limits.model_call_reserve - keep_turns >= turns
        and left.tool_calls >= limits.tools_per_attempt
        and left.task_executions >= 1
    )
    return limits.single_call_reserved() if fits else 0


def repair_shortfall(
    state: state_module.IndustryState, limits: records.Limits
) -> str:
    """Which dimension refuses a repair pair, in admission's own terms."""
    left = remaining(state, limits)
    seconds, turns = repair_pair_cost(limits)
    keep_s, keep_turns = pipeline_reserve(state, limits, "review")
    keep_s -= repair_earmark(state, limits)[0]
    keep_turns -= repair_earmark(state, limits)[1]
    if left.seconds - limits.time_reserve_s - keep_s < seconds:
        return "seconds"
    if left.turns - limits.model_call_reserve - keep_turns < turns:
        return "turns"
    if left.tool_calls < limits.tools_per_attempt:
        return "tools"
    if left.task_executions < 1:
        return "task executions"
    return "priority"


def call_timeout(node: str, limits: records.Limits) -> float:
    """What one single call of ``node`` is allowed, and reserved.

    Every node takes ``single_call_timeout_s`` except the pre-draft
    audit, which reads a compact outline rather than the registry.
    """
    return (
        limits.audit_timeout_s
        if node == "audit_findings"
        else limits.single_call_timeout_s
    )


def downstream_calls(
    state: state_module.IndustryState, stage: str
) -> tuple[str, ...]:
    """The single calls that must still run after ``stage`` on this route.

    Route S makes no coverage call, so reserving one refused research
    the route could in fact afford -- 480 s held for a session that
    never happens, and a 900 s worker turned away for it (U2-10). The
    route comes from the thread's own ``meta``, so a resumed thread
    reserves for the pipeline it is actually running.
    """
    calls = DOWNSTREAM_CALLS.get(stage, ())
    meta = state.get("meta")
    if getattr(meta, "route", "C") == "S":
        return tuple(call for call in calls if call != "assess_coverage")
    return calls


def pipeline_reserve(
    state: state_module.IndustryState, limits: records.Limits, stage: str
) -> tuple[float, int]:
    """Seconds and ``num_turns`` a stage keeps for what must follow it.

    Research dispatch (``stage="research"``) and ``review`` keep the
    review batches of the material claims collected so far plus the
    downstream single calls; later stages keep their own downstream
    calls. Headline run 3 spent its whole allowance on research and
    review batches and then had nothing left for analysis, which is
    what this reservation prevents.
    """
    downstream = downstream_calls(state, stage)
    batches = (
        review_batches(state, limits) if stage in ("research", "review") else 0
    )
    if stage == "review" and batches:
        batches -= 1  # the batch being admitted is reserved by itself
    seconds = batches * limits.review_batch_s + sum(
        call_timeout(node, limits) for node in downstream
    )
    turns = (batches + len(downstream)) * limits.single_call_reserved()
    if stage in ("research", "review"):
        # One repair pair is earmarked while the window is open, so the
        # discretionary work of these stages cannot spend it.
        held_s, held_turns = repair_earmark(state, limits)
        seconds += held_s
        turns += held_turns
    return seconds, turns


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
      The number of attempts whose full reservations fit: task
      executions (minus the kept slot), turns after the model-call
      reserve, tool calls, and wall clock after the time reserve, each
      attempt reserving ``task_timeout_s`` seconds. The same
      reservations are what the ledger charges, so the ledger can never
      exceed a limit.
    """
    left = remaining(state, limits)
    keep_s, keep_turns = pipeline_reserve(state, limits, "research")
    # An open repair window holds back the execution and the tools its
    # pair will need, not only its seconds and turns
    # (post-implementation finding 4).
    held = 1 if repair_window_open(state) else 0
    executions = (
        left.task_executions - (1 if keep_acquisition_slot else 0) - held
    )
    turns = (
        left.turns - limits.model_call_reserve - keep_turns
    ) // limits.attempt_turns()
    tools = (
        left.tool_calls - held * limits.tools_per_attempt
    ) // limits.tools_per_attempt
    seconds = left.seconds - limits.time_reserve_s - keep_s
    by_time = math.floor(seconds / limits.task_timeout_s)
    return max(0, min(executions, turns, tools, by_time))


def admit_single_call(
    state: state_module.IndustryState, limits: records.Limits, node: str
) -> int:
    """Return the ``num_turns`` a single-call node may reserve now, or 0.

    Every call reserves a full call's worst case (``num_turns`` and its
    own ``call_timeout``) or is skipped: intermediate
    nodes must fit after the reserves and after what their downstream
    stages need (``pipeline_reserve``), the reserved nodes (``write``,
    ``final_review``) may spend the reserves, which hold exactly two
    such calls. A result of 0 means the node is skipped. The session's
    ``max_turns`` is derived from the reservation by ``max_turns_for``.
    """
    left = remaining(state, limits)
    full = limits.single_call_reserved()
    if node in state_module.RESERVED_NODES:
        fits = (
            left.seconds >= limits.single_call_timeout_s and left.turns >= full
        )
    else:
        keep_s, keep_turns = pipeline_reserve(state, limits, node)
        fits = (
            left.seconds - limits.time_reserve_s - keep_s
            >= call_timeout(node, limits)
            and left.turns - limits.model_call_reserve - keep_turns >= full
        )
    return full if fits else 0


def admit_pair(
    state: state_module.IndustryState, limits: records.Limits
) -> int:
    """Return the ``num_turns`` a write *and* its final review may take.

    A substantive rewrite replaces the deliverable body, so it may only
    start when the review that would validate it is affordable too. The
    reserve was always documented as holding two complete calls; this
    is what makes that true. ``0`` means the pair does not fit and the
    rewrite must not begin.
    """
    left = remaining(state, limits)
    full = limits.single_call_reserved()
    fits = (
        left.seconds >= 2 * limits.single_call_timeout_s
        and left.turns >= 2 * full
    )
    return full if fits else 0


def max_turns_for(reserved_turns: int, limits: records.Limits) -> int:
    """The SDK ``max_turns`` that keeps a call within its reservation."""
    return max(1, reserved_turns // limits.turns_per_exchange)


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
      admission: The one admission authority: every role call and every
        worker session takes one of ``limits.concurrency`` slots from it
        and holds the slot until its work has actually ended; a survivor
        blocks every further admission in this process until it ends.
        It is never reset by ``begin``: what outlived one invocation is
        still live in the next.
      index_lock: Serializes writes to the vector index.
      floor: The Level-B usefulness bar delivery classifies against.
        One rule in one place, so it can be tuned -- and calibrated on
        fixtures -- without touching the delivery code.
      route: ``C``, the corrected existing workflow and the default, or
        ``S``, the simplified candidate (plan D-U16). Routing only:
        both routes share this runtime, the same registry, merge,
        admission, budget and delivery gate.
    """

    def __init__(
        self,
        limits: records.Limits | None = None,
        reports_dir: str = "data/reports",
        floor: Any = None,
        route: records.WorkflowRoute = "C",
    ) -> None:
        self.limits = limits or records.Limits()
        self.reports_dir = reports_dir
        self.floor = floor
        self.route = route
        self.admission = admission_module.Admission(self.limits.concurrency)
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
