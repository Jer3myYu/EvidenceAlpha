"""Adapter capabilities and route minimum profiles (03 §3.5).

Adapters are not interchangeable in what they can produce: a
markdown-returning cloud service cannot emit bounding boxes, and
PyMuPDF cannot read a scanned page. Portability without a capability
model means every swap is a silent corpus regression discovered months
later.

Each adapter declares what it can do statically. Each route declares a
minimum profile. The registry refuses to bind an adapter that falls
below its route's minimum **at startup, not at parse time**, which is
the whole point of the model.
"""

import enum

import pydantic

from contracts import document
from contracts import quality
from ingestion.parsing import shapes


@enum.unique
class TableFidelity(enum.IntEnum):
    """How much table structure an adapter can preserve (03 §3.5).

    Ordered: a higher value is strictly more capable, so a route
    minimum is a plain ``>=`` comparison.
    """

    NONE = 0
    TEXT = 1
    GRID = 2
    TYPED_GRID = 3


@enum.unique
class ExtractionClass(enum.IntEnum):
    """How an adapter arrives at its output (03 §3.5, §3.8).

    Ordered by how far the output can drift from the source bytes.
    ``GENERATIVE`` can invent text that was never in the filing, which
    is why financial routes cap the class rather than merely warning.
    """

    RULE_BASED = 0
    MODEL_ASSISTED = 1
    GENERATIVE = 2


@enum.unique
class Determinism(enum.StrEnum):
    """How reproducible an adapter's output is (03 §1.1, §5.1)."""

    PINNED = "pinned"
    VERSIONED_REMOTE = "versioned_remote"
    OPAQUE_REMOTE = "opaque_remote"


@enum.unique
class Egress(enum.StrEnum):
    """Whether an adapter transmits the artifact anywhere (03 §3.7).

    ``NONE`` is the only value any adapter may declare in the MVP, and
    the egress policy enforces that at startup. Remote transport is
    deferred until a hosted adapter is actually wanted.
    """

    NONE = "none"
    DECLARED_ENDPOINT = "declared_endpoint"


@enum.unique
class CostClass(enum.StrEnum):
    """Whether using an adapter costs money per document (03 §3.7)."""

    FREE = "free"
    METERED = "metered"


@enum.unique
class RouteRole(enum.StrEnum):
    """A parsing role, independent of who implements it (03 §3.3).

    The dispatcher knows roles; the registry binds a role to a concrete
    implementation. That indirection is what makes swapping a parser a
    one-line binding change rather than a dispatcher change.
    """

    SEC_HTML_PARSER = "sec_html_parser"
    NEWS_HTML_PARSER = "news_html_parser"
    GENERIC_HTML_PARSER = "generic_html_parser"
    PDF_LAYOUT_PARSER = "pdf_layout_parser"
    SCANNED_PDF_PARSER = "scanned_pdf_parser"
    WORD_PARSER = "word_parser"
    PRESENTATION_PARSER = "presentation_parser"
    SPREADSHEET_PARSER = "spreadsheet_parser"
    DELIMITED_TABLE_PARSER = "delimited_table_parser"
    XBRL_PARSER = "xbrl_parser"
    XML_PARSER = "xml_parser"
    MARKDOWN_PARSER = "markdown_parser"
    JSON_PARSER = "json_parser"
    PLAIN_TEXT_PARSER = "plain_text_parser"
    IMAGE_OCR_PARSER = "image_ocr_parser"


