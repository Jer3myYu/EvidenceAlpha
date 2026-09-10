"""CrewAI roles for the workflow's single-call stages.

LangGraph orchestrates. CrewAI represents and executes bounded agent
roles. The Claude Agent SDK supplies the model and tool runtime.
``ResearchState`` provides durable structured coordination.

Each single-call stage of the workflow (plan, evaluate, finish, verify)
runs as a crew of exactly one agent and one task, built here and
awaited inside its graph node. The agent's role, goal, and backstory
are the stage's existing system prompt; the task's description is the
stage's existing prompt text; the model call is still one Claude Agent
SDK call, made through ``ClaudeLLM``. The Research Agent
(``research.agent``) is not a CrewAI agent: its tool loop stays in the
SDK and ``workflow.research_node`` calls it directly.

The only intentional prompt difference from the direct calls is
CrewAI's framing: two lines around the system prompt (``You are
{role}.`` and ``Your personal goal is: {goal}``) and four short lines
around the task (``Current Task:``, the expected-output criteria, and
``Provide your complete response:``). No delegation, memory,
hierarchy, flow, or persistence of CrewAI's is used; coordination
between roles is the typed workflow state, mediated by LangGraph.
"""

import asyncio
import dataclasses
import os
import threading
import uuid
from collections.abc import Callable
from typing import Any

import claude_agent_sdk
import pydantic

from industry import admission as admission_module
from industry import sdk_children
from research import evaluate as evaluate_module
from research import plan as plan_module
from research import sources as sources_module
from research import synthesize as synthesize_module
from research import verify as verify_module

# CrewAI reports usage to its vendor and, on a first run, asks on stdin
# whether to upload traces. Both are switched off before the package is
# imported, so no script or test can forget it.
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"

import crewai  # pylint: disable=wrong-import-position

MODEL = "claude-sonnet-5"
# Reported to CrewAI, which only uses it to decide whether to summarise
# a conversation; nothing here ever approaches it.
CONTEXT_WINDOW = 200_000
# CrewAI's executor accepts a plain-text answer only behind this marker
# and strips it; a structured answer needs none.
FINAL_ANSWER = "Final Answer: "
# How long a cancelled call may take to wind down before run_task gives
# up waiting for CrewAI's worker thread.
CANCEL_GRACE_SECONDS = 30.0


class RoleTimeout(TimeoutError):
    """A role's model call exceeded its deadline and was cancelled."""


class RoleFailure(RuntimeError):
    """A terminal model outcome, never a programming or cancellation error."""

    def __init__(
        self,
        message: str,
        usage: dict[str, Any] | None = None,
        kind: str = "schema",
    ) -> None:
        super().__init__(message)
        self.usage = usage
        self.kind = kind


class RoleHung(RuntimeError):
    """This call's cancellation did not stop it within the grace period.

    One meaning only: the call missed its deadline and its kickoff is
    still alive (including its SDK child teardown). The caller charges
    the reservation and degrades, as for ``RoleTimeout``; the live
    kickoff keeps its admission slot as a
    survivor, so the next admission anywhere in the process raises
    ``admission.Blocked`` until it ends -- that guard is the authority's,
    not this exception's.
    """


# The admission authority for callers without a runtime (the Phase 6-9
# workflow): unbounded, survivors tracked. The industry graph passes its
# ``Runtime.admission`` instead, so role calls and worker sessions share
# one bound and one record of what is live.
PROCESS = admission_module.Admission(None)


async def _stop(
    kickoff: asyncio.Future, llm: crewai.BaseLLM, grace: float
) -> bool:
    """Cancel the call in flight and wait for its kickoff to end.

    Returns ``True`` when the kickoff ended within ``grace`` (CrewAI
    wraps the cancellation in its own error types, so every outcome of
    the cancelled task counts as ended) and ``False`` when it did not.
    A cancellation of this wait itself (a second interruption)
    propagates; either way the caller settles the kickoff's slot, which
    is retained while the kickoff is alive.
    """
    cancel = getattr(llm, "cancel", None)
    if cancel is not None:
        cancel()
    try:
        await asyncio.wait_for(asyncio.shield(kickoff), grace)
    except asyncio.TimeoutError:
        return False
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise
        # The cancelled call ended with CancelledError itself.
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        return True
    return True


