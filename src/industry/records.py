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
from typing import Any, Literal

import pydantic

# 2: the economics topics cost_structure and differentiation replaced
# cost_differentiation, which stays accepted as a legacy alias counting
# toward cost_structure only.
# 3: a quantity is admitted only after its scale is checked against the
# excerpt it was read from, so a claim written under schema 2 may carry
# a quantity whose scale was never validated; such a thread is replayed
# read-only and refused for resume (``persist.load_industry_state``).
# 4: a Calculation records the request that produced it, so one stopped
# by a changed input is recomputed instead of re-approved; a claim
# derived under schema 3 carries no such request.
# 5: a Calculation is versioned and a derived Claim records the version
# it reports, so a claim is citable only while it still agrees with its
# producer; and a quantity's unit must carry its own scale, which a
# quantity admitted under schema 4 was not required to do.
# 6: a quantity is an admitted structure (``UnitExpr``) bound to one
# evidence occurrence (``EvidenceBinding``) established by
# ``industry.quantities``; a schema-5 quantity carries a free-text unit
# and no binding, and its supported flag is not proof under this
# schema, so no schema-5 thread is migrated. Extraction v3 packs prose
# at certified boundaries and carries table layouts on evidence. Schema
# 7 adds the delivery contract: a claim's standalone approval, a frozen
# ``ReviewSubject`` and the ``DeliveryResult``. A schema-6 thread has no
# certificate and must never be given one, so it is not resumable
# either; it replays read-only like every earlier schema. Schema 8 adds
# the producer behind a derived calculation input, so two operands can
# be told apart by where their figures came from; a schema-7 thread can
# hold a calculation that divided a figure by itself and is refused for
# resume like the rest.
# Schema 9 adds the reservation pair and the retained delivery
# candidate: a schema-8 thread can hold a body whose review was never
# affordable, and carries no candidate to fall back to.
# 10: an acquisition task names the record it repairs
# (``Task.target``), its result carries typed attachments, and every
# repair request is kept with its disposition (``state["repairs"]``). A
# schema-9 thread's acquisitions created unrelated duplicate claims
# instead of strengthening their targets; nothing infers a target,
# attachment or disposition for it, so it replays read-only and is
# refused for resume like every earlier schema.
SCHEMA_VERSION = 10

STAGES = ("upstream", "midstream", "downstream", "adjacent")
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
# What a researcher may report: never ``derived`` (a calculation's own
# claim) and never ``map`` (made from the map draft by the merge).
DraftClaimKind = Literal["fact", "company_claim", "inference", "forecast"]
UnitKind = Literal["atom", "scale10", "multiply", "divide", "power"]
SCALE_EXPONENTS = (3, 4, 6, 8, 9, 12)
POWER_EXPONENTS = (2, 3)
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
# An issue that still describes a real problem: open, or retired at the
# follow-up limit without being answered. Delivery protections (redaction,
# report status) apply to both; only ``resolved`` issues stop counting.
UNRESOLVED_ISSUE_STATUSES = ("open", "unresolvable")
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
    "cost_structure",
    "differentiation",
    "cost_differentiation",  # legacy value of threads before 2026-09-07
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
    "cost_structure",
    "differentiation",
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

    @classmethod
    def model_construct(cls, _fields_set=None, **values: Any) -> "Record":
        """Refuse to build a record without validating it.

        The checkpoint serializer rebuilds a model that fails
        validation by calling ``model_construct``, which skips
        validation and, under ``extra="forbid"``, silently drops the
        fields it does not know -- so a record written by another
        schema would come back stripped and be indistinguishable from a
        valid one. Raising here makes the serializer hand back the raw
        payload it read instead, which ``persist.validate_records``
        then refuses by type, before anything is lost.
        """
        raise TypeError(
            f"{cls.__name__} may not be constructed without validation; "
            "the persisted record does not match the current schema"
        )


