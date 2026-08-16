"""Fixtures for the adapter conformance suite (03 §13).

The suite runs with network access disabled by default. Local adapters
must pass under that condition: 03 §3.7's "explicitly network-free" is
asserted here rather than left merely unimplemented — for the real SEC
adapter this is also 03 §4.1's dedicated offline test.

Each adapter joins the suite as a **case**: the adapter, the route role
it serves, and a factory for an artifact it can parse. The stubs share
one markdown fixture; a real adapter brings a real fixture of its own
format.
"""

import os
import socket
from typing import Callable, NamedTuple

import pytest

from contracts import document
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import service as service_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import base
from ingestion.parsing.adapters import pdf_pymupdf
from ingestion.parsing.adapters import sec_html_lxml
from tests.unit.ingestion.parsing import pdf_fixture
from tests.unit.ingestion.parsing.conformance import stub_adapters

_SEC_FIXTURE = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    os.pardir,
    os.pardir,
    os.pardir,
    "fixtures",
    "sec",
    "photronics_2026_05_8k.htm",
)


class ConformanceCase(NamedTuple):
    """One adapter's entry in the shared suite (03 §13)."""

    adapter: base.ParserAdapter
    role: capabilities_module.RouteRole
    make_artifact: Callable[[object], shapes.AcquiredArtifact]


def _markdown_artifact(tmp_path) -> shapes.AcquiredArtifact:
    """Write the stubs' shared markdown fixture."""
    path = tmp_path / "fixture.md"
    path.write_text(
        "# Fixture\n\nA short markdown fixture for the suite.\n",
        encoding="utf-8",
    )
    return stub_adapters.make_artifact(str(path), path.stat().st_size)


def _sec_artifact(tmp_path) -> shapes.AcquiredArtifact:
    """Return an artifact naming the real 8-K fixture."""
    del tmp_path
    path = os.path.normpath(_SEC_FIXTURE)
    return stub_adapters.make_artifact(
        path,
        os.path.getsize(path),
        filename=os.path.basename(path),
        source_class=document.SourceClass.SEC_FILING,
    )


def _pdf_artifact(tmp_path) -> shapes.AcquiredArtifact:
    """Generate the digital-PDF fixture and return its artifact."""
    path = str(tmp_path / "fixture.pdf")
    pdf_fixture.write_pdf(path)
    return stub_adapters.make_artifact(
        path,
        os.path.getsize(path),
        filename="fixture.pdf",
    )


#: Every adapter the shared suite runs: the three shape stubs plus each
#: real adapter as it lands (03 §13).
CONFORMANCE_CASES: tuple[ConformanceCase, ...] = tuple(
    ConformanceCase(
        adapter=adapter,
        role=capabilities_module.RouteRole.MARKDOWN_PARSER,
        make_artifact=_markdown_artifact,
    )
    for adapter in stub_adapters.CONFORMING_ADAPTERS
) + (
    ConformanceCase(
        adapter=sec_html_lxml.SecHtmlLxmlAdapter(),
        role=capabilities_module.RouteRole.SEC_HTML_PARSER,
        make_artifact=_sec_artifact,
    ),
    ConformanceCase(
        adapter=pdf_pymupdf.PdfPymupdfAdapter(),
        role=capabilities_module.RouteRole.PDF_LAYOUT_PARSER,
        make_artifact=_pdf_artifact,
    ),
)


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


@pytest.fixture(
    name="case",
    params=CONFORMANCE_CASES,
    ids=[entry.adapter.name for entry in CONFORMANCE_CASES],
)
def case_fixture(request):
    """Yield each conformance case in turn."""
    return request.param


@pytest.fixture(name="fixture_artifact")
def fixture_artifact_fixture(case, tmp_path):
    """Return an artifact the current case's adapter can parse."""
    return case.make_artifact(tmp_path)


@pytest.fixture(name="markdown_artifact")
def markdown_artifact_fixture(tmp_path):
    """The stubs' shared fixture, for the non-conforming cases."""
    return _markdown_artifact(tmp_path)


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
