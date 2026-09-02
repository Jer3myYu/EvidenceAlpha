"""Ingest a folder of documents into the vector index.

Usage::

    .venv/bin/python scripts/ingest.py ./data/documents
"""

import sys

from rag import ingest


def main() -> None:
    """Load, split, and index the documents at the given path."""
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/ingest.py <file-or-directory>")
    documents = ingest.load_documents(sys.argv[1])
    print(f"Loaded {len(documents)} documents")
    chunks = ingest.split_documents(documents)
    print(f"Created {len(chunks)} chunks")
    ingest.build_index(chunks)
    print(f"Index built successfully at {ingest.CHROMA_DIR}/")


if __name__ == "__main__":
    main()
