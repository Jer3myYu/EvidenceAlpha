# EvidenceAlpha — Design Documents

**Updated:** 2026-09-03

Design docs are organized by **level of abstraction**, from the whole system down to a single component. A lower level may refine the level above it; it may never contradict it. Where two docs disagree, the higher level wins and the lower-level doc gets corrected. Precedence comes from the level, not from the file number.

| # | Document | Level | Owns |
|---|---|---|---|
| — | [Clean-Slate Implementation Design](./clean-slate-implementation-design.md) | System | **Implementation design of record since 2026-09-02.** Rewrite policy, phase roadmap, Phase 1 standalone-RAG scope and decisions. Supersedes 01 for all new work; 01–05 now describe the frozen `legacy/` system. Unnumbered by the user's instruction. |
| — | [Handoff — Phases 1–5](./handoff-phase1-5.md) | System | Fresh-session handoff at the Phase 1–5 checkpoint (2026-09-02): architecture, runtime flow, files, decisions, limitations, tests, next phase. Unnumbered by the user's instruction. |
| — | [Handoff — Phase 6 to 7](./handoff-phase6-to-7.md) | System | Fresh-session handoff at the Phase 6 checkpoint (2026-09-02): commits, current workflow, where state lives, files, Phase 6 decisions, rough edges, and the Phase 7 brief with its batch-questions-then-autonomous process. Unnumbered by the user's instruction. |
| — | [Handoff — Phase 7 to 8](./handoff-phase7-to-8.md) | System | Fresh-session handoff at the Phase 7 checkpoint (2026-09-02): status and commits, current workflow and commands, persistence behaviour, files to inspect first, binding decisions, known limitations, the Phase 8 (independent verification) brief, and the default phase process. Superseded for current work by the Phase 8 to 9 handoff. Unnumbered by the user's instruction. |
| — | [Handoff — Phase 8 to 9](./handoff-phase8-to-9.md) | System | Fresh-session handoff at the Phase 8 checkpoint (2026-09-03): status and commits, graph, state fields, persistence, verification, modules, tests, binding decisions, known limitations, the Phase 9 (multi-agent / CrewAI) brief with its caution and questions, files to inspect first, and the default phase process. Superseded for current work by the Phase 9 to 10 handoff. Unnumbered by the user's instruction. |
| — | [Handoff — Phase 9 to 10](./handoff-phase9-to-10.md) | System | Fresh-session handoff at the Phase 9 checkpoint (2026-09-03): status and commits, the unchanged graph with the CrewAI role layer, environment, state, persistence, modules, commands, tests, binding decisions, known limitations, the absence of a Phase 10 brief, files to inspect first, and the default phase process. Unnumbered by the user's instruction. |
| — | [Handoff — Phase 10](./handoff-phase10.md) | System | Fresh-session handoff for Phase 10 (industry research system, 2026-09-07): what exists, commands, the workflow, compatibility and rollback, evaluation and review pointers, deferred work. Unnumbered by the user's instruction. |
| 01 | [System MVP Plan](./01-system-mvp-plan.md) | System | Scope, key decisions, agent/tool boundary, repository structure, module responsibilities. **Legacy spec** (superseded 2026-09-02; describes `legacy/original/`). |
| 02 | [RAG Architecture and Interfaces](./02-rag-architecture.md) | Subsystem | Ingestion, retrieval, evidence verification, storage boundaries, tool and API contracts, error model. |
| 03 | [Multi-Format Parser Architecture](./03-parser-architecture.md) | Component | Format detection, parser adapters, the normalized `ParsedDocument` contract, quality gate. Sits inside 02's ingestion pipeline. |
| 04 | [Chunker, Embedder, and Indexer](./04-chunking-embedding-indexing.md) | Component | The post-parser ingestion stages: `DocumentChunk` contract, section-aware chunking policy, pinned local embedding model, Chroma indexing and chunk retirement. Sits inside 02's ingestion pipeline, downstream of 03. |
| 05 | [Retrieval Architecture](./05-retrieval-architecture.md) | Component | The query half of 02's RAG subsystem: the `storage/vector_store.py` Chroma seam, filter normalization, dense candidate retrieval and v0 dedupe, the `EvidenceChunk` view, and retrieval diagnostics. Reads what 04 writes. |

`meta/` holds project rules rather than design: [starting-prompt.md](./meta/starting-prompt.md) is the standing brief every session reads first.

## Naming

