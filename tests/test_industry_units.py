"""The complete U2-03 failure family over declared, reviewed occurrences."""

import asyncio

import pytest

import test_industry_graph as graph_fixtures

from industry import graph
from industry import merge
from industry import pdf
from industry import records
from industry import report
from industry import report_units
from industry import roles

P = "This market has no competing suppliers."
PRICE = "Therefore suppliers can dictate prices."
PAY = "| Contract terms | Payment is due on acceptance. |"
WARRANTY = "| Warranty | Warranty claims remain valid after acceptance. |"
ROW = f"| {P} | Suppliers can dictate prices. |"


def unit(key, text, deps=(), *, kind="paragraph", prefix="\n\n", table=None):
    """An explicit fixture declaration, with no dependency inference."""
    return roles.BlockSpec(
        key=key,
        text=text,
        kind=kind,
        prefix=prefix,
        claim_ids=[],
        depends_on=list(deps) if deps is not None else None,
        container_id=table,
    )


def table(key, *, premise=None, warranty=False):
    """Two independent fixture rows sharing declared header dependencies."""
    structural = [f"{key}_h", f"{key}_r"]
    rows = [
        unit(
            structural[0],
            "| Basis | Implication |",
            kind="header",
            table=key,
            prefix="\n\n",
        ),
        unit(structural[1], "|---|---|", kind="rule", table=key, prefix="\n"),
        unit(
            f"{key}_bad",
            ROW,
            structural + ([premise] if premise else []),
            kind="row",
            table=key,
            prefix="\n",
        ),
        unit(f"{key}_pay", PAY, structural, kind="row", table=key, prefix="\n"),
    ]
    if warranty:
        rows.append(
            unit(
                f"{key}_w",
                WARRANTY,
                structural,
                kind="row",
                table=key,
                prefix="\n",
            )
        )
    return rows


def section(key, items):
    """Build a section specification with an exact rendered projection."""
    return roles.SectionSpec(
        id=key,
        title=key,
        blocks=items,
        text="".join(b.prefix + b.text for b in items),
    )


def state_for(specs, *, prior=(), version=1):
    """A frozen reviewer-approved fixture, before introducing objections."""
    sections = report_units.build(specs, list(prior), version, set())
    state = {
        "brief": records.Brief(industry="fixture", language="en"),
        "sections": sections,
        "claims": {},
        "issues": {},
        "draft_version": version,
    }
    state["review_subject"] = report.review_subject(state, [])
    state["final_review"] = records.DraftReview(
        units=[
            records.UnitReview(
                block_id=b.id,
                version=b.version,
                supported=True,
                dependencies_complete=True,
                reason="fixture independently supported",
            )
            for s in sections
            for b in s.blocks
        ],
        retainable=[s.id for s in sections],
    )
    return state


def object_to(state, key, text):
    """Attach the root objection, leaving closure to the delivery gate."""
    issue = records.Issue(
        id="I1",
        key="issue",
        category="unsupported",
        severity="material",
        target=key,
        requested_action="remove",
        text=text,
        draft_version=state["draft_version"],
    )
    state["issues"] = {issue.id: issue}
    return report.plan_delivery(state, "[X]")


def body(plan):
    """Return the delivered body only."""
    return "\n".join(s.text for s in plan.sections)


@pytest.mark.parametrize("case", ["A1", "A2", "A3"])
def test_baseline_counterexamples(case):
    if case == "A1":
        state = state_for(
            [
                section(
                    "s",
                    [
                        unit("good", "A good sentence.", prefix=""),
                        unit("bad", "A bad sentence.", prefix=" "),
                        unit("context", "More context.", prefix=" "),
                        unit("independent", "Therefore X."),
                    ],
                )
            ]
        )
        result = object_to(state, "s", "A bad sentence.")
        assert "A good sentence. [X] More context." in body(result)
        assert "Therefore X." in body(result)
    elif case == "A2":
        for text in (None, "stale wording", "foreign block"):
            state = state_for([section("s", [unit("good", "Good.")])])
            assert object_to(state, "s", text).removed == ["s"]
    else:
        state = state_for([section("s", table("t")[:-1])])
        assert object_to(state, "s", ROW).removed == ["s"]


