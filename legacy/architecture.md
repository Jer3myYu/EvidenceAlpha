# Legacy architecture — the system as it exists

**Describes:** the code in `legacy/original/` at commit `742f1f0`.
**Written:** 2026-09-02. Descriptive only; nothing here is redesigned.
Design intent lives in `tmp/docs/01`–`05` (local, gitignored); this
file records what was actually built.

## 1. Major components

```
legacy/original/
├── contracts/            neutral data layer — imports nothing else in-project
│   ├── document.py       ParsedDocument, Block, TableBlock, Locator, …
│   ├── chunk.py          DocumentChunk, ChunkSegment, ChunkBusiness
│   ├── quality.py        LocatorTier, QualityVerdict, WarningCode, BlockRejectionReason
│   └── embedding.py      QueryEmbedder protocol (the ingestion ↔ retrieval seam)
├── ingestion/
│   ├── parsing/          the parser subsystem
│   │   ├── service.py    ParserService.parse — the one entrypoint
│   │   ├── detector.py   format detection (magic bytes, containers, content)
│   │   ├── registry.py   format → route → adapter bindings; startup validation
│   │   ├── capabilities.py  what an adapter promises vs what a route requires
│   │   ├── shapes.py     AcquiredArtifact, RawParseResult, the three native shapes
│   │   ├── gate.py       quality gate: per-block admission, per-document verdict
│   │   ├── manifest.py   planned/observed manifest; parse_id
│   │   ├── egress.py     deny-all network policy for adapters
│   │   ├── adapters/     sec_html_lxml.py, pdf_pymupdf.py, base.py
│   │   └── converters/   blocks.py, elements.py, markdown.py, common.py
│   ├── chunker.py        section-aware chunking (pure function)
│   ├── embedder.py       pinned local E5 model, role prefixes
│   └── indexer.py        the only chromadb importer; upsert and retire
├── scripts/init_db.py    one-time model fetch + collection creation
├── tests/                unit/ mirrors source; integration/ uses the real model
└── storage/              runtime data (chroma.sqlite3 from an earlier init run)
```

Five layers, one dependency direction:

```
scripts/  →  ingestion/  →  contracts/
             ingestion/parsing/  →  contracts/
             ingestion/{chunker,embedder,indexer}  →  contracts/
```

`contracts/` imports nothing from the project. `ingestion/parsing/`
never imports `chunker`, `embedder`, or `indexer`. `indexer` imports
`embedder` (for `EmbeddedChunk`); `embedder` imports `chunker` (for the
`TokenCounter` protocol). Nothing imports `scripts/`.

Planned but absent: `agent/`, `tools/`, `retrieval/`, a `storage/`
Python package (SQLite repositories), `app.py`.

## 2. Agent flow

**There is none.** No agent, no LLM client, no prompt, no tool
definitions. The design docs describe a single Claude Agent SDK agent
calling a `search_documents` tool; none of it was written.

## 3. Retrieval flow

**Not implemented as a module.** The only query path is inside
`tests/integration/test_retrieval.py`:

```
question (str)
   │  SentenceTransformerEmbedder.embed_query()   prepends "query: ", L2-normalizes
   ▼
query vector (768-d)
   │  ChromaIndexer.collection.query(query_embeddings=[v], n_results=5,
   │                                 include=["documents", "metadatas"])
   ▼
Chroma result dict: documents (citation_text), metadatas (filter fields)
```

No filtering on `active`, no result model, no dedupe, no score
normalization. `contracts/embedding.QueryEmbedder` exists so a future
`retrieval/` package could embed queries identically without importing
`ingestion/`; the embedder satisfies that protocol.

## 4. Tool flow

**There is none.** No MCP, no tool wrappers, no web search, no fetch.

## 5. Ingestion flow (the flow that exists)

The pipeline is wired only in `tests/integration/conftest.py`. Each
stage is a separate call; there is no orchestrating function.

### 5.1 Parse: `ParserService.parse(artifact) -> ParserResult`

