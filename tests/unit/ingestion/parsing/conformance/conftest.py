"""Fixtures for the adapter conformance suite (03 §13).

The suite runs with network access disabled by default. Local adapters
must pass under that condition: 03 §3.7's "explicitly network-free" is
asserted here rather than left merely unimplemented.
"""

import socket

import pytest

from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import service as service_module
from tests.unit.ingestion.parsing.conformance import stub_adapters


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any attempt to open a socket during the suite."""

    def deny(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "the parser subsystem must not touch the network (03 §1.0)"
        )

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


@pytest.fixture(name="fixture_artifact")
def fixture_artifact_fixture(tmp_path):
    """Write a markdown fixture and return an artifact naming it."""
    path = tmp_path / "fixture.md"
    path.write_text(
        "# Fixture\n\nA short markdown fixture for the suite.\n",
        encoding="utf-8",
    )
    return stub_adapters.make_artifact(str(path), path.stat().st_size)


@pytest.fixture(name="build_service")
def build_service_fixture():
    """Return a factory building a service around one adapter."""

    def build(
        *adapters,
        role=capabilities_module.RouteRole.MARKDOWN_PARSER,
        fallback=None,
        severe_partial_warnings=frozenset(),
    ):
        binding = registry_module.Binding(
            primary=adapters[0].name,
            fallback=fallback,
            severe_partial_warnings=severe_partial_warnings,
        )
        registry = registry_module.AdapterRegistry(
            adapters=adapters, bindings={role: binding}
        )
        return service_module.ParserService(registry=registry)

    return build
