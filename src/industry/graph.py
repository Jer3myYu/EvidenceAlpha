"""The industry research workflow on LangGraph.

LangGraph owns scheduling, budgets, routing, and persistence. Six roles
execute at the nodes: single structured calls through the CrewAI
adapter (Lead, Analyst, Verifier judgement, Editor) and bounded SDK
tool loops (the researchers and the Verifier's acquisition), all
reading and writing one checkpointed ``IndustryState``.

Shape::

    START -> reserve_scope -> scope -> dispatch =(Send)=> run_task -> merge
      merge -> dispatch while ready tasks remain;
               mapping phase -> reserve_prepare_tasks -> prepare_tasks
               -> dispatch;
               else -> reserve_review -> review
      review -> dispatch (acquisition tasks) | reserve_analyze
      analyze -> reserve_prepare_tasks (evidence requests, once)
               | reserve_assess_coverage
      assess_coverage -> reserve_prepare_tasks (follow-up) | reserve_write
      write -> reserve_final_review -> final_review -> remediate | deliver
      remediate -> reserve_prepare_tasks | reserve_analyze | reserve_write
      deliver -> END

After every merged wave the verifier reviews (coverage counts reviewed
claims only), the analyst writes findings (questions 4-8 count claims
a finding cites), and only then the Lead assesses coverage.

Every single-call node ``X`` is preceded by ``reserve_X``, which admits
the call against the ledger and writes its reservation to
``single_calls`` before the call starts, so an interrupted call stays
charged. Routers are pure functions of state; each decision is written
to ``route_log`` with its reason, and Studio reads the same functions.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langgraph import config as langgraph_config
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from industry import admission as admission_module
from industry import budget
from industry import calc
from industry import coverage as coverage_module
from industry import merge
from industry import pdf as pdf_module
from industry import quantities
from industry import records
from industry import report
from industry import roles
from industry import schedule
from industry import state as state_module
from industry import tools
from industry import worker as worker_module
from research import crew

SINGLE_CALL_NODES = state_module.SINGLE_CALL_NODES
# What the analyst is told about calculations (one call per reservation).
ANALYSIS_NOTE = (
    "Derived claims from earlier calculations, if any, are listed with the "
    "claims above (kind derived)."
)
# Purposes prepare_tasks plans for, by the phase it is entered from.
PURPOSES = {
    "mapping": "the first research wave after the industry map: cover "
    "every stage of the chain and select representative companies",
    "coverage_followup": "close the coverage gaps the Lead identified",
    "analysis_requests": "obtain the evidence the analyst requested",
    "remediation": "resolve the open material issues",
}


class RolesApi(Protocol):
    """The single-call roles the graph needs; tests inject fakes."""

    async def scope(
        self, question: str, max_turns: int, deadline: float
    ) -> tuple[records.Brief, records.Usage]:
        """The brief."""

    async def plan_tasks(
        self,
        state: state_module.IndustryState,
        limits: records.Limits,
        slots: int,
        purpose: str,
        max_turns: int,
        deadline: float,
    ) -> tuple[roles.TaskPlan, records.Usage]:
        """The task plan."""

    async def assess_coverage(
        self, state: state_module.IndustryState, max_turns: int, deadline: float
    ) -> tuple[records.LeadAssessment, records.Usage]:
        """The coverage proposal."""

    async def analyze(
        self,
        state: state_module.IndustryState,
        note: str,
        max_turns: int,
        deadline: float,
    ) -> tuple[roles.Analysis, records.Usage]:
        """The analysis."""

    async def review_claims(
        self,
        state: state_module.IndustryState,
        claim_ids: list[str],
        max_turns: int,
        deadline: float,
    ) -> tuple[records.ClaimReview, records.Usage]:
        """The claim review."""

    async def write(
        self,
        state: state_module.IndustryState,
        instructions: str,
        max_turns: int,
        deadline: float,
    ) -> tuple[roles.Draft, records.Usage]:
        """The draft."""

    async def final_review(
        self, state: state_module.IndustryState, max_turns: int, deadline: float
    ) -> tuple[records.DraftReview, records.Usage]:
        """The draft review."""


def _usage_of(llm: crew.ClaudeLLM, started: float) -> records.Usage:
    last = llm.last_usage or {}
    usage = last.get("usage") or {}
    return records.Usage(
        turns=int(last.get("turns") or 0),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cost_usd=last.get("cost_usd"),
        duration_s=round(time.monotonic() - started, 3),
        unknown=not last,
    )


class LiveRoles:
    """The real roles over the CrewAI adapter, returning usage too.

    Every call takes its slot from ``admission`` -- the runtime's, so
    role calls and worker sessions share one bound and one record of
    what is live in the process.
    """

    def __init__(
        self, admission: admission_module.Admission | None = None
    ) -> None:
        self.admission = admission

    async def scope(self, question, max_turns, deadline):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        brief = await roles.scope(
            question, llm, max_turns, deadline, admission=self.admission
        )
        return brief, _usage_of(llm, started)

    async def plan_tasks(
        self, state, limits, slots, purpose, max_turns, deadline
    ):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        plan = await roles.plan_tasks(
            state,
            limits,
            slots,
            purpose,
            llm,
            max_turns,
            deadline,
            admission=self.admission,
        )
        return plan, _usage_of(llm, started)

    async def assess_coverage(self, state, max_turns, deadline):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        out = await roles.assess_coverage(
            state, llm, max_turns, deadline, admission=self.admission
        )
        return out, _usage_of(llm, started)

    async def analyze(self, state, note, max_turns, deadline):
        llm = roles.llm_for("analyst", max_turns)
        started = time.monotonic()
        out = await roles.analyze(
            state, note, llm, max_turns, deadline, admission=self.admission
        )
        return out, _usage_of(llm, started)

    async def review_claims(self, state, claim_ids, max_turns, deadline):
        llm = roles.llm_for("verifier", max_turns)
        started = time.monotonic()
        out = await roles.review_claims(
            state,
            claim_ids,
            llm,
            max_turns,
            deadline,
            admission=self.admission,
        )
        return out, _usage_of(llm, started)

    async def write(self, state, instructions, max_turns, deadline):
        llm = roles.llm_for("editor", max_turns)
        started = time.monotonic()
        out = await roles.write(
            state,
            instructions,
            llm,
            max_turns,
            deadline,
            admission=self.admission,
        )
        return out, _usage_of(llm, started)

    async def final_review(self, state, max_turns, deadline):
        llm = roles.llm_for("verifier", max_turns)
        started = time.monotonic()
        out = await roles.final_review(
            state, llm, max_turns, deadline, admission=self.admission
        )
        return out, _usage_of(llm, started)


WorkerFunction = Callable[..., Awaitable[records.TaskResult]]


def initial_state(
    question: str,
    limits: records.Limits,
    fixture: str | None = None,
    fixture_digest: str | None = None,
) -> dict[str, Any]:
    """The graph input: the question and the run metadata.

    ``meta`` (workflow and schema version, models, limits, the fixture
    directory of a fixed-evidence run) is checkpointed with the input,
    before the first interruptible call, so an interruption during
    ``scope`` still leaves a resumable, correctly versioned thread and a
    resume rebuilds the same backend.
    """
    return {
        "question": question,
        "meta": records.RunMeta(
            workflow_version=state_module.WORKFLOW_VERSION,
            prompt_version=roles.PROMPT_VERSION,
            models=dict(roles.ROLE_MODELS),
            limits=limits,
            started_at=records.now_iso(),
            fixture=fixture,
            fixture_digest=fixture_digest,
        ),
    }


# --- reservations ----------------------------------------------------------


def running_reservation(
    state: state_module.IndustryState, node: str
) -> records.Attempt | None:
    """The node's open reservation, written by ``reserve_<node>``."""
    calls = state.get("single_calls", {})
    for call in sorted(
        calls.values(), key=lambda c: merge.attempt_number(c.id)
    ):
        # A held allowance is a reservation waiting to be activated by
        # its `reserve_<node>`, not a call this node is running: the
        # router must not read it as one (plan revision 39 §4.46.2).
        if (
            call.task_id == node
            and call.status == "running"
            and not call.reserved.held
        ):
            return call
    return None


def _reservation(
    state: state_module.IndustryState,
    node: str,
    limits: records.Limits,
    turns: int,
) -> records.Attempt:
    calls = state.get("single_calls", {})
    number = 1 + sum(1 for c in calls.values() if c.task_id == node)
    return records.Attempt(
        id=f"{node}.{number}",
        task_id=node,
        status="running",
        reserved=records.Reservation(
            turns=turns,
            tool_calls=0,
            seconds=limits.single_call_timeout_s,
        ),
        started_at=records.now_iso(),
    )


_LEVEL_RANK = {"diagnostic_only": 0, "partial": 1, "verified": 2}


def level_rank(level: str) -> int:
    """How good a delivery level is, for choosing between candidates."""
    return _LEVEL_RANK.get(level, 0)


_STATUS_RANK = {
    "complete": 2,
    "complete_with_limitations": 1,
    "incomplete": 0,
}


def candidate_rank(
    result: records.DeliveryResult, plan: report.DeliveryPlan
) -> tuple[int, int, int]:
    """How good a delivery candidate is, for choosing between two.

    Plan §4.41.4 ranks the level first and then prefers the body with
    an applicable successful certificate. Level A spans two statuses,
    so the status breaks what is left: a reviewed rewrite that covers
    less must not replace an equally verified incumbent that covers
    more.
    """
    certified = 1 if plan.certified and not plan.changed else 0
    return (
        level_rank(result.level),
        certified,
        _STATUS_RANK.get(result.status, 0),
    )


def stored_rank(candidate: records.DeliveryCandidate) -> tuple[int, int]:
    """How good a retained candidate is, by its recorded classification.

    Both sides of a retention decision were certified when they were
    recorded, so only the level and the status separate them.
    """
    return (level_rank(candidate.level), _STATUS_RANK.get(candidate.status, 0))


def issues_for_candidate(
    candidate: records.DeliveryCandidate,
    current: dict[str, records.Issue],
) -> dict[str, records.Issue]:
    """The issue state that applies to a retained body.

    A later draft's clean review can resolve wording that still stands
    in the retained one, so a resolution recorded against another
    ``draft_version`` does not clear it here. An issue raised since is
    applied only when its exact unit is actually in this body.
    """
    applies = dict(candidate.issues)
    body = "\n".join(section.text for section in candidate.sections)
    for issue_id, issue in current.items():
        if issue_id not in applies:
            if issue.text and issue.text in body:
                applies[issue_id] = issue
            continue
        if (
            issue.status != applies[issue_id].status
            and issue.draft_version == candidate.draft_version
        ):
            applies[issue_id] = issue
    return applies


def _with_reservation(call: records.Attempt, **changes: Any) -> records.Attempt:
    """The same single call with its reservation fields changed."""
    return call.model_copy(
        update={"reserved": call.reserved.model_copy(update=changes)}
    )


def _held_call(
    calls: dict[str, records.Attempt], node: str
) -> records.Attempt | None:
    """The allowance a paired admission is holding for ``node``."""
    for call in calls.values():
        if (
            call.task_id == node
            and call.status == "running"
            and call.reserved.held
        ):
            return call
    return None


def _held_review(calls: dict[str, records.Attempt]) -> records.Attempt | None:
    """The final-review allowance held by a write, if one is waiting."""
    return _held_call(calls, "final_review")