- Filenames are `NN-short-name.md` — a two-digit number, then two to four lowercase words joined by hyphens. No spaces, underscores, capitals, dates, `v2`, `final`, or `(1)` copies.
- The name describes the **subject**, not the status or the level: `04-evaluation-harness.md`, never `04-rag-doc-updated.md`.
- **`NN` is a permanent ID, assigned in creation order** — not a level code and not a reading order. Today's numbers line up with the levels by coincidence; the next document takes `04` whatever level it sits at.
- Level lives in the `**Level:**` header line and in this table, which is grouped by level. That is what you read to see the hierarchy — never renumber files to make `ls` sort prettily. Numbers that never move are numbers that never break a link.
- Retired numbers are never reused.
- Every doc opens with an H1 title followed by `**Level:**`, `**Status:**`, `**Updated:**`, and `**Related design:**` links where they exist.

## Adding a document

1. Take the next free `NN`.
2. Write the header block, declaring the level — 1 system, 2 subsystem, 3 component. If the level is unclear, it is one step below whichever document it most refines.
3. Add a row to the table above, in that level's group.
4. Check it upward against the higher-level docs. A lower level may refine a higher one, never contradict it — if it must, amend the higher doc in the same change or log it under **Open reconciliations**.

A note in `tmp/<m-d-yy>/` keeps its free-form name while it is scratch. It gets a number, a header block, and an index row at the moment it is promoted into this folder — not before.

## Renaming

- Rename only for a real reason: the subject or scope changed, or the existing name is wrong or malformed. Not for taste, and not in passing while doing something else.
- **Keep the number.** Only the `short-name` part changes.
- A rename is not finished until all three are true:
  1. `grep -rn "<old-filename>" /home/cobot/cobot_storage/webproject/EvidenceAlpha/tmp` returns nothing;
  2. this index's row and link are updated;
  3. `meta/starting-prompt.md` is updated if it names the file.
- `tmp/` is gitignored, so there is no `git mv` and no history to fall back on. That grep is the entire safety net — run it, every time.
- If a document's **level** changes, edit its `**Level:**` line and move its row in the table. The filename does not change.

## Retiring a document

- Do not delete. Set `**Status:** Superseded by NN-<name>.md` (or `Retired <date>`), reduce the body to a pointer if it is now noise, and move its row to a **Superseded** table at the bottom of this file.
- Its number stays consumed.

## Open reconciliations

Known points where the documents do not yet agree. Resolve deliberately — do not paper over them in passing.

- **Adapter native shape (resolved 2026-08-15):** 03 §5.1 required the converter version in the
  *planned* manifest, which must be computable before parsing, but §3.5's capability list had no
  field naming the shape — so it could only be discovered from the output. `native_shape` is now a
  declared capability in 03 §3.5.
- **Planned manifest scope (resolved 2026-08-15):** the planned manifest describes **every
  registered attempt** on a route, primary and fallback alike, each with its own converter version.
  Registering or swapping a fallback therefore changes `parse_id`. 03 §5.1 states why this does not
  conflict with keeping *which* attempt ran in the observed half.
- **SEC CIK had no home (resolved 2026-08-15):** 03 §7.3 required filing identity to include CIK
  while §5.2's `business_metadata` had no such field. `cik` added to §5.2 — optional on the model,
  required by the gate for filings, normalized to a zero-padded ten-digit string.
- **Locator tier ambiguities (resolved 2026-08-15):** 03 §5.5 listed `slide` in both tier 1 and
  tier 2; it is tier 1. `heading_path` alone is tier 2. A page-blind adapter is kept off the PDF
  route by `page_fidelity`, not by the tier — 03 §3.6 now says so.
- **Encrypted-document error code (resolved 2026-08-15):** 03 §8.1 promised encrypted files "their
  own code" while 02 §15's shared enum had none. `ENCRYPTED_DOCUMENT` added to 02 §15
  (`retryable: false`, parser-side `retry_with: different_source`).
