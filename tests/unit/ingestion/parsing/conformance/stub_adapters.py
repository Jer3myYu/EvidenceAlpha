"""Test-only stub adapters, one per native shape (03 §3.6, §13).

The conformance suite exists to prove that a *legal* adapter is legal
and an *illegal* one is caught. With no real adapter yet — the SEC and
PDF routes arrive at 03 §14 steps 5 and 7, each behind its own spike —
these stubs are what the suite runs against, and untested test
infrastructure is worthless.

They live under ``tests/`` and never in ``ingestion/parsing/adapters/``.
Nothing in the shipped package may import them.

Two families:

* **conforming** — one per native shape, returning canned fixtures that
  satisfy every contract invariant;
* **non-conforming** — each breaking exactly one rule, so a suite that
  passes them all is a suite that is not actually checking anything.
"""

import datetime

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import base

#: A sentinel credential. The suite asserts it appears in neither the
#: parse manifest nor the captured logs (03 §13).
STUB_CREDENTIAL = "stub-secret-do-not-log-1a2b3c"

_ANCHORED = frozenset({quality.LocatorTier.ANCHORED})
_COARSE = frozenset({quality.LocatorTier.COARSE})


def _income_statement() -> document.TableBlock:
    """Build a two-level-header table with one merged cell.

    This is the shape 03 §5.3 describes: ``header_rows = 2`` with a
    merged "Three Months Ended" spanning two period columns, held as one
    origin cell of ``column_span = 2`` plus one covered placeholder
    beside it, and a hierarchical row-header stub.
    """
    cells: list[document.TableCell] = []
    layout: list[list[tuple[str | None, int, int]]] = [
        [("", 1, 1), ("", 1, 1), ("Three Months Ended", 1, 2), (None, 0, 0)],
        [("", 1, 1), ("Line item", 1, 1), ("2025", 1, 1), ("2024", 1, 1)],
        [("Revenue", 1, 1), ("Products", 1, 1), ("1,204", 1, 1), ("998", 1, 1)],
        [("Revenue", 1, 1), ("Services", 1, 1), ("", 1, 1), ("311", 1, 1)],
    ]
    for row, entries in enumerate(layout):
        for column, (text, row_span, column_span) in enumerate(entries):
            if text is None:
                cells.append(
                    document.TableCell(
                        row=row,
                        column=column,
                        is_origin=False,
                        origin=(0, 2),
                    )
                )
                continue
            cells.append(
                document.TableCell(
                    row=row,
                    column=column,
                    is_origin=True,
                    row_span=row_span,
                    column_span=column_span,
                    raw_text=text,
                    is_header=row < 2,
                )
            )
    return document.TableBlock(
        caption="Condensed Consolidated Statements of Operations",
        n_rows=4,
        n_columns=4,
        header_rows=2,
        row_header_columns=[0, 1],
        cells=cells,
        unit="USD",
        scale="millions",
        unit_source=document.UnitSource.CAPTION,
    )


def _block(
    ordinal: int,
    block_type: document.BlockType,
    text: str,
    anchor: str,
    heading_path: list[str] | None = None,
    payload: document.TableBlock | None = None,
) -> document.Block:
    """Build one block for the block-sequence stub's canned output."""
    if payload is not None:
        text = document.render_table_text(payload)
    return document.Block(
        block_id=f"stub-{ordinal}",
        type=block_type,
        heading_path=list(heading_path or []),
        text=text,
        payload=payload,
        locator=document.Locator(html_anchor=anchor, element_index=ordinal),
        extraction=document.BlockExtraction(
            adapter_name="stub_block_sequence", adapter_version="1.0"
        ),
    )


