"""Task dependency scheduling: validation and ready waves. Pure.

Tasks form a DAG through ``depends_on``. ``validate`` skips tasks whose
dependencies are unknown or cyclic; ``ready`` returns the pending tasks
whose dependencies are all done, in stable id order, and skips those
whose dependencies failed or were skipped, so a failed prerequisite
never leaves a dependant waiting forever.
"""

import re

from industry import records


def task_number(task_id: str) -> int:
    """The number in a task id such as ``T12``, for stable ordering."""
    match = re.search(r"(\d+)", task_id)
    return int(match.group(1)) if match else 0


def _skip(task: records.Task, reason: str) -> records.Task:
    return task.model_copy(update={"status": "skipped", "skip_reason": reason})


def validate(tasks: dict[str, records.Task]) -> dict[str, records.Task]:
    """Skip pending tasks with unknown or cyclic dependencies.

    Args:
      tasks: The task registry.

    Returns:
      A new registry; every other task is unchanged.
    """
    updated = dict(tasks)
    for task in tasks.values():
        if task.status != "pending":
            continue
        unknown = [dep for dep in task.depends_on if dep not in tasks]
        if unknown:
            missing = ", ".join(unknown)
            updated[task.id] = _skip(task, f"unknown dependency: {missing}")
            continue
        if task.kind == "acquisition" and task.target is None:
            # Plan revision 38 §4.45.2: prose is never the only link
            # between a repair and the record it repairs.
            updated[task.id] = _skip(task, "an acquisition names no target")
    for task_id in _cyclic(updated):
        task = updated[task_id]
        if task.status == "pending":
            updated[task_id] = _skip(task, "cyclic dependency")
    return updated


def _cyclic(tasks: dict[str, records.Task]) -> list[str]:
    """Ids of tasks that lie on a dependency cycle."""
    on_cycle: set[str] = set()
    state: dict[str, int] = {}  # 0 unvisited, 1 on stack, 2 done
    stack: list[str] = []

    def visit(task_id: str) -> None:
        state[task_id] = 1
        stack.append(task_id)
        for dep in tasks[task_id].depends_on:
            if dep not in tasks:
                continue
            if state.get(dep, 0) == 1:
                on_cycle.update(stack[stack.index(dep) :])
            elif state.get(dep, 0) == 0:
                visit(dep)
        stack.pop()
        state[task_id] = 2

    for task_id in sorted(tasks, key=task_number):
        if state.get(task_id, 0) == 0:
            visit(task_id)
    return sorted(on_cycle, key=task_number)


def ready(
    tasks: dict[str, records.Task],
) -> tuple[dict[str, records.Task], list[records.Task]]:
    """Find the pending tasks that may run now; skip the blocked ones.

    A pending task whose dependencies are all ``done`` is ready. One with
    a ``failed`` or ``skipped`` dependency is skipped with the reason,
    and that skip propagates to its own dependants in the same call.

    Args:
      tasks: A validated registry.

    Returns:
      The updated registry and the ready tasks in stable id order.
    """
    updated = dict(tasks)
    changed = True
    while changed:
        changed = False
        for task in list(updated.values()):
            if task.status != "pending":
                continue
            blocked = [
                dep
                for dep in task.depends_on
                if updated[dep].status in ("failed", "skipped")
            ]
            if blocked:
                names = ", ".join(blocked)
                updated[task.id] = _skip(
                    task, f"dependency not completed: {names}"
                )
                changed = True
    ready_tasks = [
        task
        for task in sorted(updated.values(), key=lambda t: task_number(t.id))
        if task.status == "pending"
        and all(updated[dep].status == "done" for dep in task.depends_on)
    ]
    return updated, ready_tasks


def target_capacity(limits: records.Limits) -> int:
    """How many named targets one attempt can plausibly evidence."""
    return max(1, limits.tools_per_attempt // limits.tools_per_target)


def decompose(targets: list[str], limits: records.Limits) -> list[list[str]]:
    """Split a task's targets into chunks one session can actually do.

    Run 7's first task requested nine areas and at least ten companies
    in one session with a 24-call tool allowance. Nothing checked that
    before dispatch, so the session did what it could and the plan's
    stated scope silently became a fiction (plan D-U5).

    Deterministic: the order the Lead gave is preserved, so a replay
    decomposes identically.
    """
    size = target_capacity(limits)
    return [targets[i : i + size] for i in range(0, len(targets), size)] or [[]]
