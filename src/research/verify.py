"""Independent verification of the synthesised answer.

The synthesis writes the final answer; nothing in Phases 1-7 reads it
afterwards. This module checks it, in two layers that never mix:

- deterministic Python for what must not depend on prose: every
  citation in the answer must be an ``[S#]`` that exists in the source
  registry (``check_citations``);
- one structured model call, independent of the synthesis, for the
  judgements: claim support, conflicting evidence, source quality
  (``verify_answer``). It sees the question, the answer, the
  observations, and the source list; never the plan, the round answers,
  or the synthesis prompt.

``list_issues`` turns both layers into the problems that matter, and
``format_verification_notes`` discloses them at the end of the answer.
The workflow (``research.workflow``) decides what else to do with them.
"""

import re
from typing import Literal

import claude_agent_sdk
import pydantic

from research import agent
from research import sources as sources_module

# A citation is one or more labels inside one pair of brackets, as the
# synthesis writes them: [S1], [S1, S2]; [S1][S2] is two citations.
# Any other bracketed text is prose and is left alone.
_CITATION = re.compile(r"\[([SDW]\d+(?:\s*,\s*[SDW]\d+)*)\]")


def cited_labels(answer: str) -> list[str]:
    """Return every citation label in the answer, in order, repeats kept."""
    labels: list[str] = []
    for match in _CITATION.finditer(answer):
        labels.extend(part.strip() for part in match[1].split(","))
    return labels


def check_citations(
    answer: str, sources: dict[str, sources_module.SourceRecord]
) -> list[str]:
    """Return one sentence per invalid citation in the answer.

    A valid citation is an ``[S#]`` present in the registry. ``[D#]``
    and ``[W#]`` are the tools' round-local labels and never valid in a
    final answer; an unknown ``[S#]`` cites nothing.

    Args:
      answer: The synthesised answer text.
      sources: The graph-level source registry.

    Returns:
      The issues, one per distinct invalid label in first-seen order;
      empty when every citation is valid or there are none.
    """
    issues: list[str] = []
    for label in dict.fromkeys(cited_labels(answer)):
        if label[0] in "DW":
            issues.append(f"[{label}] is a round-local label, not a source.")
        elif label not in sources:
            issues.append(f"[{label}] is not a known source.")
    return issues


MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""\
You independently verify a written research answer against the evidence
it was written from. You did not write the answer. You do not research,
search, call tools, add facts, or rewrite the answer.

The tool observations are the only evidence. Each carries a source label
such as [S2], and the source list says what each label is. The answer
cites those labels. Check three things and return only the structured
result.

claims: every factual claim the answer makes, in order. For each, quote
or closely paraphrase the claim, list the labels the answer cites for it
(empty when it cites none), and judge it against the observations:
- supported: the cited observations state it, at the scope the claim
  has. A claim with no citation is supported only when it merely
  summarises claims that are themselves cited and supported.
- unsupported: no observation states it, or the cited observations are
  about something else or say less than the claim does.
- contradicted: an observation states the opposite or an incompatible
  value.
reason is one sentence naming the observation that decides it. The
fixed sentence "{agent.EVIDENCE_GAP}" is not a claim. A statement that some
evidence is missing is a claim about the observations, and it is
supported when they indeed lack that evidence.

conflicts: places where two or more observations genuinely disagree on
a point one of the answer's claims relies on, so that both cannot be
true. An answer with no claims has no conflicts. Not conflicts: figures
for different dates or periods that can both hold, differences of scope
or definition, or one source being more detailed than another; never
fold such a difference into a conflict's description. For each conflict
give the labels, one sentence stating the disagreement, and whether the
answer discloses it (disclosed_in_answer). Do not resolve a conflict
yourself.

source_ratings: one per source the answer cites. primary: the company
itself, a regulatory filing, a government, standards, or court body.
secondary: an established news organisation, an analyst or research
firm, a reference work. weak: a blog, forum, aggregator, content farm,
marketing page, or unknown origin. Judge from the title, URL, and text;
when unsure, say weak and explain. A rating never changes a verdict.
"""


class ClaimCheck(pydantic.BaseModel):
    """One claim from the answer and whether the evidence supports it."""

    model_config = pydantic.ConfigDict(extra="forbid")

    claim: str
    cited_sources: list[str]
    verdict: Literal["supported", "unsupported", "contradicted"]
    reason: str


class Conflict(pydantic.BaseModel):
    """Observations that disagree on a point the answer relies on."""

    model_config = pydantic.ConfigDict(extra="forbid")

    sources: list[str]
    description: str
    disclosed_in_answer: bool


class SourceRating(pydantic.BaseModel):
    """The verifier's quality assessment of one cited source."""

    model_config = pydantic.ConfigDict(extra="forbid")

    source_id: str
    quality: Literal["primary", "secondary", "weak"]
    reason: str


