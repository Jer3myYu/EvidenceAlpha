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
from typing import Any

from industry import merge
from industry import quantities
from industry import records
from industry import schedule


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
    if (
        not _same_period(a.quantity.period, b.quantity.period)
        or a.quantity.scope != b.quantity.scope
    ):
        if note:
            return note
        raise CalcError(
            "misaligned_inputs: periods or scopes differ "
            f"({a.quantity.period!r}/{a.quantity.scope!r} vs "
            f"{b.quantity.period!r}/{b.quantity.scope!r}) and "
            "no alignment note explains why they are comparable"
        )
    return None


def _finite(value: float, role: str) -> None:
    if math.isnan(value) or math.isinf(value):
        raise CalcError(f"non_finite_{role}: {value!r}")


def inputs_from_claims(
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation] | None = None,
) -> dict[str, records.CalcInput]:
    """The quantities a calculation may consume, by claim id.

    Only a claim reviewed supported or qualified with an admitted
    quantity becomes an input; anything else is a missing input, never
    a number. A claim that reports a calculation of its own is an input
    only while the whole chain under it is live (``merge.citable``).
    Each input is a preserved copy of the parent as consumed -- its
    version, its whole quantity and its qualification -- so a parent
    that later changes is detected even if a cascade missed it.
    """
    live = calculations or {}
    return {
        cid: records.CalcInput(
            claim_id=cid,
            claim_version=claim.version,
            quantity=claim.quantity,
            qualification=(
                claim.review_reason if claim.review == "qualified" else None
            ),
            # A derived parent's figure is its producer's result, not an
            # evidence occurrence, so its origin is recorded here.
            source_calculation_id=claim.calculation_id,
            source_calculation_version=(
                claim.calculation_version
                if claim.calculation_id is not None
                else None
            ),
        )
        for cid, claim in claims.items()
        if claim.quantity is not None and merge.citable(claim, claims, live)
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
        return _compute(calc_id, request, inputs).model_copy(
            update={"request": request}
        )
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
            request=request,
        )


def _compute(
    calc_id: str,
    request: records.CalcRequest,
    inputs: dict[str, records.CalcInput],
) -> records.Calculation:
    if request.kind == "growth":
        start = _input(request.start_claim_id, inputs, "start")
        end = _input(request.end_claim_id, inputs, "end")
        if start.quantity.unit != end.quantity.unit:
            raise CalcError(
                "unit_mismatch: "
                f"{quantities.render(start.quantity.unit)!r} vs "
                f"{quantities.render(end.quantity.unit)!r}"
            )
        if (
            start.quantity.scope != end.quantity.scope
            and not request.alignment_note
        ):
            raise CalcError("scope_mismatch: growth inputs differ in scope")
        first, last = start.quantity.value, end.quantity.value
        _finite(first, "start")
        _finite(last, "end")
        if first <= 0:
            raise CalcError("non_positive_start: growth needs a start > 0")
        if last <= 0:
            raise CalcError("non_positive_end: growth needs an end > 0")
        years = elapsed_years(
            parse_period(start.quantity.period),
            parse_period(end.quantity.period),
        )
        result = ((last / first) ** (1.0 / years) - 1.0) * 100.0
        return records.Calculation(
            id=calc_id,
            kind="growth",
            label=request.label,
            inputs=[start, end],
            formula=(f"(({last} / {first}) ^ (1/{years}) - 1) * 100"),
            result=round(result, 4),
            unit=quantities.divide(
                quantities.atom("%"), quantities.atom("year")
            ),
            status="ok",
            alignment_note=request.alignment_note,
        )
    numerator = _input(request.numerator_claim_id, inputs, "numerator")
    denominator = _input(request.denominator_claim_id, inputs, "denominator")
    # One figure over itself is 100% or 1.0 whatever the label claims,
    # so it is refused before the division rather than reported.
    same = merge.identical_operands(numerator, denominator)
    if same is not None:
        raise CalcError(same)
    above, below = numerator.quantity, denominator.quantity
    _finite(above.value, "numerator")
    _finite(below.value, "denominator")
    if below.value <= 0:
        raise CalcError("non_positive_denominator")
    note = _same_period_and_scope(
        numerator, denominator, request.alignment_note
    )
    if request.kind == "share":
        if above.unit != below.unit:
            raise CalcError(
                "unit_mismatch: "
                f"{quantities.render(above.unit)!r} vs "
                f"{quantities.render(below.unit)!r}"
            )
        result = above.value / below.value * 100.0
        unit = quantities.atom("%")
        formula = f"{above.value} / {below.value} * 100"
    else:
        result = above.value / below.value
        # Whole operands: USD/(kg/day) and (USD/kg)/day stay different.
        unit = (
            quantities.atom("ratio")
            if above.unit == below.unit
            else quantities.divide(above.unit, below.unit)
        )
        formula = f"{above.value} / {below.value}"
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


STALE_INPUT = "stale_input:"


def derived_fields(
    result: records.Calculation, claims: dict[str, records.Claim]
) -> dict[str, Any]:
    """The claim fields that report one calculation's result.

    The one projection rule lives in ``merge.derived_fields`` (the
    citability check compares a derived claim against it); this is the
    same function.
    """
    return merge.derived_fields(result, claims)


def recompute_stale(
    claims: dict[str, records.Claim],
    calculations: dict[str, records.Calculation],
) -> tuple[dict[str, records.Claim], dict[str, records.Calculation], list[str]]:
    """Run again every calculation a changed input stopped.

    This is the only way back for a derived claim: its calculation is
    recomputed from the claims as they stand now, and the claim that
    reports it becomes a new version stating the new result. A
    calculation whose inputs are still unusable stays stopped and its
    claim stays uncitable. Returns the updated claims, the updated
    calculations, and the log lines.

    A calculation may consume a claim another calculation produces, so
    one pass in id order is not enough (``K10`` reads what ``K2``
    writes, and lexicographic order visits ``K10`` first): the pass
    repeats while it recovers anything, which terminates because every
    repetition moves at least one calculation out of ``error`` for
    good.
    """
    claims = dict(claims)
    calculations = dict(calculations)
    log: list[str] = []
    recovered = True
    while recovered:
        recovered = False
        for calc_id in sorted(calculations, key=schedule.task_number):
            record = calculations[calc_id]
            if record.status != "error" or record.request is None:
                continue
            if not (record.message or "").startswith(STALE_INPUT):
                continue
            fresh = compute(
                calc_id,
                record.request,
                inputs_from_claims(claims, calculations),
            )
            if fresh.status != "ok":
                continue
            # A new version of the calculation, so a claim still
            # reporting the old one stays uncitable until it is
            # rewritten below.
            fresh = fresh.model_copy(update={"version": record.version + 1})
            calculations[calc_id] = fresh
            recovered = True
            for claim_id, claim in list(claims.items()):
                if claim.calculation_id != calc_id:
                    continue
                claims[claim_id] = claim.model_copy(
                    update={
                        **derived_fields(fresh, claims),
                        "version": claim.version + 1,
                        "supersedes": f"{claim_id}@{claim.version}",
                        "reviewed_topics": [],
                    }
                )
                log.append(
                    f"analyze: {calc_id} recomputed = {fresh.result} "
                    f"{quantities.render(fresh.unit)} -> {claim_id} version "
                    f"{claim.version + 1}"
                )
    return claims, calculations, log
