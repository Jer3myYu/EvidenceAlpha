"""One normalized comparison projection over the claim registry. Pure.

Question 7 asks how representative companies compare on business-relevant,
consistent dimensions. Before this module, coverage answered it by
checking that two claims carried the same ``dimension`` string and
different ``entity`` strings -- which passes when one company's
consolidated 2024 revenue in 亿元 sits beside another's semiconductor
segment revenue for 2023 in 百万美元. Matching labels is not
comparability (plan D-U9).

A cell here binds entity, metric, value, unit, period, scope, the
evidence that established it, and any qualification the verifier
attached. Null is unknown, never zero. Two cells are comparable only
when their unit reduces to the same base, and their period and scope
agree; otherwise they stay in separate bases with the difference stated
rather than made to disappear.
"""

import dataclasses
from typing import Any

from industry import quantities
from industry import records


@dataclasses.dataclass(frozen=True)
class Cell:
    """One company's value for one metric, with everything it depends on."""

    claim_id: str
    claim_version: int
    entity: str
    metric: str
    value: float | None
    unit: str
    period: str | None
    scope: str | None
    evidence_ids: tuple[str, ...]
    source_version_ids: tuple[str, ...]
    caveat: str | None

    @property
    def basis(self) -> tuple[str, str | None, str | None]:
        """What must agree before two cells may be compared."""
        return (self.unit, self.period, self.scope)


@dataclasses.dataclass(frozen=True)
class Row:
    """One metric, its cells, and how they group into comparable bases."""

    metric: str
    cells: tuple[Cell, ...]

    def bases(self) -> dict[tuple[str, str | None, str | None], list[Cell]]:
        """The cells grouped by what makes them comparable."""
        grouped: dict[tuple[str, str | None, str | None], list[Cell]] = {}
        for cell in self.cells:
            grouped.setdefault(cell.basis, []).append(cell)
        return grouped

    def comparable(self) -> list[list[Cell]]:
        """Groups where at least two distinct entities can be compared.

        A group of numbers whose unit or period nobody established is
        not a basis -- it is the same unknown written twice, and
        treating it as agreement is how two unrelated figures end up in
        one column (U1-03). Scope is not required, because sources often
        do not state one; it only has to *agree*, which it does by
        being part of the basis, so consolidated still never groups with
        a segment. Qualitative cells carry no value at all and are
        unaffected: they compare on the metric itself.
        """
        groups = []
        for (unit, period, _), cells in self.bases().items():
            if len({c.entity.casefold() for c in cells}) < 2:
                continue
            numeric = any(c.value is not None for c in cells)
            if numeric and not (unit and period):
                continue
            groups.append(cells)
        return groups


@dataclasses.dataclass(frozen=True)
class Projection:
    """Every metric a comparison could rest on, and its incompatibilities."""

    rows: tuple[Row, ...]
    notes: tuple[str, ...]

    def any_comparable(self) -> bool:
        """Whether one metric compares two entities on one basis."""
        return any(row.comparable() for row in self.rows)

    def entities(self) -> set[str]:
        """Every entity that appears at all."""
        return {c.entity for row in self.rows for c in row.cells}


def normalise(quantity: records.Quantity) -> tuple[float, str]:
    """The value with every power-of-ten scale folded in, and its base unit.

    ``52亿元`` and ``5_200_000_000元`` are the same number written twice,
    and a projection that treats them as different bases would report two
    companies as incomparable because one report used 亿 and the other
    did not. Only ``scale10`` is folded: converting 元 to 美元 needs a
    rate, which is evidence this module does not have and will not
    invent.
    """
    exponent, base = _strip_scale(quantity.unit)
    return quantity.value * 10.0**exponent, quantities.render(base)


def _strip_scale(expr: records.UnitExpr) -> tuple[int, records.UnitExpr]:
    """The total power of ten in ``expr``, and ``expr`` without it.

    A scale does not only sit at the top. ``万元/片`` parses as
    ``divide(scale10(4, 元), 片)``, and a loop that only unwrapped the
    outermost node never reached it -- so ``1 万元/片`` and
    ``10000 元/片`` looked like two incompatible bases and a legitimate
    comparison regressed (U1-04). A scale in a denominator counts
    negatively; one under a power counts as many times as the power.
    """
    if expr.kind == "scale10" and expr.left is not None:
        inner, base = _strip_scale(expr.left)
        return expr.exponent + inner, base
    if expr.kind in ("multiply", "divide"):
        if expr.left is None or expr.right is None:
            return 0, expr
        left_exp, left = _strip_scale(expr.left)
        right_exp, right = _strip_scale(expr.right)
        sign = 1 if expr.kind == "multiply" else -1
        rebuilt = records.UnitExpr(kind=expr.kind, left=left, right=right)
        return left_exp + sign * right_exp, rebuilt
    if expr.kind == "power" and expr.left is not None:
        inner, base = _strip_scale(expr.left)
        return inner * expr.exponent, records.UnitExpr(
            kind="power", exponent=expr.exponent, left=base
        )
    return 0, expr


