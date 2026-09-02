# Legacy module map

**Describes:** `legacy/original/` at commit `742f1f0`. Paths below are
relative to `legacy/original/`. **Written:** 2026-09-02.

Conventions: every data model is a frozen Pydantic v2 model with
`extra="forbid"` unless noted. "Used by" lists in-project importers
only. Module docstrings cite the design-doc section they implement
(for example `03 §5.3`); those docs are in `tmp/docs/`, local-only.

---

## contracts/ — neutral data layer

### `contracts/quality.py`
- **Purpose:** the quality vocabulary shared by parsing, chunking, and retrieval.
- **Main symbols:** `LocatorTier` (IntEnum 1 `ANCHORED`, 2 `COARSE`, 3 `DIAGNOSTIC`; lower is better; `.meets(required)`), `QualityVerdict` (`VALID`/`PARTIAL`/`FAILED`), `WarningCode` (closed enum, 18 members), `BlockRejectionReason`.
- **Inputs / outputs:** enums only; no functions.
- **Dependencies:** stdlib `enum`.
- **Used by:** `contracts/document.py`, `contracts/chunk.py`, `ingestion/chunker.py`, `ingestion/parsing/{capabilities,gate,manifest,registry}.py`, adapters, converters.
- **Notes:** warnings are a closed enum on purpose so they can be metadata filters, not log lines.

### `contracts/document.py` (693 L)
- **Purpose:** the normalized document contract every downstream stage consumes.
- **Main symbols:** enums `BlockType`, `ValueType`, `UnitSource`, `SourceClass`, `SourceType`; models `Locator` (`html_anchor`, `xpath`, `page`, `bounding_box`, `slide`, `sheet`, `cell_range`, `line_start/end`, `element_index`; `.tier(has_heading_path)`), `ParseWarning`, `TableCell`, `TableBlock` (complete `n_rows × n_columns` grid of origin cells and covered placeholders; grid invariant enforced by validator), `FinancialFact`, `KeyValuePair`, `BlockExtraction`, `Block` (`block_id`, `type`, `heading_path`, `text`, `payload`, `locator`, `extraction`; `.locator_tier()`), `RejectedBlock`, `ParseMetrics`, `ParseQuality`, `DocumentIdentity`, `SourceInfo`, `BusinessMetadata`, `ParsedDocument`; functions `render_table_text(table)`, `render_financial_fact_text(fact)`.
- **Inputs / outputs:** models; the two render functions take a payload and return its canonical text.
- **Dependencies:** `pydantic`; `contracts/quality.py`.
- **Used by:** everything in `ingestion/`, `contracts/chunk.py`, tests.
- **Notes:** `Block.text` must equal the canonical rendering of `Block.payload` (validator). `heading_path` holds enclosing headings only; a heading block never contains itself. CIK is normalized to ten zero-padded digits. `SCHEMA_VERSION = "1.1"`.

### `contracts/chunk.py` (163 L)
- **Purpose:** the chunk contract written by the chunker and read by indexing and (future) retrieval.
- **Main symbols:** `ChunkSegmentKind` (`paragraph_span`, `table_rows`), `ChunkSegment`, `ChunkBusiness` (company, ticker, cik, document_type, reporting_period, published_at, url), `DocumentChunk` (`chunk_id`, `document_id`, `version_id`, `parse_id`, `chunking_signature`, `ordinal`, `citation_text`, `embedding_text`, `block_ids`, `segment`, `section`, `heading_path`, `locator`, `locator_tier`, `warning_codes`, `token_count`, `business`, `schema_version`).
- **Dependencies:** `pydantic`; `contracts/document.py`, `contracts/quality.py`.
- **Used by:** `ingestion/chunker.py`, `ingestion/embedder.py`, `ingestion/indexer.py`.
- **Notes:** rejects empty `citation_text` and empty or duplicate `block_ids`; sorts and dedupes `warning_codes` so equal chunks serialize identically.

### `contracts/embedding.py` (36 L)
- **Purpose:** the `QueryEmbedder` protocol so a future retrieval layer can embed queries without importing `ingestion/`.
- **Main symbols:** `QueryEmbedder` (runtime-checkable Protocol: `embed_query(text) -> list[float]`, `signature -> str`).
- **Dependencies:** `typing`.
- **Used by:** satisfied by `ingestion/embedder.SentenceTransformerEmbedder`; checked in `tests/unit/ingestion/test_embedder.py`. No production importer.

---

## ingestion/parsing/ — the parser subsystem

