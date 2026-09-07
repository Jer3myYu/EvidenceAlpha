"""Source acquisition with provenance: safe fetch, immutable snapshots,
extraction that keeps headings and table rows, and a versioned index.

A fetch is checked before every network hop (no loopback, private,
link-local, or reserved addresses; http(s) only; at most three manual
redirects; a size cap while streaming; a timeout), its bytes are stored
once under their content hash, and each fetch gets its own immutable
metadata file keyed by URL and hash. Chunks are indexed under
``<version_id>:<index>`` with upsert semantics, so repeating a fetch of
the same bytes changes nothing, and a later fetch of the same URL with
different bytes adds a new version beside the old one.

The index is the ``documents_v2`` collection with a multilingual
embedding model (the measured reason is in the Phase 10 log: the
Phase 1 model cannot discriminate Chinese text). The Phase 1
``documents`` collection is not touched.
"""

import dataclasses
import hashlib
import ipaddress
import json
import os
import pathlib
import socket
import tempfile
import urllib.parse
from collections.abc import Callable
from typing import Any

import bs4
import pymupdf
import requests
from langchain_chroma import Chroma
from langchain_core import documents as lc_documents
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from industry import records
from research import sources as sources_module

EXTRACTION_VERSION = "v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "documents_v2"
CHROMA_DIR = "data/chroma"
SOURCES_DIR = "data/sources"
USER_AGENT = "EvidenceAlpha/0.3 (industry research agent)"
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 3

Resolver = Callable[[str], list[str]]


class FetchError(RuntimeError):
    """A fetch was refused or failed; the message says why."""


class UnsafeTarget(FetchError):
    """The URL points at an address the system must not contact."""


@dataclasses.dataclass(frozen=True)
class Fetched:
    """One downloaded document.

    Attributes:
      url: The URL as requested.
      final_url: The URL after redirects.
      content_type: The response content type, lowercased.
      content: The bytes.
      retrieved_at: ISO time of the fetch.
    """

    url: str
    final_url: str
    content_type: str
    content: bytes
    retrieved_at: str


def resolve(hostname: str) -> list[str]:
    """Every address a hostname resolves to (the default resolver)."""
    infos = socket.getaddrinfo(hostname, None)
    return sorted({info[4][0] for info in infos})


