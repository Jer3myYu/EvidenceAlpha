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

from industry import budget
from industry import calc
from industry import coverage as coverage_module
from industry import merge
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
    """The real roles over the CrewAI adapter, returning usage too."""

    async def scope(self, question, max_turns, deadline):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        brief = await roles.scope(question, llm, max_turns, deadline)
        return brief, _usage_of(llm, started)

    async def plan_tasks(
        self, state, limits, slots, purpose, max_turns, deadline
    ):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        plan = await roles.plan_tasks(
            state, limits, slots, purpose, llm, max_turns, deadline
        )
        return plan, _usage_of(llm, started)

    async def assess_coverage(self, state, max_turns, deadline):
        llm = roles.llm_for("lead", max_turns)
        started = time.monotonic()
        out = await roles.assess_coverage(state, llm, max_turns, deadline)
        return out, _usage_of(llm, started)

    async def analyze(self, state, note, max_turns, deadline):
        llm = roles.llm_for("analyst", max_turns)
        started = time.monotonic()
        out = await roles.analyze(state, note, llm, max_turns, deadline)
        return out, _usage_of(llm, started)

    async def review_claims(self, state, claim_ids, max_turns, deadline):
        llm = roles.llm_for("verifier", max_turns)
        started = time.monotonic()
        out = await roles.review_claims(
            state, claim_ids, llm, max_turns, deadline
        )
        return out, _usage_of(llm, started)

    async def write(self, state, instructions, max_turns, deadline):
        llm = roles.llm_for("editor", max_turns)
        started = time.monotonic()
        out = await roles.write(state, instructions, llm, max_turns, deadline)
        return out, _usage_of(llm, started)

    async def final_review(self, state, max_turns, deadline):
        llm = roles.llm_for("verifier", max_turns)
        started = time.monotonic()
        out = await roles.final_review(state, llm, max_turns, deadline)
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
        if call.task_id == node and call.status == "running":
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


def reserve_node(node: str, limits: records.Limits):
    """The checkpointed admission step that precedes a single-call node."""

    async def reserve(state: state_module.IndustryState) -> dict[str, Any]:
        allowed = budget.admit_single_call(state, limits, node)
        if allowed <= 0:
            return {
                "route_log": [
                    f"reserve_{node}: refused, budget exhausted; {node} "
                    "will be skipped"
                ]
            }
        calls = dict(state.get("single_calls", {}))
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


def pending_review(state: state_module.IndustryState) -> list[str]:
    """The claims the verifier judges next: unreviewed material or map.

    Review is bounded by the budget, so the order is the priority in
    which claims earn citability, interleaved so no group starves: one
    queue for map claims (the value chain and its participants) and one
    per central question, taken round-robin in id order, then the
    remaining material claims; at most ``REVIEW_BATCH`` per call.
    """
    unreviewed = sorted(
        (
            c
            for c in state.get("claims", {}).values()
            if c.review == "unreviewed" and c.material
        ),
        key=lambda c: merge.schedule.task_number(c.id),
    )
    queues: dict[str, list[str]] = {"map": []}
    for question in records.CENTRAL_QUESTIONS:
        queues[f"q{question}"] = []
    rest: list[str] = []
    for claim in unreviewed:
        if claim.map_ref is not None:
            queues["map"].append(claim.id)
            continue
        central = [q for q in claim.questions if q in records.CENTRAL_QUESTIONS]
        if central:
            queues[f"q{min(central)}"].append(claim.id)
        else:
            rest.append(claim.id)
    ordered: list[str] = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                ordered.append(queue.pop(0))
    ordered.extend(rest)
    return ordered[:REVIEW_BATCH]


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


def review_remaining(state: state_module.IndustryState) -> int:
    """How many material claims are still unreviewed."""
    return sum(
        1
        for c in state.get("claims", {}).values()
        if c.review == "unreviewed" and c.material
    )


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


def planning_purpose(state: state_module.IndustryState) -> str:
    """What prepare_tasks plans for in the state's phase."""
    return PURPOSES.get(state.get("phase", "mapping"), PURPOSES["remediation"])


def planning_slots(
    state: state_module.IndustryState, limits: records.Limits
) -> int:
    """How many tasks prepare_tasks may create now."""
    keep_slot = state.get("review_rounds", 0) == 0
    return budget.dispatchable(state, limits, keep_slot)


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