@pytest.mark.parametrize("case", ["B1", "B2", "B3", "B4", "B5", "C1"])
def test_dependency_counterexamples_together(case):
    items = [unit("p", P, prefix="")]
    if case == "B1":
        items += [unit("price", PRICE, ["p"])]
    elif case == "B2":
        items += [
            unit("price", f"Therefore: {P} Prices are dictated.", ["p"]),
            unit("margin", "Accordingly margins expand.", ["price"]),
        ]
    elif case == "B3":
        items += [
            unit("repeat", f"Separately, {P}", ["p"]),
            unit("price", PRICE, ["repeat"]),
        ]
    elif case == "B4":
        items += table("t", premise="p")
    else:
        items = [unit("price", PRICE, ["t1_bad"], prefix="")]
        items += table("t1", warranty=case == "C1") + table("t2")
    state = state_for([section("s", items)])
    result = object_to(state, "s", ROW if case in ("B5", "C1") else P)
    assert not result.removed
    text = body(result)
    for rejected in (
        P,
        "dictate prices",
        "Prices are dictated",
        "margins expand",
    ):
        assert rejected not in text
    if case in ("B4", "B5", "C1"):
        assert PAY in text
    if case == "C1":
        assert WARRANTY in text and text.count(PAY) == 2


def test_c2_independent_leading_conclusion_survives():
    conclusion = (
        "Therefore warranty claims remain valid after acceptance: "
        "the signed contract explicitly preserves those rights."
    )
    state = state_for(
        [
            section(
                "s",
                [
                    unit("conclusion", conclusion),
                    unit("bad", "- Separately, " + P, kind="list_item"),
                    unit(
                        "pay",
                        "- Payment is due on acceptance.",
                        kind="list_item",
                    ),
                ],
            )
        ]
    )
    result = object_to(state, "s", "- Separately, " + P)
    assert conclusion in body(result) and "Payment is due" in body(result)
    assert P not in body(result)


def test_c3_tables_do_not_create_positional_edges():
    # Different later wording ensures only the later table is objected.
    specs = [
        section(
            "s",
            [unit("conclusion", PRICE, ["t1_pay"])] + table("t1") + table("t2"),
        )
    ]
    specs[0].blocks[-2].text = "| Later premise | Later conclusion |"
    specs[0].text = "".join(b.prefix + b.text for b in specs[0].blocks)
    state = state_for(specs)
    result = object_to(state, "s", specs[0].blocks[-2].text)
    assert PRICE in body(result) and ROW in body(result)


@pytest.mark.parametrize("case", ["D1", "D2", "D3"])
def test_unit_identity_counterexamples(case):
    first, other = {
        "D1": ("| A | 1 |", "| A | 1 | estimate |"),
        "D2": ("- Capacity: 10", "- Capacity: 100 units"),
        "D3": ("Bad sentence.", "Bad sentence. Further unsupported wording."),
    }[case]
    if case == "D1":
        first_table, second_table = table("t"), table("t")
        first_table[2].text, second_table[2].text = first, other
        specs = [section("a", first_table), section("b", second_table)]
    else:
        kind = "list_item" if case == "D2" else "paragraph"
        specs = [
            section("a", [unit("x", first, kind=kind)]),
            section("b", [unit("y", other, kind=kind)]),
        ]
    state = state_for(specs)
    result = object_to(state, "a", first)
    assert other in body(result)
    if case == "D3":
        state["issues"]["I2"] = state["issues"]["I1"].model_copy(
            update={"id": "I2", "target": "b", "text": other}
        )
        assert "Bad sentence" not in body(report.plan_delivery(state, "[X]"))


@pytest.mark.parametrize("case", ["E1", "E2", "E3", "E4"])
def test_retained_candidate_counterexamples(case):
    old = state_for([section("intro", [unit("p", P), unit("x", PRICE, ["p"])])])
    candidate = records.DeliveryCandidate(
        sections=old["sections"],
        subject=old["review_subject"],
        review=old["final_review"],
        draft_version=1,
    )
    issue = records.Issue(
        id="I1",
        key="k",
        category="unsupported",
        severity="material",
        target="intro" if case == "E3" else "new_intro",
        requested_action="remove",
        text="new wording" if case in ("E2", "E3") else P,
        draft_version=2,
    )
    if case == "E4":
        issue = issue.model_copy(
            update={"status": "resolved", "resolved_by_draft": 3}
        )
    old["issues"] = graph.issues_for_candidate(candidate, {"I1": issue})
    result = report.plan_delivery(old, "[X]")
    if case == "E3":
        assert P in body(result) and PRICE in body(result)
    else:
        assert P not in body(result) and PRICE not in body(result)


