"""The ledger, admission rules, and the run meter."""

import threading

import pytest

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
        "single_calls": {
            "scope.1": records.Attempt(
                id="scope.1",
                task_id="scope",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(turns=5, duration_s=30),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
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
        model_call_reserve=20,
        tool_calls=150,
        wall_clock_s=5400,
        time_reserve_s=960,
        task_timeout_s=1200,
        concurrency=2,
    )
    empty = {"attempts": {}, "single_calls": {}}
    # executions 12; tools 150//24 = 6; time
    # (5400-960-2*480-180)//1200 = 2 full reservations after the three
    # downstream calls -- analyze, assess, and the pre-draft audit,
    # which reserves 180 s because it reads an outline. Time binds.
    assert limits.attempt_turns() == 34
    assert budget.dispatchable(empty, limits, keep_acquisition_slot=False) == 2
    assert budget.dispatchable(empty, limits, keep_acquisition_slot=True) == 2
    tight = records.Limits(
        **{
            **limits.model_dump(),
            "tool_calls": 1000,
            "model_calls": 1000,
            "wall_clock_s": 100000,
        }
    )
    # An open repair window holds back the execution and the tools its
    # pair will need as well as its seconds and turns (plan revision 39
    # §4.46.3), so the same ledger admits one fewer ordinary attempt
    # until the window closes.
    assert budget.dispatchable(empty, tight, keep_acquisition_slot=True) == 10
    closed = {**empty, "repair_window": "closed"}
    assert budget.dispatchable(closed, tight, keep_acquisition_slot=True) == 11


def test_reservations_never_exceed_the_limits_at_the_boundary():
    """The ledger's reservations and the limits share one contract."""
    limits = records.Limits(wall_clock_s=5400, time_reserve_s=960)
    n = budget.dispatchable({"attempts": {}}, limits, False)
    kept, _ = budget.pipeline_reserve({"attempts": {}}, limits, "research")
    reserved = n * limits.task_timeout_s
    assert reserved + limits.time_reserve_s + kept <= limits.wall_clock_s
    assert (n + 1) * limits.task_timeout_s + limits.time_reserve_s + kept > (
        limits.wall_clock_s
    )
    # A single call at the wall-clock boundary: with the reserve spent
    # to the second, an intermediate call is refused and a reserved
    # node gets a full call while two still fit.
    spent = records.Attempt(
        id="T1.1",
        task_id="T1",
        status="done",
        reserved=records.Reservation(turns=34, tool_calls=24, seconds=1200),
        observed=records.Usage(turns=10, duration_s=5400 - 960),
        started_at="2026-09-07T00:00:00+00:00",
    )
    state = {"attempts": {"T1.1": spent}, "single_calls": {}}
    assert budget.admit_single_call(state, limits, "analyze") == 0
    assert budget.admit_single_call(state, limits, "write") == 10
    almost = spent.model_copy(
        update={"observed": records.Usage(turns=10, duration_s=5400 - 479)}
    )
    state = {"attempts": {"T1.1": almost}, "single_calls": {}}
    assert budget.admit_single_call(state, limits, "write") == 0
    # Turns: the reserve holds exactly two full calls.
    turns = spent.model_copy(
        update={"observed": records.Usage(turns=200 - 20, duration_s=1.0)}
    )
    state = {"attempts": {"T1.1": turns}, "single_calls": {}}
    assert budget.admit_single_call(state, limits, "analyze") == 0
    assert budget.admit_single_call(state, limits, "write") == 10
    nearly = spent.model_copy(
        update={"observed": records.Usage(turns=200 - 9, duration_s=1.0)}
    )
    state = {"attempts": {"T1.1": nearly}, "single_calls": {}}
    assert budget.admit_single_call(state, limits, "write") == 0


def test_limits_reserves_must_hold_two_final_calls():
    with pytest.raises(ValueError):
        records.Limits(time_reserve_s=900)
    with pytest.raises(ValueError):
        records.Limits(model_call_reserve=12)
    legacy = records.Limits.model_validate({"expected_task_s": 600})
    assert not hasattr(legacy, "expected_task_s")


def test_no_attempt_starts_without_a_full_time_reservation():
    limits = records.Limits(wall_clock_s=5400, time_reserve_s=960)
    spent = {
        "attempts": {},
        "single_calls": {
            "w.1": records.Attempt(
                id="w.1",
                task_id="w",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(duration_s=4000),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
    }
    # 1400 s left, 440 after the reserve: no 1200 s reservation fits.
    assert budget.dispatchable(spent, limits, keep_acquisition_slot=False) == 0


def test_admit_single_call_intermediate_versus_reserved():
    limits = records.Limits(
        model_calls=20, model_call_reserve=12, turns_per_exchange=1
    )
    state = {
        "attempts": {},
        "single_calls": {
            "w.1": records.Attempt(
                id="w.1",
                task_id="w",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(turns=5),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
    }
    # 15 left; intermediate needs 5 after the 12 reserve: 3 < 5 -> skip.
    assert budget.admit_single_call(state, limits, "analyze") == 0
    assert budget.admit_single_call(state, limits, "write") == 5
    almost = {
        "attempts": {},
        "single_calls": {
            "w.1": records.Attempt(
                id="w.1",
                task_id="w",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(turns=18),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
    }
    assert budget.admit_single_call(almost, limits, "final_review") == 0
    out_of_time = {
        "attempts": {},
        "single_calls": {
            "w.1": records.Attempt(
                id="w.1",
                task_id="w",
                status="done",
                reserved=records.Reservation(
                    turns=5, tool_calls=0, seconds=480
                ),
                observed=records.Usage(duration_s=5400),
                started_at="2026-09-07T00:00:00+00:00",
            )
        },
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
        "single_calls": {},
    }
    assert runtime.meter_for("t") is None
    meter = runtime.new_meter("t", state)
    assert meter.global_remaining == 20
    assert runtime.meter_for("t") is meter
    runtime.drop("t")
    assert runtime.meter_for("t") is None


def test_begin_revokes_admissions_of_an_earlier_invocation():
    runtime = budget.Runtime(records.Limits())
    meter = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    meter.register("T1.1", 24)
    assert runtime.meter_for("t").is_admitted("T1.1")
    runtime.begin("t")  # the resume invocation starts
    assert runtime.meter_for("t") is None
    fresh = runtime.new_meter("t", {"attempts": {}, "single_calls": {}})
    assert not fresh.is_admitted("T1.1")


def test_reservations_are_in_sdk_turn_units():
    limits = records.Limits()
    assert budget.reservation_for(limits).turns == 34
    assert limits.single_call_reserved() == 10
    assert budget.max_turns_for(10, limits) == 5
    assert budget.max_turns_for(3, limits) == 1


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


def test_unknown_usage_with_a_measured_duration_charges_that_duration():
    failed = attempt(
        "T1.1", "failed", records.Usage(turns=0, duration_s=450.0, unknown=True)
    )
    charge = budget.attempt_charge(failed)
    assert (charge.turns, charge.tool_calls) == (12, 24)
    assert charge.duration_s == 450.0 and charge.unknown


def test_limits_reject_zero_divisors_and_incoherent_totals():
    for field in ("task_timeout_s", "tools_per_attempt", "turns_per_exchange"):
        with pytest.raises(ValueError):
            records.Limits(**{field: 0})
    with pytest.raises(ValueError):
        records.Limits(wall_clock_s=100, time_reserve_s=960)
    with pytest.raises(ValueError):
        records.Limits(model_calls=10, model_call_reserve=20)
    legacy = records.Limits.model_validate(
        {
            "material_claims": 80,
            "material_per_attempt": 15,
            "map_participants": 24,
        }
    )
    assert legacy.map_claims() == 28 and legacy.material_claims() == 64


def test_pipeline_reserve_keeps_time_for_review_analysis_and_assessment():
    limits = records.Limits(review_batch_s=240, single_call_timeout_s=480)
    claims = {
        f"C{n}": records.Claim(
            id=f"C{n}", statement="s", kind="fact", material=True
        )
        for n in range(25)
    }
    # The repair earmark rides with the two stages that could spend it
    # (plan revision 39 §4.46.3); closed, the reserve is what it was.
    state = {
        "attempts": {},
        "single_calls": {},
        "claims": claims,
        "repair_window": "closed",
    }
    # 25 unreviewed material claims = 3 batches; analyze, assess and the
    # pre-draft audit follow.
    seconds, turns = budget.pipeline_reserve(state, limits, "research")
    assert seconds == 3 * 240 + 2 * 480 + 180
    assert turns == 6 * limits.single_call_reserved()
    seconds, _ = budget.pipeline_reserve(state, limits, "review")
    assert seconds == 2 * 240 + 2 * 480 + 180  # admitted batch excluded
    assert budget.pipeline_reserve(state, limits, "analyze") == (
        480 + 180,
        20,
    )
    # Assessment can no longer take the last discretionary call: the
    # audit still has to run after it (U1-N03).
    assert budget.pipeline_reserve(state, limits, "assess_coverage") == (
        180,
        10,
    )
    assert budget.pipeline_reserve(state, limits, "audit_findings") == (0, 0)
    # Research dispatch keeps that time: with 5400 s and the 960 s
    # reserve, 5400 - 960 - 1860 = 2580 s admits 2 attempts of 900 s,
    # not the 4 that fit without the pipeline reserve.
    assert budget.dispatchable(state, limits, False) == 2
    empty = {
        "attempts": {},
        "single_calls": {},
        "claims": {},
        "repair_window": "closed",
    }
    assert budget.dispatchable(empty, limits, False) == 3  # (4440-960)//900
    # With the window open, one repair pair is held back from both.
    held_s, held_turns = budget.repair_pair_cost(limits)
    for stage in ("research", "review"):
        was = budget.pipeline_reserve(state, limits, stage)
        now = budget.pipeline_reserve(
            {**state, "repair_window": "open"}, limits, stage
        )
        assert now == (was[0] + held_s, was[1] + held_turns)
    assert budget.pipeline_reserve(
        {**state, "repair_window": "open"}, limits, "analyze"
    ) == (480 + 180, 20)


def test_review_is_refused_when_analysis_could_not_follow():
    limits = records.Limits()
    spent = records.Attempt(
        id="T1.1",
        task_id="T1",
        status="done",
        reserved=records.Reservation(turns=34, tool_calls=24, seconds=900),
        observed=records.Usage(turns=10, duration_s=5400 - 960 - 480 * 2),
        started_at="2026-09-07T00:00:00+00:00",
    )
    state = {"attempts": {"T1.1": spent}, "single_calls": {}, "claims": {}}
    # Exactly analyze + assess + audit fit after the reserve: no review
    # batch.
    assert budget.admit_single_call(state, limits, "review") == 0
    assert budget.admit_single_call(state, limits, "analyze") == 0
    assert budget.admit_single_call(state, limits, "assess_coverage") == 10
    assert budget.admit_single_call(state, limits, "audit_findings") == 10
