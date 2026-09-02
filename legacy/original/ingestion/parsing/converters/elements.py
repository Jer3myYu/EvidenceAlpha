"""``ElementList`` to normalized blocks (03 §3.6).

Element-based APIs — Unstructured, Azure Document Intelligence,
Textract — return a flat list of typed elements. The adapter maps its
vendor's kind strings onto :class:`ingestion.parsing.shapes.ElementKind`
and hands the list back; everything below is written once and shared, so
two vendors returning the same elements produce the same blocks.

The one structural decision this converter makes is grouping: a run of
consecutive list items becomes a single ``list`` block, because a
one-item-per-block reading produces chunks too small to retrieve on.
"""

from contracts import document
from ingestion.parsing import shapes
from ingestion.parsing.converters import common

#: Version of this converter. Part of the planned parse manifest.
CONVERTER_VERSION = "elements/1.0"

_BLOCK_TYPES: dict[shapes.ElementKind, document.BlockType] = {
    shapes.ElementKind.TITLE: document.BlockType.HEADING,
    shapes.ElementKind.HEADING: document.BlockType.HEADING,
    shapes.ElementKind.NARRATIVE_TEXT: document.BlockType.PARAGRAPH,
    shapes.ElementKind.LIST_ITEM: document.BlockType.LIST,
    shapes.ElementKind.TABLE: document.BlockType.TABLE,
    shapes.ElementKind.KEY_VALUE: document.BlockType.KEY_VALUE,
    shapes.ElementKind.CODE: document.BlockType.CODE,
    shapes.ElementKind.IMAGE_TEXT: document.BlockType.IMAGE_TEXT,
}


def _heading_level(element: shapes.Element) -> int:
    """Return the heading level an element implies."""
    if element.kind is shapes.ElementKind.TITLE:
        return 1
    return element.heading_level or 2


def _group_list_items(
    elements: list[shapes.Element],
) -> list[list[shapes.Element]]:
    """Group consecutive list items, leaving other elements alone."""
    groups: list[list[shapes.Element]] = []
    for element in elements:
        if (
            element.kind is shapes.ElementKind.LIST_ITEM
            and groups
            and groups[-1][0].kind is shapes.ElementKind.LIST_ITEM
        ):
            groups[-1].append(element)
            continue
        groups.append([element])
    return groups


def convert(
    element_list: shapes.ElementList, context: common.ConversionContext
) -> list[document.Block]:
    """Convert a flat element list into normalized blocks.

    Args:
      element_list: The elements the adapter returned.
      context: The conversion context.

    Returns:
      Normalized blocks in document order.
    """
    blocks: list[document.Block] = []
    headings = common.HeadingStack()
    element_index = 0
    for group in _group_list_items(list(element_list.elements)):
        first = group[0]
        locator = first.locator
        if locator.element_index is None:
            locator = locator.model_copy(
                update={"element_index": element_index}
            )
        block_type = _BLOCK_TYPES[first.kind]
        payload: document.TableBlock | document.KeyValuePair | None = None
        text = "\n".join(element.text for element in group)
        if first.kind is shapes.ElementKind.TABLE:
            payload = first.table
        elif first.kind is shapes.ElementKind.KEY_VALUE:
            payload = document.KeyValuePair(
                key=common.normalize_text(first.key or ""),
                value=common.normalize_text(first.text) or None,
            )

        heading_path = headings.path()
        blocks.append(
            common.build_block(
                context=context,
                ordinal=len(blocks),
                block_type=block_type,
                text=text,
                locator=locator,
                heading_path=heading_path,
                payload=payload,
            )
        )
        if block_type is document.BlockType.HEADING:
            headings.push(
                _heading_level(first), common.normalize_text(first.text)
            )
        element_index += len(group)
    return blocks
