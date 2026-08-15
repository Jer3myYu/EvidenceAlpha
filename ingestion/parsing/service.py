"""``ParserService.parse`` — the parser subsystem entrypoint (02 §9.3).

One acquired artifact in, one :class:`ParserResult` out. Serializable in
and out, no global state, bounded execution, and no network access
(03 §3.1, decision Q22).

The pipeline, and the two places it can stop early:

1. bounded-execution and encryption checks, before any dispatch, so an
   encrypted file fails with its own error rather than consuming the one
   permitted fallback;
2. detection — ``ambiguous`` or ``unsupported`` is a controlled failure,
   never a guess;
3. route resolution — a detected format with no registered adapter
   returns ``UNSUPPORTED_FORMAT`` with the format named and
   ``retry_with: none``. It never falls through to a text adapter;
4. ``parse_id`` from the planned manifest — which describes **every**
   registered attempt on the route, the fallback included — before
   parsing;
5. the primary attempt: egress decision, adapter, shape check, shared
   converter, quality gate;
6. **one** fallback, and only when the gate said ``failed`` or the route
   declared one of the observed warnings severe enough to escalate. The
   better of the two results is kept, and both attempts are recorded in
   the observed manifest.

``parse_id`` is the same whichever attempt produced the accepted output,
because the manifest describes the configured route rather than the
outcome. For a fixed artifact and a fixed planned manifest, whether the
primary fails is itself determined, so identity loses nothing by
excluding the outcome — and gains being computable up front (03 §5.1).
"""

import time

import pydantic

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector as detector_module
from ingestion.parsing import gate as gate_module
from ingestion.parsing import manifest as manifest_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import base
from ingestion.parsing.converters import blocks as blocks_converter
from ingestion.parsing.converters import common
from ingestion.parsing.converters import elements as elements_converter
from ingestion.parsing.converters import markdown as markdown_converter

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")

_VERDICT_RANK: dict[quality.QualityVerdict, int] = {
    quality.QualityVerdict.FAILED: 0,
    quality.QualityVerdict.PARTIAL: 1,
    quality.QualityVerdict.VALID: 2,
}


class ParserError(pydantic.BaseModel):
    """A controlled parser failure (03 §8.3).

    ``retry_with`` replaces a bare ``retryable`` boolean: for a local
    adapter, re-running the identical call can never produce a different
    outcome, so a boolean is always misleading. The mapping to the
    tool-facing boolean of 02 §15 is made once, at the ingestion/tool
    boundary, and nowhere inside the parser.
    """

    model_config = _MODEL_CONFIG

    code: shapes.ParserErrorCode
    message: str
    retry_with: shapes.RetryWith = shapes.RetryWith.NONE


class ParserResult(pydantic.BaseModel):
    """The parser's structured result (03 §8.3)."""

    model_config = _MODEL_CONFIG

    status: quality.QualityVerdict
    document_id: str
    version_id: str
    parse_id: str | None = None
    detected_format: detector_module.DetectedFormat | None = None
    resolution: detector_module.Resolution | None = None
    parser_used: str | None = None
    fallback_used: bool = False
    retry_with: shapes.RetryWith = shapes.RetryWith.NONE
    warnings: list[document.ParseWarning] = pydantic.Field(default_factory=list)
    metrics: document.ParseMetrics = pydantic.Field(
        default_factory=document.ParseMetrics
    )
    manifest: manifest_module.ParseManifest | None = None
    parsed_document: document.ParsedDocument | None = None
    error: ParserError | None = None

    @pydantic.model_validator(mode="after")
    def _check_failure_carries_error(self) -> "ParserResult":
        """A failed result must say why, and carry no document."""
        if self.status is quality.QualityVerdict.FAILED:
            if self.error is None:
                raise ValueError("a failed result must carry an error")
            if self.parsed_document is not None:
                raise ValueError("a failed result carries no document")
        elif self.error is not None:
            raise ValueError("only a failed result carries an error")
        return self


class _Attempt:
    """One adapter attempt and everything it produced."""

    def __init__(
        self,
        role: capabilities_module.RouteRole,
        adapter: base.ParserAdapter,
        is_fallback: bool,
    ) -> None:
        """Initialize an attempt record.

        Args:
          role: The route role being served.
          adapter: The adapter that ran.
          is_fallback: Whether this was the fallback attempt.
        """
        self.role = role
        self.adapter = adapter
        self.is_fallback = is_fallback
        self.raw: shapes.RawParseResult | None = None
        self.outcome: gate_module.GateOutcome | None = None
        self.error: str | None = None

    def record(self) -> manifest_module.ParseAttempt:
        """Return this attempt as a manifest entry.

        Returns:
          The manifest record for the observed half.
        """
        return manifest_module.ParseAttempt(
            role=self.role,
            adapter_name=self.adapter.name,
            adapter_version=self.adapter.version,
            is_fallback=self.is_fallback,
            verdict=self.outcome.verdict if self.outcome else None,
            error=self.error,
        )


