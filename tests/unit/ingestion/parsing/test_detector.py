"""Tests for format detection (03 §3.2)."""

import zipfile

import pytest

from contracts import document
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector as detector_module
from ingestion.parsing import registry as registry_module
from ingestion.parsing import shapes


def _artifact(path, source_class=None, **overrides):
    """Build an artifact naming a fixture file."""
    fields = {
        "path": str(path),
        "content_hash": "sha256:test",
        "size_bytes": path.stat().st_size,
        "document_id": "doc",
        "version_id": "sha256:v",
        "source_class": source_class or document.SourceClass.USER_UPLOAD,
    }
    fields.update(overrides)
    return shapes.AcquiredArtifact(**fields)


def _write(tmp_path, name, content):
    """Write a fixture file and return its path."""
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _detect(path, **kwargs):
    """Detect the format of a fixture file."""
    return detector_module.FormatDetector().detect(_artifact(path, **kwargs))


class TestHtmlFamily:
    """Source-aware HTML routing (03 §3.2, §3.3)."""

    def test_inline_xbrl_is_detected_by_namespace(self, tmp_path):
        """Inline XBRL markers beat the caller's context."""
        path = _write(
            tmp_path,
            "filing.htm",
            '<html xmlns:ix="http://www.xbrl.org/2013/inlinexbrl">'
            "<body><ix:nonFraction>1</ix:nonFraction></body></html>",
        )
        result = _detect(path, source_class=document.SourceClass.SEC_FILING)
        assert (
            result.format is detector_module.DetectedFormat.SEC_INLINE_XBRL_HTML
        )
        assert result.resolution is detector_module.Resolution.EXACT

    def test_sec_context_gives_the_sec_route(self, tmp_path):
        """Plain filing HTML routes by trusted caller context."""
        path = _write(
            tmp_path, "filing.htm", "<html><body>Item 1</body></html>"
        )
        result = _detect(path, source_class=document.SourceClass.SEC_FILING)
        assert result.format is detector_module.DetectedFormat.SEC_HTML

    def test_news_context_gives_the_news_route(self, tmp_path):
        """The same bytes route differently for a news article."""
        path = _write(tmp_path, "story.html", "<html><body>Story</body></html>")
        result = _detect(path, source_class=document.SourceClass.NEWS_ARTICLE)
        assert result.format is detector_module.DetectedFormat.NEWS_HTML

    @pytest.mark.parametrize("name", ["a.htm", "a.html", "a.xhtml"])
    def test_html_extensions_share_one_family(self, tmp_path, name):
        """`.htm`, `.html`, and `.xhtml` all reach the HTML family."""
        path = _write(tmp_path, name, "<html><body>x</body></html>")
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.GENERIC_HTML
        assert not result.conflicts


class TestMisleadingSignals:
    """A misleading hint is a conflict, never a wrong dispatch."""

    def test_pdf_bytes_named_html_are_still_a_pdf(self, tmp_path):
        """Magic bytes outrank the file extension (03 §17)."""
        path = _write(tmp_path, "report.bin", b"%PDF-1.7\n%stub\n")
        result = _detect(path, filename="report.htm")
        assert result.format is detector_module.DetectedFormat.PDF
        assert result.resolution is detector_module.Resolution.EXACT
        assert any("extension" in conflict for conflict in result.conflicts)

    def test_wrong_media_type_is_recorded_not_obeyed(self, tmp_path):
        """A wrong Content-Type is a conflict, not a decision."""
        path = _write(tmp_path, "data.json", '{"a": 1}')
        result = _detect(path, declared_media_type="text/html")
        assert result.format is detector_module.DetectedFormat.JSON
        assert any("media type" in conflict for conflict in result.conflicts)


