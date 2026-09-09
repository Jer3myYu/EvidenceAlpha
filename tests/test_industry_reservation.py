"""The write/final-review pair and the retained delivery candidate.

Headline live run 5 (thread `37d841ac`) produced 98 claims, 29
relationships, 12 analysis findings and all eight questions at least
`partial`, and shipped nothing. `write.3` replaced a deliverable body
and `reserve_final_review` was then refused by 21.678 s. The reserve
was always documented as holding two complete calls; it never held the
second one. Plan revision 35 §4.41 [D6].
"""

import test_industry_graph as harness
from industry import budget
from industry import graph as graph_module
from industry import records
from research import persist

NOW = "2026-09-07T00:00:00+00:00"


def _call(node, number, *, held=False, pair=None, status="running"):
    return records.Attempt(
        id=f"{node}.{number}",
        task_id=node,
        status=status,
        reserved=records.Reservation(
            turns=10, tool_calls=0, seconds=480.0, pair_id=pair, held=held
        ),
        started_at=NOW,
    )


def _spent(seconds, turns=0):
    """A state whose ledger has already consumed `seconds`."""
    return {
        "single_calls": {
            "spent.1": records.Attempt(
                id="spent.1",
                task_id="scope",
                status="done",
                reserved=records.Reservation(
                    turns=turns, tool_calls=0, seconds=seconds
                ),
                observed=records.Usage(
                    turns=turns, tool_calls=0, duration_s=seconds
                ),
                started_at=NOW,
            )
        }
    }


def test_a_write_needs_its_review_to_fit_too():
    # The run-5 boundary: 707.808 s remained before write.3. One call
    # (480 s) fitted, so the write was admitted and the review was then
    # refused by 21.678 s. A pair needs 960 s.
    limits = records.Limits()
    assert budget.admit_pair(_spent(5400.0 - 707.808), limits) == 0
    assert (
        budget.admit_single_call(_spent(5400.0 - 707.808), limits, "write") > 0
    )
    # With the pair's worth left, both fit.
    assert budget.admit_pair(_spent(5400.0 - 960.0), limits) > 0
    assert budget.admit_pair(_spent(5400.0 - 959.9), limits) == 0


def test_the_pair_is_admitted_together_and_the_review_is_held():
    limits = records.Limits()
    reserve_write = graph_module.reserve_node("write", limits)
    update = harness.run(reserve_write({}))
    calls = update["single_calls"]
    writer = calls["write.1"]
    review = calls["final_review.1"]
    assert writer.reserved.pair_id == "write.1"
    assert review.reserved.pair_id == "write.1"
    assert review.reserved.held and not writer.reserved.held
    # Held capacity is charged from the moment it is taken, so nothing
    # else can spend it.
    assert budget.ledger(update).turns == 20


def test_the_held_review_is_activated_not_charged_again():
    limits = records.Limits()
    state = harness.run(graph_module.reserve_node("write", limits)({}))
    before = budget.ledger(state).turns
    update = harness.run(
        graph_module.reserve_node("final_review", limits)(state)
    )
    calls = update["single_calls"]
    assert not calls["final_review.1"].reserved.held
    assert "final_review.2" not in calls
    assert budget.ledger(update).turns == before


def test_a_write_that_cannot_be_paired_is_refused():
    limits = records.Limits()
    state = _spent(5400.0 - 707.808)
    update = harness.run(graph_module.reserve_node("write", limits)(state))
    assert "single_calls" not in update
    assert "reviewed body stands" in update["route_log"][0]


def test_an_issue_resolved_against_a_later_draft_still_applies_here():
    # The retained body keeps its own dispositions: a later draft's
    # clean review can resolve wording that still stands in this one.
    section = records.Section(
        id="intro", title="t", text="未获支持的一句。", claim_ids=[]
    )
    issue = records.Issue(
        id="I1",
        key="unsupported:intro#1",
        category="unsupported",
        severity="material",
        target="intro",
        requested_action="edit",
        description="unsupported",
        text="未获支持的一句。",
        draft_version=1,
    )
    candidate = records.DeliveryCandidate(
        sections=[section],
        subject=records.ReviewSubject(digest="d"),
        draft_version=1,
        issues={"I1": issue},
    )
    resolved_elsewhere = issue.model_copy(
        update={"status": "resolved", "draft_version": 2}
    )
    applies = graph_module.issues_for_candidate(
        candidate, {"I1": resolved_elsewhere}
    )
    assert applies["I1"].status == "open"
    # A resolution recorded against *this* draft does clear it.
    resolved_here = issue.model_copy(
        update={"status": "resolved", "draft_version": 1}
    )
    applies = graph_module.issues_for_candidate(
        candidate, {"I1": resolved_here}
    )
    assert applies["I1"].status == "resolved"


def test_a_new_issue_applies_only_when_its_unit_is_in_the_retained_body():
    section = records.Section(
        id="intro", title="t", text="保留下来的一句。", claim_ids=[]
    )
    candidate = records.DeliveryCandidate(
        sections=[section],
        subject=records.ReviewSubject(digest="d"),
        draft_version=1,
    )

    def _issue(text):
        return records.Issue(
            id="I9",
            key="unsupported:intro#9",
            category="unsupported",
            severity="material",
            target="intro",
            requested_action="edit",
            description="d",
            text=text,
            draft_version=2,
        )

    assert "I9" in graph_module.issues_for_candidate(
        candidate, {"I9": _issue("保留下来的一句。")}
    )
    assert "I9" not in graph_module.issues_for_candidate(
        candidate, {"I9": _issue("只在新草稿里的一句。")}
    )


def test_the_incumbent_wins_ties():
    assert graph_module.level_rank("verified") > graph_module.level_rank(
        "partial"
    )
    assert graph_module.level_rank("partial") > graph_module.level_rank(
        "diagnostic_only"
    )


def test_the_pair_survives_a_checkpoint_round_trip():
    held = _call("final_review", 1, held=True, pair="write.1")
    payload = persist.SERIALIZER.dumps_typed(held)
    back = persist.SERIALIZER.loads_typed(payload)
    assert back.reserved.held and back.reserved.pair_id == "write.1"
    assert back.status == "running"
