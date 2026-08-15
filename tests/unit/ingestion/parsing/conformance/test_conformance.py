"""The shared adapter conformance suite (03 §13).

One parameterized suite that **every** adapter must pass, asserting
contract invariants rather than content. Evaluating a new vendor is then
bounded: write the adapter, run this suite to prove it is a legal
adapter, then diff the golden outputs to judge whether it is a better
one. Content quality stays a per-adapter golden test; contract
compliance is shared.

A real adapter joins the suite by being added to
``stub_adapters.CONFORMING_ADAPTERS``' real counterpart when it lands.
The non-conforming cases at the bottom are what prove the suite has
teeth: each breaks exactly one rule and must be rejected.
"""

import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import manifest as manifest_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import shapes
from tests.unit.ingestion.parsing.conformance import stub_adapters

_ADAPTER_IDS = [adapter.name for adapter in stub_adapters.CONFORMING_ADAPTERS]


@pytest.fixture(
    name="adapter", params=stub_adapters.CONFORMING_ADAPTERS, ids=_ADAPTER_IDS
)
def adapter_fixture(request):
    """Yield each conforming adapter in turn."""
    return request.param


@pytest.fixture(name="result")
def result_fixture(adapter, build_service, fixture_artifact):
    """Run one adapter end to end through the parser service."""
    return build_service(adapter).parse(fixture_artifact)


def test_parse_succeeds(result):
    """A conforming adapter produces a usable document."""
    assert result.error is None
    assert result.status is not quality.QualityVerdict.FAILED
    assert result.parsed_document is not None
    assert result.parsed_document.blocks


def test_declared_block_types_cover_observed(adapter, result):
    """No block type beyond what the adapter declared (03 §3.5)."""
    for block in result.parsed_document.blocks:
        assert block.type in adapter.capabilities.block_types


def test_declared_locator_tiers_cover_observed(adapter, result):
    """No locator tier beyond what the adapter declared (03 §3.5)."""
    for block in result.parsed_document.blocks:
        assert block.locator_tier in adapter.capabilities.locator_tiers


def test_no_capability_overstatement(result):
    """A conforming adapter raises no overstatement warning."""
    codes = {warning.code for warning in result.warnings}
    assert quality.WarningCode.CAPABILITY_OVERSTATED not in codes
    assert not result.parsed_document.parse_quality.rejected_blocks


def test_every_block_has_canonical_text(result):
    """Every admitted block carries non-empty text (03 §5.4)."""
    for block in result.parsed_document.blocks:
        assert block.text.strip()


def test_table_text_is_the_canonical_rendering(result):
    """A table's text is rendered from its grid, not the adapter."""
    for block in result.parsed_document.blocks:
        if block.type is document.BlockType.TABLE:
            assert block.text == document.render_table_text(block.payload)


def test_table_grid_invariant_holds(result):
    """Exactly one entry per coordinate, spans agreeing (03 §5.3)."""
    for block in result.parsed_document.blocks:
        if block.type is not document.BlockType.TABLE:
            continue
        table = block.payload
        coordinates = {(cell.row, cell.column) for cell in table.cells}
        assert len(table.cells) == table.n_rows * table.n_columns
        assert len(coordinates) == len(table.cells)
        by_coordinate = {(cell.row, cell.column): cell for cell in table.cells}
        for cell in table.cells:
            if cell.is_origin:
                assert cell.raw_text is not None
                continue
            origin = by_coordinate[cell.origin]
            assert origin.is_origin
            assert cell.raw_text is None
            assert origin.row <= cell.row < origin.row + origin.row_span
            assert (
                origin.column
                <= cell.column
                < origin.column + origin.column_span
            )


def test_table_cells_preserve_raw_text(result):
    """``raw_text`` survives; typing appears only where declared."""
    for block in result.parsed_document.blocks:
        if block.type is not document.BlockType.TABLE:
            continue
        for cell in block.payload.cells:
            if not cell.is_origin:
                continue
            assert cell.raw_text is not None


def test_typing_only_where_typed_grid_declared(adapter, result):
    """Cells are typed only when ``typed_grid`` was declared (03 §3.6)."""
    if (
        adapter.capabilities.table_fidelity
        >= capabilities_module.TableFidelity.TYPED_GRID
    ):
        pytest.skip("adapter declares typed_grid")
    for block in result.parsed_document.blocks:
        if block.type is not document.BlockType.TABLE:
            continue
        for cell in block.payload.cells:
            assert cell.value is None
            assert cell.value_type is None