def check_url(url: str, resolver: Resolver = resolve) -> None:
    """Refuse anything but a public http(s) host.

    Raises:
      UnsafeTarget: For a non-http(s) scheme, a missing host, an IP
        literal or resolved address that is loopback, private,
        link-local, reserved, multicast, or unspecified.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeTarget(f"only http(s) URLs are fetched: {url}")
    host = parts.hostname
    if not host:
        raise UnsafeTarget(f"URL has no host: {url}")
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = resolver(host)
        except OSError as error:
            raise FetchError(f"cannot resolve {host}: {error}") from error
    if not addresses:
        raise FetchError(f"{host} resolves to nothing")
    for text in addresses:
        address = ipaddress.ip_address(text)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeTarget(
                f"{host} resolves to {text}, which is not public"
            )


def fetch(
    url: str,
    session: Any = None,
    resolver: Resolver = resolve,
    max_bytes: int = MAX_BYTES,
    timeout: float = TIMEOUT_SECONDS,
) -> Fetched:
    """Download one document with every hop checked and the size capped.

    Args:
      url: The address to fetch.
      session: A ``requests.Session``-like object (tests inject one).
      resolver: Hostname resolver (tests inject one).
      max_bytes: Refuse bodies larger than this while streaming.
      timeout: Seconds per request.

    Returns:
      The bytes with the final URL and content type.

    Raises:
      UnsafeTarget: If any hop targets a non-public address.
      FetchError: On too many redirects, an HTTP error, a body over the
        cap, or a transport failure.
    """
    session = session or requests.Session()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        check_url(current, resolver)
        try:
            response = session.get(
                current,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            raise FetchError(f"fetch failed for {current}: {error}") from error
        if 300 <= response.status_code < 400 and response.headers.get(
            "location"
        ):
            current = urllib.parse.urljoin(
                current, response.headers["location"]
            )
            response.close()
            continue
        if response.status_code >= 400:
            response.close()
            raise FetchError(f"HTTP {response.status_code} for {current}")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > max_bytes:
                response.close()
                raise FetchError(f"{current} exceeds the {max_bytes} byte cap")
            chunks.append(chunk)
        response.close()
        return Fetched(
            url=url,
            final_url=current,
            content_type=response.headers.get("content-type", "").lower(),
            content=b"".join(chunks),
            retrieved_at=records.now_iso(),
        )
    raise FetchError(f"too many redirects from {url}")


def content_hash(content: bytes) -> str:
    """The sha256 hex digest of the bytes."""
    return hashlib.sha256(content).hexdigest()


def version_id(canonical_url: str, digest: str) -> str:
    """The identity of one fetch: the URL and the bytes it returned."""
    return hashlib.sha256(f"{canonical_url}\n{digest}".encode()).hexdigest()[
        :16
    ]


def is_pdf(content_type: str, url: str, content: bytes) -> bool:
    """Decide PDF from the type, the path, or the magic bytes."""
    path = urllib.parse.urlsplit(url).path.lower()
    return (
        "application/pdf" in content_type
        or path.endswith(".pdf")
        or content[:5] == b"%PDF-"
    )


def _atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".tmp-", delete=False
    )
    try:
        handle.write(data)
        handle.close()
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)


# What the metadata file records beside the version's own fields; the
# registry id of the source is attempt-local and is never written.
_METADATA_ONLY = ("url", "canonical_url", "publisher", "published")


def store_snapshot(
    fetched: Fetched,
    source_id: str,
    root: str = SOURCES_DIR,
    chunk_count: int = 0,
    publisher: str | None = None,
    published: str | None = None,
) -> records.SourceVersion:
    """Save the bytes once and the fetch metadata once; return the version.

    The blob is content-addressed (identical bytes from two URLs share
    it); the metadata is keyed by URL and hash, never rewritten, and is
    what the returned version reports once it exists, so a second fetch
    of the same bytes cannot re-date or re-interpret it. The
    metadata holds only content facts (URL, hash, type, size, time,
    extraction version, chunk count, publisher, published date); the
    registry id of the source is attempt-local and stays out of it.
    """
    canonical = sources_module.canonical_url(fetched.url)
    digest = content_hash(fetched.content)
    vid = version_id(canonical, digest)
    extension = (
        ".pdf"
        if is_pdf(fetched.content_type, fetched.final_url, fetched.content)
        else ".html"
    )
    blob = pathlib.Path(root) / "blobs" / f"{digest}{extension}"
    meta = pathlib.Path(root) / "versions" / f"{vid}.json"
    if not blob.exists():
        _atomic_write(blob, fetched.content)
    version = records.SourceVersion(
        id=vid,
        source_id=source_id,
        content_hash=digest,
        blob_path=str(blob),
        meta_path=str(meta),
        final_url=fetched.final_url,
        content_type=fetched.content_type,
        size=len(fetched.content),
        retrieved_at=fetched.retrieved_at,
        extraction_version=EXTRACTION_VERSION,
        chunk_count=chunk_count,
    )
    if meta.exists():
        # The version is immutable: a later fetch of the same bytes
        # keeps the recorded retrieval time, content type, extraction
        # version and chunk count, so every chunk indexed under this
        # version id keeps one consistent interpretation.
        recorded = json.loads(meta.read_text(encoding="utf-8"))
        fields = {
            name: value
            for name, value in recorded.items()
            if name not in _METADATA_ONLY
        }
        return records.SourceVersion.model_validate(
            {**fields, "source_id": source_id}
        )
    payload = version.model_dump(exclude={"source_id"})
    payload["url"] = fetched.url
    payload["canonical_url"] = canonical
    payload["publisher"] = publisher
    payload["published"] = published
    _atomic_write(
        meta, json.dumps(payload, ensure_ascii=False, indent=1).encode()
    )
    return version


def read_metadata(
    version: records.SourceVersion,
) -> tuple[str | None, str | None]:
    """The publisher and published date recorded with a version, if any."""
    path = pathlib.Path(version.meta_path)
    if not path.exists():
        return None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("publisher"), payload.get("published")


def html_metadata(content: bytes) -> tuple[str | None, str | None]:
    """Publisher and published date from common HTML meta tags."""
    soup = bs4.BeautifulSoup(content, "html.parser")

    def meta(*names: str) -> str | None:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find(
                "meta", attrs={"name": name}
            )
            if tag and tag.get("content"):
                return " ".join(str(tag["content"]).split())
        return None

    publisher = meta("og:site_name", "publisher", "author", "og:article:author")
    published = meta(
        "article:published_time",
        "og:article:published_time",
        "publishdate",
        "pubdate",
        "date",
        "publication_date",
    )
    if published is None:
        time_tag = soup.find("time")
        if time_tag and (time_tag.get("datetime") or time_tag.get_text()):
            published = str(
                time_tag.get("datetime") or time_tag.get_text()
            ).strip()
    return publisher, published


@dataclasses.dataclass(frozen=True)
class Block:
    """One extracted unit of text with its location.

    Attributes:
      text: The text, or table rows joined by newlines.
      section: The nearest heading above the block, or ``""``.
      page: 1-based page for PDFs, else ``None``.
      kind: ``text`` or ``table``.
      limitations: Extraction caveats, for example a merged cell.
    """

    text: str
    section: str
    page: int | None
    kind: str
    limitations: tuple[str, ...] = ()


_SKIP_TAGS = ("script", "style", "noscript", "nav", "footer", "header")


def _table_block(table: bs4.Tag, section: str) -> Block | None:
    rows: list[str] = []
    limitations: set[str] = set()
    widths: set[int] = set()
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        for cell in cells:
            if cell.get("colspan") or cell.get("rowspan"):
                limitations.add("table_merged_cells")
        texts = [
            " ".join(cell.get_text(" ", strip=True).split()) for cell in cells
        ]
        widths.add(len(texts))
        rows.append(" | ".join(texts))
    if not rows:
        return None
    if len(widths) > 1:
        limitations.add("table_unequal_rows")
    return Block(
        text="[table]\n" + "\n".join(rows),
        section=section,
        page=None,
        kind="table",
        limitations=tuple(sorted(limitations)),
    )


def extract_html(content: bytes) -> list[Block]:
    """Headings, paragraphs, list items, and tables in document order."""
    soup = bs4.BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(_SKIP_TAGS):
        tag.decompose()
    body = soup.body or soup
    blocks: list[Block] = []
    section = ""
    for element in body.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "pre"]
    ):
        if element.find_parent("table") is not None and element.name != "table":
            continue
        if element.name.startswith("h"):
            section = " ".join(element.get_text(" ", strip=True).split())
            continue
        if element.name == "table":
            block = _table_block(element, section)
            if block:
                blocks.append(block)
            continue
        if element.find("p") is not None or element.find("li") is not None:
            continue  # its children will be visited
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) >= 20:
            blocks.append(
                Block(text=text, section=section, page=None, kind="text")
            )
    if not blocks:
        text = " ".join(body.get_text(" ", strip=True).split())
        if text:
            blocks.append(
                Block(
                    text=text,
                    section="",
                    page=None,
                    kind="text",
                    limitations=("html_no_structure",),
                )
            )
    return blocks


def extract_pdf(content: bytes) -> list[Block]:
    """Page text with page locators; tables are not reconstructed."""
    blocks: list[Block] = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        for number, page in enumerate(document, start=1):
            text = " ".join(page.get_text().split())
            if text:
                blocks.append(
                    Block(
                        text=text,
                        section="",
                        page=number,
                        kind="text",
                        limitations=("pdf_text_no_table_structure",),
                    )
                )
    return blocks


def extract_text(content: bytes) -> list[Block]:
    """Plain text or Markdown: paragraphs, ``#`` headings as sections."""
    blocks: list[Block] = []
    section = ""
    for paragraph in content.decode("utf-8", errors="replace").split("\n\n"):
        stripped = paragraph.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            continue
        blocks.append(
            Block(
                text=" ".join(stripped.split()),
                section=section,
                page=None,
                kind="text",
            )
        )
    return blocks


