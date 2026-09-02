"""Explicit research workflow on LangGraph: plan -> research -> finish.

LangGraph owns the workflow level: which stage runs next and what state
moves between stages. The Research Agent (``research.agent``) keeps the
tool-use level: which tool to call, in what order, and when to answer.
Neither layer makes the other's decisions.

Phase 6.1 is the linear graph::

    START -> plan -> research -> finish -> END

The three node functions are plain async functions over ``ResearchState``
and are parameters of ``build_graph`` so tests can pass fakes.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from research import agent
from research import plan as plan_module


class ResearchState(TypedDict, total=False):
    """Workflow state; each node fills only the keys it owns.

    Attributes:
      question: The user's question (input).
      research_plan: The planning call's result, unchanged.
      evidence: Every tool observation the agent saw, verbatim, in order.
      answer: The agent's answer for the research round.
      final_answer: The answer returned by the workflow.
    """

    question: str
    research_plan: plan_module.ResearchPlan
    evidence: list[str]
    answer: str
    final_answer: str


NodeFunction = Callable[[ResearchState], Awaitable[dict[str, Any]]]


async def plan_node(state: ResearchState) -> dict[str, Any]:
    """Run the existing planning call on the question."""
    return {"research_plan": await plan_module.plan_research(state["question"])}


async def research_node(state: ResearchState) -> dict[str, Any]:
    """Run the existing Research Agent once with the selected approach."""
    prompt = agent.research_prompt(state["question"], state["research_plan"])
    result = await agent.research(prompt)
    return {"answer": result.answer, "evidence": result.observations}


async def finish_node(state: ResearchState) -> dict[str, Any]:
    """Pass the agent's answer through unchanged (Phase 6.1)."""
    return {"final_answer": state["answer"]}


def build_graph(
    plan: NodeFunction = plan_node,
    research: NodeFunction = research_node,
    finish: NodeFunction = finish_node,
) -> CompiledStateGraph:
    """Compile ``START -> plan -> research -> finish -> END``.

    Args:
      plan: Node filling ``research_plan``.
      research: Node filling ``answer`` and ``evidence``.
      finish: Node filling ``final_answer``.

    Returns:
      The compiled graph; run it with ``await graph.ainvoke({"question":
      ...})``.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("plan", plan)
    graph.add_node("research", research)
    graph.add_node("finish", finish)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "finish")
    graph.add_edge("finish", END)
    return graph.compile()
