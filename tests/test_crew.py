"""Phase 9 crew tests: the adapter, the crew seam, and the role functions.

No model calls: a ``FakeLLM`` stands in for ``ClaudeLLM`` behind a real
CrewAI agent, task, and crew, so what CrewAI adds around the existing
prompts is asserted exactly.
"""

import asyncio
import os
from typing import Any

import pydantic

from research import crew
from research import evaluate

# CrewAI's framing around a no-tools agent, pinned with the package.
SYSTEM_FRAME = "You are {name}. {backstory}\nYour personal goal is: {goal}"
USER_FRAME = (
    "\nCurrent Task: {description}\n\n"
    "This is the expected criteria for your final answer: {expected}\n"
    "you MUST return the actual complete content as the final answer, "
    "not a summary.\n\n"
    "Provide your complete response:"
)


class FakeLLM(crew.crewai.BaseLLM):
    """Returns a canned reply and records what CrewAI sent.

    CrewAI's executor calls the synchronous ``call`` from a worker
    thread, as it does with ``ClaudeLLM``.
    """

    reply: Any = None
    seen: list[tuple[Any, Any]] = pydantic.Field(default_factory=list)

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        self.seen.append((messages, response_model))
        return self.reply


def run(coroutine):
    return asyncio.run(coroutine)


def test_environment_is_locked_down_on_import():
    assert os.environ["CREWAI_DISABLE_TELEMETRY"] == "true"
    assert os.environ["CREWAI_TRACING_ENABLED"] == "false"


def test_claude_llm_answers_the_capability_probes():
    llm = crew.ClaudeLLM()
    assert llm.model == "claude-sonnet-5"
    assert llm.supports_stop_words() is False
    assert llm.get_context_window_size() == crew.CONTEXT_WINDOW
    # No tools are ever given, so CrewAI must not take the native
    # tool-calling path; the probe it uses is the attribute's absence.
    assert getattr(llm, "supports_function_calling", None) is None


def test_split_messages_separates_system_from_the_rest():
    assert crew.split_messages("just a prompt") == ("", "just a prompt")
    system, user = crew.split_messages(
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "draft"},
        ]
    )
    assert system == "rules"
    assert user == "question\n\ndraft"


def test_run_task_returns_text_without_the_marker_and_frames_only():
    role = crew.Role("Writer", "Write it.", "You write answers.\nPlainly.")
    fake = FakeLLM(model="fake", reply=crew.FINAL_ANSWER + "the answer")
    result = run(crew.run_task(role, "Question:\nWhy?", "One line.", fake))
    assert result == "the answer"
    assert len(fake.seen) == 1
    messages, response_model = fake.seen[0]
    assert response_model is None
    system, user = crew.split_messages(messages)
    assert system == SYSTEM_FRAME.format(
        name="Writer", backstory=role.backstory, goal=role.goal
    )
    assert user == USER_FRAME.format(
        description="Question:\nWhy?", expected="One line."
    )


def test_run_task_returns_the_output_model_from_a_structured_reply():
    role = crew.Role(
        "Judge", "Judge it.", "You judge.", evaluate.EvidenceEvaluation
    )
    verdict = evaluate.EvidenceEvaluation.model_validate(
        {
            "question_answerable_from_observations": False,
            "missing_evidence": ["No 2025 revenue figure."],
        }
    )
    fake = FakeLLM(model="fake", reply=verdict)
    result = run(crew.run_task(role, "Question:\nRevenue?", "JSON.", fake))
    assert result is verdict
    assert fake.seen[0][1] is evaluate.EvidenceEvaluation


def test_run_task_leaves_braces_in_the_description_alone():
    role = crew.Role("Writer", "Write it.", "You write.")
    fake = FakeLLM(model="fake", reply=crew.FINAL_ANSWER + "ok")
    description = 'Observation: {"revenue": null} and {gap}'
    run(crew.run_task(role, description, "One line.", fake))
    _, user = crew.split_messages(fake.seen[0][0])
    assert description in user
