"""The parse quality gate (03 §7).

The gate decides what may enter the corpus, so it is the component
whose failure is least visible and most damaging. Its checks are
predicates with numbers, not adjectives.

Two rules shape everything here:

* **The verdict is per document; admission is per block.** A ``partial``
  document admits the blocks that individually pass their checks and
  rejects the rest, and rejected blocks are persisted with their reason
  rather than silently dropped.
* **The gate is capability-aware.** It asserts what the bound adapter
  *promised*, while the route's minimum profile guarantees the corpus
  floor. A markdown-based adapter is not failed for missing bounding
  boxes it never claimed — but it is also not allowed onto a route that
  requires them, and that refusal happens at startup.

Named ``gate.py`` rather than ``quality.py`` because
:mod:`contracts.quality` already owns that name and this repository
imports modules rather than symbols.
"""

import pydantic

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")

#: Source types whose coverage is measured as extracted characters
#: against source byte size (03 §7.1).
_HTML_SOURCE_TYPES = frozenset(
    {
        document.SourceType.SEC_FILING,
        document.SourceType.NEWS_ARTICLE,
        document.SourceType.IR_DOCUMENT,
        document.SourceType.GENERIC_HTML,
    }
)


class QualityPolicy(pydantic.BaseModel):
    """Versioned thresholds the gate applies (03 §7.1).

    These numbers are **policy v0: provisional, configurable, and not
    architectural constants.** They are strawmen to be calibrated
    against the golden SEC and PDF fixtures once those exist.

    The version is part of the planned parse manifest, so changing a
    threshold changes ``parse_id`` and makes the affected documents
    re-parseable, instead of silently reclassifying an existing corpus.
    """

    model_config = _MODEL_CONFIG

    version: str = "v0"

    #: PDF to OCR routing: route to OCR when the median characters per
    #: page falls below the floor, or too large a share of pages are
    #: nearly empty. A document-level metric, because per-page floors
    #: misfire on legitimate near-empty covers and dividers.
    pdf_ocr_median_chars_per_page: int = pydantic.Field(default=100, ge=0)
    pdf_ocr_sparse_page_char_floor: int = pydantic.Field(default=50, ge=0)
    pdf_ocr_sparse_page_fraction: float = pydantic.Field(
        default=0.30, ge=0.0, le=1.0
    )

    #: PDF coverage: pages emitted must equal the container page count.
    require_exact_pdf_page_coverage: bool = True

    #: HTML coverage. The ratio is low on purpose — an inline-XBRL 10-K
    #: is mostly markup, so a few percent text by byte is normal. The
    #: absolute floor is what catches a small, well-formed page that is
    #: not a filing at all.
    html_min_extracted_ratio: float = pydantic.Field(
        default=0.01, ge=0.0, le=1.0
    )
    html_min_extracted_characters: int = pydantic.Field(default=2000, ge=0)

    #: News boilerplate ratio: the one v0 threshold with no value,
    #: because it belongs to the news route, which is outside the MVP
    #: profile (03 §18).
    news_max_boilerplate_ratio: float | None = None


#: The policy in force. Replacing it is a versioned decision, never an
#: edit to a constant inside a predicate.
POLICY_V0 = QualityPolicy()


class GateOutcome(pydantic.BaseModel):
    """What the gate decided about one parse (03 §7.4)."""

    model_config = _MODEL_CONFIG

    verdict: quality.QualityVerdict
    policy_version: str
    admitted: list[document.Block] = pydantic.Field(default_factory=list)
    rejected: list[document.RejectedBlock] = pydantic.Field(
        default_factory=list
    )
    warnings: list[document.ParseWarning] = pydantic.Field(default_factory=list)
    metrics: document.ParseMetrics = pydantic.Field(
        default_factory=document.ParseMetrics
    )

    @property
    def failed(self) -> bool:
        """Return whether the verdict forbids indexing."""
        return self.verdict is quality.QualityVerdict.FAILED