def reserve_node(node: str, limits: records.Limits):
    """The checkpointed admission step that precedes a single-call node."""

    async def reserve(state: state_module.IndustryState) -> dict[str, Any]:
        calls = dict(state.get("single_calls", {}))
        if node == "review":
            held = _held_call(calls, "review")
            if held is not None:
                # Taken with the repair that made it necessary and
                # charged ever since (plan revision 39 §4.46.2).
                calls[held.id] = _with_reservation(held, held=False)
                return {
                    "single_calls": calls,
                    "route_log": [
                        f"reserve_review: {held.id} activated, held since "
                        "its repair was admitted"
                    ],
                }
        if node == "final_review":
            held = _held_review(calls)
            if held is not None:
                # Its allowance was taken with the write it validates
                # and charged ever since; activating it starts no
                # second reservation.
                calls[held.id] = _with_reservation(held, held=False)
                return {
                    "single_calls": calls,
                    "route_log": [
                        f"reserve_final_review: {held.id} activated, held "
                        "since its write was admitted"
                    ],
                }
        if node == "write":
            allowed = budget.admit_pair(state, limits)
            if allowed <= 0:
                return {
                    "route_log": [
                        "reserve_write: refused, a write and its final "
                        "review do not both fit; the reviewed body stands"
                    ]
                }
            writer = _reservation(state, node, limits, allowed)
            writer = _with_reservation(writer, pair_id=writer.id)
            calls[writer.id] = writer
            review = _reservation(
                {**state, "single_calls": calls},
                "final_review",
                limits,
                allowed,
            )
            review = _with_reservation(review, pair_id=writer.id, held=True)
            calls[review.id] = review
            return {
                "single_calls": calls,
                "route_log": [
                    f"reserve_write: {writer.id} reserved with "
                    f"{review.id} held ({allowed} turns each)"
                ],
            }
        allowed = budget.admit_single_call(state, limits, node)
        if allowed <= 0:
            return {
                "route_log": [
                    f"reserve_{node}: refused, budget exhausted; {node} "
                    "will be skipped"
                ]
            }
        reservation = _reservation(state, node, limits, allowed)
        calls[reservation.id] = reservation
        return {
            "single_calls": calls,
            "route_log": [
                f"reserve_{node}: {reservation.id} reserved ({allowed} turns)"
            ],
        }

    reserve.__name__ = f"reserve_{node}"
    return reserve


def resume_updates(
    state: state_module.IndustryState, node: str, limits: records.Limits
) -> dict[str, Any]:
    """What the CLI writes as ``reserve_<node>`` before re-running ``node``.

    Every running reservation of the node becomes ``unknown`` (its
    charge stays forever). A fresh reservation is added only if the
    ledger, with that charge, still admits the call; otherwise the node
    is skipped on the re-run, exactly as ``reserve_<node>`` would do.
    """
    calls = dict(state.get("single_calls", {}))
    lost = []
    for call_id, call in calls.items():
        if call.task_id == node and call.status == "running":
            calls[call_id] = call.model_copy(update={"status": "unknown"})
            lost.append(call_id)
    charged = {**state, "single_calls": calls}
    lost_text = ", ".join(lost) or "no"
    allowed = budget.admit_single_call(charged, limits, node)
    if allowed <= 0:
        return {
            "single_calls": calls,
            "route_log": [
                f"resume at {node}: {lost_text} interrupted reservation "
                "charged as unknown; budget exhausted, the call is skipped"
            ],
        }
    reservation = _reservation(charged, node, limits, allowed)
    calls[reservation.id] = reservation
    return {
        "single_calls": calls,
        "route_log": [
            f"resume at {node}: {lost_text} interrupted reservation charged "
            f"as unknown; {reservation.id} reserved ({allowed} turns)"
        ],
    }


def _release(
    state: state_module.IndustryState, node: str
) -> dict[str, records.Attempt]:
    """Close the node's reservation unused (the node had nothing to do)."""
    reservation = running_reservation(state, node)
    if reservation is None:
        return dict(state.get("single_calls", {}))
    return _complete(state, reservation, records.Usage())


def _complete(
    state: state_module.IndustryState,
    reservation: records.Attempt,
    usage: records.Usage,
) -> dict[str, records.Attempt]:
    calls = dict(state.get("single_calls", {}))
    calls[reservation.id] = reservation.model_copy(
        update={
            "status": "done" if not usage.unknown else "failed",
            "observed": usage,
            "duration_s": usage.duration_s,
        }
    )
    return calls


# --- helpers ----------------------------------------------------------------


def _thread_id() -> str:
    try:
        config = langgraph_config.get_config()
    except RuntimeError:
        return "anonymous"
    return str(config.get("configurable", {}).get("thread_id", "anonymous"))


def _render_pdf(thread_id: str, text: str, directory: str) -> str:
    """Render the delivered report as a PDF; report failure, never raise.

    The Markdown report is the delivered artifact and its status was
    decided by the delivery gate. Typography runs afterwards and is
    allowed to fail: a broken render costs the reader a formatted copy,
    and must never cost them the report or change what it says it is.

    Args:
      thread_id: Names the file, as it names the Markdown report.
      text: The delivered Markdown, verbatim.
      directory: Where reports are written.

    Returns:
      The route-log line naming the PDF, or naming the failure.
    """
    try:
        written = pdf_module.write_pdf(thread_id, text, directory)
    except Exception as error:  # pylint: disable=broad-exception-caught
        # The Markdown was replaced already; an earlier run's PDF must
        # not stay beside it pretending to be this report.
        pdf_module.discard_stale(thread_id, directory)
        try:
            detail = f"{type(error).__name__}: {error}"
        except Exception:  # pylint: disable=broad-exception-caught
            detail = type(error).__name__
        return (
            "deliver: pdf rendering failed, the Markdown report stands "
            f"({detail})"
        )
    return f"deliver: pdf {written}"


def _writer() -> Callable[[dict[str, Any]], Any] | None:
    try:
        return langgraph_config.get_stream_writer()
    except RuntimeError:
        return None


def _material_open_issues(
    state: state_module.IndustryState,
) -> list[records.Issue]:
    return [
        i
        for i in state.get("issues", {}).values()
        if i.status == "open" and i.severity == "material"
    ]


# How many claims one verifier call judges; the review loops over
# reservations until nothing material is left or the budget refuses.
REVIEW_BATCH = records.Limits().review_batch


def reviewable(
    state: state_module.IndustryState,
) -> list[records.Claim]:
    """The material claims a verifier verdict could still settle.

    One selection, so the node and its router can never disagree:
    ``pending_review`` orders and truncates this list and
    ``review_remaining`` counts it. ``merge.outstanding_review`` is the
    one definition of selectable work, shared with
    ``budget.review_batches`` so the reserve is never sized for work the
    reviewer cannot select. A claim whose producer chain is not
    intact is not among them -- only ``calc.recompute_stale`` can settle
    that one -- so a router that asks for another review round can never
    ask for a batch the node would find empty.
    """
    claims = state.get("claims", {})
    calculations = state.get("calculations", {})
    relationships = state.get("relationships", {})
    return [
        c
        for c in merge.outstanding_review(claims, relationships)
        if merge.producer_chain_intact(c, claims, calculations)
    ]


def repair_key(request: records.RepairRequest) -> tuple[str, str, str]:
    """What makes two repair requests the same request."""
    return (
        request.claim_id,
        request.relationship_id or "",
        merge.normalize_text(request.objective),
    )


def record_repairs(
    state: state_module.IndustryState,
    requests: list[records.AcquisitionRequest],
    claims: dict[str, records.Claim],
    review_round: int,
) -> tuple[dict[str, records.RepairRequest], list[str]]:
    """Keep every acquisition request the verifier made.

    Plan revision 38 §4.45.4: nothing is truncated here. A request that
    repeats one already open is folded into it; one naming a claim the
    registry does not hold is recorded as ``dropped`` with its reason,
    so an operator sees what was asked and what became of it.
    """
    repairs = dict(state.get("repairs", {}))
    # Only an *open* request suppresses a repeat: a later review may
    # legitimately ask again after an attempt attached nothing, or once
    # a new source exists.
    known = {
        repair_key(r): rid
        for rid, r in repairs.items()
        if r.status in ("pending", "admitted", "deferred")
    }
    log: list[str] = []
    for request in requests:
        if not request.claim_id:
            continue
        new = records.RepairRequest(
            id=merge.next_id("RQ", repairs),
            claim_id=request.claim_id,
            relationship_id=request.relationship_id,
            objective=request.objective,
            url=request.url,
            review_round=review_round,
        )
        key = repair_key(new)
        if key in known:
            continue
        if request.claim_id not in claims:
            new = new.model_copy(
                update={
                    "status": "dropped",
                    "reason": "the claim is not in the registry",
                }
            )
        repairs[new.id] = new
        known[key] = new.id
    if requests:
        waiting = sum(1 for r in repairs.values() if r.status == "pending")
        log.append(
            f"review: {len(requests)} repair request(s) recorded; "
            f"{waiting} pending"
        )
    return repairs, log


def acquisition_route(
    state: state_module.IndustryState,
    claim: records.Claim,
    request: records.RepairRequest,
) -> int:
    """How real a route to original context is; lower sorts first.

    A recorded route, never a predicted verdict (plan revision 39
    §4.46.4). 0: a snippet whose source already has a resolvable
    version agreeing on its source. 1: a concrete document URL, from
    the request or the source. 2: neither -- a speculative search,
    which waits behind every accessible repair.
    """
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    versions = state.get("source_versions", {})

    def fetchable(url: str | None) -> bool:
        return bool(url) and url.lower().startswith(("http://", "https://"))

    urls: list[str] = []
    for eid in claim.evidence_ids:
        item = evidence.get(eid)
        if item is None:
            continue
        source = sources.get(item.source_id)
        version = versions.get(item.source_version_id or "")
        if (
            item.kind == "snippet"
            and source is not None
            and version is not None
            and version.source_id == item.source_id
        ):
            # The snippet's own source already carries a fetched
            # version to read the original from.
            return 0
        if source is not None and fetchable(source.canonical_url):
            urls.append(source.canonical_url or "")
    if fetchable(request.url) or urls:
        return 1
    return 2


def repair_priority(
    state: state_module.IndustryState, request: records.RepairRequest
) -> tuple[int, int, int, int]:
    """Lower sorts first: what the reader loses most by not repairing.

    Plan revision 39 §4.46.4, and deterministic to the last field so a
    replay ranks identically.
    """
    claim = state.get("claims", {})[request.claim_id]
    central = set(records.required_ids(state.get("brief")))
    thin = {
        row.question
        for row in state.get("coverage", [])
        if row.question in central and row.status != "covered"
    }
    findings = state.get("findings", {}).values()
    if thin & set(claim.questions):
        rank = 0
    elif any(
        finding.status == "current"
        and finding.material
        and claim.id in finding.claim_ids
        and central & set(finding.questions)
        for finding in findings
    ):
        rank = 1
    elif (
        claim.quantity is not None
        or claim.milestone is not None
        or request.relationship_id is not None
        or {"cost_structure", "bargaining_power", "commercialization"}
        & set(claim.topics)
    ):
        rank = 2
    elif any(
        issue.status in records.UNRESOLVED_ISSUE_STATUSES
        and issue.severity == "material"
        and issue.category in ("unsupported", "contradiction")
        and issue.target == claim.id
        for issue in state.get("issues", {}).values()
    ):
        rank = 3
    else:
        rank = 4
    return (
        rank,
        acquisition_route(state, claim, request),
        merge.schedule.task_number(claim.id),
        merge.schedule.task_number(request.id),
    )


def repair_affordable(
    state: state_module.IndustryState,
    limits: records.Limits,
    outstanding: int,
) -> bool:
    """Whether a repair and the review it forces both fit.

    Both halves or neither (plan revision 39 §4.46.2): a repair that
    could not be validated withdraws a citable claim and leaves no way
    to restore it. Neither half may touch the write/final-review
    reserve or the downstream provisions.

    Args:
      state: The state the decision is made on -- with the ledger the
        completed call actually left, never the one it no longer holds.
      limits: The run's limits.
      outstanding: Repair pairs already outstanding, this one included.

    Returns:
      Whether this repair may be admitted.
    """
    if outstanding > 1:
        # One pair at a time keeps the held review's ownership
        # unambiguous.
        return False
    return budget.admit_repair_pair(state, limits) > 0


