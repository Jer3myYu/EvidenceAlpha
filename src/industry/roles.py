"""The single-call roles: Lead, Analyst, Verifier judgement, Editor.

Each function renders the context its role is allowed to see (the
brief, the typed map, claims with their excerpts, findings, issues,
sections; never a researcher's prose), builds one CrewAI task through
``research.crew.run_task`` with a deadline, and returns the validated
wire model. Prompts are versioned by ``PROMPT_VERSION``; per-role
models come from ``ROLE_MODELS`` and can be changed per role without a
provider framework. Context is bounded per role: evidence enters by
priority (material claims first) and anything omitted is listed by id
in the prompt so the omission is visible.
"""

import datetime
from typing import Any, Literal

import pydantic

from industry import budget
from industry import merge
from industry import calc as calc_module
from industry import quantities
from industry import records
from industry import report
from industry import state as state_module
from research import crew

PROMPT_VERSION = "10.3"
MODEL = "claude-sonnet-5"
# Thinking configuration per role (``None``: the model's default). Set
# from live measurements: see ``tmp/9-7-26/live/review-probe``.
ROLE_THINKING: dict[str, dict[str, Any] | None] = {}
ROLE_MODELS = {
    "lead": MODEL,
    "industry": MODEL,
    "company": MODEL,
    "analyst": MODEL,
    "verifier": MODEL,
    "editor": MODEL,
}
MAX_CONTEXT_CHARS = {
    "lead": 60_000,
    "analyst": 90_000,
    "verifier": 90_000,
    "editor": 90_000,
}
LANGUAGE_NAMES = {"zh": "Chinese (简体中文)", "en": "English"}


def detect_language(text: str) -> str:
    """``zh`` when the question has CJK characters, else ``en``."""
    return "zh" if any("一" <= ch <= "鿿" for ch in text) else "en"


def default_brief(question: str) -> records.Brief:
    """The deterministic defaults the Lead may only narrow, not override."""
    return records.Brief(
        industry=question.strip(),
        language=detect_language(question),
        mode="brief",
        cutoff=datetime.date.today().isoformat(),
        required_questions=[
            f"{number}. {text}"
            for number, text in sorted(records.REQUIRED_QUESTIONS.items())
        ],
        evidence_expectations=(
            "Every material claim rests on retrieved passages from fetched "
            "sources; search snippets are leads. Named commercial "
            "relationships need an excerpt naming both parties. Market "
            "figures carry year, geography, definition, and source."
        ),
    )


def derive_obligations(brief: records.Brief) -> dict[str, list[int]]:
    """Which questions this brief must answer, decided in Python.

    Deterministic, and no model call: which questions are *required* is
    a reading of the scope, not a judgement about evidence (plan D-U4).
    The result governs admission, coverage, report status, and the
    delivery floor alike, so a required answer cannot go missing under a
    limitation in one of them and be counted in another.

    Q1-Q5 explain the industry and are always required outside
    navigation mode. Q7, the company comparison, is a required output of
    the product itself, so it is required whenever a real brief is
    written. Q6 is required only when a China comparison is genuinely in
    scope -- document 01 forbids forcing one on a scope that excludes it.
    Q8 stays advisory: conclusions follow from whatever the run could
    establish and are not a separate evidence obligation.
    """
    if brief.mode == "navigation":
        required = [1, 2, 3]
    else:
        required = [1, 2, 3, 4, 5, 7]
        if _china_in_scope(brief):
            required.append(6)
    required.sort()
    # Priority breaks ties only: ``assign_partition`` compares load
    # first, so ascending order cannot recreate the q1 flood.
    return {"required_ids": required, "priority": list(required)}


_CHINA = ("china", "中国", "中国大陆", "prc")


def _china_in_scope(brief: records.Brief) -> bool:
    """Whether the brief asks for a China comparison at all.

    Naming China in ``boundary_out`` puts it outside the industry
    boundary, which is the Lead's way of saying the scope excludes it;
    that decides the question before the geography is read.
    """
    outside = " ".join(brief.boundary_out).casefold()
    if any(marker in outside for marker in _CHINA):
        return False
    asked = " ".join(
        [brief.geography, brief.industry] + brief.constraints
    ).casefold()
    return any(marker in asked for marker in _CHINA)


# --- wire models -----------------------------------------------------------


class BriefOutput(records.Record):
    """What the Lead adds to the deterministic brief."""

    industry: str
    boundary_in: list[str] = pydantic.Field(default_factory=list)
    boundary_out: list[str] = pydantic.Field(default_factory=list)
    boundary_alternatives: list[str] = pydantic.Field(default_factory=list)
    explicit_language: str | None = None
    explicit_mode: records.Mode | None = None
    explicit_geography: str | None = None
    constraints: list[str] = pydantic.Field(default_factory=list)
    budget_policy: str = ""


