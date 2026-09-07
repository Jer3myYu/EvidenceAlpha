"""The checkpointed state of the industry research workflow.

Every key is owned by the node kind that writes it. Registries are
dictionaries replaced whole by ``merge``; the two ``Annotated`` lists
accumulate through LangGraph's reducer, so a concurrent worker returns
only its own items and a resumed superstep never appends twice (the
``merged`` list names the attempts already folded). Budget accounting
lives in ``attempts`` and ``single_calls`` only.
"""

import hashlib
import operator
from typing import Annotated, TypedDict

from industry import records

WORKFLOW_VERSION = "industry-v1"

# Nodes whose work is one model call through the CrewAI adapter; they
# are admitted against the ledger before calling and charged a
# conservative reservation when a resume finds them interrupted.
SINGLE_CALL_NODES = (
    "scope",
    "prepare_tasks",
    "assess_coverage",
    "analyze",
    "review",
    "write",
    "final_review",
)
# The calls the budget reserve is kept for.
RESERVED_NODES = ("write", "final_review")


class IndustryState(TypedDict, total=False):
    """Workflow state; see the module docstring for ownership."""

    question: str
    meta: records.RunMeta
    brief: records.Brief
    map: records.IndustryMap
    tasks: dict[str, records.Task]
    attempts: dict[str, records.Attempt]
    single_calls: dict[str, records.Attempt]
    phase: str
    task_results: Annotated[list[records.TaskResult], operator.add]
    merged: list[str]
    sources: dict[str, records.Source]
    source_versions: dict[str, records.SourceVersion]
    evidence: dict[str, records.Evidence]
    claims: dict[str, records.Claim]
    relationships: dict[str, records.Relationship]
    calculations: dict[str, records.Calculation]
    issues: dict[str, records.Issue]
    findings: dict[str, records.Finding]
    coverage: list[records.Coverage]
    sections: list[records.Section]
    review: records.ClaimReview | None
    final_review: records.DraftReview | None
    assessment: records.LeadAssessment | None
    cycle: int
    follow_up_rounds: int
    review_rounds: int
    analysis_rounds: int
    return_to: str
    last_signature: str
    route_log: Annotated[list[str], operator.add]


def registry_signature(state: IndustryState) -> str:
    """A digest of what remediation can change, for progress detection.

    Two states with the same signature hold the same evidence, the same
    claim versions, the same calculations, and the same set of open
    issues; a remediation cycle that leaves it unchanged made no
    progress.
    """
    parts = [
        ",".join(sorted(state.get("evidence", {}))),
        ",".join(
            f"{claim.id}:{claim.version}:{claim.review}"
            for claim in sorted(
                state.get("claims", {}).values(), key=lambda c: c.id
            )
        ),
        ",".join(sorted(state.get("calculations", {}))),
        ",".join(
            sorted(
                issue.id
                for issue in state.get("issues", {}).values()
                if issue.status == "open"
            )
        ),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
