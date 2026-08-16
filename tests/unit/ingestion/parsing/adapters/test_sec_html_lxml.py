"""Golden tests for the SEC HTML adapter (03 §13).

Contract compliance lives in the shared conformance suite; these tests
pin **content** against two real Photronics filings under
``tests/fixtures/sec/``: a 10-Q with full financial statements and a
small 8-K. Per 03 §13, they assert critical structure — an expected
Item heading, a table shape and one specific fact value, locators, and
coverage — rather than exact full text.

The suite runs with sockets disabled (the shared ``no_network``
fixture): this is 03 §4.1's requirement that the SEC adapter parses an
already-acquired filing with the network unavailable, asserted rather
than assumed.
"""

# pylint: disable=protected-access  # white-box tests of adapter internals

import os

import lxml.html
import pytest

from contracts import document
from contracts import quality
from ingestion.parsing import detector as detector_module
from ingestion.parsing import service as service_module
from ingestion.parsing import shapes
from ingestion.parsing.adapters import sec_html_lxml

_FIXTURES = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    os.pardir,
    os.pardir,
    os.pardir,
    "fixtures",
    "sec",
)
_TEN_Q = os.path.normpath(os.path.join(_FIXTURES, "photronics_2026_q2_10q.htm"))
_EIGHT_K = os.path.normpath(
    os.path.join(_FIXTURES, "photronics_2026_05_8k.htm")
)


def _artifact(path: str) -> shapes.AcquiredArtifact:
    """Build the artifact the ingestion service would hand over."""
    return shapes.AcquiredArtifact(
        path=path,
        content_hash="sha256:golden",
        size_bytes=os.path.getsize(path),
        document_id="doc_golden",
        version_id="sha256:golden-version",
        source_class=document.SourceClass.SEC_FILING,
        filename=os.path.basename(path),
        expected_source_type=document.SourceType.SEC_FILING,
    )


@pytest.fixture(name="ten_q", scope="module")
def ten_q_fixture():
    """Parse the 10-Q once for the module."""
    return service_module.ParserService().parse(_artifact(_TEN_Q))


@pytest.fixture(name="eight_k", scope="module")
def eight_k_fixture():
    """Parse the 8-K once for the module."""
    return service_module.ParserService().parse(_artifact(_EIGHT_K))


class TestTenQ:
    """The 10-Q golden fixture (03 §13)."""

    def test_the_parse_is_valid(self, ten_q):
        """A clean filing produces a valid verdict with no rejects."""
        assert ten_q.status is quality.QualityVerdict.VALID
        assert ten_q.error is None
        assert not ten_q.parsed_document.parse_quality.rejected_blocks

    def test_detection_names_inline_xbrl(self, ten_q):
        """The filing routes through the SEC inline-XBRL format."""
        assert ten_q.detected_format is (
            detector_module.DetectedFormat.SEC_INLINE_XBRL_HTML
        )
        assert ten_q.parser_used == "sec_html_lxml"

    def test_filing_identity_is_complete(self, ten_q):
        """CIK, form, period, and company all survive parsing (03 §7.3)."""
        metadata = ten_q.parsed_document.business_metadata
        assert metadata.cik == "0000810136"
        assert metadata.company == "PHOTRONICS, INC."
        assert metadata.document_type == "10-Q"
        assert metadata.ticker == "PLAB"
        assert metadata.reporting_period

    def test_expected_item_headings_are_found(self, ten_q):
        """Form-aware section rules find the 10-Q's Parts and Items."""
        headings = [
            block.text.lower()
            for block in ten_q.parsed_document.blocks
            if block.type is document.BlockType.HEADING
        ]
        assert any(text.startswith("part i.") for text in headings)
        assert any(text.startswith("item 1.") for text in headings)
        assert any(text.startswith("item 2.") for text in headings)

    def test_heading_path_encloses_body_text(self, ten_q):
        """Narrative under an Item carries that Item in its path."""
        assert any(
            block.type is document.BlockType.PARAGRAPH
            and len(block.heading_path) >= 2
            for block in ten_q.parsed_document.blocks
        )

    def test_a_known_fact_value_is_extracted(self, ten_q):
        """Q2 FY2026 revenue arrives typed, scaled, and dated."""
        facts = [
            block.payload
            for block in ten_q.parsed_document.blocks
            if block.type is document.BlockType.FINANCIAL_FACT
        ]
        assert len(facts) > 500
        revenue = [
            fact
            for fact in facts
            if fact.concept
            == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
            and fact.period == "2026-02-02/2026-05-03"
            and not fact.dimensions
        ]
        assert revenue
        assert revenue[0].value == 209_940_000
        assert revenue[0].unit == "USD"

    def test_the_income_statement_grid_survives(self, ten_q):
        """A financial-statement table keeps a real merged-header grid."""
        tables = [
            block.payload
            for block in ten_q.parsed_document.blocks
            if block.type is document.BlockType.TABLE
        ]
        assert len(tables) > 50
        spanning = [
            table
            for table in tables
            if any(
                cell.is_origin
                and cell.raw_text == "Three Months Ended"
                and (cell.column_span or 1) > 1
                for cell in table.cells
            )
        ]
        assert spanning

    def test_every_block_is_anchored(self, ten_q):
        """Every admitted block carries a tier-1 source anchor."""
        for block in ten_q.parsed_document.blocks:
            assert block.locator_tier is quality.LocatorTier.ANCHORED
            assert block.locator.xpath

    def test_coverage_is_plausible(self, ten_q):
        """Extraction clears the HTML coverage floor (03 §7.1)."""
        metrics = ten_q.parsed_document.parse_quality.metrics
        assert metrics.characters > 100_000
        assert metrics.tables > 50