def schedule_repairs(
    state: state_module.IndustryState,
    limits: records.Limits,
) -> tuple[
    dict[str, records.RepairRequest], dict[str, records.Task], list[str]
]:
    """Admit the repairs that can run; defer the rest with a reason.

    Plan revision 38 §4.45.4. Eligible requests are ranked, and each
    admission must pay for both halves of a repair: the attempt itself
    and the review its attachment makes necessary. Capacity is debited
    inside this call, so several requests cannot each pass the same
    one-slot test. Nothing is discarded: what is not admitted is
    ``deferred`` with its reason and considered again next round.
    """
    repairs = dict(state.get("repairs", {}))
    tasks = dict(state.get("tasks", {}))
    claims = state.get("claims", {})
    log: list[str] = []
    open_targets = {
        r.claim_id for r in repairs.values() if r.status == "admitted"
    }
    # Ownership is read from what the run actually holds -- a repair
    # task waiting or running, or a review held for one -- so a retry
    # or a second scheduling call cannot open a second pair
    # (post-implementation finding 3).
    outstanding = sum(
        1
        for task in tasks.values()
        if task.kind == "acquisition"
        and task.target is not None
        and task.status in ("pending", "running")
    ) + sum(
        1
        for call in state.get("single_calls", {}).values()
        if call.task_id == "review"
        and call.reserved.held
        and call.status == "running"
    )
    attempts = state.get("attempts", {})
    spent = sum(
        1
        for a in attempts.values()
        if tasks.get(a.task_id) is not None
        and tasks[a.task_id].kind == "acquisition"
    )
    waiting = sum(
        1
        for task in tasks.values()
        if task.kind == "acquisition" and task.status == "pending"
    )
    room = limits.acquisition_executions - spent - waiting
    admitted_now = 0
    open_requests = [
        r for r in repairs.values() if r.status in ("pending", "deferred")
    ]
    for request in open_requests:
        claim = claims.get(request.claim_id)
        if claim is None or not claim.material or claim.calculation_id:
            # The target stopped being repairable; the request is closed
            # with its reason rather than left open for ever.
            repairs[request.id] = request.model_copy(
                update={
                    "status": "dropped",
                    "reason": ("the target is gone, not material, or derived"),
                }
            )
    considered = sorted(
        (
            r
            for r in repairs.values()
            if r.status in ("pending", "deferred")
            and r.claim_id not in open_targets
        ),
        key=lambda r: repair_priority(state, r),
    )
    for request in considered:
        if request.claim_id in open_targets:
            # Another request admitted this target inside this same
            # call; a second session would repair what is already being
            # repaired and its result would be refused as stale.
            repairs[request.id] = request.model_copy(
                update={
                    "status": "deferred",
                    "reason": "another repair already targets this claim",
                }
            )
            continue
        if room <= 0:
            repairs[request.id] = request.model_copy(
                update={
                    "status": "deferred",
                    "reason": (
                        f"execution ceiling: {limits.acquisition_executions} "
                        "repairs is the run's limit"
                    ),
                }
            )
            continue
        if admitted_now or outstanding:
            repairs[request.id] = request.model_copy(
                update={
                    "status": "deferred",
                    "reason": "priority: one repair pair runs at a time",
                }
            )
            continue
        # Both halves or neither: the repair attempt and the review its
        # attachment forces are admitted together (plan revision 39
        # §4.46.2), out of what is free after the delivery reserve and
        # the downstream provisions.
        if not repair_affordable(state, limits, admitted_now + 1):
            seconds, turns = budget.repair_pair_cost(limits)
            short = budget.repair_shortfall(state, limits)
            repairs[request.id] = request.model_copy(
                update={
                    "status": "deferred",
                    "reason": (
                        f"{short}: the repair and the review it needs "
                        f"({seconds:.0f}s, {turns} turns) do not both fit "
                        "outside the reserve"
                    ),
                }
            )
            continue
        claim = claims[request.claim_id]
        task_id = merge.next_id("T", tasks)
        tasks[task_id] = records.Task(
            id=task_id,
            kind="acquisition",
            role="verifier",
            objective=request.objective
            + (f" URL: {request.url}" if request.url else ""),
            references=list(claim.evidence_ids),
            issue_id=request.issue_id,
            target=records.RepairTarget(
                claim_id=claim.id,
                claim_version=claim.version,
                statement=claim.statement,
                qualification=claim.review_reason,
                evidence_ids=list(claim.evidence_ids),
                relationship_id=request.relationship_id,
                gap=request.objective,
            ),
            acceptance=(
                "The original passage supporting or contradicting the "
                "claim is retrieved and returned as an attachment."
            ),
        )
        repairs[request.id] = request.model_copy(
            update={"status": "admitted", "reason": "", "task_id": task_id}
        )
        open_targets.add(claim.id)
        room -= 1
        admitted_now += 1
        log.append(
            f"repair {request.id}: {task_id} admitted for {claim.id}@"
            f"{claim.version}"
        )
    deferred = sum(1 for r in repairs.values() if r.status == "deferred")
    if deferred:
        log.append(f"repairs: {deferred} deferred, kept for the next round")
    return repairs, tasks, log


def can_start(
    state: state_module.IndustryState,
    limits: records.Limits,
    ready: list[records.Task],
) -> bool:
    """Whether anything ready could actually start now.

    An admitted repair pair is funded on its own terms and must not be
    routed away because no ordinary 900-second slot is free: at every
    recorded decision boundary there was none (plan revision 39
    §4.46.2, post-implementation finding 1).
    """
    if budget.dispatchable(state, limits, False) > 0:
        return True
    return any(
        task.kind == "acquisition"
        and task.target is not None
        and not stale_repair(task, state.get("claims", {}))
        and repair_affordable(state, limits, 1)
        for task in ready
    )


def stale_repair(task: records.Task, claims: dict[str, records.Claim]) -> bool:
    """Whether a repair task's target has moved since it was planned.

    The question a repair was sent to answer is the claim as it stood
    then; once the claim is versioned, the session would be answering a
    question nobody is asking (plan revision 38 §4.45.4).
    """
    target = task.target
    if target is None:
        return False
    held = claims.get(target.claim_id)
    return held is None or held.version != target.claim_version


def settle_repairs(
    state: state_module.IndustryState, update: dict[str, Any]
) -> dict[str, records.RepairRequest]:
    """Record what became of every admitted repair after a merge.

    Plan revision 38 §4.45.4: ``done`` means evidence was actually
    attached to the target -- a claim that gained a version, or a
    relationship that gained evidence -- never that a session ran.
    """
    repairs = dict(update.get("repairs", state.get("repairs", {})))
    before_relations = state.get("relationships", {})
    after_relations = update.get("relationships", before_relations)
    tasks = update.get("tasks", state.get("tasks", {}))
    applied = merge.applied_attachments(update.get("route_log", []))
    for rid, request in repairs.items():
        if request.status != "admitted" or request.task_id is None:
            continue
        task = tasks.get(request.task_id)
        if task is None or task.status in ("pending", "running"):
            continue
        # Only this task's own attempts count: two requests for one
        # target must not both be credited with the one attachment that
        # landed.
        mine = {
            attempt_id
            for attempt_id in applied
            if attempt_id.rsplit(".", 1)[0] == request.task_id
        }
        attached = any(
            request.claim_id in applied[attempt_id] for attempt_id in mine
        )
        if not attached and request.relationship_id:
            was = before_relations.get(request.relationship_id)
            now = after_relations.get(request.relationship_id)
            attached = (
                was is not None
                and now is not None
                and len(now.evidence_ids) > len(was.evidence_ids)
            )
        if attached:
            repairs[rid] = request.model_copy(
                update={"status": "done", "reason": "evidence attached"}
            )
        else:
            repairs[rid] = request.model_copy(
                update={
                    "status": "dropped",
                    "reason": (
                        f"the repair task {task.status} without attaching "
                        "evidence"
                    ),
                }
            )
    return repairs


def repaired_awaiting_review(state: state_module.IndustryState) -> list[str]:
    """Targets a repair strengthened that still need their verdict.

    The review a repair paid for is the *next ordinary batch*, so the
    batch has to actually contain the target: without this the queue's
    ordinary order can spend every funded batch elsewhere and leave the
    repaired claim withdrawn (plan revision 39 §4.46.2,
    post-implementation finding 2).
    """
    claims = state.get("claims", {})
    relationships = state.get("relationships", {})
    calculations = state.get("calculations", {})
    ordered: list[str] = []
    for request in sorted(
        state.get("repairs", {}).values(),
        key=lambda r: merge.schedule.task_number(r.id),
    ):
        if request.status != "done":
            continue
        claim = claims.get(request.claim_id)
        if (
            claim is None
            or claim.id in ordered
            or not claim.material
            or not merge.claim_needs_attention(claim, relationships)
            or not merge.producer_chain_intact(claim, claims, calculations)
        ):
            continue
        ordered.append(claim.id)
    return ordered


def pending_review(
    state: state_module.IndustryState, batch: int | None = None
) -> list[str]:
    """The claims the verifier judges next: unreviewed material or map.

    Review is bounded by the budget, so the order is the priority in
    which claims earn citability, interleaved so no group starves: one
    queue for map claims (the value chain and its participants) and one
    per question the brief requires, taken round-robin, then the
    remaining material claims; at most ``batch`` per call (the run's
    ``Limits.review_batch``; ``REVIEW_BATCH`` is only the default).

    A claim goes to the queue of the partition it was admitted to
    (``Claim.partition``), which is the same least-loaded assignment
    ``merge.assign_partition`` made, so the round-robin drains the
    partitions the quota actually governs rather than a second,
    disagreeing grouping by lowest question id.

    Within the batch priority selects, claims resting on the same
    source travel together and their shared excerpts are rendered once
    (plan D-U6b). Grouping never changes *which* claims are selected --
    doing so let one source's mates crowd out a required question --
    only the order they are presented in. Ordering stays deterministic
    given the registry.
    """
    unreviewed = sorted(
        reviewable(state),
        key=lambda c: merge.schedule.task_number(c.id),
    )
    queues: dict[str, list[str]] = {"map": []}
    for question in records.required_ids(state.get("brief")):
        queues[f"q{question}"] = []
    rest: list[str] = []
    for claim in unreviewed:
        if claim.map_ref is not None:
            queues["map"].append(claim.id)
            continue
        partition = merge.material_partition(claim)
        if partition in queues:
            queues[partition].append(claim.id)
        else:
            rest.append(claim.id)
    ordered: list[str] = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                ordered.append(queue.pop(0))
    ordered.extend(rest)
    # A claim a repair strengthened goes first: its verdict is what the
    # repair bought, and the rest of the batch fills in behind it.
    repaired = repaired_awaiting_review(state)
    ordered = repaired + [cid for cid in ordered if cid not in repaired]
    # Cut to the batch *before* grouping. Grouping first pulled
    # source-mates ahead of the round-robin and could fill a whole batch
    # from one question, spending scarce review capacity on work the
    # priority order had not selected (U1-10). Selection is priority's;
    # grouping only decides the order within what priority chose.
    selected = ordered[: batch or REVIEW_BATCH]
    return group_by_source(state, selected)


