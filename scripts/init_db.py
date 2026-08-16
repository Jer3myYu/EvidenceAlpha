"""One-time local setup for the ingestion pipeline (04 §4.1, §5).

Run from the repo root::

    .venv/bin/python scripts/init_db.py

This is the only step that touches the network: it fetches the pinned
embedding model (~1.1 GB, cached by HuggingFace under ``~/.cache``)
and creates the Chroma collection for the current embedding signature
under ``storage/chroma/``. Everything after this — chunking,
embedding, indexing, retrieval — runs offline.

Re-running is safe and cheap: the model loads from cache and the
collection is get-or-create. The SQLite evidence schema (02 §12) is a
later milestone and is not created here yet.
"""

import pathlib

from ingestion import embedder as embedder_module
from ingestion import indexer as indexer_module


def main() -> None:
    """Fetch the pinned model and create the vector collection."""
    root = pathlib.Path(__file__).resolve().parent.parent
    storage = root / "storage"
    for subdirectory in ("chroma", "documents"):
        (storage / subdirectory).mkdir(parents=True, exist_ok=True)

    print(
        f"Loading {embedder_module.MODEL_NAME}"
        f"@{embedder_module.MODEL_REVISION[:12]} (downloads on first run)"
    )
    embedder = embedder_module.SentenceTransformerEmbedder()
    probe = embedder.embed_query("setup probe")
    print(f"Model ready: {len(probe)}-d, L2-normalized")

    indexer = indexer_module.ChromaIndexer(
        embedding_signature=embedder.signature,
        path=str(storage / "chroma"),
    )
    print(f"Embedding signature: {embedder.signature}")
    print(
        f"Collection ready: {indexer.collection.name} "
        f"({indexer.collection.count()} records)"
    )


if __name__ == "__main__":
    main()
