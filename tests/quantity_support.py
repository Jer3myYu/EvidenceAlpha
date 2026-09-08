"""Helpers the test modules share for building admitted quantities.

An admitted ``Quantity`` carries a unit tree and an exact binding, so a
test that needs one either admits a draft against real evidence
(``admitted``) or builds one whose binding is structurally valid for a
claim (``bound``). Drafts are what researchers send (``draft``).
"""

from industry import quantities
from industry import records

NOW = "2026-09-07T00:00:00+00:00"


def unit(text: str) -> records.UnitExpr:
    """The unit tree for a proposal spelling; raises on a refusal."""
    parsed = quantities.parse_unit(text)
    if isinstance(parsed, quantities.Refusal):
        raise ValueError(f"{text!r}: {parsed.code} {parsed.detail}")
    return parsed


def draft(
    value: float,
    unit_text: str,
    quote: str,
    evidence_ref: str = "E1",
    occurrence: int = 1,
    period: str | None = None,
    scope: str | None = None,
) -> records.QuantityDraft:
    """A researcher's quantity as it arrives on the wire."""
    return records.QuantityDraft(
        value=value,
        unit_text=unit_text,
        evidence_ref=evidence_ref,
        quote=quote,
        occurrence=occurrence,
        period=period,
        scope=scope,
    )


def evidence(
    eid: str,
    excerpt: str,
    source_id: str = "S1",
    version_id: str | None = "va",
    kind: records.EvidenceKind = "passage",
    table: records.TableLayout | None = None,
    limitations: list[str] | None = None,
) -> records.Evidence:
    """A registry evidence record holding ``excerpt``."""
    return records.Evidence(
        id=eid,
        source_id=source_id,
        source_version_id=version_id,
        excerpt=excerpt,
        locator="sec 1",
        kind=kind,
        extraction="html_text" if kind != "snippet" else "search_snippet",
        limitations=list(limitations or []),
        task_id="T1",
        retrieved_at=NOW,
        table=table,
    )


def admitted(
    value: float,
    unit_text: str,
    quote: str,
    holder: records.Evidence,
    occurrence: int = 1,
    period: str | None = None,
    scope: str | None = None,
) -> records.Quantity:
    """Admit a draft against ``holder``; raises on a refusal."""
    outcome = quantities.admit(
        draft(value, unit_text, quote, holder.id, occurrence, period, scope),
        holder,
        holder.id,
    )
    if isinstance(outcome, quantities.Refusal):
        raise ValueError(f"{quote!r}: {outcome.code} {outcome.detail}")
    return outcome


def bound(
    value: float,
    unit_text: str,
    evidence_id: str = "E1",
    as_written: str | None = None,
    period: str | None = None,
    scope: str | None = None,
) -> records.Quantity:
    """A quantity with a structurally valid binding, for readers' tests.

    The binding is not verified against any excerpt: use ``admitted``
    where admission or persistence is under test.
    """
    written = as_written or f"{value:g} {unit_text}"
    return records.Quantity(
        value=value,
        unit=unit(unit_text),
        period=period,
        scope=scope,
        binding=records.EvidenceBinding(
            evidence_id=evidence_id,
            excerpt_sha256=quantities.excerpt_hash(written),
            number_start=0,
            number_end=len(f"{value:g}"),
            expression_start=0,
            expression_end=len(written),
            as_written=written,
        ),
    )


def cinput(
    claim: records.Claim, version: int | None = None
) -> records.CalcInput:
    """The calculation input a claim yields, as ``calc`` would copy it."""
    return records.CalcInput(
        claim_id=claim.id,
        claim_version=version if version is not None else claim.version,
        quantity=claim.quantity,
        qualification=(
            claim.review_reason if claim.review == "qualified" else None
        ),
    )


def derived(
    value: float,
    unit_text: str,
    period: str | None = None,
    scope: str | None = None,
) -> records.Quantity:
    """A calculation's result quantity: structured unit, no binding."""
    return records.Quantity(
        value=value, unit=unit(unit_text), period=period, scope=scope
    )
