"""Format detection before dispatch (03 §3.2).

Detection is deterministic and absolute: the same artifact always
resolves to the same format. It uses no models and no randomness.

The result carries a **categorical resolution** rather than a numeric
score. A synthetic confidence float that gates ingestion is worse than
no number, because nothing can calibrate it. Signals are recorded in
priority order and genuine disagreements are listed as conflicts.

Signal priority (03 §3.2):

1. trusted caller context — ``source_class`` on the artifact;
2. magic bytes and container signature;
3. content inspection;
4. HTTP ``Content-Type``;
5. file extension, which is a supporting signal and never the only one.

A lower-priority signal that disagrees with a higher-priority one is a
recorded conflict, not a failure: a misleading extension must not cause
incorrect dispatch (03 §17). ``AMBIGUOUS`` is reserved for the case
where the highest-priority signal that reaches a decision cannot itself
choose between formats.
"""

import enum
import json
import os
import zipfile

import pydantic

from contracts import document
from ingestion.parsing import shapes

#: How many leading bytes content inspection may look at.
SNIFF_BYTES = 64 * 1024

#: How many trailing bytes the encryption probe may look at.
_PDF_TRAILER_BYTES = 4096

#: Compound-file (OLE2) inspection bounds and layout, from MS-CFB. The
#: directory chain is followed only as far as the header's own DIFAT
#: reaches, which is all a document-sized container needs.
_OLE2_HEADER_BYTES = 512
_OLE2_DIRECTORY_ENTRY_BYTES = 128
_OLE2_MAX_DIRECTORY_SECTORS = 64
_OLE2_HEADER_DIFAT_ENTRIES = 109
_OLE2_HEADER_DIFAT_OFFSET = 76
#: Sector numbers at or above this are chain terminators, not sectors.
_OLE2_RESERVED_SECTOR = 0xFFFFFFFA
#: Directory object types that are live: storage, stream, and root.
#: Type 0 is an unallocated entry, whose name bytes MS-CFB leaves in
#: place.
_OLE2_ALLOCATED_OBJECT_TYPES = frozenset({0x01, 0x02, 0x05})
#: Stream names that make a compound file a legacy Excel workbook;
#: ``Book`` is the pre-Excel 97 spelling.
_XLS_STREAM_NAMES = frozenset({"Workbook", "Book"})

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_TIFF_MAGICS = (b"II*\x00", b"MM\x00*")

_INLINE_XBRL_MARKERS = (
    "http://www.xbrl.org/2013/inlinexbrl",
    "xmlns:ix=",
    "<ix:nonfraction",
    "<ix:nonnumeric",
)
_HTML_MARKERS = ("<!doctype html", "<html", "<head", "<body")

#: EDGAR's full-submission dissemination file opens with this SGML tag.
#: The wrapper bundles every document of a filing — 03 has no route for
#: it, and splitting it belongs to the ingestion service, so detection
#: names it and stops (03 §18).
_SEC_SUBMISSION_MARKER = "<sec-document>"

#: XML root local names that identify an XBRL *taxonomy* file rather
#: than an instance. A schema or linkbase declares the instance
#: namespace without being one, so the namespace alone must never decide
#: (defect D4, 2026-08-15).
_XBRL_TAXONOMY_ROOTS = frozenset({"schema", "linkbase"})

#: Structural markers a markdown document may open with. The extension
#: is never the only signal (03 §3.2), so a ``.md`` file must show at
#: least one of these at a line start before it is named markdown.
_MARKDOWN_LINE_MARKERS = ("#", "- ", "* ", "+ ", "```", ">", "|")