def test_pinned_determinism(adapter, build_service, fixture_artifact):
    """A pinned adapter over one fixture twice is byte-identical."""
    if (
        adapter.capabilities.determinism
        is not capabilities_module.Determinism.PINNED
    ):
        pytest.skip("determinism is not pinned")
    first = build_service(adapter).parse(fixture_artifact)
    second = build_service(adapter).parse(fixture_artifact)
    assert (
        first.parsed_document.model_dump_json()
        == second.parsed_document.model_dump_json()
    )


def test_declares_no_egress(adapter):
    """Every adapter in this session declares ``egress: none``."""
    assert adapter.capabilities.egress is capabilities_module.Egress.NONE
    assert adapter.capabilities.endpoint_host is None


def test_manifest_records_the_planned_half(adapter, result):
    """The planned manifest carries everything 03 §5.1 requires."""
    planned = result.manifest.planned
    primary = planned.primary
    assert primary.adapter_name == adapter.name
    assert primary.adapter_version == adapter.version
    assert primary.extraction_class is adapter.capabilities.extraction_class
    assert primary.determinism is adapter.capabilities.determinism
    assert primary.native_shape is adapter.capabilities.native_shape
    assert primary.converter_version
    assert primary.endpoint_host is None
    assert planned.normalizer_version
    assert planned.quality_policy_version
    assert planned.schema_version


def test_every_registered_attempt_is_planned(
    adapter, build_service, fixture_artifact
):
    """A registered fallback is described before anything runs."""
    other = stub_adapters.StubElementListAdapter()
    if other.name == adapter.name:
        other = stub_adapters.StubMarkdownAdapter()
    result = build_service(adapter, other, fallback=other.name).parse(
        fixture_artifact
    )
    planned = result.manifest.planned
    assert [item.adapter_name for item in planned.attempts] == [
        adapter.name,
        other.name,
    ]
    assert planned.attempts[1].is_fallback is True
    assert planned.attempts[1].converter_version


def test_parse_id_derives_from_the_planned_manifest_only(result):
    """``parse_id`` is reproducible from the planned half alone."""
    recomputed = manifest_module.compute_parse_id(
        result.version_id, result.manifest.planned
    )
    assert result.parse_id == recomputed
    assert result.parsed_document.identity.parse_id == recomputed


def test_observed_manifest_is_not_hashed(result):
    """The observed half cannot change ``parse_id``; the planned can."""
    planned = result.manifest.planned
    unchanged = manifest_module.ParseManifest(
        planned=planned,
        observed=result.manifest.observed.model_copy(
            update={
                "fallback_used": True,
                "rejected_block_count": 99,
                "raw_output_digest": "sha256:different",
            }
        ),
    )
    assert (
        manifest_module.compute_parse_id(result.version_id, unchanged.planned)
        == result.parse_id
    )

    bumped = planned.primary.model_copy(update={"adapter_version": "9.9"})
    changed = planned.model_copy(update={"attempts": [bumped]})
    assert (
        manifest_module.compute_parse_id(result.version_id, changed)
        != result.parse_id
    )


def test_no_credentials_in_the_manifest(result, caplog):
    """Credentials appear in neither the manifest nor the logs."""
    serialized = result.manifest.model_dump_json()
    assert stub_adapters.STUB_CREDENTIAL not in serialized
    assert stub_adapters.STUB_CREDENTIAL not in caplog.text


def test_locator_tier_travels_with_every_block(result):
    """Every admitted block records the tier it achieved (03 §5.5)."""
    for block in result.parsed_document.blocks:
        assert isinstance(block.locator_tier, quality.LocatorTier)


# --- Non-conforming adapters: the suite must reject each of these. ---


def test_overstating_adapter_is_caught(build_service, fixture_artifact):
    """An undeclared block type is rejected, loudly (03 §3.5)."""
    result = build_service(stub_adapters.OverstatingAdapter()).parse(
        fixture_artifact
    )
    rejected = result.parsed_document.parse_quality.rejected_blocks
    reasons = {item.reason for item in rejected}
    assert quality.BlockRejectionReason.UNDECLARED_BLOCK_TYPE in reasons
    codes = {warning.code for warning in result.warnings}
    assert quality.WarningCode.CAPABILITY_OVERSTATED in codes


