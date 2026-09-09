"""Operand identity: a share or ratio may not divide a figure by itself.

Headline live run 5 (thread `37d841ac`, 2026-09-09) produced four
calculations whose numerator and denominator resolved to one quantity.
The Analyst meant two different figures inside one claim -- C10 carries
both 中国大陆 18.53亿美元 and 全球 53.24亿美元 -- but `CalcRequest` names
claims and `Claim.quantity` is singular, so `calc` divided 53.24 by
itself and reported 100%. Plan revision 34 [D5].

The identity tested is the quantity's *origin*: the evidence occurrence
behind an observed value, or the producer behind a derived one. Equal
values are not identity -- two distinct observations may legitimately
give 100%.
"""

import quantity_support as support
from industry import calc
from industry import merge
from industry import records

NOW = "2026-09-07T00:00:00+00:00"


def _binding(evidence_id="E8", start=1139, end=1144):
    return records.EvidenceBinding(
        evidence_id=evidence_id,
        excerpt_sha256="da761021b5bddd30e7555a71567fcdd9074f528989b38e08e2",
        number_start=start,
        number_end=end,
        expression_start=start,
        expression_end=end + 3,
        as_written="53.24亿美元",
    )


def _quantity(value, binding):
    return support.bound(value, "USD", "E8", "53.24亿美元").model_copy(
        update={"binding": binding, "value": value}
    )


def _observed(claim_id, value, binding):
    return records.CalcInput(
        claim_id=claim_id, claim_version=1, quantity=_quantity(value, binding)
    )


def _derived(claim_id, value, calc_id, version=1):
    return records.CalcInput(
        claim_id=claim_id,
        claim_version=1,
        quantity=_quantity(value, None),
        source_calculation_id=calc_id,
        source_calculation_version=version,
    )


def _share(numerator, denominator):
    return records.CalcRequest(
        kind="share",
        label="占比",
        numerator_claim_id=numerator,
        denominator_claim_id=denominator,
        alignment_note="分子取中国大陆，分母取全球",
    )


def test_the_run_5_reproduction_is_refused():
    # I1: the same canonical claim in both operand positions. This is
    # exactly K1: 53.24 / 53.24 * 100 = 100%, labelled as China's share
    # of the global market.
    inputs = {"C10": _observed("C10", 53.24, _binding())}
    result = calc.compute("K1", _share("C10", "C10"), inputs)
    assert result.status == "error"
    assert "identical_operands" in (result.message or "")
    assert result.result is None


def test_a_ratio_over_one_claim_is_refused():
    inputs = {"C10": _observed("C10", 53.24, _binding())}
    request = records.CalcRequest(
        kind="ratio",
        label="倍数",
        numerator_claim_id="C10",
        denominator_claim_id="C10",
    )
    result = calc.compute("K4", request, inputs)
    assert result.status == "error"
    assert "identical_operands" in (result.message or "")


def test_two_claims_over_one_evidence_occurrence_are_refused():
    # I2: different claim ids, one numeric occurrence. Claim-id
    # inequality is not enough -- an alias reaches the same tautology.
    shared = _binding()
    inputs = {
        "C10": _observed("C10", 53.24, shared),
        "C11": _observed("C11", 53.24, shared),
    }
    result = calc.compute("K5", _share("C10", "C11"), inputs)
    assert result.status == "error"
    assert "identical_operands" in (result.message or "")


def test_two_derived_claims_over_one_producer_are_refused():
    # I3: different derived claims projecting one calculation.
    inputs = {
        "C95": _derived("C95", 100.0, "K1"),
        "C96": _derived("C96", 100.0, "K1"),
    }
    result = calc.compute("K6", _share("C95", "C96"), inputs)
    assert result.status == "error"
    assert "identical_operands" in (result.message or "")


def test_the_same_producer_at_another_version_is_still_the_same_origin():
    inputs = {
        "C95": _derived("C95", 100.0, "K1", version=1),
        "C96": _derived("C96", 100.0, "K1", version=2),
    }
    result = calc.compute("K7", _share("C95", "C96"), inputs)
    # A different version is a different producer result, so this is a
    # distinct origin and identity does not refuse it.
    assert result.status == "ok"


def test_distinct_occurrences_with_equal_values_are_allowed():
    # P1: identity is about origin, never about the number. Two real
    # observations that happen to be equal must still compute, and 100%
    # is a legitimate answer.
    inputs = {
        "C1": _observed("C1", 50.0, _binding("E1", 10, 14)),
        "C2": _observed("C2", 50.0, _binding("E2", 90, 94)),
    }
    result = calc.compute("K8", _share("C1", "C2"), inputs)
    assert result.status == "ok"
    assert result.result == 100.0


def test_two_figures_in_one_excerpt_stay_distinct():
    # P2: the same evidence, different numeric spans -- the intended
    # operands of K1. These must remain usable.
    inputs = {
        "C10": _observed("C10", 18.53, _binding("E8", 1100, 1105)),
        "C11": _observed("C11", 53.24, _binding("E8", 1139, 1144)),
    }
    result = calc.compute("K9", _share("C10", "C11"), inputs)
    assert result.status == "ok"
    assert round(result.result, 4) == 34.8047


def test_an_input_without_a_usable_origin_cannot_compute():
    # I4: neither an evidence binding nor a producer. Nothing may be
    # established from an input whose origin is unknown.
    nowhere = records.CalcInput(
        claim_id="C1", claim_version=1, quantity=_quantity(50.0, None)
    )
    inputs = {"C1": nowhere, "C2": _observed("C2", 25.0, _binding())}
    result = calc.compute("K10", _share("C1", "C2"), inputs)
    assert result.status == "error"
    assert "origin" in (result.message or "")


def test_merge_refuses_an_identity_invalid_producer():
    # The same rule at the eligibility boundary: a stored tautology
    # cannot be projected into a citable derived claim.
    inputs = [_observed("C10", 53.24, _binding())] * 2
    tautology = records.Calculation(
        id="K1",
        kind="share",
        label="占比",
        inputs=inputs,
        formula="53.24 / 53.24 * 100",
        result=100.0,
        unit=support.unit("%"),
        status="ok",
    )
    assert not merge.calculation_identity_ok(tautology)
