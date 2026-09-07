"""Deterministic arithmetic over claim quantities. Pure.

Three operations: ``ratio`` (a / b), ``share`` (a / b as a percentage),
and ``growth`` (compound annual growth from a start to an end quantity,
with the elapsed years derived from the two periods, never supplied by
a model). Every check that would make a result economically invalid
raises ``CalcError`` with a short code, and ``compute`` turns that into
a ``Calculation`` with ``status="error"`` so the analyst sees the
problem instead of a number.
"""

import dataclasses
import math
import re

from industry import merge
from industry import records


class CalcError(ValueError):
    """A calculation input is missing, unparseable, or incompatible."""


@dataclasses.dataclass(frozen=True)
class Period:
    """A normalized reporting period.

    Attributes:
      year: The calendar or fiscal year.
      kind: ``year``, ``half``, or ``quarter``.
      index: 1 for a year; the half or quarter number otherwise.
      fiscal: Whether the period was written as a fiscal year.
    """

    year: int
    kind: str
    index: int
    fiscal: bool

    def key(self) -> tuple[int, str, int, bool]:
        """The identity used to compare two periods."""
        return (self.year, self.kind, self.index, self.fiscal)


_YEAR = re.compile(r"^(FY)?(\d{4})(?:年)?$", re.IGNORECASE)
_HALF = re.compile(r"^(\d{4})H([12])$", re.IGNORECASE)
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)


def parse_period(text: str | None) -> Period:
    """Normalize ``2024``, ``FY2024``, ``2024年``, ``2024H1``, ``2024Q3``.

    Raises:
      CalcError: ``unparseable_period`` for anything else, including
        ``None``.
    """
    if not text:
        raise CalcError("unparseable_period: missing period")
    value = text.strip()
    match = _YEAR.match(value)
    if match:
        return Period(int(match.group(2)), "year", 1, bool(match.group(1)))
    match = _HALF.match(value)
    if match:
        return Period(int(match.group(1)), "half", int(match.group(2)), False)
    match = _QUARTER.match(value)
    if match:
        return Period(
            int(match.group(1)), "quarter", int(match.group(2)), False
        )
    raise CalcError(f"unparseable_period: {text!r}")


def elapsed_years(start: Period, end: Period) -> int:
    """Whole years between two periods of the same kind and index.

    Raises:
      CalcError: If the kinds differ (``2023`` vs ``2024H1``), the
        fiscal flags differ, the sub-period indexes differ, or the end
        is not after the start.
    """
    if (start.kind, start.index, start.fiscal) != (
        end.kind,
        end.index,
        end.fiscal,
    ):
        raise CalcError(
            "incomparable_periods: growth needs the same period type, "
            f"got {start} and {end}"
        )
    years = end.year - start.year
    if years <= 0:
        raise CalcError("period_order: the end period must be later")
    return years


def _same_period(a: str | None, b: str | None) -> bool:
    """Whether two period labels denote the same period once normalized."""
    if a == b:
        return True
    try:
        return parse_period(a).key() == parse_period(b).key()
    except CalcError:
        return False


def _same_period_and_scope(
    a: records.CalcInput, b: records.CalcInput, note: str | None
) -> str | None:
    """Check ratio/share alignment; return a qualification or raise."""
    if not _same_period(a.period, b.period) or a.scope != b.scope:
        if note:
            return note
        raise CalcError(
            "misaligned_inputs: periods or scopes differ "
            f"({a.period!r}/{a.scope!r} vs {b.period!r}/{b.scope!r}) and "
            "no alignment note explains why they are comparable"
        )
    return None


def _finite(value: float, role: str) -> None:
    if math.isnan(value) or math.isinf(value):
        raise CalcError(f"non_finite_{role}: {value!r}")


def inputs_from_claims(
    claims: dict[str, records.Claim],
) -> dict[str, records.CalcInput]:
    """The quantities a calculation may consume, by claim id.

    Only a claim reviewed supported or qualified whose quantity is
    consistent (``merge.quantity_consistent``: the numeric value is the
    number as written) becomes an input; anything else is a missing
    input, never a number.
    """
    return {
        cid: records.CalcInput(
            claim_id=cid,
            value=claim.quantity.value,
            unit=claim.quantity.unit,
            period=claim.quantity.period,
            scope=claim.quantity.scope,
        )
        for cid, claim in claims.items()
        if claim.quantity is not None
        and claim.is_reviewed()
        and merge.quantity_consistent(claim.quantity)
    }