def group_by_source(
    state: state_module.IndustryState, ordered: list[str]
) -> list[str]:
    """Reorder claims so those sharing a source are adjacent (D-U6b).

    Stable: a claim keeps the position its priority earned, and the
    others resting on the same source are pulled up behind it. The
    priority order therefore still decides what gets reviewed at all;
    grouping only decides what accompanies it, so one document is read
    once per batch instead of once per claim.

    A group result still needs a verdict per target. ``scope_review``
    and ``merge.apply_review`` are unchanged: a claim the verifier
    omitted stays unreviewed, never supported by association.
    """
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})

    def sources_of(claim_id: str) -> frozenset[str]:
        claim = claims.get(claim_id)
        if claim is None:
            return frozenset()
        found = (evidence.get(eid) for eid in claim.evidence_ids)
        return frozenset(item.source_id for item in found if item is not None)

    remaining = list(ordered)
    grouped: list[str] = []
    while remaining:
        head = remaining.pop(0)
        grouped.append(head)
        shared = sources_of(head)
        if not shared:
            continue
        companions = [c for c in remaining if sources_of(c) & shared]
        for companion in companions:
            remaining.remove(companion)
        grouped.extend(companions)
    return grouped


def scope_review(
    state: state_module.IndustryState,
    outcome: records.ClaimReview,
    pending: list[str],
) -> records.ClaimReview:
    """Keep only the verdicts about what the verifier was handed.

    Claim verdicts outside the batch, relationship verdicts whose
    parent claim is not in the batch, source judgements about sources
    none of the batch's evidence comes from, contradictions that name
    no batch claim, and acquisition requests for claims outside the
    batch are dropped, so verifier output can never alter, or spend
    budget on, what it did not see.
    """
    batch = set(pending)
    relationships = state.get("relationships", {})
    evidence = state.get("evidence", {})
    claims = state.get("claims", {})
    sources = {
        evidence[eid].source_id
        for cid in batch
        if cid in claims
        for eid in claims[cid].evidence_ids
        if eid in evidence
    }
    for rel in relationships.values():
        if rel.claim_id in batch:
            sources.update(
                evidence[eid].source_id
                for eid in rel.evidence_ids
                if eid in evidence
            )
    return outcome.model_copy(
        update={
            "claims": [v for v in outcome.claims if v.claim_id in batch],
            "relationships": [
                v
                for v in outcome.relationships
                if v.relationship_id in relationships
                and relationships[v.relationship_id].claim_id in batch
            ],
            "sources": [v for v in outcome.sources if v.source_id in sources],
            "contradictions": [
                text
                for text in outcome.contradictions
                if set(report.cited_ids(text)) & batch
            ],
            "acquisitions": [
                r for r in outcome.acquisitions if r.claim_id in batch
            ],
        }
    )


def uncomputed_comparison(
    finding: records.Finding,
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
) -> str | None:
    """The metric a finding compares without arithmetic, if any.

    Deterministic and narrow on purpose: two or more cited claims that
    carry an admitted quantity for the *same* metric, and no derived
    claim among the citations to have compared them. That is a
    comparison whether the prose says "twice", "higher", or nothing at
    all, and it is the case ``calc`` exists to settle (plan D-U10).
    """
    by_metric: dict[str, set[str]] = {}
    for cid in finding.claim_ids:
        claim = claims.get(cid)
        if claim is None or claim.quantity is None:
            continue
        if claim.kind == "derived" and claim.calculation_id in calculations:
            # The comparison was computed; this is its result.
            return None
        if not claim.dimension:
            continue
        metric = " ".join(claim.dimension.split()).casefold()
        by_metric.setdefault(metric, set()).add(claim.id)
    for metric, cited in sorted(by_metric.items()):
        if len(cited) >= 2:
            return metric
    return None


def review_remaining(state: state_module.IndustryState) -> int:
    """How many material claims review could still settle.

    Exactly the claims ``pending_review`` draws its batches from: a
    derived claim whose calculation was stopped, or whose inputs were
    withdrawn, is not among them -- only recomputation can settle it
    (``calc.recompute_stale``).
    """
    return len(reviewable(state))


def write_instructions(state: state_module.IndustryState) -> str:
    """Full draft, or a revision when sections are stale or issues open."""
    stale = [s for s in state.get("sections", []) if s.stale]
    pending = [
        i
        for i in state.get("issues", {}).values()
        if i.status == "open" and i.requested_action in ("edit", "remove")
    ]
    if state.get("sections") and (stale or pending):
        return (
            "Revise the draft: rewrite the stale sections and fix the open "
            "edit/remove issues with the smallest change; keep every other "
            "section as it is."
        )
    return "Write the full report."


def initial_allocation(state: state_module.IndustryState) -> bool:
    """Whether this is the first allocation, which owns the map.

    One helper, so Studio's reconstruction of a planning call agrees
    with what execution actually asked for.
    """
    return state.get("phase", "mapping") == "mapping" and not state.get("tasks")


MAP_FIELDS = (
    "segments with stage and description",
    "links with what flows",
    "participants with role, supplies/buys, region, listed",
    "boundary note",
)


def _own_the_map(
    state: state_module.IndustryState,
    tasks: dict[str, records.Task],
    limits: records.Limits,
) -> tuple[dict[str, records.Task], str | None]:
    """Give the first admitted task the map's responsibilities.

    ``Task.kind`` is the ownership mechanism: it already selects the
    map instructions and already requires a map output, so no separate
    flag is added.
    """
    fresh = [tid for tid in tasks if tid not in state.get("tasks", {})]
    if not fresh:
        return tasks, None
    owner = tasks[fresh[0]]
    tasks = dict(tasks)
    tasks[owner.id] = owner.model_copy(
        update={
            "kind": "map",
            "required_fields": list(owner.required_fields)
            + [f for f in MAP_FIELDS if f not in owner.required_fields],
            "acceptance": (
                f"{owner.acceptance} Every segment, link and participant "
                "cites a passage from a fetched source; at most "
                f"{limits.map_segments} segments, {limits.map_links} links "
                f"and {limits.map_participants_per_stage} participants per "
                "stage are retained."
            ).strip(),
        }
    )
    return tasks, owner.id


def planning_purpose(state: state_module.IndustryState) -> str:
    """What prepare_tasks plans for in the state's phase."""
    if initial_allocation(state):
        return PURPOSES["mapping"]
    return PURPOSES.get(state.get("phase", "mapping"), PURPOSES["remediation"])


def planning_slots(
    state: state_module.IndustryState, limits: records.Limits
) -> int:
    """How many tasks prepare_tasks may create now."""
    keep_slot = state.get("review_rounds", 0) == 0
    slots = budget.dispatchable(state, limits, keep_slot)
    if initial_allocation(state):
        # The first allocation admits one ordinary industry task, which
        # owns the map. The dedicated map session it replaces spent 54
        # turns and 26.70 minutes across headline runs 4 and 5 for no
        # admitted finding, while the ordinary tasks produced the map
        # anyway.
        return min(1, slots)
    return slots


def issue_stage(issues: list[records.Issue]) -> str | None:
    """The earliest stage the open material issues need, or ``None``.

    research > acquire > analyze > edit, per the brief's routing table.
    """
    actions = {i.requested_action for i in issues}
    if actions & {"research", "acquire"}:
        return "research"
    if "analyze" in actions:
        return "analyze"
    if actions & {"edit", "remove"}:
        return "write"
    return None


def build_worker_input(
    state: state_module.IndustryState,
    attempt: records.Attempt,
    thread_id: str,
) -> records.WorkerInput:
    """The complete payload of one attempt, copied from state."""
    task = state["tasks"][attempt.task_id]
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    versions = state.get("source_versions", {})
    references = []
    for eid in task.references:
        item = evidence.get(eid)
        if item is None:
            continue
        source = sources.get(item.source_id)
        version = versions.get(item.source_version_id or "")
        references.append(
            records.Reference(
                evidence=item,
                source_title=source.title if source else item.source_id,
                source_url=source.canonical_url if source else None,
                source_path=source.path if source else None,
                source_kind=source.kind if source else "web_page",
                version=version,
                version_date=version.retrieved_at[:10] if version else None,
            )
        )
    open_issue = None
    if task.issue_id and task.issue_id in state.get("issues", {}):
        issue = state["issues"][task.issue_id]
        open_issue = f"[{issue.id}] {issue.description}"
        if issue.next_step:
            open_issue += f" Next step: {issue.next_step}"
    return records.WorkerInput(
        thread_id=thread_id,
        attempt=attempt,
        task=task,
        brief=state["brief"],
        language=state["brief"].language,
        references=references,
        open_issue=open_issue,
        allowance=attempt.reserved,
        max_turns=state["meta"].limits.max_turns,
        model=roles.ROLE_MODELS[task.role],
        prompt_version=roles.PROMPT_VERSION,
    )


def _tasks_from_plan(
    state: state_module.IndustryState,
    plan: roles.TaskPlan,
    slots: int,
    kind: records.TaskKind,
    limits: records.Limits,
) -> tuple[dict[str, records.Task], dict[str, records.Issue], list[str]]:
    tasks = dict(state.get("tasks", {}))
    issues = dict(state.get("issues", {}))
    evidence = state.get("evidence", {})
    log: list[str] = []
    key_to_id: dict[str, str] = {}
    accepted: list[tuple[str, roles.TaskSpec]] = []
    next_number = schedule.task_number(merge.next_id("T", tasks))
    for spec in plan.tasks:
        if spec.key in key_to_id:
            log.append(f"prepare_tasks: duplicate key {spec.key!r} dropped")
            continue
        issue = issues.get(spec.issue_id or "")
        if issue is not None and (
            issue.status != "open" or followups_exhausted(issue, limits)
        ):
            # The per-issue allowance is enforced here, where a task is
            # admitted, not only when issues are retired afterwards.
            log.append(
                f"prepare_tasks: {spec.key!r} works on {issue.id}, which "
                f"is {issue.status} with {issue.attempts} attempts; dropped"
            )
            continue
        if len(accepted) >= slots:
            log.append(
                f"prepare_tasks: {spec.key!r} beyond the {slots} slots the "
                "budget allows; dropped"
            )
            continue
        if issue is not None:
            # The attempt is counted as the task is admitted, so a plan
            # naming one issue several times spends the allowance once
            # per task: the next spec on the same issue sees the count
            # this one made, exactly as a later plan would.
            issues[issue.id] = issue.model_copy(
                update={"attempts": issue.attempts + 1, "evidence_added": False}
            )
        chunks = schedule.decompose(spec.targets, limits)
        if len(chunks) > 1:
            # Infeasible as proposed: the session's tool allowance
            # cannot evidence this many named targets. Decompose, and
            # say plainly what did not fit rather than dispatching a
            # scope the session cannot meet (plan D-U5).
            log.append(
                f"prepare_tasks: {spec.key!r} names {len(spec.targets)} "
                f"targets; one session can evidence "
                f"{schedule.target_capacity(limits)}, so it is split into "
                f"{len(chunks)}"
            )
        for index, chunk in enumerate(chunks):
            named = ", ".join(chunk) or "no targets"
            if len(accepted) >= slots:
                log.append(
                    f"prepare_tasks: {spec.key!r} part {index + 1} of "
                    f"{len(chunks)} ({named}) has no slot; recorded as an "
                    "explicit partial plan"
                )
                continue
            # Scoping the record without scoping the contract would
            # multiply the infeasible task rather than split it: the
            # worker prompt renders objective, scope and acceptance,
            # so a part says what it alone must cover (U1-08).
            part = spec.model_copy(
                update={
                    "targets": chunk,
                    "objective": _scoped(spec.objective, chunk, index, chunks),
                    "scope": _scoped_note(spec.scope, chunk, index, chunks),
                }
            )
            key = spec.key if index == 0 else f"{spec.key}#{index + 1}"
            key_to_id[key] = f"T{next_number}"
            next_number += 1
            accepted.append((key, part))
    for key, spec in accepted:
        task_id = key_to_id[key]
        depends = []
        for dep in spec.depends_on:
            resolved = key_to_id.get(dep, dep if dep in tasks else None)
            if resolved is None:
                log.append(f"{task_id}: dependency {dep!r} unknown; dropped")
            elif resolved != task_id:
                depends.append(resolved)
        references = [r for r in spec.references if r in evidence]
        issue_id = spec.issue_id if spec.issue_id in issues else None
        tasks[task_id] = records.Task(
            id=task_id,
            kind=kind,
            role=spec.role,
            objective=spec.objective,
            scope=spec.scope,
            depends_on=depends,
            references=references,
            required_fields=spec.required_fields,
            acceptance=spec.acceptance,
            targets=spec.targets,
            issue_id=issue_id,
        )
        log.append(f"{task_id} ({spec.role}): {spec.objective[:80]}")
    if len(plan.tasks) > slots:
        log.append(
            f"prepare_tasks: {len(plan.tasks) - slots} proposed tasks "
            "beyond the budget were not created"
        )
    return tasks, issues, log