def _primary_dimension(blocks: list[document.Block]) -> str:
    """Return the locator dimension block order is checked against."""
    if any(block.locator.page is not None for block in blocks):
        return "page"
    if any(block.locator.line_start is not None for block in blocks):
        return "line_start"
    return "element_index"


def _dimension_value(block: document.Block, dimension: str) -> int | None:
    """Return one block's coordinate in the ordering dimension."""
    return getattr(block.locator, dimension)


class QualityGate:
    """Applies the versioned quality policy to one parse (03 §7)."""

    def __init__(self, policy: QualityPolicy | None = None) -> None:
        """Initialize the gate.

        Args:
          policy: The quality policy to apply; :data:`POLICY_V0` when
            omitted.
        """
        self._policy = policy or POLICY_V0

    @property
    def policy(self) -> QualityPolicy:
        """Return the policy this gate applies."""
        return self._policy

    def evaluate(
        self,
        blocks: list[document.Block],
        artifact: shapes.AcquiredArtifact,
        raw: shapes.RawParseResult,
        adapter_capabilities: capabilities_module.AdapterCapabilities,
        profile: capabilities_module.RouteProfile,
        conversion_warnings: list[document.ParseWarning] | None = None,
    ) -> GateOutcome:
        """Decide the verdict and admit blocks individually.

        Args:
          blocks: Every normalized block the converter produced.
          artifact: The artifact that was parsed, for the independent
            coverage measure and the expectation check.
          raw: The adapter's native result, for its own metrics.
          adapter_capabilities: What the bound adapter declared.
          profile: The route's minimum capability profile.
          conversion_warnings: Warnings raised during conversion.

        Returns:
          The gate outcome: verdict, admitted blocks, rejected blocks
          with reasons, document warnings, and metrics.
        """
        warnings = list(conversion_warnings or [])
        warnings.extend(raw.warnings)

        admitted, rejected = self._admit_blocks(
            blocks, adapter_capabilities, profile, warnings
        )
        metrics = self._metrics(blocks, admitted, raw)
        failures = self._document_checks(
            admitted, artifact, raw, metrics, warnings
        )

        if failures:
            verdict = quality.QualityVerdict.FAILED
        elif rejected or warnings:
            verdict = quality.QualityVerdict.PARTIAL
        else:
            verdict = quality.QualityVerdict.VALID

        return GateOutcome(
            verdict=verdict,
            policy_version=self._policy.version,
            admitted=admitted,
            rejected=rejected,
            warnings=warnings,
            metrics=metrics,
        )

    def _admit_blocks(
        self,
        blocks: list[document.Block],
        adapter_capabilities: capabilities_module.AdapterCapabilities,
        profile: capabilities_module.RouteProfile,
        warnings: list[document.ParseWarning],
    ) -> tuple[list[document.Block], list[document.RejectedBlock]]:
        """Admit or reject each block on its own merits (03 §7.4)."""
        admitted: list[document.Block] = []
        rejected: list[document.RejectedBlock] = []
        overstated = False
        dimension = _primary_dimension(blocks)
        highwater: int | None = None

        for block in blocks:
            reason, detail = self._reject_reason(
                block, adapter_capabilities, profile
            )
            if reason is None:
                value = _dimension_value(block, dimension)
                if (
                    value is not None
                    and highwater is not None
                    and value < highwater
                ):
                    reason = quality.BlockRejectionReason.ORDERING_VIOLATION
                    detail = (
                        f"{dimension} {value} follows {highwater} in "
                        "document order"
                    )
                elif value is not None:
                    highwater = value
            if reason is None:
                admitted.append(block)
                continue
            if reason in (
                quality.BlockRejectionReason.UNDECLARED_BLOCK_TYPE,
                quality.BlockRejectionReason.UNDECLARED_LOCATOR_TIER,
            ):
                overstated = True
            rejected.append(
                document.RejectedBlock(
                    block=block, reason=reason, detail=detail
                )
            )

        if overstated:
            warnings.append(
                document.ParseWarning(
                    code=quality.WarningCode.CAPABILITY_OVERSTATED,
                    message=(
                        "the adapter emitted a block type or locator tier "
                        "it did not declare (03 §3.5)"
                    ),
                )
            )
        if any(
            item.reason is quality.BlockRejectionReason.ORDERING_VIOLATION
            for item in rejected
        ):
            warnings.append(
                document.ParseWarning(
                    code=quality.WarningCode.BLOCK_ORDER_UNSTABLE,
                    message=(f"block sequence is not monotonic in {dimension}"),
                )
            )
        if any(
            item.reason
            is quality.BlockRejectionReason.LOCATOR_TIER_BELOW_MINIMUM
            for item in rejected
        ):
            warnings.append(
                document.ParseWarning(
                    code=quality.WarningCode.LOCATOR_MISSING,
                    message=(
                        "one or more blocks did not reach the route's "
                        f"minimum locator tier "
                        f"({profile.min_locator_tier.name})"
                    ),
                )
            )
        return admitted, rejected

    def _reject_reason(
        self,
        block: document.Block,
        adapter_capabilities: capabilities_module.AdapterCapabilities,
        profile: capabilities_module.RouteProfile,
    ) -> tuple[quality.BlockRejectionReason | None, str | None]:
        """Return why one block is inadmissible, if it is."""
        if not block.text.strip():
            return (
                quality.BlockRejectionReason.EMPTY_TEXT,
                "canonical text is empty or whitespace only",
            )
        if block.type not in adapter_capabilities.block_types:
            return (
                quality.BlockRejectionReason.UNDECLARED_BLOCK_TYPE,
                f"the adapter did not declare block type {block.type.value}",
            )
        tier = block.locator_tier
        if tier not in adapter_capabilities.locator_tiers:
            return (
                quality.BlockRejectionReason.UNDECLARED_LOCATOR_TIER,
                f"the adapter did not declare locator tier {tier.name}",
            )
        if not tier.meets(profile.min_locator_tier):
            return (
                quality.BlockRejectionReason.LOCATOR_TIER_BELOW_MINIMUM,
                (
                    f"locator tier {tier.name} is below the route minimum "
                    f"{profile.min_locator_tier.name}"
                ),
            )
        return None, None

    def _metrics(
        self,
        blocks: list[document.Block],
        admitted: list[document.Block],
        raw: shapes.RawParseResult,
    ) -> document.ParseMetrics:
        """Count what the parse produced (03 §8.3)."""
        return document.ParseMetrics(
            pages=raw.page_count,
            blocks_emitted=len(blocks),
            blocks_admitted=len(admitted),
            characters=sum(len(block.text) for block in admitted),
            tables=sum(
                1
                for block in admitted
                if block.type is document.BlockType.TABLE
            ),
            ocr_pages=raw.page_count or 0 if raw.ocr_used else 0,
        )

    def _document_checks(
        self,
        admitted: list[document.Block],
        artifact: shapes.AcquiredArtifact,
        raw: shapes.RawParseResult,
        metrics: document.ParseMetrics,
        warnings: list[document.ParseWarning],
    ) -> list[str]:
        """Run the document-level predicates (03 §7.2, §7.3).

        Returns:
          A list of failures. Any entry makes the verdict ``failed``;
          an empty list leaves the verdict to the per-block outcome.
        """
        failures: list[str] = []
        if not admitted:
            failures.append("no admitted block carries non-whitespace text")
        self._check_coverage(
            admitted, artifact, raw, metrics, warnings, failures
        )
        self._check_expectation(artifact, raw, warnings, failures)
        self._check_sec_identity(raw, warnings)
        return failures

    def _check_coverage(
        self,
        admitted: list[document.Block],
        artifact: shapes.AcquiredArtifact,
        raw: shapes.RawParseResult,
        metrics: document.ParseMetrics,
        warnings: list[document.ParseWarning],
        failures: list[str],
    ) -> None:
        """Compare extraction against an independent source measure.

        Catches the silent-truncation failure where a parser returns
        page 1 of 200 without erroring (03 §7.2). The measure is
        deliberately independent of the parser's own report: source byte
        size for HTML, container page count for PDF.
        """
        if raw.source_type in _HTML_SOURCE_TYPES:
            self._check_html_coverage(artifact, metrics, warnings, failures)
            return
        if raw.source_type is document.SourceType.PDF_DOCUMENT:
            self._check_pdf_coverage(admitted, raw, warnings, failures)

    def _check_html_coverage(
        self,
        artifact: shapes.AcquiredArtifact,
        metrics: document.ParseMetrics,
        warnings: list[document.ParseWarning],
        failures: list[str],
    ) -> None:
        """Check extracted characters against source byte size."""
        if artifact.size_bytes <= 0:
            return
        ratio = metrics.characters / artifact.size_bytes
        if (
            ratio >= self._policy.html_min_extracted_ratio
            and metrics.characters >= self._policy.html_min_extracted_characters
        ):
            return
        message = (
            f"extracted {metrics.characters} characters from "
            f"{artifact.size_bytes} bytes (ratio {ratio:.4f}); policy "
            f"requires ratio >= {self._policy.html_min_extracted_ratio} "
            f"and >= {self._policy.html_min_extracted_characters} "
            "characters"
        )
        warnings.append(
            document.ParseWarning(
                code=quality.WarningCode.COVERAGE_BELOW_THRESHOLD,
                message=message,
            )
        )
        failures.append(message)

    def _check_pdf_coverage(
        self,
        admitted: list[document.Block],
        raw: shapes.RawParseResult,
        warnings: list[document.ParseWarning],
        failures: list[str],
    ) -> None:
        """Check pages emitted against the container page count."""
        if (
            not self._policy.require_exact_pdf_page_coverage
            or raw.page_count is None
        ):
            return
        emitted = len(
            {
                block.locator.page
                for block in admitted
                if block.locator.page is not None
            }
        )
        if emitted == raw.page_count:
            return
        message = (
            f"emitted content for {emitted} pages, but the container "
            f"reports {raw.page_count}"
        )
        warnings.append(
            document.ParseWarning(
                code=quality.WarningCode.COVERAGE_BELOW_THRESHOLD,
                message=message,
            )
        )
        failures.append(message)

    def _check_expectation(
        self,
        artifact: shapes.AcquiredArtifact,
        raw: shapes.RawParseResult,
        warnings: list[document.ParseWarning],
        failures: list[str],
    ) -> None:
        """Compare the parsed source type with what the caller expected.

        The most common real-world failure is not a corrupt file: it is
        a well-formed HTML page that is an EDGAR search result or an
        error page rather than the filing that was requested. Extraction
        succeeds; the evidence is garbage (03 §7.2).
        """
        expected = artifact.expected_source_type
        if expected is None or expected is raw.source_type:
            return
        message = (
            f"caller expected source_type {expected.value}, parsed "
            f"{raw.source_type.value}"
        )
        warnings.append(
            document.ParseWarning(
                code=quality.WarningCode.EXPECTATION_MISMATCH,
                message=message,
            )
        )
        failures.append(message)

    def _check_sec_identity(
        self,
        raw: shapes.RawParseResult,
        warnings: list[document.ParseWarning],
    ) -> None:
        """Check that SEC filing identity survived parsing (03 §7.3).

        CIK, form, and period are required for a filing. Losing any of
        them is a ``partial`` verdict rather than a failure, because
        03 §6 makes loss of SEC filing identity a *severe-partial*
        escalation trigger — the route spends its one fallback on it,
        which would be redundant if the document had already failed.
        """
        if raw.source_type is not document.SourceType.SEC_FILING:
            return
        metadata = raw.business_metadata
        missing = [
            name
            for name, value in (
                ("company", metadata.company),
                ("cik", metadata.cik),
                ("document_type", metadata.document_type),
                ("reporting_period", metadata.reporting_period),
            )
            if not value
        ]
        if missing:
            warnings.append(
                document.ParseWarning(
                    code=quality.WarningCode.SEC_IDENTITY_INCOMPLETE,
                    message=(
                        "SEC filing identity is incomplete: missing "
                        + ", ".join(missing)
                    ),
                )
            )