class StubBlockSequenceAdapter:
    """Conforming adapter returning normalized blocks directly."""

    name = "stub_block_sequence"
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
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=_ANCHORED,
        extraction_class=capabilities_module.ExtractionClass.RULE_BASED,
        determinism=capabilities_module.Determinism.PINNED,
        egress=capabilities_module.Egress.NONE,
    )

    def supports(self, request: base.ParseRequest) -> bool:
        """Accept every request."""
        del request
        return True

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return canned blocks, including a merged-cell table."""
        del request
        return shapes.RawParseResult(
            content=shapes.BlockSequence(
                blocks=[
                    _block(
                        0,
                        document.BlockType.HEADING,
                        "Item 7. Management's Discussion",
                        "item7",
                    ),
                    _block(
                        1,
                        document.BlockType.PARAGRAPH,
                        "Revenue increased 21% year over year.",
                        "item7-p1",
                        heading_path=["Item 7. Management's Discussion"],
                    ),
                    _block(
                        2,
                        document.BlockType.TABLE,
                        "",
                        "item7-t1",
                        heading_path=["Item 7. Management's Discussion"],
                        payload=_income_statement(),
                    ),
                ]
            ),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            business_metadata=document.BusinessMetadata(
                company="Stub Industries", document_type="10-Q"
            ),
            adapter_name=self.name,
            adapter_version=self.version,
            library_versions={"stub": "1.0"},
        )


class StubElementListAdapter:
    """Conforming adapter returning flat typed elements."""

    name = "stub_element_list"
    version = "1.0"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset(
            {
                document.BlockType.HEADING,
                document.BlockType.PARAGRAPH,
                document.BlockType.LIST,
                document.BlockType.TABLE,
                document.BlockType.KEY_VALUE,
            }
        ),
        native_shape=shapes.NativeShape.ELEMENT_LIST,
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=_COARSE,
        page_fidelity=True,
        extraction_class=capabilities_module.ExtractionClass.MODEL_ASSISTED,
        determinism=capabilities_module.Determinism.PINNED,
        egress=capabilities_module.Egress.NONE,
    )

    def supports(self, request: base.ParseRequest) -> bool:
        """Accept every request."""
        del request
        return True

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return canned elements spanning two pages."""
        del request
        page_one = document.Locator(page=1)
        page_two = document.Locator(page=2)
        return shapes.RawParseResult(
            content=shapes.ElementList(
                elements=[
                    shapes.Element(
                        kind=shapes.ElementKind.TITLE,
                        text="Annual Report",
                        locator=page_one,
                    ),
                    shapes.Element(
                        kind=shapes.ElementKind.NARRATIVE_TEXT,
                        text="Operating margin expanded by 140 bps.",
                        locator=page_one,
                    ),
                    shapes.Element(
                        kind=shapes.ElementKind.LIST_ITEM,
                        text="Segment A grew 12%",
                        locator=page_one,
                    ),
                    shapes.Element(
                        kind=shapes.ElementKind.LIST_ITEM,
                        text="Segment B declined 3%",
                        locator=page_one,
                    ),
                    shapes.Element(
                        kind=shapes.ElementKind.KEY_VALUE,
                        key="Fiscal year end",
                        text="December 31, 2025",
                        locator=page_two,
                    ),
                    shapes.Element(
                        kind=shapes.ElementKind.TABLE,
                        text="",
                        locator=page_two,
                        table=_income_statement(),
                    ),
                ]
            ),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
            page_count=2,
            element_count=6,
        )