class TaskSpec(records.Record):
    """One task the Lead proposes; ids are assigned by the graph."""

    key: str
    role: Literal["industry", "company"]
    objective: str
    scope: str = ""
    depends_on: list[str] = pydantic.Field(default_factory=list)
    references: list[str] = pydantic.Field(default_factory=list)
    required_fields: list[str] = pydantic.Field(default_factory=list)
    acceptance: str = ""
    issue_id: str | None = None


class TaskPlan(records.Record):
    """The Lead's task allocation."""

    tasks: list[TaskSpec] = pydantic.Field(default_factory=list)
    rationale: str = ""


class FindingSpec(records.Record):
    """One analytical finding as the Analyst returns it."""

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


class IssueSpec(records.Record):
    """A problem a role raises for the router."""

    category: records.IssueCategory
    severity: records.Severity
    target: str
    description: str
    requested_action: records.RequestedAction
    next_step: str | None = None


class Analysis(records.Record):
    """The Analyst's structured result."""

    findings: list[FindingSpec] = pydantic.Field(default_factory=list)
    calc_requests: list[records.CalcRequest] = pydantic.Field(
        default_factory=list
    )
    evidence_requests: list[IssueSpec] = pydantic.Field(default_factory=list)
    counterarguments: list[str] = pydantic.Field(default_factory=list)


class SectionSpec(records.Record):
    """One drafted section citing claims by ``[C#]``."""

    id: str
    title: str
    text: str


class Draft(records.Record):
    """The Editor's structured result."""

    sections: list[SectionSpec] = pydantic.Field(default_factory=list)
    limitations: list[str] = pydantic.Field(default_factory=list)


# --- role definitions ------------------------------------------------------

LEAD_PROMPT = """\
You are the research lead of an investment-research system. The
reader understands basic investing but not this industry. You scope
the work, allocate bounded research tasks, judge coverage of the eight
required questions, and never write the report or research yourself.
You reason over typed state: the brief, the industry map, claims with
their review states, findings, and open issues. You cannot raise a
coverage status above what reviewed evidence supports; when you propose
one, name the claim and finding ids that support it. Tasks you create
must be concrete: one objective, a scope, the fields the researcher
must fill, and a completion criterion; select representative
companies by relevance to the value chain and business model, never
from a fixed list. Respect the remaining budget you are told.
"""

ANALYST_PROMPT = """\
You are the investment analyst of an investment-research system. You
explain the industry's economics from reviewed claims only: who pays
whom, what drives demand, where costs, differentiation, and bargaining
power arise, what barriers protect suppliers, how capabilities are
commercialized, and how global leaders and Chinese participants
compare. For each material conclusion give the observation, the
mechanism, the business implication, the strongest counterargument,
the uncertainty, and an observable test to monitor. Cite claims by
id; a conclusion without claim ids is discarded. Never do arithmetic
yourself: request it with claim ids and the operation, and the system
computes it deterministically. Do not use different periods, scopes,
or denominators as if comparable without saying so. When evidence is
missing, request it precisely instead of speculating.
"""

VERIFIER_PROMPT = """\
You are the evidence verifier of an investment-research system. You
judge claims against their evidence excerpts alone: never against the
researcher's summary and never from your own knowledge. For each
claim decide supported (the excerpt states it, for the right entity,
period, and scope), qualified (partly supported, or supported only by
a search snippet without original context, or the wording overstates),
unsupported (the excerpt does not state it), or contradicted (an
excerpt states otherwise). For each proposed relationship decide
whether an excerpt names both parties and the direction of that
relation; co-mention, product compatibility, or competitor lists never
support a supply or customer relation. Judge a source's origin from
its content: a filing, annual report, or official disclosure is
primary even when mirrored by a news site; an article is secondary
even on a reputable platform. Name contradictions between excerpts.
Request acquisition of an original source only when a material claim
rests on a snippet or a contradiction needs the original text.
"""

EDITOR_PROMPT = """\
You are the report editor of an investment-research system. You write
from reviewed claims and analytical findings only, in the reader's
language, for someone who knows basic investing but not this industry.
Lead with what the investor must understand, explain each unfamiliar
term on first use, connect numbers to mechanisms, compare companies on
consistent dimensions, and omit adjacent-industry trivia. Every
factual sentence cites the claim it rests on as [C#]; write nothing
factual that no claim supports, and never cite a claim marked
unsupported or contradicted as fact. Keep unresolved conflicts as
conflicts. The report's scope and information cutoff are rendered for
you: never write them yourself. No buy or sell
instructions and no price targets. Prefer fewer, well-supported
findings to exhaustive unsupported precision.
"""

