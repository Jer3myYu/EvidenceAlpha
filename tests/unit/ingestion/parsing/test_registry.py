"""Tests for route bindings and startup validation (03 §3.3, §3.5)."""

import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector as detector_module
from ingestion.parsing import egress as egress_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import shapes


class _Adapter:
    """A minimal adapter good enough to bind to the SEC route."""

    name = "capable"
    version = "1.0"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset(
            {
                document.BlockType.HEADING,
                document.BlockType.PARAGRAPH,
                document.BlockType.TABLE,
            }
        ),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.TYPED_GRID,
        locator_tiers=frozenset({quality.LocatorTier.ANCHORED}),
        page_fidelity=True,
        extraction_class=capabilities_module.ExtractionClass.RULE_BASED,
    )

    def supports(self, request):
        """Accept every request."""
        del request
        return True

    def parse(self, request):
        """Never called in these tests."""
        raise NotImplementedError


class _WeakFallback(_Adapter):
    """A fallback that does not meet the route minimum."""

    name = "weak_fallback"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.PARAGRAPH}),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.NONE,
        locator_tiers=frozenset({quality.LocatorTier.DIAGNOSTIC}),
    )


class TestRouteResolution:
    """Detected formats resolve to roles deterministically."""

    @pytest.mark.parametrize(
        "detected,role",
        [
            (
                detector_module.DetectedFormat.SEC_INLINE_XBRL_HTML,
                capabilities_module.RouteRole.SEC_HTML_PARSER,
            ),
            (
                detector_module.DetectedFormat.SEC_HTML,
                capabilities_module.RouteRole.SEC_HTML_PARSER,
            ),
            (
                detector_module.DetectedFormat.NEWS_HTML,
                capabilities_module.RouteRole.NEWS_HTML_PARSER,
            ),
            (
                detector_module.DetectedFormat.PDF,
                capabilities_module.RouteRole.PDF_LAYOUT_PARSER,
            ),
        ],
    )
    def test_format_maps_to_role(self, detected, role):
        """SEC HTML and news HTML take different routes."""
        assert registry_module.DEFAULT_REGISTRY.resolve(detected) is role

    def test_an_archive_has_no_route(self):
        """An ordinary archive is not a document route."""
        assert (
            registry_module.DEFAULT_REGISTRY.resolve(
                detector_module.DetectedFormat.ZIP_ARCHIVE
            )
            is None
        )

    def test_only_the_mvp_routes_are_bound(self):
        """SEC HTML and digital PDF are live (03 §2.1); the rest stay
        planned routes."""
        live = {
            capabilities_module.RouteRole.SEC_HTML_PARSER: "sec_html_lxml",
            capabilities_module.RouteRole.PDF_LAYOUT_PARSER: "pdf_pymupdf",
        }
        for role in capabilities_module.RouteRole:
            binding = registry_module.DEFAULT_REGISTRY.binding_for(role)
            if role in live:
                assert binding is not None
                assert binding.primary == live[role]
                assert binding.fallback is None
            else:
                assert binding is None


class TestStartupValidation:
    """Bindings are validated when the registry is constructed."""

    def test_a_capable_adapter_binds(self):
        """An adapter meeting the profile is accepted."""
        registry = registry_module.AdapterRegistry(
            adapters=[_Adapter()],
            bindings={
                capabilities_module.RouteRole.SEC_HTML_PARSER: (
                    registry_module.Binding(primary="capable")
                )
            },
        )
        assert registry.adapter("capable").name == "capable"

    def test_a_weak_fallback_is_refused(self):
        """The fallback is held to the same route minimum."""
        with pytest.raises(registry_module.RegistryError, match="weak"):
            registry_module.AdapterRegistry(
                adapters=[_Adapter(), _WeakFallback()],
                bindings={
                    capabilities_module.RouteRole.SEC_HTML_PARSER: (
                        registry_module.Binding(
                            primary="capable", fallback="weak_fallback"
                        )
                    )
                },
            )

    def test_an_unknown_adapter_name_is_refused(self):
        """A binding naming nothing real fails at boot."""
        with pytest.raises(registry_module.RegistryError, match="unknown"):
            registry_module.AdapterRegistry(
                adapters=[_Adapter()],
                bindings={
                    capabilities_module.RouteRole.SEC_HTML_PARSER: (
                        registry_module.Binding(primary="ghost")
                    )
                },
            )

    def test_a_role_without_a_profile_binds_permissively(self):
        """Routes outside the MVP have not declared a floor yet."""
        registry = registry_module.AdapterRegistry(
            adapters=[_WeakFallback()],
            bindings={
                capabilities_module.RouteRole.PLAIN_TEXT_PARSER: (
                    registry_module.Binding(primary="weak_fallback")
                )
            },
        )
        profile = registry.profile_for(
            capabilities_module.RouteRole.PLAIN_TEXT_PARSER
        )
        assert (
            profile.min_table_fidelity is capabilities_module.TableFidelity.NONE
        )

    def test_the_egress_policy_is_consulted_at_startup(self):
        """A registry records the policy it validated against."""
        registry = registry_module.AdapterRegistry(
            adapters=[_Adapter()], bindings={}
        )
        assert isinstance(
            registry.egress_policy, egress_module.DenyAllEgressPolicy
        )

    def test_asking_for_an_unregistered_adapter_raises(self):
        """Fail loudly rather than returning None."""
        registry = registry_module.AdapterRegistry()
        with pytest.raises(registry_module.RegistryError):
            registry.adapter("absent")


class TestSeverePartialDeclaration:
    """A route may declare which warnings justify the fallback."""

    def test_binding_carries_the_escalation_set(self):
        """MVP financial routes escalate on lost table structure."""
        binding = registry_module.Binding(
            primary="capable",
            severe_partial_warnings=frozenset(
                {quality.WarningCode.TABLE_STRUCTURE_LOST}
            ),
        )
        assert (
            quality.WarningCode.TABLE_STRUCTURE_LOST
            in binding.severe_partial_warnings
        )

    def test_the_default_escalation_set_is_empty(self):
        """Everything else keeps the plain failed-only rule."""
        assert not registry_module.Binding(
            primary="capable"
        ).severe_partial_warnings