@enum.unique
class DetectedFormat(enum.StrEnum):
    """Formats the detector can name (03 §2).

    Naming a format is not the same as supporting it. A detected format
    with no registered adapter returns ``UNSUPPORTED_FORMAT`` with the
    name reported, so the gap is measurable (03 §3.3).

    There is deliberately no ``scanned_pdf`` member: separating a
    digital PDF from a scanned one requires reading the embedded text
    layer, which needs a PDF library. That branch belongs to the PDF
    route (03 §4.3), not to detection.
    """

    SEC_INLINE_XBRL_HTML = "sec_inline_xbrl_html"
    SEC_HTML = "sec_html"
    SEC_SUBMISSION_TEXT = "sec_submission_text"
    NEWS_HTML = "news_html"
    GENERIC_HTML = "generic_html"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    XLS_LEGACY = "xls_legacy"
    ZIP_ARCHIVE = "zip_archive"
    CSV = "csv"
    TSV = "tsv"
    XBRL_XML = "xbrl_xml"
    GENERIC_XML = "generic_xml"
    JSON = "json"
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    PNG_IMAGE = "png_image"
    JPEG_IMAGE = "jpeg_image"
    TIFF_IMAGE = "tiff_image"
    OLE2_COMPOUND = "ole2_compound"
    UNKNOWN = "unknown"


@enum.unique
class Resolution(enum.StrEnum):
    """How firmly detection settled on a format (03 §3.2)."""

    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


_MEDIA_TYPES: dict[DetectedFormat, str] = {
    DetectedFormat.SEC_INLINE_XBRL_HTML: "text/html",
    DetectedFormat.SEC_HTML: "text/html",
    DetectedFormat.SEC_SUBMISSION_TEXT: "text/plain",
    DetectedFormat.NEWS_HTML: "text/html",
    DetectedFormat.GENERIC_HTML: "text/html",
    DetectedFormat.PDF: "application/pdf",
    DetectedFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
    DetectedFormat.XLSX: (
        "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
    ),
    DetectedFormat.PPTX: (
        "application/vnd.openxmlformats-officedocument."
        "presentationml.presentation"
    ),
    DetectedFormat.XLS_LEGACY: "application/vnd.ms-excel",
    DetectedFormat.ZIP_ARCHIVE: "application/zip",
    DetectedFormat.CSV: "text/csv",
    DetectedFormat.TSV: "text/tab-separated-values",
    DetectedFormat.XBRL_XML: "application/xml",
    DetectedFormat.GENERIC_XML: "application/xml",
    DetectedFormat.JSON: "application/json",
    DetectedFormat.MARKDOWN: "text/markdown",
    DetectedFormat.PLAIN_TEXT: "text/plain",
    DetectedFormat.PNG_IMAGE: "image/png",
    DetectedFormat.JPEG_IMAGE: "image/jpeg",
    DetectedFormat.TIFF_IMAGE: "image/tiff",
    DetectedFormat.OLE2_COMPOUND: "application/x-ole-storage",
    DetectedFormat.UNKNOWN: "application/octet-stream",
}

_EXTENSION_HINTS: dict[str, DetectedFormat] = {
    ".htm": DetectedFormat.GENERIC_HTML,
    ".html": DetectedFormat.GENERIC_HTML,
    ".xhtml": DetectedFormat.GENERIC_HTML,
    ".pdf": DetectedFormat.PDF,
    ".docx": DetectedFormat.DOCX,
    ".xlsx": DetectedFormat.XLSX,
    ".pptx": DetectedFormat.PPTX,
    ".xls": DetectedFormat.XLS_LEGACY,
    ".csv": DetectedFormat.CSV,
    ".tsv": DetectedFormat.TSV,
    ".xbrl": DetectedFormat.XBRL_XML,
    ".xml": DetectedFormat.GENERIC_XML,
    ".json": DetectedFormat.JSON,
    ".md": DetectedFormat.MARKDOWN,
    ".markdown": DetectedFormat.MARKDOWN,
    ".txt": DetectedFormat.PLAIN_TEXT,
    ".png": DetectedFormat.PNG_IMAGE,
    ".jpg": DetectedFormat.JPEG_IMAGE,
    ".jpeg": DetectedFormat.JPEG_IMAGE,
    ".tif": DetectedFormat.TIFF_IMAGE,
    ".tiff": DetectedFormat.TIFF_IMAGE,
    ".zip": DetectedFormat.ZIP_ARCHIVE,
}