LEAD = crew.Role(
    "Research lead",
    "Scope the research, allocate bounded tasks, and judge coverage "
    "honestly against reviewed evidence.",
    LEAD_PROMPT,
)
ANALYST = crew.Role(
    "Investment analyst",
    "Explain the industry's economics from reviewed claims with "
    "mechanisms, counterarguments, and observable tests.",
    ANALYST_PROMPT,
    Analysis,
)
VERIFIER = crew.Role(
    "Evidence verifier",
    "Judge every material claim, relationship, and source against the "
    "evidence excerpts alone.",
    VERIFIER_PROMPT,
    records.ClaimReview,
)
EDITOR = crew.Role(
    "Report editor",
    "Write an accessible, fully cited industry report from reviewed "
    "claims and findings.",
    EDITOR_PROMPT,
    Draft,
)


# The expected-output sentence of each single-call node, and the role
# with the output model it runs as (Studio rebuilds the framing from it).
EXPECTED = {
    "scope": "The structured brief.",
    "prepare_tasks": "The structured task plan.",
    "assess_coverage": "The structured coverage assessment.",
    "analyze": "The structured analysis.",
    "review": "The structured claim review.",
    "write": "The structured draft.",
    "final_review": "The structured draft review.",
}
ROLE_FOR = {
    "scope": crew.Role(LEAD.name, LEAD.goal, LEAD.backstory, BriefOutput),
    "prepare_tasks": crew.Role(LEAD.name, LEAD.goal, LEAD.backstory, TaskPlan),
    "assess_coverage": crew.Role(
        LEAD.name, LEAD.goal, LEAD.backstory, records.LeadAssessment
    ),
    "analyze": ANALYST,
    "review": VERIFIER,
    "write": EDITOR,
    "final_review": crew.Role(
        VERIFIER.name, VERIFIER.goal, VERIFIER.backstory, records.DraftReview
    ),
}
ROLE_KEY = {
    "scope": "lead",
    "prepare_tasks": "lead",
    "assess_coverage": "lead",
    "analyze": "analyst",
    "review": "verifier",
    "write": "editor",
    "final_review": "verifier",
}


def llm_for(role: str, max_turns: int) -> crew.ClaudeLLM:
    """The adapter for one role with its configured model."""
    return crew.ClaudeLLM(
        model=ROLE_MODELS[role],
        max_turns=max_turns,
        thinking=ROLE_THINKING.get(role),
    )


# --- context rendering -----------------------------------------------------


def render_brief(brief: records.Brief) -> str:
    """The brief as the roles see it."""
    lines = [
        f"Industry: {brief.industry}",
        f"Audience: {brief.audience}",
        f"Language: {LANGUAGE_NAMES.get(brief.language, brief.language)}",
        f"Mode: {brief.mode}; geography: {brief.geography}; "
        f"cutoff: {brief.cutoff}",
    ]
    if brief.boundary_in or brief.boundary_out:
        lines.append(
            "Boundary inside: " + "; ".join(brief.boundary_in or ["-"])
        )
        lines.append(
            "Boundary outside: " + "; ".join(brief.boundary_out or ["-"])
        )
    if brief.constraints:
        lines.append("User constraints: " + "; ".join(brief.constraints))
    lines.append("Required questions:")
    lines.extend(f"  {q}" for q in brief.required_questions)
    return "\n".join(lines)