```
AcquiredArtifact                 path, content_hash, size_bytes, source_class,
   │                             document_id, version_id, limits, ocr_policy
   ├─ budget / encryption check   oversize → PARSER_BUDGET_EXCEEDED
   │                              encrypted PDF → ENCRYPTED_DOCUMENT
   ├─ FormatDetector.detect()  ──► DetectionResult (format, resolution, conflicts)
   ├─ AdapterRegistry.resolve() ─► RouteRole, or UNSUPPORTED_FORMAT naming the format
   ├─ build_planned_manifest() ──► parse_id = sha256(version_id + canonical planned json)
   ├─ adapter.parse(request) ────► RawParseResult carrying one native shape:
   │                               BlockSequence | ElementList | MarkdownDocument
   ├─ converters._convert() ─────► list[Block]  normalized text, block_id, extraction info
   └─ QualityGate.evaluate() ────► GateOutcome  verdict + admitted + rejected blocks
                ▼
   ParserResult{ parsed_document: ParsedDocument | None,
                 manifest, error: ParserError | None }
```

Detection signal priority: caller `source_class` → magic bytes and
container inspection (ZIP members, OLE2 directory walk) → content
markers (inline XBRL, HTML, XML root, JSON, Markdown, delimiters) →
HTTP content type → file extension (supporting only). Disagreements
are recorded as `conflicts`, not failures.

Routing: `DetectedFormat → RouteRole → adapter name`. Bound today:
`sec_html_parser → sec_html_lxml`, `pdf_layout_parser → pdf_pymupdf`.
The other thirteen roles refuse. `AdapterRegistry.__init__` checks every
binding's declared capabilities against the route's minimum profile at
import time.

Gate verdicts: `FAILED` (must not be indexed), `PARTIAL` (indexable,
carries warnings), `VALID`. Per-block rejections are persisted in
`parse_quality.rejected_blocks`, never dropped silently.

### 5.2 Chunk: `chunker.chunk(parsed, counter, policy) -> list[DocumentChunk]`

Pure function. Policy v0: `max_tokens=420`, `min_tokens=240`,
`overlap_tokens=50`, chosen so content plus context prefix plus role
prefix stays under the model's 512-token window.

1. Compute each block's *effective path*: `heading_path`, plus its own
   text if it is a heading.
2. Group contiguous runs of equal effective path into sections. Chunks
   never span a section.
3. Within a section, pack blocks greedily to `max_tokens`. Overlap is
   whole trailing blocks of the previous chunk, never a character
   window. A heading-only draft is not emitted; it attaches forward to
   the next chunk.
4. An oversize block splits: prose on lines → sentences → words,
   recording a `paragraph_span` of character offsets; a table on row
   boundaries of its canonical rendering, recording `table_rows`.
5. Finalize: `citation_text` verbatim, `embedding_text = context_prefix
   + citation_text`, `locator_tier` = worst member, `warning_codes` =
   document codes ∪ member block codes, `chunk_id` = hash of
   `(document_id, parse_id, chunking_signature, locator, ordinal)`.

### 5.3 Embed: `SentenceTransformerEmbedder.embed_documents(chunks) -> list[EmbeddedChunk]`

Model `intfloat/multilingual-e5-base` at a pinned revision. Prepends
`"passage: "`, batch size 32, L2-normalized, 768 dimensions. The
embedder also exposes `token_counter()`, the model's own tokenizer, so
the chunk budget means what the model means.

`EMBEDDING_SIGNATURE = model@revision|prefix-v1|ctx-v1|norm-l2`.

### 5.4 Index: `ChromaIndexer.upsert(embedded) -> IndexingResult`

Collection `evidence_<sha256(signature)[:8]>`, created with
`hnsw.space = cosine`, stamped with the full signature; construction
raises `SignatureMismatchError` if an existing collection's stamp
differs. Batches of 256; a failed batch raises `IndexWriteError`.
Preflight `get(ids)` splits the result into `upserted` and
`already_present`. `retire_superseded(document_id, version_id,
parse_id)` flips `active = False` on records not matching the pair in
force; nothing is deleted.

## 6. State and data flow

Every object crossing a boundary is a frozen Pydantic v2 model with
`extra="forbid"`:

