# Legacy EvidenceAlpha — the pre-rewrite implementation

**Preserved:** 2026-09-02, from commit `742f1f0` on `main`.
**Status:** frozen. Nothing under `legacy/` is maintained, and the new
implementation must never import from it.

This folder keeps the first EvidenceAlpha build exactly as it was when
the project restarted from a clean slate (see the rewrite brief that
introduced Phase 0–7). Three documents describe it; `original/` holds
the code.

| File | What it is |
|---|---|
| `README.md` (this file) | What the old project does, how to run it, entry points, dependencies, environment, limitations, behavior worth keeping |
| `architecture.md` | The system as it exists: components, flows, storage, external services, loops |
| `module_map.md` | Per-module reference: purpose, public API, inputs, outputs, dependencies, users, notes |
| `original/` | The code, tests, fixtures, `pyproject.toml`, and `pylintrc`, moved with `git mv` so history follows |

The design documents the old code implements (`01`–`05`) live in
`tmp/docs/`, which is gitignored and local to this machine. They are
not copied here. Where this README and those docs disagree, the docs
describe the *intent* and the code in `original/` is the *fact*.

## 1. What the old project does

It is the **ingestion half** of an investment-research RAG system,
specialized for SEC filings. One vertical slice works end to end:

```
file on disk → detect format → parse → normalize → quality gate
            → chunk → embed → index in ChromaDB → (raw Chroma query)
```

Concretely, given a Photronics 10-Q as inline-XBRL HTML, it produces
~106 citation-safe chunks, each anchored to an XPath in the source
file, embeds them with a pinned local model, and stores them in Chroma.
An integration test then asks a paraphrased revenue question and checks
that the answer-bearing chunk is a top-5 hit.

What it does **not** do: there is no agent, no tools, no `retrieval/`
package, no SQLite evidence database, no `app.py`, no LLM call
anywhere. "Retrieval" exists only as a direct `collection.query()` in
one integration test. The design docs specify all of those; none were
built.

Roughly 8,100 lines of source and 5,800 lines of tests, all Python.

## 2. How it runs

Everything runs from the repository root, with the project's virtual
environment. After the move the code lives in `legacy/original/`, so
the working directory for these commands is that folder:

```bash
cd legacy/original

# 1. One-time setup: downloads the ~1.1 GB embedding model into
#    ~/.cache/huggingface and creates the Chroma collection under
#    storage/chroma/. The only step that needs the network.
../../.venv/bin/python scripts/init_db.py

# 2. Tests. Unit tests are offline and take seconds.
../../.venv/bin/python -m pytest tests/unit -q

# 3. Integration tests: real parser, real model, temporary Chroma.
#    Tens of seconds on CPU. Needs the model from step 1 in cache.
../../.venv/bin/python -m pytest tests/integration -q
```

Note on the environment: `.venv/` at the repo root was built for this
code (`pip install -e .` against the root `pyproject.toml`). That
editable install now points at a location the packages no longer
occupy. The tests above still work because pytest puts
`legacy/original/` on `sys.path` (it is the first ancestor of `tests/`
without an `__init__.py`). Running the modules any other way from the
root will fail with `ModuleNotFoundError`, which is the intended
outcome: the new code cannot import the old code by accident.

There is **no user-facing command** in the old project. It was never
wired into a CLI or an app. The only executable is `scripts/init_db.py`.

## 3. Main entry points

| Entry point | Role |
|---|---|
| `scripts/init_db.py` | Fetch the pinned model, create the Chroma collection. The only script. |
| `ingestion.parsing.service.ParserService.parse(artifact) -> ParserResult` | The parser subsystem's single entrypoint. A local file in, a `ParsedDocument` or a typed error out. |
| `ingestion.chunker.chunk(parsed, counter, policy) -> list[DocumentChunk]` | Pure function. Section-aware chunking under a token budget. |
| `ingestion.embedder.SentenceTransformerEmbedder` | `.embed_documents(chunks)` and `.embed_query(text)`; applies E5 role prefixes itself. |
| `ingestion.indexer.ChromaIndexer` | `.upsert(embedded)` and `.retire_superseded(...)`. The only module that imports `chromadb`. |
| `tests/integration/test_retrieval.py` | The closest thing to a demo: the full slice on a real 10-Q. |

The pipeline is wired together only in `tests/integration/conftest.py`.
There is no service, function, or script that runs "ingest this file"
end to end outside the tests.

## 4. Important dependencies

Declared in `original/pyproject.toml`; installed versions as of the
freeze in parentheses.