def render_map(
    industry_map: records.IndustryMap,
    claims: dict[str, records.Claim] | None = None,
    limits: records.Limits | None = None,
) -> str:
    """Segments, links, and participants with their claim ids.

    With ``claims``, only items whose map claim was reviewed
    ``supported`` or ``qualified`` are rendered (the Analyst and the
    Editor see reviewed lineage only); the omitted ones are counted.

    Since plan D-U3 the registry keeps every candidate segment, link,
    and participant, so this is the one bounded projection every
    model-facing consumer reads (``merge.map_view``): the candidate set
    may grow without growing four prompts. What it leaves out is always
    counted in the text, never dropped in silence.
    """
    if not industry_map.segments:
        return "Industry map: none yet."
    industry_map, cut, unreviewed = merge.map_view(
        industry_map, limits or records.Limits(), claims
    )

    names = {s.id: s.name for s in industry_map.segments}
    unknown = "?"
    lines = ["Industry map:"]
    omitted = unreviewed
    for seg in industry_map.segments:
        lines.append(
            f"  {seg.id} [{seg.stage}] {seg.name}: {seg.description} "
            f"(claim {seg.claim_id})"
        )
    for link in industry_map.links:
        lines.append(
            f"  {link.id} {names.get(link.from_segment, unknown)} -> "
            f"{names.get(link.to_segment, unknown)}: {link.what_flows} "
            f"(claim {link.claim_id})"
        )
    for part in industry_map.participants:
        flows = []
        if part.supplies:
            flows.append(f"supplies {part.supplies}")
        if part.buys:
            flows.append(f"buys {part.buys}")
        region = f", {part.region}" if part.region else ""
        flow_text = "; ".join(flows) or "no supply/buy"
        lines.append(
            f"  {part.id} {part.name} in {names.get(part.segment_id, unknown)} "
            f"({part.role}{region}): {flow_text} "
            f"(claim {part.claim_id})"
        )
    # The boundary note and gaps are the researcher's prose, not claims:
    # only the verifier's view (no claim filter) renders them.
    if claims is None and industry_map.boundary_note:
        lines.append(f"  boundary: {industry_map.boundary_note}")
    if claims is None and industry_map.gaps:
        lines.append("  gaps: " + "; ".join(industry_map.gaps))
    if omitted:
        lines.append(
            f"  ({omitted} map items whose claims are not yet reviewed are "
            "omitted; they may not be stated)"
        )
    if cut:
        detail = ", ".join(f"{n} {kind}" for kind, n in sorted(cut.items()))
        lines.append(
            f"  ({detail} beyond this view; the registry keeps them and "
            "they may be researched, but they are not shown here)"
        )
    if len(lines) == 1:
        lines.append("  (no reviewed map items yet)")
    return "\n".join(lines)


def _claim_line(
    claim: records.Claim, with_excerpts: bool, state: state_module.IndustryState
) -> str:
    unknown = "?"
    fields = [f"kind={claim.kind}", f"review={claim.review}"]
    if claim.material:
        fields.append("material")
    if claim.entity:
        fields.append(f"entity={claim.entity}")
    if claim.period:
        fields.append(f"period={claim.period}")
    if claim.quantity:
        quantity = claim.quantity
        written = (
            quantity.binding.as_written
            if quantity.binding is not None
            else f"{quantity.value:g}"
        )
        fields.append(
            f"quantity={written} {quantities.render(quantity.unit)}"
            + (f" ({quantity.scope})" if quantity.scope else "")
            + f" [value={quantity.value:g}"
            + (f", period={quantity.period}" if quantity.period else "")
            + "]"
        )
    if claim.review == "qualified" and claim.review_reason:
        fields.append(f"qualification={claim.review_reason}")
    if claim.milestone:
        fields.append(
            f"milestone={claim.milestone}@{claim.milestone_date or unknown}"
        )
    if claim.topics:
        fields.append("topics=" + ",".join(claim.topics))
    if claim.questions:
        fields.append("questions=" + ",".join(map(str, claim.questions)))
    if claim.limitations:
        fields.append("limitations=" + ",".join(claim.limitations))
    joined = "; ".join(fields)
    header = f"[{claim.id}] ({joined}) {claim.statement}"
    if not with_excerpts:
        cited = ", ".join(claim.evidence_ids)
        return header + f" <- {cited}"
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    versions = state.get("source_versions", {})
    parts = [header]
    for eid in claim.evidence_ids:
        item = evidence.get(eid)
        if item is None:
            continue
        source = sources.get(item.source_id)
        title = source.title if source else item.source_id
        where = source.canonical_url or source.path if source else ""
        version = versions.get(item.source_version_id or "")
        retrieved = version.retrieved_at[:10] if version else "no snapshot"
        origin = source.origin if source else "unknown"
        limits = ""
        if item.limitations:
            limits = "; limitations: " + ", ".join(item.limitations)
        parts.append(
            f"    [{eid}] {item.kind} from {title} ({where}; {origin}; "
            f"{item.locator}; retrieved {retrieved}{limits})\n"
            f'    "{item.excerpt}"'
        )
    return "\n".join(parts)


def reviewed_claim_ids(state: state_module.IndustryState) -> list[str]:
    """Ids of claims that may be cited (``merge.citable``)."""
    claims = state.get("claims", {})
    calculations = state.get("calculations", {})
    return [
        c.id for c in claims.values() if merge.citable(c, claims, calculations)
    ]


