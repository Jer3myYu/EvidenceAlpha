"""Trace lines for the CLI: one short line per completed node.

Every line is derived from the node's update and the state after it,
with the budget read through ``budget.ledger`` so the CLI and Studio
never disagree about what a run has spent.
"""

from typing import Any

from industry import budget
from industry import state as state_module


def budget_line(state: state_module.IndustryState, limits: Any) -> str:
    """The ledger in one line."""
    spent = budget.ledger(state)
    return (
        f"budget: {spent.task_executions}/{limits.task_executions} tasks, "
        f"{spent.turns}/{limits.model_calls} turns, "
        f"{spent.tool_calls}/{limits.tool_calls} tools, "
        f"{spent.wall_clock_s / 60:.0f}/{limits.wall_clock_s / 60:.0f} min"
        + (
            f", {spent.unknown_attempts} unknown"
            if spent.unknown_attempts
            else ""
        )
    )


def render_update(
    node: str, update: dict[str, Any], state: state_module.IndustryState
) -> list[str]:
    """Lines for one completed node (``state`` may predate the update)."""
    state = {**state, **update}
    lines: list[str] = []
    upper = node.upper()
    if node.startswith("reserve_"):
        return [f"{upper}: {line}" for line in update.get("route_log", [])]
    if node == "scope":
        brief = update.get("brief")
        if brief:
            lines.append(
                f"SCOPE: {brief.industry} ({brief.language}, {brief.mode})"
            )
    elif node == "dispatch":
        started = [
            line for line in update.get("route_log", []) if "admitted" in line
        ]
        lines.append(f"DISPATCH: {len(started)} attempts started")
    elif node == "run_task":
        for result in update.get("task_results", []):
            lines.append(
                f"TASK {result.attempt_id}: {result.status}, "
                f"{len(result.evidence)} evidence, "
                f"{len(result.findings)} findings, "
                f"{result.usage.turns} turns"
                + (f" ({result.error})" if result.error else "")
            )
    elif node == "merge":
        claims = len(state.get("claims", {}))
        evidence = len(state.get("evidence", {}))
        sources = len(state.get("sources", {}))
        relationships = len(state.get("relationships", {}))
        lines.append(
            f"MERGE: {claims} claims, {evidence} evidence, {sources} sources, "
            f"{relationships} relationships"
        )
    elif node == "assess_coverage":
        lines.append(
            "COVERAGE: "
            + ", ".join(
                f"Q{c.question}={c.status}" for c in update.get("coverage", [])
            )
        )
    elif node == "deliver":
        meta = update.get("meta")
        if meta:
            lines.append(f"DELIVER: {meta.report_status} -> {meta.report_path}")
    else:
        for line in update.get("route_log", []):
            if line.startswith(f"{node}:"):
                lines.append(f"{upper}: {line[len(node) + 1:].strip()}")
    for line in update.get("route_log", []):
        if line.startswith(
            ("remediate", "resume", "dispatch:")
        ) and node not in ("dispatch",):
            lines.append(f"ROUTE: {line}")
    return lines