class ParserService:
    """Converts one acquired artifact into one parsed document."""

    def __init__(
        self,
        registry: registry_module.AdapterRegistry | None = None,
        detector: detector_module.FormatDetector | None = None,
        gate: gate_module.QualityGate | None = None,
    ) -> None:
        """Initialize the service.

        Args:
          registry: The validated adapter registry;
            :data:`ingestion.parsing.registry.DEFAULT_REGISTRY` when
            omitted.
          detector: The format detector; a default one when omitted.
          gate: The quality gate; one at policy v0 when omitted.
        """
        self._registry = registry or registry_module.DEFAULT_REGISTRY
        self._detector = detector or detector_module.FormatDetector()
        self._gate = gate or gate_module.QualityGate()

    def parse(self, artifact: shapes.AcquiredArtifact) -> ParserResult:
        """Parse one acquired artifact.

        Args:
          artifact: The already-acquired artifact. Source policy, size
            limits, acquisition, and hashing have all already happened
            (02 §9.3); this method fetches nothing.

        Returns:
          A :class:`ParserResult`. A failure is always a controlled
          result carrying a code and a ``retry_with`` value; the service
          never returns a silent empty document.
        """
        started = time.monotonic()
        if artifact.size_bytes > artifact.limits.max_bytes:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.PARSER_BUDGET_EXCEEDED,
                (
                    f"artifact is {artifact.size_bytes} bytes, above the "
                    f"{artifact.limits.max_bytes} byte parse limit"
                ),
                shapes.RetryWith.LARGER_BUDGET,
            )

        try:
            detection = self._detector.detect(artifact)
        except detector_module.DetectionError as error:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.PARSE_FAILED,
                f"detection failed: {error}",
                shapes.RetryWith.DIFFERENT_SOURCE,
            )

        stop = self._pre_dispatch_failure(artifact, detection)
        if stop is not None:
            return stop

        role = self._registry.resolve(detection.format)
        binding = self._registry.binding_for(role) if role is not None else None
        if role is None or binding is None:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.UNSUPPORTED_FORMAT,
                (
                    f"detected format {detection.format.value!r} has no "
                    "registered adapter"
                ),
                shapes.RetryWith.NONE,
                detection=detection,
            )

        return self._run_route(artifact, detection, role, binding, started)

    def _pre_dispatch_failure(
        self,
        artifact: shapes.AcquiredArtifact,
        detection: detector_module.DetectionResult,
    ) -> ParserResult | None:
        """Return a controlled failure that precedes any dispatch."""
        if detection.encrypted:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.ENCRYPTED_DOCUMENT,
                (
                    "the artifact is encrypted or password protected; "
                    "detected before dispatch so it does not consume the "
                    "one permitted fallback"
                ),
                shapes.RetryWith.DIFFERENT_SOURCE,
                detection=detection,
            )
        if detection.resolution is detector_module.Resolution.AMBIGUOUS:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.PARSE_FAILED,
                (
                    "format detection was ambiguous: "
                    + "; ".join(detection.conflicts or detection.signals)
                ),
                shapes.RetryWith.DIFFERENT_SOURCE,
                detection=detection,
            )
        if detection.resolution is detector_module.Resolution.UNSUPPORTED:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.UNSUPPORTED_FORMAT,
                (
                    f"format {detection.format.value!r} is outside the "
                    "supported set"
                ),
                shapes.RetryWith.NONE,
                detection=detection,
            )
        return None

    def _run_route(
        self,
        artifact: shapes.AcquiredArtifact,
        detection: detector_module.DetectionResult,
        role: capabilities_module.RouteRole,
        binding: registry_module.Binding,
        started: float,
    ) -> ParserResult:
        """Run the primary attempt, then at most one fallback."""
        primary = self._registry.adapter(binding.primary)
        fallback = (
            self._registry.adapter(binding.fallback)
            if binding.fallback is not None
            else None
        )
        planned_attempts = [
            manifest_module.build_planned_attempt(
                adapter_name=primary.name,
                adapter_version=primary.version,
                adapter_capabilities=primary.capabilities,
            )
        ]
        if fallback is not None:
            planned_attempts.append(
                manifest_module.build_planned_attempt(
                    adapter_name=fallback.name,
                    adapter_version=fallback.version,
                    adapter_capabilities=fallback.capabilities,
                    is_fallback=True,
                )
            )
        planned = manifest_module.build_planned_manifest(
            role=role,
            attempts=planned_attempts,
            quality_policy_version=self._gate.policy.version,
        )
        parse_id = manifest_module.compute_parse_id(
            artifact.version_id, planned
        )

        denial = self._egress_denial(artifact, primary)
        if denial is not None:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.PARSER_EGRESS_DENIED,
                denial,
                shapes.RetryWith.NONE,
                detection=detection,
                parse_id=parse_id,
            )

        request = base.ParseRequest(artifact=artifact, detection=detection)
        attempts = [self._attempt(request, role, primary, parse_id, False)]
        if fallback is not None and self._should_escalate(attempts[0], binding):
            if self._egress_denial(artifact, fallback) is None:
                attempts.append(
                    self._attempt(request, role, fallback, parse_id, True)
                )

        best = self._best(attempts)
        elapsed = time.monotonic() - started
        if elapsed > artifact.limits.wall_clock_seconds:
            return self._failure(
                artifact,
                shapes.ParserErrorCode.PARSER_BUDGET_EXCEEDED,
                (
                    f"parsing took {elapsed:.1f}s, above the "
                    f"{artifact.limits.wall_clock_seconds}s budget; "
                    "partial work is discarded, not emitted"
                ),
                shapes.RetryWith.LARGER_BUDGET,
                detection=detection,
                parse_id=parse_id,
            )
        return self._result(
            artifact, detection, planned, parse_id, attempts, best
        )

    def _attempt(
        self,
        request: base.ParseRequest,
        role: capabilities_module.RouteRole,
        adapter: base.ParserAdapter,
        parse_id: str,
        is_fallback: bool,
    ) -> _Attempt:
        """Run one adapter and gate its output."""
        attempt = _Attempt(role, adapter, is_fallback)
        if not adapter.supports(request):
            attempt.error = f"adapter {adapter.name!r} declined the request"
            return attempt
        try:
            raw = adapter.parse(request)
        except base.AdapterError as error:
            attempt.error = f"adapter {adapter.name!r} failed: {error}"
            return attempt

        observed_shape = shapes.shape_of(raw.content)
        if observed_shape is not adapter.capabilities.native_shape:
            attempt.error = (
                f"adapter {adapter.name!r} declared native shape "
                f"{adapter.capabilities.native_shape.value} but returned "
                f"{observed_shape.value}"
            )
            return attempt

        attempt.raw = raw
        context = common.ConversionContext(
            parse_id=parse_id,
            adapter_name=adapter.name,
            adapter_version=adapter.version,
            adapter_capabilities=adapter.capabilities,
            ocr_used=raw.ocr_used,
            ocr_confidence=raw.ocr_confidence,
        )
        blocks = _convert(raw.content, context)
        attempt.outcome = self._gate.evaluate(
            blocks=blocks,
            artifact=request.artifact,
            raw=raw,
            adapter_capabilities=adapter.capabilities,
            profile=self._registry.profile_for(role),
            conversion_warnings=context.warnings,
        )
        return attempt

    def _egress_denial(
        self,
        artifact: shapes.AcquiredArtifact,
        adapter: base.ParserAdapter,
    ) -> str | None:
        """Return the denial reason, or None when transmission is fine."""
        decision = self._registry.egress_policy.allows(
            artifact.source_class, adapter.capabilities
        )
        return None if decision.allowed else decision.reason

    def _should_escalate(
        self, attempt: _Attempt, binding: registry_module.Binding
    ) -> bool:
        """Decide whether the one permitted fallback is worth running.

        ``failed`` is the default trigger. A route may also declare
        warning codes whose presence in a ``partial`` result is worth
        spending the fallback on (03 §6).
        """
        if attempt.outcome is None:
            return True
        if attempt.outcome.failed:
            return True
        if attempt.outcome.verdict is not quality.QualityVerdict.PARTIAL:
            return False
        observed = {warning.code for warning in attempt.outcome.warnings}
        for block in attempt.outcome.admitted:
            observed.update(
                warning.code for warning in block.extraction.warnings
            )
        return bool(observed & binding.severe_partial_warnings)

    def _best(self, attempts: list[_Attempt]) -> _Attempt:
        """Return the attempt whose result should be kept.

        If the fallback came back worse, the better of the two is kept
        (03 §6).
        """

        def rank(attempt: _Attempt) -> tuple[int, int]:
            if attempt.outcome is None:
                return (-1, 0)
            return (
                _VERDICT_RANK[attempt.outcome.verdict],
                len(attempt.outcome.admitted),
            )

        return max(attempts, key=rank)

    def _result(
        self,
        artifact: shapes.AcquiredArtifact,
        detection: detector_module.DetectionResult,
        planned: manifest_module.PlannedManifest,
        parse_id: str,
        attempts: list[_Attempt],
        best: _Attempt,
    ) -> ParserResult:
        """Assemble the final result from the accepted attempt."""
        observed = manifest_module.ObservedManifest(
            attempts=[attempt.record() for attempt in attempts],
            fallback_used=best.is_fallback,
            warnings=(list(best.outcome.warnings) if best.outcome else []),
            metrics=(
                best.outcome.metrics
                if best.outcome
                else document.ParseMetrics()
            ),
            rejected_block_count=(
                len(best.outcome.rejected) if best.outcome else 0
            ),
            vendor_reported_version=(
                best.raw.vendor_reported_version if best.raw else None
            ),
            raw_output_digest=(
                manifest_module.raw_output_digest(best.raw)
                if best.raw
                else None
            ),
        )
        manifest = manifest_module.ParseManifest(
            planned=planned, observed=observed
        )

        raw = best.raw
        if best.outcome is None or best.outcome.failed or raw is None:
            message = best.error or "the quality gate rejected the parse"
            code = (
                shapes.ParserErrorCode.PARSE_QUALITY_TOO_LOW
                if best.outcome is not None and best.outcome.failed
                else shapes.ParserErrorCode.PARSE_FAILED
            )
            return ParserResult(
                status=quality.QualityVerdict.FAILED,
                document_id=artifact.document_id,
                version_id=artifact.version_id,
                parse_id=parse_id,
                detected_format=detection.format,
                resolution=detection.resolution,
                parser_used=best.adapter.name,
                fallback_used=best.is_fallback,
                retry_with=shapes.RetryWith.NONE,
                warnings=observed.warnings,
                metrics=observed.metrics,
                manifest=manifest,
                error=ParserError(
                    code=code,
                    message=message,
                    retry_with=shapes.RetryWith.NONE,
                ),
            )

        parsed = document.ParsedDocument(
            identity=document.DocumentIdentity(
                document_id=artifact.document_id,
                version_id=artifact.version_id,
                parse_id=parse_id,
            ),
            source=document.SourceInfo(
                source_type=raw.source_type,
                source_class=artifact.source_class,
                original_url=artifact.original_url,
                canonical_url=artifact.canonical_url,
                filename=artifact.filename,
                retrieved_at=artifact.retrieved_at,
            ),
            business_metadata=raw.business_metadata,
            blocks=best.outcome.admitted,
            parse_quality=document.ParseQuality(
                verdict=best.outcome.verdict,
                policy_version=best.outcome.policy_version,
                warnings=best.outcome.warnings,
                metrics=best.outcome.metrics,
                rejected_blocks=best.outcome.rejected,
            ),
        )
        return ParserResult(
            status=best.outcome.verdict,
            document_id=artifact.document_id,
            version_id=artifact.version_id,
            parse_id=parse_id,
            detected_format=detection.format,
            resolution=detection.resolution,
            parser_used=best.adapter.name,
            fallback_used=best.is_fallback,
            retry_with=shapes.RetryWith.NONE,
            warnings=best.outcome.warnings,
            metrics=best.outcome.metrics,
            manifest=manifest,
            parsed_document=parsed,
        )

    def _failure(
        self,
        artifact: shapes.AcquiredArtifact,
        code: shapes.ParserErrorCode,
        message: str,
        retry_with: shapes.RetryWith,
        detection: detector_module.DetectionResult | None = None,
        parse_id: str | None = None,
    ) -> ParserResult:
        """Build a controlled failure result."""
        return ParserResult(
            status=quality.QualityVerdict.FAILED,
            document_id=artifact.document_id,
            version_id=artifact.version_id,
            parse_id=parse_id,
            detected_format=detection.format if detection else None,
            resolution=detection.resolution if detection else None,
            retry_with=retry_with,
            error=ParserError(
                code=code, message=message, retry_with=retry_with
            ),
        )


def _convert(
    content: shapes.NativeContent, context: common.ConversionContext
) -> list[document.Block]:
    """Dispatch to the converter for a native shape (03 §3.6)."""
    if isinstance(content, shapes.BlockSequence):
        return blocks_converter.convert(content, context)
    if isinstance(content, shapes.ElementList):
        return elements_converter.convert(content, context)
    return markdown_converter.convert(content, context)
