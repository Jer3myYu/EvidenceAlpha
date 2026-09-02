"""Similarity search over the vector index built by ``rag.ingest``."""

import logging

from rag import ingest
from rag import models

logger = logging.getLogger(__name__)


def search_documents(
    query: str,
    k: int = 5,
    persist_directory: str = ingest.CHROMA_DIR,
) -> list[models.RetrievedChunk]:
    """Return the ``k`` chunks whose embeddings are closest to the query.

    Args:
      query: The question or phrase to search for.
      k: How many chunks to return.
      persist_directory: Directory holding the Chroma data.

    Returns:
      Chunks ordered from closest to farthest.
    """
    store = ingest.vector_store(persist_directory)
    hits = store.similarity_search_with_score(query, k=k)
    logger.info("query=%r results=%d", query, len(hits))
    results = []
    for document, score in hits:
        source = document.metadata["source"]
        page = document.metadata.get("page")
        if page is not None:
            source = f"{source} (page {page + 1})"
        results.append(
            models.RetrievedChunk(
                text=document.page_content, source=source, score=score
            )
        )
    return results