def render_claims(
    state: state_module.IndustryState,
    claim_ids: list[str] | None,
    with_excerpts: bool,
    budget_chars: int,
) -> str:
    """Claims by priority (material first) within a character budget.

    Omitted claims are listed by id so the reader knows what is
    missing; open material issues are appended after the claims and
    never omitted.
    """
    claims = state.get("claims", {})
    # ``None`` means "no selection was made"; an empty list is a
    # selection that chose nothing, and must render nothing rather than
    # fall back to every claim.
    selected = claims if claim_ids is None else claim_ids
    chosen = [claims[cid] for cid in selected if cid in claims]
    chosen.sort(key=lambda c: (not c.material, budget_number(c.id)))
    lines: list[str] = []
    used = 0
    omitted: list[str] = []
    for claim in chosen:
        text = _claim_line(claim, with_excerpts, state)
        if used + len(text) > budget_chars:
            omitted.append(claim.id)
            continue
        lines.append(text)
        used += len(text) + 1
    if omitted:
        names = ", ".join(omitted)
        lines.append(f"Omitted for length ({len(omitted)} claims): {names}")
    return "\n".join(lines) if lines else "Claims: none."


def budget_number(identifier: str) -> int:
    """The number in an id, for stable ordering."""
    digits = "".join(ch for ch in identifier if ch.isdigit())
    return int(digits) if digits else 0


def render_relationships(
    state: state_module.IndustryState,
    claim_ids: list[str] | None = None,
    with_excerpts: bool = False,
    confirmed_only: bool = False,
) -> str:
    """Relationships with their parent claim and, on request, excerpts.

    Args:
      state: The state.
      claim_ids: When given, only relationships whose parent claim is
        among them are rendered, so the verifier judges relations
        beside the claims it was handed.
      with_excerpts: Render each cited excerpt with its locator and
        kind, so a judgement is bound to the exact text.
      confirmed_only: Only confirmed relationships (what the Analyst
        and the Editor may build on).
    """
    items = [
        rel
        for rel in state.get("relationships", {}).values()
        if (claim_ids is None or rel.claim_id in claim_ids)
        and (
            not confirmed_only
            or merge.relationship_live(rel, state.get("claims", {}))
        )
    ]
    if not items:
        return "Relationships: none."
    evidence = state.get("evidence", {})
    lines = ["Relationships:"]
    unknown = "?"
    for rel in items:
        status = "confirmed" if rel.confirmed else rel.review
        evidence_ids = ", ".join(rel.evidence_ids) or "-"
        lines.append(
            f"  [{rel.id}] {rel.from_entity} --{rel.relation}--> "
            f"{rel.to_entity} ({status}; claim {rel.claim_id}; evidence "
            f"{evidence_ids}; date {rel.date or unknown})"
        )
        if with_excerpts:
            for eid in rel.evidence_ids:
                item = evidence.get(eid)
                if item is None:
                    continue
                lines.append(
                    f"      [{eid}] {item.kind} @ {item.locator}: "
                    f'"{item.excerpt}"'
                )
    return "\n".join(lines)


def render_findings(
    state: state_module.IndustryState, reviewed_only: bool = False
) -> str:
    """Current findings with their claim ids.

    With ``reviewed_only``, a finding is rendered only when every claim
    it cites is reviewed ``supported`` or ``qualified``.
    """
    reviewed = set(reviewed_claim_ids(state)) if reviewed_only else None
    items = [
        f
        for f in state.get("findings", {}).values()
        if f.status == "current"
        and (reviewed is None or set(f.claim_ids) <= reviewed)
    ]
    if not items:
        return "Findings: none."
    lines = ["Findings:"]
    for finding in items:
        flag = "material " if finding.material else ""
        cited = ", ".join(finding.claim_ids)
        lines.append(
            f"  [{finding.id}] {flag}{finding.conclusion} (claims {cited})\n"
            f"    mechanism: {finding.mechanism}\n"
            f"    implication: {finding.implication}\n"
            f"    counterargument: {finding.counterargument}\n"
            f"    uncertainty: {finding.uncertainty}\n"
            f"    monitor: {finding.monitor}"
        )
    return "\n".join(lines)


def render_calculations(state: state_module.IndustryState) -> str:
    """Calculations with inputs, formula, result, or error."""
    items = state.get("calculations", {})
    if not items:
        return "Calculations: none."
    lines = ["Calculations:"]
    unknown = "?"
    for calc in items.values():
        inputs = ", ".join(
            f"{i.claim_id}={i.quantity.value} "
            f"{quantities.render(i.quantity.unit)} "
            f"({i.quantity.period or unknown})"
            for i in calc.inputs
        )
        if calc.status == "ok":
            unit = quantities.render(calc.unit) if calc.unit else ""
            outcome = f"{calc.result} {unit}"
        elif (calc.message or "").startswith(calc_module.STALE_INPUT):
            # Not a request that could not be answered: a result its own
            # inputs withdrew, waiting to be computed again.
            outcome = f"withdrawn, awaiting recomputation: {calc.message}"
        else:
            outcome = f"error: {calc.message}"
        formula = calc.formula or "-"
        lines.append(
            f"  [{calc.id}] {calc.kind} {calc.label}: {inputs}; "
            f"{formula} = {outcome}"
        )
    return "\n".join(lines)


