"""Load documents, split them into chunks, and build the vector index.

The three public functions are the three ingestion steps, in order::

    documents = load_documents("data/documents")
    chunks = split_documents(documents)
    build_index(chunks)

Phase 1 limitation: PDFs must carry a text layer. Scanned or
image-only PDFs yield no text and are not supported; there is no OCR
and no fallback.
"""

import logging
import pathlib

from langchain_chroma import Chroma
from langchain_community import document_loaders
from langchain_core import documents as lc_documents
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Learning-stage defaults, in characters. Change them here to experiment.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# A small, fast, local sentence-embedding model (384 dimensions).
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Where the persistent Chroma store lives, relative to the repo root.
CHROMA_DIR = "data/chroma"
COLLECTION_NAME = "documents"

SUPPORTED_SUFFIXES = (".txt", ".md", ".pdf")

logger = logging.getLogger(__name__)


def load_documents(path: str) -> list[lc_documents.Document]:
    """Read every supported file under ``path`` into LangChain documents.

    ``.txt`` and ``.md`` files load as one document each. A ``.pdf``
    loads as one document per page, each tagged with its page number.

    Args:
      path: A file, or a directory searched recursively.

    Returns:
      The loaded documents, in sorted path order.

    Raises:
      FileNotFoundError: If ``path`` does not exist or holds no files.
      ValueError: If any file has an unsupported extension. Nothing is
        skipped silently.
    """
    root = pathlib.Path(path)
    if not root.exists():
        raise FileNotFoundError(f"No such file or directory: {path}")
    files = (
        [root]
        if root.is_file()
        else sorted(file for file in root.rglob("*") if file.is_file())
    )
    if not files:
        raise FileNotFoundError(f"No documents found under {path}")

    supported = ", ".join(SUPPORTED_SUFFIXES)
    documents: list[lc_documents.Document] = []
    for file in files:
        suffix = file.suffix.lower()
        if suffix in (".txt", ".md"):
            loader = document_loaders.TextLoader(str(file), encoding="utf-8")
        elif suffix == ".pdf":
            loader = document_loaders.PyMuPDFLoader(str(file))
        else:
            raise ValueError(
                f"Unsupported file type {file.suffix!r}: {file}. "
                f"Supported: {supported}"
            )
        documents.extend(loader.load())
    logger.info("loaded_documents=%d", len(documents))
    return documents


def split_documents(
    documents: list[lc_documents.Document],
) -> list[lc_documents.Document]:
    """Split documents into overlapping chunks of about CHUNK_SIZE chars.

    Each chunk keeps its parent document's metadata (``source`` and,
    for PDFs, ``page``).

    Args:
      documents: The loaded documents.

    Returns:
      The chunks, in document order.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(documents)
    logger.info("created_chunks=%d", len(chunks))
    return chunks


def vector_store(persist_directory: str = CHROMA_DIR) -> Chroma:
    """Open (or create) the persistent Chroma store with its embeddings.

    Ingestion writes to this store and retrieval reads from it, so both
    sides share this one function and therefore the same embedding
    model, collection, and distance metric.

    Args:
      persist_directory: Directory holding the Chroma data.

    Returns:
      The LangChain ``Chroma`` vector store.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL),
        persist_directory=persist_directory,
        collection_metadata={"hnsw:space": "cosine"},
    )


def build_index(
    chunks: list[lc_documents.Document],
    persist_directory: str = CHROMA_DIR,
) -> int:
    """Embed the chunks and store them in Chroma, replacing per source.

    Chunk IDs are ``<source>:<index>`` with the index counting from 0
    within each source. Before adding, every chunk previously stored for
    those sources is deleted, so re-ingesting a changed file leaves only
    its current chunks.

    Args:
      chunks: The chunks to index.
      persist_directory: Directory holding the Chroma data.

    Returns:
      The number of chunks indexed.

    Raises:
      ValueError: If ``chunks`` is empty.
    """
    if not chunks:
        raise ValueError("No chunks to index")
    ids = []
    next_index: dict[str, int] = {}
    for chunk in chunks:
        source = chunk.metadata["source"]
        ids.append(f"{source}:{next_index.get(source, 0)}")
        next_index[source] = next_index.get(source, 0) + 1

    store = vector_store(persist_directory)
    for source in next_index:
        store.delete(where={"source": source})
    store.add_documents(chunks, ids=ids)
    logger.info("indexed_chunks=%d", len(chunks))
    return len(chunks)
