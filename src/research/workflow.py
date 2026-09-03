"""Explicit research workflow on LangGraph with one follow-up round.

LangGraph owns the workflow level: which stage runs next and what state
moves between stages. The Research Agent (``research.agent``) keeps the
tool-use level: which tool to call, in what order, and when to answer.
Neither layer makes the other's decisions.

Phase 6.3 adds the loop::

    START -> plan -> research -> evaluate -+- sufficient -----> finish -> END
                        ^                  +- insufficient, round 1 --+
                        +---------------------------------------------+
                                           +- insufficient, round 2 -> finish

Evidence and answers accumulate across rounds through LangGraph's
``operator.add`` reducer: a research round returns only its new items.
Before they enter state, a round's observations are relabelled with
stable source ids (``research.sources``), so the evaluator, the
follow-up round, and the synthesis all cite ``[S#]``.
The finish node synthesises one answer from everything and, when the
loop ended insufficient, appends the evaluator's unresolved gaps.

The node functions are plain async functions over ``ResearchState``
and are parameters of ``build_graph`` so tests can pass fakes.

Phase 7 adds one optional ``checkpointer``. With it, LangGraph stores
the state after every completed node under the caller's thread id
(``research.persist``), so an interrupted run resumes at the node that
did not finish and a completed run can be reopened. Without it the
graph is exactly the Phase 6 graph.

Phase 8 adds ``verify`` after ``finish``: the synthesised answer is
checked independently of the call that wrote it (``research.verify``).
Citations are checked deterministically, then one structured call
judges claims, conflicts, and source quality. When that finds a
problem, ``finish`` runs once more as a revision with the findings and
``verify`` checks the result; the second verification always ends the
run. Problems that remain are disclosed at the end of the answer in
Python, like the gaps::

    finish -> verify -+- clean, or revision_round == 1 ---------> END
                ^     +- problems and revision_round == 0 -+
                +-----------------------------------------+

Verification never starts another research round.

Phase 9 changes no edge, state, or router: the single-call nodes run
their model call as a CrewAI crew of one agent and one task
(``research.crew``), each agent carrying the stage's existing system
prompt and each task the stage's existing prompt text. The research
node still calls the Claude Agent SDK Research Agent directly.
"""

import operator
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from research import agent
from research import crew
from research import plan as plan_module
from research import sources as sources_module
from research import verify as verify_module

# Round 1 is the initial research, round 2 the one follow-up.
MAX_RESEARCH_ROUNDS = 2
# One revision of the synthesis when verification finds a problem.
MAX_REVISIONS = 1


class ResearchState(TypedDict, total=False):
    """Workflow state; each node fills only the keys it owns.

    Attributes:
      question: The user's question (input).
      research_plan: The planning call's result, unchanged.
      evidence: Every tool observation from every round, in order, with
        source labels rewritten to ``[S#]``. Appended by the reducer; a
        node returns only new items.
      sources: The source registry, ``[S#]`` id to record. Replaced
        whole by the research node.
      answers: One agent answer per research round, in order. Appended
        by the reducer.
      research_round: How many research rounds have completed.
      evidence_sufficient: The latest evaluator verdict.
      evidence_gaps: The latest evaluator gaps; empty if sufficient.
      synthesis: The synthesis text alone, what verification checks.
      final_answer: The answer returned by the workflow: the synthesis,
        then the unresolved gaps, then the verification notes, each
        block only when it applies.
      revision_round: How many revisions of the synthesis have run.
      citation_issues: Invalid citations found in ``synthesis``.
      verification: The verifier's judgement of ``synthesis``.
    """

    question: str
    research_plan: plan_module.ResearchPlan
    evidence: Annotated[list[str], operator.add]
    sources: dict[str, sources_module.SourceRecord]
    answers: Annotated[list[str], operator.add]
    research_round: int
    evidence_sufficient: bool
    evidence_gaps: list[str]
    synthesis: str
    final_answer: str
    revision_round: int
    citation_issues: list[str]
    verification: verify_module.Verification


NodeFunction = Callable[[ResearchState], Awaitable[dict[str, Any]]]


async def plan_node(state: ResearchState) -> dict[str, Any]:
    """Run the existing planning call on the question."""
    return {"research_plan": await crew.plan(state["question"])}


async def research_node(state: ResearchState) -> dict[str, Any]:
    """Run the agent for one round; a follow-up sees prior evidence and gaps."""
    completed = state.get("research_round", 0)
    if completed == 0:
        prompt = agent.research_prompt(
            state["question"], state["research_plan"]
        )
    else:
        prompt = agent.followup_prompt(
            state["question"],
            state["research_plan"],
            state["evidence"],
            state["evidence_gaps"],
        )
    result = await agent.research(prompt)
    evidence, sources = sources_module.normalize_observations(
        result.observations, state.get("sources", {})
    )
    return {
        "evidence": evidence,
        "sources": sources,
        "answers": [result.answer],
        "research_round": completed + 1,
    }


