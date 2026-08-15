"""Tests for the parser service pipeline (03 §6, §8)."""

import zipfile

import pytest

from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector as detector_module
from ingestion.parsing import manifest as manifest_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import service as service_module
from ingestion.parsing import shapes
from tests.unit.ingestion.parsing.conformance import stub_adapters

_ROLE = capabilities_module.RouteRole.MARKDOWN_PARSER


@pytest.fixture(name="markdown_artifact")
def markdown_artifact_fixture(tmp_path):
    """Write a markdown fixture and return an artifact naming it."""
    path = tmp_path / "fixture.md"
    path.write_text("# Fixture\n\nBody text.\n", encoding="utf-8")
    return stub_adapters.make_artifact(str(path), path.stat().st_size)


def _service(*adapters, fallback=None, severe=frozenset()):
    """Build a service binding the first adapter to the markdown route."""
    registry = registry_module.AdapterRegistry(
        adapters=adapters,
        bindings={
            _ROLE: registry_module.Binding(
                primary=adapters[0].name,
                fallback=fallback,
                severe_partial_warnings=severe,
            )
        },
    )
    return service_module.ParserService(registry=registry)


class TestControlledFailures:
    """Every failure is a coded result, never an exception."""

    def test_oversize_artifact_exceeds_the_budget(self, markdown_artifact):
        """A too-large artifact is refused before any parsing."""
        artifact = markdown_artifact.model_copy(
            update={"limits": shapes.ParseLimits(max_bytes=1)}
        )
        result = _service(stub_adapters.StubMarkdownAdapter()).parse(artifact)
        assert (
            result.error.code is shapes.ParserErrorCode.PARSER_BUDGET_EXCEEDED
        )
        assert result.retry_with is shapes.RetryWith.LARGER_BUDGET

    def test_unsupported_format_is_named(self, tmp_path):
        """An ordinary archive fails with its detected name."""
        path = tmp_path / "bundle.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("notes.txt", "hello")
        artifact = stub_adapters.make_artifact(
            str(path), path.stat().st_size, filename="bundle.zip"
        )
        result = _service(stub_adapters.StubMarkdownAdapter()).parse(artifact)
        assert result.error.code is shapes.ParserErrorCode.UNSUPPORTED_FORMAT
        assert result.retry_with is shapes.RetryWith.NONE
        assert (
            result.detected_format is detector_module.DetectedFormat.ZIP_ARCHIVE
        )

    def test_ambiguous_detection_never_guesses(self, tmp_path):
        """An ambiguous container is a controlled failure."""
        path = tmp_path / "legacy.xls"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
        artifact = stub_adapters.make_artifact(
            str(path), path.stat().st_size, filename="legacy.xls"
        )
        result = _service(stub_adapters.StubMarkdownAdapter()).parse(artifact)
        assert result.error.code is shapes.ParserErrorCode.PARSE_FAILED
        assert result.retry_with is shapes.RetryWith.DIFFERENT_SOURCE

    def test_encrypted_file_fails_before_dispatch(self, tmp_path):
        """An encrypted file does not consume the fallback (03 §8.1)."""
        path = tmp_path / "locked.pdf"
        path.write_bytes(
            b"%PDF-1.7\nbody\ntrailer\n<< /Encrypt 1 0 R >>\n%%EOF"
        )
        artifact = stub_adapters.make_artifact(
            str(path), path.stat().st_size, filename="locked.pdf"
        )
        result = _service(stub_adapters.StubMarkdownAdapter()).parse(artifact)
        assert result.error.code is shapes.ParserErrorCode.ENCRYPTED_DOCUMENT
        assert result.retry_with is shapes.RetryWith.DIFFERENT_SOURCE
        assert "encrypted" in result.error.message
        assert result.manifest is None

    def test_unregistered_route_does_not_fall_through(self, markdown_artifact):
        """A detected format with no adapter never reaches a text one."""
        service = service_module.ParserService(
            registry=registry_module.AdapterRegistry()
        )
        result = service.parse(markdown_artifact)
        assert result.error.code is shapes.ParserErrorCode.UNSUPPORTED_FORMAT
        assert "markdown" in result.error.message
        assert result.parsed_document is None

    def test_a_failed_result_carries_no_document(self, markdown_artifact):
        """Nothing empty or truncated can reach the corpus."""
        result = _service(stub_adapters.EmptyAdapter()).parse(markdown_artifact)
        assert result.status is quality.QualityVerdict.FAILED
        assert result.parsed_document is None
        assert result.error is not None