class TestContainers:
    """ZIP discrimination and its limits (03 §3.2.1)."""

    def _zip(self, tmp_path, name, entries, compress=False):
        """Write a ZIP fixture with the given entries."""
        path = tmp_path / name
        compression = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for entry, content in entries.items():
                archive.writestr(entry, content)
        return path

    def test_docx_is_discriminated_by_its_parts(self, tmp_path):
        """`word/` parts name the real format."""
        path = self._zip(
            tmp_path,
            "a.docx",
            {
                "[Content_Types].xml": "<Types/>",
                "word/document.xml": "<document/>",
            },
        )
        assert _detect(path).format is detector_module.DetectedFormat.DOCX

    def test_xlsx_is_discriminated_by_its_parts(self, tmp_path):
        """`xl/` parts name a spreadsheet."""
        path = self._zip(
            tmp_path,
            "a.xlsx",
            {
                "[Content_Types].xml": "<Types/>",
                "xl/workbook.xml": "<workbook/>",
            },
        )
        assert _detect(path).format is detector_module.DetectedFormat.XLSX

    def test_plain_archive_is_unsupported(self, tmp_path):
        """An ordinary archive is not a document."""
        path = self._zip(tmp_path, "a.zip", {"notes.txt": "hello"})
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.ZIP_ARCHIVE
        assert result.resolution is detector_module.Resolution.UNSUPPORTED

    def test_entry_count_limit_is_a_controlled_failure(self, tmp_path):
        """Too many entries stops inspection rather than truncating."""
        path = self._zip(
            tmp_path, "many.zip", {f"f{i}.txt": "x" for i in range(20)}
        )
        limits = detector_module.ZipLimits(max_entries=5)
        with pytest.raises(detector_module.DetectionError, match="entry limit"):
            detector_module.inspect_zip(str(path), limits)

    def test_expansion_ratio_limit_is_a_controlled_failure(self, tmp_path):
        """A decompression bomb is refused, not expanded."""
        path = self._zip(
            tmp_path, "bomb.zip", {"big.txt": "a" * 200_000}, compress=True
        )
        limits = detector_module.ZipLimits(max_expansion_ratio=1.5)
        with pytest.raises(
            detector_module.DetectionError, match="expansion ratio"
        ):
            detector_module.inspect_zip(str(path), limits)

    def test_expanded_size_limit_is_a_controlled_failure(self, tmp_path):
        """Total expanded size is bounded independently."""
        path = self._zip(tmp_path, "big.zip", {"big.txt": "a" * 50_000})
        limits = detector_module.ZipLimits(max_expanded_bytes=1_000)
        with pytest.raises(detector_module.DetectionError, match="expands to"):
            detector_module.inspect_zip(str(path), limits)


class TestTextFormats:
    """Content inspection for text-bearing artifacts."""

    def test_json_is_detected_by_syntax(self, tmp_path):
        """A complete JSON value is JSON."""
        path = _write(tmp_path, "a.json", '{"revenue": 1204}')
        assert _detect(path).format is detector_module.DetectedFormat.JSON

    def test_csv_is_detected_by_consistent_delimiters(self, tmp_path):
        """Consistent comma counts across lines mean CSV."""
        path = _write(tmp_path, "a.csv", "a,b,c\n1,2,3\n4,5,6\n")
        assert _detect(path).format is detector_module.DetectedFormat.CSV

    def test_tsv_is_detected_by_tabs(self, tmp_path):
        """Tabs give TSV rather than CSV."""
        path = _write(tmp_path, "a.tsv", "a\tb\n1\t2\n3\t4\n")
        assert _detect(path).format is detector_module.DetectedFormat.TSV

    def test_xbrl_instance_is_detected(self, tmp_path):
        """XBRL markers separate an instance from generic XML."""
        path = _write(
            tmp_path,
            "a.xbrl",
            '<?xml version="1.0"?><xbrl '
            'xmlns="http://www.xbrl.org/2003/instance"/>',
        )
        assert _detect(path).format is detector_module.DetectedFormat.XBRL_XML

    def test_generic_xml_stays_generic(self, tmp_path):
        """Uncertain XBRL detection does not claim financial facts."""
        path = _write(tmp_path, "a.xml", '<?xml version="1.0"?><root/>')
        assert (
            _detect(path).format is detector_module.DetectedFormat.GENERIC_XML
        )

    def test_markdown_falls_back_to_the_extension(self, tmp_path):
        """Markdown has no signature, so the extension decides."""
        path = _write(tmp_path, "a.md", "# Title\n\nBody text.\n")
        assert _detect(path).format is detector_module.DetectedFormat.MARKDOWN

    def test_plain_text_is_the_last_resort(self, tmp_path):
        """Unstructured text is plain text, not a guess at structure."""
        path = _write(tmp_path, "a.txt", "just some prose\nand more prose\n")
        assert _detect(path).format is detector_module.DetectedFormat.PLAIN_TEXT