class UnitExpr(Record):
    """A unit as a small tree; equality is structural, never textual.

    One tagged record instead of five classes, so every nested field is
    ``UnitExpr | None`` and the checkpoint validator walks it unchanged.
    ``atom`` names a canonical lexicon identifier (``quantities.ATOMS``);
    ``scale10`` is a decimal exponent over ``left``; ``power`` raises
    ``left`` to ``exponent``; ``multiply`` and ``divide`` combine
    ``left`` and ``right``. Text is generated by ``quantities.render``
    and never stored: ``USD/(kg/day)`` and ``(USD/kg)/day`` are two
    different trees.
    """

    # A value record: immutable, so a snapshot or a projection that
    # holds it can never be changed under the reader that compares it.
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    kind: UnitKind
    atom: str | None = None
    exponent: int | None = None
    left: "UnitExpr | None" = None
    right: "UnitExpr | None" = None

    @pydantic.model_validator(mode="after")
    def _shape_of_its_kind(self) -> "UnitExpr":
        # The lexicon belongs to the grammar module; importing it here
        # would be circular at module load, so it is looked up lazily.
        from industry import (  # pylint: disable=import-outside-toplevel
            quantities,
        )

        if self.kind == "atom":
            if self.atom not in quantities.ATOMS:
                raise ValueError(f"unknown unit atom {self.atom!r}")
            if self.exponent is not None or self.left or self.right:
                raise ValueError("an atom carries nothing else")
        elif self.kind == "scale10":
            if self.exponent not in SCALE_EXPONENTS or self.left is None:
                raise ValueError("scale10 needs a supported exponent, left")
            if self.atom is not None or self.right is not None:
                raise ValueError("scale10 carries only exponent and left")
            if self.left.kind == "scale10":
                raise ValueError("a scale over a scale is not a unit")
        elif self.kind == "power":
            if self.exponent not in POWER_EXPONENTS or self.left is None:
                raise ValueError("power needs exponent 2 or 3 and left")
            if self.atom is not None or self.right is not None:
                raise ValueError("power carries only exponent and left")
            if self.left.kind in ("power", "scale10"):
                raise ValueError("a power applies to an atom or a group")
        else:
            if self.left is None or self.right is None:
                raise ValueError(f"{self.kind} needs left and right")
            if self.atom is not None or self.exponent is not None:
                raise ValueError(f"{self.kind} carries only left and right")
        return self


class EvidenceBinding(Record):
    """What established an observed quantity: one exact occurrence.

    Offsets address the canonical excerpt of ``evidence_id`` as stored
    (``excerpt_sha256`` pins it). ``as_written`` is the expression text
    verbatim. For a table chunk, ``cell_row``/``cell_col`` name the
    number's own cell and ``header_row``/``header_col`` the one header
    cell whose declaration a bare cell inherited.
    """

    # A value record: immutable, so a snapshot or a projection that
    # holds it can never be changed under the reader that compares it.
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    excerpt_sha256: str
    number_start: int
    number_end: int
    expression_start: int
    expression_end: int
    as_written: str
    cell_row: int | None = None
    cell_col: int | None = None
    header_row: int | None = None
    header_col: int | None = None

    @pydantic.model_validator(mode="after")
    def _coordinates_in_pairs(self) -> "EvidenceBinding":
        """A row and its column are present or absent together, and a
        header cell only accompanies a number cell."""
        if (self.cell_row is None) != (self.cell_col is None):
            raise ValueError("cell_row and cell_col go together")
        if (self.header_row is None) != (self.header_col is None):
            raise ValueError("header_row and header_col go together")
        if self.header_row is not None and self.cell_row is None:
            raise ValueError("a header cell needs a number cell")
        if self.number_start >= self.number_end:
            raise ValueError("the number span is empty")
        if not (
            self.expression_start <= self.number_start
            and self.number_end <= self.expression_end
        ):
            raise ValueError("the number lies outside its expression")
        return self


class Quantity(Record):
    """An admitted number: a value, a unit tree, and what established it.

    An observed quantity carries the ``binding`` ``quantities.admit``
    wrote, re-checked by ``quantities.verify_binding`` at correction
    and load; a derived quantity carries none, its claim names the
    calculation that produced it. Nothing here is free text.

    Attributes:
      value: The signed, finite numeric value, in ``unit``.
      unit: The complete unit, scale included, as a tree.
      period: The period as written, for example ``2024``, ``2024H1``.
      scope: Geography or definition, for example ``全球``.
      binding: The evidence occurrence, for an observed quantity.
    """

    # A value record: immutable, so a snapshot or a projection that
    # holds it can never be changed under the reader that compares it.
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    value: float
    unit: UnitExpr
    period: str | None = None
    scope: str | None = None
    binding: EvidenceBinding | None = None


