"""Lightweight Tree-of-Thought planning: one structured Claude call.

Before the research agent runs, one call decides whether the question
has several plausible research structures. If it does, the call returns
three candidate approaches rated on three criteria and picks one; the
agent then follows the chosen approach. If it does not, the plan says so
and the agent runs unchanged. Depth is one, candidates three, survivor
one. This is a visible planning artifact, not hidden reasoning.
"""

import dataclasses
from typing import Any

import claude_agent_sdk

MODEL = "claude-sonnet-5"

RATING = {"type": "string", "enum": ["strong", "medium", "weak"]}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "use_tot": {"type": "boolean"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "approach": {"type": "string"},
                    "scope": RATING,
                    "evidence": RATING,
                    "coverage": RATING,
                },
                "required": [
                    "label",
                    "approach",
                    "scope",
                    "evidence",
                    "coverage",
                ],
                # Candidate(**item) accepts exactly these keys; an extra
                # one from the model (seen: "approach_detail") crashed it.
                "additionalProperties": False,
            },
        },
        "selected": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["use_tot", "candidates", "selected", "reason"],
}

SYSTEM_PROMPT = """\
You plan research for an investment-research assistant. Decide whether
the user's question needs a choice between several plausible research
structures before evidence is gathered.

Set use_tot to false for questions with one clear path: a fact lookup,
a definition, a question answered by reading one document or one search.
Then candidates is empty, selected is "", and reason is one sentence.

Set use_tot to true only when the question is a broad research or
decomposition task where committing to the first reasonable structure
could shape the whole result, such as "research industry X" or "how
should we structure research on Y". Then give exactly three candidate
research structures labelled A, B, and C. For each, write a one-line
approach and rate it strong, medium, or weak on:
- scope: how well it matches what the user asked;
- evidence: how likely public evidence is to exist for it;
- coverage: how much of the useful ground it covers.
Set selected to the label of the best candidate and reason to one
sentence on why it wins.
"""


@dataclasses.dataclass(frozen=True)
class Candidate:
    """One candidate research structure with its three ratings."""

    label: str
    approach: str
    scope: str
    evidence: str
    coverage: str


@dataclasses.dataclass(frozen=True)
class ResearchPlan:
    """The planning call's result.

    Attributes:
      use_tot: Whether alternatives were generated at all.
      candidates: The alternatives, empty when ``use_tot`` is false.
      selected: The label of the chosen candidate, or ``""``.
      reason: One sentence on the decision.
    """

    use_tot: bool
    candidates: list[Candidate]
    selected: str
    reason: str

    def chosen(self) -> Candidate | None:
        """Return the selected candidate, if any."""
        for candidate in self.candidates:
            if candidate.label == self.selected:
                return candidate
        return None


def parse_plan(data: dict[str, Any]) -> ResearchPlan:
    """Build a ``ResearchPlan`` from the structured output dictionary."""
    return ResearchPlan(
        use_tot=bool(data["use_tot"]),
        candidates=[Candidate(**item) for item in data["candidates"]],
        selected=data["selected"],
        reason=data["reason"],
    )


async def plan_research(question: str) -> ResearchPlan:
    """Run the one planning call and return its plan.

    Args:
      question: The user's question.

    Returns:
      The plan. For a simple question ``use_tot`` is false.

    Raises:
      RuntimeError: If the call fails or returns no structured output.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        # Structured output is delivered through an extra SDK turn, so a
        # cap of 1 can cut it off; 3 leaves room. Still one model call.
        max_turns=3,
        output_format={"type": "json_schema", "schema": PLAN_SCHEMA},
        setting_sources=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    result = None
    async for message in claude_agent_sdk.query(
        prompt=question, options=options
    ):
        if isinstance(message, claude_agent_sdk.ResultMessage):
            result = message
    if result is None or result.is_error or result.structured_output is None:
        errors = result.errors if result else "no result"
        raise RuntimeError(f"Planning failed: {errors}")
    return parse_plan(result.structured_output)