#: Directory object types, from MS-CFB: unallocated, storage, stream,
#: and root storage.
_UNALLOCATED, _STORAGE, _STREAM, _ROOT = 0x00, 0x01, 0x02, 0x05


def _ole2(tmp_path, name, stream_names, object_type=_STREAM):
    """Write a minimal 512-byte-sector compound file.

    Builds only what detection reads: the header, one FAT sector, and a
    one-sector directory whose entries carry the given names.

    Args:
      tmp_path: Directory to write into.
      name: Filename for the fixture.
      stream_names: Directory entry names, in order.
      object_type: The object type byte every entry carries; pass
        ``_UNALLOCATED`` to build a container of deleted entries.
    """
    sector_size = 512
    header = bytearray(b"\x00" * sector_size)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    header[28:30] = (0xFFFE).to_bytes(2, "little")  # byte order
    header[30:32] = (9).to_bytes(2, "little")  # 512-byte sectors
    header[44:48] = (1).to_bytes(4, "little")  # one FAT sector
    header[48:52] = (1).to_bytes(4, "little")  # directory at sector 1
    header[76:80] = (0).to_bytes(4, "little")  # FAT itself at sector 0

    fat = bytearray(b"\xff" * sector_size)
    fat[0:4] = (0xFFFFFFFD).to_bytes(4, "little")  # sector 0: the FAT
    fat[4:8] = (0xFFFFFFFE).to_bytes(4, "little")  # sector 1: chain end

    directory = bytearray()
    for stream_name in stream_names:
        entry = bytearray(b"\x00" * 128)
        encoded = stream_name.encode("utf-16-le") + b"\x00\x00"
        entry[0 : len(encoded)] = encoded
        entry[64:66] = len(encoded).to_bytes(2, "little")
        entry[66] = object_type
        directory += entry
    directory += b"\x00" * (sector_size - len(directory))
    return _write(tmp_path, name, bytes(header + fat + directory))