class QuantityDraft(Record):
    """A number as the researcher reports it, before admission.

    ``quote`` is the number with the unit text attached to it exactly
    as the excerpt writes it (``52亿元``, ``$52 million``, ``60%``);
    ``unit_text`` is the complete unit with its scale, spelled as the
    excerpt spells it; ``occurrence`` selects which occurrence of the
    quote in the excerpt of ``evidence_ref`` (1 = the first). Python
    locates and checks it; nothing is inferred.
    """

    value: float
    unit_text: str
    evidence_ref: str
    quote: str
    occurrence: int = 1
    period: str | None = None
    scope: str | None = None


class TableCell(Record):
    """One physical cell of an extracted table, with its text offsets."""

    # A value record: immutable, so a snapshot or a projection that
    # holds it can never be changed under the reader that compares it.
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    text: str
    row: int
    col: int
    header: bool = False
    row_span: int = 1
    col_span: int = 1
    start: int
    end: int


class TableLayout(Record):
    """Extractor-owned geometry of a table chunk (a flat cell list)."""

    # A value record: immutable, so a snapshot or a projection that
    # holds it can never be changed under the reader that compares it.
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    cells: list[TableCell] = pydantic.Field(default_factory=list)
    header_rows: int = 0
    limitations: list[str] = pydantic.Field(default_factory=list)


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
    # The table geometry of a table chunk extracted under revision v3;
    # ``None`` for prose, snippets, PDFs and v2 evidence.
    table: TableLayout | None = None

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
    # The verifier's reason for the verdict, kept on the reviewed
    # version (reset whenever the claim is re-versioned) so that a
    # ``qualified`` claim carries its qualification to the Analyst, the
    # Editor, and the final verifier.
    review_reason: str | None = None
    # For a derived claim, the version of ``calculation_id`` it
    # reports; ``merge.calculation_current`` refuses the claim when the
    # producer has moved on, stopped, or disagrees with it.
    calculation_version: int | None = None
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
    # Whether the verifier approved this claim's statement for verbatim
    # standalone delivery. Level B retains a block only on an exact
    # wording basis; a citation to a supported claim is not one, because
    # the deterministic check never compares a sentence to its claim.
    standalone: bool = False
    dimension: str | None = None
    origin: str = ""
    map_ref: str | None = None
    # The material partition the claim was admitted to (``merge.
    # admit_material``); fixed at admission, so a repeat that adds
    # questions never moves a claim into another partition.
    partition: str | None = None

    @pydantic.model_validator(mode="after")
    def _quantity_ownership(self) -> "Claim":
        # A derived claim is its calculation's; an observed quantity is
        # its evidence's. Neither may borrow the other's authority.
        derived = self.kind == "derived"
        if derived != (self.calculation_id is not None):
            raise ValueError(
                "a derived claim names its calculation and no other does"
            )
        if self.quantity is not None:
            bound = self.quantity.binding
            if derived and bound is not None:
                raise ValueError("a derived quantity carries no binding")
            if not derived and bound is None:
                raise ValueError("an observed quantity carries a binding")
            if bound is not None and bound.evidence_id not in self.evidence_ids:
                raise ValueError("a binding names evidence the claim cites")
        return self

    def is_reviewed(self) -> bool:
        """Whether the claim may be cited, counted, or calculated with.

        ``supported``, or ``qualified`` with the qualification on record:
        a qualified claim whose reason is missing (a thread persisted
        before ``review_reason`` existed) cannot carry its restriction
        to the report, so it is not citable until reviewed again.
        """
        return self.review == "supported" or (
            self.review == "qualified" and bool(self.review_reason)
        )

    def needs_review(self) -> bool:
        """Whether the verifier still has to judge (or re-judge) it."""
        return self.review == "unreviewed" or (
            self.review == "qualified" and not self.review_reason
        )


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


class RepairTarget(Record):
    """The exact record an acquisition task was sent to repair.

    Plan revision 38 §4.45.2. A worker reads no state, so the target
    carries what the session must be told: the claim's id and the
    version it was read at, its statement and any qualification, the
    evidence it already rests on, and the gap to close. The version is
    what makes a result that outlived its target fail closed.
    """

    claim_id: str
    claim_version: int
    statement: str
    qualification: str | None = None
    evidence_ids: list[str] = pydantic.Field(default_factory=list)
    relationship_id: str | None = None
    gap: str = ""


class AttachmentDraft(Record):
    """Evidence a repair session offers for its task's target.

    It names attempt-local evidence labels and nothing else: the target
    is stamped from the task in Python, never taken from the model.
    """

    evidence_refs: list[str] = pydantic.Field(default_factory=list)
    note: str = ""


