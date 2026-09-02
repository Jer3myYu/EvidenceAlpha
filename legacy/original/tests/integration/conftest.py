"""Shared fixtures for the integration suite (04 §8).

These tests use the real parser, the real pinned embedding model, and
a real (temporary) Chroma store. The model must already be in the
local HuggingFace cache — ``scripts/init_db.py`` fetches it once;
after that everything here runs offline. Parsing, chunking, and
embedding the golden 10-Q are done once per session because they cost
tens of seconds on CPU.
"""

import os

import pytest

from contracts import document
from ingestion import chunker
from ingestion import embedder as embedder_module
from ingestion.parsing import service as service_module
from ingestion.parsing import shapes

TEN_Q_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        os.pardir,
        "fixtures",
        "sec",
        "photronics_2026_q2_10q.htm",
    )
)


def ten_q_artifact(
    document_id: str = "doc_plab_10q",
    version_id: str = "sha256:golden-version",
) -> shapes.AcquiredArtifact:
    """Build the artifact the ingestion service would hand over."""
    return shapes.AcquiredArtifact(
        path=TEN_Q_PATH,
        content_hash="sha256:golden",
        size_bytes=os.path.getsize(TEN_Q_PATH),
        document_id=document_id,
        version_id=version_id,
        source_class=document.SourceClass.SEC_FILING,
        filename=os.path.basename(TEN_Q_PATH),
        expected_source_type=document.SourceType.SEC_FILING,
        canonical_url="https://www.sec.gov/Archives/plab-10q.htm",
    )


@pytest.fixture(name="ten_q", scope="session")
def ten_q_fixture():
    """Parse the golden 10-Q once for the whole session."""
    result = service_module.ParserService().parse(ten_q_artifact())
    if result.parsed_document is None:
        pytest.fail(f"golden 10-Q failed to parse: {result.error}")
    return result.parsed_document


@pytest.fixture(name="real_embedder", scope="session")
def real_embedder_fixture():
    """Load the pinned model once for the whole session."""
    return embedder_module.SentenceTransformerEmbedder()


@pytest.fixture(name="ten_q_chunks", scope="session")
def ten_q_chunks_fixture(ten_q, real_embedder):
    """Chunk the golden 10-Q under the real tokenizer counter."""
    return chunker.chunk(ten_q, real_embedder.token_counter())


@pytest.fixture(name="ten_q_embedded", scope="session")
def ten_q_embedded_fixture(ten_q_chunks, real_embedder):
    """Embed the golden 10-Q's chunks once for the whole session."""
    return real_embedder.embed_documents(ten_q_chunks)
