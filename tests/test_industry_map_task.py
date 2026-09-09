"""The map task loses its own session, and what a failed one leaves.

Headline runs 4 and 5 both lost the dedicated map session to malformed
`StructuredOutput` JSON, rejected before schema validation: 54 turns,
42 tool calls, 26.70 minutes and ~117k output tokens across the two,
for zero admitted findings, while the ordinary tasks produced the map
anyway. Plan revision 35 §4.42 [D7].
"""

import test_industry_graph as harness
import test_industry_worker as worker_tests
from industry import graph as graph_module
from industry import merge
from industry import records
from industry import roles
from industry import worker as worker_module

LIMITS = records.Limits()


def test_scope_creates_no_map_session():
    # The dedicated session is gone: the first allocation owns the map.
    assert not hasattr(graph_module, "_map_task")


def test_the_first_allocation_owns_the_map(tmp_path):
    runtime, api, worker, compiled = harness.make(tmp_path)
    runtime.begin("m1")
    state = harness.run(
        compiled.ainvoke({"question": "q"}, harness.persist.thread_config("m1"))
    )
    tasks = list(state["tasks"].values())
    owner = tasks[0]
    assert owner.kind == "map"
    assert "boundary note" in owner.required_fields
    assert "segments" in owner.acceptance or "segment" in owner.acceptance
    # Exactly one worker session before the handoff plans the rest.
    assert worker.order[0] == f"{owner.id}.1"
    assert api.calls[1].startswith("plan:")


def test_the_handoff_plans_against_the_merged_map(tmp_path):
    runtime, api, _, compiled = harness.make(tmp_path)
    runtime.begin("m2")
    harness.run(
        compiled.ainvoke({"question": "q"}, harness.persist.thread_config("m2"))
    )
    # Two allocations: the map owner, then company work with the map in
    # hand. The second is the one added Lead call §4.42 costs.
    assert len([c for c in api.calls if c.startswith("plan:")]) == 2


def test_initial_allocation_is_one_slot_and_shared_by_studio():
    state = {"phase": "mapping", "tasks": {}}
    assert graph_module.initial_allocation(state)
    assert graph_module.planning_slots(state, LIMITS) == 1
    # Once an owner exists it is no longer the initial allocation, so
    # the handoff plans normally.
    with_owner = {"phase": "mapping", "tasks": {"T1": object()}}
    assert not graph_module.initial_allocation(with_owner)


def _result(status, error=None, findings=None, mapdraft=None):
    sid = "S1"
    return records.TaskResult(
        attempt_id="T1.1",
        task_id="T1",
        status=status,
        error=error,
        sources=[
            records.Source(
                id=sid,
                canonical_url="https://a.example/x",
                title="A",
                kind="web_page",
            )
        ],
        source_versions=[harness.version(sid)],
        evidence=[harness.passage("E1", sid, "掩模基板由信越化学供应。")],
        findings=findings or [],
        map=mapdraft,
        usage=records.Usage(turns=3, tool_calls=2, duration_s=1.0),
    )


def test_a_schema_failure_keeps_its_acquisitions_and_no_assertions(tmp_path):
    del tmp_path
    registry_state = {
        "tasks": {
            "T1": records.Task(
                id="T1", kind="map", role="industry", objective="o"
            )
        },
        "attempts": {
            "T1.1": records.Attempt(
                id="T1.1",
                task_id="T1",
                reserved=records.Reservation(
                    turns=10, tool_calls=24, seconds=900.0
                ),
                started_at=records.now_iso(),
            )
        },
    }
    failed = _result(
        "failed",
        error="schema: ResultError[error_max_structured_output_retries]",
        findings=[harness.finding_draft("不该被采纳的断言", ["product"], [1])],
        mapdraft=harness.map_draft(),
    )
    update = merge.merge_results(registry_state, [failed], LIMITS)
    # The pages it fetched survive as provenance.
    assert len(update["evidence"]) == 1
    assert len(update["sources"]) == 1
    # Its assertions do not, whatever the structured output carried.
    assert not update["claims"]
    assert not update.get("relationships")
    assert update["map"].segments == []
    # The task stays failed and is not re-queued.
    assert update["tasks"]["T1"].status == "failed"
    # And the recovery is auditable.
    found = merge.recovered_acquisitions(update["route_log"])
    assert list(found) == ["T1.1"]
    assert found["T1.1"] == sorted(update["evidence"])


def test_a_conflicting_version_takes_its_evidence_with_it():
    # Correction 3: reusing the registered version here would conceal
    # that the incoming record is a different one.
    sid = "S1"
    held = harness.version(sid)
    state = {
        "tasks": {
            "T1": records.Task(
                id="T1", kind="map", role="industry", objective="o"
            )
        },
        "attempts": {
            "T1.1": records.Attempt(
                id="T1.1",
                task_id="T1",
                reserved=records.Reservation(
                    turns=10, tool_calls=24, seconds=900.0
                ),
                started_at=records.now_iso(),
            )
        },
        "sources": {
            sid: records.Source(
                id=sid,
                canonical_url="https://a.example/x",
                title="A",
                kind="web_page",
                versions=[held.id],
            )
        },
        "source_versions": {held.id: held},
    }
    conflicting = held.model_copy(update={"content_hash": "different"})
    result = _result(
        "failed",
        error="schema: bad output",
    ).model_copy(update={"source_versions": [conflicting]})
    update = merge.merge_results(state, [result], LIMITS)
    assert not update["evidence"], "evidence on a rejected version survived"
    assert any("disagrees" in line for line in update["route_log"])
    assert merge.recovered_acquisitions(update["route_log"])["T1.1"] == []


def test_the_worker_prompt_shows_valid_json_and_forbids_xml():
    # The three shapes both runs actually emitted: XML-style tags, an
    # outer wrapper, and unescaped ASCII quotes inside `gaps`.
    work = worker_tests.work_input(kind="map")
    text = worker_module.user_prompt(work, None)
    assert "XML-style tags" in text
    assert '"summary"' in text and '"segments"' in text
    assert "escape every ASCII double quote" in text
    assert roles.PROMPT_VERSION == "10.3"