class EvidenceAttachment(Record):
    """Evidence to attach to an existing claim, and maybe a relation."""

    target_claim_id: str
    target_claim_version: int
    evidence_ids: list[str] = pydantic.Field(default_factory=list)
    relationship_id: str | None = None
    note: str = ""


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
    # Set on an acquisition task, and required there: what this session
    # repairs (plan revision 38 §4.45.2).
    target: RepairTarget | None = None


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
    # A write and the final review that validates it are admitted
    # together and share this id: the reserve that was documented as
    # holding two complete calls never in fact held the second one, so
    # a rewrite could replace the deliverable body and then find its
    # review unaffordable.
    pair_id: str | None = None
    # A held allowance funds a call that has not started. It is charged
    # from the moment it is taken, so nothing else can spend it, and it
    # is never mistaken for work that was interrupted.
    held: bool = False


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
    kind: DraftClaimKind = "fact"
    evidence_refs: list[str] = pydantic.Field(default_factory=list)
    entity: str | None = None
    period: str | None = None
    quantity: QuantityDraft | None = None
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
    attachments: list[EvidenceAttachment] = pydantic.Field(default_factory=list)
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
    version: SourceVersion | None = None
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
    # The SDK session cap (model exchanges); the allowance above is the
    # ledger's worst case in ``num_turns`` units and is never the cap.
    max_turns: int = 12
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
    draft_version: int | None = None
    # The exact factual unit (sentence, table row, list item) the issue
    # is about, when deterministic: the renderer removes it while the
    # issue is open, so it can never be delivered as fact.
    text: str | None = None


class CalcInput(Record):
    """One input of a calculation: the parent claim as it was consumed.

    A preserved copy, so a parent that changed under the calculation is
    detected even when a cascade missed it: its version, its whole
    quantity, and the qualification it carried (its review reason when
    it was ``qualified``, else ``None``).
    """

    claim_id: str
    claim_version: int
    quantity: Quantity
    qualification: str | None = None
    # For a derived parent, the producer behind its number. An observed
    # parent carries its origin in ``quantity.binding`` instead; a
    # derived one has no binding, so without this the two figures could
    # not be told apart and a calculation could divide one producer's
    # result by itself through two different claims.
    source_calculation_id: str | None = None
    source_calculation_version: int | None = None

    @pydantic.model_validator(mode="after")
    def _one_origin(self) -> "CalcInput":
        """An input is observed or derived, never half of each."""
        producer = self.source_calculation_id, self.source_calculation_version
        if any(producer) and not all(producer):
            raise ValueError(
                "a derived input needs both source_calculation_id and "
                "source_calculation_version"
            )
        if self.source_calculation_version is not None and (
            self.source_calculation_version <= 0
        ):
            raise ValueError("source_calculation_version must be positive")
        return self


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
    unit: UnitExpr | None = None
    status: CalcStatus
    message: str | None = None
    alignment_note: str | None = None
    # The request that produced it, so a calculation stopped by a
    # changed input can be run again from the corrected claims rather
    # than have its old result re-approved.
    request: CalcRequest | None = None
    # Bumped on every recomputation. A derived claim records the
    # version it reports, so a claim left behind by a later run of the
    # same calculation is not citable.
    version: int = 1


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
    # Whether this statement, quoted verbatim and alone, would still be
    # accurate without the surrounding draft. Defaults to false, so a
    # verifier that says nothing approves nothing.
    standalone: bool = False


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
    relationship_id: str | None = None
    url: str | None = None


RepairStatus = Literal["pending", "admitted", "deferred", "done", "dropped"]


class RepairRequest(Record):
    """One recorded request to repair a claim's evidence.

    Plan revision 38 §4.45.4. Every request the verifier makes is kept:
    what could not be funded is ``deferred`` with its reason and
    reconsidered next round, never dropped in silence. ``done`` means an
    attachment was applied, not that a session ran.
    """

    id: str
    claim_id: str
    relationship_id: str | None = None
    objective: str = ""
    url: str | None = None
    issue_id: str | None = None
    review_round: int = 0
    status: RepairStatus = "pending"
    reason: str = ""
    task_id: str | None = None


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
    # Section ids that remain accurate on their own if other sections
    # are removed around them. Defaults to empty: a review that judges
    # nothing retains nothing.
    retainable: list[str] = pydantic.Field(default_factory=list)