class StubMarkdownAdapter:
    """Conforming adapter returning markdown plus a page map."""

    name = "stub_markdown"
    version = "1.0"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset(
            {
                document.BlockType.HEADING,
                document.BlockType.PARAGRAPH,
                document.BlockType.LIST,
                document.BlockType.TABLE,
                document.BlockType.CODE,
            }
        ),
        native_shape=shapes.NativeShape.MARKDOWN_DOCUMENT,
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=_COARSE,
        page_fidelity=True,
        extraction_class=capabilities_module.ExtractionClass.MODEL_ASSISTED,
        determinism=capabilities_module.Determinism.PINNED,
        egress=capabilities_module.Egress.NONE,
    )

    markdown = (
        "# Quarterly Update\n"
        "\n"
        "Revenue grew across both segments.\n"
        "\n"
        "## Segments\n"
        "\n"
        "- Segment A grew 12%\n"
        "- Segment B declined 3%\n"
        "\n"
        "| Segment | Revenue |\n"
        "| --- | --- |\n"
        "| A | 1,204 |\n"
        "| B | 311 |\n"
    )

    def supports(self, request: base.ParseRequest) -> bool:
        """Accept every request."""
        del request
        return True

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return canned markdown with a complete page map."""
        del request
        return shapes.RawParseResult(
            content=shapes.MarkdownDocument(
                markdown=self.markdown,
                page_map=[
                    shapes.PageSpan(page=1, start=0, end=len(self.markdown))
                ],
            ),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
            page_count=1,
        )


class OverstatingAdapter(StubBlockSequenceAdapter):
    """Non-conforming: emits a block type it never declared.

    03 §3.5's capability model is only worth having if an overstatement
    is caught. The gate refuses the undeclared blocks and raises
    ``CAPABILITY_OVERSTATED``.
    """

    name = "stub_overstating"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.PARAGRAPH}),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.GRID,
        locator_tiers=_ANCHORED,
        egress=capabilities_module.Egress.NONE,
    )


class ShapeLiarAdapter(StubMarkdownAdapter):
    """Non-conforming: returns a shape other than the declared one.

    The declared shape fixes the converter version in the **planned**
    manifest, so returning a different one silently invalidates
    ``parse_id``. The service refuses the attempt instead.
    """

    name = "stub_shape_liar"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.PARAGRAPH}),
        native_shape=shapes.NativeShape.ELEMENT_LIST,
        table_fidelity=capabilities_module.TableFidelity.NONE,
        locator_tiers=_COARSE,
        page_fidelity=True,
        egress=capabilities_module.Egress.NONE,
    )


class TypingOverreachAdapter(StubBlockSequenceAdapter):
    """Non-conforming: supplies cell types without declaring them.

    Declares ``GRID`` but hands back typed cells. The shared converter
    strips the typing and warns; it never infers a type of its own.
    """

    name = "stub_typing_overreach"

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return a table whose cells carry undeclared typing."""
        table = _income_statement()
        typed = [
            (
                cell.model_copy(
                    update={
                        "value": 1204,
                        "value_type": document.ValueType.NUMBER,
                    }
                )
                if cell.is_origin and cell.raw_text == "1,204"
                else cell
            )
            for cell in table.cells
        ]
        table = table.model_copy(update={"cells": typed})
        return shapes.RawParseResult(
            content=shapes.BlockSequence(
                blocks=[
                    _block(
                        0,
                        document.BlockType.PARAGRAPH,
                        "Revenue increased 21% year over year.",
                        "p1",
                    ),
                    _block(
                        1,
                        document.BlockType.TABLE,
                        "",
                        "t1",
                        payload=table,
                    ),
                ]
            ),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
        )


class FailingAdapter(StubBlockSequenceAdapter):
    """Non-conforming: raises instead of parsing."""

    name = "stub_failing"

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Fail the way a real adapter fails.

        Raises:
          AdapterError: Always.
        """
        del request
        raise base.AdapterError("the stub cannot parse this artifact")


class EmptyAdapter(StubBlockSequenceAdapter):
    """Non-conforming: returns nothing at all.

    A silent empty result is the failure the gate exists to catch: it
    must become a loud ``failed`` verdict, never an empty document.
    """

    name = "stub_empty"

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return an empty block sequence."""
        del request
        return shapes.RawParseResult(
            content=shapes.BlockSequence(blocks=[]),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
        )


