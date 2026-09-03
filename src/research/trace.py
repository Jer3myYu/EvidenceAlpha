"""Render the workflow's completed node updates as short trace lines.

The graph streams one ``{node: update}`` per completed node
(``stream_mode="updates"``). ``render_update`` turns one such update
into the lines a person wants to see while the run is in progress:
the node's result and, where it follows from the update alone, the
next action. It reads counts, the verdict, the gap sentences, and the
route; prompts, observations, answers, and state never pass through it.
"""

from typing import Any

from research import workflow


def render_update(
    node: str, update: dict[str, Any], research_round: int
) -> list[str]:
    """Trace lines for one completed node.

    Args:
      node: The node that completed: ``plan``, ``research``,
        ``evaluate``, ``finish``, or ``verify``.
      update: What the node returned.
      research_round: Rounds completed so far, from the latest research
        update; the evaluate lines need it to render the route.

    Returns:
      The lines to print, in order. Empty for an unknown node.
    """
    if node == "plan":
        chosen = update["research_plan"].chosen()
        outcome = (
            f"approach {chosen.label} selected"
            if chosen
            else "no tree-of-thought"
        )
        return [f"PLAN: {outcome}", "RESEARCH ROUND 1"]
    if node == "research":
        count = len(update["evidence"])
        completed = update["research_round"]
        return [f"RESEARCH ROUND {completed}: {count} observations"]
    if node == "evaluate":
        sufficient = update["evidence_sufficient"]
        verdict = "sufficient" if sufficient else "insufficient"
        lines = [f"EVALUATE: {verdict}"]
        if update["evidence_gaps"]:
            lines.append("GAPS:")
            lines.extend(f"- {gap}" for gap in update["evidence_gaps"])
        route = workflow.route_after_evaluate(
            {
                "evidence_sufficient": sufficient,
                "research_round": research_round,
            }
        )
        lines.append(f"ROUTE: {route}")
        if route == "research":
            lines.append(f"RESEARCH ROUND {research_round + 1}")
        return lines
    if node == "finish":
        return ["FINISH"]
    if node == "verify":
        issues = update["citation_issues"]
        if not issues:
            return ["VERIFY: no citation issues"]
        lines = [f"VERIFY: {len(issues)} citation issues", "ISSUES:"]
        lines.extend(f"- {issue}" for issue in issues)
        return lines
    return []