def split_messages(messages: str | list[dict[str, Any]]) -> tuple[str, str]:
    """Return CrewAI's conversation as one system text and one user text.

    Args:
      messages: A bare prompt, or CrewAI's ``role``/``content`` dicts.

    Returns:
      The system messages joined, and every other message joined, each
      with a blank line between parts.
    """
    if isinstance(messages, str):
        return "", messages
    system = [m["content"] for m in messages if m.get("role") == "system"]
    user = [m["content"] for m in messages if m.get("role") != "system"]
    return "\n\n".join(system), "\n\n".join(user)


class ClaudeLLM(crewai.BaseLLM):
    """CrewAI's LLM seam, served by one Claude Agent SDK call.

    With a response model the call is structured (the model's JSON
    schema as the SDK output format, validated before it is returned);
    without one it is a single text turn. Settings are the Phase 2
    ones: ``claude-sonnet-5``, no tools, no settings files, no
    auto-memory.
    """

    def __init__(
        self,
        model: str | None = None,
        max_turns: int = 5,
        thinking: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(model=model or MODEL)
        self.max_turns = max_turns
        # The SDK's thinking configuration for this role's calls
        # (``None`` leaves the model's default, adaptive, in place).
        self.thinking = thinking
        # What the last completed call consumed, as the SDK reported it.
        self.last_usage: dict[str, Any] | None = None
        self.on_invoke: Callable[[], None] | None = None
        self._cancel: Callable[[], None] | None = None
        self._cancel_requested = False
        self._cancel_lock = threading.Lock()
        self._children = sdk_children.Watch(f"role-{uuid.uuid4().hex}")

    def cancel(self) -> None:
        """Cancel the call in flight, or the next one, from any thread.

        A request that arrives before ``call`` has installed its handle
        is latched, so the call ends as soon as it starts.
        """
        with self._cancel_lock:
            self._cancel_requested = True
            if self._cancel is not None:
                self._cancel()

    def describe(self) -> str:
        """Name the child still owned by this role, when present."""
        return self._children.describe() or "CrewAI kickoff still running"

    async def _drain_children(self, teardown: list[asyncio.Future]) -> None:
        """Keep the SDK's loop alive until every child really terminates.

        This runs after the consumption task ends, outside its cancellation
        target. The caller's bounded grace may expire, but its retained
        kickoff still owns this loop, the teardown and the admission slot.
        Even exhausted terminate/kill escalation cannot release that slot
        over a surviving child.
        """
        # The cancellation backstop may have started before the SDK's
        # consumption finished. Scan again now that no more children can
        # start, and join both ends before closing their loop.
        pending = admission_module.when_all(*teardown, self._children.close())
        if pending is not None:
            await pending

    async def acall(
        self,
        messages: str | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: type[pydantic.BaseModel] | None = None,
    ) -> str | pydantic.BaseModel:
        """Make the call; return marked text or the validated model.

        CrewAI's default executor does not await this itself; it calls
        ``call`` from a thread, which runs this coroutine to completion.

        Raises:
          RoleFailure: If the SDK reports failure or invalid output.
        """
        del tools, callbacks, available_functions, from_task, from_agent
        system_prompt, prompt = split_messages(messages)
        options = claude_agent_sdk.ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            tools=[],
            # Structured output arrives through an extra SDK turn and may
            # need a second attempt (Phase 6.2); text is one turn.
            max_turns=1 if response_model is None else self.max_turns,
            setting_sources=[],
            env={
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                **sdk_children.marked_env(self._children.session_id),
            },
        )
        if self.thinking is not None:
            options.thinking = self.thinking
        if response_model is not None:
            options.output_format = {
                "type": "json_schema",
                "schema": response_model.model_json_schema(),
            }
        result = None
        exchanges = 0
        self.last_usage = None
        if self.on_invoke is not None:
            self.on_invoke()
        try:
            async for message in claude_agent_sdk.query(
                prompt=prompt, options=options
            ):
                if isinstance(message, claude_agent_sdk.AssistantMessage):
                    exchanges += 1
                if isinstance(message, claude_agent_sdk.ResultMessage):
                    result = message
                    # Save before advancing: the iterator can raise with
                    # this same terminal result. Never add it twice.
                    self._record_usage(dataclasses.asdict(message), exchanges)
        except claude_agent_sdk.ResultError as error:
            if self.last_usage is None:
                self._record_usage(error.data or {}, exchanges)
            kind = (
                "transport"
                if error.terminal_reason == "api_error"
                else "schema"
            )
            raise RoleFailure(str(error), self.last_usage, kind) from error
        if result is None or result.is_error:
            errors = result.errors if result else "no result"
            kind = (
                "transport"
                if result and result.terminal_reason == "api_error"
                else "schema"
            )
            raise RoleFailure(
                f"Model call failed: {errors}", self.last_usage, kind
            )
        if response_model is None:
            if result.result is None:
                raise RoleFailure(
                    "Model call returned no text.", self.last_usage
                )
            return FINAL_ANSWER + result.result
        if result.structured_output is None:
            raise RoleFailure(
                "Model call returned no structured output.", self.last_usage
            )
        try:
            return response_model.model_validate(result.structured_output)
        except pydantic.ValidationError as error:
            raise RoleFailure(
                f"Model output failed validation: {error}", self.last_usage
            ) from error

    def _record_usage(self, data: dict[str, Any], exchanges: int) -> None:
        """Keep the terminal cumulative payload, including cache categories."""
        if not any(
            data.get(key) is not None
            for key in ("num_turns", "usage", "total_cost_usd", "modelUsage")
        ):
            return
        self.last_usage = {
            "turns": data.get("num_turns"),
            "exchanges": exchanges,
            "usage": data.get("usage"),
            "model_usage": data.get("model_usage") or data.get("modelUsage"),
            "cost_usd": data.get("total_cost_usd"),
            "duration_ms": data.get("duration_ms"),
            "is_error": data.get("is_error"),
        }

    def call(
        self,
        messages: str | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: type[pydantic.BaseModel] | None = None,
    ) -> str | pydantic.BaseModel:
        """The entry CrewAI uses: its executor runs it in a worker thread.

        That thread has no event loop, so the SDK call gets a private
        one for its duration; the workflow's own loop is not involved.
        Cancellation targets only the consumption task. Every exit drains
        its children on this same loop before closing it or returning to
        CrewAI: kickoff completion therefore includes actual child exit.
        """
        if self._cancel_requested:
            raise asyncio.CancelledError("cancelled before the call started")
        loop = asyncio.new_event_loop()
        teardown: list[asyncio.Future] = []
        try:
            task = loop.create_task(
                self.acall(
                    messages,
                    tools,
                    callbacks,
                    available_functions,
                    from_task,
                    from_agent,
                    response_model,
                )
            )

            def cancel_call() -> None:
                task.cancel()
                if not teardown:
                    # SDK cleanup itself can stall inside task. Its full
                    # grace still applies, but escalation must not depend
                    # on that task returning before the backstop starts.
                    teardown.append(self._children.close())

            with self._cancel_lock:
                self._cancel = lambda: loop.call_soon_threadsafe(cancel_call)
                if self._cancel_requested:
                    task.cancel()
            return loop.run_until_complete(task)
        finally:
            # Removing the handle under the same lock as cancel() prevents
            # a racing caller from scheduling onto a closed private loop.
            # Further cancellation is latched; it cannot tear away cleanup.
            with self._cancel_lock:
                self._cancel = None
            try:
                loop.run_until_complete(self._drain_children(teardown))
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def supports_stop_words(self) -> bool:
        """Stop sequences are not forwarded; the call is one turn anyway."""
        return False

    def get_context_window_size(self) -> int:
        """Claude's window, so CrewAI never tries to summarise a prompt."""
        return CONTEXT_WINDOW