def test_cross_section_forward_dependency_and_unknown_scope():
    state = state_for(
        [
            section("conclusion", [unit("x", PRICE, ["premise:p"])]),
            section(
                "premise", [unit("p", P), unit("independent", "Unrelated.")]
            ),
            section("unknown", [unit("u", "Unresolved scope.", None)]),
        ]
    )
    result = object_to(state, "premise", P)
    assert PRICE not in body(result) and "Unrelated." in body(result)
    assert "unknown" in result.removed and result.changed


def test_editor_independence_is_not_semantic_approval():
    state = state_for([section("s", [unit("p", P), unit("false", PRICE)])])
    verdicts = state["final_review"].units
    verdicts[1] = verdicts[1].model_copy(
        update={"dependencies_complete": False}
    )
    assert object_to(state, "s", P).removed == ["s"]
    state["final_review"] = records.DraftReview()
    assert report.plan_delivery(state, "[X]").removed == ["s"]


@pytest.mark.parametrize("deps", [["missing"], ["self"], ["self", "self"]])
def test_invalid_references_never_become_independence(deps):
    with pytest.raises(ValueError):
        state_for([section("s", [unit("self", "Text.", deps)])])


def test_dependency_change_invalidates_version_and_transitive_approval():
    specs = [
        section("a", [unit("p", P), unit("other", "Independent.")]),
        section("b", [unit("x", PRICE, ["a:p"])]),
    ]
    old = state_for(specs)
    specs[0].blocks[0].text = "Competition exists."
    specs[0].text = "".join(b.prefix + b.text for b in specs[0].blocks)
    new = state_for(specs, prior=old["sections"], version=2)
    new["review_subject"] = old["review_subject"]
    new["final_review"] = old["final_review"]
    assert report.accepted_units(new) == {"a:other"}
    assert new["sections"][0].blocks[0].version == 2
    assert not report.certificate_applies(new)


def test_unknown_dependencies_are_not_backfilled_for_legacy():
    old = records.Section(id="s", title="Old", text=f"{P}\n\n{PRICE}")
    assert report.blocks_of(old) == []


def test_changed_unit_recheck_carries_only_exact_independent_judgments(
    tmp_path,
):
    specs = [
        section("a", [unit("p", P), unit("other", "Independent.")]),
        section("b", [unit("x", PRICE, ["a:p"])]),
    ]
    old = state_for(specs)
    specs[0].blocks[0].text = "Competition exists."
    specs[0].text = "".join(b.prefix + b.text for b in specs[0].blocks)
    current = state_for(specs, prior=old["sections"], version=2)
    current["review_subject"] = old["review_subject"]
    current["final_review"] = old["final_review"]
    current["single_calls"] = {
        "final_review.1": records.Attempt(
            id="final_review.1",
            task_id="final_review",
            started_at=records.now_iso(),
            reserved=records.Reservation(turns=10, tool_calls=0, seconds=480),
        )
    }
    _, api, _, compiled = graph_fixtures.make(tmp_path)
    seen = []

    async def review(state, max_turns, deadline):
        del max_turns, deadline
        seen.extend(state["review_subject"].targets)
        # One target is omitted: it must not inherit approval.
        return (
            records.DraftReview(
                units=[
                    records.UnitReview(
                        block_id="a:p",
                        version=2,
                        supported=True,
                        dependencies_complete=True,
                        reason="reviewed changed premise",
                    )
                ]
            ),
            graph_fixtures.USAGE,
        )

    api.final_review = review
    update = asyncio.run(
        compiled.nodes["final_review"].node.steps[0].afunc(current)
    )
    assert seen == ["a:p", "b:x"]
    merged = {**current, **update}
    assert report.accepted_units(merged) == {"a:p", "a:other"}
    plan = report.plan_delivery(merged, "[X]")
    assert "b" in plan.removed
    assert "Independent." in body(plan)


def test_stale_version_cannot_bind_an_objection_to_current_wording(tmp_path):
    state = state_for(
        [section("s", [unit("p", P), unit("other", "Independent.")])]
    )
    state["single_calls"] = {
        "final_review.1": records.Attempt(
            id="final_review.1",
            task_id="final_review",
            started_at=records.now_iso(),
            reserved=records.Reservation(turns=10, tool_calls=0, seconds=480),
        )
    }
    _, api, _, compiled = graph_fixtures.make(tmp_path)

    async def review(current, max_turns, deadline):
        del max_turns, deadline
        return (
            records.DraftReview(
                issues=[
                    records.SectionIssue(
                        section_id="s",
                        category="unsupported",
                        severity="material",
                        description="stale target",
                        block_id="s:p",
                        block_version=0,
                    )
                ],
                units=current["final_review"].units,
                consistent=False,
            ),
            graph_fixtures.USAGE,
        )

    api.final_review = review
    update = asyncio.run(
        compiled.nodes["final_review"].node.steps[0].afunc(state)
    )
    assert report.plan_delivery({**state, **update}, "[X]").removed == ["s"]