#: Formats that are members of the HTML family, so a hint naming any of
#: them does not conflict with a decision naming another.
_HTML_FAMILY = frozenset(
    {
        DetectedFormat.SEC_INLINE_XBRL_HTML,
        DetectedFormat.SEC_HTML,
        DetectedFormat.NEWS_HTML,
        DetectedFormat.GENERIC_HTML,
    }
)


class ZipLimits(pydantic.BaseModel):
    """Bounds on opening an untrusted archive (03 §3.2.1).

    Opening an archive to discriminate DOCX from XLSX from an ordinary
    ZIP is itself an attack surface, so inspection runs under limits and
    exceeding any of them is a controlled failure, not a truncated
    parse.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    max_input_bytes: int = pydantic.Field(default=100 * 1024 * 1024, ge=1)
    max_expanded_bytes: int = pydantic.Field(default=500 * 1024 * 1024, ge=1)
    max_expansion_ratio: float = pydantic.Field(default=100.0, gt=0.0)
    max_entries: int = pydantic.Field(default=10_000, ge=1)
    max_depth: int = pydantic.Field(default=2, ge=1)


class DetectionResult(pydantic.BaseModel):
    """What detection concluded, and on what evidence (03 §3.2)."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    format: DetectedFormat
    media_type: str
    resolution: Resolution
    signals: list[str] = pydantic.Field(default_factory=list)
    conflicts: list[str] = pydantic.Field(default_factory=list)
    encrypted: bool = False


class DetectionError(Exception):
    """Raised when an artifact cannot be inspected safely.

    Exceeding an archive limit or failing to read the artifact is a
    controlled failure. The detector never guesses its way past one.
    """


def _read_head(path: str, count: int) -> bytes:
    """Return the first ``count`` bytes of a file."""
    try:
        with open(path, "rb") as handle:
            return handle.read(count)
    except OSError as error:
        raise DetectionError(f"cannot read artifact: {error}") from error


def _read_tail(path: str, count: int) -> bytes:
    """Return the last ``count`` bytes of a file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - count))
            return handle.read(count)
    except OSError as error:
        raise DetectionError(f"cannot read artifact: {error}") from error


def _decode(head: bytes) -> str:
    """Decode a sniff window leniently for content inspection."""
    return head.decode("utf-8", errors="replace")


def _looks_binary(head: bytes) -> bool:
    """Return whether a sniff window contains NUL bytes."""
    return b"\x00" in head


def _extension(artifact: shapes.AcquiredArtifact) -> str:
    """Return the lowercased extension implied by the artifact."""
    for candidate in (artifact.filename, artifact.original_url, artifact.path):
        if not candidate:
            continue
        name = candidate.split("?", 1)[0].split("#", 1)[0]
        _, extension = os.path.splitext(name)
        if extension:
            return extension.lower()
    return ""


def _delimiter_of(text: str) -> str | None:
    """Return the delimiter of a consistently delimited text sample.

    Args:
      text: A decoded sniff window.

    Returns:
      ``","`` or ``"\\t"`` when at least two lines agree on a positive
      field count for that delimiter, otherwise ``None``.
    """
    lines = [line for line in text.splitlines() if line.strip()][:10]
    if len(lines) < 2:
        return None
    for delimiter in (",", "\t"):
        counts = {line.count(delimiter) for line in lines}
        if len(counts) == 1 and counts.pop() >= 1:
            return delimiter
    return None


class ZipInspection(pydantic.BaseModel):
    """What archive inspection found inside a ZIP container."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    format: DetectedFormat
    encrypted: bool = False
    entry_count: int = 0


