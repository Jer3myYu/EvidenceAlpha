"""One structured call: does the collected evidence answer the question?

The evaluator sees the question, the selected research approach, the
agent's answer, and the raw tool observations, and returns a validated
``EvidenceEvaluation``. It never researches, calls tools, or rewrites
the answer; the workflow (``research.workflow``) decides what to do with
the verdict.
"""

import claude_agent_sdk
import pydantic

from research import plan as plan_module

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """\
You judge whether collected evidence is sufficient to answer a research
question. You do not research, search, call tools, or invent evidence,
and you do not grade or rewrite the answer's writing.

The tool observations are the evidence. The agent answer is context
that shows which claims were made; it is not proof of anything, and an
answer that reports that nothing was found does not make the evidence
sufficient. Judge the observations against the original question and,
if one is given, the selected research approach:
1. Do the observations contain the information the question asks for,
   at the scope it asks for?
2. Are the factual claims the answer makes supported by observations?
3. Are the observations relevant to the requested scope and time?
4. Are material conflicts, uncertainties, or unknowns identified?

question_answerable_from_observations is about whether the question
can be answered from the observations, not about whether the search
was thorough. If the question asks for specific information (a figure,
a date, a name, a list) and no observation states it for the right
entity and period, it is false, even when the search was extensive and
the absence is well established. Otherwise it is true when the
observations are adequate for a grounded answer at the requested
scope, not perfect or exhaustive: do not set it false merely because
stronger sources could exist, only when missing evidence materially
affects the answer.

missing_evidence lists the gaps when it is false: each entry is one
sentence naming the specific missing evidence another research round
could go and find, for example "No source gives Acme Robotics' revenue
for 2025". Entries are not comments on wording, and there are only as
many as matter. When the question is answerable, missing_evidence is
empty.

Return only the structured evaluation.
"""


class EvidenceEvaluation(pydantic.BaseModel):
    """The evaluator's verdict.

    Attributes:
      sufficient: Whether the evidence supports a grounded answer at the
        requested scope.
      gaps: Specific, actionable research gaps; empty when sufficient.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    # The JSON keys the model fills are aliased on purpose. Named
    # "sufficient", the key made Sonnet 5 judge a well-supported "nothing
    # was found" answer as sufficient in every trial (2026-09-02); named
    # for the question, it reported the missing figure every time.
    sufficient: bool = pydantic.Field(
        alias="question_answerable_from_observations"
    )
    gaps: list[str] = pydantic.Field(alias="missing_evidence")


def build_prompt(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answer: str,
    observations: list[str],
) -> str:
    """Lay out question, plan, answer, and raw observations as one message.

    Args:
      question: The user's question.
      research_plan: The planning result; only the chosen approach is
        shown, or "none" for a single-path question.
      answer: The agent's answer, verbatim.
      observations: The agent's tool observations, verbatim, in order.

    Returns:
      The prompt text, exactly as it will be sent.
    """
    chosen = research_plan.chosen() if research_plan.use_tot else None
    plan_text = (
        f"({chosen.label}) {chosen.approach}"
        if chosen
        else "none: single-path question"
    )
    observation_text = (
        "\n".join(
            f"--- observation {number} ---\n{observation}"
            for number, observation in enumerate(observations, start=1)
        )
        or "none: no tool was called"
    )
    return (
        f"Question:\n{question}\n\n"
        f"Research plan:\n{plan_text}\n\n"
        f"Agent answer:\n{answer}\n\n"
        f"Tool observations:\n{observation_text}"
    )


async def evaluate_evidence(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answer: str,
    observations: list[str],
) -> EvidenceEvaluation:
    """Run the evaluation call and return its validated verdict.

    Args:
      question: The user's question.
      research_plan: The planning result for the question.
      answer: The agent's answer for the round.
      observations: The agent's tool observations for the round.

    Returns:
      The verdict.

    Raises:
      RuntimeError: If the call fails or returns no structured output.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        # Structured output arrives through an extra SDK turn, and the
        # model sometimes needs a second attempt at it; 3 failed 2 of 8
        # trials, 5 has held.
        max_turns=5,
        output_format={
            "type": "json_schema",
            "schema": EvidenceEvaluation.model_json_schema(),
        },
        setting_sources=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    prompt = build_prompt(question, research_plan, answer, observations)
    result = None
    async for message in claude_agent_sdk.query(prompt=prompt, options=options):
        if isinstance(message, claude_agent_sdk.ResultMessage):
            result = message
    if result is None or result.is_error or result.structured_output is None:
        errors = result.errors if result else "no result"
        raise RuntimeError(f"Evaluation failed: {errors}")
    return EvidenceEvaluation.model_validate(result.structured_output)
