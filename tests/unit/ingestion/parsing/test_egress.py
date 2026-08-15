"""Tests for the deny-all egress policy (03 §3.7, §14 step 1)."""

import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import egress as egress_module
from ingestion.parsing import shapes


def _capabilities(egress, endpoint_host=None):
    """Build capabilities declaring a given egress posture."""
    return capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.PARAGRAPH}),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.NONE,
        locator_tiers=frozenset({quality.LocatorTier.COARSE}),
        egress=egress,
        endpoint_host=endpoint_host,
    )


@pytest.mark.parametrize("source_class", list(document.SourceClass))
def test_a_network_free_adapter_is_permitted(source_class):
    """An adapter that transmits nothing is always allowed."""
    decision = egress_module.DEFAULT_EGRESS_POLICY.allows(
        source_class, _capabilities(capabilities_module.Egress.NONE)
    )
    assert decision.allowed


@pytest.mark.parametrize("source_class", list(document.SourceClass))
def test_remote_transport_is_denied_for_every_source_class(source_class):
    """Remote transport is deferred; the default is deny."""
    decision = egress_module.DEFAULT_EGRESS_POLICY.allows(
        source_class,
        _capabilities(
            capabilities_module.Egress.DECLARED_ENDPOINT,
            "parser.example.com",
        ),
    )
    assert not decision.allowed
    assert decision.reason


def test_validation_rejects_a_remote_adapter():
    """A hosted adapter cannot be bound while the policy denies it."""
    with pytest.raises(egress_module.EgressPolicyError, match="denies"):
        egress_module.validate_adapter_egress(
            "hosted",
            _capabilities(
                capabilities_module.Egress.DECLARED_ENDPOINT,
                "parser.example.com",
            ),
        )


def test_validation_accepts_a_local_adapter():
    """A network-free adapter passes startup validation silently."""
    egress_module.validate_adapter_egress(
        "local", _capabilities(capabilities_module.Egress.NONE)
    )


def test_declaring_an_endpoint_without_egress_is_incoherent():
    """The declaration must be internally consistent."""
    with pytest.raises(ValueError, match="no endpoint"):
        _capabilities(capabilities_module.Egress.NONE, "parser.example.com")


def test_declaring_egress_without_an_endpoint_is_incoherent():
    """A remote adapter names exactly one endpoint host."""
    with pytest.raises(ValueError, match="endpoint host"):
        _capabilities(capabilities_module.Egress.DECLARED_ENDPOINT)
