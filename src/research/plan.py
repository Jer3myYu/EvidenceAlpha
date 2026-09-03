"""Lightweight Tree-of-Thought planning: one structured Claude call.

Before the research agent runs, one call decides whether the question
has several plausible research structures. If it does, the call returns
three candidate approaches rated on three criteria and picks one; the
agent then follows the chosen approach. If it does not, the plan says so
and the agent runs unchanged. Depth is one, candidates three, survivor
one. This is a visible planning artifact, not hidden reasoning.

``PlanOutput`` is the wire shape of the call; ``ResearchPlan`` and
``Candidate`` are the dataclasses kept in workflow state.
"""

import dataclasses
from typing import Any, Literal

import claude_agent_sdk
import pydantic

MODEL = "claude-sonnet-5"

Rating = Literal["strong", "medium", "weak"]


class CandidateOutput(pydantic.BaseModel):
    """One candidate as the planning call returns it on the wire."""

    # Candidate(**item) accepts exactly these keys; an extra one from
    # the model (seen: "approach_detail") crashed it before extras were
    # forbidden.
    model_config = pydantic.ConfigDict(extra="forbid")

    label: str
    approach: str
    scope: Rating
    evidence: Rating
    coverage: Rating


class PlanOutput(pydantic.BaseModel):
    """The planning call's structured output on the wire.

    ``parse_plan`` turns its dictionary form into the ``ResearchPlan``
    dataclass that lives in workflow state.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    use_tot: bool
    candidates: list[CandidateOutput]
    selected: str
    reason: str


# The JSON schema the planning call requests, derived from the model.
PLAN_SCHEMA = PlanOutput.model_json_schema()

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
        # Structured output is delivered through an extra SDK turn, and
        # the model sometimes needs a second attempt at it (a cap of 3
        # was exhausted in 2 of 8 evaluator trials); 5 leaves room.
        # Still one model call.
        max_turns=5,
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
