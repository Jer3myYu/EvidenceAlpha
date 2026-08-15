"""Quality vocabulary shared by parsing, chunking, and retrieval.

This module is part of the neutral ``contracts`` layer and imports
nothing else in the project (01 §8). It holds the closed enumerations
that travel out of the parser, into chunk metadata, and back into
retrieval filters: locator tiers (03 §5.5), warning codes (03 §8.2),
block rejection reasons and document verdicts (03 §7.4).

A warning that cannot be filtered on is a log line, not metadata, which
is why every code here is a closed enum member rather than free text.
"""

import enum


@enum.unique
class LocatorTier(enum.IntEnum):
    """How precisely a block can be pointed at (03 §5.5).

    The numeric value is the tier number, so a **lower** value is a
    better locator. Use :meth:`meets` rather than comparing values
    directly, because the natural reading of "tier 2 or better" is the
    opposite of ``>=``.
    """

    ANCHORED = 1
    COARSE = 2
    DIAGNOSTIC = 3

    def meets(self, required: "LocatorTier") -> bool:
        """Return whether this tier is at least as precise as required.

        Args:
          required: The minimum tier a route or adapter demands.

        Returns:
          True when this tier is the required tier or a better one.
        """
        return self.value <= required.value


@enum.unique
class QualityVerdict(enum.StrEnum):
    """Per-document gate verdict (03 §7.4).

    Admission is per block; this verdict is per document.
    """

    VALID = "valid"
    PARTIAL = "partial"
    FAILED = "failed"


@enum.unique
class WarningCode(enum.StrEnum):
    """Closed set of parser warning codes (03 §8.2).

    These reach chunk metadata and therefore retrieval filters, so the
    set is closed and additions are a deliberate contract change.
    """

    TABLE_STRUCTURE_LOST = "TABLE_STRUCTURE_LOST"
    TABLE_TYPING_UNAVAILABLE = "TABLE_TYPING_UNAVAILABLE"
    OCR_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
    LOCATOR_MISSING = "LOCATOR_MISSING"
    LOCATOR_TIER_DEGRADED = "LOCATOR_TIER_DEGRADED"
    COVERAGE_BELOW_THRESHOLD = "COVERAGE_BELOW_THRESHOLD"
    GENERATIVE_EXTRACTION = "GENERATIVE_EXTRACTION"
    GROUNDING_UNVERIFIED = "GROUNDING_UNVERIFIED"
    FALLBACK_ADAPTER_USED = "FALLBACK_ADAPTER_USED"
    ENCODING_FALLBACK_USED = "ENCODING_FALLBACK_USED"
    SEC_IDENTITY_INCOMPLETE = "SEC_IDENTITY_INCOMPLETE"
    SEC_SECTIONS_MISSING = "SEC_SECTIONS_MISSING"
    EXPECTATION_MISMATCH = "EXPECTATION_MISMATCH"
    BLOCK_ORDER_UNSTABLE = "BLOCK_ORDER_UNSTABLE"
    HEADING_STRUCTURE_MISSING = "HEADING_STRUCTURE_MISSING"
    PAGE_MAP_MISSING = "PAGE_MAP_MISSING"
    BOILERPLATE_RATIO_HIGH = "BOILERPLATE_RATIO_HIGH"
    CAPABILITY_OVERSTATED = "CAPABILITY_OVERSTATED"


@enum.unique
class BlockRejectionReason(enum.StrEnum):
    """Why a single block was refused admission (03 §7.4).

    Rejected blocks are persisted with their reason for diagnosis and
    are never chunked.
    """

    EMPTY_TEXT = "EMPTY_TEXT"
    LOCATOR_TIER_BELOW_MINIMUM = "LOCATOR_TIER_BELOW_MINIMUM"
    UNDECLARED_BLOCK_TYPE = "UNDECLARED_BLOCK_TYPE"
    UNDECLARED_LOCATOR_TIER = "UNDECLARED_LOCATOR_TIER"
    ORDERING_VIOLATION = "ORDERING_VIOLATION"
    GROUNDING_FAILED = "GROUNDING_FAILED"


#: Warning codes that mark content a reader must treat cautiously,
#: whatever the document verdict. Retrieval and evidence verification
#: use this set rather than re-listing codes at each call site.
CAUTION_WARNINGS: frozenset[WarningCode] = frozenset(
    {
        WarningCode.GENERATIVE_EXTRACTION,
        WarningCode.GROUNDING_UNVERIFIED,
        WarningCode.OCR_LOW_CONFIDENCE,
        WarningCode.TABLE_STRUCTURE_LOST,
    }
)