def extract(fetched: Fetched) -> list[Block]:
    """Dispatch on PDF, HTML, or text."""
    if is_pdf(fetched.content_type, fetched.final_url, fetched.content):
        return extract_pdf(fetched.content)
    if "html" in fetched.content_type or fetched.content[
        :200
    ].lstrip().lower().startswith((b"<!doctype", b"<html")):
        return extract_html(fetched.content)
    return extract_text(fetched.content)


@dataclasses.dataclass(frozen=True)
class Chunk:
    """One indexable piece of a version."""

    index: int
    text: str
    section: str
    page: int | None
    kind: str
    limitations: tuple[str, ...]


def chunk_blocks(
    blocks: list[Block],
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split within blocks so a chunk never crosses a heading or table."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap
    )
    chunks: list[Chunk] = []
    for block in blocks:
        pieces = (
            [block.text]
            if len(block.text) <= size
            else splitter.split_text(block.text)
        )
        for piece in pieces:
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    section=block.section,
                    page=block.page,
                    kind=block.kind,
                    limitations=block.limitations,
                )
            )
    return chunks


def language_of(text: str) -> str:
    """``zh`` when the text holds CJK characters, else ``en``."""
    return "zh" if any("一" <= ch <= "鿿" for ch in text) else "en"


_EMBEDDINGS: dict[str, HuggingFaceEmbeddings] = {}


