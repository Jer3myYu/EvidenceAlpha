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
import types
import typing
from typing import Annotated, Any, TypedDict

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
    # Every evidence repair the verifier asked for, with what became of
    # it (plan revision 38 §4.45.4).
    repairs: dict[str, records.RepairRequest]
    # "open" while one repair pair is still earmarked, "used" once one
    # was admitted, "closed" once the run passed the point of asking
    # (plan revision 39 §4.46.3). Absent means open.
    repair_window: str
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
    # The frozen document that review judged, and the basis for
    # every retention decision at delivery.
    review_subject: records.ReviewSubject | None
    delivery: records.DeliveryResult | None
    # The best body validated so far. It stays authoritative until a
    # replacement has completed its own review and classified at least
    # as well.
    candidate: records.DeliveryCandidate | None
    assessment: records.LeadAssessment | None
    cycle: int
    follow_up_rounds: int
    review_rounds: int
    analysis_rounds: int
    draft_version: int
    final_review_version: int
    return_to: str
    last_signature: str
    route_log: Annotated[list[str], operator.add]


def record_types() -> dict[str, tuple[str, type | None]]:
    """The container kind and record class of every state key.

    ``("model", cls)`` for a single record, ``("optional", cls)`` when
    it may be ``None``, ``("dict", cls)`` for a registry, ``("list",
    cls)`` for a list of records, and ``(kind, None)`` for plain values.
    ``persist.validate_records`` uses it to reject a persisted field
    whose records came back as plain dictionaries.
    """
    return {
        key: container_of(hint)
        for key, hint in typing.get_type_hints(
            IndustryState, include_extras=True
        ).items()
    }


def container_of(hint: Any) -> tuple[str, type | None]:
    """The container kind and record class a type hint describes.

    ``("model", cls)`` for a single record, ``("optional", cls)`` when
    it may be ``None``, ``("dict", cls)`` for a registry, ``("list",
    cls)`` for a list of records, and ``(kind, None)`` when no record
    class is involved. ``persist.validate_records`` uses it on the
    state keys and, recursively, on the fields of a loaded record.
    """
    if typing.get_origin(hint) is Annotated:
        hint = typing.get_args(hint)[0]
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is types.UnionType or origin is typing.Union:
        inner = [a for a in args if a is not NoneType]
        model = inner[0] if inner and _is_record(inner[0]) else None
        if len(inner) == 1 and not _is_record(inner[0]):
            kind, model = container_of(inner[0])
            return ("optional" if kind in ("model", "plain") else kind, model)
        return ("optional", model)
    if origin is dict:
        return ("dict", args[1] if args and _is_record(args[1]) else None)
    if origin is list:
        return ("list", args[0] if args and _is_record(args[0]) else None)
    if _is_record(hint):
        return ("model", hint)
    return ("plain", None)


NoneType = type(None)


def _is_record(hint: Any) -> bool:
    return isinstance(hint, type) and issubclass(hint, records.Record)


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
