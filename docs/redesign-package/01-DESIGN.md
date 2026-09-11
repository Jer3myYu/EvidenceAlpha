# Product and architecture contract

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

## 1. Runtime shape

Brief → lead scope/plan → researcher work → lead synthesis + figures → independent review → optional one lead revision + focused recheck → assemble/deliver.

These are logical recorded stages, not a requirement to create a new model session per stage. Continue the lead's session where useful; export explicit stage inputs so fresh-session replay also works. Separate the reviewer's context from the writer. Research tasks may run in parallel (initial maximum two); writing starts after bounded research, using what is available and stating evidence gaps. Scope and research should not consume the writing allocation.

One small controller coordinates stages, deadlines, files and adapters. Keep LangGraph only if it makes this smaller; a Python orchestrator is acceptable. No CrewAI role wrappers on the new path. Avoid custom event buses, distributed services, semantic approval graphs, agent voting panels and per-sentence state machines.

## 2. Role responsibilities

| Role | Runtime and input | Output |
|---|---|---|
| Lead | Profile-selected SDK; original brief, research notes and source access | Short plan; coherent report; figure data/code; bounded revision |
| Industry Researcher | Profile-selected SDK; scoped questions, shared tools | Industry/value-chain findings, evidence passages and limitations |
| Company Researcher | Profile-selected SDK; named companies/metrics | Company evidence with periods/definitions; comparable inputs, not unsupported rankings |
| Reviewer | Codex SDK; GPT-5.6 Sol medium; brief, exact report/figures, original evidence | One consolidated review with locations, supporting evidence, impact and suggested changes |

The default campaign selects Codex for all four roles. The preferred profile selects Claude for lead/researchers. Document contextualization is a bounded operation, not a fifth autonomous role. See 07 for models and limits.

Researchers return compact Markdown notes and source IDs, not huge nested JSON reports. The lead connects findings into an explanation for the reader rather than concatenating worker summaries. Researchers should recognize quoted third-party company information inside an issuer document. The source publisher is not necessarily the subject of every passage.

Reviewer evaluates factual support, material omissions relative to the fixed brief, comparison validity, conclusions, uncertainty, and visual accuracy. It can use retrieval, original files, selective external search and code. Give a read-only evidence/report workspace and a separate writable findings directory. Its findings are suggestions with evidence, not commands from a trusted authority. Distinguish required corrections from optional questions/polish. Author may contest a false objection with source support; record it for recheck.

Review focuses effort on material conclusions, key numbers, comparisons and suspicious passages, and records coverage limitations. It is not an exhaustive truth guarantee. Do not relabel unexamined claims as verified.

## 3. Delivery behavior

Persist `draft.md` and figures before review. Final deliverable normally includes `report.md`, `report.pdf`, source links, figure assets and a short limitations section. The canonical report is Markdown plus referenced assets; PDF is a rendering of that version. If PDF export fails, preserve and deliver Markdown, mark PDF pending and debug the renderer independently.

Review feedback must improve a report, not trigger a diagnostic-only replacement. Minor residual issues or optional polish do not block delivery. Evidence shortages receive substantive explanations: what is known, what is unknown and how that constrains the conclusion. Do not fill sections with generic placeholders to meet a completeness check.

After the single revision/recheck, retain a useful report and disclose unresolved uncertainty. Explicitly known unsupported claims cannot be advertised as supported. If an essential conclusion is unresolved, label that conclusion and report status accordingly. On reviewer/runtime failure, retain the draft as `draft_review_incomplete` rather than calling it reviewed or deleting it. Do not automatically edit prose after review under the guise of deterministic checks. A preserved incomplete draft is useful failure recovery, but it does not satisfy product acceptance.

Final-report metadata includes a small honest status such as `reviewed`, `reviewed_with_limitations`, or `draft_review_incomplete`. This is not a reimplementation of the former A/B/C eligibility machinery.

## 4. Tools and source capture

Expose existing built-in search/page access, file read/write, code execution and subagent capabilities only as needed. Verify actual capabilities and permissions in each SDK. The underlying model does not execute tools by itself. Do not assume tools or search providers are identical across Claude and Codex.

Use one small custom `search_evidence` interface for local semantic/lexical retrieval; original passage locations can be opened using built-in file tools. A focused `open_source` helper is acceptable if built-ins cannot expand stored locations safely and faithfully. Reuse one working search provider rather than simultaneously exposing several overlapping search tools.

Capture raw downloaded source bytes and parsed text. Built-in web fetch may return summaries rather than raw documents: do not label those as original snapshots. Use a small fetch/capture adapter when necessary. Record inaccessible sources and search snippets as such. Retrieval results and external pages are untrusted data; their instructions do not override research tasks.