DeliveryLevel = Literal["verified", "partial", "diagnostic_only"]


class DeliveryResult(Record):
    """What delivery decided, and why: the one authority all surfaces read.

    ``report_status`` alone cannot tell a useful partial report from a
    withheld one -- both are ``incomplete`` -- so the level is recorded
    beside it and the report, the CLI and Studio all render this record.
    """

    level: DeliveryLevel
    status: ReportStatus
    reason: str = ""
    sections: list[str] = pydantic.Field(default_factory=list)
    removed: list[str] = pydantic.Field(default_factory=list)
    floor: str = ""
    drift: list[str] = pydantic.Field(default_factory=list)


class ReviewSubject(Record):
    """The exact substantive document one final review judged.

    A certificate binds to this, never to ``draft_version``: a draft can
    be rewritten, a supporting claim requalified and the appendices
    re-derived without that counter moving. ``sections`` holds one
    digest per section, so one changed section loses its own retention
    approval without invalidating the others.
    """

    digest: str
    sections: dict[str, str] = pydantic.Field(default_factory=dict)
    section_ids: list[str] = pydantic.Field(default_factory=list)
    # The exact appendix lines shown to the verifier. Delivery renders
    # these, not a fresh derivation, so the reader and the reviewer see
    # the same limitations and coverage.
    appendix: list[str] = pydantic.Field(default_factory=list)
    draft_version: int = 0