def _map_task(brief: records.Brief) -> records.Task:
    return records.Task(
        id="T1",
        kind="map",
        role="industry",
        objective=(
            f"Map the {brief.industry} value chain: upstream, midstream, "
            "downstream, and adjacent segments; what flows between them; "
            "representative participants per segment (global leaders and "
            "Chinese participants) with what each supplies or buys."
        ),
        scope=brief.geography,
        required_fields=[
            "segments with stage and description",
            "links with what flows",
            "participants with role, supplies/buys, region, listed",
            "boundary note",
        ],
        acceptance=(
            "Every segment, link, and participant cites a passage from a "
            "fetched source; at least two participants per stage."
        ),
    )


def _tasks_from_plan(
    state: state_module.IndustryState,
    plan: roles.TaskPlan,
    slots: int,
    kind: records.TaskKind,
) -> tuple[dict[str, records.Task], dict[str, records.Issue], list[str]]:
    tasks = dict(state.get("tasks", {}))
    issues = dict(state.get("issues", {}))
    evidence = state.get("evidence", {})
    log: list[str] = []
    key_to_id: dict[str, str] = {}
    accepted: list[roles.TaskSpec] = []
    next_number = schedule.task_number(merge.next_id("T", tasks))
    for spec in plan.tasks:
        if spec.key in key_to_id:
            log.append(f"prepare_tasks: duplicate key {spec.key!r} dropped")
            continue
        if len(accepted) >= slots:
            log.append(
                f"prepare_tasks: {spec.key!r} beyond the {slots} slots the "
                "budget allows; dropped"
            )
            continue
        key_to_id[spec.key] = f"T{next_number}"
        next_number += 1
        accepted.append(spec)
    for spec in accepted:
        task_id = key_to_id[spec.key]
        depends = []
        for dep in spec.depends_on:
            resolved = key_to_id.get(dep, dep if dep in tasks else None)
            if resolved is None:
                log.append(f"{task_id}: dependency {dep!r} unknown; dropped")
            elif resolved != task_id:
                depends.append(resolved)
        references = [r for r in spec.references if r in evidence]
        issue_id = spec.issue_id if spec.issue_id in issues else None
        if issue_id:
            issue = issues[issue_id]
            issues[issue_id] = issue.model_copy(
                update={"attempts": issue.attempts + 1, "evidence_added": False}
            )
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
            issue_id=issue_id,
        )
        log.append(f"{task_id} ({spec.role}): {spec.objective[:80]}")
    if len(plan.tasks) > slots:
        log.append(
            f"prepare_tasks: {len(plan.tasks) - slots} proposed tasks "
            "beyond the budget were not created"
        )
    return tasks, issues, log


