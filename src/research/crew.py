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
from typing import Any

import claude_agent_sdk
import pydantic

from research import evaluate as evaluate_module
from research import plan as plan_module

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

    def __init__(self) -> None:
        super().__init__(model=MODEL)

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
          RuntimeError: If the SDK reports an error or returns nothing.
        """
        del tools, callbacks, available_functions, from_task, from_agent
        system_prompt, prompt = split_messages(messages)
        options = claude_agent_sdk.ClaudeAgentOptions(
            model=MODEL,
            system_prompt=system_prompt,
            tools=[],
            # Structured output arrives through an extra SDK turn and may
            # need a second attempt (Phase 6.2); text is one turn.
            max_turns=1 if response_model is None else 5,
            setting_sources=[],
            env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        )
        if response_model is not None:
            options.output_format = {
                "type": "json_schema",
                "schema": response_model.model_json_schema(),
            }
        result = None
        async for message in claude_agent_sdk.query(
            prompt=prompt, options=options
        ):
            if isinstance(message, claude_agent_sdk.ResultMessage):
                result = message
        if result is None or result.is_error:
            errors = result.errors if result else "no result"
            raise RuntimeError(f"Model call failed: {errors}")
        if response_model is None:
            if result.result is None:
                raise RuntimeError("Model call returned no text.")
            return FINAL_ANSWER + result.result
        if result.structured_output is None:
            raise RuntimeError("Model call returned no structured output.")
        return response_model.model_validate(result.structured_output)

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
        """
        return asyncio.run(
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

    Returns:
      The task's text, or an instance of ``role.output`` when it has one.

    Raises:
      RuntimeError: If the model call fails, or a structured task did
        not produce its model.
    """
    agent = crewai.Agent(
        role=role.name,
        goal=role.goal,
        backstory=role.backstory,
        llm=llm or ClaudeLLM(),
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
    output = await crew.akickoff()
    task_output = output.tasks_output[0]
    if role.output is None:
        return task_output.raw
    if not isinstance(task_output.pydantic, role.output):
        raise RuntimeError(
            f"{role.name} task returned no {role.output.__name__}."
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