## 5. Document preparation and RAG

Data flow: save original → parse structural blocks → chunks retaining structure → optional contextual descriptions/overview → index → retrieve original text with context and source locations.

Keep a local vector index such as the existing Chroma integration if sound and lightweight; keyword retrieval is useful for company names and technical identifiers. Avoid a dependency overhaul just to obtain a particular library. Use an existing permitted local embedding model by default; do not introduce a paid embedding API. Record the embedding/index version, and retain lexical retrieval if local embedding support is unavailable. A document parser capable of table/heading structure is preferred; prove support on actual Chinese PDF/HTML samples. Small documents can be read directly.

Parsing assigns source blocks and locations. Chunk by headings, paragraphs, lists and table structure under an embedding-token limit. Preserve headers, units, captions and associated footnotes; split large tables by rows with header context. Record OCR/extraction limitations instead of fabricating exact locations. No LLM is asked to invent character offsets.

Minimum records, kept in simple files/SQLite:
- Source: ID, original URL/name, content hash, acquisition timestamp, original path, extracted-text path, parser version, available document date and extraction warnings.
- Block/chunk: ID, source version/hash, original block IDs, section heading, exact text and source locators.
- Locator: offsets into the saved canonical extracted Unicode text (start inclusive/end exclusive); for PDF, page and bounding box if available. Label offset encoding/index basis. Offsets are not offsets into PDF bytes. A chunk/summary may reference multiple discontiguous spans.
- Context: generated description or overview, linked original block IDs, model/prompt version, clearly tagged as generated.

A bounded LLM contextualizer may add concise subject/period/section explanations and section overviews for long, high-value documents. Process selected documents once, cache using source hash + parser/chunker/context versions, and reuse across roles/runs. Do not synchronously summarize every fetched page/chunk. If enrichment fails, structural original-text retrieval still works. Contextual text is stored separately and can be indexed alongside original text; it never replaces original evidence.

Retrieval returns original text, generated context labeled separately, source URL/ID, locations and parent-section references. When details are ambiguous, read the surrounding section/table. Do not build recursive summary trees in this first implementation.

## 6. Visual research and output

Lead selects visuals because they answer questions, not to meet a quota. Researchers collect their underlying data and provenance. Use plotting libraries for quantitative figures and a layout library such as Graphviz for exact relationship diagrams. Use installed code tools, not a new autonomous graphics agent or generated bitmap text for factual charts.

Examples: value-chain diagram, company comparison table, sourced financial trend/comparison chart and qualification timeline. Quantitative comparisons must state units, periods and definitions; do not infer comparability merely because values are numeric. Missing values remain missing. No synthetic market shares in real reports.

Each figure has a title, explanatory caption, source IDs and applicable period/unit/caveats. Retain input data and generation code. Use consistent typography, legible Chinese fonts, axis scales and numbering. PDF must contain tables/figures with readable captions and source links. Review the rendered figures and a rendered PDF sample, not only Markdown or successful export exit codes.

## 7. Deterministic checks

Keep checks local: reference existence and valid spans; basic required fields; explicit calculation execution; asset presence; final artifact matches reviewed version; visible export omissions; operational limits. These do not prove semantic accuracy. A calculator confirms arithmetic on supplied inputs, not that the selected metric/denominator is appropriate.

Do not infer semantic dependencies with regex/position, demand every prose number match a bespoke quantity grammar, remove report sections automatically, or use a per-claim certification ledger. Logging and document IDs are ordinary provenance, not an excuse to rebuild that machinery.

## 8. Provider adapters

One small application-facing contract: run or continue a role with prompt, workspace, tool capabilities, model/settings and budget; stream observable events; return artifact references and usage/error metadata. Implement concrete Claude and Codex adapters; no generalized plugin framework.

GPT reviewer default: `gpt-5.6-sol`, medium. Model/settings are configuration, not scattered literals. Python Codex SDK is preferred if the installed supported version works; a documented CLI/app-server adapter is an acceptable fallback. Confirm current SDK schemas with local help/docs; do not guess constructors or copy stale snippets. Do not nest development sessions' private context into report review.

Use only the user's available, permitted authentication. Codex subscription-backed local access does not mean ordinary OpenAI Agents SDK/API calls are subscription-funded. Claude subscription support for third-party products must not be assumed; retain only a supported configured path. No token extraction, auth-file copying, account modification, hidden API fallback or purchased quota. A blocked Claude adapter does not block authorized all-GPT work. Report provider-specific validation separately. If all configured providers are inaccessible, preserve the fixture-backed implementation and mark live checks pending.