class Verification(pydantic.BaseModel):
    """The verifier's structured result; report only, never evidence."""

    model_config = pydantic.ConfigDict(extra="forbid")

    claims: list[ClaimCheck]
    conflicts: list[Conflict]
    source_ratings: list[SourceRating]


def format_sources(sources: dict[str, sources_module.SourceRecord]) -> str:
    """Render the registry as one line per source, or a fixed sentence."""
    lines = []
    for record in sources.values():
        location = record.canonical_url or f"{record.local_document_id} (local)"
        seen_via = ", ".join(record.seen_via)
        lines.append(
            f"[{record.source_id}] {record.title} - {location}; via {seen_via}"
        )
    return "\n".join(lines) or "none: no source seen"


def build_prompt(
    question: str,
    answer: str,
    evidence: list[str],
    sources: dict[str, sources_module.SourceRecord],
) -> str:
    """Lay out question, answer, source list, and observations as one message.

    The plan and the round answers are deliberately absent: the verifier
    judges the answer against the evidence alone.

    Args:
      question: The user's question.
      answer: The synthesised answer, verbatim.
      evidence: Every observation, ``[S#]`` labelled, in order.
      sources: The graph-level source registry.

    Returns:
      The prompt text, exactly as it will be sent.
    """
    return (
        f"Question:\n{question}\n\n"
        f"Answer to verify:\n{answer}\n\n"
        f"Sources:\n{format_sources(sources)}\n\n"
        f"Tool observations (evidence):\n{agent.format_observations(evidence)}"
    )


async def verify_answer(
    question: str,
    answer: str,
    evidence: list[str],
    sources: dict[str, sources_module.SourceRecord],
) -> Verification:
    """Run the verification call and return its validated result.

    Args:
      question: The user's question.
      answer: The synthesised answer.
      evidence: Every observation, ``[S#]`` labelled.
      sources: The graph-level source registry.

    Returns:
      The verification.

    Raises:
      RuntimeError: If the call fails or returns no structured output.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        max_turns=5,  # Structured output may need a second attempt.
        output_format={
            "type": "json_schema",
            "schema": Verification.model_json_schema(),
        },
        setting_sources=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    prompt = build_prompt(question, answer, evidence, sources)
    result = None
    async for message in claude_agent_sdk.query(prompt=prompt, options=options):
        if isinstance(message, claude_agent_sdk.ResultMessage):
            result = message
    if result is None or result.is_error or result.structured_output is None:
        errors = result.errors if result else "no result"
        raise RuntimeError(f"Verification failed: {errors}")
    return Verification.model_validate(result.structured_output)


def list_issues(
    citation_issues: list[str], verification: Verification
) -> list[str]:
    """Return the problems that make the answer unfit as it stands.

    Invalid citations first, then each unsupported or contradicted claim,
    then each conflict the answer does not disclose. An answer that makes
    no claims (the evidence-gap sentence) has nothing to disclose, so its
    conflicts are not problems. Source ratings are never problems.

    Args:
      citation_issues: From ``check_citations``.
      verification: The verifier's result.

    Returns:
      One sentence per problem, wording kept; empty for a clean answer.
    """
    issues = list(citation_issues)
    for check in verification.claims:
        if check.verdict != "supported":
            issues.append(
                f"{check.verdict.capitalize()} claim: "
                f'"{check.claim}" {check.reason}'
            )
    for conflict in verification.conflicts:
        if verification.claims and not conflict.disclosed_in_answer:
            labels = ", ".join(f"[{label}]" for label in conflict.sources)
            issues.append(
                f"Conflicting evidence not disclosed ({labels}): "
                f"{conflict.description}"
            )
    return issues


def format_verification_notes(
    citation_issues: list[str], verification: Verification
) -> str:
    """Render the remaining problems as a numbered block for the answer.

    Like ``workflow.format_unresolved_gaps``: the wording is
    ``list_issues``'s, the only changes are numbering and whitespace.

    Args:
      citation_issues: From ``check_citations``.
      verification: The verifier's result.

    Returns:
      The block under a fixed heading, or an empty string when the
      answer is clean.
    """
    issues = list_issues(citation_issues, verification)
    if not issues:
        return ""
    normalised = (" ".join(issue.split()) for issue in issues)
    lines = "\n".join(
        f"{number}. {issue}" for number, issue in enumerate(normalised, start=1)
    )
    return f"Verification notes:\n{lines}"
