"""Tests for the parse manifest and ``parse_id`` (03 §5.1)."""

import pydantic
import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import manifest as manifest_module
from ingestion.parsing import shapes

_CAPABILITIES = capabilities_module.AdapterCapabilities(
    block_types=frozenset({document.BlockType.PARAGRAPH}),
    native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
    table_fidelity=capabilities_module.TableFidelity.GRID,
    locator_tiers=frozenset({quality.LocatorTier.ANCHORED}),
)


def _attempt(name="stub", is_fallback=False, **overrides):
    """Build one planned attempt."""
    attempt = manifest_module.build_planned_attempt(
        adapter_name=name,
        adapter_version="1.0",
        adapter_capabilities=_CAPABILITIES,
        is_fallback=is_fallback,
        library_versions={"lxml": "5.2.0"},
    )
    return attempt.model_copy(update=overrides) if overrides else attempt


def _planned(attempts=None, **overrides):
    """Build a planned manifest with optional overrides."""
    planned = manifest_module.build_planned_manifest(
        role=capabilities_module.RouteRole.SEC_HTML_PARSER,
        attempts=[_attempt()] if attempts is None else attempts,
        quality_policy_version="v0",
    )
    return planned.model_copy(update=overrides) if overrides else planned


class TestParseId:
    """Identity is a pure function of bytes plus configuration."""

    def test_is_computable_before_parsing(self):
        """No adapter output is needed to derive the identity."""
        assert manifest_module.compute_parse_id(
            "sha256:bytes", _planned()
        ).startswith("sha256:")

    def test_is_stable_for_identical_inputs(self):
        """The same pipeline over the same bytes gives one identity."""
        assert manifest_module.compute_parse_id(
            "sha256:bytes", _planned()
        ) == manifest_module.compute_parse_id("sha256:bytes", _planned())

    def test_changes_with_the_content_hash(self):
        """Different bytes are a different parse."""
        assert manifest_module.compute_parse_id(
            "sha256:a", _planned()
        ) != manifest_module.compute_parse_id("sha256:b", _planned())

    @pytest.mark.parametrize(
        "field,value",
        [
            ("adapter_name", "other"),
            ("adapter_version", "2.0"),
            ("library_versions", {"lxml": "6.0.0"}),
            (
                "extraction_class",
                capabilities_module.ExtractionClass.GENERATIVE,
            ),
            (
                "determinism",
                capabilities_module.Determinism.OPAQUE_REMOTE,
            ),
            ("converter_version", "blocks/2.0"),
            ("native_shape", shapes.NativeShape.MARKDOWN_DOCUMENT),
            ("endpoint_host", "parser.example.com"),
            ("pinned_service_version", "2026-08-01"),
        ],
    )
    def test_every_attempt_field_changes_it(self, field, value):
        """Any change to a registered attempt re-parses the corpus."""
        base = manifest_module.compute_parse_id("sha256:b", _planned())
        changed = manifest_module.compute_parse_id(
            "sha256:b", _planned(attempts=[_attempt(**{field: value})])
        )
        assert base != changed

    @pytest.mark.parametrize(
        "field,value",
        [
            ("normalizer_version", "2.0"),
            ("quality_policy_version", "v1"),
            ("schema_version", "2.0"),
            (
                "route_role",
                capabilities_module.RouteRole.PDF_LAYOUT_PARSER,
            ),
        ],
    )
    def test_every_manifest_field_changes_it(self, field, value):
        """Pipeline-wide versions are part of the identity too."""
        base = manifest_module.compute_parse_id("sha256:b", _planned())
        changed = manifest_module.compute_parse_id(
            "sha256:b", _planned(**{field: value})
        )
        assert base != changed

    def test_registering_a_fallback_changes_it(self):
        """A route whose fallback changed is a different pipeline."""
        primary_only = _planned()
        with_fallback = _planned(
            attempts=[_attempt(), _attempt("other", is_fallback=True)]
        )
        assert manifest_module.compute_parse_id(
            "sha256:b", primary_only
        ) != manifest_module.compute_parse_id("sha256:b", with_fallback)

    def test_changing_the_fallback_changes_it(self):
        """Swapping only the fallback still re-parses the corpus."""
        first = _planned(
            attempts=[_attempt(), _attempt("fallback_a", is_fallback=True)]
        )
        second = _planned(
            attempts=[_attempt(), _attempt("fallback_b", is_fallback=True)]
        )
        assert manifest_module.compute_parse_id(
            "sha256:b", first
        ) != manifest_module.compute_parse_id("sha256:b", second)