### `ingestion/parsing/shapes.py` (278 L)
- **Purpose:** data shapes crossing the parser boundary.
- **Main symbols:** `ParserErrorCode`, `RetryWith` (`none`/`larger_budget`/`different_source`/`transient`), `OcrPolicy`, `ParseLimits` (100 MB / 120 s defaults), `AcquiredArtifact` (path, content_hash, size_bytes, document_id, version_id, source_class, URLs, headers, declared media type, expected_source_type, limits, ocr_policy), the three native shapes `BlockSequence`, `ElementList` (+ `Element`, `ElementKind`), `MarkdownDocument` (+ `PageSpan`), `NativeShape`, `shape_of(content)`, `RawParseResult`.
- **Dependencies:** `pydantic`; `contracts/document.py`.
- **Used by:** every other parsing module, adapters, converters, tests.
- **Notes:** the parser starts from an already-fetched local file; acquisition is out of scope.

### `ingestion/parsing/capabilities.py` (262 L)
- **Purpose:** what an adapter declares it can do versus what a route requires.
- **Main symbols:** `TableFidelity` (`NONE < TEXT < GRID < TYPED_GRID`), `ExtractionClass`, `Determinism`, `Egress`, `CostClass`, `RouteRole` (15 roles), `AdapterCapabilities` (`.best_locator_tier()`), `RouteProfile`, `check_capabilities(capabilities, profile) -> list[str]`.
- **Dependencies:** `pydantic`; `contracts/document.py`, `contracts/quality.py`, `shapes.py`.
- **Used by:** `registry.py`, `gate.py`, `manifest.py`, `egress.py`, `service.py`, adapters, `converters/common.py`.

### `ingestion/parsing/detector.py` (885 L)
- **Purpose:** deterministic format detection before dispatch.
- **Main symbols:** `DetectedFormat` (~20 formats), `Resolution` (categorical, not a score), `ZipLimits`, `ZipInspection`, `inspect_zip(path, limits)`, `Ole2Inspection`, `inspect_ole2(path)`, `DetectionResult` (format, resolution, conflicts), `DetectionError`, `FormatDetector.detect(artifact) -> DetectionResult`.
- **Inputs:** an `AcquiredArtifact`; reads the file head (`SNIFF_BYTES`) and tail. **Outputs:** `DetectionResult`.
- **Dependencies:** stdlib `json`, `os`, `zipfile`; `pydantic`; `contracts/document.py`, `shapes.py`.
- **Used by:** `service.py`, `registry.py`, adapters (for format constants).
- **Notes:** signal priority is caller `source_class` → magic bytes and containers → content markers → media type → extension. Extension never decides. No models.

### `ingestion/parsing/registry.py` (315 L)
- **Purpose:** format → route → adapter bindings, validated at import time.
- **Main symbols:** `ROUTE_TABLE` (`DetectedFormat → RouteRole`), `ROUTE_BINDINGS` (`RouteRole → Binding`), `Binding` (adapter name, optional fallback, profile, `severe_partial_warnings`), `RegistryError`, `AdapterRegistry` (`.resolve(detected_format)`, `.binding_for(role)`, `.profile_for(role)`, `.adapter(name)`, `.egress_policy()`), `DEFAULT_REGISTRY`.
- **Dependencies:** `pydantic`; `contracts/quality.py`, `capabilities.py`, `detector.py`, `egress.py`, `adapters/base.py`, `adapters/pdf_pymupdf.py`, `adapters/sec_html_lxml.py`.
- **Used by:** `service.py`, tests.
- **Notes:** bound routes: `sec_html_parser → sec_html_lxml`, `pdf_layout_parser → pdf_pymupdf`. Neither has a fallback. A binding below its profile fails at import.

### `ingestion/parsing/egress.py` (141 L)
- **Purpose:** network policy for adapters.
- **Main symbols:** `EgressPolicy` (Protocol), `DenyAllEgressPolicy`, `EgressDecision`, `EgressPolicyError`, `validate_adapter_egress(adapter_name, capabilities, policy)`.
- **Dependencies:** `pydantic`; `contracts/document.py`, `capabilities.py`.
- **Used by:** `registry.py`.
- **Notes:** only the decision point exists; there is no transport or allowlist.

### `ingestion/parsing/manifest.py` (284 L)
- **Purpose:** the planned/observed parse manifest and `parse_id`.
- **Main symbols:** `PlannedAttempt`, `PlannedManifest` (`.primary()`), `ParseAttempt`, `ObservedManifest`, `ParseManifest`, `canonical_planned_payload(planned)`, `compute_parse_id(version_id, planned) -> str`, `build_planned_attempt(...)`, `build_planned_manifest(role, attempts, quality_policy_version)`, `raw_output_digest(raw)`.
- **Dependencies:** stdlib `hashlib`, `json`; `pydantic`; `contracts/`, `capabilities.py`, `shapes.py`, all four converters (for their version constants).
- **Used by:** `service.py`.
- **Notes:** only the planned half is hashed, so `parse_id` is computable before parsing and is stable whichever attempt wins.