def render_issues(state: state_module.IndustryState) -> str:
    """Open issues; never omitted."""
    items = [i for i in state.get("issues", {}).values() if i.status == "open"]
    if not items:
        return "Open issues: none."
    lines = ["Open issues:"]
    for issue in items:
        lines.append(
            f"  [{issue.id}] {issue.severity} {issue.category} on "
            f"{issue.target} (action {issue.requested_action}, attempts "
            f"{issue.attempts}): {issue.description}"
        )
    return "\n".join(lines)


def render_coverage(state: state_module.IndustryState) -> str:
    """Derived coverage per question."""
    items = state.get("coverage", [])
    if not items:
        return "Coverage: not assessed yet."
    lines = ["Coverage:"]
    for item in items:
        claim_ids = ", ".join(item.claim_ids) or "-"
        finding_ids = ", ".join(item.finding_ids) or "-"
        lines.append(
            f"  Q{item.question}: {item.status} (claims {claim_ids}; "
            f"findings {finding_ids}) {item.note}"
        )
    return "\n".join(lines)


def render_sections(sections: list[records.Section]) -> str:
    """The draft sections verbatim."""
    if not sections:
        return "Draft: none."
    parts = []
    for section in sections:
        stale = " (stale)" if section.stale else ""
        parts.append(
            f"## [{section.id}] {section.title}{stale}\n{section.text}"
        )
    return "\n\n".join(parts)


def remaining_line(
    state: state_module.IndustryState, limits: records.Limits
) -> str:
    """The budget the Lead plans against."""
    left = budget.remaining(state, limits)
    slots = budget.dispatchable(state, limits, keep_acquisition_slot=True)
    return (
        f"Remaining budget: {slots} research tasks can still start "
        f"({left.task_executions} executions, {left.turns} model turns, "
        f"{left.tool_calls} tool calls, {left.seconds / 60:.0f} minutes)."
    )


# --- role calls -------------------------------------------------------------