class TestPlannedAttempts:
    """Every registered attempt is described before any of them runs."""

    def test_converter_version_follows_the_declared_shape(self):
        """The declared shape fixes the converter version up front."""
        for shape in shapes.NativeShape:
            capabilities = _CAPABILITIES.model_copy(
                update={"native_shape": shape}
            )
            attempt = manifest_module.build_planned_attempt(
                adapter_name="stub",
                adapter_version="1.0",
                adapter_capabilities=capabilities,
            )
            assert (
                attempt.converter_version
                == manifest_module.CONVERTER_VERSIONS[shape]
            )

    def test_the_fallback_carries_its_own_converter_version(self):
        """A fallback of another shape names its own converter."""
        markdown = _CAPABILITIES.model_copy(
            update={"native_shape": shapes.NativeShape.MARKDOWN_DOCUMENT}
        )
        planned = _planned(
            attempts=[
                _attempt(),
                manifest_module.build_planned_attempt(
                    adapter_name="hosted",
                    adapter_version="1.0",
                    adapter_capabilities=markdown,
                    is_fallback=True,
                ),
            ]
        )
        versions = {attempt.converter_version for attempt in planned.attempts}
        assert len(versions) == 2

    def test_the_primary_is_reachable(self):
        """The primary attempt is the first one, and named."""
        planned = _planned(
            attempts=[_attempt(), _attempt("other", is_fallback=True)]
        )
        assert planned.primary.adapter_name == "stub"
        assert planned.primary.is_fallback is False

    def test_a_manifest_needs_an_attempt(self):
        """A route with no adapter is not a pipeline."""
        with pytest.raises(pydantic.ValidationError, match="at least one"):
            _planned(attempts=[])

    def test_the_primary_must_come_first(self):
        """Ordering is part of the shape, not a convention."""
        with pytest.raises(pydantic.ValidationError, match="first"):
            _planned(attempts=[_attempt("f", is_fallback=True)])

    def test_exactly_one_primary(self):
        """Two primaries is not a route."""
        with pytest.raises(pydantic.ValidationError, match="one primary"):
            _planned(attempts=[_attempt("a"), _attempt("b")])

    def test_an_adapter_appears_once_per_route(self):
        """Binding one adapter as its own fallback is meaningless."""
        with pytest.raises(pydantic.ValidationError, match="once"):
            _planned(attempts=[_attempt("same"), _attempt("same", True)])


def test_canonical_payload_is_key_order_independent():
    """Field construction order cannot change the identity."""
    payload = manifest_module.canonical_planned_payload(_planned())
    assert payload == manifest_module.canonical_planned_payload(
        manifest_module.PlannedManifest.model_validate_json(payload)
    )


def test_observed_manifest_records_both_attempts():
    """Both the failed and accepted attempts are recorded (03 §3.3)."""
    observed = manifest_module.ObservedManifest(
        attempts=[
            manifest_module.ParseAttempt(
                role=capabilities_module.RouteRole.SEC_HTML_PARSER,
                adapter_name="primary",
                adapter_version="1.0",
                error="boom",
            ),
            manifest_module.ParseAttempt(
                role=capabilities_module.RouteRole.SEC_HTML_PARSER,
                adapter_name="fallback",
                adapter_version="1.0",
                is_fallback=True,
                verdict=quality.QualityVerdict.PARTIAL,
            ),
        ],
        fallback_used=True,
    )
    assert len(observed.attempts) == 2
    assert observed.attempts[0].error == "boom"


def test_raw_output_digest_detects_drift():
    """An opaque vendor changing its output is at least detectable."""
    first = shapes.RawParseResult(
        content=shapes.MarkdownDocument(markdown="a"),
        source_type=document.SourceType.PDF_DOCUMENT,
        adapter_name="hosted",
        adapter_version="1.0",
    )
    second = first.model_copy(
        update={"content": shapes.MarkdownDocument(markdown="b")}
    )
    assert manifest_module.raw_output_digest(
        first
    ) != manifest_module.raw_output_digest(second)