### `ingestion/parsing/gate.py` (509 L)
- **Purpose:** per-block admission and per-document verdict.
- **Main symbols:** `QualityPolicy` (thresholds; `POLICY_V0`), `GateOutcome` (verdict, admitted, rejected, warnings, metrics; `.failed()`), `QualityGate` (`.policy()`, `.evaluate(blocks, artifact, raw, adapter_capabilities, profile, conversion_warnings) -> GateOutcome`).
- **Dependencies:** `pydantic`; `contracts/`, `capabilities.py`, `shapes.py`.
- **Used by:** `service.py`, `adapters/pdf_pymupdf.py` (reads the scanned-PDF thresholds from the same policy).
- **Notes:** HTML coverage checks extracted characters against source bytes (ratio floor 0.01, absolute floor 2000 chars); PDF coverage requires every page emitted. Block-level warnings do not reach the verdict (known gap).

### `ingestion/parsing/service.py` (610 L)
- **Purpose:** `ParserService.parse` — the subsystem entrypoint.
- **Main symbols:** `ParserError` (code, message, retry_with), `ParserResult` (parsed_document | error, manifest), `ParserService.parse(artifact) -> ParserResult`, private `_Attempt`, `_convert(content, context)`.
- **Inputs:** `AcquiredArtifact`. **Outputs:** `ParserResult`; never raises for a bad document.
- **Dependencies:** stdlib `time`; `pydantic`; `contracts/`, `capabilities.py`, `detector.py`, `gate.py`, `manifest.py`, `registry.py`, `shapes.py`, `adapters/base.py`, all converters.
- **Used by:** `tests/integration/conftest.py`, unit and conformance tests. No production caller.
- **Notes:** budget and encryption checks run before dispatch; at most one fallback attempt; a validator makes "failed but carrying a document" unconstructible.

### `ingestion/parsing/adapters/base.py` (104 L)
- **Purpose:** the adapter contract.
- **Main symbols:** `ParserAdapter` (Protocol: `supports(request) -> bool`, `parse(request) -> RawParseResult`), `ParseRequest`, `AdapterError`, `UnsupportedContent`.
- **Dependencies:** `pydantic`; `capabilities.py`, `detector.py`, `shapes.py`.
- **Used by:** both adapters, `registry.py`, `service.py`, conformance stubs.

### `ingestion/parsing/adapters/sec_html_lxml.py` (810 L)
- **Purpose:** SEC HTML and inline-XBRL adapter over lxml.
- **Main symbols:** `SecHtmlLxmlAdapter` (`.supports`, `.parse`), private `_BlockBuilder` (DOM walk: `.walk(element)`, `.emit_facts(root)`), `_FactIndex`, `_build_grid(element)`, `_numeric_value`, `_words_to_number`.
- **Inputs:** `ParseRequest` for `sec_inline_xbrl_html` / `sec_html`. **Outputs:** `RawParseResult` with a `BlockSequence`; every block has an XPath locator (tier 1).
- **Dependencies:** stdlib `decimal`, `re`; `lxml`; `contracts/`, `capabilities.py`, `detector.py`, `shapes.py`, `adapters/base.py`.
- **Used by:** `registry.py`.
- **Notes:** recognizes Part/Item headings by form-aware regex; resolves rowspan/colspan into the grid; emits each `ix:nonFraction` as a `financial_fact` with the declared transform applied; lifts `dei:` cover facts into `BusinessMetadata`. `header_rows` is never populated (no `<th>` in the fixtures).

### `ingestion/parsing/adapters/pdf_pymupdf.py` (421 L)
- **Purpose:** digital-PDF adapter over PyMuPDF.
- **Main symbols:** `PdfPymupdfAdapter` (`.supports`, `.parse`), `has_sufficient_embedded_text(page_characters, policy)`, private `_PageWalker.walk_page(page)`, `_build_grid(table)`, `_merge_split_parentheses`, `_grid_warnings`.
- **Inputs:** `ParseRequest` for `pdf`. **Outputs:** `BlockSequence`; every block has `page` + `bounding_box` (tier 1).
- **Dependencies:** stdlib `re`, `statistics`; `pymupdf`; `contracts/`, `capabilities.py`, `detector.py`, `gate.py`, `shapes.py`, `adapters/base.py`.
- **Used by:** `registry.py`.
- **Notes:** refuses image-only PDFs with `UnsupportedContent("scanned_pdf")`. Emits no headings, so every PDF is a single chunker section. Tables via `page.find_tables()`; collapsed rows carry `TABLE_STRUCTURE_LOST`.