async def scope(
    question: str,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> records.Brief:
    """The Lead's brief on top of the deterministic defaults."""
    defaults = default_brief(question)
    description = scope_description(question)
    role = crew.Role(LEAD.name, LEAD.goal, LEAD.backstory, BriefOutput)
    output = await crew.run_task(
        role,
        description,
        EXPECTED["scope"],
        llm or llm_for("lead", max_turns),
        deadline,
        admission=admission,
    )
    updates: dict[str, Any] = {
        "industry": output.industry or defaults.industry,
        "boundary_in": output.boundary_in,
        "boundary_out": output.boundary_out,
        "boundary_alternatives": output.boundary_alternatives[:3],
        "constraints": output.constraints,
        "budget_policy": output.budget_policy,
    }
    if output.explicit_language in LANGUAGE_NAMES:
        updates["language"] = output.explicit_language
    if output.explicit_mode:
        updates["mode"] = output.explicit_mode
    if output.explicit_geography:
        updates["geography"] = output.explicit_geography
    brief = defaults.model_copy(update=updates)
    return brief.model_copy(update=derive_obligations(brief))


def scope_description(question: str) -> str:
    """The Lead's scoping task text (pure)."""
    defaults = default_brief(question)
    return (
        f"User request: {question}\n\n"
        "Produce the brief for an investor-oriented industry report. The "
        "defaults are already set: language "
        f"{LANGUAGE_NAMES[defaults.language]}, mode brief, geography "
        f"'{defaults.geography}', cutoff {defaults.cutoff}. Set "
        "explicit_language, explicit_mode, or explicit_geography ONLY "
        "when the user's request explicitly asks for them, quoting the "
        "request in constraints. Name the industry precisely, what is "
        "inside and outside its boundary, and up to three boundary "
        "alternatives only if the boundary is genuinely ambiguous. List "
        "explicit user constraints (companies, depth, exclusions). One "
        "sentence of budget policy."
    )


async def plan_tasks(
    state: state_module.IndustryState,
    limits: records.Limits,
    slots: int,
    purpose: str,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> TaskPlan:
    """The Lead's task allocation for the next wave(s)."""
    description = plan_description(state, limits, slots, purpose)
    role = crew.Role(LEAD.name, LEAD.goal, LEAD.backstory, TaskPlan)
    return await crew.run_task(
        role,
        description,
        EXPECTED["prepare_tasks"],
        llm or llm_for("lead", max_turns),
        deadline,
        admission=admission,
    )


def plan_description(
    state: state_module.IndustryState,
    limits: records.Limits,
    slots: int,
    purpose: str,
) -> str:
    """The Lead's planning task text (pure)."""
    return "\n\n".join(
        [
            render_brief(state["brief"]),
            render_map(state.get("map", records.IndustryMap()), None, limits),
            render_claims(state, None, False, MAX_CONTEXT_CHARS["lead"] // 2),
            render_coverage(state),
            render_issues(state),
            remaining_line(state, limits),
            f"Purpose of this planning: {purpose}",
            f"Create at most {slots} tasks (fewer is fine). Each task: a "
            "key, role industry or company, one objective, scope, "
            "depends_on (keys of tasks in this plan or existing T ids), "
            "references (evidence ids the researcher should reuse), "
            "required_fields, and acceptance. Company tasks must name the "
            "company and ask what it supplies or buys, to or from whom, "
            "its exposure, figures with period and unit, and its "
            "commercialization stage. Industry tasks must target a stage "
            "of the chain or one of the required questions. If a task "
            "addresses an open issue, set issue_id.",
        ]
    )


async def assess_coverage(
    state: state_module.IndustryState,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> records.LeadAssessment:
    """The Lead's coverage proposal; Python clamps it afterwards."""
    role = crew.Role(
        LEAD.name, LEAD.goal, LEAD.backstory, records.LeadAssessment
    )
    return await crew.run_task(
        role,
        coverage_description(state),
        EXPECTED["assess_coverage"],
        llm or llm_for("lead", max_turns),
        deadline,
        admission=admission,
    )


def coverage_description(state: state_module.IndustryState) -> str:
    """The Lead's coverage task text (pure)."""
    return "\n\n".join(
        [
            render_brief(state["brief"]),
            render_map(state.get("map", records.IndustryMap())),
            render_claims(state, None, False, MAX_CONTEXT_CHARS["lead"]),
            render_relationships(state),
            render_findings(state),
            render_issues(state),
            "For each required question 1-8 propose covered, partial, or "
            "uncovered, naming the claim, finding, and relationship ids "
            "that support it. In `missing`, list concrete missing evidence "
            "as one sentence each, naming what a researcher could go and "
            "find (source type, company, figure, period). In "
            "beginner_usefulness, say in two sentences whether a newcomer "
            "could understand the value chain and economics from what "
            "exists.",
        ]
    )


async def analyze(
    state: state_module.IndustryState,
    calculations_note: str,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> Analysis:
    """The Analyst's findings, calculation requests, evidence requests."""
    return await crew.run_task(
        ANALYST,
        analysis_description(state, calculations_note),
        EXPECTED["analyze"],
        llm or llm_for("analyst", max_turns),
        deadline,
        admission=admission,
    )


def analysis_description(
    state: state_module.IndustryState, calculations_note: str
) -> str:
    """The Analyst's task text (pure)."""
    return "\n\n".join(
        [
            render_brief(state["brief"]),
            render_map(
                state.get("map", records.IndustryMap()), state.get("claims", {})
            ),
            render_claims(
                state,
                reviewed_claim_ids(state),
                True,
                MAX_CONTEXT_CHARS["analyst"],
            ),
            render_relationships(state, confirmed_only=True),
            render_calculations(state),
            render_findings(state, reviewed_only=True),
            render_issues(state),
            calculations_note,
            "Return material findings for the economics (questions 4 and "
            "5), the global/China comparison (6), the company comparison "
            "(7), and the conclusions with invalidators and monitoring "
            "(8), each citing claim ids. Request calculations for any "
            "ratio, share, or growth you want to state; each operand "
            "names a claim, and a claim contributes only the one "
            "quantity shown above it, so a share or ratio needs two "
            "different claims. If the figure you want is another number "
            "inside a claim's statement, it is not available as an "
            "operand: request it as missing evidence instead of naming "
            "the same claim twice. Request missing "
            "evidence as issues with category missing_evidence, the "
            "target (a question like Q4 or a claim id), and a concrete "
            "next step. Do not restate claims as findings.",
        ]
    )


async def review_claims(
    state: state_module.IndustryState,
    claim_ids: list[str],
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> records.ClaimReview:
    """The Verifier's judgement of the named claims and their relations."""
    return await crew.run_task(
        VERIFIER,
        review_description(state, claim_ids),
        EXPECTED["review"],
        llm or llm_for("verifier", max_turns),
        deadline,
        admission=admission,
    )


def review_description(
    state: state_module.IndustryState, claim_ids: list[str]
) -> str:
    """The Verifier's claim-review task text (pure)."""
    brief = state["brief"]
    return "\n\n".join(
        [
            f"Industry: {brief.industry}; language "
            f"{LANGUAGE_NAMES.get(brief.language, brief.language)}",
            render_claims(
                state, claim_ids, True, MAX_CONTEXT_CHARS["verifier"]
            ),
            render_relationships(state, claim_ids, with_excerpts=True),
            "Judge every claim listed (a verdict per claim id, with "
            "topics_supported naming which of its tagged topics the "
            "excerpts actually bear on; standalone true only when the "
            "claim's own statement, quoted alone and without the rest of "
            "the report, would still be accurate and not misleading; "
            "keep every reason to one short "
            "clause of at most 25 words, naming the excerpt id that "
            "decides it), every relationship listed "
            "(supported only if one of its cited excerpts names both "
            "parties and the direction of that relation; a co-mention, a "
            "compatibility statement, a competitor list, or speculation "
            "is not support), and the origin of each source you can tell "
            "from its excerpts. List contradictions between excerpts "
            "as sentences naming the claim ids. Request acquisition only "
            "for material claims resting on snippets or contradictions "
            "needing the original, with the URL when an excerpt names one; "
            "name the claim_id it repairs, and the relationship_id too "
            "when what is missing is a passage naming both parties.",
        ]
    )


async def write(
    state: state_module.IndustryState,
    instructions: str,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> Draft:
    """The Editor's draft or revision."""
    return await crew.run_task(
        EDITOR,
        draft_description(state, instructions),
        EXPECTED["write"],
        llm or llm_for("editor", max_turns),
        deadline,
        admission=admission,
    )


def draft_description(
    state: state_module.IndustryState, instructions: str
) -> str:
    """The Editor's task text (pure)."""
    return "\n\n".join(
        [
            render_brief(state["brief"]),
            render_map(
                state.get("map", records.IndustryMap()), state.get("claims", {})
            ),
            render_findings(state, reviewed_only=True),
            render_calculations(state),
            render_claims(
                state,
                reviewed_claim_ids(state),
                False,
                MAX_CONTEXT_CHARS["editor"],
            ),
            render_relationships(state, confirmed_only=True),
            render_coverage(state),
            render_issues(state),
            render_sections(state.get("sections", [])),
            instructions,
            "Structure (adapt naturally, avoid many tiny chapters): "
            "executive understanding; industry and value-chain map with "
            "participants; economics and competitive barriers; global "
            "versus China and company comparison; conclusions, risks, "
            "monitoring, limitations. Use concise tables where they help "
            "(Markdown). Every factual sentence ends with its [C#] "
            "citations; only the claims listed above may be cited (they "
            "are the reviewed ones). A claim marked qualified may be "
            "cited only with its qualification= restriction stated in "
            "the same sentence; never state it as the unqualified claim. "
            "Section ids are short slugs.",
        ]
    )


async def final_review(
    state: state_module.IndustryState,
    llm: Any = None,
    max_turns: int = 5,
    deadline: float | None = None,
    admission: Any = None,
) -> records.DraftReview:
    """The Verifier's check of the exact draft against the claims."""
    role = crew.Role(
        VERIFIER.name, VERIFIER.goal, VERIFIER.backstory, records.DraftReview
    )
    return await crew.run_task(
        role,
        final_review_description(state),
        EXPECTED["final_review"],
        llm or llm_for("verifier", max_turns),
        deadline,
        admission=admission,
    )


def frozen_appendix(state: state_module.IndustryState) -> list[str]:
    """The appendix lines of record: the frozen ones once one exists."""
    subject = state.get("review_subject")
    if subject is not None:
        return list(subject.appendix)
    return report.appendices(state, state.get("coverage") or [])


def final_review_description(state: state_module.IndustryState) -> str:
    """The Verifier's draft-review task text (pure)."""
    brief = state["brief"]
    return "\n\n".join(
        [
            f"Industry: {brief.industry}",
            render_claims(
                state,
                reviewed_claim_ids(state),
                False,
                MAX_CONTEXT_CHARS["verifier"],
            ),
            render_findings(state, reviewed_only=True),
            render_sections(state.get("sections", [])),
            "\n".join(frozen_appendix(state)),
            "Check the exact draft: the sections above plus the "
            "limitations and coverage blocks are what delivery "
            "publishes; every factual sentence must be "
            "supported by the claims it cites (category unsupported when "
            "a sentence asserts more than its claims, or cites none, or "
            "cites a qualified claim without its qualification= "
            "restriction); "
            "conclusions must be consistent across text and tables "
            "(category contradiction); limitations must sit next to the "
            "claims they qualify; wording must be intelligible to a "
            "newcomer (category wording, minor). Give the section id and, "
            "where one applies, the claim id. Set consistent=false if any "
            "material issue exists. In retainable, list the section ids "
            "that would still be accurate on their own if the other "
            "sections were removed around them -- a section whose "
            "meaning depends on another section's text, or whose "
            "qualification sits elsewhere, does not belong there.",
        ]
    )
