"""Render the workflow's completed node updates as short trace lines.

The graph streams one ``{node: update}`` per completed node
(``stream_mode="updates"``). ``render_update`` turns one such update
into the lines a person wants to see while the run is in progress:
the node's result and, where it follows from the update alone, the
next action. It reads counts, verdicts, the gap and issue sentences,
and the route; prompts, observations, answers, and state never pass
through it.
"""

from typing import Any

from research import verify
from research import workflow


def render_update(
    node: str,
    update: dict[str, Any],
    research_round: int,
    revision_round: int = 0,
) -> list[str]:
    """Trace lines for one completed node.

    Args:
      node: The node that completed: ``plan``, ``research``,
        ``evaluate``, ``finish``, or ``verify``.
      update: What the node returned.
      research_round: Rounds completed so far, from the latest research
        update; the evaluate lines need it to render the route.
      revision_round: Revisions completed so far, from the latest finish
        update; the verify lines need it to render the route.

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
        revision = update["revision_round"]
        return [f"FINISH: revision {revision}" if revision else "FINISH"]
    if node == "verify":
        verification = update["verification"]
        verdicts = [check.verdict for check in verification.claims]
        counts = ", ".join(
            f"{verdicts.count(verdict)} {verdict}"
            for verdict in ("supported", "unsupported", "contradicted")
            if verdict in verdicts
        )
        summary = f"{len(verdicts)} claims" + (f": {counts}" if counts else "")
        lines = [f"VERIFY: {summary}"]
        issues = verify.list_issues(update["citation_issues"], verification)
        if issues:
            lines.append("ISSUES:")
            lines.extend(f"- {issue}" for issue in issues)
        route = workflow.route_after_verify(
            {
                "citation_issues": update["citation_issues"],
                "verification": verification,
                "revision_round": revision_round,
            }
        )
        lines.append(f"ROUTE: {route}")
        if route == "revise":
            lines.append(f"REVISION: {revision_round + 1}")
        return lines
    return []
