"""Typed records of the industry research workflow.

Every class that can appear in a checkpoint is defined here and listed
in ``PERSISTED``; ``research.persist`` builds the serializer allowlist
from that tuple, so a record that is not listed cannot be saved by
mistake. Ids are assigned by Python (``industry.merge``), never by a
model. Confidence is expressed by review states, evidence kinds, and
limitations, never by a number.

Two families of records exist side by side:

- registry records with canonical ids (``S#`` source, ``E#`` evidence,
  ``C#`` claim, ``R#`` relationship, ``G#``/``L#``/``P#`` map items,
  ``T#`` task, ``T#.n`` attempt, ``I#`` issue, ``K#`` calculation,
  ``F#`` finding);
- worker output (``TaskResult`` and the drafts inside it), which uses
  attempt-local labels (``E1``...) that the merge canonicalises.
"""

import datetime
from typing import Literal

import pydantic

SCHEMA_VERSION = 1

Stage = Literal["upstream", "midstream", "downstream", "adjacent"]
ParticipantRole = Literal[
    "supplier", "manufacturer", "customer", "equipment", "service", "other"
]
SourceKind = Literal["web_search", "web_page", "pdf", "local_document"]
SourceOrigin = Literal["primary", "secondary", "unknown"]
EvidenceKind = Literal["snippet", "passage", "table"]
Extraction = Literal["search_snippet", "html_text", "pdf_text", "local_text"]
ClaimKind = Literal[
    "fact", "company_claim", "inference", "forecast", "derived", "map"
]
Review = Literal[
    "unreviewed", "supported", "qualified", "unsupported", "contradicted"
]
Relation = Literal[
    "supplies", "customer_of", "competes_with", "generic_dependency"
]
RelationshipReview = Literal["unreviewed", "supported", "unsupported"]
TaskKind = Literal["map", "research", "follow_up", "acquisition"]
TaskRole = Literal["industry", "company", "verifier"]
TaskStatus = Literal["pending", "ready", "running", "done", "failed", "skipped"]
AttemptStatus = Literal["running", "done", "failed", "unknown"]
ResultStatus = Literal["done", "failed", "unknown"]
IssueCategory = Literal[
    "missing_evidence",
    "contradiction",
    "weak_inference",
    "wording",
    "unsupported",
    "unavailable",
]
Severity = Literal["material", "minor"]
RequestedAction = Literal["research", "acquire", "analyze", "edit", "remove"]
IssueStatus = Literal["open", "resolved", "unresolvable"]
CalcKind = Literal["ratio", "share", "growth"]
CalcStatus = Literal["ok", "error"]
FindingStatus = Literal["current", "stale"]
CoverageStatus = Literal["covered", "partial", "uncovered"]
Mode = Literal["navigation", "brief", "deep_dive"]
Milestone = Literal[
    "rd",
    "sample_delivery",
    "customer_qualification",
    "small_batch",
    "stable_production",
    "material_revenue",
]
ExecutionStatus = Literal["running", "interrupted", "completed", "failed"]
ReportStatus = Literal["complete", "complete_with_limitations", "incomplete"]
Verdict = Literal["supported", "qualified", "unsupported", "contradicted"]
# Sub-topics that coverage counts; question 4 needs its first four.
Topic = Literal[
    "product",
    "payer_flow",
    "demand_driver",
    "cost_differentiation",
    "bargaining_power",
    "barrier",
    "commercialization",
    "global_china",
    "comparison",
    "boundary",
    "other",
]
QUESTION_4_TOPICS = (
    "payer_flow",
    "demand_driver",
    "cost_differentiation",
    "bargaining_power",
)

# The eight learning questions of the brief, by number.
REQUIRED_QUESTIONS = {
    1: "What is the product or service, why is it needed, and what belongs "
    "inside or outside this industry?",
    2: "How do upstream, midstream, downstream, and relevant adjacent "
    "activities connect?",
    3: "Which representative companies participate, what do they supply or "
    "buy, and which relationships are documented?",
    4: "Who pays whom, what drives demand, and where do costs, "
    "differentiation, and bargaining power arise?",
    5: "What barriers protect existing suppliers, and how are technical "
    "capabilities commercialized?",
    6: "How do global leaders and Chinese participants differ in capability "
    "and commercial progress?",
    7: "How do representative companies compare on business-relevant, "
    "consistent dimensions?",
    8: "What conclusions are supported, what could invalidate them, and "
    "what should the reader monitor next?",
}
CENTRAL_QUESTIONS = (1, 2, 3, 4, 5)