class TestFallback:
    """One bounded fallback, triggered by the gate (03 §6)."""

    def test_gate_failure_triggers_the_fallback(self, markdown_artifact):
        """A failed verdict spends the one permitted fallback."""
        result = _service(
            stub_adapters.EmptyAdapter(),
            stub_adapters.StubBlockSequenceAdapter(),
            fallback="stub_block_sequence",
        ).parse(markdown_artifact)
        assert result.fallback_used is True
        assert result.status is quality.QualityVerdict.VALID
        assert result.parser_used == "stub_block_sequence"
        assert len(result.manifest.observed.attempts) == 2

    def test_a_valid_primary_does_not_spend_the_fallback(
        self, markdown_artifact
    ):
        """A clean parse never runs a second parser."""
        result = _service(
            stub_adapters.StubBlockSequenceAdapter(),
            stub_adapters.StubMarkdownAdapter(),
            fallback="stub_markdown",
        ).parse(markdown_artifact)
        assert result.fallback_used is False
        assert len(result.manifest.observed.attempts) == 1

    def test_severe_partial_escalates(self, markdown_artifact):
        """A declared severe warning is worth the fallback (03 §6)."""
        result = _service(
            stub_adapters.SeverePartialAdapter(),
            stub_adapters.StubBlockSequenceAdapter(),
            fallback="stub_block_sequence",
            severe=frozenset({quality.WarningCode.TABLE_STRUCTURE_LOST}),
        ).parse(markdown_artifact)
        assert len(result.manifest.observed.attempts) == 2
        assert result.fallback_used is True

    def test_partial_without_a_declared_warning_does_not_escalate(
        self, markdown_artifact
    ):
        """Everything else keeps the plain failed-only rule."""
        result = _service(
            stub_adapters.SeverePartialAdapter(),
            stub_adapters.StubBlockSequenceAdapter(),
            fallback="stub_block_sequence",
        ).parse(markdown_artifact)
        assert len(result.manifest.observed.attempts) == 1
        assert result.status is quality.QualityVerdict.PARTIAL

    def test_the_better_of_the_two_results_is_kept(self, markdown_artifact):
        """A worse fallback does not replace a usable primary."""
        result = _service(
            stub_adapters.SeverePartialAdapter(),
            stub_adapters.EmptyAdapter(),
            fallback="stub_empty",
            severe=frozenset({quality.WarningCode.TABLE_STRUCTURE_LOST}),
        ).parse(markdown_artifact)
        assert len(result.manifest.observed.attempts) == 2
        assert result.fallback_used is False
        assert result.status is quality.QualityVerdict.PARTIAL

    def test_parse_id_is_unchanged_by_which_attempt_won(
        self, markdown_artifact
    ):
        """Identity comes from the configuration, not the outcome.

        The fallback produced the accepted output here, and the identity
        is still exactly what the planned manifest — computed before any
        adapter ran — says it is.
        """
        result = _service(
            stub_adapters.EmptyAdapter(),
            stub_adapters.StubBlockSequenceAdapter(),
            fallback="stub_block_sequence",
        ).parse(markdown_artifact)
        assert result.fallback_used is True
        assert result.parse_id == manifest_module.compute_parse_id(
            markdown_artifact.version_id, result.manifest.planned
        )
        assert (
            result.manifest.observed.attempts[0].verdict
            is quality.QualityVerdict.FAILED
        )

    def test_registering_a_fallback_changes_parse_id(self, markdown_artifact):
        """A route whose fallback changed is a different pipeline."""
        primary_only = _service(stub_adapters.StubBlockSequenceAdapter()).parse(
            markdown_artifact
        )
        with_fallback = _service(
            stub_adapters.StubBlockSequenceAdapter(),
            stub_adapters.StubMarkdownAdapter(),
            fallback="stub_markdown",
        ).parse(markdown_artifact)
        assert primary_only.parse_id != with_fallback.parse_id
        assert with_fallback.fallback_used is False


class TestSuccessfulResult:
    """A successful parse assembles the whole contract."""

    def test_identity_source_and_quality_are_populated(self, markdown_artifact):
        """The document carries identity, source, and its verdict."""
        result = _service(stub_adapters.StubBlockSequenceAdapter()).parse(
            markdown_artifact
        )
        parsed = result.parsed_document
        assert parsed.identity.document_id == markdown_artifact.document_id
        assert parsed.identity.version_id == markdown_artifact.version_id
        assert parsed.identity.parse_id == result.parse_id
        assert parsed.source.source_class is markdown_artifact.source_class
        assert parsed.parse_quality.verdict is result.status
        assert parsed.parse_quality.policy_version == "v0"

    def test_parse_id_matches_the_planned_manifest(self, markdown_artifact):
        """The identity is reproducible from the manifest alone."""
        result = _service(stub_adapters.StubBlockSequenceAdapter()).parse(
            markdown_artifact
        )
        assert result.parse_id == manifest_module.compute_parse_id(
            markdown_artifact.version_id, result.manifest.planned
        )

    def test_business_metadata_survives(self, markdown_artifact):
        """Metadata the adapter extracted reaches the document."""
        result = _service(stub_adapters.StubBlockSequenceAdapter()).parse(
            markdown_artifact
        )
        assert (
            result.parsed_document.business_metadata.company
            == "Stub Industries"
        )

    def test_the_raw_output_digest_is_recorded(self, markdown_artifact):
        """Drift in an opaque adapter stays detectable after the fact."""
        result = _service(stub_adapters.StubBlockSequenceAdapter()).parse(
            markdown_artifact
        )
        assert result.manifest.observed.raw_output_digest
