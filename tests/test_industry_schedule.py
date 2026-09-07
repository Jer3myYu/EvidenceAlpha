"""Dependency validation and ready waves."""

from industry import records
from industry import schedule


def task(tid, deps=(), status="pending"):
    return records.Task(
        id=tid,
        kind="research",
        role="industry",
        objective=tid,
        depends_on=list(deps),
        status=status,
    )


def test_unknown_and_cyclic_dependencies_are_skipped():
    tasks = {
        "T1": task("T1"),
        "T2": task("T2", ["T9"]),
        "T3": task("T3", ["T4"]),
        "T4": task("T4", ["T3"]),
    }
    checked = schedule.validate(tasks)
    assert checked["T1"].status == "pending"
    assert checked["T2"].status == "skipped"
    assert "unknown dependency: T9" in str(checked["T2"].skip_reason)
    assert checked["T3"].status == checked["T4"].status == "skipped"
    assert checked["T3"].skip_reason == "cyclic dependency"


def test_waves_follow_completion_in_stable_order():
    tasks = {
        "T1": task("T1"),
        "T10": task("T10", ["T1"]),
        "T2": task("T2"),
        "T3": task("T3", ["T2", "T10"]),
    }
    _, wave = schedule.ready(tasks)
    assert [t.id for t in wave] == ["T1", "T2"]
    tasks["T1"] = task("T1", status="done")
    tasks["T2"] = task("T2", status="done")
    _, wave = schedule.ready(tasks)
    assert [t.id for t in wave] == ["T10"]
    tasks["T10"] = task("T10", ["T1"], status="done")
    _, wave = schedule.ready(tasks)
    assert [t.id for t in wave] == ["T3"]


def test_failed_prerequisite_skips_dependants_transitively():
    tasks = {
        "T1": task("T1", status="failed"),
        "T2": task("T2", ["T1"]),
        "T3": task("T3", ["T2"]),
        "T4": task("T4"),
    }
    updated, wave = schedule.ready(tasks)
    assert updated["T2"].status == "skipped"
    assert "T1" in updated["T2"].skip_reason
    assert updated["T3"].status == "skipped"
    assert [t.id for t in wave] == ["T4"]