def now_iso() -> str:
    """The current UTC time as an ISO 8601 string with seconds."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


class Record(pydantic.BaseModel):
    """Base of every record: unknown fields are an error, not ignored."""

    model_config = pydantic.ConfigDict(extra="forbid")


class Quantity(Record):
    """A number as a claim states it, kept only if the excerpt contains it.

    Attributes:
      value: The numeric value.
      unit: The unit as written, for example ``亿元``, ``%``, ``USD bn``.
      period: The period as written, for example ``2024``, ``2024H1``.
      scope: Geography or definition, for example ``全球``.
      as_written: The number string as it appears in the excerpt.
    """

    value: float
    unit: str
    period: str | None = None
    scope: str | None = None
    as_written: str


class Source(Record):
    """One underlying publication, identified by canonical URL or path."""

    id: str
    canonical_url: str | None = None
    path: str | None = None
    title: str
    publisher: str | None = None
    published: str | None = None
    kind: SourceKind
    origin: SourceOrigin = "unknown"
    syndicated_of: str | None = None
    versions: list[str] = pydantic.Field(default_factory=list)


class SourceVersion(Record):
    """One fetch of a source: immutable bytes and immutable metadata."""

    id: str
    source_id: str
    content_hash: str
    blob_path: str
    meta_path: str
    final_url: str
    content_type: str
    size: int
    retrieved_at: str
    extraction_version: str
    chunk_count: int = 0


class Evidence(Record):
    """A verbatim excerpt with its locator and extraction limitations."""

    id: str
    source_id: str
    source_version_id: str | None = None
    excerpt: str
    locator: str
    kind: EvidenceKind
    entity: str | None = None
    period: str | None = None
    unit: str | None = None
    scope: str | None = None
    extraction: Extraction
    limitations: list[str] = pydantic.Field(default_factory=list)
    task_id: str
    retrieved_at: str

    @pydantic.model_validator(mode="after")
    def _passages_need_a_version(self) -> "Evidence":
        if self.kind in ("passage", "table") and not self.source_version_id:
            raise ValueError(
                f"{self.kind} evidence needs a source_version_id; only "
                "search snippets have none"
            )
        return self


class Claim(Record):
    """A statement with its evidence, kind, materiality, and review state."""

    id: str
    statement: str
    kind: ClaimKind
    evidence_ids: list[str] = pydantic.Field(default_factory=list)
    calculation_id: str | None = None
    material: bool = False
    review: Review = "unreviewed"
    version: int = 1
    supersedes: str | None = None
    entity: str | None = None
    period: str | None = None
    quantity: Quantity | None = None
    milestone: Milestone | None = None
    milestone_date: str | None = None
    limitations: list[str] = pydantic.Field(default_factory=list)
    questions: list[int] = pydantic.Field(default_factory=list)
    topics: list[Topic] = pydantic.Field(default_factory=list)
    reviewed_topics: list[Topic] = pydantic.Field(default_factory=list)
    dimension: str | None = None
    origin: str = ""
    map_ref: str | None = None


class Relationship(Record):
    """A named relation; ``confirmed`` only after a verifier judgement."""

    id: str
    from_entity: str
    to_entity: str
    relation: Relation
    confirmed: bool = False
    evidence_ids: list[str] = pydantic.Field(default_factory=list)
    date: str | None = None
    claim_id: str
    review: RelationshipReview = "unreviewed"


class Segment(Record):
    """One stage of the value chain, backed by a map claim."""

    id: str
    name: str
    stage: Stage
    description: str
    claim_id: str


class Link(Record):
    """What flows from one segment to another, backed by a map claim."""

    id: str
    from_segment: str
    to_segment: str
    what_flows: str
    claim_id: str


class Participant(Record):
    """A company placed in a segment with a role, backed by a map claim.

    ``supplies`` and ``buys`` name the particular products or services
    the company sells into or purchases from the chain; a participant
    with neither is a categorised name, not an evidenced link, and
    coverage treats it as such.
    """

    id: str
    name: str
    segment_id: str
    role: ParticipantRole
    supplies: str | None = None
    buys: str | None = None
    listed: bool | None = None
    region: str | None = None
    selection_rationale: str
    claim_id: str


class IndustryMap(Record):
    """Segments, links, and participants; every item has a map claim."""

    segments: list[Segment] = pydantic.Field(default_factory=list)
    links: list[Link] = pydantic.Field(default_factory=list)
    participants: list[Participant] = pydantic.Field(default_factory=list)
    boundary_note: str = ""
    gaps: list[str] = pydantic.Field(default_factory=list)
    version: int = 0


class Task(Record):
    """A bounded unit of research work with dependencies and acceptance."""

    id: str
    kind: TaskKind
    role: TaskRole
    objective: str
    scope: str = ""
    depends_on: list[str] = pydantic.Field(default_factory=list)
    references: list[str] = pydantic.Field(default_factory=list)
    required_fields: list[str] = pydantic.Field(default_factory=list)
    acceptance: str = ""
    status: TaskStatus = "pending"
    attempts: int = 0
    issue_id: str | None = None
    skip_reason: str | None = None


class Usage(Record):
    """What one execution consumed, or a conservative unknown."""

    turns: int = 0
    tool_calls: int = 0
    denied_tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    web_searches: int = 0
    fetches: int = 0
    duration_s: float = 0.0
    unknown: bool = False
    node: str | None = None

    def __add__(self, other: "Usage") -> "Usage":
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            turns=self.turns + other.turns,
            tool_calls=self.tool_calls + other.tool_calls,
            denied_tool_calls=self.denied_tool_calls + other.denied_tool_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=cost,
            web_searches=self.web_searches + other.web_searches,
            fetches=self.fetches + other.fetches,
            duration_s=self.duration_s + other.duration_s,
            unknown=self.unknown or other.unknown,
        )


class Reservation(Record):
    """The allowance an attempt is charged until its usage is observed."""

    turns: int
    tool_calls: int
    seconds: float


class Attempt(Record):
    """One execution of a task: reserved before it starts, then observed."""

    id: str
    task_id: str
    status: AttemptStatus = "running"
    reserved: Reservation
    observed: Usage | None = None
    started_at: str
    duration_s: float | None = None


class RelationshipDraft(Record):
    """A relation a researcher proposes; never confirmed by itself."""

    from_entity: str
    to_entity: str
    relation: Relation
    date: str | None = None
    evidence_refs: list[str] = pydantic.Field(default_factory=list)


class FindingDraft(Record):
    """One researcher finding, citing attempt-local evidence labels."""

    statement: str
    kind: ClaimKind = "fact"
    evidence_refs: list[str] = pydantic.Field(default_factory=list)
    entity: str | None = None
    period: str | None = None
    quantity: Quantity | None = None
    material: bool = False
    milestone: Milestone | None = None
    milestone_date: str | None = None
    relationships: list[RelationshipDraft] = pydantic.Field(
        default_factory=list
    )
    questions: list[int] = pydantic.Field(default_factory=list)
    topics: list[Topic] = pydantic.Field(default_factory=list)
    dimension: str | None = None


class SegmentDraft(Record):
    """A segment as the map researcher describes it."""

    key: str
    name: str
    stage: Stage
    description: str
    evidence_refs: list[str] = pydantic.Field(default_factory=list)


class LinkDraft(Record):
    """A link between two segment keys."""

    from_key: str
    to_key: str
    what_flows: str
    evidence_refs: list[str] = pydantic.Field(default_factory=list)


class ParticipantDraft(Record):
    """A participant placed in a segment key, with what it supplies or buys."""

    name: str
    segment_key: str
    role: ParticipantRole
    supplies: str | None = None
    buys: str | None = None
    listed: bool | None = None
    region: str | None = None
    selection_rationale: str = ""
    evidence_refs: list[str] = pydantic.Field(default_factory=list)


class MapDraft(Record):
    """The map task's structured output."""

    segments: list[SegmentDraft] = pydantic.Field(default_factory=list)
    links: list[LinkDraft] = pydantic.Field(default_factory=list)
    participants: list[ParticipantDraft] = pydantic.Field(default_factory=list)
    boundary_note: str = ""
    gaps: list[str] = pydantic.Field(default_factory=list)