| Package | Why | Installed |
|---|---|---|
| `pydantic` 2.x | Every data contract is a frozen Pydantic model with `extra="forbid"` and model validators | 2.13.4 |
| `lxml` | SEC HTML / inline-XBRL adapter; XPath locators | 6.1.1 |
| `pymupdf` | Digital-PDF adapter; page + bounding-box locators; `find_tables` | 1.28.2 |
| `sentence-transformers` | Loads `intfloat/multilingual-e5-base` at a pinned revision | 5.7.0 |
| `chromadb` 1.x | The vector store; one collection per embedding signature, cosine space | 1.5.9 |
| `torch` (CPU wheel) | Pulled in by sentence-transformers; installed from the CPU index by hand before the project | 2.13.0+cpu |
| `edgartools` (spike group only) | Evaluated and rejected as the SEC parser; kept as a dev comparator | 5.49.0 |
| dev: `black`, `pylint`, `pytest` | Formatting at 80 columns, Google `pylintrc`, tests | 26.5.1 / 4.0.7 / 9.1.1 |

Python: `requires-python = ">=3.11,<3.13"`; the venv is Python 3.12.13.

The embedding model is a runtime dependency that is not a package:
`intfloat/multilingual-e5-base` at revision
`d128750597153bb5987e10b1c3493a34e5a4502a`, cached under
`~/.cache/huggingface/hub/models--intfloat--multilingual-e5-base`.

## 5. Required environment variables

**None.** The old code reads no environment variables and has no
`.env`. There are no API keys because there is no LLM or web call. The
only external interaction is the one-time HuggingFace model download,
which honors the standard `HF_HOME` / `HF_HUB_OFFLINE` variables if set
but does not require them.

Runtime data paths are constants: `storage/chroma` (Chroma persist
directory, `ingestion.indexer.DEFAULT_PERSIST_PATH`) and
`storage/documents` (created by `init_db.py`, never written to).

## 6. Known limitations

Ordered by how much they cost.

1. **Only two input formats parse.** SEC HTML (including inline XBRL)
   and digital PDF. Fifteen route roles are recognized; thirteen are
   unbound and refuse with `UNSUPPORTED_FORMAT`. Plain text, Markdown,
   generic HTML, DOCX, XLSX, CSV, JSON, images: all refused. No OCR.
2. **No query-side code.** No retriever, no result model, no filters.
   Doc 05 designed it; nothing was implemented.
3. **No agent, no LLM, no tools.** Nothing generates an answer.
4. **PDFs produce no headings**, so every PDF is one chunker section
   and chunking degenerates to flat greedy packing.
5. **Split tables lose their column headers.** The header-repeat rule in
   the chunker is implemented and unit-tested but no adapter populates
   `header_rows`, `caption`, or `unit`, so it never fires on real data.
6. **A document with dozens of degraded tables still grades `valid`.**
   Block-level warnings never reach the document verdict.
7. **No SQLite evidence store.** Chroma holds the only copy of chunk
   text and metadata.
8. **Re-upserting a retired chunk silently reactivates it**
   (`active: True` is unconditional in `chunk_metadata()`).
9. **The 512-token model window is guarded by a test, not by
   construction.** A pathological heading path could overflow it.
10. **The parser corpus (27 fixtures) lives in gitignored `tmp/`** and is
    hand-run; the committed suite does not exercise it.

## 7. Behavior worth preserving

These are the ideas the old code got right. They are candidates for
the rewrite once it needs them, not requirements for Phase 1.

- **Two texts per chunk.** `citation_text` is verbatim source text and
  is what the user sees; `embedding_text` is the same text with a
  deterministic context line in front (company, ticker, period, form,
  heading path) and is what gets vectorized. Nothing ever re-renders
  content that will be quoted.
- **E5 role prefixes applied inside the embedder.** `"passage: "` for
  chunks, `"query: "` for questions. A caller cannot forget them.
- **One Chroma collection per embedding signature**, named by a hash of
  `model@revision|prefix-v1|ctx-v1|norm-l2`, created with cosine space
  explicitly, stamped with the signature, and refused on mismatch.
  Vectors from different configurations never share a space.
- **Derived, deterministic IDs.** `parse_id`, `block_id`, and `chunk_id`
  are hashes of content and pipeline configuration, so re-running the
  pipeline is idempotent and the indexer can report `upserted` vs
  `already_present`.
- **Retire, never delete.** Superseded chunks are flagged
  `active = False` so old citations keep resolving.
- **Locator tiers.** Every block and chunk carries a graded pointer back
  into the source (XPath, page + bbox, line range). Routes demand a
  minimum tier; the gate rejects blocks below it.
- **Fail loudly with a typed error.** The parser never returns an empty
  document; it returns `ParserError` with a code and a `retry_with`
  hint. Unbound formats refuse by name rather than falling through to
  a generic text extractor.
- **Illegal states are unconstructible.** Frozen Pydantic models with
  validators for the table-grid invariant, payload/type agreement,
  canonical-text equality, and "a failed result carries no document".
- **Section-aware chunking.** Chunks never span a heading boundary;
  headings attach forward to the chunk they open; oversize blocks split
  on line → sentence → word (prose) or on row boundaries (tables) and
  the piece records the exact character or row span it came from.

If any of the above looks reusable for the new implementation, say so
and ask before copying. The rewrite brief's rule stands: the new code
must not import from `legacy/`.