def inspect_zip(path: str, limits: ZipLimits | None = None) -> ZipInspection:
    """Discriminate an Office container from an ordinary archive.

    DOCX, XLSX, PPTX, and an ordinary ZIP share one magic signature, so
    the container must be opened; ``[Content_Types].xml`` and the part
    names inside it name the real format (03 §3.2.1).

    Args:
      path: Local path to the archive.
      limits: Expansion limits; the documented defaults when omitted.

    Returns:
      What the archive is, and whether any entry is encrypted.

    Raises:
      DetectionError: If any expansion limit is exceeded or the archive
        cannot be opened.
    """
    limits = limits or ZipLimits()
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise DetectionError(f"cannot stat artifact: {error}") from error
    if size > limits.max_input_bytes:
        raise DetectionError(
            f"archive is {size} bytes, above the "
            f"{limits.max_input_bytes} byte input limit"
        )

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_entries:
                raise DetectionError(
                    f"archive has {len(infos)} entries, above the "
                    f"{limits.max_entries} entry limit"
                )
            expanded = sum(info.file_size for info in infos)
            if expanded > limits.max_expanded_bytes:
                raise DetectionError(
                    f"archive expands to {expanded} bytes, above the "
                    f"{limits.max_expanded_bytes} byte limit"
                )
            if size > 0 and expanded / size > limits.max_expansion_ratio:
                raise DetectionError(
                    f"archive expansion ratio {expanded / size:.1f} is "
                    f"above the {limits.max_expansion_ratio} limit"
                )
            encrypted = any(info.flag_bits & 0x1 for info in infos)
            names = {info.filename for info in infos}
    except zipfile.BadZipFile as error:
        raise DetectionError(f"corrupt archive: {error}") from error
    except OSError as error:
        raise DetectionError(f"cannot read archive: {error}") from error

    detected = DetectedFormat.ZIP_ARCHIVE
    if any(name.startswith("word/") for name in names):
        detected = DetectedFormat.DOCX
    elif any(name.startswith("xl/") for name in names):
        detected = DetectedFormat.XLSX
    elif any(name.startswith("ppt/") for name in names):
        detected = DetectedFormat.PPTX
    return ZipInspection(
        format=detected, encrypted=encrypted, entry_count=len(names)
    )


class Ole2Inspection(pydantic.BaseModel):
    """What inspection found inside an OLE2 compound file."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    format: DetectedFormat
    stream_names: list[str] = pydantic.Field(default_factory=list)


def _ole2_directory_entry_names(block: bytes) -> list[str]:
    """Return the live entry names in one directory sector.

    An unallocated entry keeps its name: MS-CFB frees the slot without
    clearing the bytes. Reading names without checking the object type
    would let a deleted ``Workbook`` stream inside a Word document name
    the whole container a spreadsheet, so only allocated entries count.
    """
    names: list[str] = []
    stride = _OLE2_DIRECTORY_ENTRY_BYTES
    for offset in range(0, len(block) - stride + 1, stride):
        entry = block[offset : offset + stride]
        if entry[66] not in _OLE2_ALLOCATED_OBJECT_TYPES:
            continue
        length = int.from_bytes(entry[64:66], "little")
        if not 2 <= length <= 64:
            continue
        name = entry[: length - 2].decode("utf-16-le", errors="replace")
        if name:
            names.append(name)
    return names


def _ole2_next_sector(
    handle, header: bytes, sector_size: int, sector: int
) -> int:
    """Return the sector following ``sector`` in the FAT chain."""
    entries_per_sector = sector_size // 4
    fat_index = sector // entries_per_sector
    if fat_index >= _OLE2_HEADER_DIFAT_ENTRIES:
        return _OLE2_RESERVED_SECTOR
    start = _OLE2_HEADER_DIFAT_OFFSET + fat_index * 4
    fat_sector = int.from_bytes(header[start : start + 4], "little")
    if fat_sector >= _OLE2_RESERVED_SECTOR:
        return _OLE2_RESERVED_SECTOR
    handle.seek(
        (fat_sector + 1) * sector_size + (sector % entries_per_sector) * 4
    )
    raw = handle.read(4)
    if len(raw) < 4:
        return _OLE2_RESERVED_SECTOR
    return int.from_bytes(raw, "little")


def _ole2_directory_names(handle, header: bytes, sector_size: int) -> set[str]:
    """Return every stream name in a compound file's directory."""
    sector = int.from_bytes(header[48:52], "little")
    names: set[str] = set()
    visited: set[int] = set()
    for _ in range(_OLE2_MAX_DIRECTORY_SECTORS):
        if sector >= _OLE2_RESERVED_SECTOR or sector in visited:
            break
        visited.add(sector)
        handle.seek((sector + 1) * sector_size)
        block = handle.read(sector_size)
        if len(block) < _OLE2_DIRECTORY_ENTRY_BYTES:
            break
        names.update(_ole2_directory_entry_names(block))
        sector = _ole2_next_sector(handle, header, sector_size, sector)
    return names