def reviewed_update(state, tmp_path, outcome):
    """Exercise the actual final-review boundary without model usage."""
    state["single_calls"] = {
        "final_review.1": records.Attempt(
            id="final_review.1",
            task_id="final_review",
            started_at=records.now_iso(),
            reserved=records.Reservation(turns=10, tool_calls=0, seconds=480),
        )
    }
    _, api, _, compiled = graph_fixtures.make(tmp_path)

    async def review(current, max_turns, deadline):
        del current, max_turns, deadline
        return outcome, graph_fixtures.USAGE

    api.final_review = review
    update = asyncio.run(
        compiled.nodes["final_review"].node.steps[0].afunc(state)
    )
    return {**state, **update}


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("duplicate", [False, True])
def test_contextual_rejection_overrides_inherited_approval(
    tmp_path, changed, duplicate
):
    specs = [section("s", [unit("p", P), unit("good", "Independent.")])]
    old = state_for(specs)
    current = dict(old)
    if changed:
        current = state_for(
            specs + [section("new", [unit("x", "New independent wording.")])],
            prior=old["sections"],
            version=2,
        )
        current["review_subject"] = old["review_subject"]
        current["final_review"] = old["final_review"]
    reject = records.UnitReview(
        block_id="s:p",
        version=1,
        supported=False,
        dependencies_complete=True,
        reason="contextual unsupported assertion",
    )
    verdicts = [reject]
    if duplicate:
        verdicts.append(reject.model_copy(update={"supported": True}))
    current = reviewed_update(
        current, tmp_path, records.DraftReview(units=verdicts)
    )
    assert "s:p" not in report.accepted_units(current)
    plan = report.plan_delivery(current, "[X]")
    assert P not in body(plan) and not plan.certified
    if not duplicate:
        assert "Independent." in body(plan)


@pytest.mark.parametrize("target_version", [1, 3])
def test_reintroduced_key_never_reuses_old_identity(tmp_path, target_version):
    old = state_for([section("s", [unit("p", P), unit("good", "Good.")])])
    middle = state_for(
        [section("s", [unit("good", "Good.")])],
        prior=old["sections"],
        version=2,
    )
    current = state_for(
        [
            section(
                "s",
                [unit("p", "New supported wording."), unit("good", "Good.")],
            )
        ],
        prior=middle["sections"],
        version=3,
    )
    assert current["sections"][0].blocks[0].version == 3
    outcome = records.DraftReview(
        units=current["final_review"].units,
        issues=[
            records.SectionIssue(
                section_id="s",
                block_id="s:p",
                block_version=target_version,
                category="unsupported",
                severity="material",
                description="objection",
            )
        ],
    )
    plan = report.plan_delivery(
        reviewed_update(current, tmp_path, outcome), "[X]"
    )
    if target_version == 1:
        assert plan.removed == ["s"]
    else:
        assert "Good." in body(plan) and "New supported" not in body(plan)


def test_retained_candidate_cannot_evade_new_dependency_scope_objection(
    tmp_path,
):
    old = state_for([section("s", [unit("p", P), unit("conclusion", PRICE)])])
    candidate = records.DeliveryCandidate(
        sections=old["sections"],
        subject=old["review_subject"],
        review=old["final_review"],
        draft_version=1,
    )
    current = state_for(
        [section("s", [unit("p", P), unit("conclusion", PRICE, None)])],
        prior=old["sections"],
        version=2,
    )
    current["review_subject"] = old["review_subject"]
    current["final_review"] = old["final_review"]
    current = reviewed_update(
        current,
        tmp_path,
        records.DraftReview(
            units=[
                records.UnitReview(
                    block_id="s:conclusion",
                    version=2,
                    supported=False,
                    dependencies_complete=False,
                    reason="unknown premises",
                )
            ]
        ),
    )
    old["issues"] = graph.issues_for_candidate(candidate, current["issues"])
    plan = report.plan_delivery(old, "[X]")
    assert plan.removed == ["s"] and not plan.certified