@dataclasses.dataclass(frozen=True)
class Role:
    """A CrewAI agent definition for one existing system prompt.

    Attributes:
      name: The agent's role, as CrewAI names it.
      goal: One sentence; CrewAI appends it to the system prompt.
      backstory: The stage's existing system prompt, verbatim.
      output: The pydantic model the task must return, or ``None`` for
        plain text.
    """

    name: str
    goal: str
    backstory: str
    output: type[pydantic.BaseModel] | None = None


async def run_task(
    role: Role,
    description: str,
    expected_output: str,
    llm: crewai.BaseLLM | None = None,
    deadline: float | None = None,
    grace: float | None = None,
    admission: admission_module.Admission | None = None,
) -> str | pydantic.BaseModel:
    """Run one task as a crew of one agent and return its output.

    The agent, task, and crew are built for this call: CrewAI mutates
    them while running. No delegation, no retries, no memory, no
    console output.

    Args:
      role: The agent definition.
      description: The task's full prompt text.
      expected_output: One sentence on what the task must return.
      llm: The model seam; ``ClaudeLLM`` unless a test injects a fake.
      deadline: Seconds after which the call is cancelled. CrewAI runs
        the model call in a worker thread, so on timeout the LLM's
        ``cancel`` is called and the crew is awaited until that thread
        has finished (bounded by ``grace``) before ``RoleTimeout`` is
        raised; if it has not finished by then ``RoleHung`` is raised
        instead, so nothing keeps running unobserved. An external
        cancellation of this coroutine (an interruption, a shutdown)
        stops the call the same way and then propagates: the kickoff
        never outlives its deadline watcher unrecorded.
      grace: Seconds to wait for the cancelled call to wind down
        (``CANCEL_GRACE_SECONDS`` unless given).
      admission: The authority the call takes its slot from, held until
        the kickoff, including SDK child teardown, has actually ended:
        a kickoff that outlives its cancellation keeps the slot as a
        survivor, and nothing is
        admitted in that process until it ends. The industry graph
        passes its runtime's; callers without one get ``PROCESS``.

    Returns:
      The task's text, or an instance of ``role.output`` when it has one.

    Raises:
      RoleTimeout: If ``deadline`` passed and the call was stopped.
      RoleHung: If ``deadline`` passed and the call did not stop.
      admission.Blocked: If an earlier operation that outlived its
        cancellation is still live; no call is started.
      RoleFailure: If the model call fails, or a structured task did
        not produce its model.
    """
    if grace is None:
        grace = CANCEL_GRACE_SECONDS
    authority = admission or PROCESS
    llm = llm or ClaudeLLM()
    agent = crewai.Agent(
        role=role.name,
        goal=role.goal,
        backstory=role.backstory,
        llm=llm,
        allow_delegation=False,
        verbose=False,
        max_iter=1,
        max_retry_limit=0,
    )
    task_settings: dict[str, Any] = {}
    if role.output is not None:
        # output_pydantic types the task's output; response_model hands
        # the same model to the LLM call and, being set, keeps CrewAI
        # from pasting the JSON schema into the task prompt.
        task_settings["output_pydantic"] = role.output
        task_settings["response_model"] = role.output
    task = crewai.Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
        **task_settings,
    )
    crew = crewai.Crew(
        agents=[agent],
        tasks=[task],
        process=crewai.Process.sequential,
        verbose=False,
    )
    # One of the process's slots, shared with the worker sessions; a
    # survivor anywhere in the process refuses this before any call.
    slot = await authority.acquire(
        "role", role.name, getattr(llm, "describe", None)
    )
    kickoff: asyncio.Future | None = None
    try:
        if isinstance(llm, ClaudeLLM):
            llm.on_invoke = slot.invoked
        slot.kickoff()
        kickoff = asyncio.ensure_future(crew.akickoff())
        try:
            output = await asyncio.wait_for(asyncio.shield(kickoff), deadline)
        except asyncio.TimeoutError:
            if not await _stop(kickoff, llm, grace):
                raise RoleHung(
                    f"{role.name} exceeded {deadline:.0f} s and did not stop "
                    f"within {grace:.0f} s after cancellation."
                ) from None
            raise RoleTimeout(
                f"{role.name} exceeded {deadline:.0f} s and was cancelled."
            ) from None
        except asyncio.CancelledError:
            # The shield keeps the kickoff alive through this
            # cancellation; left alone it would run on with no deadline
            # watcher and no record of it. It is stopped like a timed-out
            # call before the cancellation goes on.
            await _stop(kickoff, llm, grace)
            raise
    finally:
        # ClaudeLLM keeps its private loop and kickoff alive through actual
        # SDK child exit. Thus this one completion includes both lifetimes.
        # The slot ends with the kickoff, not with this coroutine:
        # released now if the kickoff has ended, kept as a survivor until
        # it does otherwise -- after a grace that expired, or a second
        # interruption during the wait.
        slot.settle(kickoff)
    if not output.tasks_output:
        raise RoleFailure(
            f"{role.name} task returned no output.",
            getattr(llm, "last_usage", None),
        )
    task_output = output.tasks_output[0]
    if role.output is None:
        return task_output.raw
    if not isinstance(task_output.pydantic, role.output):
        raise RoleFailure(
            f"{role.name} task returned no {role.output.__name__}.",
            getattr(llm, "last_usage", None),
        )
    return task_output.pydantic