async def evaluate_node(state: ResearchState) -> dict[str, Any]:
    """Evaluate all accumulated evidence against the latest answer."""
    verdict = await crew.evaluate(
        state["question"],
        state["research_plan"],
        state["answers"][-1],
        state["evidence"],
    )
    return {
        "evidence_sufficient": verdict.sufficient,
        "evidence_gaps": verdict.gaps,
    }


def route_after_evaluate(state: ResearchState) -> str:
    """Return ``"finish"`` or ``"research"`` from the latest verdict."""
    if state["evidence_sufficient"]:
        return "finish"
    if state["research_round"] >= MAX_RESEARCH_ROUNDS:
        return "finish"
    return "research"


def format_unresolved_gaps(gaps: list[str]) -> str:
    """Render the evaluator's gaps as a numbered block under a fixed heading.

    The wording is kept; the only changes are numbering and whitespace
    normalisation.

    Args:
      gaps: The evaluator's gap sentences.

    Returns:
      The block, or an empty string if there are no gaps.
    """
    if not gaps:
        return ""
    lines = "\n".join(
        f"{number}. {normalised}"
        for number, normalised in enumerate(
            (" ".join(gap.split()) for gap in gaps), start=1
        )
    )
    return f"Unresolved evidence gaps:\n{lines}"


async def finish_node(state: ResearchState) -> dict[str, Any]:
    """Synthesise one answer from every round, then disclose open gaps.

    After a verification, the same call revises the previous synthesis
    with the verifier's findings instead; the evidence stays the
    observations.
    """
    verification = state.get("verification")
    if verification is None:
        draft = findings = None
        revision_round = 0
    else:
        draft = state["synthesis"]
        findings = verify_module.format_verification_notes(
            state["citation_issues"], verification
        )
        revision_round = state["revision_round"] + 1
    answer = await crew.report(
        state["question"],
        state["research_plan"],
        state["answers"],
        state["evidence"],
        draft,
        findings,
    )
    final_answer = answer
    block = format_unresolved_gaps(state["evidence_gaps"])
    if block and not state["evidence_sufficient"]:
        final_answer = f"{answer}\n\n{block}"
    return {
        "synthesis": answer,
        "final_answer": final_answer,
        "revision_round": revision_round,
    }


async def verify_node(state: ResearchState) -> dict[str, Any]:
    """Check the synthesis: citations in Python, then the verifier call."""
    citation_issues = verify_module.check_citations(
        state["synthesis"], state["sources"]
    )
    verification = await crew.verify(
        state["question"],
        state["synthesis"],
        state["evidence"],
        state["sources"],
    )
    update = {"citation_issues": citation_issues, "verification": verification}
    notes = verify_module.format_verification_notes(
        citation_issues, verification
    )
    if notes:
        update["final_answer"] = state["final_answer"] + "\n\n" + notes
    return update


def route_after_verify(state: ResearchState) -> str:
    """Return ``"revise"`` or ``"end"`` from the latest verification."""
    problems = verify_module.list_issues(
        state["citation_issues"], state["verification"]
    )
    if not problems or state["revision_round"] >= MAX_REVISIONS:
        return "end"
    return "revise"


def build_graph(
    plan: NodeFunction = plan_node,
    research: NodeFunction = research_node,
    evaluate: NodeFunction = evaluate_node,
    finish: NodeFunction = finish_node,
    verify: NodeFunction = verify_node,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the graph with the evaluate loop and the verify loop.

    Args:
      plan: Node filling ``research_plan``.
      research: Node adding ``evidence`` and ``answers`` and setting
        ``sources`` and ``research_round``.
      evaluate: Node filling ``evidence_sufficient`` and ``evidence_gaps``.
      finish: Node filling ``synthesis``, ``final_answer``, and
        ``revision_round``.
      verify: Node filling ``citation_issues`` and ``verification`` and
        appending the verification notes to ``final_answer``.
      checkpointer: Where LangGraph saves the state after each node.
        ``None`` (the default) keeps every run in memory and anonymous.

    Returns:
      The compiled graph; run it with ``await graph.ainvoke({"question":
      ...})``. With a checkpointer, every call also needs
      ``persist.thread_config(thread_id)`` as its config.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("plan", plan)
    graph.add_node("research", research)
    graph.add_node("evaluate", evaluate)
    graph.add_node("finish", finish)
    graph.add_node("verify", verify)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"finish": "finish", "research": "research"},
    )
    graph.add_edge("finish", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, {"revise": "finish", "end": END}
    )
    return graph.compile(checkpointer=checkpointer)