def test_shape_liar_adapter_is_caught(build_service, fixture_artifact):
    """A returned shape must match the declared one."""
    result = build_service(stub_adapters.ShapeLiarAdapter()).parse(
        fixture_artifact
    )
    assert result.status is quality.QualityVerdict.FAILED
    assert result.error.code is shapes.ParserErrorCode.PARSE_FAILED
    assert "native shape" in result.error.message


def test_typing_overreach_is_stripped(build_service, fixture_artifact):
    """Undeclared cell typing is discarded, and the loss is reported."""
    result = build_service(stub_adapters.TypingOverreachAdapter()).parse(
        fixture_artifact
    )
    tables = [
        block
        for block in result.parsed_document.blocks
        if block.type is document.BlockType.TABLE
    ]
    assert tables
    for cell in tables[0].payload.cells:
        assert cell.value is None
    assert any(
        cell.raw_text == "1,204"
        for cell in tables[0].payload.cells
        if cell.is_origin
    )
    codes = {
        warning.code
        for block in result.parsed_document.blocks
        for warning in block.extraction.warnings
    }
    assert quality.WarningCode.TABLE_TYPING_UNAVAILABLE in codes


def test_failing_adapter_is_a_controlled_failure(
    build_service, fixture_artifact
):
    """An adapter exception becomes a controlled failure, not a crash."""
    result = build_service(stub_adapters.FailingAdapter()).parse(
        fixture_artifact
    )
    assert result.status is quality.QualityVerdict.FAILED
    assert result.parsed_document is None
    assert result.error.code is shapes.ParserErrorCode.PARSE_FAILED


def test_empty_adapter_fails_loudly(build_service, fixture_artifact):
    """An empty extraction never becomes an empty document (03 §7.2)."""
    result = build_service(stub_adapters.EmptyAdapter()).parse(fixture_artifact)
    assert result.status is quality.QualityVerdict.FAILED
    assert result.parsed_document is None
    assert result.error.code is shapes.ParserErrorCode.PARSE_QUALITY_TOO_LOW


def test_under_capable_adapter_is_refused_at_startup():
    """A weaker adapter fails when the process boots (03 §3.5)."""
    adapter = stub_adapters.UnderCapableAdapter()
    with pytest.raises(registry_module.RegistryError) as error:
        registry_module.AdapterRegistry(
            adapters=[adapter],
            bindings={
                capabilities_module.RouteRole.SEC_HTML_PARSER: (
                    registry_module.Binding(primary=adapter.name)
                )
            },
        )
    assert "table_fidelity" in str(error.value)


def test_generative_adapter_cannot_bind_a_financial_route():
    """Financial routes cap extraction class at model_assisted."""
    adapter = stub_adapters.GenerativeAdapter()
    with pytest.raises(registry_module.RegistryError) as error:
        registry_module.AdapterRegistry(
            adapters=[adapter],
            bindings={
                capabilities_module.RouteRole.SEC_HTML_PARSER: (
                    registry_module.Binding(primary=adapter.name)
                )
            },
        )
    assert "extraction_class" in str(error.value)


def test_remote_adapter_is_denied_by_the_egress_policy():
    """The MVP deny-all policy refuses a declared endpoint (03 §3.7)."""
    adapter = stub_adapters.RemoteAdapter()
    with pytest.raises(registry_module.RegistryError) as error:
        registry_module.AdapterRegistry(
            adapters=[adapter],
            bindings={
                capabilities_module.RouteRole.SEC_HTML_PARSER: (
                    registry_module.Binding(primary=adapter.name)
                )
            },
        )
    assert "egress" in str(error.value)


def test_unknown_adapter_binding_is_refused():
    """A binding naming no known adapter fails at startup."""
    with pytest.raises(registry_module.RegistryError):
        registry_module.AdapterRegistry(
            adapters=[],
            bindings={
                capabilities_module.RouteRole.SEC_HTML_PARSER: (
                    registry_module.Binding(primary="does_not_exist")
                )
            },
        )