def _input(
    claim_id: str | None, inputs: dict[str, records.CalcInput], role: str
) -> records.CalcInput:
    if claim_id is None:
        raise CalcError(f"missing_input: no {role} claim")
    if claim_id not in inputs:
        raise CalcError(
            f"missing_quantity: claim {claim_id} has no validated quantity"
        )
    return inputs[claim_id]


def compute(
    calc_id: str,
    request: records.CalcRequest,
    inputs: dict[str, records.CalcInput],
) -> records.Calculation:
    """Run one request; never raises, the status carries the outcome.

    Args:
      calc_id: The id to assign (``K#``).
      request: The analyst's request.
      inputs: Validated quantities by claim id.

    Returns:
      A ``Calculation`` with ``result`` and ``unit`` on success, or
      ``status="error"`` and a ``message`` naming the failed check.
    """
    try:
        return _compute(calc_id, request, inputs)
    except CalcError as error:
        used = [
            inputs[cid]
            for cid in (
                request.numerator_claim_id,
                request.denominator_claim_id,
                request.start_claim_id,
                request.end_claim_id,
            )
            if cid in inputs
        ]
        return records.Calculation(
            id=calc_id,
            kind=request.kind,
            label=request.label,
            inputs=used,
            formula="",
            status="error",
            message=str(error),
            alignment_note=request.alignment_note,
        )


def _compute(
    calc_id: str,
    request: records.CalcRequest,
    inputs: dict[str, records.CalcInput],
) -> records.Calculation:
    if request.kind == "growth":
        start = _input(request.start_claim_id, inputs, "start")
        end = _input(request.end_claim_id, inputs, "end")
        if start.unit != end.unit:
            raise CalcError(f"unit_mismatch: {start.unit!r} vs {end.unit!r}")
        if start.scope != end.scope and not request.alignment_note:
            raise CalcError("scope_mismatch: growth inputs differ in scope")
        _finite(start.value, "start")
        _finite(end.value, "end")
        if start.value <= 0:
            raise CalcError("non_positive_start: growth needs a start > 0")
        if end.value <= 0:
            raise CalcError("non_positive_end: growth needs an end > 0")
        years = elapsed_years(
            parse_period(start.period), parse_period(end.period)
        )
        result = ((end.value / start.value) ** (1.0 / years) - 1.0) * 100.0
        return records.Calculation(
            id=calc_id,
            kind="growth",
            label=request.label,
            inputs=[start, end],
            formula=(
                f"(({end.value} / {start.value}) ^ (1/{years}) - 1) * 100"
            ),
            result=round(result, 4),
            unit="% per year",
            status="ok",
            alignment_note=request.alignment_note,
        )
    numerator = _input(request.numerator_claim_id, inputs, "numerator")
    denominator = _input(request.denominator_claim_id, inputs, "denominator")
    _finite(numerator.value, "numerator")
    _finite(denominator.value, "denominator")
    if denominator.value <= 0:
        raise CalcError("non_positive_denominator")
    note = _same_period_and_scope(
        numerator, denominator, request.alignment_note
    )
    if request.kind == "share":
        if numerator.unit != denominator.unit:
            raise CalcError(
                f"unit_mismatch: {numerator.unit!r} vs {denominator.unit!r}"
            )
        result = numerator.value / denominator.value * 100.0
        unit = "%"
        formula = f"{numerator.value} / {denominator.value} * 100"
    else:
        result = numerator.value / denominator.value
        unit = (
            "ratio"
            if numerator.unit == denominator.unit
            else f"{numerator.unit}/{denominator.unit}"
        )
        formula = f"{numerator.value} / {denominator.value}"
    return records.Calculation(
        id=calc_id,
        kind=request.kind,
        label=request.label,
        inputs=[numerator, denominator],
        formula=formula,
        result=round(result, 6),
        unit=unit,
        status="ok",
        alignment_note=note,
    )
