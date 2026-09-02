"""Search the vector index and print the closest chunks.

Usage::

    .venv/bin/python scripts/query.py "What risks does this company disclose?"
"""

import sys

from rag import retrieve


def main() -> None:
    """Print the top chunks for the query given on the command line."""
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/query.py "<question>"')
    results = retrieve.search_documents(sys.argv[1], k=3)
    print(f"Retrieved {len(results)} chunks\n")
    for number, chunk in enumerate(results, start=1):
        print(f"{number}. source: {chunk.source}")
        print(f"   distance: {chunk.score:.4f}")
        print(f"   text: {chunk.text}\n")


if __name__ == "__main__":
    main()