### `ingestion/parsing/converters/common.py` (298 L)
- **Purpose:** normalization shared by all three shape converters.
- **Main symbols:** `NORMALIZER_VERSION`, `normalize_text(text)`, `make_block_id(parse_id, ordinal, locator)`, `enforce_table_typing(table, table_fidelity)`, `ConversionContext` (`.extraction(block_warnings)`), `build_block(context, ordinal, block_type, text, locator, heading_path, payload, block_warnings)`, `HeadingStack` (`.push(level, text)`, `.path()`).
- **Dependencies:** stdlib `hashlib`, `unicodedata`; `contracts/`, `capabilities.py`.
- **Used by:** the three converters, `manifest.py`, `service.py`.
- **Notes:** the one place block identity and canonical text are produced; strips cell typing if the adapter only declared `GRID`.

### `ingestion/parsing/converters/blocks.py` (52 L)
- **Purpose:** `BlockSequence` → normalized `list[Block]`.
- **Main symbols:** `CONVERTER_VERSION`, `convert(sequence, context)`.
- **Dependencies:** `contracts/document.py`, `shapes.py`, `converters/common.py`.
- **Used by:** `service.py`, `manifest.py`.
- **Notes:** the only converter a production adapter exercises.

### `ingestion/parsing/converters/elements.py` (107 L)
- **Purpose:** `ElementList` → `list[Block]` (groups list items, derives heading levels).
- **Main symbols:** `CONVERTER_VERSION`, `convert(element_list, context)`.
- **Dependencies:** `contracts/document.py`, `shapes.py`, `converters/common.py`.
- **Used by:** `service.py`, `manifest.py`; exercised only by conformance stubs.

### `ingestion/parsing/converters/markdown.py` (329 L)
- **Purpose:** `MarkdownDocument` → `list[Block]` (ATX/setext headings, fences, lists, pipe tables → grids, page map → locators).
- **Main symbols:** `CONVERTER_VERSION`, `convert(markdown_document, context)`, private `_Parser.run()`, `_build_table(rows)`.
- **Dependencies:** stdlib `re`; `contracts/`, `shapes.py`, `converters/common.py`.
- **Used by:** `service.py`, `manifest.py`; exercised only by conformance stubs.

---

## ingestion/ — post-parser stages

### `ingestion/chunker.py` (743 L)
- **Purpose:** section-aware chunking of a `ParsedDocument`; a pure function.
- **Main symbols:** `TokenCounter` (Protocol: callable on text, `.name`), `WhitespaceTokenCounter`, `ChunkPolicy` (`POLICY_V0`: 420 / 240 / 50 tokens), `CHUNKER_VERSION = "chunk-1.0"`, `CONTEXT_PREFIX_VERSION = "ctx-v1"`, `make_chunking_signature(policy, counter)`, `make_chunk_id(...)`, `context_prefix(business, path)`, `chunk(parsed, counter, policy=POLICY_V0) -> list[DocumentChunk]`; private `_sections`, `_chunk_section`, `_seed_overlap`, `_split_block`, `_split_text`, `_split_table`, `_finalize`.
- **Inputs:** `ParsedDocument`, a token counter, a policy. **Outputs:** ordered `DocumentChunk`s.
- **Dependencies:** stdlib `hashlib`, `re`; `pydantic`; `contracts/`.
- **Used by:** `ingestion/embedder.py` (protocol only), `tests/integration/conftest.py`, unit tests.
- **Notes:** no I/O, no clock, no randomness. A `ChunkPolicy` that changes a number without a new version string is rejected.

### `ingestion/embedder.py` (178 L)
- **Purpose:** the pinned local embedding model behind two methods.
- **Main symbols:** `MODEL_NAME = "intfloat/multilingual-e5-base"`, `MODEL_REVISION`, `EMBEDDING_SIGNATURE`, `MODEL_TOKEN_WINDOW = 512`, `EmbeddedChunk` (chunk, vector, embedding_signature), `ModelTokenCounter`, `SentenceTransformerEmbedder` (`.signature`, `.token_counter()`, `.embed_documents(chunks) -> list[EmbeddedChunk]`, `.embed_query(text) -> list[float]`).
- **Dependencies:** `pydantic`; `sentence_transformers` (imported inside `__init__`); `contracts/chunk.py`, `ingestion/chunker.py`.
- **Used by:** `ingestion/indexer.py`, `scripts/init_db.py`, integration conftest, unit tests (with a stub model).
- **Notes:** prepends `"passage: "` / `"query: "`; L2-normalizes; batch 32. Satisfies `contracts.embedding.QueryEmbedder`.