def _scoped(objective: str, chunk: list[str], index: int, chunks: list) -> str:
    """One part's objective, naming only what this part must cover."""
    if len(chunks) == 1 or not chunk:
        return objective
    named = ", ".join(chunk)
    return (
        f"{objective} -- part {index + 1} of {len(chunks)}: cover only "
        f"{named} in this session."
    )


def _scoped_note(scope: str, chunk: list[str], index: int, chunks: list) -> str:
    """One part's scope note, saying which targets are somebody else's."""
    if len(chunks) == 1 or not chunk:
        return scope
    named = ", ".join(chunk)
    note = (
        f"This session covers {named} only; the other targets of this "
        f"plan are separate tasks (part {index + 1} of {len(chunks)})."
    )
    return f"{scope} {note}".strip()


def company_obligation(
    state: state_module.IndustryState,
    tasks: dict[str, records.Task],
    issues: dict[str, records.Issue],
    reason: str,
) -> tuple[dict[str, records.Issue], list[str]]:
    """A required comparison gets company tasks, or a recorded failure.

    Run 7 defined a Company Researcher role, gave it a focus and a
    prompt, and never created a single task for it: T1 and T2 were both
    ``industry`` and T3-T6 were repairs. Q7 could then be judged on
    whatever entities happened to turn up. A role definition is not a
    comparison (plan D-U5, A18).

    So when the brief requires Q7 and the map has named participants,
    either a company task exists or this records an explicit admission
    failure naming what stopped it. What it never does is let the
    obligation disappear: the issue is material, it reaches coverage and
    the reader, and it says which budget dimension was binding.
    """
    brief = state.get("brief")
    if 7 not in records.required_ids(brief):
        return issues, []
    industry_map = state.get("map", records.IndustryMap())
    if not industry_map.participants:
        # Nothing has been discovered to compare yet; the obligation is
        # real but not yet actionable.
        return issues, []
    # Every company a company task actually owns, whatever its status:
    # a role-bearing task is not an assignment for companies it never
    # named, and a failed task leaves its own targets unmet (U1-09).
    assigned: set[str] = set()
    for task in tasks.values():
        if task.role != "company" or task.status in ("failed", "skipped"):
            continue
        assigned.update(name.casefold() for name in task.targets)
        if not task.targets:
            # An untargeted company task is a general assignment; it
            # covers the comparison as a whole.
            return issues, []
    unassigned = [
        part.name
        for part in industry_map.participants
        if part.name.casefold() not in assigned
    ]
    if not unassigned:
        return issues, []
    named = ", ".join(sorted(unassigned)[:6])
    if len(unassigned) > 6:
        named += f", and {len(unassigned) - 6} more"
    key = "q7:no-company-task"
    updated = dict(issues)
    for issue in updated.values():
        if issue.key == key and issue.status in (
            records.UNRESOLVED_ISSUE_STATUSES
        ):
            return issues, []
    issue_id = merge.next_id("I", updated)
    updated[issue_id] = records.Issue(
        id=issue_id,
        key=key,
        category="missing_evidence",
        severity="material",
        target="Q7",
        description=(
            "The brief requires a company comparison and no company "
            f"evidence task covers {named}. {reason}"
        ),
        requested_action="research",
        next_step=(
            "Assign a company task naming the selected comparison companies."
        ),
    )
    return updated, [
        f"{issue_id}: Q7 requires company evidence; no company task "
        f"covers {named} ({reason})"
    ]


def followups_exhausted(issue: records.Issue, limits: records.Limits) -> bool:
    """Whether the issue may not be worked on again.

    The one definition of the per-issue limit: ``issue_follow_ups``
    attempts, one more only when evidence was added and a concrete next
    step is on record. Used to retire issues and to refuse tasks that
    would work on an exhausted one.
    """
    over = issue.attempts >= limits.issue_follow_ups
    third_allowed = (
        issue.attempts == limits.issue_follow_ups
        and issue.evidence_added
        and bool(issue.next_step)
    )
    return over and not third_allowed


def _close_followup_issues(
    issues: dict[str, records.Issue], limits: records.Limits
) -> tuple[dict[str, records.Issue], list[str]]:
    """Retire issues past the follow-up limit without a productive step."""
    updated = dict(issues)
    log = []
    for issue in issues.values():
        if issue.status != "open":
            continue
        if followups_exhausted(issue, limits):
            updated[issue.id] = issue.model_copy(
                update={
                    "status": "unresolvable",
                    "resolution": (
                        f"follow-up limit reached after {issue.attempts} "
                        "attempts without a productive next step"
                    ),
                }
            )
            log.append(f"{issue.id} unresolvable: follow-up limit")
    return updated, log


def resolve_issues(state: state_module.IndustryState) -> dict[str, Any]:
    """Close issues the registry has answered; pure.

    A question issue closes when the question is at least partial and
    the issue's target question is covered; a claim issue closes when
    the claim is supported or qualified, or when nothing cites it any
    more; a section issue closes when the section was rewritten.
    """
    issues = dict(state.get("issues", {}))
    claims = state.get("claims", {})
    coverage = {c.question: c.status for c in state.get("coverage", [])}
    cited: set[str] = set()
    for finding in state.get("findings", {}).values():
        if finding.status == "current":
            cited.update(finding.claim_ids)
    for section in state.get("sections", []):
        cited.update(section.claim_ids)
    # A claim a live calculation still consumes is cited through the
    # derived claim that reports its result, so its unsupported issue is
    # not resolved by "no longer cited".
    calculations = state.get("calculations", {})
    for claim in claims.values():
        if claim.calculation_id and claim.is_reviewed():
            calculation = calculations.get(claim.calculation_id)
            if calculation is not None and calculation.status == "ok":
                cited.update(item.claim_id for item in calculation.inputs)
    log = []
    for issue in issues.values():
        if issue.status != "open":
            continue
        resolved = None
        target = issue.target
        if target.startswith("Q") and target[1:].isdigit():
            if coverage.get(int(target[1:])) == "covered":
                resolved = "question covered"
        elif target in claims:
            claim = claims[target]
            if issue.category == "contradiction" and claim.is_reviewed():
                resolved = f"claim reviewed {claim.review}"
            elif issue.category == "unsupported" and (
                claim.is_reviewed() or target not in cited
            ):
                resolved = (
                    "claim no longer cited"
                    if target not in cited
                    else f"claim reviewed {claim.review}"
                )
        elif issue.draft_version is not None:
            resolved = None  # closed only by a clean later final review
        if resolved:
            issues[issue.id] = issue.model_copy(
                update={"status": "resolved", "resolution": resolved}
            )
            log.append(f"{issue.id} resolved: {resolved}")
    return {"issues": issues, "route_log": log}


# --- the graph ---------------------------------------------------------------


