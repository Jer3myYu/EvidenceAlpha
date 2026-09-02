"""Small shared data structures for the RAG pipeline."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class RetrievedChunk:
    """One chunk returned by a similarity search.

    Attributes:
      text: The chunk's text, exactly as it was stored.
      source: Where the chunk came from: the file path, plus the page
        number for PDFs.
      score: Cosine distance between the query and the chunk. Lower is
        closer; 0.0 is identical. ``None`` if the store gave no score.
    """

    text: str
    source: str
    score: float | None
