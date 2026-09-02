"""One text call: the final answer from every research round's evidence.

The synthesis sees all tool observations (the evidence) and each round's
answer (context only), and writes one grounded answer. It never
researches or calls tools; unresolved gaps are disclosed by the
workflow in Python, not by this prompt.
"""

import claude_agent_sdk

from research import agent
from research import plan as plan_module

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""\
You write the final answer to a research question from evidence
gathered in one or more research rounds. You do not research, call
tools, or add facts of your own.

The tool observations are the evidence; use all of them, from every
round. Factual support must come from the observations. Cite each
claim with the label it carries in the observations, such as [S2]; a
final citation is always [S#]. The round answers show how each round
read its evidence; they are context, not evidence, and a claim that
appears only in a round answer is unsupported. Labels such as [D1] or
[W1] inside the round answers are round-local and are not valid
citations. Answer what the evidence supports and no more. If it
supports nothing, reply with exactly:
{agent.EVIDENCE_GAP}
Write plain prose.
"""


def build_prompt(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answers: list[str],
    evidence: list[str],
) -> str:
    """Lay out question, plan, round answers, and observations as one message.

    Args:
      question: The user's question.
      research_plan: The planning result; only the chosen approach is
        shown, or "none" for a single-path question.
      answers: One answer per research round, in order.
      evidence: Every tool observation from every round, in order.

    Returns:
      The prompt text, exactly as it will be sent.
    """
    chosen = research_plan.chosen() if research_plan.use_tot else None
    plan_text = (
        f"({chosen.label}) {chosen.approach}"
        if chosen
        else "none: single-path question"
    )
    answers_text = "\n\n".join(
        f"--- round {number} answer ---\n{answer}"
        for number, answer in enumerate(answers, start=1)
    )
    return (
        f"Question:\n{question}\n\n"
        f"Research plan:\n{plan_text}\n\n"
        f"Round answers (context, not evidence):\n{answers_text}\n\n"
        f"Tool observations (evidence):\n{agent.format_observations(evidence)}"
    )


async def synthesize(
    question: str,
    research_plan: plan_module.ResearchPlan,
    answers: list[str],
    evidence: list[str],
) -> str:
    """Run the synthesis call and return the final answer text.

    Args:
      question: The user's question.
      research_plan: The planning result for the question.
      answers: One answer per research round.
      evidence: Every tool observation from every round.

    Returns:
      The synthesised answer, or the fixed evidence-gap sentence.

    Raises:
      RuntimeError: If the call fails or returns no result.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        max_turns=1,
        setting_sources=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    prompt = build_prompt(question, research_plan, answers, evidence)
    result = None
    async for message in claude_agent_sdk.query(prompt=prompt, options=options):
        if isinstance(message, claude_agent_sdk.ResultMessage):
            result = message
    if result is None or result.is_error or result.result is None:
        errors = result.errors if result else "no result"
        raise RuntimeError(f"Synthesis failed: {errors}")
    return result.result
