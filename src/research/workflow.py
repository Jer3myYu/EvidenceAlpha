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
The finish node synthesises one answer from everything and, when the
loop ended insufficient, appends the evaluator's unresolved gaps.

The node functions are plain async functions over ``ResearchState``
and are parameters of ``build_graph`` so tests can pass fakes.
"""

import operator
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from research import agent
from research import evaluate as evaluate_module
from research import plan as plan_module
from research import synthesize as synthesize_module

# Round 1 is the initial research, round 2 the one follow-up.
MAX_RESEARCH_ROUNDS = 2


class ResearchState(TypedDict, total=False):
    """Workflow state; each node fills only the keys it owns.

    Attributes:
      question: The user's question (input).
      research_plan: The planning call's result, unchanged.
      evidence: Every tool observation from every round, verbatim, in
        order. Appended by the reducer; a node returns only new items.
      answers: One agent answer per research round, in order. Appended
        by the reducer.
      research_round: How many research rounds have completed.
      evidence_sufficient: The latest evaluator verdict.
      evidence_gaps: The latest evaluator gaps; empty if sufficient.
      final_answer: The answer returned by the workflow.
    """

    question: str
    research_plan: plan_module.ResearchPlan
    evidence: Annotated[list[str], operator.add]
    answers: Annotated[list[str], operator.add]
    research_round: int
    evidence_sufficient: bool
    evidence_gaps: list[str]
    final_answer: str


NodeFunction = Callable[[ResearchState], Awaitable[dict[str, Any]]]


async def plan_node(state: ResearchState) -> dict[str, Any]:
    """Run the existing planning call on the question."""
    return {"research_plan": await plan_module.plan_research(state["question"])}


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
    return {
        "evidence": result.observations,
        "answers": [result.answer],
        "research_round": completed + 1,
    }


async def evaluate_node(state: ResearchState) -> dict[str, Any]:
    """Evaluate all accumulated evidence against the latest answer."""
    verdict = await evaluate_module.evaluate_evidence(
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
    """Synthesise one answer from every round, then disclose open gaps."""
    answer = await synthesize_module.synthesize(
        state["question"],
        state["research_plan"],
        state["answers"],
        state["evidence"],
    )
    block = format_unresolved_gaps(state["evidence_gaps"])
    if state["evidence_sufficient"] or not block:
        return {"final_answer": answer}
    return {"final_answer": f"{answer}\n\n{block}"}


def build_graph(
    plan: NodeFunction = plan_node,
    research: NodeFunction = research_node,
    evaluate: NodeFunction = evaluate_node,
    finish: NodeFunction = finish_node,
) -> CompiledStateGraph:
    """Compile the graph with the evaluate -> research / finish loop.

    Args:
      plan: Node filling ``research_plan``.
      research: Node adding ``evidence`` and ``answers`` and setting
        ``research_round``.
      evaluate: Node filling ``evidence_sufficient`` and ``evidence_gaps``.
      finish: Node filling ``final_answer``.

    Returns:
      The compiled graph; run it with ``await graph.ainvoke({"question":
      ...})``.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("plan", plan)
    graph.add_node("research", research)
    graph.add_node("evaluate", evaluate)
    graph.add_node("finish", finish)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"finish": "finish", "research": "research"},
    )
    graph.add_edge("finish", END)
    return graph.compile()
