"""Deterministic calculations and their validation."""

import pytest

import quantity_support as support
from industry import calc
from industry import merge
from industry import quantities
from industry import records


def cinput(cid, value, unit="亿元", period="2024", scope=None):
    quantity = support.bound(value, unit, "E1", period=period, scope=scope)
    return records.CalcInput(claim_id=cid, claim_version=1, quantity=quantity)


def test_parse_period_forms():
    assert calc.parse_period("2024").key() == (2024, "year", 1, False)
    assert calc.parse_period("FY2024").key() == (2024, "year", 1, True)
    assert calc.parse_period("2024年").key() == (2024, "year", 1, False)
    assert calc.parse_period("2024H1").key() == (2024, "half", 1, False)
    assert calc.parse_period("2023Q3").key() == (2023, "quarter", 3, False)
    with pytest.raises(calc.CalcError, match="unparseable_period"):
        calc.parse_period("last year")
    with pytest.raises(calc.CalcError, match="unparseable_period"):
        calc.parse_period(None)


def test_growth_derives_years_from_periods():
    inputs = {
        "C1": cinput("C1", 100, period="2020"),
        "C2": cinput("C2", 200, period="2024"),
    }
    request = records.CalcRequest(
        kind="growth", label="cagr", start_claim_id="C1", end_claim_id="C2"
    )
    result = calc.compute("K1", request, inputs)
    assert result.status == "ok"
    assert result.result == pytest.approx(18.9207, abs=1e-3)
    assert quantities.render(result.unit) == "%/year"
    assert "1/4" in result.formula


@pytest.mark.parametrize(
    "start,end,code",
    [
        (("2024", False), ("2023", False), "period_order"),
        (("2023", False), ("2024H1", False), "incomparable_periods"),
        (("FY2023", False), ("2024", False), "incomparable_periods"),
        (("2023H1", False), ("2024H2", False), "incomparable_periods"),
    ],
)
def test_growth_rejects_incomparable_periods(start, end, code):
    inputs = {
        "C1": cinput("C1", 100, period=start[0]),
        "C2": cinput("C2", 120, period=end[0]),
    }
    request = records.CalcRequest(
        kind="growth", label="g", start_claim_id="C1", end_claim_id="C2"
    )
    result = calc.compute("K1", request, inputs)
    assert result.status == "error" and code in str(result.message)


def test_growth_half_year_to_half_year_is_one_year():
    inputs = {
        "C1": cinput("C1", 100, period="2023H1"),
        "C2": cinput("C2", 110, period="2024H1"),
    }
    request = records.CalcRequest(
        kind="growth", label="g", start_claim_id="C1", end_claim_id="C2"
    )
    assert calc.compute("K1", request, inputs).result == pytest.approx(10.0)


def test_share_and_ratio_need_same_period_and_scope():
    inputs = {
        "C1": cinput("C1", 30, scope="中国"),
        "C2": cinput("C2", 120, scope="全球"),
        "C3": cinput("C3", 120, period="2023"),
        "C4": cinput("C4", 120, scope="中国"),
    }
    share = records.CalcRequest(
        kind="share",
        label="s",
        numerator_claim_id="C1",
        denominator_claim_id="C2",
    )
    result = calc.compute("K1", share, inputs)
    assert result.status == "error" and "misaligned_inputs" in str(
        result.message
    )
    aligned = share.model_copy(update={"denominator_claim_id": "C4"})
    result = calc.compute("K2", aligned, inputs)
    assert result.status == "ok" and result.result == 25.0
    assert result.unit == quantities.atom("%")
    period_mismatch = share.model_copy(update={"denominator_claim_id": "C3"})
    assert calc.compute("K3", period_mismatch, inputs).status == "error"
    explained = period_mismatch.model_copy(
        update={"alignment_note": "denominator is the latest full year"}
    )
    result = calc.compute("K4", explained, inputs)
    assert result.status == "ok" and result.alignment_note


