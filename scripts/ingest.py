"""Ingest a folder of documents into a vector index.

Usage::

    .venv/bin/python scripts/ingest.py ./data/documents              # v2
    .venv/bin/python scripts/ingest.py ./data/documents --collection v1

``v2`` (the default since Phase 10) snapshots each file under
``data/sources/`` and indexes it in the ``documents_v2`` collection
with the multilingual embedding the industry workflow searches. ``v1``
is the Phase 1 pipeline into the ``documents`` collection, unchanged.
"""

import argparse
import pathlib

from industry import snapshots
from rag import ingest


def main() -> None:
    """Load, split, and index the documents at the given path."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", maxsplit=1)[0]
    )
    parser.add_argument("path", help="a file or a directory")
    parser.add_argument("--collection", choices=["v1", "v2"], default="v2")
    args = parser.parse_args()
    if args.collection == "v1":
        documents = ingest.load_documents(args.path)
        print(f"Loaded {len(documents)} documents")
        chunks = ingest.split_documents(documents)
        print(f"Created {len(chunks)} chunks")
        ingest.build_index(chunks)
        print(f"Index built successfully at {ingest.CHROMA_DIR}/")
        return
    root = pathlib.Path(args.path)
    files = (
        [root]
        if root.is_file()
        else sorted(f for f in root.rglob("*") if f.is_file())
    )
    store = snapshots.vector_store()
    total = 0
    for file in files:
        version, count = snapshots.ingest_local(str(file), store)
        total += count
        print(f"{file}: version {version.id}, {count} chunks")
    print(f"Indexed {total} chunks into {snapshots.COLLECTION_NAME}")


if __name__ == "__main__":
    main()