def inspect_ole2(path: str) -> Ole2Inspection:
    """Discriminate a legacy Excel workbook from other OLE2 files.

    XLS, DOC, and PPT share one magic signature exactly as DOCX, XLSX,
    and PPTX share the ZIP one, so the container has to be opened before
    it can be named. The compound file's directory carries the stream
    names, and a ``Workbook`` stream is what makes one a spreadsheet
    (03 §3.2.1).

    Only Excel is discriminated: it is the sole legacy OLE2 format with
    a member in :class:`DetectedFormat` and a route in the registry.
    Anything else stays ``OLE2_COMPOUND``, and therefore ambiguous,
    which is the honest answer while no route can serve it.

    Args:
      path: Local path to the compound file.

    Returns:
      What the container is, with the directory names that were read.

    Raises:
      DetectionError: If the file cannot be read.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(_OLE2_HEADER_BYTES)
            if len(header) < _OLE2_HEADER_BYTES:
                return Ole2Inspection(format=DetectedFormat.OLE2_COMPOUND)
            sector_shift = int.from_bytes(header[30:32], "little")
            if sector_shift not in (9, 12):
                return Ole2Inspection(format=DetectedFormat.OLE2_COMPOUND)
            names = _ole2_directory_names(handle, header, 1 << sector_shift)
    except OSError as error:
        raise DetectionError(f"cannot read compound file: {error}") from error

    detected = (
        DetectedFormat.XLS_LEGACY
        if names & _XLS_STREAM_NAMES
        else DetectedFormat.OLE2_COMPOUND
    )
    return Ole2Inspection(format=detected, stream_names=sorted(names))


class FormatDetector:
    """Resolve an artifact to exactly one format (03 §3.2).

    The detector reads a bounded prefix of the artifact and never
    dereferences anything. It is a pure function of the bytes on disk
    and the acquisition metadata.
    """

    def __init__(self, zip_limits: ZipLimits | None = None) -> None:
        """Initialize the detector.

        Args:
          zip_limits: Archive expansion limits; the documented defaults
            when omitted.
        """
        self._zip_limits = zip_limits or ZipLimits()

    def detect(self, artifact: shapes.AcquiredArtifact) -> DetectionResult:
        """Detect the format of one acquired artifact.

        Args:
          artifact: The already-acquired artifact to inspect.

        Returns:
          A :class:`DetectionResult` naming the format, the signals that
          supported it, and any lower-priority signal that disagreed.

        Raises:
          DetectionError: If the artifact cannot be inspected safely.
        """
        head = _read_head(artifact.path, SNIFF_BYTES)
        signals = [f"source_class={artifact.source_class.value}"]
        conflicts: list[str] = []
        encrypted = False

        detected, resolution = self._detect_by_container(
            artifact, head, signals
        )
        if detected is DetectedFormat.UNKNOWN:
            detected, resolution = self._detect_by_content(
                artifact, head, signals
            )
        if detected is DetectedFormat.PDF:
            encrypted = _pdf_is_encrypted(artifact.path)
        elif detected in (
            DetectedFormat.DOCX,
            DetectedFormat.XLSX,
            DetectedFormat.PPTX,
            DetectedFormat.ZIP_ARCHIVE,
        ):
            encrypted = inspect_zip(artifact.path, self._zip_limits).encrypted
        if encrypted:
            signals.append("encrypted_container_detected")

        self._record_hint_conflicts(artifact, detected, signals, conflicts)
        return DetectionResult(
            format=detected,
            media_type=_MEDIA_TYPES[detected],
            resolution=resolution,
            signals=signals,
            conflicts=conflicts,
            encrypted=encrypted,
        )

    def _detect_by_container(
        self,
        artifact: shapes.AcquiredArtifact,
        head: bytes,
        signals: list[str],
    ) -> tuple[DetectedFormat, Resolution]:
        """Resolve by magic bytes and container signature."""
        if head.startswith(_PDF_MAGIC):
            signals.append("magic=pdf_header")
            return DetectedFormat.PDF, Resolution.EXACT
        if head.startswith(_PNG_MAGIC):
            signals.append("magic=png")
            return DetectedFormat.PNG_IMAGE, Resolution.EXACT
        if head.startswith(_JPEG_MAGIC):
            signals.append("magic=jpeg")
            return DetectedFormat.JPEG_IMAGE, Resolution.EXACT
        if any(head.startswith(magic) for magic in _TIFF_MAGICS):
            signals.append("magic=tiff")
            return DetectedFormat.TIFF_IMAGE, Resolution.EXACT
        if head.startswith(_OLE2_MAGIC):
            signals.append("magic=ole2_compound")
            inspection = inspect_ole2(artifact.path)
            signals.append(f"ole2_streams={inspection.format.value}")
            if inspection.format is DetectedFormat.OLE2_COMPOUND:
                return DetectedFormat.OLE2_COMPOUND, Resolution.AMBIGUOUS
            return inspection.format, Resolution.EXACT
        if head.startswith(_ZIP_MAGIC):
            signals.append("magic=zip_container")
            inspection = inspect_zip(artifact.path, self._zip_limits)
            signals.append(f"zip_parts={inspection.format.value}")
            if inspection.format is DetectedFormat.ZIP_ARCHIVE:
                return DetectedFormat.ZIP_ARCHIVE, Resolution.UNSUPPORTED
            return inspection.format, Resolution.EXACT
        return DetectedFormat.UNKNOWN, Resolution.UNSUPPORTED

    def _detect_by_content(
        self,
        artifact: shapes.AcquiredArtifact,
        head: bytes,
        signals: list[str],
    ) -> tuple[DetectedFormat, Resolution]:
        """Resolve a text-bearing artifact by inspecting its content."""
        if _looks_binary(head):
            signals.append("content=binary_with_no_known_signature")
            return DetectedFormat.UNKNOWN, Resolution.UNSUPPORTED

        text = _decode(head)
        lowered = text.lower()
        if lowered.lstrip().startswith(_SEC_SUBMISSION_MARKER):
            # Checked before the HTML markers: the wrapper embeds whole
            # HTML documents inside the sniff window, and matching one of
            # them would mistake the container for its first passenger
            # (defect D3, 2026-08-15).
            signals.append("content=sec_submission_wrapper")
            return DetectedFormat.SEC_SUBMISSION_TEXT, Resolution.UNSUPPORTED
        if any(marker in lowered for marker in _HTML_MARKERS):
            signals.append("content=html_root_detected")
            return self._resolve_html(artifact, lowered, signals)
        if lowered.lstrip().startswith("<?xml") or lowered.lstrip().startswith(
            "<"
        ):
            signals.append("content=xml_root_detected")
            root = _xml_root_name(lowered)
            if root == "xbrl":
                signals.append("content=xbrl_instance_root")
                return DetectedFormat.XBRL_XML, Resolution.EXACT
            if root in _XBRL_TAXONOMY_ROOTS:
                # A schema or linkbase declares the XBRL instance
                # namespace without being an instance; representing its
                # elements as financial facts would be wrong (03 §4.6).
                signals.append(f"content=xbrl_taxonomy_root({root})")
            return DetectedFormat.GENERIC_XML, Resolution.EXACT
        truncated = len(head) >= SNIFF_BYTES
        if _is_json(text, truncated=truncated):
            signals.append(
                "content=json_prefix_syntax"
                if truncated
                else "content=json_syntax"
            )
            return DetectedFormat.JSON, Resolution.EXACT

        extension = _extension(artifact)
        delimiter = _delimiter_of(text)
        if delimiter is not None:
            if delimiter == "\t":
                signals.append("content=delimited_rows(tab)")
                return DetectedFormat.TSV, Resolution.EXACT
            signals.append("content=delimited_rows(comma)")
            return DetectedFormat.CSV, Resolution.EXACT
        if extension in (".md", ".markdown") and _looks_markdown(text):
            # The extension corroborates; the structure decides. A
            # ``.md`` file with no markdown structure stays plain text,
            # and the hint disagreement is recorded as a conflict —
            # the extension is never the only signal (03 §3.2,
            # defect D5, 2026-08-15).
            signals.append("content=markdown_structure")
            return DetectedFormat.MARKDOWN, Resolution.EXACT
        signals.append("content=plain_text")
        return DetectedFormat.PLAIN_TEXT, Resolution.EXACT

    def _resolve_html(
        self,
        artifact: shapes.AcquiredArtifact,
        lowered: str,
        signals: list[str],
    ) -> tuple[DetectedFormat, Resolution]:
        """Split the HTML family by caller context and DOM markers."""
        if any(marker in lowered for marker in _INLINE_XBRL_MARKERS):
            signals.append("content=inline_xbrl_namespace_detected")
            return DetectedFormat.SEC_INLINE_XBRL_HTML, Resolution.EXACT
        if artifact.source_class is document.SourceClass.SEC_FILING:
            return DetectedFormat.SEC_HTML, Resolution.EXACT
        if artifact.source_class is document.SourceClass.NEWS_ARTICLE:
            return DetectedFormat.NEWS_HTML, Resolution.EXACT
        return DetectedFormat.GENERIC_HTML, Resolution.EXACT

    def _record_hint_conflicts(
        self,
        artifact: shapes.AcquiredArtifact,
        detected: DetectedFormat,
        signals: list[str],
        conflicts: list[str],
    ) -> None:
        """Record media-type and extension signals, and disagreements.

        A lower-priority hint that disagrees with the resolved format is
        a conflict worth reporting, but it never changes the decision:
        that is exactly what stops a misleading extension from causing
        incorrect dispatch.
        """
        media_type = artifact.declared_media_type
        if media_type:
            signals.append(f"declared_media_type={media_type}")
            base = media_type.split(";", 1)[0].strip().lower()
            if base and base != _MEDIA_TYPES[detected]:
                conflicts.append(
                    f"declared media type {base} disagrees with detected "
                    f"format {detected.value}"
                )
        extension = _extension(artifact)
        if extension:
            signals.append(f"extension={extension}")
            hint = _EXTENSION_HINTS.get(extension)
            if hint is None:
                return
            if hint is detected:
                return
            if hint in _HTML_FAMILY and detected in _HTML_FAMILY:
                return
            if (
                hint is DetectedFormat.PLAIN_TEXT
                and detected is DetectedFormat.SEC_SUBMISSION_TEXT
            ):
                # EDGAR serves the submission wrapper as ``.txt``; the
                # extension is right about the encoding, not wrong about
                # the format.
                return
            conflicts.append(
                f"extension {extension} suggests {hint.value}, detected "
                f"{detected.value}"
            )


def _xml_root_name(lowered: str) -> str | None:
    """Return the local name of an XML document's first real element.

    Walks past the prolog, comments, processing instructions, and any
    DOCTYPE to the first element tag, and strips its namespace prefix.
    A namespace *declaration* can appear on any file that references a
    vocabulary — only the root element says what the document is.

    Args:
      lowered: The lowercased, decoded sniff window.

    Returns:
      The root element's local name, or None when no element was found
      inside the window.
    """
    index = 0
    length = len(lowered)
    while index < length:
        start = lowered.find("<", index)
        if start < 0:
            return None
        if lowered.startswith("<?", start):
            end = lowered.find("?>", start)
            index = end + 2 if end >= 0 else length
            continue
        if lowered.startswith("<!--", start):
            end = lowered.find("-->", start)
            index = end + 3 if end >= 0 else length
            continue
        if lowered.startswith("<!", start):
            end = lowered.find(">", start)
            index = end + 1 if end >= 0 else length
            continue
        name = []
        for char in lowered[start + 1 :]:
            if char.isspace() or char in "/>":
                break
            name.append(char)
        if not name:
            return None
        return "".join(name).rsplit(":", 1)[-1]
    return None


def _looks_markdown(text: str) -> bool:
    """Return whether a text window shows any markdown structure.

    A single structural marker at a line start is enough, because the
    caller only asks when the extension already says markdown — the
    probe exists so the extension is never the *only* signal (03 §3.2).
    """
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith(_MARKDOWN_LINE_MARKERS):
            return True
        if "](" in stripped:
            return True
    return False


def _is_json(text: str, truncated: bool = False) -> bool:
    """Return whether a sniff window is JSON, or the start of JSON.

    A large artifact is only ever seen through ``SNIFF_BYTES``, so
    requiring the window to parse whole means no JSON document above the
    window size is ever detected — and every SEC ``companyfacts``
    response is far above it. Such a file would fall through to plain
    text, which is the silent text fallback the design forbids, one
    stage earlier than route dispatch can guard against it.

    Widening ``SNIFF_BYTES`` would not fix that; it would only move the
    threshold, while reading more of an untrusted file. Instead, a window
    known to be truncated is judged as a *prefix*.

    Args:
      text: The decoded sniff window.
      truncated: Whether the window stopped short of the whole artifact.

    Returns:
      Whether the artifact is a JSON document.
    """
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return _is_json_prefix(stripped) if truncated else False
    return True


def _is_json_prefix(text: str) -> bool:
    """Return whether a truncated window is a valid start of JSON.

    Walks the window tracking string state and open containers, cuts it
    back to the last point at which an element was complete, closes
    whatever was still open there, and lets :mod:`json` judge the
    result. Deciding the grammar stays with the real parser; this only
    finds a defensible place to cut.

    A window whose containers all closed is *not* a truncated prefix —
    it is a complete value with trailing content, which the caller has
    already found unparseable — so it is rejected here.
    """
    stack: list[str] = []
    cut: int | None = None
    cut_stack: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
            cut, cut_stack = index + 1, list(stack)
        elif char in "}]":
            if not stack or stack[-1] != char:
                return False
            stack.pop()
            cut, cut_stack = index + 1, list(stack)
        elif char == ",":
            cut, cut_stack = index, list(stack)
    if cut is None or not cut_stack:
        return False
    try:
        json.loads(text[:cut] + "".join(reversed(cut_stack)))
    except ValueError:
        return False
    return True


def _pdf_is_encrypted(path: str) -> bool:
    """Return whether a PDF declares an encryption dictionary.

    Encrypted and password-protected files are detected **before**
    dispatch so they fail with their own error and do not consume the
    one permitted fallback (03 §8.1).
    """
    return b"/Encrypt" in _read_tail(path, _PDF_TRAILER_BYTES)