def build_graph(
    runtime: budget.Runtime,
    backend: tools.Backend | None = None,
    api: RolesApi | None = None,
    worker_fn: WorkerFunction = worker_module.run_attempt,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the industry research graph.

    Args:
      runtime: The process runtime (limits, meters, the admission
        authority, index lock).
      backend: The services behind the tools; the live backend if
        ``None``.
      api: The single-call roles; the live ones if ``None``.
      worker_fn: Runs one attempt (tests inject a fake).
      checkpointer: Where LangGraph saves state after each node.
    """
    limits = runtime.limits
    backend = backend or tools.LiveBackend()
    api = api or LiveRoles(runtime.admission)

    async def call_with_reservation(
        state: state_module.IndustryState,
        node: str,
        call: Callable[[int, float], Awaitable[tuple[Any, records.Usage]]],
    ) -> tuple[Any | None, dict[str, Any]]:
        """Run a single call under its reservation; ``None`` if skipped."""
        reservation = running_reservation(state, node)
        if reservation is None:
            return None, {"route_log": [f"{node}: skipped (no reservation)"]}
        max_turns = budget.max_turns_for(reservation.reserved.turns, limits)
        try:
            output, usage = await call(max_turns, reservation.reserved.seconds)
        except (crew.RoleTimeout, crew.RoleHung) as error:
            # This call's own deadline, not a program fault: the
            # reservation stays charged in full and the node degrades
            # exactly as a refused one does, so the reserve can still
            # write and deliver instead of the run ending on a
            # traceback with everything it collected undelivered. An
            # ``admission.Blocked`` -- work that outlived its
            # cancellation is still live in this process -- is not
            # caught here: it ends the run resumably before anything
            # starts over that work.
            return None, {
                "single_calls": _complete(
                    state, reservation, records.Usage(unknown=True)
                ),
                "route_log": [f"{node}: {type(error).__name__}: {error}"],
            }
        return output, {"single_calls": _complete(state, reservation, usage)}

    async def scope(state: state_module.IndustryState) -> dict[str, Any]:
        question = state["question"]

        async def call(max_turns: int, deadline: float):
            return await api.scope(question, max_turns, deadline)

        brief, update = await call_with_reservation(state, "scope", call)
        if brief is None:
            brief = roles.default_brief(question)
            update.setdefault("route_log", []).append(
                "scope: deterministic defaults used"
            )
        meta = state.get("meta") or initial_state(question, limits)["meta"]
        update.update(
            {
                "meta": meta,
                "brief": brief,
                # Nothing seeds tasks in production -- the first
                # allocation creates the one that owns the map -- but a
                # pre-seeded registry is preserved, so a test can start
                # from a dispatchable task without a planning call.
                "tasks": dict(state.get("tasks") or {}),
                "phase": "mapping",
                "cycle": 0,
                "follow_up_rounds": 0,
            }
        )
        update.setdefault("route_log", []).append(
            f"scope: industry {brief.industry!r}, language {brief.language}, "
            f"mode {brief.mode}"
        )
        return update

    async def dispatch(state: state_module.IndustryState) -> dict[str, Any]:
        thread_id = _thread_id()
        tasks = schedule.validate(state.get("tasks", {}))
        tasks, ready = schedule.ready(tasks)
        keep_slot = state.get("review_rounds", 0) == 0 and not any(
            t.kind == "acquisition" for t in ready
        )
        slots = budget.dispatchable(state, limits, keep_slot)
        # A repair pair is admitted on its own terms (plan revision 39
        # §4.46.2). It must not then wait for an ordinary 900-second
        # slot: at every recorded decision boundary there were none,
        # which would leave the pair admitted and unable to start.
        repairs_first = [
            task
            for task in ready
            if task.kind == "acquisition" and task.target is not None
        ]
        ordinary = [task for task in ready if task not in repairs_first]
        attempts = dict(state.get("attempts", {}))
        # Acquisition attempts are capped for the run: beyond the cap a
        # ready acquisition task is skipped, never dispatched.
        acquisitions = sum(
            1
            for a in attempts.values()
            if state["tasks"][a.task_id].kind == "acquisition"
        )
        admitted = []
        claims = state.get("claims", {})
        for task in ready:
            if task.kind == "acquisition":
                # The ceiling is enforced where attempts start, because
                # a re-queued attempt never passes task creation again.
                if acquisitions >= limits.acquisition_executions:
                    tasks[task.id] = task.model_copy(
                        update={
                            "status": "skipped",
                            "skip_reason": (
                                f"{limits.acquisition_executions} acquisition "
                                "attempts is the cap"
                            ),
                        }
                    )
                    continue
                target = task.target
                # Historical acquisitions are already charged in the
                # ledger; only this one is new work to project.
                if target is not None and not repair_affordable(
                    state, limits, 1
                ):
                    # A retry never passes task creation again, so the
                    # rule that both halves of a repair must fit is
                    # enforced where attempts actually start.
                    tasks[task.id] = task.model_copy(
                        update={
                            "status": "skipped",
                            "skip_reason": (
                                "the review this repair needs no longer fits"
                            ),
                        }
                    )
                    continue
                if stale_repair(task, claims):
                    tasks[task.id] = task.model_copy(
                        update={
                            "status": "skipped",
                            "skip_reason": (
                                f"{task.target.claim_id} changed since the "
                                "repair was planned"
                            ),
                        }
                    )
                    continue
                acquisitions += 1
            admitted.append(task)
        ready = admitted
        meter = runtime.meter_for(thread_id) or runtime.new_meter(
            thread_id, state
        )
        log = []
        calls = dict(state.get("single_calls", {}))
        window = state.get("repair_window", "open")
        starting = repairs_first + ordinary[:slots]
        for task in starting:
            repair = task.kind == "acquisition" and task.target is not None
            reservation = (
                budget.repair_reservation_for(limits)
                if repair
                else budget.reservation_for(limits)
            )
            attempt = records.Attempt(
                id=f"{task.id}.{task.attempts + 1}",
                task_id=task.id,
                reserved=reservation,
                started_at=records.now_iso(),
            )
            if repair:
                # The review this repair forces is taken with it and
                # charged from now, exactly as a write takes its final
                # review (plan revision 39 §4.46.2). It is held until
                # `reserve_review` activates it, without a second
                # charge, and it is the next ordinary batch.
                attempt = _with_reservation(attempt, pair_id=attempt.id)
                held = _reservation(
                    {**state, "single_calls": calls},
                    "review",
                    limits,
                    limits.single_call_reserved(),
                )
                held = _with_reservation(held, pair_id=attempt.id, held=True)
                calls[held.id] = held
                window = "used"
                log.append(
                    f"dispatch: {attempt.id} admitted, reserved "
                    f"{limits.repair_timeout_s:.0f}s with {held.id} held "
                    "for the review it forces"
                )
            attempts[attempt.id] = attempt
            tasks[task.id] = task.model_copy(
                update={"status": "running", "attempts": task.attempts + 1}
            )
            meter.register(attempt.id, attempt.reserved.tool_calls)
            if not repair:
                log.append(f"dispatch: {attempt.id} reserved and admitted")
        if len(ordinary) > slots:
            log.append(
                f"dispatch: {len(ordinary) - slots} ready tasks wait for "
                "budget"
            )
        if not starting:
            log.append("dispatch: nothing ready")
        return {
            "tasks": tasks,
            "attempts": attempts,
            "single_calls": calls,
            "repair_window": window,
            "route_log": log,
        }

    def fan_out(state: state_module.IndustryState) -> list[Send] | str:
        thread_id = _thread_id()
        merged = set(state.get("merged", []))
        sends = [
            Send(
                "run_task",
                build_worker_input(state, attempt, thread_id),
            )
            for attempt in state.get("attempts", {}).values()
            if attempt.status == "running"
            and attempt.id not in merged
            and state["tasks"][attempt.task_id].status == "running"
        ]
        return sends or "merge"

    async def run_task(work: records.WorkerInput) -> dict[str, Any]:
        if not isinstance(work, records.WorkerInput):
            # A payload the serializer could not rebuild comes back as
            # the raw mapping it read; running the attempt on it would
            # fail somewhere further in, on a field at a time.
            raise TypeError(
                "worker payload was not restored as a WorkerInput "
                f"({type(work).__name__}); this thread cannot be resumed"
            )
        result = await worker_fn(work, runtime, backend, on_event=_writer())
        return {"task_results": [result]}

    async def merge_node(state: state_module.IndustryState) -> dict[str, Any]:
        update = merge.merge_results(
            state, state.get("task_results", []), limits
        )
        issues = dict(state.get("issues", {}))
        before = set(state.get("evidence", {}))
        added_by_task: dict[str, int] = {}
        for eid in set(update["evidence"]) - before:
            task_id = update["evidence"][eid].task_id
            added_by_task[task_id] = added_by_task.get(task_id, 0) + 1
        for task_id, task in update["tasks"].items():
            if task.issue_id in issues and added_by_task.get(task_id):
                issues[task.issue_id] = issues[task.issue_id].model_copy(
                    update={"evidence_added": True}
                )
        update["issues"] = issues
        update["repairs"] = settle_repairs(state, update)
        runtime.drop(_thread_id())
        return update

    def after_merge(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and can_start(state, limits, ready):
            return "dispatch"
        if state.get("phase", "mapping") == "mapping":
            return "reserve_prepare_tasks"
        return "reserve_review"

    async def prepare_tasks(
        state: state_module.IndustryState,
    ) -> dict[str, Any]:
        phase = state.get("phase", "mapping")
        first = initial_allocation(state)
        purpose = planning_purpose(state)
        slots = planning_slots(state, limits)
        update: dict[str, Any] = {"route_log": []}
        if slots <= 0:
            update["single_calls"] = _release(state, "prepare_tasks")
            update["route_log"].append("prepare_tasks: no budget for tasks")
        else:

            async def call(max_turns: int, deadline: float):
                return await api.plan_tasks(
                    state, limits, slots, purpose, max_turns, deadline
                )

            plan, update = await call_with_reservation(
                state, "prepare_tasks", call
            )
            update.setdefault("route_log", [])
            if plan is not None:
                kind: records.TaskKind = (
                    "research" if phase == "mapping" else "follow_up"
                )
                tasks, issues, log = _tasks_from_plan(
                    state, plan, slots, kind, limits
                )
                if first:
                    tasks, owned = _own_the_map(state, tasks, limits)
                    if owned:
                        log.append(
                            f"prepare_tasks: {owned} owns the industry map"
                        )
                if not first:
                    # The handoff that plans work against the merged map
                    # is where a company comparison is either funded or
                    # explicitly recorded as unfunded (plan D-U5).
                    issues, obligation = company_obligation(
                        state,
                        tasks,
                        issues,
                        f"the plan filled {slots} slot(s) with other work",
                    )
                    log.extend(obligation)
                update.update({"tasks": tasks, "issues": issues})
                update["route_log"].extend(log)
                if plan.rationale:
                    update["route_log"].append(
                        f"prepare_tasks: {plan.rationale[:200]}"
                    )
        if first:
            # Stay in mapping only while an owner is outstanding: the
            # next allocation is the handoff that plans company work
            # against the merged map.
            admitted = any(
                task.kind == "map" for task in update.get("tasks", {}).values()
            )
            update["phase"] = "mapping" if admitted else "researching"
        elif phase == "mapping":
            update["phase"] = "researching"
        return update

    def after_prepare(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and can_start(state, limits, ready):
            return "dispatch"
        return "reserve_review"

    async def assess_coverage(
        state: state_module.IndustryState,
    ) -> dict[str, Any]:
        async def call(max_turns: int, deadline: float):
            return await api.assess_coverage(state, max_turns, deadline)

        assessment, update = await call_with_reservation(
            state, "assess_coverage", call
        )
        derived = coverage_module.derive(state, assessment)
        issues = dict(state.get("issues", {}))
        missing = list(assessment.missing) if assessment else []
        for item in derived:
            central = item.question in records.required_ids(state.get("brief"))
            if item.status == "covered":
                continue
            description = f"Q{item.question} {item.status}: {item.note}"
            if missing:
                description += " Missing: " + " ".join(missing)
            issues, _ = merge.open_issue(
                issues,
                "missing_evidence",
                "material" if central else "minor",
                f"Q{item.question}",
                "research",
                description,
            )
        update.update(
            {"coverage": derived, "assessment": assessment, "issues": issues}
        )
        update.setdefault("route_log", []).append(
            "assess_coverage: "
            + ", ".join(f"Q{c.question}={c.status}" for c in derived)
        )
        resolved = resolve_issues({**state, **update})
        update["issues"] = resolved["issues"]
        update["route_log"].extend(resolved["route_log"])
        after = {**state, **update}
        gaps = [
            i
            for i in _material_open_issues(after)
            if i.category == "missing_evidence"
            and i.target.startswith("Q")
            and i.attempts < limits.issue_follow_ups
        ]
        rounds = state.get("follow_up_rounds", 0)
        if (
            gaps
            and rounds < limits.follow_up_rounds
            and budget.dispatchable(after, limits, True) > 0
        ):
            update["phase"] = "coverage_followup"
            update["follow_up_rounds"] = rounds + 1
            update["route_log"].append(
                f"assess_coverage: follow-up round {rounds + 1} for "
                + ", ".join(i.target for i in gaps)
            )
        else:
            update["phase"] = "assessed"
        return update

    def after_assess(state: state_module.IndustryState) -> str:
        if state.get("phase") == "coverage_followup":
            return "follow_up"
        return "write"

    async def analyze(state: state_module.IndustryState) -> dict[str, Any]:
        note = ANALYSIS_NOTE
        # Reaching analysis is the run passing the point of asking for
        # repairs; whatever the earmark was holding goes back.
        closed = close_repair_window(state)
        # A calculation a corrected claim stopped is run again from the
        # claims as they stand now, before the analyst is asked for
        # anything: a derived claim comes back as a new version stating
        # the new result, never as the old result re-approved.
        claims, calculations, log = calc.recompute_stale(
            state.get("claims", {}), state.get("calculations", {})
        )

        async def first(max_turns: int, deadline: float):
            return await api.analyze(state, note, max_turns, deadline)

        analysis, update = await call_with_reservation(state, "analyze", first)
        update.setdefault("route_log", []).extend(log)
        if closed:
            update["repair_window"] = closed["repair_window"]
            update["route_log"].extend(closed["route_log"])
        if log:
            # Recomputation is deterministic arithmetic, not a model
            # call: it stands whether or not the analyst was admitted,
            # so an exhausted reservation never leaves a derived claim
            # withdrawn over a result Python already has.
            update["claims"] = claims
            update["calculations"] = calculations
        if analysis is None:
            return update
        if analysis.calc_requests:
            # Only reviewed, consistent quantities may enter a
            # calculation; anything else is a missing input, never a
            # number.
            inputs = calc.inputs_from_claims(claims, calculations)
            requested = analysis.calc_requests
            cap = limits.calc_requests_per_call
            if len(requested) > cap:
                update["route_log"].append(
                    f"analyze: {len(requested)} calculation requests, the "
                    f"first {cap} taken"
                )
                requested = requested[:cap]
            for request in requested:
                calc_id = merge.next_id("K", calculations)
                result = calc.compute(calc_id, request, inputs)
                calculations[calc_id] = result
                if result.status == "ok":
                    claim_id = merge.next_id("C", claims)
                    # A calculation's result matters because its inputs
                    # did, never because a partition has room (U1-02).
                    # The queue decides only whether its review waits.
                    material = any(
                        claims[item.claim_id].material
                        for item in result.inputs
                        if item.claim_id in claims
                    )
                    fits = merge.admit_material(
                        claims, limits, "q4", state.get("relationships", {})
                    )
                    claims[claim_id] = records.Claim(
                        id=claim_id,
                        kind="derived",
                        material=material,
                        partition="q4",
                        questions=[4],
                        question_mapping="declared",
                        review_disposition=(
                            "pending" if not material or fits else "deferred"
                        ),
                        review_deferred_reason=(
                            None if not material or fits else "q4 at capacity"
                        ),
                        origin=calc_id,
                        **calc.derived_fields(result, claims),
                    )
                    update["route_log"].append(
                        f"analyze: {calc_id} = {result.result} "
                        f"{quantities.render(result.unit)} -> {claim_id}"
                    )
                else:
                    update["route_log"].append(
                        f"analyze: {calc_id} error {result.message}"
                    )
            # The derived claims are available to the editor now and to
            # the analyst in the next cycle; one reservation is one call.
        findings: dict[str, records.Finding] = {}
        for spec in analysis.findings:
            # A finding rests on reviewed claims only; one unreviewed,
            # unsupported, or unknown citation drops it (logged), so
            # nothing unreviewed is promoted into analysis.
            valid = [
                cid
                for cid in spec.claim_ids
                if cid in claims and claims[cid].is_reviewed()
            ]
            if len(valid) != len(spec.claim_ids) or not valid:
                update["route_log"].append(
                    f"analyze: finding dropped, claims {spec.claim_ids} "
                    "not all reviewed supported/qualified"
                )
                continue
            if not all(
                [
                    spec.mechanism,
                    spec.implication,
                    spec.counterargument,
                    spec.monitor,
                ]
            ):
                update["route_log"].append(
                    f"analyze: finding dropped (claims {spec.claim_ids}, "
                    "missing mechanism/implication/counterargument/monitor "
                    "or unknown claims)"
                )
                continue
            fid = merge.next_id("F", findings)
            findings[fid] = records.Finding(
                id=fid,
                conclusion=spec.conclusion,
                claim_ids=valid,
                mechanism=spec.mechanism,
                implication=spec.implication,
                counterargument=spec.counterargument,
                uncertainty=spec.uncertainty,
                monitor=spec.monitor,
                material=spec.material,
                questions=spec.questions,
                entity=spec.entity,
            )
        issues = dict(state.get("issues", {}))
        for fid, finding in findings.items():
            gap = uncomputed_comparison(finding, claims, calculations)
            if gap is None:
                continue
            # A conclusion that compares two numbers rests on arithmetic
            # whether or not anyone ran it. Admitting it silently is how
            # "A is roughly twice B" reaches a reader with nothing behind
            # it (U1-12, A12). The finding is kept -- the Analyst's
            # reasoning is not thrown away -- and the obligation is
            # recorded, which caps the report's status until it is met.
            issues, issue = merge.open_issue(
                issues,
                "weak_inference",
                "material",
                fid,
                "analyze",
                f"[{fid}] the conclusion compares {gap} without a "
                "calculation behind it",
                next_step=(
                    "Request the calculation, or state the comparison "
                    "qualitatively."
                ),
            )
            update["route_log"].append(
                f"{issue.id}: {fid} compares {gap} with no calculation"
            )
        for request in analysis.evidence_requests:
            issues, _ = merge.open_issue(
                issues,
                request.category,
                request.severity,
                request.target,
                request.requested_action,
                request.description,
                request.next_step,
            )
        rounds = state.get("analysis_rounds", 0) + 1
        update.update(
            {
                "findings": findings,
                "calculations": calculations,
                "claims": claims,
                "issues": issues,
                "analysis_rounds": rounds,
                "phase": "analysis",
            }
        )
        after = {**state, **update}
        requests = [
            i
            for i in _material_open_issues(after)
            if i.requested_action == "research"
            and i.attempts == 0
            and not i.target.startswith("Q")
        ]
        if (
            requests
            and rounds <= 1
            and budget.dispatchable(after, limits, True) > 0
        ):
            update["phase"] = "analysis_requests"
        update["route_log"].append(
            f"analyze: {len(findings)} findings, "
            f"{len(analysis.calc_requests)} calculations, "
            f"{len(analysis.evidence_requests)} evidence requests"
        )
        return update

    def after_analyze(state: state_module.IndustryState) -> str:
        if state.get("phase") == "analysis_requests":
            return "requests"
        return "assess"

    async def review(state: state_module.IndustryState) -> dict[str, Any]:
        claims = state.get("claims", {})
        pending = pending_review(state, limits.review_batch)
        if not pending:
            return {
                "review_rounds": state.get("review_rounds", 0) + 1,
                "single_calls": _release(state, "review"),
                "route_log": ["review: nothing unreviewed"],
            }

        async def call(max_turns: int, deadline: float):
            return await api.review_claims(state, pending, max_turns, deadline)

        outcome, update = await call_with_reservation(state, "review", call)
        update.setdefault("route_log", [])
        update["review_rounds"] = state.get("review_rounds", 0) + 1
        if outcome is None:
            return update
        outcome = scope_review(state, outcome, pending)
        applied = merge.apply_review(state, outcome)
        # A settled claim frees its partition slot, so the claims that
        # were waiting for one are admitted now, before anything asks
        # what is left to review (U1-01). Without this the deferral the
        # quota created was permanent -- a demotion under another name.
        promoted, promotion_log = merge.reconsider_deferred(
            applied["claims"],
            limits,
            state.get("brief"),
            applied["relationships"],
        )
        applied["claims"] = promoted
        update.setdefault("route_log", []).extend(
            f"review: {line}" for line in promotion_log
        )
        update.update(
            {
                "claims": applied["claims"],
                "relationships": applied["relationships"],
                "sources": applied["sources"],
                "calculations": applied["calculations"],
                "findings": applied["findings"],
                "sections": applied["sections"],
                "review": outcome,
            }
        )
        update["route_log"].extend(applied["route_log"])
        issues = dict(state.get("issues", {}))
        tasks = dict(state.get("tasks", {}))
        newly_bad = {
            v.claim_id
            for v in outcome.claims
            if v.verdict in ("unsupported", "contradicted")
            and v.claim_id in claims
        }
        for verdict in outcome.claims:
            if verdict.claim_id not in claims:
                continue
            claim = applied["claims"][verdict.claim_id]
            if verdict.verdict == "contradicted":
                issues, _ = merge.open_issue(
                    issues,
                    "contradiction",
                    "material" if claim.material else "minor",
                    claim.id,
                    "acquire",
                    verdict.reason,
                )
            elif verdict.verdict == "unsupported":
                issues, _ = merge.open_issue(
                    issues,
                    "unsupported",
                    "material" if claim.material else "minor",
                    claim.id,
                    "remove",
                    verdict.reason,
                )
        for text in outcome.contradictions:
            issues, _ = merge.open_issue(
                issues,
                "contradiction",
                "material",
                "contradictions",
                "acquire",
                text,
            )
        # Every request is recorded, then scheduling decides what can
        # actually run and defers the rest with a reason (plan revision
        # 38 §4.45.4). Nothing is truncated and nothing is dropped in
        # silence.
        reviewed_claims = applied["claims"]
        repairs, repair_log = record_repairs(
            state,
            outcome.acquisitions,
            reviewed_claims,
            update["review_rounds"],
        )
        update["route_log"].extend(repair_log)
        reviewed_state = {
            **state,
            # The call that has just finished is charged its observed
            # usage, not the full reservation it no longer holds: this
            # decision used to be made against a stale ledger, and it
            # is the difference between admitting a repair and refusing
            # one (plan revision 39 §4.46.0).
            "single_calls": update.get(
                "single_calls", state.get("single_calls", {})
            ),
            "repairs": repairs,
            "tasks": tasks,
            "claims": reviewed_claims,
            "relationships": applied["relationships"],
            "issues": issues,
        }
        # Priority ranks against the coverage of the claims it is
        # ranking, not the rows a previous assessment left behind.
        reviewed_state["coverage"] = coverage_module.derive(
            reviewed_state, state.get("assessment")
        )
        repairs, tasks, scheduled_log = schedule_repairs(reviewed_state, limits)
        update["route_log"].extend(scheduled_log)
        created = sum(
            1
            for task in tasks.values()
            if task.kind == "acquisition"
            and task.id not in state.get("tasks", {})
        )
        update["repairs"] = repairs
        update["tasks"] = tasks
        update["issues"] = issues
        if created:
            update["phase"] = "acquisition"
        remaining = review_remaining({**state, **update})
        update["route_log"].append(
            f"review: {len(outcome.claims)} verdicts, {len(newly_bad)} "
            f"unsupported/contradicted, {created} repair task(s), "
            f"{remaining} claims still unreviewed"
        )
        return update

    def _progress(state: state_module.IndustryState) -> bool:
        return state_module.registry_signature(state) != state.get(
            "last_signature", ""
        )

    def close_repair_window(
        state: state_module.IndustryState,
    ) -> dict[str, Any]:
        """Release the earmark once the run has stopped asking.

        Recorded, so a later phase change cannot silently recreate it
        (plan revision 39 §4.46.3).
        """
        if not budget.repair_window_open(state):
            return {}
        return {
            "repair_window": "closed",
            "route_log": [
                "repairs: the window closed with no repair admitted; "
                "its earmark is released"
            ],
        }

    def after_review(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and can_start(state, limits, ready):
            return "dispatch"
        last = running_reservation(state, "review")
        if (
            pending_review(state, limits.review_batch)
            and last is None
            and budget.admit_single_call(state, limits, "review") > 0
        ):
            # The router asks for the batch the node will actually take,
            # never for a count computed another way: a round that the
            # node would find empty releases its reservation unused and
            # would be routed here again forever.
            return "again"
        return "analyze"

    async def remediate(state: state_module.IndustryState) -> dict[str, Any]:
        issues, log = _close_followup_issues(state.get("issues", {}), limits)
        open_material = [
            i
            for i in issues.values()
            if i.status == "open" and i.severity == "material"
        ]
        stage = issue_stage(open_material) or "write"
        cycle = state.get("cycle", 0) + 1
        return {
            "issues": issues,
            "cycle": cycle,
            "phase": "remediation",
            "return_to": stage,
            "last_signature": state_module.registry_signature(state),
            "route_log": log
            + [
                f"remediate: cycle {cycle} -> {stage} "
                f"({len(open_material)} material issues open)"
            ],
        }

    def after_remediate(state: state_module.IndustryState) -> str:
        stage = state.get("return_to", "write")
        if stage == "write" and budget.admit_pair(state, limits) <= 0:
            return "deliver"
        return {
            "research": "reserve_prepare_tasks",
            "analyze": "reserve_analyze",
            "write": "reserve_write",
        }[stage]

    async def write(state: state_module.IndustryState) -> dict[str, Any]:
        instructions = write_instructions(state)

        async def call(max_turns: int, deadline: float):
            return await api.write(state, instructions, max_turns, deadline)

        draft, update = await call_with_reservation(state, "write", call)
        update.setdefault("route_log", [])
        if draft is None:
            return update
        # The outgoing body is about to be replaced. If it was reviewed
        # and is deliverable, it stays the incumbent until the
        # replacement has completed its own review and classified at
        # least as well.
        kept = _retain(state)
        if kept is not None:
            update["candidate"] = kept
            update["route_log"].append(
                f"write: draft {kept.draft_version} retained as the "
                f"{kept.level} candidate"
            )
        version = state.get("draft_version", 0) + 1
        sections = [
            records.Section(
                id=s.id,
                title=s.title,
                text=s.text,
                claim_ids=report.cited_claims(s.text),
                review_version=version,
            )
            for s in draft.sections
        ]
        issues = dict(state.get("issues", {}))
        for problem in report.check_citations(
            sections,
            state.get("claims", {}),
            report.known_entities(state),
            state.get("calculations", {}),
        ):
            issues, _ = merge.open_issue(
                issues,
                "unsupported",
                "material",
                problem.section_id,
                "edit",
                problem.description,
                draft_version=version,
                text=problem.text,
            )
        update.update(
            {"sections": sections, "issues": issues, "draft_version": version}
        )
        open_count = sum(1 for i in issues.values() if i.status == "open")
        update["route_log"].append(
            f"write: {len(sections)} sections, {open_count} open issues"
        )
        return update

    async def final_review(
        state: state_module.IndustryState,
    ) -> dict[str, Any]:
        # Freeze the subject before the call, so the appendix the
        # verifier reads is the one delivery renders. This node reopens
        # issues and re-derives coverage below, and `deliver` derives it
        # again, which used to let the delivered limitations differ from
        # the reviewed ones with no new draft and no version change.
        subject = report.review_subject(state, state.get("coverage") or [])
        reviewed = {**state, "review_subject": subject}

        async def call(max_turns: int, deadline: float):
            return await api.final_review(reviewed, max_turns, deadline)

        outcome, update = await call_with_reservation(
            state, "final_review", call
        )
        update.setdefault("route_log", [])
        issues = dict(state.get("issues", {}))
        version = state.get("draft_version", 0)
        if outcome is not None:
            flagged: set[str] = set()
            for problem in outcome.issues:
                action: records.RequestedAction = {
                    "unsupported": "remove",
                    "contradiction": "analyze",
                    "weak_inference": "analyze",
                    "missing_evidence": "research",
                    "wording": "edit",
                    "unavailable": "edit",
                }[problem.category]
                claim_note = (
                    f" (claim {problem.claim_id})" if problem.claim_id else ""
                )
                # The exact unit the reviewer named, resolved against the
                # draft it reviewed. A block that resolves buys a smaller
                # removal; one that does not buys nothing worse than
                # before -- `blocking_issues` still takes the section
                # (plan D-U12, U0-04).
                block = report.resolve_block(
                    state.get("sections", []),
                    problem.section_id,
                    problem.block_id,
                )
                if problem.block_id and block is None:
                    update["route_log"].append(
                        f"final_review: {problem.block_id!r} names no unit "
                        f"of {problem.section_id} in draft {version}; the "
                        "issue stands and the section is at risk whole"
                    )
                issues, issue = merge.open_issue(
                    issues,
                    problem.category,
                    problem.severity,
                    problem.section_id,
                    action,
                    f"[{problem.section_id}] {problem.description}{claim_note}",
                    draft_version=version,
                    text=block.text if block is not None else None,
                )
                flagged.add(issue.key)
            # A draft issue closes only when a newer draft was reviewed
            # and this review did not flag it again.
            for issue in list(issues.values()):
                if (
                    issue.status == "open"
                    and issue.draft_version is not None
                    and issue.draft_version < version
                    and issue.key not in flagged
                ):
                    issues[issue.id] = issue.model_copy(
                        update={
                            "status": "resolved",
                            "resolution": f"draft {version} reviewed clean",
                        }
                    )
                    update["route_log"].append(
                        f"{issue.id} resolved: draft {version} reviewed clean"
                    )
            if not outcome.consistent and not outcome.issues:
                issues, _ = merge.open_issue(
                    issues,
                    "contradiction",
                    "material",
                    "draft",
                    "edit",
                    f"[draft {version}] the final review judged the draft "
                    "inconsistent without naming a section: "
                    + (outcome.summary or "no summary"),
                    draft_version=version,
                )
            # A retention approval that names no frozen body section
            # grants nothing -- `retainable_sections` drops it, and a
            # title is never guessed into an id. It used to do so in
            # silence (plan revision 37 §4.44.3).
            rejected = [
                value
                for value in outcome.retainable
                if value not in subject.sections
            ]
            if rejected:
                update["route_log"].append(
                    f"retainable_rejected: draft {version}, subject "
                    f"{subject.digest[:12]}: "
                    + ", ".join(repr(value) for value in rejected)
                    + " name no body section; no retention granted"
                )
            update["final_review"] = outcome
            update["final_review_version"] = version
            update["review_subject"] = subject
        derived = coverage_module.derive(state, state.get("assessment"))
        update["coverage"] = derived
        resolved = resolve_issues(
            {**state, "issues": issues, "coverage": derived}
        )
        update["issues"] = resolved["issues"]
        update["route_log"].extend(resolved["route_log"])
        open_material = [
            i
            for i in update["issues"].values()
            if i.status == "open" and i.severity == "material"
        ]
        update["route_log"].append(
            f"final_review: {len(open_material)} material issues open"
        )
        return update

    def after_final(state: state_module.IndustryState) -> str:
        issues = _material_open_issues(state)
        if (
            issues
            and state.get("cycle", 0) < limits.remediation_cycles
            and _progress(state)
            # Affordability funds an attempt at a replacement. Without
            # a write *and* its review, remediation would only spend
            # what is left traversing refused nodes toward a rewrite
            # that could never be validated.
            and budget.admit_pair(state, limits) > 0
        ):
            return "remediate"
        return "deliver"

    def _floor():
        return runtime.floor or coverage_module.FLOOR

    def _assess(
        state: state_module.IndustryState,
    ) -> tuple[report.DeliveryPlan, records.DeliveryResult]:
        """Plan and classify a body with the unchanged §4.39 machinery."""
        derived = coverage_module.derive(state, state.get("assessment"))
        plan = report.plan_delivery(state, report.removal_note(state))
        return plan, coverage_module.classify_delivery(
            state, derived, plan, _floor()
        )

    def _retain(
        state: state_module.IndustryState,
    ) -> records.DeliveryCandidate | None:
        """The outgoing body as a candidate, if it is worth keeping."""
        subject = state.get("review_subject")
        if subject is None or not report.certificate_applies(state):
            return None
        _, result = _assess(state)
        if result.level == "diagnostic_only":
            return None
        fresh = records.DeliveryCandidate(
            sections=list(state.get("sections", [])),
            subject=subject,
            review=state.get("final_review"),
            draft_version=state.get("draft_version", 0),
            issues=dict(state.get("issues", {})),
            level=result.level,
            status=result.status,
        )
        held = state.get("candidate")
        if held is not None and stored_rank(held) >= stored_rank(fresh):
            # The incumbent wins ties: a replacement has to be better,
            # not merely newer.
            return held
        return fresh

    def _candidate_state(
        state: state_module.IndustryState,
        candidate: records.DeliveryCandidate,
    ) -> dict[str, Any]:
        """The retained body as a state, judged against current support."""
        return {
            **state,
            "sections": list(candidate.sections),
            "review_subject": candidate.subject,
            "final_review": candidate.review,
            "draft_version": candidate.draft_version,
            "issues": issues_for_candidate(candidate, state.get("issues", {})),
        }

    async def deliver(state: state_module.IndustryState) -> dict[str, Any]:
        # The report is not written over work that outlived its
        # cancellation: the same authority that admits sessions stops
        # delivery, resumably, until the survivor has ended.
        runtime.admission.check()
        # The gate decides the body before anything renders, and the
        # classification decides what the body may be called. A
        # certificate bound to `draft_version` alone never established
        # that the delivered words were the reviewed ones.
        chosen = state
        plan, delivery = _assess(state)
        delivery_of_later = delivery
        reason = ""
        incumbent = state.get("candidate")
        if incumbent is not None:
            # The retained body is judged against *current* support, with
            # the issue state that applies to it -- never restored, and
            # never given a later draft's resolutions.
            kept_state = _candidate_state(state, incumbent)
            kept_plan, kept_delivery = _assess(kept_state)
            if candidate_rank(kept_delivery, kept_plan) > candidate_rank(
                delivery, plan
            ):
                chosen, plan, delivery = kept_state, kept_plan, kept_delivery
                later = state.get("draft_version", 0)
                reason = (
                    f"the body is reviewed draft {incumbent.draft_version}; "
                    f"the later draft {later} classified "
                    f"{delivery_of_later.level} "
                    f"({delivery_of_later.status})"
                )
        derived = coverage_module.derive(chosen, chosen.get("assessment"))
        if reason:
            delivery = delivery.model_copy(
                update={"reason": f"{delivery.reason}; {reason}"}
            )
        delivery = delivery.model_copy(
            update={"drift": report.appendix_drift(chosen, derived)}
        )
        # A held review allowance that was never activated closes with
        # zero usage, as any unused reservation does.
        released = {
            cid: call.model_copy(
                update={
                    "status": "done",
                    "observed": records.Usage(),
                    "reserved": call.reserved.model_copy(
                        update={"held": False}
                    ),
                }
            )
            for cid, call in state.get("single_calls", {}).items()
            if call.reserved.held and call.status == "running"
        }
        status = delivery.status
        text = report.render(chosen, derived, status, delivery, plan)
        path = report.write_report(_thread_id(), text, runtime.reports_dir)
        pdf_note = _render_pdf(_thread_id(), text, runtime.reports_dir)
        meta = state["meta"].model_copy(
            update={
                "execution_status": "completed",
                "report_status": status,
                "report_path": path,
            }
        )
        update: dict[str, Any] = {
            "coverage": derived,
            "meta": meta,
            "delivery": delivery,
            "route_log": [
                f"deliver: {delivery.level} ({status}); {delivery.reason}; "
                f"report {path}",
                pdf_note,
            ],
        }
        if released:
            update["single_calls"] = {
                **state.get("single_calls", {}),
                **released,
            }
            update["route_log"].append(
                "deliver: released " + ", ".join(sorted(released)) + " unused"
            )
        return update

    graph = StateGraph(state_module.IndustryState)
    for node in SINGLE_CALL_NODES:
        graph.add_node(f"reserve_{node}", reserve_node(node, limits))
    graph.add_node("scope", scope)
    graph.add_node("dispatch", dispatch)
    graph.add_node("run_task", run_task)
    graph.add_node("merge", merge_node)
    graph.add_node("prepare_tasks", prepare_tasks)
    graph.add_node("assess_coverage", assess_coverage)
    graph.add_node("analyze", analyze)
    graph.add_node("review", review)
    graph.add_node("remediate", remediate)
    graph.add_node("write", write)
    graph.add_node("final_review", final_review)
    graph.add_node("deliver", deliver)

    graph.add_edge(START, "reserve_scope")
    for node in SINGLE_CALL_NODES:
        graph.add_edge(f"reserve_{node}", node)
    graph.add_edge("scope", "dispatch")
    graph.add_conditional_edges("dispatch", fan_out, ["run_task", "merge"])
    graph.add_edge("run_task", "merge")
    stages = ["dispatch", "reserve_prepare_tasks", "reserve_review"]
    graph.add_conditional_edges("merge", after_merge, stages)
    graph.add_conditional_edges("prepare_tasks", after_prepare, stages)
    graph.add_conditional_edges(
        "review",
        after_review,
        {
            "dispatch": "dispatch",
            "again": "reserve_review",
            "analyze": "reserve_analyze",
        },
    )
    graph.add_conditional_edges(
        "analyze",
        after_analyze,
        {
            "requests": "reserve_prepare_tasks",
            "assess": "reserve_assess_coverage",
        },
    )
    graph.add_conditional_edges(
        "assess_coverage",
        after_assess,
        {"follow_up": "reserve_prepare_tasks", "write": "reserve_write"},
    )
    graph.add_conditional_edges(
        "remediate",
        after_remediate,
        [
            "reserve_prepare_tasks",
            "reserve_analyze",
            "reserve_write",
            "deliver",
        ],
    )
    graph.add_edge("write", "reserve_final_review")
    graph.add_conditional_edges(
        "final_review",
        after_final,
        {"remediate": "remediate", "deliver": "deliver"},
    )
    graph.add_edge("deliver", END)
    return graph.compile(checkpointer=checkpointer)