def test_ratio_units_and_denominator():
    inputs = {
        "C1": cinput("C1", 50, unit="亿元"),
        "C2": cinput("C2", 10, unit="万平方米"),
        "C3": cinput("C3", 0, unit="万平方米"),
    }
    ratio = records.CalcRequest(
        kind="ratio",
        label="r",
        numerator_claim_id="C1",
        denominator_claim_id="C2",
    )
    result = calc.compute("K1", ratio, inputs)
    assert result.status == "ok"
    # The quotient keeps both operands whole: no simplification.
    assert result.unit == quantities.divide(
        support.unit("亿元"), support.unit("万平方米")
    )
    assert quantities.render(result.unit) == "亿元/万m²"
    zero = ratio.model_copy(update={"denominator_claim_id": "C3"})
    assert "non_positive_denominator" in str(
        calc.compute("K2", zero, inputs).message
    )
    unit_mismatch = records.CalcRequest(
        kind="share",
        label="s",
        numerator_claim_id="C1",
        denominator_claim_id="C2",
    )
    assert "unit_mismatch" in str(
        calc.compute("K3", unit_mismatch, inputs).message
    )


def test_a_quotient_of_a_quotient_keeps_its_grouping():
    # C1 round 6, finding 3: 52 USD / 1 kg/day and 52 USD/kg / 1 day
    # both emitted "USD/kg/day" and a share over the two returned 100%.
    per_day = cinput("C1", 1, unit="kg/day")
    usd = cinput("C2", 52, unit="USD")
    usd_per_kg = cinput("C3", 52, unit="USD/kg")
    day = cinput("C4", 1, unit="day")
    inputs = {"C1": per_day, "C2": usd, "C3": usd_per_kg, "C4": day}
    first = calc.compute(
        "K1",
        records.CalcRequest(
            kind="ratio",
            label="a",
            numerator_claim_id="C2",
            denominator_claim_id="C1",
        ),
        inputs,
    )
    second = calc.compute(
        "K2",
        records.CalcRequest(
            kind="ratio",
            label="b",
            numerator_claim_id="C3",
            denominator_claim_id="C4",
        ),
        inputs,
    )
    assert quantities.render(first.unit) == "USD/(kg/day)"
    assert quantities.render(second.unit) == "USD/kg/day"
    assert first.unit != second.unit
    # A share over the two different dimensions refuses.
    # A derived input carries the producer behind its figure, as
    # `inputs_from_claims` copies it, so two results can be told apart.
    derived = {
        "K1": records.CalcInput(
            claim_id="D1",
            claim_version=1,
            quantity=records.Quantity(
                value=first.result, unit=first.unit, binding=None
            ),
            source_calculation_id="K1",
            source_calculation_version=1,
        ),
        "K2": records.CalcInput(
            claim_id="D2",
            claim_version=1,
            quantity=records.Quantity(
                value=second.result, unit=second.unit, binding=None
            ),
            source_calculation_id="K2",
            source_calculation_version=1,
        ),
    }
    share = calc.compute(
        "K3",
        records.CalcRequest(
            kind="share",
            label="s",
            numerator_claim_id="K1",
            denominator_claim_id="K2",
        ),
        derived,
    )
    assert share.status == "error" and "unit_mismatch" in str(share.message)


def test_missing_quantity_is_an_error_not_a_guess():
    request = records.CalcRequest(
        kind="ratio",
        label="r",
        numerator_claim_id="C1",
        denominator_claim_id="C9",
    )
    result = calc.compute("K1", request, {"C1": cinput("C1", 1)})
    assert result.status == "error" and "missing_quantity" in str(
        result.message
    )


@pytest.mark.parametrize(
    "start,end,code",
    [
        (100, -100, "non_positive_end"),
        (100, 0, "non_positive_end"),
        (float("nan"), 100, "non_finite_start"),
        (100, float("inf"), "non_finite_end"),
    ],
)
def test_growth_rejects_non_positive_or_non_finite_values(start, end, code):
    inputs = {
        "C1": cinput("C1", start, period="2020"),
        "C2": cinput("C2", end, period="2022"),
    }
    request = records.CalcRequest(
        kind="growth", label="g", start_claim_id="C1", end_claim_id="C2"
    )
    result = calc.compute("K1", request, inputs)
    assert result.status == "error" and code in str(result.message)


def test_equivalent_period_labels_are_the_same_period():
    inputs = {
        "C1": cinput("C1", 30, period="2024"),
        "C2": cinput("C2", 120, period="2024年"),
        "C3": cinput("C3", 120, period="FY2024"),
    }
    share = records.CalcRequest(
        kind="share",
        label="s",
        numerator_claim_id="C1",
        denominator_claim_id="C2",
    )
    assert calc.compute("K1", share, inputs).status == "ok"
    fiscal = share.model_copy(update={"denominator_claim_id": "C3"})
    assert calc.compute("K2", fiscal, inputs).status == "error"