class TaskResult(Record):
    """What one attempt returned; the merge folds it into the registry."""

    attempt_id: str
    task_id: str
    status: ResultStatus
    sources: list[Source] = pydantic.Field(default_factory=list)
    source_versions: list[SourceVersion] = pydantic.Field(default_factory=list)
    evidence: list[Evidence] = pydantic.Field(default_factory=list)
    findings: list[FindingDraft] = pydantic.Field(default_factory=list)
    map: MapDraft | None = None
    gaps: list[str] = pydantic.Field(default_factory=list)
    usage: Usage = pydantic.Field(default_factory=Usage)
    error: str | None = None


class Brief(Record):
    """The Lead's typed research brief; defaults are set in Python."""

    industry: str
    audience: str = (
        "an investor who knows basic investing but not this industry"
    )
    language: str = "zh"
    mode: Mode = "brief"
    boundary_in: list[str] = pydantic.Field(default_factory=list)
    boundary_out: list[str] = pydantic.Field(default_factory=list)
    boundary_alternatives: list[str] = pydantic.Field(default_factory=list)
    geography: str = "global structure with a China comparison"
    cutoff: str = ""
    required_questions: list[str] = pydantic.Field(default_factory=list)
    evidence_expectations: str = ""
    constraints: list[str] = pydantic.Field(default_factory=list)
    budget_policy: str = ""