def _cell(
    claim: records.Claim, evidence: dict[str, records.Evidence]
) -> Cell | None:
    """One cell from a claim, or None when it cannot anchor a comparison."""
    if not claim.entity or not claim.dimension:
        return None
    metric = " ".join(claim.dimension.split())
    value: float | None = None
    unit = ""
    period = claim.period
    scope = None
    if claim.quantity is not None:
        value, unit = normalise(claim.quantity)
        period = claim.quantity.period or claim.period
        scope = claim.quantity.scope
    versions = []
    for eid in claim.evidence_ids:
        item = evidence.get(eid)
        if item is not None and item.source_version_id:
            if item.source_version_id not in versions:
                versions.append(item.source_version_id)
    return Cell(
        claim_id=claim.id,
        claim_version=claim.version,
        entity=claim.entity,
        metric=metric,
        value=value,
        unit=unit,
        period=period,
        scope=scope,
        evidence_ids=tuple(claim.evidence_ids),
        source_version_ids=tuple(versions),
        # A qualified claim carries its qualification into the table, so
        # a reader sees the restriction beside the number rather than in
        # a footnote nobody reaches.
        caveat=claim.review_reason if claim.review == "qualified" else None,
    )


def project(state: dict[str, Any]) -> Projection:
    """Build the comparison projection from the reviewed registry.

    Only reviewed claims take part: an unreviewed number has not earned
    a place in a table a reader will compare across. The order is by
    metric then claim id, so a replay projects identically.
    Only claims the verifier confirmed as bearing on the comparison
    take part (``reviewed_topics``), the same rule coverage applies
    everywhere else: a tag the verifier did not confirm has never been
    allowed to earn coverage, and it may not earn it here either
    (U1-03).
    """
    claims = state.get("claims", {})
    evidence = state.get("evidence", {})
    # Grouped by the metric's casefolded spelling: "2024 revenue" and
    # "2024 Revenue" are one metric, and treating them as two would
    # report two companies as incomparable over a capital letter. The
    # first spelling seen is what the table shows.
    by_metric: dict[str, tuple[str, list[Cell]]] = {}
    for claim in sorted(claims.values(), key=lambda c: c.id):
        if not claim.is_reviewed():
            continue
        if "comparison" not in claim.reviewed_topics:
            continue
        cell = _cell(claim, evidence)
        if cell is None:
            continue
        label, cells = by_metric.setdefault(
            cell.metric.casefold(), (cell.metric, [])
        )
        del label
        cells.append(cell)
    rows = tuple(
        Row(metric=label, cells=tuple(cells))
        for _, (label, cells) in sorted(by_metric.items())
    )
    return Projection(rows=rows, notes=tuple(_notes(rows)))


def _notes(rows: tuple[Row, ...]) -> list[str]:
    """Say which metrics hold values that must not be compared directly.

    Incompatible periods, units, or scopes are not reconciled here and
    are never silently dropped: the note is what stops a reader adding
    a 2023 segment figure to a 2024 consolidated one.
    """
    notes = []
    for row in rows:
        bases = row.bases()
        if len(bases) < 2:
            continue
        entities = {c.entity.casefold() for c in row.cells}
        if len(entities) < 2:
            continue
        if row.comparable():
            continue
        described = "; ".join(
            _describe(basis)
            for basis in sorted(bases, key=lambda b: tuple(str(x) for x in b))
        )
        notes.append(
            f"{row.metric}: the entities are reported on different bases "
            f"({described}); they are not directly comparable"
        )
    return notes


def _describe(basis: tuple[str, str | None, str | None]) -> str:
    """One basis in words: unit, period, scope, each named when unknown."""
    unit, period, scope = basis
    return "/".join(
        [unit or "no unit", period or "no period", scope or "no scope"]
    )


def render(projection: Projection) -> str:
    """The projection as a table a reader and a reviewer can both check."""
    if not projection.rows:
        return (
            "Comparison: no reviewed claim carries both an entity and a "
            "metric yet."
        )
    lines = ["Comparison projection:"]
    for row in projection.rows:
        lines.append(f"  {row.metric}")
        for basis, cells in sorted(
            row.bases().items(), key=lambda kv: tuple(str(x) for x in kv[0])
        ):
            unit, period, scope = basis
            head = ", ".join(
                part
                for part in (
                    unit or "unit unknown",
                    period or "period unknown",
                    scope or "scope unstated",
                )
            )
            lines.append(f"    [{head}]")
            for cell in cells:
                value = "unknown" if cell.value is None else f"{cell.value:g}"
                caveat = f" -- {cell.caveat}" if cell.caveat else ""
                lines.append(
                    f"      {cell.entity}: {value} "
                    f"(claim {cell.claim_id}){caveat}"
                )
    for note in projection.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)