class DeliveryCandidate(Record):
    """A reviewed body, kept until a replacement has been validated.

    The exact sections, the review that judged them and the issue
    dispositions as they stood for *this* body. A later draft's clean
    review can resolve wording that still stands here, so its
    resolutions are not inherited; ``ReviewSubject`` carries digests
    and appendix lines but not the sections, so retention cannot be
    built from the certificate alone.
    """

    sections: list[Section] = pydantic.Field(default_factory=list)
    subject: ReviewSubject
    review: DraftReview | None = None
    draft_version: int = 0
    issues: dict[str, Issue] = pydantic.Field(default_factory=dict)
    level: DeliveryLevel = "diagnostic_only"
    status: ReportStatus = "incomplete"


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
    """The configurable safety limits of one run.

    ``model_calls`` and every turn count are in the SDK's ``num_turns``
    unit, which counts assistant turns and tool-result turns alike (a
    session with ``max_turns`` model exchanges reports about twice that,
    plus the structured-output attempts). ``turns_per_exchange`` and
    ``structured_output_attempts`` size the worst case one session can
    report, which is what an attempt reserves.
    """

    wall_clock_s: float = pydantic.Field(default=5400.0, gt=0)
    # The reserves hold two complete single calls (write, final_review):
    # 2 * single_call_timeout_s and 2 * single_call_reserved().
    time_reserve_s: float = pydantic.Field(default=960.0, ge=0)
    task_executions: int = pydantic.Field(default=12, ge=0)
    model_calls: int = pydantic.Field(default=200, gt=0)
    model_call_reserve: int = pydantic.Field(default=20, ge=0)
    tool_calls: int = pydantic.Field(default=150, ge=0)
    remediation_cycles: int = pydantic.Field(default=3, ge=0)
    issue_follow_ups: int = pydantic.Field(default=2, ge=0)
    follow_up_rounds: int = pydantic.Field(default=2, ge=0)
    max_turns: int = pydantic.Field(default=12, gt=0)
    tools_per_attempt: int = pydantic.Field(default=24, gt=0)
    concurrency: int = pydantic.Field(default=2, gt=0)
    # The reservation of one attempt. Headline runs 1 and 3 observed
    # 31-670 s per attempt (map attempts 484-550 s), so 900 s bounds them.
    task_timeout_s: float = pydantic.Field(default=900.0, gt=0)
    single_call_timeout_s: float = pydantic.Field(default=480.0, gt=0)
    single_call_turns: int = pydantic.Field(default=5, gt=0)
    task_attempts: int = pydantic.Field(default=2, gt=0)
    turns_per_exchange: int = pydantic.Field(default=2, gt=0)
    structured_output_attempts: int = pydantic.Field(default=5, ge=0)
    # Material claims are partitioned by review capacity, and every
    # material insertion (finding, map item, derived claim) is admitted
    # by ``merge.admit_material`` against its partition: the map
    # (segments, links, participants, each also capped), each central
    # question, and the rest. No partition can consume another's
    # capacity, so the economics questions keep their share however
    # large the map grows. 28 + 5 * 6 + 6 = 64 claims = 7 review batches
    # (headline run 3 reviewed 90 of 130 material claims in nine
    # batches and had no time left for analysis).
    material_per_question: int = pydantic.Field(default=6, ge=0)
    material_other: int = pydantic.Field(default=6, ge=0)
    # The map partition is the sum of its sub-quotas: segments, links,
    # and participants per stage (four stages), each admitted by kind,
    # so segments and links can never crowd the participants out.
    map_segments: int = pydantic.Field(default=6, ge=0)
    map_links: int = pydantic.Field(default=6, ge=0)
    map_participants_per_stage: int = pydantic.Field(default=4, ge=0)
    calc_requests_per_call: int = pydantic.Field(default=8, ge=0)
    # Acquisition tasks one review batch may create, and how many
    # acquisition attempts a run may execute in all; each is a task
    # execution, so the verifier cannot spend the research budget
    # (headline run 3 spent 7 of 12 executions on acquisitions).
    # The one run-level repair ceiling (plan revision 38 §4.45.2): a
    # ceiling, never a promise -- the budget decides how many run.
    acquisition_executions: int = pydantic.Field(default=4, ge=0)
    # Pipeline reservations: what research dispatch and each single
    # call keep for the stages that must follow (review batches of the
    # material claims already collected, then analyze and assess).
    # ``review_batch_s`` is the expected duration of one review batch of
    # ``REVIEW_BATCH`` claims (headline run 3: nine batches, 105-237 s,
    # mean 174 s; the probes 219-300 s).
    review_batch_s: float = pydantic.Field(default=240.0, gt=0)
    review_batch: int = pydantic.Field(default=10, gt=0)

    @pydantic.model_validator(mode="before")
    @classmethod
    def _drop_legacy_keys(cls, data: Any) -> Any:
        # Schema-2 keys that no longer exist: ``expected_task_s`` (dispatch
        # reserves ``task_timeout_s``), ``material_claims``,
        # ``material_per_attempt`` and ``map_participants`` (revisions
        # 10-12 partitioned the material budget).
        legacy = {
            "expected_task_s",
            "material_claims",
            "material_per_attempt",
            "map_participants",
            "map_claims",
        }
        if isinstance(data, dict) and legacy & set(data):
            data = {k: v for k, v in data.items() if k not in legacy}
        return data

    @pydantic.model_validator(mode="after")
    def _totals_hold_their_reserves(self) -> "Limits":
        if self.time_reserve_s < 2 * self.single_call_timeout_s:
            raise ValueError(
                "time_reserve_s must hold two single calls "
                f"(2 * {self.single_call_timeout_s})"
            )
        if self.model_call_reserve < 2 * self.single_call_reserved():
            raise ValueError(
                "model_call_reserve must hold two single calls "
                f"(2 * {self.single_call_reserved()})"
            )
        if self.wall_clock_s < self.time_reserve_s:
            raise ValueError("wall_clock_s must be at least time_reserve_s")
        if self.model_calls < self.model_call_reserve:
            raise ValueError("model_calls must be at least model_call_reserve")
        return self

    def map_claims(self) -> int:
        """The map partition: its sub-quotas summed over the stages."""
        return (
            self.map_segments
            + self.map_links
            + len(STAGES) * self.map_participants_per_stage
        )

    def material_claims(self) -> int:
        """The whole material budget: the sum of its partitions."""
        return (
            self.map_claims()
            + len(CENTRAL_QUESTIONS) * self.material_per_question
            + self.material_other
        )

    def attempt_turns(self) -> int:
        """The most ``num_turns`` a tool session can report."""
        return (
            self.turns_per_exchange * self.max_turns
            + self.turns_per_exchange * self.structured_output_attempts
        )

    def single_call_reserved(self) -> int:
        """The most ``num_turns`` a single call can report."""
        return self.turns_per_exchange * self.single_call_turns


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
    fixture: str | None = None
    fixture_digest: str | None = None


# Every class that can appear in a checkpoint; the serializer allowlist.
PERSISTED: tuple[type[Record], ...] = (
    UnitExpr,
    EvidenceBinding,
    Quantity,
    QuantityDraft,
    TableCell,
    TableLayout,
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
    RepairTarget,
    AttachmentDraft,
    EvidenceAttachment,
    RepairRequest,
    TaskResult,
    Brief,
    ReviewSubject,
    DeliveryResult,
    DeliveryCandidate,
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
