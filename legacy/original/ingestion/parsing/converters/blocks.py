"""``BlockSequence`` to normalized blocks (03 §3.6).

Adapters with rich structural access — the SEC HTML and PyMuPDF
adapters — build blocks directly. This converter still runs: it
re-normalizes text, re-renders canonical table and fact text from the
payload, applies the declared table-typing policy, and mints block IDs.

Identity construction and normalization stay in one place even for the
shape that arrives closest to the contract, so a block produced this way
is indistinguishable from the same block arriving as elements or
markdown.
"""

from contracts import document
from ingestion.parsing import shapes
from ingestion.parsing.converters import common

#: Version of this converter. Part of the planned parse manifest.
CONVERTER_VERSION = "blocks/1.0"


def convert(
    sequence: shapes.BlockSequence, context: common.ConversionContext
) -> list[document.Block]:
    """Normalize an adapter's block sequence.

    Args:
      sequence: The :class:`ingestion.parsing.shapes.BlockSequence` the
        adapter returned.
      context: The conversion context.

    Returns:
      Normalized blocks in document order.
    """
    blocks: list[document.Block] = []
    for ordinal, block in enumerate(sequence.blocks):
        locator = block.locator
        if locator.element_index is None:
            locator = locator.model_copy(update={"element_index": ordinal})
        blocks.append(
            common.build_block(
                context=context,
                ordinal=ordinal,
                block_type=block.type,
                text=block.text,
                locator=locator,
                heading_path=block.heading_path,
                payload=block.payload,
                block_warnings=list(block.extraction.warnings),
            )
        )
    return blocks