def test_inputs_are_preserved_copies_of_citable_claims():
    # C0 round 13, finding 2 (a value that is not the number written)
    # is now impossible by construction: only an admitted quantity
    # exists on a claim. What remains is that only citable claims
    # become inputs, and that an input copies the parent as consumed.
    def claim(cid, review, value):
        return records.Claim(
            id=cid,
            statement="s",
            kind="fact",
            evidence_ids=["E1"],
            review=review,
            review_reason="scope narrowed" if review == "qualified" else None,
            quantity=support.bound(value, "亿元", "E1", period="2024"),
        )

    claims = {
        "C1": claim("C1", "supported", 52),
        "C3": claim("C3", "unreviewed", 52),
        "C4": records.Claim(
            id="C4", statement="s", kind="fact", review="supported"
        ),
        "C5": claim("C5", "qualified", 100),
    }
    inputs = calc.inputs_from_claims(claims)
    assert sorted(inputs) == ["C1", "C5"]
    assert inputs["C1"].quantity == claims["C1"].quantity
    assert inputs["C1"].claim_version == 1
    assert inputs["C1"].qualification is None
    assert inputs["C5"].qualification == "scope narrowed"
    request = records.CalcRequest(
        kind="share",
        label="share",
        numerator_claim_id="C3",
        denominator_claim_id="C5",
    )
    result = calc.compute("K1", request, inputs)
    assert result.status == "error" and "missing_quantity" in str(
        result.message
    )
    good = request.model_copy(update={"numerator_claim_id": "C1"})
    assert calc.compute("K2", good, inputs).result == pytest.approx(52.0)


def test_a_chain_recomputes_whatever_the_order_of_its_ids():
    # K10 consumes what K2 produces, and lexicographic order visits K10
    # first, so one pass left the downstream result withdrawn over
    # arithmetic that was already recoverable.
    parent = records.Claim(
        id="C1",
        statement="a measured claim",
        kind="fact",
        evidence_ids=["E1"],
        quantity=support.bound(52, "亿元", "E1", "52亿元", period="2024"),
        review="supported",
        material=True,
        partition="q4",
        questions=[4],
    )
    # Two real operands: a share of a figure over itself states nothing
    # and is refused, so the chain is built from two distinct figures.
    whole = parent.model_copy(
        update={
            "id": "C0",
            "quantity": support.bound(
                104, "亿元", "E1", "104亿元", period="2024"
            ),
        }
    )
    claims = {"C0": whole, "C1": parent}
    upstream = calc.compute(
        "K2",
        records.CalcRequest(
            kind="share",
            label="share",
            numerator_claim_id="C1",
            denominator_claim_id="C0",
        ),
        calc.inputs_from_claims(claims, {}),
    )
    claims["C2"] = records.Claim(
        id="C2",
        kind="derived",
        material=True,
        partition="q4",
        questions=[4],
        origin="K2",
        **calc.derived_fields(upstream, claims),
    )
    calculations = {"K2": upstream}
    downstream = calc.compute(
        "K10",
        records.CalcRequest(
            kind="ratio",
            label="share2",
            numerator_claim_id="C2",
            denominator_claim_id="C0",
        ),
        calc.inputs_from_claims(claims, calculations),
    )
    assert downstream.status == "ok"
    claims["C3"] = records.Claim(
        id="C3",
        kind="derived",
        material=True,
        partition="q4",
        questions=[4],
        origin="K10",
        **calc.derived_fields(downstream, claims),
    )
    calculations["K10"] = downstream
    assert sorted(calculations) == ["K10", "K2"]  # the order that broke it

    # A verdict re-qualifies the parent: the whole chain goes stale.
    claims["C1"] = claims["C1"].model_copy(
        update={"review": "qualified", "review_reason": "sample only"}
    )
    stale = merge.cascade_changes(
        {"claims": claims, "calculations": calculations}, {"C1"}, claims
    )
    claims, calculations = stale["claims"], stale["calculations"]
    assert [c.status for c in calculations.values()] == ["error", "error"]

    claims, calculations, log = calc.recompute_stale(claims, calculations)
    assert calculations["K2"].status == "ok"
    assert calculations["K10"].status == "ok"
    assert merge.citable(claims["C3"], claims, calculations)
    assert len(log) == 2