PLANNER = Role(
    "Research planner",
    "Decide whether the question needs a choice between research "
    "structures and, if it does, choose one.",
    plan_module.SYSTEM_PROMPT,
    plan_module.PlanOutput,
)
EVALUATOR = Role(
    "Evidence evaluator",
    "Judge whether the collected evidence answers the question and name "
    "exactly what is missing.",
    evaluate_module.SYSTEM_PROMPT,
    evaluate_module.EvidenceEvaluation,
)


async def plan(
    question: str, llm: crewai.BaseLLM | None = None
) -> plan_module.ResearchPlan:
    """The planner's task: the question alone, as ``plan_research`` sends it."""
    output = await run_task(
        PLANNER, question, "The structured research plan.", llm
    )
    return plan_module.parse_plan(output.model_dump())


async def evaluate(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answer: str,
    observations: list[str],
    llm: crewai.BaseLLM | None = None,
) -> evaluate_module.EvidenceEvaluation:
    """The evaluator's task: ``evaluate.build_prompt`` as the description."""
    description = evaluate_module.build_prompt(
        question, research_plan, answer, observations
    )
    return await run_task(
        EVALUATOR, description, "The structured evaluation.", llm
    )


REPORTER = Role(
    "Report writer",
    "Write the final answer from the evidence, citing only the [S#] "
    "labels the observations carry.",
    synthesize_module.SYSTEM_PROMPT,
)
VERIFIER = Role(
    "Answer verifier",
    "Check every claim, citation, and conflict in the answer against the "
    "evidence alone.",
    verify_module.SYSTEM_PROMPT,
    verify_module.Verification,
)


async def report(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answers: list[str],
    evidence: list[str],
    draft: str | None = None,
    findings: str | None = None,
    llm: crewai.BaseLLM | None = None,
) -> str:
    """The reporter's task: ``synthesize.build_prompt``, revision included."""
    description = synthesize_module.build_prompt(
        question, research_plan, answers, evidence, draft, findings
    )
    return await run_task(
        REPORTER,
        description,
        "The answer as plain prose, citing [S#] labels only.",
        llm,
    )


async def verify(
    question: str,
    answer: str,
    evidence: list[str],
    sources: dict[str, sources_module.SourceRecord],
    llm: crewai.BaseLLM | None = None,
) -> verify_module.Verification:
    """The verifier's task: ``verify.build_prompt``; no plan, no rounds."""
    description = verify_module.build_prompt(
        question, answer, evidence, sources
    )
    return await run_task(
        VERIFIER, description, "The structured verification.", llm
    )
