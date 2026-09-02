"""Acquire one web source by URL and add it to the local collection.

This is the step between web discovery and document retrieval::

    search_web()   finds a source              (discovery evidence, [W#])
    ingest_url()   downloads and indexes it    (this module)
    search_documents() retrieves from it        (document evidence, [D#])

Supported: HTML pages via ``WebBaseLoader`` and digital PDFs via
``PyMuPDFLoader``. No local copy is kept; the URL is the source. Scanned
PDFs, crawling, and JavaScript rendering are out of scope.
"""

import logging
import os
import tempfile
import urllib.parse

import requests
from langchain_community import document_loaders
from langchain_core import documents as lc_documents

from rag import ingest

USER_AGENT = "EvidenceAlpha/0.2 (research agent)"
TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)


def is_pdf(url: str, content_type: str) -> bool:
    """Decide PDF or HTML from the response type or the URL path."""
    path = urllib.parse.urlparse(url).path.lower()
    return "application/pdf" in content_type.lower() or path.endswith(".pdf")


def load_url(url: str) -> list[lc_documents.Document]:
    """Download one HTML page or digital PDF as LangChain documents.

    Args:
      url: An ``http://`` or ``https://`` address.

    Returns:
      One document for an HTML page, or one per page for a PDF. Every
      document carries ``metadata["source"] == url``.

    Raises:
      ValueError: If the URL scheme is not http or https.
      requests.RequestException: If the download fails.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"Only http and https URLs are supported: {url}")

    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()

    if not is_pdf(url, response.headers.get("content-type", "")):
        loader = document_loaders.WebBaseLoader(
            url, header_template={"User-Agent": USER_AGENT}
        )
        return loader.load()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(response.content)
        path = handle.name
    try:
        pages = document_loaders.PyMuPDFLoader(path).load()
    finally:
        os.remove(path)
    for page in pages:
        page.metadata["source"] = url
    return pages


def ingest_url(url: str) -> int:
    """Download a source and index it with the Phase 1 pipeline.

    Args:
      url: The source address; it becomes the chunks' ``source``.

    Returns:
      The number of chunks indexed.
    """
    chunks = ingest.split_documents(load_url(url))
    count = ingest.build_index(chunks)
    logger.info("ingested_url=%s chunks=%d", url, count)
    return count