def _close_followup_issues(
    issues: dict[str, records.Issue], limits: records.Limits
) -> tuple[dict[str, records.Issue], list[str]]:
    """Retire issues past the follow-up limit without a productive step."""
    updated = dict(issues)
    log = []
    for issue in issues.values():
        if issue.status != "open":
            continue
        over = issue.attempts >= limits.issue_follow_ups
        third_allowed = (
            issue.attempts == limits.issue_follow_ups
            and issue.evidence_added
            and bool(issue.next_step)
        )
        if over and not third_allowed:
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
            if issue.category == "contradiction" and claim.review in (
                "supported",
                "qualified",
            ):
                resolved = f"claim reviewed {claim.review}"
            elif issue.category == "unsupported" and (
                claim.review in ("supported", "qualified")
                or target not in cited
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
      runtime: The process runtime (limits, meters, semaphore, index lock).
      backend: The services behind the tools; the live backend if
        ``None``.
      api: The single-call roles; the live ones if ``None``.
      worker_fn: Runs one attempt (tests inject a fake).
      checkpointer: Where LangGraph saves state after each node.
    """
    limits = runtime.limits
    backend = backend or tools.LiveBackend()
    api = api or LiveRoles()

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
        output, usage = await call(max_turns, reservation.reserved.seconds)
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
                "tasks": {"T1": _map_task(brief)},
                "phase": "mapping",
                "cycle": 0,
                "follow_up_rounds": 0,
            }
        )
        update.setdefault("route_log", []).append(
            f"scope: industry {brief.industry!r}, language {brief.language}, "
            f"mode {brief.mode}; map task T1 created"
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
        attempts = dict(state.get("attempts", {}))
        # Acquisition attempts are capped for the run: beyond the cap a
        # ready acquisition task is skipped, never dispatched.
        acquisitions = sum(
            1
            for a in attempts.values()
            if state["tasks"][a.task_id].kind == "acquisition"
        )
        admitted = []
        for task in ready:
            if task.kind == "acquisition":
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
                acquisitions += 1
            admitted.append(task)
        ready = admitted
        meter = runtime.meter_for(thread_id) or runtime.new_meter(
            thread_id, state
        )
        log = []
        for task in ready[:slots]:
            attempt = records.Attempt(
                id=f"{task.id}.{task.attempts + 1}",
                task_id=task.id,
                reserved=budget.reservation_for(limits),
                started_at=records.now_iso(),
            )
            attempts[attempt.id] = attempt
            tasks[task.id] = task.model_copy(
                update={"status": "running", "attempts": task.attempts + 1}
            )
            meter.register(attempt.id, attempt.reserved.tool_calls)
            log.append(f"dispatch: {attempt.id} reserved and admitted")
        if len(ready) > slots:
            log.append(
                f"dispatch: {len(ready) - slots} ready tasks wait for budget"
            )
        if not ready:
            log.append("dispatch: nothing ready")
        return {"tasks": tasks, "attempts": attempts, "route_log": log}

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
        runtime.drop(_thread_id())
        return update

    def after_merge(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and budget.dispatchable(state, limits, False) > 0:
            return "dispatch"
        if state.get("phase", "mapping") == "mapping":
            return "reserve_prepare_tasks"
        return "reserve_review"

    async def prepare_tasks(
        state: state_module.IndustryState,
    ) -> dict[str, Any]:
        phase = state.get("phase", "mapping")
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
                tasks, issues, log = _tasks_from_plan(state, plan, slots, kind)
                update.update({"tasks": tasks, "issues": issues})
                update["route_log"].extend(log)
                if plan.rationale:
                    update["route_log"].append(
                        f"prepare_tasks: {plan.rationale[:200]}"
                    )
        if phase == "mapping":
            update["phase"] = "researching"
        return update

    def after_prepare(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and budget.dispatchable(state, limits, False) > 0:
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
            central = item.question in records.CENTRAL_QUESTIONS
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
        calculations = dict(state.get("calculations", {}))
        claims = dict(state.get("claims", {}))
        log: list[str] = []

        async def first(max_turns: int, deadline: float):
            return await api.analyze(state, note, max_turns, deadline)

        analysis, update = await call_with_reservation(state, "analyze", first)
        update.setdefault("route_log", []).extend(log)
        if analysis is None:
            return update
        if analysis.calc_requests:
            # Only reviewed quantities may enter a calculation; anything
            # else is a missing input, never a number.
            inputs = {
                cid: records.CalcInput(
                    claim_id=cid,
                    value=c.quantity.value,
                    unit=c.quantity.unit,
                    period=c.quantity.period,
                    scope=c.quantity.scope,
                )
                for cid, c in claims.items()
                if c.quantity is not None
                and c.review in ("supported", "qualified")
            }
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
                    cited = [i.claim_id for i in result.inputs]
                    evidence_ids: list[str] = []
                    for cid in cited:
                        for eid in claims[cid].evidence_ids:
                            if eid not in evidence_ids:
                                evidence_ids.append(eid)
                    cited_text = ", ".join(cited)
                    claims[claim_id] = records.Claim(
                        id=claim_id,
                        statement=(
                            f"{result.label}: {result.result} {result.unit} "
                            f"(computed from {cited_text}; {result.formula})"
                        ),
                        kind="derived",
                        evidence_ids=evidence_ids,
                        calculation_id=calc_id,
                        material=merge.admit_material(claims, limits, "q4"),
                        partition="q4",
                        review=(
                            "qualified"
                            if result.alignment_note
                            or any(
                                claims[cid].review == "qualified"
                                for cid in cited
                            )
                            else "supported"
                        ),
                        quantity=records.Quantity(
                            value=result.result or 0.0,
                            unit=result.unit or "",
                            period=result.inputs[-1].period,
                            scope=result.inputs[-1].scope,
                            as_written=str(result.result),
                        ),
                        limitations=(
                            [f"alignment: {result.alignment_note}"]
                            if result.alignment_note
                            else []
                        ),
                        questions=[4],
                        origin=calc_id,
                    )
                    update["route_log"].append(
                        f"analyze: {calc_id} = {result.result} {result.unit} "
                        f"-> {claim_id}"
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
                if cid in claims
                and claims[cid].review in ("supported", "qualified")
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
        pending = pending_review(state)
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
        update.update(
            {
                "claims": applied["claims"],
                "relationships": applied["relationships"],
                "sources": applied["sources"],
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
        update["findings"] = merge.stale_findings(
            state.get("findings", {}), newly_bad
        )
        created = 0
        wanted = outcome.acquisitions
        if len(wanted) > limits.acquisitions_per_review:
            update["route_log"].append(
                f"review: {len(wanted)} acquisition requests, the first "
                f"{limits.acquisitions_per_review} taken"
            )
            wanted = wanted[: limits.acquisitions_per_review]
        for request in wanted:
            task_id = merge.next_id("T", tasks)
            references = []
            if request.claim_id in claims:
                references = list(claims[request.claim_id].evidence_ids)
            tasks[task_id] = records.Task(
                id=task_id,
                kind="acquisition",
                role="verifier",
                objective=request.objective
                + (f" URL: {request.url}" if request.url else ""),
                references=references,
                acceptance=(
                    "The original passage supporting or contradicting the "
                    "claim is retrieved and cited."
                ),
            )
            created += 1
        update["tasks"] = tasks
        update["issues"] = issues
        if created:
            update["phase"] = "acquisition"
        remaining = review_remaining({**state, **update})
        update["route_log"].append(
            f"review: {len(outcome.claims)} verdicts, {len(newly_bad)} "
            f"unsupported/contradicted, {created} acquisition tasks, "
            f"{remaining} claims still unreviewed"
        )
        return update

    def _progress(state: state_module.IndustryState) -> bool:
        return state_module.registry_signature(state) != state.get(
            "last_signature", ""
        )

    def after_review(state: state_module.IndustryState) -> str:
        _, ready = schedule.ready(schedule.validate(state.get("tasks", {})))
        if ready and budget.dispatchable(state, limits, False) > 0:
            return "dispatch"
        last = running_reservation(state, "review")
        if (
            review_remaining(state) > 0
            and last is None
            and budget.admit_single_call(state, limits, "review") > 0
        ):
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
        return {
            "research": "reserve_prepare_tasks",
            "analyze": "reserve_analyze",
            "write": "reserve_write",
        }[state.get("return_to", "write")]

    async def write(state: state_module.IndustryState) -> dict[str, Any]:
        instructions = write_instructions(state)

        async def call(max_turns: int, deadline: float):
            return await api.write(state, instructions, max_turns, deadline)

        draft, update = await call_with_reservation(state, "write", call)
        update.setdefault("route_log", [])
        if draft is None:
            return update
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
            sections, state.get("claims", {}), report.known_entities(state)
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
        async def call(max_turns: int, deadline: float):
            return await api.final_review(state, max_turns, deadline)

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
                issues, issue = merge.open_issue(
                    issues,
                    problem.category,
                    problem.severity,
                    problem.section_id,
                    action,
                    f"[{problem.section_id}] {problem.description}{claim_note}",
                    draft_version=version,
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
            update["final_review"] = outcome
            update["final_review_version"] = version
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
        ):
            return "remediate"
        return "deliver"

    async def deliver(state: state_module.IndustryState) -> dict[str, Any]:
        derived = coverage_module.derive(state, state.get("assessment"))
        review = state.get("final_review")
        verified = (
            review is not None
            and review.consistent
            and state.get("final_review_version")
            == state.get("draft_version", 0)
        )
        status = coverage_module.report_status(derived, state, verified)
        text = report.render(state, derived, status)
        path = report.write_report(_thread_id(), text, runtime.reports_dir)
        meta = state["meta"].model_copy(
            update={
                "execution_status": "completed",
                "report_status": status,
                "report_path": path,
            }
        )
        return {
            "coverage": derived,
            "meta": meta,
            "route_log": [f"deliver: {status}; report {path}"],
        }

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
        ["reserve_prepare_tasks", "reserve_analyze", "reserve_write"],
    )
    graph.add_edge("write", "reserve_final_review")
    graph.add_conditional_edges(
        "final_review",
        after_final,
        {"remediate": "remediate", "deliver": "deliver"},
    )
    graph.add_edge("deliver", END)
    return graph.compile(checkpointer=checkpointer)
