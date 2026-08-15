"""Tests for the ``ElementList`` converter (03 §3.6)."""

import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes
from ingestion.parsing.converters import common
from ingestion.parsing.converters import elements as elements_converter

_CAPABILITIES = capabilities_module.AdapterCapabilities(
    block_types=frozenset(
        {
            document.BlockType.HEADING,
            document.BlockType.PARAGRAPH,
            document.BlockType.LIST,
            document.BlockType.TABLE,
            document.BlockType.KEY_VALUE,
            document.BlockType.CODE,
            document.BlockType.IMAGE_TEXT,
        }
    ),
    native_shape=shapes.NativeShape.ELEMENT_LIST,
    table_fidelity=capabilities_module.TableFidelity.GRID,
    locator_tiers=frozenset({quality.LocatorTier.COARSE}),
    page_fidelity=True,
)


def _convert(elements):
    """Convert an element list into blocks."""
    context = common.ConversionContext(
        parse_id="sha256:parse",
        adapter_name="stub",
        adapter_version="1.0",
        adapter_capabilities=_CAPABILITIES,
    )
    return elements_converter.convert(
        shapes.ElementList(elements=elements), context
    )


def _element(kind, text="", **overrides):
    """Build one element."""
    fields = {"kind": kind, "text": text}
    fields.update(overrides)
    return shapes.Element(**fields)


def _table():
    """Build a one-cell table."""
    return document.TableBlock(
        n_rows=1,
        n_columns=1,
        cells=[
            document.TableCell(
                row=0, column=0, is_origin=True, raw_text="1,204"
            )
        ],
    )


@pytest.mark.parametrize(
    "kind,block_type",
    [
        (shapes.ElementKind.TITLE, document.BlockType.HEADING),
        (shapes.ElementKind.HEADING, document.BlockType.HEADING),
        (shapes.ElementKind.NARRATIVE_TEXT, document.BlockType.PARAGRAPH),
        (shapes.ElementKind.CODE, document.BlockType.CODE),
        (shapes.ElementKind.IMAGE_TEXT, document.BlockType.IMAGE_TEXT),
    ],
)
def test_kinds_map_to_block_types(kind, block_type):
    """Vendor kinds are mapped once, in shared code."""
    blocks = _convert([_element(kind, "content")])
    assert blocks[0].type is block_type


def test_consecutive_list_items_group():
    """A run of items becomes one retrievable block."""
    blocks = _convert(
        [
            _element(shapes.ElementKind.LIST_ITEM, "one"),
            _element(shapes.ElementKind.LIST_ITEM, "two"),
            _element(shapes.ElementKind.NARRATIVE_TEXT, "after"),
        ]
    )
    assert len(blocks) == 2
    assert blocks[0].type is document.BlockType.LIST
    assert blocks[0].text.splitlines() == ["one", "two"]


def test_headings_build_a_path():
    """Enclosing headings reach the blocks beneath them."""
    blocks = _convert(
        [
            _element(shapes.ElementKind.TITLE, "Annual Report"),
            _element(shapes.ElementKind.HEADING, "Segments", heading_level=2),
            _element(shapes.ElementKind.NARRATIVE_TEXT, "Body"),
        ]
    )
    assert blocks[0].heading_path == []
    assert blocks[1].heading_path == ["Annual Report"]
    assert blocks[2].heading_path == ["Annual Report", "Segments"]


def test_table_elements_keep_their_grid():
    """A table element becomes a table block with canonical text."""
    blocks = _convert([_element(shapes.ElementKind.TABLE, table=_table())])
    assert blocks[0].type is document.BlockType.TABLE
    assert blocks[0].text == document.render_table_text(blocks[0].payload)


def test_key_value_elements_carry_a_pair():
    """Cover-page fields keep their key alongside their value."""
    blocks = _convert(
        [
            _element(
                shapes.ElementKind.KEY_VALUE,
                "December 31, 2025",
                key="Fiscal year end",
            )
        ]
    )
    assert blocks[0].type is document.BlockType.KEY_VALUE
    assert blocks[0].payload.key == "Fiscal year end"
    assert blocks[0].payload.value == "December 31, 2025"


def test_element_index_is_filled_in_when_absent():
    """Every block gets at least a diagnostic position."""
    blocks = _convert(
        [
            _element(shapes.ElementKind.NARRATIVE_TEXT, "one"),
            _element(shapes.ElementKind.NARRATIVE_TEXT, "two"),
        ]
    )
    assert blocks[0].locator.element_index == 0
    assert blocks[1].locator.element_index == 1


def test_a_table_element_requires_a_grid():
    """The shape refuses a table element with no table."""
    with pytest.raises(ValueError, match="table grid"):
        _element(shapes.ElementKind.TABLE)


def test_a_key_value_element_requires_a_key():
    """The shape refuses a key/value element with no key."""
    with pytest.raises(ValueError, match="requires a key"):
        _element(shapes.ElementKind.KEY_VALUE, "value only")
