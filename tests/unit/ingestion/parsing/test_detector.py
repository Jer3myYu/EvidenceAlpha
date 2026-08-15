"""Tests for format detection (03 §3.2)."""

import zipfile

import pytest

from contracts import document
from ingestion.parsing import detector as detector_module
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
