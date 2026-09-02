"""Phase 1 tests: load and split, retrieve a known fact, load a PDF."""

import pymupdf

from rag import ingest
from rag import retrieve

FACT = "Acme Robotics manufactures industrial robotic arms in Pittsburgh."


def test_load_and_split_produces_chunks(tmp_path):
    (tmp_path / "note.md").write_text("# Acme\n\n" + FACT, encoding="utf-8")

    documents = ingest.load_documents(str(tmp_path))
    chunks = ingest.split_documents(documents)

    assert len(documents) == 1
    assert len(chunks) >= 1
    assert "Pittsburgh" in chunks[0].page_content


def test_retrieves_the_chunk_holding_a_known_fact(tmp_path):
    docs = tmp_path / "documents"
    docs.mkdir()
    (docs / "acme.txt").write_text(FACT, encoding="utf-8")
    (docs / "other.txt").write_text(
        "Beta Foods sells frozen vegetables in Ohio.", encoding="utf-8"
    )
    chroma = str(tmp_path / "chroma")
    ingest.build_index(
        ingest.split_documents(ingest.load_documents(str(docs))), chroma
    )

    results = retrieve.search_documents(
        "Where does Acme Robotics manufacture robotic arms?",
        k=1,
        persist_directory=chroma,
    )

    assert "Pittsburgh" in results[0].text
    assert results[0].source.endswith("acme.txt")


def test_loads_text_from_a_digital_pdf(tmp_path):
    pdf_path = tmp_path / "acme.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), FACT)
        pdf.save(str(pdf_path))

    documents = ingest.load_documents(str(pdf_path))

    assert len(documents) == 1
    assert "Pittsburgh" in documents[0].page_content
    assert documents[0].metadata["page"] == 0


def test_reingesting_a_changed_source_replaces_its_chunks(tmp_path):
    source = tmp_path / "acme.txt"
    chroma = str(tmp_path / "chroma")
    source.write_text((FACT + " ") * 30, encoding="utf-8")  # several chunks
    ingest.build_index(
        ingest.split_documents(ingest.load_documents(str(source))), chroma
    )
    assert len(ingest.vector_store(chroma).get()["ids"]) > 1

    source.write_text("Acme Robotics moved to Cleveland.", encoding="utf-8")
    ingest.build_index(
        ingest.split_documents(ingest.load_documents(str(source))), chroma
    )

    stored = ingest.vector_store(chroma).get()
    assert stored["ids"] == [f"{source}:0"]
    assert stored["documents"] == ["Acme Robotics moved to Cleveland."]
