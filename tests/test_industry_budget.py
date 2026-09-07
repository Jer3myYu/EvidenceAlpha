"""The ledger, admission rules, and the run meter."""

import threading

from industry import budget
from industry import records


def attempt(aid, status="running", observed=None, duration=None):
    return records.Attempt(
        id=aid,
        task_id=aid.split(".")[0],
        status=status,
        reserved=records.Reservation(turns=12, tool_calls=24, seconds=1200),
        observed=observed,
        started_at="2026-09-07T00:00:00+00:00",
        duration_s=duration,
    )


def test_ledger_charges_reservation_until_observed():
    state = {
        "attempts": {
            "T1.1": attempt(
                "T1.1",
                "done",
                records.Usage(turns=4, tool_calls=3, duration_s=90),
            ),
            "T2.1": attempt("T2.1"),  # running: reserved
            "T3.1": attempt("T3.1", "unknown"),
        },
        "usage_events": [records.Usage(turns=5, duration_s=30, node="scope")],
    }
    spent = budget.ledger(state)
    assert spent.turns == 4 + 12 + 12 + 5
    assert spent.tool_calls == 3 + 24 + 24
    assert spent.wall_clock_s == 90 + 1200 + 1200 + 30
    assert spent.task_executions == 3 and spent.unknown_attempts == 2


def test_ledger_counts_each_attempt_once():
    state = {
        "attempts": {
            "T1.1": attempt("T1.1", "done", records.Usage(turns=2)),
        },
        "task_results": [
            records.TaskResult(
                attempt_id="T1.1",
                task_id="T1",
                status="done",
                usage=records.Usage(turns=2),
            )
        ],
    }
    assert budget.ledger(state).turns == 2


def test_dispatchable_respects_every_limit_and_reserve():
    limits = records.Limits(
        task_executions=12,
        model_calls=200,
        model_call_reserve=12,
        tool_calls=150,
        wall_clock_s=5400,
        time_reserve_s=900,
        expected_task_s=600,
        concurrency=2,
    )
    empty = {"attempts": {}, "usage_events": []}
    # executions 12; turns (200-12)//12 = 15; tools 150//24 = 6;
    # time (5400-900)/600 = 7 waves * 2 = 14. Tools bind.
    assert budget.dispatchable(empty, limits, keep_acquisition_slot=False) == 6
    assert budget.dispatchable(empty, limits, keep_acquisition_slot=True) == 6
    tight = records.Limits(**{**limits.model_dump(), "tool_calls": 1000})
    assert budget.dispatchable(empty, tight, keep_acquisition_slot=True) == 11
    spent = {
        "attempts": {},
        "usage_events": [records.Usage(duration_s=4000)],
    }
    # 1400 s left, 500 after reserve: no full wave fits.
    assert budget.dispatchable(spent, tight, keep_acquisition_slot=False) == 0


def test_admit_single_call_intermediate_versus_reserved():
    limits = records.Limits(model_calls=20, model_call_reserve=12)
    state = {"attempts": {}, "usage_events": [records.Usage(turns=5)]}
    # 15 left; intermediate needs 5 after the 12 reserve: 3 < 5 -> skip.
    assert budget.admit_single_call(state, limits, "analyze") == 0
    assert budget.admit_single_call(state, limits, "write") == 5
    almost = {"attempts": {}, "usage_events": [records.Usage(turns=18)]}
    assert budget.admit_single_call(almost, limits, "final_review") == 2
    out_of_time = {
        "attempts": {},
        "usage_events": [records.Usage(duration_s=5400)],
    }
    assert budget.admit_single_call(out_of_time, limits, "write") == 0


def test_meter_bounds_per_attempt_and_global():
    meter = budget.RunMeter(global_tool_calls=3)
    meter.register("T1.1", 2)
    meter.register("T2.1", 2)
    assert not meter.is_admitted("T9.1")
    assert meter.admit("T1.1") and meter.admit("T1.1")
    assert not meter.admit("T1.1")  # per-attempt allowance spent
    assert meter.admit("T2.1")
    assert not meter.admit("T2.1")  # global spent
    assert meter.counts("T1.1") == (2, 1)
    assert meter.counts("T2.1") == (1, 1)
    assert meter.global_remaining == 0


def test_meter_is_thread_safe_under_contention():
    meter = budget.RunMeter(global_tool_calls=50)
    meter.register("T1.1", 100)
    meter.register("T2.1", 100)
    admitted = []

    def worker(aid):
        for _ in range(40):
            if meter.admit(aid):
                admitted.append(aid)

    threads = [
        threading.Thread(target=worker, args=(a,)) for a in ("T1.1", "T2.1")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(admitted) == 50


def test_runtime_rebuilds_meter_from_ledger():
    runtime = budget.Runtime(records.Limits(tool_calls=30))
    state = {
        "attempts": {
            "T1.1": attempt("T1.1", "done", records.Usage(tool_calls=10))
        },
        "usage_events": [],
    }
    assert runtime.meter_for("t") is None
    meter = runtime.new_meter("t", state)
    assert meter.global_remaining == 20
    assert runtime.meter_for("t") is meter
    runtime.drop("t")
    assert runtime.meter_for("t") is None


def test_begin_revokes_admissions_of_an_earlier_invocation():
    runtime = budget.Runtime(records.Limits())
    meter = runtime.new_meter("t", {"attempts": {}, "usage_events": []})
    meter.register("T1.1", 24)
    assert runtime.meter_for("t").is_admitted("T1.1")
    runtime.begin("t")  # the resume invocation starts
    assert runtime.meter_for("t") is None
    fresh = runtime.new_meter("t", {"attempts": {}, "usage_events": []})
    assert not fresh.is_admitted("T1.1")


def test_unknown_observed_usage_charges_the_reservation():
    failed = attempt("T1.1", "failed", records.Usage(turns=0, unknown=True))
    charge = budget.attempt_charge(failed)
    assert (charge.turns, charge.tool_calls, charge.duration_s) == (
        12,
        24,
        1200,
    )
    assert charge.unknown
    single = {
        "attempts": {},
        "single_calls": {
            "scope.1": records.Attempt(
                id="scope.1",
                task_id="scope",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
    }
    assert budget.ledger(single).turns == 5
