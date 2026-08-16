"""The query-embedding protocol (04 §4.2).

``retrieval/`` must embed queries with the exact model, role prefix,
and normalization that embedded the corpus, but it may not import
``ingestion/`` (01 §8). This module is the neutral seam: it defines the
protocol only, imports nothing from the project, and the application
layer injects the one concrete embedder into both sides.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class QueryEmbedder(Protocol):
    """Embeds a query into the corpus's vector space (04 §4.2)."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one query string.

        Args:
          text: The raw query text, without any role prefix — the
            implementation owns prefixing so no caller can forget it.

        Returns:
          The L2-normalized query vector.
        """
        raise NotImplementedError

    @property
    def signature(self) -> str:
        """The embedding signature this embedder produces (04 §4.3).

        Vectors from different signatures never share a collection;
        retrieval uses this to address the right one.
        """
        raise NotImplementedError