- **Repository structure (resolved 2026-08-15):** 01 §7/§8 were amended to give the parser an `ingestion/parsing/` package and to add a neutral top-level `contracts/` layer that both `ingestion/` and `retrieval/` may import. 02 §17 and 03 §12 now agree with 01. No `config/` directory: parser route bindings live in `ingestion/parsing/registry.py`.
- **Parser boundary (resolved 2026-08-15):** 03 previously placed `SourceAcquirer` inside the parser, contradicting 02 §4.5. The parser is now network-free and starts from an `AcquiredArtifact`; acquisition belongs to the ingestion service. 02 §9.3 states the guarantee.
- **Parse identity (resolved 2026-08-15):** chunk IDs derive from `parse_id`, not `version_id` — 02 §13 and 03 §5.1 are updated together.
- **Parser network rule (revised 2026-08-15):** "no network access" was replaced by "no content-derived fetch, plus a declared allowlisted endpoint," so hosted parsers stay usable. Stated in 03 §1.0/§3.7 and mirrored in 02 §9.3/§16 — if these two ever drift, 02 wins.
- **SEC adapter choice (resolved 2026-08-15):** the EdgarTools offline spike passed on extraction but its document model carries no source-DOM anchors, so it cannot meet 03 §3.5's per-block tier-1 minimum; the in-house lxml adapter (`sec_html_lxml`) is primary and the route is single-adapter (03 §4.1). EdgarTools remains the planned acquisition/search client.
- **SEC full-submission wrapper (resolved 2026-08-15):** `sec_submission_text` is detected and named with no route; splitting the SGML container belongs to the ingestion service (03 §2, §18).
- **PDF route minimum (resolved 2026-08-15):** the PyMuPDF table spike produced real cell grids on the golden filing; `table_fidelity ≥ grid` stands (03 §3.5, §14 step 6).
- **PDF → OCR hand-off, MVP half (resolved 2026-08-15):** a scanned PDF is refused by the PDF route with a typed `UnsupportedContent` mapped to `UNSUPPORTED_FORMAT` naming `scanned_pdf`, without spending the fallback (03 §4.3); the step-9 re-dispatch design remains open.
- **Chunk contract home (resolved 2026-08-15):** 04 puts `DocumentChunk` in a new `contracts/chunk.py` — retrieval filters on it, so it belongs to the neutral layer; 01 §7/§8 amended in the same change.
- **Codex review of 04 (applied 2026-08-15):** chunk IDs now include the chunking signature (02 §13 amended); `Indexer.delete_document_version` → `retire_superseded` (02 §9.5 amended); query embedding moved behind `contracts/embedding.py` so retrieval never imports ingestion (01 §7/§8 amended); chunk budget cut to fit multilingual-e5-base's 512-token window (01 §2 amended); heading blocks carry the *exclusive* `heading_path` per 03 §5.3 — the SEC adapter was brought to the shared converters' convention (adapter 1.1) and conformance asserts it.
- **Doc 04 implementation deviations (applied 2026-08-16):** implementing the chunker forced
  three refinements, written into 04 rather than left silent: (1) rule 6 outranks rule 5's
  atomicity — a block that cannot fit beside its opening heading is split even when under
  budget alone, so headings attach forward instead of becoming heading-only chunks; (2) any
  oversized non-table block (list, code, image text), not only a paragraph, splits by the
  `paragraph_span` mechanism, with word boundaries as a last resort — atomicity may never
  break the 512-token window guarantee; (3) `table_rows` segment indices are absolute grid
  row indices, and `chunk_id` is stored as `chk_` + 16 hex like block IDs. Also recorded in
  04 §13: the golden fixture's tables parse with `header_rows = 0`, so header-line
  repetition is pinned by unit tests, and dense-only retrieval ranks statement-table
  segments below prose — the known 02 Phase 4 gap.
- **Chroma access seam (resolved 2026-08-16):** 02 §9.5 ("only the indexer imports Chroma")
  and 01 §8 ("retrieval never imports ingestion") could not both hold once retrieval queries
  the index. Doc 05 §2 resolves it with `storage/vector_store.py` — the storage layer, which
  both sides may import, becomes the only chromadb import; the indexer owns writes, the
  retriever owns reads. 01 §7/§8, 02 §9.5, and 04 §5 are amended by 05 §11; the already-
  implemented indexer is refactored onto the seam when 05 is implemented.
- **Codex review of 05 (applied 2026-08-16):** 15 findings, all folded into 05 (see its §12):
  `score` is query-relative and absent on ID lookups (Chroma `get()` has no distances); the
  read-side seam preflights store existence because `PersistentClient` creates directories;
  chunk-level vs collection-level signature errors stay distinct (`EMBEDDING_FAILED` vs
  `RETRIEVAL_UNAVAILABLE`); `to_where` respects chromadb 1.5.9's `$and` arity; date filters
  always warn about excluding undated records; dedupe drops are recorded, not just counted;
  final ordering is fully deterministic; rehydration defaults cover omitted-when-empty
  metadata; a derived `source_title` satisfies 01 §10's visible-title floor; `authority`
  filtering stays at the tool layer until Phase 2 (02 §12 amended).
- **Python version (revised 2026-08-15):** the docs no longer pin an interpreter. `pyproject.toml` declares `requires-python = ">=3.11,<3.13"` and the environment is built with any available supported version; 3.12 is a project preference, not an architectural requirement. This supersedes the entry below.
- **Python version:** all three docs say 3.11+; the machine's default `python3` is 3.10.12, with 3.12 also installed. The environment therefore has to be built on `python3.12` — see `meta/starting-prompt.md` §7.
