"""Deterministic calculations and their validation."""

import pytest

from industry import calc
from industry import records


def cinput(cid, value, unit="亿元", period="2024", scope=None):
    return records.CalcInput(
        claim_id=cid, value=value, unit=unit, period=period, scope=scope
    )


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
    assert result.unit == "% per year" and "1/4" in result.formula


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
    assert (
        result.status == "ok" and result.result == 25.0 and result.unit == "%"
    )
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
    assert result.status == "ok" and result.unit == "亿元/万平方米"
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