### `ingestion/indexer.py` (272 L)
- **Purpose:** the only module that imports `chromadb`; writes and retires.
- **Main symbols:** `DEFAULT_PERSIST_PATH = "storage/chroma"`, `SignatureMismatchError`, `IndexWriteError`, `IndexingResult` (upserted, already_present), `collection_name_for(signature)`, `chunk_metadata(chunk) -> dict`, `ChromaIndexer(embedding_signature, path=None, client=None)` (`.collection`, `.upsert(chunks) -> IndexingResult`, `.retire_superseded(document_id, active_version_id, active_parse_id) -> int`).
- **Dependencies:** stdlib `hashlib`, `json`; `chromadb`; `pydantic`; `contracts/chunk.py`, `ingestion/embedder.py`.
- **Used by:** `scripts/init_db.py`, integration tests, unit tests.
- **Notes:** one collection per signature, cosine space, signature stamped and re-checked; batches of 256; `active` always written `True`; `None` metadata omitted.

---

## scripts/

### `scripts/init_db.py` (51 L)
- **Purpose:** one-time setup: create `storage/chroma` and `storage/documents`, load the model (downloading on first run), create the collection, print the signature and record count.
- **Main symbols:** `main()`.
- **Dependencies:** stdlib `pathlib`; `ingestion/embedder.py`, `ingestion/indexer.py`.
- **Used by:** the developer, by hand.
- **Notes:** the only executable in the project; safe to re-run.

---

## tests/

| Path | Tests | What it covers |
|---|---|---|
| `tests/unit/contracts/` | 57 | Grid invariant, payload/type agreement, canonical text, CIK normalization, locator tiers, chunk segment rules |
| `tests/unit/ingestion/parsing/test_detector.py` | 56 | Signal priority, ZIP and OLE2 inspection, JSON prefix, Markdown probe, ambiguity |
| `tests/unit/ingestion/parsing/test_registry.py` | 12 | Under-capable bindings fail at import |
| `tests/unit/ingestion/parsing/test_gate.py` | 20 | Admission reasons, verdicts, coverage predicates |
| `tests/unit/ingestion/parsing/test_manifest.py` | 28 | `parse_id` stability, planned vs observed |
| `tests/unit/ingestion/parsing/test_service.py` | 19 | Pipeline order, controlled failures, fallback path against stubs |
| `tests/unit/ingestion/parsing/test_egress.py` | 12 | Deny-all asserted |
| `tests/unit/ingestion/parsing/converters/` | 45 | All three shapes normalize identically |
| `tests/unit/ingestion/parsing/conformance/` | 79 | The suite every adapter must pass; deliberately broken stub adapters prove it has teeth |
| `tests/unit/ingestion/parsing/adapters/` | 30 | Golden tests on the real 8-K, 10-Q, and a generated PDF |
| `tests/unit/ingestion/test_chunker.py` | 31 | Sections, packing, overlap, both split kinds |
| `tests/unit/ingestion/test_embedder.py` | 8 | Role prefixes, signature, protocol conformance (stub model) |
| `tests/unit/ingestion/test_indexer.py` | 8 | Metadata mapping |
| `tests/integration/test_golden_chunks.py` | 10 | Real 10-Q chunks within budget and window, anchored, deterministic |
| `tests/integration/test_indexing.py` | 8 | Cosine space, signature refusal, idempotent upsert, retirement |
| `tests/integration/test_retrieval.py` | 3 | The vertical slice: paraphrased question → answer-bearing chunk |

Helpers: `tests/unit/ingestion/parsing/conftest.py` disables sockets for every parsing test; `pdf_fixture.py` writes a small digital PDF; `conformance/stub_adapters.py` holds three well-behaved adapters and ten variants that misbehave or declare different capabilities; `tests/integration/conftest.py` parses, chunks, and embeds the golden 10-Q once per session. Fixtures: `tests/fixtures/sec/photronics_2026_05_8k.htm`, `tests/fixtures/sec/photronics_2026_q2_10q.htm`.

Total: 426 tests (405 unit, 21 integration), all passing at the freeze.

---

## Configuration files

| File | Role |
|---|---|
| `pyproject.toml` | Package metadata, dependencies (see `README.md` §4), `black` line length 80, pytest `testpaths`. Declares the five packages for setuptools. |
| `pylintrc` | Google's `pylintrc`, unmodified. |