class Reference(Record):
    """Evidence handed to a worker, with the source identity it needs.

    The worker copies it into its collector under the same source
    identity (URL or path), so the merge maps it back to the canonical
    source and evidence instead of registering a duplicate.
    """

    evidence: Evidence
    source_title: str
    source_url: str | None = None
    source_path: str | None = None
    source_kind: SourceKind = "web_page"
    version_date: str | None = None


class WorkerInput(Record):
    """The complete ``Send`` payload of one attempt; workers read no state."""

    thread_id: str
    attempt: Attempt
    task: Task
    brief: Brief
    language: str
    references: list[Reference] = pydantic.Field(default_factory=list)
    open_issue: str | None = None
    allowance: Reservation
    model: str
    prompt_version: str


class Issue(Record):
    """A problem with a canonical key so repeats do not reset attempts."""

    id: str
    key: str
    category: IssueCategory
    severity: Severity
    target: str
    description: str = ""
    requested_action: RequestedAction
    attempts: int = 0
    evidence_added: bool = False
    next_step: str | None = None
    status: IssueStatus = "open"
    resolution: str | None = None


class CalcInput(Record):
    """One input of a calculation, copied from a claim's quantity."""

    claim_id: str
    value: float
    unit: str
    period: str | None = None
    scope: str | None = None


class CalcRequest(Record):
    """The analyst's request for one deterministic calculation."""

    kind: CalcKind
    label: str
    numerator_claim_id: str | None = None
    denominator_claim_id: str | None = None
    start_claim_id: str | None = None
    end_claim_id: str | None = None
    alignment_note: str | None = None


class Calculation(Record):
    """A computed value with its inputs, formula, and status."""

    id: str
    kind: CalcKind
    label: str
    inputs: list[CalcInput]
    formula: str
    result: float | None = None
    unit: str | None = None
    status: CalcStatus
    message: str | None = None
    alignment_note: str | None = None


class Finding(Record):
    """An analytical conclusion with mechanism and observable test."""

    id: str
    conclusion: str
    claim_ids: list[str]
    mechanism: str
    implication: str
    counterargument: str
    uncertainty: str
    monitor: str
    material: bool = False
    questions: list[int] = pydantic.Field(default_factory=list)
    entity: str | None = None
    status: FindingStatus = "current"


class Coverage(Record):
    """Derived coverage of one required question, with the Lead's view."""

    question: int
    status: CoverageStatus
    claim_ids: list[str] = pydantic.Field(default_factory=list)
    finding_ids: list[str] = pydantic.Field(default_factory=list)
    relationship_ids: list[str] = pydantic.Field(default_factory=list)
    note: str = ""
    lead_status: CoverageStatus | None = None


class Section(Record):
    """One report section citing claims by ``[C#]``."""

    id: str
    title: str
    text: str
    claim_ids: list[str] = pydantic.Field(default_factory=list)
    review_version: int = 0
    stale: bool = False


