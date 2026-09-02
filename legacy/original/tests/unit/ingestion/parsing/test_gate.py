"""Tests for the quality gate (03 §7)."""

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import gate as gate_module
from ingestion.parsing import shapes

_CAPABILITIES = capabilities_module.AdapterCapabilities(
    block_types=frozenset(
        {
            document.BlockType.HEADING,
            document.BlockType.PARAGRAPH,
            document.BlockType.TABLE,
        }
    ),
    native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
    table_fidelity=capabilities_module.TableFidelity.GRID,
    locator_tiers=frozenset(
        {quality.LocatorTier.ANCHORED, quality.LocatorTier.COARSE}
    ),
    page_fidelity=True,
)

_PROFILE = capabilities_module.RouteProfile(
    role=capabilities_module.RouteRole.SEC_HTML_PARSER,
    min_locator_tier=quality.LocatorTier.COARSE,
)


def _block(text="Some prose about revenue.", locator=None, block_type=None):
    """Build one admitted-shaped block."""
    return document.Block(
        block_id=f"b-{text[:8]}-{id(text) % 97}",
        type=block_type or document.BlockType.PARAGRAPH,
        text=text,
        locator=locator or document.Locator(html_anchor="a1"),
        extraction=document.BlockExtraction(
            adapter_name="t", adapter_version="1"
        ),
    )


def _artifact(size_bytes=10_000, expected=None):
    """Build an artifact for the gate's independent measures."""
    return shapes.AcquiredArtifact(
        path="/dev/null",
        content_hash="sha256:x",
        size_bytes=size_bytes,
        document_id="d",
        version_id="v",
        source_class=document.SourceClass.SEC_FILING,
        expected_source_type=expected,
    )


def _raw(source_type=None, page_count=None, metadata=None, warnings=None):
    """Build a raw adapter result carrying only what the gate reads."""
    return shapes.RawParseResult(
        content=shapes.BlockSequence(blocks=[]),
        source_type=source_type or document.SourceType.MARKDOWN_DOCUMENT,
        business_metadata=metadata or document.BusinessMetadata(),
        adapter_name="t",
        adapter_version="1",
        page_count=page_count,
        warnings=list(warnings or []),
    )


def _evaluate(blocks, artifact=None, raw=None, policy=None, profile=None):
    """Run the gate over a block list."""
    return gate_module.QualityGate(policy).evaluate(
        blocks=blocks,
        artifact=artifact or _artifact(),
        raw=raw or _raw(),
        adapter_capabilities=_CAPABILITIES,
        profile=profile or _PROFILE,
    )


class TestVerdicts:
    """valid, partial, and failed are distinguishable (03 §7.4)."""

    def test_clean_parse_is_valid(self):
        """No rejections and no warnings means valid."""
        outcome = _evaluate([_block()])
        assert outcome.verdict is quality.QualityVerdict.VALID
        assert outcome.policy_version == "v0"

    def test_a_rejected_block_makes_the_document_partial(self):
        """Useful content survives a bad block."""
        outcome = _evaluate([_block(), _block(text="   ")])
        assert outcome.verdict is quality.QualityVerdict.PARTIAL
        assert len(outcome.admitted) == 1
        assert (
            outcome.rejected[0].reason
            is quality.BlockRejectionReason.EMPTY_TEXT
        )

    def test_no_admitted_block_fails_loudly(self):
        """An empty extraction is a failure, never an empty document."""
        outcome = _evaluate([_block(text="  ")])
        assert outcome.verdict is quality.QualityVerdict.FAILED
        assert not outcome.admitted

    def test_an_adapter_warning_makes_the_document_partial(self):
        """A warning the adapter raised travels into the verdict."""
        outcome = _evaluate(
            [_block()],
            raw=_raw(
                warnings=[
                    document.ParseWarning(
                        code=quality.WarningCode.TABLE_STRUCTURE_LOST,
                        message="one table was flattened",
                    )
                ]
            ),
        )
        assert outcome.verdict is quality.QualityVerdict.PARTIAL


class TestPerBlockAdmission:
    """Admission is per block, with a recorded reason (03 §7.4)."""

    def test_undeclared_block_type_is_rejected(self):
        """The gate asserts what the adapter promised (03 §3.5)."""
        outcome = _evaluate(
            [_block(), _block(block_type=document.BlockType.CODE)]
        )
        reasons = {item.reason for item in outcome.rejected}
        assert quality.BlockRejectionReason.UNDECLARED_BLOCK_TYPE in reasons
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.CAPABILITY_OVERSTATED in codes

    def test_locator_below_the_route_minimum_is_rejected(self):
        """A diagnostic-only locator never satisfies an MVP route."""
        outcome = _evaluate(
            [
                _block(),
                _block(
                    text="orphan text",
                    locator=document.Locator(element_index=3),
                ),
            ]
        )
        reasons = {item.reason for item in outcome.rejected}
        assert (
            quality.BlockRejectionReason.UNDECLARED_LOCATOR_TIER in reasons
            or quality.BlockRejectionReason.LOCATOR_TIER_BELOW_MINIMUM
            in reasons
        )

    def test_out_of_order_block_is_rejected(self):
        """Block order must be monotonic in its primary dimension."""
        outcome = _evaluate(
            [
                _block(text="page two prose", locator=document.Locator(page=2)),
                _block(text="page one prose", locator=document.Locator(page=1)),
            ]
        )
        reasons = {item.reason for item in outcome.rejected}
        assert quality.BlockRejectionReason.ORDERING_VIOLATION in reasons
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.BLOCK_ORDER_UNSTABLE in codes

    def test_rejected_blocks_keep_their_reason(self):
        """Rejections are persisted for diagnosis, not dropped."""
        outcome = _evaluate([_block(), _block(text=" ")])
        assert outcome.rejected[0].detail