class TestLegacyCompoundFiles:
    """OLE2 gets the same treatment as ZIP (03 §3.2.1).

    Regression: ``XLS_LEGACY`` was unreachable — every compound file
    resolved to ``OLE2_COMPOUND``/``AMBIGUOUS``, so the enum member and
    its ``ROUTE_TABLE`` entry were dead code and a legacy workbook
    failed with ``PARSE_FAILED``/``different_source`` rather than
    reaching the spreadsheet route.
    """

    def test_workbook_stream_names_a_spreadsheet(self, tmp_path):
        """A `Workbook` stream makes a compound file an XLS."""
        path = _ole2(tmp_path, "a.xls", ["Root Entry", "Workbook"])
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.XLS_LEGACY
        assert result.resolution is detector_module.Resolution.EXACT
        assert not result.conflicts

    def test_legacy_book_stream_is_also_a_spreadsheet(self, tmp_path):
        """The pre-Excel 97 `Book` spelling resolves the same way."""
        path = _ole2(tmp_path, "a.xls", ["Root Entry", "Book"])
        assert _detect(path).format is detector_module.DetectedFormat.XLS_LEGACY

    def test_a_spreadsheet_reaches_the_spreadsheet_route(self, tmp_path):
        """The detected format must actually resolve to a route."""
        path = _ole2(tmp_path, "a.xls", ["Root Entry", "Workbook"])
        role = registry_module.ROUTE_TABLE.get(_detect(path).format)
        assert role is capabilities_module.RouteRole.SPREADSHEET_PARSER

    def test_other_compound_files_stay_ambiguous(self, tmp_path):
        """A Word or PowerPoint compound file has no route to claim."""
        path = _ole2(tmp_path, "a.doc", ["Root Entry", "WordDocument"])
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.OLE2_COMPOUND
        assert result.resolution is detector_module.Resolution.AMBIGUOUS

    def test_a_deleted_workbook_entry_does_not_name_the_file(self, tmp_path):
        """An unallocated entry keeps its name; it must not be read.

        MS-CFB frees a directory slot without clearing the name bytes,
        so a Word document that once held a `Workbook` stream would
        otherwise be named a spreadsheet and routed to one.
        """
        path = _ole2(
            tmp_path,
            "a.doc",
            ["Root Entry", "Workbook"],
            object_type=_UNALLOCATED,
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.OLE2_COMPOUND
        assert result.resolution is detector_module.Resolution.AMBIGUOUS

    def test_a_storage_entry_still_counts(self, tmp_path):
        """Storage and root entries are live and are read."""
        path = _ole2(
            tmp_path, "a.xls", ["Root Entry", "Workbook"], object_type=_STORAGE
        )
        assert _detect(path).format is detector_module.DetectedFormat.XLS_LEGACY

    def test_stream_names_are_reported(self, tmp_path):
        """Inspection reports what it read, not just its conclusion."""
        path = _ole2(tmp_path, "a.xls", ["Root Entry", "Workbook"])
        inspection = detector_module.inspect_ole2(str(path))
        assert inspection.stream_names == ["Root Entry", "Workbook"]

    def test_a_truncated_compound_file_is_ambiguous(self, tmp_path):
        """A header too short to inspect resolves to ambiguous, not raise."""
        path = _write(tmp_path, "a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        assert (
            detector_module.inspect_ole2(str(path)).format
            is detector_module.DetectedFormat.OLE2_COMPOUND
        )

    def test_an_unreadable_compound_file_is_a_detection_error(self, tmp_path):
        """An unreadable container is a controlled failure."""
        with pytest.raises(detector_module.DetectionError):
            detector_module.inspect_ole2(str(tmp_path / "absent.xls"))


class TestLargeJsonDocuments:
    """JSON above the sniff window (03 §3.2).

    Regression: ``_is_json`` parsed the truncated window, so any JSON
    larger than ``SNIFF_BYTES`` — which every SEC ``companyfacts``
    response is — fell through to ``plain_text``. That is the silent
    text fallback the design forbids, reached one stage before route
    dispatch can guard against it.
    """

    def _big_json(self, tmp_path, name="facts.json"):
        """Write a single-line JSON document larger than the window."""
        entries = ",".join(
            f'"concept{index}":{{"value":{index},"unit":"USD"}}'
            for index in range(4000)
        )
        payload = (
            '{"cik":810136,"entityName":"PHOTRONICS, INC.",' + entries + "}"
        )
        assert len(payload) > detector_module.SNIFF_BYTES
        return _write(tmp_path, name, payload)

    def test_json_larger_than_the_sniff_window_is_json(self, tmp_path):
        """The window is judged as a prefix once it is truncated."""
        path = self._big_json(tmp_path)
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.JSON
        assert "content=json_prefix_syntax" in result.signals

    def test_a_large_json_array_is_json(self, tmp_path):
        """A top-level array is a prefix in the same way."""
        payload = "[" + ",".join(f'{{"i":{n}}}' for n in range(8000)) + "]"
        assert len(payload) > detector_module.SNIFF_BYTES
        path = _write(tmp_path, "rows.json", payload)
        assert _detect(path).format is detector_module.DetectedFormat.JSON

    def test_no_extension_conflict_is_recorded(self, tmp_path):
        """The `.json` hint now agrees with the decision."""
        assert not _detect(self._big_json(tmp_path)).conflicts

    def test_a_large_json_reaches_the_json_route(self, tmp_path):
        """Detection must land on a route, not on plain text."""
        role = registry_module.ROUTE_TABLE.get(
            _detect(self._big_json(tmp_path)).format
        )
        assert role is capabilities_module.RouteRole.JSON_PARSER

    def test_truncated_prose_is_not_json(self, tmp_path):
        """A large text file that opens with a brace is still text."""
        payload = "{ this is prose, not a document. " * 5000
        assert len(payload) > detector_module.SNIFF_BYTES
        path = _write(tmp_path, "notes.txt", payload)
        assert _detect(path).format is not detector_module.DetectedFormat.JSON

    def test_a_small_malformed_json_is_not_json(self, tmp_path):
        """Below the window there is no truncation to forgive."""
        path = _write(tmp_path, "broken.json", '{"a": 1, "b":')
        assert _detect(path).format is not detector_module.DetectedFormat.JSON

    def test_a_complete_value_with_trailing_junk_is_not_json(self, tmp_path):
        """A closed value followed by content is not a JSON prefix."""
        payload = '{"a": 1} ' + "x" * detector_module.SNIFF_BYTES
        path = _write(tmp_path, "mixed.json", payload)
        assert _detect(path).format is not detector_module.DetectedFormat.JSON

    def test_a_brace_inside_a_string_does_not_confuse_the_scan(self, tmp_path):
        """String contents are skipped, braces and commas included."""
        entries = ",".join(
            f'"k{index}":"a, b {{ c }} \\" d"' for index in range(3000)
        )
        payload = "{" + entries + "}"
        assert len(payload) > detector_module.SNIFF_BYTES
        path = _write(tmp_path, "quoted.json", payload)
        assert _detect(path).format is detector_module.DetectedFormat.JSON


class TestControlledFailures:
    """Ambiguity and unknown binaries fail loudly (03 §3.2)."""

    def test_ole2_container_is_ambiguous(self, tmp_path):
        """One signature covering .doc, .xls, and .ppt cannot resolve."""
        path = _write(
            tmp_path,
            "a.xls",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
        )
        result = _detect(path)
        assert result.resolution is detector_module.Resolution.AMBIGUOUS

    def test_unknown_binary_is_unsupported(self, tmp_path):
        """An unknown binary fails safely, never decoded as text."""
        path = _write(tmp_path, "a.bin", b"\x01\x02\x00\x03\x04")
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.UNKNOWN
        assert result.resolution is detector_module.Resolution.UNSUPPORTED

    def test_encrypted_pdf_is_flagged_before_dispatch(self, tmp_path):
        """Encryption is detected during inspection (03 §8.1)."""
        path = _write(
            tmp_path,
            "locked.pdf",
            b"%PDF-1.7\nbody\ntrailer\n<< /Encrypt 1 0 R >>\n%%EOF",
        )
        assert _detect(path).encrypted is True

    def test_plain_pdf_is_not_flagged(self, tmp_path):
        """An ordinary PDF is not reported as encrypted."""
        path = _write(tmp_path, "open.pdf", b"%PDF-1.7\nbody\n%%EOF")
        assert _detect(path).encrypted is False

    def test_missing_file_is_a_detection_error(self, tmp_path):
        """An unreadable artifact is a controlled failure."""
        artifact = shapes.AcquiredArtifact(
            path=str(tmp_path / "absent.pdf"),
            content_hash="sha256:x",
            size_bytes=0,
            document_id="d",
            version_id="v",
            source_class=document.SourceClass.USER_UPLOAD,
        )
        with pytest.raises(detector_module.DetectionError):
            detector_module.FormatDetector().detect(artifact)


def test_signals_are_recorded_in_priority_order(tmp_path):
    """The caller context is always the first signal recorded."""
    path = _write(tmp_path, "a.htm", "<html><body>x</body></html>")
    result = _detect(path, source_class=document.SourceClass.SEC_FILING)
    assert result.signals[0] == "source_class=sec_filing"


class TestSecSubmissionWrapper:
    """The EDGAR full-submission file is named, never mistaken (D3)."""

    _HEAD = (
        "<SEC-DOCUMENT>0001140361-25-045801.txt : 20251217\n"
        "<SEC-HEADER>0001140361-25-045801.hdr.sgml : 20251217\n"
        "ACCESSION NUMBER:\t0001140361-25-045801\n"
        "CONFORMED SUBMISSION TYPE:\t10-K\n"
        "<DOCUMENT>\n<TYPE>10-K\n<TEXT>\n"
        "<html><body><p>The first embedded document.</p></body></html>\n"
    )

    def test_the_wrapper_is_named_not_its_first_passenger(self, tmp_path):
        """Embedded HTML inside the window must not win detection."""
        path = _write(tmp_path, "submission.txt", self._HEAD)
        result = _detect(path, source_class=document.SourceClass.SEC_FILING)
        assert (
            result.format is detector_module.DetectedFormat.SEC_SUBMISSION_TEXT
        )
        assert result.resolution is detector_module.Resolution.UNSUPPORTED
        assert "content=sec_submission_wrapper" in result.signals

    def test_the_txt_extension_is_not_a_conflict(self, tmp_path):
        """EDGAR serves the wrapper as ``.txt``; that is not a lie."""
        path = _write(tmp_path, "submission.txt", self._HEAD)
        result = _detect(path, source_class=document.SourceClass.SEC_FILING)
        assert result.conflicts == []

    def test_the_wrapper_has_no_route(self):
        """Splitting the wrapper belongs to ingestion, not a route."""
        registry = registry_module.AdapterRegistry()
        assert (
            registry.resolve(detector_module.DetectedFormat.SEC_SUBMISSION_TEXT)
            is None
        )

    def test_an_ordinary_sgml_like_text_is_not_a_wrapper(self, tmp_path):
        """Only the leading marker names a submission file."""
        path = _write(
            tmp_path,
            "notes.txt",
            "notes about <SEC-DOCUMENT> markers\nand more prose\n",
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.PLAIN_TEXT


class TestXbrlTaxonomyFiles:
    """The instance namespace never makes a taxonomy an instance (D4)."""

    def test_a_schema_is_generic_xml(self, tmp_path):
        """An ``.xsd`` declaring XBRL namespaces is not an instance."""
        path = _write(
            tmp_path,
            "plab-2025.xsd",
            '<?xml version="1.0"?>\n'
            "<!-- generated -->\n"
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            "</xs:schema>",
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.GENERIC_XML
        assert "content=xbrl_taxonomy_root(schema)" in result.signals

    def test_a_linkbase_is_generic_xml(self, tmp_path):
        """A linkbase references the instance namespace; it is not one."""
        path = _write(
            tmp_path,
            "plab-lab.xml",
            '<?xml version="1.0"?>'
            '<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" '
            'xmlns:xbrli="http://www.xbrl.org/2003/instance"/>',
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.GENERIC_XML

    def test_a_prefixed_instance_root_is_an_instance(self, tmp_path):
        """``<xbrli:xbrl>`` is the instance root, prefix and all."""
        path = _write(
            tmp_path,
            "instance.xbrl",
            '<?xml version="1.0"?>'
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>',
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.XBRL_XML
        assert "content=xbrl_instance_root" in result.signals

    def test_comments_and_doctype_are_skipped_to_the_root(self, tmp_path):
        """Prolog noise before the root element does not confuse it."""
        path = _write(
            tmp_path,
            "instance.xml",
            '<?xml version="1.0"?>\n'
            "<!-- Created: today -->\n"
            "<!DOCTYPE something>\n"
            '<xbrl xmlns="http://www.xbrl.org/2003/instance"/>',
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.XBRL_XML


class TestMarkdownProbe:
    """The extension is never the only markdown signal (D5, 03 §3.2)."""

    def test_structure_plus_extension_is_markdown(self, tmp_path):
        """A heading at a line start is structure enough."""
        path = _write(tmp_path, "a.md", "# Title\n\nBody text.\n")
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.MARKDOWN
        assert "content=markdown_structure" in result.signals

    def test_prose_with_the_extension_stays_plain_text(self, tmp_path):
        """A ``.md`` file with no structure is plain text, with the
        disagreement recorded rather than obeyed."""
        path = _write(tmp_path, "a.md", "just prose\nand more prose\n")
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.PLAIN_TEXT
        assert any("extension .md" in c for c in result.conflicts)

    def test_structure_without_the_extension_stays_plain_text(self, tmp_path):
        """Markdown is a plain-text superset; without the extension the
        conservative answer stands."""
        path = _write(tmp_path, "a.txt", "# Title\n\nBody text.\n")
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.PLAIN_TEXT

    def test_a_pipe_table_is_structure(self, tmp_path):
        """A markdown table row counts as structure."""
        path = _write(
            tmp_path,
            "metrics.md",
            "Metric summary follows.\n\n| Metric | Value |\n|---|---|\n",
        )
        result = _detect(path)
        assert result.format is detector_module.DetectedFormat.MARKDOWN