def test_citation_defect_targets_stored_owner_and_preserves_independent_unit():
    state = state_for(
        [
            section(
                "s",
                [
                    unit("bad", "Capacity is 10. It is growing."),
                    unit(
                        "dependent",
                        "Therefore capacity is sufficient.",
                        ["bad"],
                    ),
                    unit("good", "Independent supported warranty terms."),
                ],
            )
        ]
    )
    for problem in report.check_citations(state["sections"], {}):
        state["issues"], _ = merge.open_issue(
            state["issues"],
            "unsupported",
            "material",
            problem.section_id,
            "edit",
            problem.description,
            draft_version=1,
            text=problem.text,
        )
    plan = report.plan_delivery(state, "[X]")
    assert not plan.removed
    assert "Capacity" not in body(plan) and "Therefore" not in body(plan)
    assert "Independent supported warranty terms." in body(plan)


@pytest.mark.parametrize("position", [1, 2, 3])
@pytest.mark.parametrize("separator", ["", "\n\n"])
def test_table_declarations_must_match_physical_rendering(position, separator):
    rows = table("t")
    rows[position].prefix = separator
    with pytest.raises(ValueError, match="exactly one newline"):
        state_for([section("s", rows)])


def test_reviewer_receives_versions_dependencies_and_actual_table_projection():
    state = state_for([section("s", table("t"))])
    text = roles.final_review_description(state)
    assert state["sections"][0].text in text
    assert "version=1; kind=row" in text
    assert "premises=['s:t_h', 's:t_r']" in text
    html = pdf.markdown_to_html(state["sections"][0].text)
    assert html.count("<table>") == 1


def test_empty_table_does_not_take_supported_independent_prose_with_it():
    state = state_for(
        [
            section(
                "s",
                table("t")[:-1]
                + [
                    unit("independent", "Independent supported warranty terms.")
                ],
            )
        ]
    )
    plan = object_to(state, "s", ROW)
    assert not plan.removed
    assert "Independent supported warranty terms." in body(plan)
    assert P not in body(plan) and "|" not in body(plan)


def test_distinct_table_containers_require_a_rendered_boundary():
    second = table("second")
    second[0].prefix = "\n"
    with pytest.raises(ValueError, match="distinct line boundary"):
        state_for([section("s", table("first") + second)])


def test_rejected_declared_claim_removes_only_its_explicit_consumers():
    state = state_for(
        [
            section(
                "s",
                [
                    unit("p", P),
                    unit("dependent", PRICE, ["p"]),
                    unit(
                        "independent", "Independent supported warranty terms."
                    ),
                ],
            )
        ]
    )
    owner = state["sections"][0]
    owner.blocks[0].text += " [C1]"
    owner.blocks[0].sha256 = report_units.digest(owner.blocks[0].text)
    owner.blocks[0].claim_ids = ["C1"]
    owner.claim_ids = ["C1"]
    owner.text = report_units.render(owner.blocks)
    state["claims"] = {
        "C1": records.Claim(
            id="C1",
            statement=P,
            kind="fact",
            review="supported",
        )
    }
    state["review_subject"] = report.review_subject(state, [])
    state["claims"]["C1"].review = "unsupported"
    plan = report.plan_delivery(state, "[X]")
    assert not plan.removed
    assert P not in body(plan) and PRICE not in body(plan)
    assert "Independent supported warranty terms." in body(plan)


@pytest.mark.parametrize("header", ["FY2025 terms", "WarrantyCorp"])
def test_structural_headers_survive_but_uncited_numeric_rows_do_not(header):
    rows = table("t", warranty=True)
    rows[0].text = f"| Basis | {header} |"
    rows[2].text = "| Capacity | 10 units |"
    state = state_for([section("s", rows)])
    problems = report.check_citations(state["sections"], {}, ["WarrantyCorp"])
    assert len(problems) == 1 and problems[0].text == rows[2].text
    for problem in problems:
        state["issues"], _ = merge.open_issue(
            state["issues"],
            "unsupported",
            "material",
            problem.section_id,
            "edit",
            problem.description,
            draft_version=1,
            text=problem.text,
        )
    plan = report.plan_delivery(state, "[X]")
    assert rows[0].text in body(plan) and not plan.removed
    assert PAY in body(plan) and WARRANTY in body(plan)
    assert "10 units" not in body(plan)


def test_structural_header_citations_still_require_valid_claims():
    rows = table("t")
    rows[0].text = "| Basis [C99] | Terms |"
    state = state_for([section("s", rows)])
    problems = report.check_citations(state["sections"], {})
    assert len(problems) == 1
    assert problems[0].text == rows[0].text
    assert "unknown claim C99" in problems[0].description