class TestEightK:
    """The 8-K golden fixture (03 §13)."""

    def test_the_parse_is_valid(self, eight_k):
        """The small filing still clears every gate."""
        assert eight_k.status is quality.QualityVerdict.VALID

    def test_the_8k_items_are_recognized(self, eight_k):
        """8-K Items are a different set and are still found (03 §7.1)."""
        headings = [
            block.text.lower()
            for block in eight_k.parsed_document.blocks
            if block.type is document.BlockType.HEADING
        ]
        assert any(text.startswith("item 2.02") for text in headings)
        assert any(text.startswith("item 9.01") for text in headings)

    def test_filing_identity_is_complete(self, eight_k):
        """Cover-page dei facts populate the identity fields."""
        metadata = eight_k.parsed_document.business_metadata
        assert metadata.cik == "0000810136"
        assert metadata.document_type == "8-K"
        assert metadata.reporting_period

    def test_reparsing_is_byte_identical(self, eight_k):
        """The route is deterministic under a fixed manifest (03 §1.1)."""
        again = service_module.ParserService().parse(_artifact(_EIGHT_K))
        assert (
            again.parsed_document.model_dump_json()
            == eight_k.parsed_document.model_dump_json()
        )
        assert again.parse_id == eight_k.parse_id


class TestVerifierFindings:
    """Regressions for the 2026-08-15 adversarial verification round."""

    def test_word_form_values_are_decoded_with_scale(self):
        """``numwordsen`` is a mechanical ixt transform (F1)."""
        cases = [
            ("five", "6", 5_000_000),
            ("twenty", "-2", 0.2),
            ("none", "3", 0),
            ("eleven", None, 11),
            ("twenty-five million", None, 25_000_000),
        ]
        for text, scale, expected in cases:
            element = lxml.html.fromstring(
                '<ix:nonfraction name="a:b"'
                + (f' scale="{scale}"' if scale else "")
                + ' format="ixt-sec:numwordsen">x</ix:nonfraction>'
            )
            assert sec_html_lxml._numeric_value(text, element) == expected, text

    def test_an_unknown_word_keeps_the_raw_text(self):
        """Outside the registry vocabulary, nothing is invented."""
        element = lxml.html.fromstring(
            '<ix:nonfraction name="a:b" format="ixt-sec:numwordsen">'
            "x</ix:nonfraction>"
        )
        assert sec_html_lxml._numeric_value("umpteen", element) == "umpteen"

    def test_scaling_is_exact_decimal_arithmetic(self):
        """``16.6 x 10^6`` must not grow float tail digits (F2)."""
        element = lxml.html.fromstring(
            '<ix:nonfraction name="a:b" scale="6"'
            ' format="ixt:num-dot-decimal">x</ix:nonfraction>'
        )
        assert sec_html_lxml._numeric_value("16.6", element) == 16_600_000
        small = lxml.html.fromstring(
            '<ix:nonfraction name="a:b" scale="-2"'
            ' format="ixt:num-dot-decimal">x</ix:nonfraction>'
        )
        assert sec_html_lxml._numeric_value("5.9", small) == 0.059

    def test_facts_carry_their_enclosing_item(self, ten_q):
        """A fact is attributable to its Item without re-deriving the
        xpath (F4)."""
        facts = [
            block
            for block in ten_q.parsed_document.blocks
            if block.type is document.BlockType.FINANCIAL_FACT
        ]
        with_path = [block for block in facts if block.heading_path]
        assert len(with_path) > len(facts) * 0.9
        assert any(
            any("item" in part.lower() for part in block.heading_path)
            for block in with_path
        )


class TestHeadingPathConvention:
    """03 §5.3: ``heading_path`` is *enclosing* headings only."""

    def test_a_heading_block_does_not_enclose_itself(self, ten_q):
        """Heading blocks carry the exclusive path, matching the
        shared markdown converter's convention (design-review round)."""
        for block in ten_q.parsed_document.blocks:
            if block.type is not document.BlockType.HEADING:
                continue
            assert block.text not in block.heading_path