class TestCoverage:
    """Coverage is measured against an independent signal (03 §7.2)."""

    def test_html_shortfall_fails(self):
        """A parser returning a fragment of a filing is caught."""
        outcome = _evaluate(
            [_block(text="tiny")],
            artifact=_artifact(size_bytes=500_000),
            raw=_raw(source_type=document.SourceType.SEC_FILING),
        )
        assert outcome.verdict is quality.QualityVerdict.FAILED
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.COVERAGE_BELOW_THRESHOLD in codes

    def test_html_coverage_passes_on_a_healthy_filing(self):
        """A few percent text by byte is normal for inline XBRL."""
        blocks = [
            _block(text=f"Paragraph {index} " + "revenue " * 40)
            for index in range(10)
        ]
        outcome = _evaluate(
            blocks,
            artifact=_artifact(size_bytes=200_000),
            raw=_raw(
                source_type=document.SourceType.SEC_FILING,
                metadata=document.BusinessMetadata(
                    company="Stub",
                    cik="320193",
                    document_type="10-K",
                    reporting_period="Q3",
                ),
            ),
        )
        assert outcome.verdict is quality.QualityVerdict.VALID

    def test_pdf_page_shortfall_fails(self):
        """Page 1 of 200 without an error is exactly the failure."""
        outcome = _evaluate(
            [_block(locator=document.Locator(page=1))],
            raw=_raw(
                source_type=document.SourceType.PDF_DOCUMENT, page_count=200
            ),
        )
        assert outcome.verdict is quality.QualityVerdict.FAILED

    def test_pdf_full_coverage_passes(self):
        """Every page accounted for is a clean parse."""
        outcome = _evaluate(
            [
                _block(text="page one", locator=document.Locator(page=1)),
                _block(text="page two", locator=document.Locator(page=2)),
            ],
            raw=_raw(
                source_type=document.SourceType.PDF_DOCUMENT, page_count=2
            ),
        )
        assert outcome.verdict is quality.QualityVerdict.VALID


class TestExpectationAndIdentity:
    """The failure that is not a corrupt file (03 §7.2, §7.3)."""

    def test_expectation_mismatch_fails(self):
        """An EDGAR error page parses fine and is still garbage."""
        outcome = _evaluate(
            [_block()],
            artifact=_artifact(expected=document.SourceType.SEC_FILING),
            raw=_raw(source_type=document.SourceType.GENERIC_HTML),
        )
        assert outcome.verdict is quality.QualityVerdict.FAILED
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.EXPECTATION_MISMATCH in codes

    def test_matching_expectation_passes(self):
        """A declared expectation that holds raises nothing."""
        outcome = _evaluate(
            [_block()],
            artifact=_artifact(expected=document.SourceType.MARKDOWN_DOCUMENT),
        )
        assert outcome.verdict is quality.QualityVerdict.VALID

    def test_incomplete_sec_identity_warns(self):
        """Lost filing identity is visible, not silent."""
        blocks = [
            _block(text=f"Paragraph {index} " + "revenue " * 40)
            for index in range(10)
        ]
        outcome = _evaluate(
            blocks,
            artifact=_artifact(size_bytes=200_000),
            raw=_raw(source_type=document.SourceType.SEC_FILING),
        )
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.SEC_IDENTITY_INCOMPLETE in codes

    def test_a_missing_cik_is_missing_sec_identity(self):
        """CIK is required for a filing (03 §7.3)."""
        blocks = [
            _block(text=f"Paragraph {index} " + "revenue " * 40)
            for index in range(10)
        ]
        outcome = _evaluate(
            blocks,
            artifact=_artifact(size_bytes=200_000),
            raw=_raw(
                source_type=document.SourceType.SEC_FILING,
                metadata=document.BusinessMetadata(
                    company="Stub",
                    document_type="10-K",
                    reporting_period="Q3",
                ),
            ),
        )
        warnings = [
            warning
            for warning in outcome.warnings
            if warning.code is quality.WarningCode.SEC_IDENTITY_INCOMPLETE
        ]
        assert warnings
        assert "cik" in warnings[0].message
        assert outcome.verdict is quality.QualityVerdict.PARTIAL

    def test_a_missing_cik_does_not_matter_off_the_sec_route(self):
        """Only filings are held to filing identity."""
        outcome = _evaluate([_block()])
        codes = {warning.code for warning in outcome.warnings}
        assert quality.WarningCode.SEC_IDENTITY_INCOMPLETE not in codes


class TestPolicy:
    """Thresholds are versioned policy, not constants (03 §7.1)."""

    def test_a_stricter_policy_changes_the_verdict(self):
        """The same parse under a different policy can fail."""
        blocks = [
            _block(text=f"Paragraph {index} " + "revenue " * 40)
            for index in range(10)
        ]
        strict = gate_module.QualityPolicy(
            version="test-strict", html_min_extracted_characters=1_000_000
        )
        outcome = _evaluate(
            blocks,
            artifact=_artifact(size_bytes=200_000),
            raw=_raw(source_type=document.SourceType.SEC_FILING),
            policy=strict,
        )
        assert outcome.verdict is quality.QualityVerdict.FAILED
        assert outcome.policy_version == "test-strict"

    def test_the_news_boilerplate_ratio_has_no_v0_value(self):
        """The one threshold deliberately left unset (03 §18)."""
        assert gate_module.POLICY_V0.news_max_boilerplate_ratio is None

    def test_metrics_are_reported(self):
        """Metrics count what was emitted and what was admitted."""
        outcome = _evaluate([_block(), _block(text="  ")])
        assert outcome.metrics.blocks_emitted == 2
        assert outcome.metrics.blocks_admitted == 1
        assert outcome.metrics.characters > 0