class ClaimVerdict(Record):
    """The verifier's judgement of one claim against its evidence.

    ``topics_supported`` names the tagged topics the excerpt actually
    bears on; coverage counts a topic only when the verifier confirmed
    it, so one claim cannot cover four economics topics by tagging.
    """

    claim_id: str
    verdict: Verdict
    reason: str
    topics_supported: list[Topic] = pydantic.Field(default_factory=list)


class RelationshipVerdict(Record):
    """The verifier's judgement of one proposed relationship."""

    relationship_id: str
    supported: bool
    reason: str


class SourceOriginJudgement(Record):
    """Whether a source is primary or secondary, by its content."""

    source_id: str
    origin: SourceOrigin
    reason: str


class AcquisitionRequest(Record):
    """The verifier's request to inspect an original source."""

    objective: str
    claim_id: str | None = None
    url: str | None = None


class ClaimReview(Record):
    """The pre-draft review's structured result."""

    claims: list[ClaimVerdict] = pydantic.Field(default_factory=list)
    relationships: list[RelationshipVerdict] = pydantic.Field(
        default_factory=list
    )
    sources: list[SourceOriginJudgement] = pydantic.Field(default_factory=list)
    acquisitions: list[AcquisitionRequest] = pydantic.Field(
        default_factory=list
    )
    contradictions: list[str] = pydantic.Field(default_factory=list)


class SectionIssue(Record):
    """A problem the final review found in one section."""

    section_id: str
    category: IssueCategory
    severity: Severity
    description: str
    claim_id: str | None = None


class DraftReview(Record):
    """The final review's structured result on the exact draft."""

    issues: list[SectionIssue] = pydantic.Field(default_factory=list)
    consistent: bool = True
    summary: str = ""


class CoverageProposal(Record):
    """The Lead's proposed coverage of one question."""

    question: int
    status: CoverageStatus
    claim_ids: list[str] = pydantic.Field(default_factory=list)
    finding_ids: list[str] = pydantic.Field(default_factory=list)
    relationship_ids: list[str] = pydantic.Field(default_factory=list)
    note: str = ""


class LeadAssessment(Record):
    """The Lead's coverage proposal and beginner-usefulness judgement."""

    coverage: list[CoverageProposal] = pydantic.Field(default_factory=list)
    beginner_usefulness: str = ""
    missing: list[str] = pydantic.Field(default_factory=list)


class Limits(Record):
    """The configurable safety limits of one run."""

    wall_clock_s: float = 5400.0
    time_reserve_s: float = 900.0
    task_executions: int = 12
    model_calls: int = 200
    model_call_reserve: int = 12
    tool_calls: int = 150
    remediation_cycles: int = 3
    issue_follow_ups: int = 2
    follow_up_rounds: int = 2
    max_turns: int = 12
    tools_per_attempt: int = 24
    concurrency: int = 2
    task_timeout_s: float = 1200.0
    single_call_timeout_s: float = 480.0
    single_call_turns: int = 5
    expected_task_s: float = 600.0
    task_attempts: int = 2


class RunMeta(Record):
    """Versions, models, limits, and statuses of one thread."""

    workflow_version: str
    schema_version: int = SCHEMA_VERSION
    prompt_version: str
    models: dict[str, str]
    limits: Limits
    started_at: str
    execution_status: ExecutionStatus = "running"
    report_status: ReportStatus | None = None
    report_path: str | None = None


# Every class that can appear in a checkpoint; the serializer allowlist.
PERSISTED: tuple[type[Record], ...] = (
    Quantity,
    Source,
    SourceVersion,
    Evidence,
    Claim,
    Relationship,
    Segment,
    Link,
    Participant,
    IndustryMap,
    Task,
    Usage,
    Reservation,
    Attempt,
    RelationshipDraft,
    FindingDraft,
    SegmentDraft,
    LinkDraft,
    ParticipantDraft,
    MapDraft,
    TaskResult,
    Brief,
    Reference,
    WorkerInput,
    Issue,
    CalcInput,
    CalcRequest,
    Calculation,
    Finding,
    Coverage,
    Section,
    ClaimVerdict,
    RelationshipVerdict,
    SourceOriginJudgement,
    AcquisitionRequest,
    ClaimReview,
    SectionIssue,
    DraftReview,
    CoverageProposal,
    LeadAssessment,
    Limits,
    RunMeta,
)