| Stage | In | Out |
|---|---|---|
| Parse | `AcquiredArtifact` | `ParserResult` → `ParsedDocument` (blocks, identity, business metadata, parse quality) |
| Chunk | `ParsedDocument`, `TokenCounter`, `ChunkPolicy` | `list[DocumentChunk]` |
| Embed | `list[DocumentChunk]` | `list[EmbeddedChunk]` (chunk + vector + signature) |
| Index | `list[EmbeddedChunk]` | `IndexingResult{upserted, already_present}` |
| Query | `str` | Chroma result dict (documents, metadatas) |

Identities, all derived, never assigned:

```
version_id  = f(file bytes)                      supplied by the caller
parse_id    = sha256(version_id + planned manifest)
block_id    = f(parse_id, ordinal, locator)
chunk_id    = f(document_id, parse_id, chunking_signature, locator, ordinal)
```

No global state, no clock, no randomness in parse or chunk. The only
mutable state is the Chroma collection.

## 7. Storage

| Store | Where | Holds | Written by |
|---|---|---|---|
| ChromaDB (persistent, SQLite-backed) | `storage/chroma/` (`DEFAULT_PERSIST_PATH`); tests use a `tmp_path` client | `citation_text` as the document; vector; metadata: `heading_path`, `warning_codes` (native lists), `page`, `section`, `ticker`, `cik`, `document_type`, `reporting_period`, `published_at`, `url`, `locator_tier`, `token_count`, `source_type`, `document_id`, `version_id`, `parse_id`, `chunking_signature`, `active`, and JSON strings for `locator` and `segment`. `None` values omitted. | `ChromaIndexer` only |
| HuggingFace cache | `~/.cache/huggingface/hub/` | The embedding model weights | `sentence_transformers` on first load |
| `storage/documents/` | created by `init_db.py` | nothing; reserved for acquired files | never |
| SQLite evidence DB | designed (`research.db`) | not built | — |

The `storage/chroma/chroma.sqlite3` preserved under `original/` is from
an `init_db.py` run on 2026-08-16. It holds an empty collection for the
current signature and can be regenerated.

## 8. External services

| Service | When | Purpose |
|---|---|---|
| HuggingFace Hub | first run of `init_db.py` or first `SentenceTransformerEmbedder()` | Download the pinned model (~1.1 GB) |

That is the complete list. The parser is network-free by contract:
adapters declare `egress = NONE`, and `DenyAllEgressPolicy` refuses
any adapter that declares otherwise, at import time. No SEC EDGAR
client, no web search, no LLM API.

## 9. Important loops

- **Parser fallback loop** (`service.py`, `_run_route`): at most one
  fallback attempt if the gate says `FAILED` or an observed warning is
  in the binding's `severe_partial_warnings`; both attempts are
  recorded and the better verdict kept. Dormant: neither route has a
  fallback bound.
- **Chunker packing loop** (`chunker.py`, `_chunk_section`): walk a
  section's blocks; close a draft when the next block would exceed the
  budget or is itself oversize; seed the next draft with trailing-block
  overlap; split oversize blocks into pieces.
- **Indexer batch loop** (`indexer.py`, `upsert`): 256 chunks per
  batch, preflight `get` then `upsert`, abort loudly on the first
  failed batch.
- **Detector container walks** (`detector.py`): bounded ZIP member
  listing under `ZipLimits`, and an OLE2 FAT-chain directory walk
  capped by `_OLE2_MAX_DIRECTORY_SECTORS`.

There is no agent loop, no research/verify loop, no retry loop around
any external call.

## 10. Tests

426 tests, all passing at the freeze (2026-09-02, full suite run
from the repo root before the move). 405 unit tests are offline and
fast; 21 integration tests parse, chunk, embed, and index the golden
Photronics 10-Q with the real model and a temporary Chroma store.
Fixtures: two real Photronics filings in `tests/fixtures/sec/`
(an 8-K and a 10-Q). A 79-test conformance suite under
`tests/unit/ingestion/parsing/conformance/` runs every adapter against
the contract invariants, using stub adapters to prove the suite itself
has teeth.