def embeddings() -> HuggingFaceEmbeddings:
    """The multilingual embedding model, loaded once per process."""
    if EMBEDDING_MODEL not in _EMBEDDINGS:
        _EMBEDDINGS[EMBEDDING_MODEL] = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL
        )
    return _EMBEDDINGS[EMBEDDING_MODEL]


def vector_store(persist_directory: str = CHROMA_DIR) -> Chroma:
    """Open (or create) the ``documents_v2`` collection."""
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings(),
        persist_directory=persist_directory,
        collection_metadata={"hnsw:space": "cosine"},
    )


def index_version(
    store: Chroma,
    version: records.SourceVersion,
    canonical_url: str,
    chunks: list[Chunk],
) -> int:
    """Upsert the chunks under ``<version_id>:<index>``; return the count."""
    if not chunks:
        return 0
    documents = [
        lc_documents.Document(
            page_content=chunk.text,
            metadata={
                "source": canonical_url,
                "source_version_id": version.id,
                "section": chunk.section,
                "chunk_index": chunk.index,
                "page": chunk.page if chunk.page is not None else -1,
                "kind": chunk.kind,
                "extraction_version": version.extraction_version,
                "retrieved_at": version.retrieved_at,
                "language": language_of(chunk.text),
                "limitations": ",".join(chunk.limitations),
            },
        )
        for chunk in chunks
    ]
    store.add_documents(
        documents, ids=[f"{version.id}:{chunk.index}" for chunk in chunks]
    )
    return len(chunks)


@dataclasses.dataclass(frozen=True)
class Hit:
    """One retrieved chunk with its distance."""

    text: str
    metadata: dict[str, Any]
    distance: float


def search(
    store: Chroma,
    query: str,
    k: int = 5,
    source_url: str | None = None,
) -> list[Hit]:
    """Similarity search, optionally restricted to one canonical URL."""
    where = {"source": source_url} if source_url else None
    results = store.similarity_search_with_score(query, k=k, filter=where)
    return [
        Hit(
            text=doc.page_content,
            metadata=dict(doc.metadata),
            distance=float(score),
        )
        for doc, score in results
    ]


def acquire_bytes(
    url: str,
    source_id: str,
    root: str = SOURCES_DIR,
    session: Any = None,
    resolver: Resolver = resolve,
) -> tuple[records.SourceVersion, list[Chunk]]:
    """Fetch, extract, chunk, then snapshot with the accurate chunk count.

    Indexing is the caller's step (it needs the index lock).
    """
    fetched = fetch(url, session=session, resolver=resolver)
    chunks = chunk_blocks(extract(fetched))
    publisher = published = None
    if not is_pdf(fetched.content_type, fetched.final_url, fetched.content):
        publisher, published = html_metadata(fetched.content)
    version = store_snapshot(
        fetched,
        source_id,
        root,
        chunk_count=len(chunks),
        publisher=publisher,
        published=published,
    )
    return version, chunks


def acquire(
    url: str,
    source_id: str,
    store: Chroma,
    root: str = SOURCES_DIR,
    session: Any = None,
    resolver: Resolver = resolve,
) -> tuple[records.SourceVersion, list[Chunk]]:
    """Fetch, snapshot, extract, chunk, and index one URL.

    Returns:
      The version (with ``chunk_count``) and the chunks it indexed.
    """
    version, chunks = acquire_bytes(url, source_id, root, session, resolver)
    canonical = sources_module.canonical_url(url)
    index_version(store, version, canonical, chunks)
    return version, chunks


LOCAL_SCHEME = "file://"


def ingest_local(
    path: str, store: Chroma, root: str = SOURCES_DIR
) -> tuple[records.SourceVersion, int]:
    """Snapshot and index one local file (``.txt``, ``.md``, ``.pdf``).

    The file's absolute path under ``file://`` is its identity, so a
    changed file becomes a new version beside the old one, exactly as a
    re-fetched page does.
    """
    file = pathlib.Path(path).resolve()
    suffix = file.suffix.lower()
    if suffix not in (".pdf", ".md", ".txt"):
        raise ValueError(f"Unsupported file type {suffix!r}: {file}")
    content = file.read_bytes()
    content_type = {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
    }.get(suffix, "text/plain")
    url = f"{LOCAL_SCHEME}{file}"
    fetched = Fetched(
        url=url,
        final_url=url,
        content_type=content_type,
        content=content,
        retrieved_at=records.now_iso(),
    )
    chunks = chunk_blocks(extract(fetched))
    version = store_snapshot(fetched, "local", root, chunk_count=len(chunks))
    count = index_version(store, version, url, chunks)
    return version, count