class AdapterCapabilities(pydantic.BaseModel):
    """What one adapter implementation declares it can do (03 §3.5).

    A declaration that overstates the adapter fails the conformance
    suite (03 §13) rather than the corpus, and the quality gate asserts
    only what was promised here.

    ``native_shape`` is one field beyond 03 §3.5's list. It is required
    because 03 §5.1 puts "the converter version for the shape it
    returns" in the **planned** manifest, which must be computable
    before parsing — so the shape has to be a static declaration rather
    than something observed in the output. Proposed as an amendment to
    03 §3.5.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    block_types: frozenset[document.BlockType]
    native_shape: shapes.NativeShape
    table_fidelity: TableFidelity
    locator_tiers: frozenset[quality.LocatorTier]
    page_fidelity: bool = False
    ocr: bool = False
    extraction_class: ExtractionClass = ExtractionClass.RULE_BASED
    determinism: Determinism = Determinism.PINNED
    egress: Egress = Egress.NONE
    cost_class: CostClass = CostClass.FREE
    max_bytes: int | None = pydantic.Field(default=None, ge=1)
    endpoint_host: str | None = None

    @pydantic.model_validator(mode="after")
    def _check_egress_and_endpoint(self) -> "AdapterCapabilities":
        """Keep the endpoint declaration consistent with egress."""
        if self.egress is Egress.NONE and self.endpoint_host is not None:
            raise ValueError(
                "an adapter declaring egress=none must declare no endpoint"
            )
        if (
            self.egress is Egress.DECLARED_ENDPOINT
            and self.endpoint_host is None
        ):
            raise ValueError(
                "an adapter declaring egress=declared_endpoint must name "
                "exactly one endpoint host"
            )
        return self

    @property
    def best_locator_tier(self) -> quality.LocatorTier:
        """Return the most precise tier this adapter claims to reach."""
        if not self.locator_tiers:
            return quality.LocatorTier.DIAGNOSTIC
        return min(self.locator_tiers, key=lambda tier: tier.value)


class RouteProfile(pydantic.BaseModel):
    """The floor an adapter must clear to serve a route (03 §3.5).

    The route minimum guarantees the corpus floor; the adapter's own
    declaration is what the gate then holds it to. The two are separate
    on purpose: an adapter is never failed for missing a bounding box it
    never claimed, but it is also not allowed onto a route that needs
    one.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    role: RouteRole
    min_table_fidelity: TableFidelity = TableFidelity.NONE
    min_locator_tier: quality.LocatorTier = quality.LocatorTier.DIAGNOSTIC
    requires_page_fidelity: bool = False
    max_extraction_class: ExtractionClass = ExtractionClass.GENERATIVE
    required_block_types: frozenset[document.BlockType] = frozenset()


def check_capabilities(
    capabilities: AdapterCapabilities, profile: RouteProfile
) -> list[str]:
    """Return every way an adapter falls short of a route minimum.

    Args:
      capabilities: What the adapter declared about itself.
      profile: The route's minimum capability profile.

    Returns:
      A list of human-readable violations, empty when the adapter meets
      the profile. The caller decides whether a violation is fatal; the
      registry treats every one of them as fatal at startup.
    """
    violations: list[str] = []
    if capabilities.table_fidelity < profile.min_table_fidelity:
        violations.append(
            f"table_fidelity {capabilities.table_fidelity.name} is below "
            f"the route minimum {profile.min_table_fidelity.name}"
        )
    if not capabilities.best_locator_tier.meets(profile.min_locator_tier):
        violations.append(
            f"best locator tier {capabilities.best_locator_tier.name} is "
            f"below the route minimum {profile.min_locator_tier.name}"
        )
    if profile.requires_page_fidelity and not capabilities.page_fidelity:
        violations.append("the route requires page fidelity")
    if capabilities.extraction_class > profile.max_extraction_class:
        violations.append(
            f"extraction_class {capabilities.extraction_class.name} exceeds "
            f"the route maximum {profile.max_extraction_class.name}"
        )
    missing = profile.required_block_types - capabilities.block_types
    if missing:
        names = ", ".join(sorted(block.value for block in missing))
        violations.append(f"the route requires block types: {names}")
    return violations


#: Minimum capability profiles for the MVP routes (03 §3.5).
#:
#: Both financial routes cap ``extraction_class`` at ``model_assisted``
#: deliberately: a generative adapter cannot bind to a route that
#: carries financial values, and the refusal happens at startup rather
#: than per document (03 §3.8).
#:
#: The PDF route's ``GRID`` minimum was confirmed by the PyMuPDF table
#: spike (03 §14 step 6, 2026-08-15): real cell grids extract from the
#: golden filing, so the minimum stands. Were a future adapter to lose
#: that, the drop to ``TEXT`` is a one-line change here precisely
#: because the claim lives in one place.
ROUTE_PROFILES: dict[RouteRole, RouteProfile] = {
    RouteRole.SEC_HTML_PARSER: RouteProfile(
        role=RouteRole.SEC_HTML_PARSER,
        min_table_fidelity=TableFidelity.GRID,
        min_locator_tier=quality.LocatorTier.ANCHORED,
        requires_page_fidelity=False,
        max_extraction_class=ExtractionClass.MODEL_ASSISTED,
        required_block_types=frozenset(
            {
                document.BlockType.HEADING,
                document.BlockType.PARAGRAPH,
                document.BlockType.TABLE,
            }
        ),
    ),
    RouteRole.PDF_LAYOUT_PARSER: RouteProfile(
        role=RouteRole.PDF_LAYOUT_PARSER,
        min_table_fidelity=TableFidelity.GRID,
        min_locator_tier=quality.LocatorTier.COARSE,
        requires_page_fidelity=True,
        max_extraction_class=ExtractionClass.MODEL_ASSISTED,
        required_block_types=frozenset(
            {
                document.BlockType.PARAGRAPH,
                document.BlockType.TABLE,
            }
        ),
    ),
}