class SeverePartialAdapter(StubBlockSequenceAdapter):
    """Returns usable content, but with a severe warning attached.

    A filing whose income statement collapsed to plain text is exactly
    the case 03 §6's severe-partial escalation exists for: useful, but
    worth spending the one fallback on.
    """

    name = "stub_severe_partial"

    def parse(self, request: base.ParseRequest) -> shapes.RawParseResult:
        """Return one paragraph plus a table-structure-lost warning."""
        del request
        return shapes.RawParseResult(
            content=shapes.BlockSequence(
                blocks=[
                    _block(
                        0,
                        document.BlockType.PARAGRAPH,
                        "Revenue increased 21% year over year.",
                        "p1",
                    )
                ]
            ),
            source_type=document.SourceType.MARKDOWN_DOCUMENT,
            adapter_name=self.name,
            adapter_version=self.version,
            warnings=[
                document.ParseWarning(
                    code=quality.WarningCode.TABLE_STRUCTURE_LOST,
                    message="one table was preserved as plain text",
                )
            ],
        )


class UnderCapableAdapter(StubBlockSequenceAdapter):
    """Non-conforming: below every MVP route's minimum profile.

    The registry must refuse to bind it at startup rather than let the
    corpus degrade quietly (03 §3.5).
    """

    name = "stub_under_capable"
    capabilities = capabilities_module.AdapterCapabilities(
        block_types=frozenset({document.BlockType.PARAGRAPH}),
        native_shape=shapes.NativeShape.BLOCK_SEQUENCE,
        table_fidelity=capabilities_module.TableFidelity.TEXT,
        locator_tiers=frozenset({quality.LocatorTier.DIAGNOSTIC}),
        egress=capabilities_module.Egress.NONE,
    )


class GenerativeAdapter(StubBlockSequenceAdapter):
    """Non-conforming for a financial route: generative extraction.

    A generative adapter cannot bind to a route that carries financial
    values. The refusal happens at startup, not per document (03 §3.8).
    """

    name = "stub_generative"
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
        locator_tiers=_ANCHORED,
        page_fidelity=True,
        extraction_class=capabilities_module.ExtractionClass.GENERATIVE,
        egress=capabilities_module.Egress.NONE,
    )


class RemoteAdapter(StubBlockSequenceAdapter):
    """Non-conforming under the MVP policy: declares egress.

    Remote transport is deferred, so the deny-all policy must refuse
    this binding at startup (03 §3.7, §14 step 1).
    """

    name = "stub_remote"
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
        locator_tiers=_ANCHORED,
        page_fidelity=True,
        determinism=capabilities_module.Determinism.OPAQUE_REMOTE,
        egress=capabilities_module.Egress.DECLARED_ENDPOINT,
        endpoint_host="parser.example.com",
        cost_class=capabilities_module.CostClass.METERED,
    )


#: Every adapter that must pass the conformance suite unchanged.
CONFORMING_ADAPTERS: tuple[base.ParserAdapter, ...] = (
    StubBlockSequenceAdapter(),
    StubElementListAdapter(),
    StubMarkdownAdapter(),
)


def make_artifact(
    path: str, size_bytes: int, **overrides: object
) -> shapes.AcquiredArtifact:
    """Build an artifact pointing at a fixture file.

    Args:
      path: Local path to the fixture.
      size_bytes: The fixture's size on disk.
      **overrides: Fields to override on the artifact.

    Returns:
      An artifact suitable for driving the parser service in tests.
    """
    fields: dict[str, object] = {
        "path": path,
        "content_hash": "sha256:stub",
        "size_bytes": size_bytes,
        "document_id": "doc_stub",
        "version_id": "sha256:stub-version",
        "source_class": document.SourceClass.USER_UPLOAD,
        "filename": "fixture.md",
        "retrieved_at": datetime.datetime(
            2026, 8, 15, 12, 0, tzinfo=datetime.timezone.utc
        ),
    }
    fields.update(overrides)
    return shapes.AcquiredArtifact(**fields)
