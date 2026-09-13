# Workflow Studio update plan

Status: overall scope approved; refined with topic/answer and RAG observability
requirements. No Studio implementation or live execution in this design update.
Inspected 2026-09-12 at main `560662e`, with uncommitted documentation/diagram
changes preserved. This plan describes new functionality, not an existing UI.

## Product purpose

A local visual workspace for following an industry report from brief to delivery.
An investor should see what the system learned, what supports the conclusions,
what remains uncertain and whether review improved the report. A developer should
be able to inspect the actual requests, retrieval, handoffs and failure point.
The normal command remains the execution authority; Studio must not implement a
second scheduler, reviewer or evidence assembly path.

Use the new architecture/workflow PNGs as visual language: navy headings, blue
orchestration, green research/source operations, lavender model stages and subtle
bordered side panels. The interactive graph uses HTML/SVG so nodes remain clickable
and accessible; the PNGs are explanatory reference images, not live state.

## What exists and what must change

The former Studio is recoverable at commit
`3abe9692f3b5f3bbe20390a8d8971af994d3f07b`, in `scripts/studio.py` and
`scripts/studio.html`. Read-only inspection found live execution, checkpoint replay,
node/tool inspection and reconstructed prompt views. It imports retired
`industry`/`research` modules, LangGraph, CrewAI framing and SQLite thread history.
None of those is the current runtime. Do not restore its backend or dependencies.
Reuse interaction ideas and visual concepts only.

Current entry points are `cli.py` → `execution.run()` → `workflow.run()`.
Current artifacts include frozen execution/corpus settings, manifests, per-stage
requests and outputs, source versions, selection manifests, ledgers and report
exports. The inspected saved `presentation-live-20260912/continued-2` run contains
plan, two researchers, follow-up, synthesis, review, revision and recheck. It is a
recovered historical execution, not a fresh Studio test.

## Proposed workspace

```text
Run selector / brief title       Live | recovery | replay       Last update
Execution    Coverage    Review readiness    Export             Usage / Stop
┌──────────────────┬────────────────────────────┬───────────────────────┐
│ Runs & sources   │ Clickable workflow         │ Selected stage        │
│ Brief & settings│ or report / evidence view  │ Inputs / outputs      │
│ Report versions │                            │ Tools / timing / error│
└──────────────────┴────────────────────────────┴───────────────────────┘
Overview | Workflow | Evidence | Review & corrections | Report | Diagnostics
```

Default to concise, reader-facing summaries. Exact JSON, prompts and technical
traces belong in expandable diagnostic views. Show status using text/icons as well
as color. Fit a laptop display, allow panel resizing, and support keyboard node
selection. Chinese report text must remain readable. Do not stream repetitive
raw logs into the main workspace.

## Functionality proposed for approval

| View | What the user can see and do | Truthfulness requirement |
| --- | --- | --- |
| Run library | List configured local runs, brief, date, code version, mode, four outcomes; open prior runs and compare report versions. | Deduplicate worktree aliases; historical schema gaps show unavailable, not success. No recursive scan of every ignored directory. |
| Brief and launch | Edit brief, required scope, source inventory, cutoff, explicit web toggle and model/execution settings; inspect resolved configuration and launch a new run. | No seeded answers or silent reuse. Show model availability/capacity checks, new output path and actual hard limits before launch. |
| Workflow canvas | Plan → industry/company research → optional gap follow-up → handoff → synthesis → review → conditional correction/recheck → export. Click any stage. | Populate actual planned tasks and stage IDs; do not invent executed stages from the static diagram. Indicate planned, running, completed, failed, skipped, reused and unknown distinctly. |
| Stage inspector | Assigned questions, expected deliverables, actual input/output, model request/response identity, elapsed time, source-tool calls and failure cause. | Separate saved request text from UI summaries; never reconstruct a prompt and label it exact. Actual model can be unreported. |
| Plan and coverage | Map brief requirements to dispatched tasks, notes, support and outstanding gaps; compare initial and follow-up coverage. | Model-assigned coverage is provisional. A retrieval miss does not prove non-disclosure. Unmapped requirements remain visible. |
| Retrieval inspector | Query → candidates → ranked results → returned reading blocks; open original and surrounding text. Show initialization, scoring and preparation timing separately when recorded. | Distinguish candidate support from returned/writing support. Missing observations stay unknown; no invented relevance score or new inference on view. |
| Evidence explorer | Source title, issuer, URL, dates, period, version, page/chunk; original text next to cited report passage; source-to-research-to-writing lineage. | Preserve original wording, units and status qualifiers. Exact lineage only where recorded; unresolved references show unavailable. Separate corpus and web-captured evidence. |
| Handoff inspector | Compare research originals with selected writing/revision context; show omitted references/reasons, full request-size estimates and capacity. | Do not infer that every retrieved passage reached writing. Distinguish conservative estimates from measured provider tokens/limits. |
| Review and corrections | Five rubric cards with explanations; examined scope, limitations, material issues, source objections, route, revision and recheck resolution. | No numerical aggregate or exhaustive certification. Supplemental findings carry their declared origin. Unknown/unexamined scope cannot become verified. |
| Report workspace | Markdown/HTML view, embedded PDF, sourced charts, source mapping; click citations; compare draft/revised/best preserved reports. | Link assessment to the report hash/version. Later presentation edits are not automatically reviewed. Best existing report is not overwritten by the latest candidate. |
| Execution diagnostics | Overall deadline, admitted calls, usage, current operation, request capacity, reranker resources, watchdog/error and checkpoint origin. | Separate hard stops from scheduling guidance; unknown token usage is unknown. No speculative progress percentage or guaranteed ETA. |
| Saved-run playback | Step/play through recorded stage and tool events without model calls; jump to failures and corrections. | Label artifact playback. Do not manufacture missing events/timestamps or call it live evaluation. |

Coverage should use a compact requirement matrix; evidence lineage should use a
selected-claim/source path, not an unreadable graph of every passage. Review issues
should be cards or a table with route and resolution. Report comparison should
highlight changed passages and citations without claiming semantic correctness
from a text diff. Render-inspection status is available only if actually recorded;
merely opening a PDF is not an inspection result.

## Controls and execution semantics

Proposed controls: Open run, New run, Start, Stop, View checkpoint compatibility,
Continue eligible active attempt, Recover into a new run, Play saved history,
Compare reports and Download artifacts. These actions must be clearly separated.

- Viewing, source opening and playback are read-only and never call models.
- Start uses the existing normal command, frozen configuration and a unique output
  directory. Explicit web mode selects `verify-report`; offline mode selects
  `fixed-corpus`. Secrets stay in the configured environment, not browser storage.
- One Studio-owned command process is admitted at a time. Its configured provider
  and local worker limits remain authoritative. Warn about detected external runs;
  do not claim a global lock against unrelated CLI processes unless implemented.
- Stop requests cancellation of the owned process group, allows ledger/artifact
  settlement, and confirms worker exit. Force termination after bounded cleanup
  must be shown as interrupted/uncertain if accounting was not settled. Closing a
  tab must not start another run or silently kill ongoing work.
- Refresh/reconnect shows the same process and ledger. Never relaunch on reconnect.
- Continue is enabled only for an eligible active ledger/checkpoint under current
  normal-path rules. Closed ledgers are never reopened. Recovery creates an additive
  run and shows reused stages, provenance, compatibility checks and new usage.
- No arbitrary stage rerun or “rerun everything” shortcut in the initial UI.
  Fixture replay is separate from charged recovery. Do not add pause semantics
  unsupported by providers or promise a model can resume mid-invocation.
- Re-export targets a new candidate directory/version; it cannot overwrite a
  historically reviewed report or silently transfer its review decision.

## Implementation approach

Use a small loopback-only local server plus packaged HTML/CSS/JavaScript assets,
with no separate frontend service, cloud account, database migration or new
orchestration framework. Suggested CLI:

```bash
# Proposed command; not implemented yet.
PYTHONPATH="$PWD/src" runtime/environment/bin/python -m evidencealpha studio \
  --runs-root data/redesign --port 8765
```

Suggested files: `src/evidencealpha/studio.py` for HTTP/lifecycle integration,
`src/evidencealpha/studio_artifacts.py` for read-only artifact projection, and
`src/evidencealpha/static/studio/` for the UI. Package assets in `pyproject.toml`.
Use existing dependencies where suitable; select a minimal server implementation
based on concrete streaming/cancellation requirements rather than restoring the
old Starlette/LangGraph stack wholesale.

An initial request loads a compact run snapshot; periodic incremental polling
reads atomically completed artifacts. Lazy-load large originals/traces instead of
embedding the corpus in each response. Polling can show new recorded tool/stage
results, but does not imply token streaming. Add a small observer callback only
if necessary for a concrete active-operation gap. Observers may report events;
they must not change routing, payload selection, admission or quality decisions.
Unknown ordering/timing in old artifacts stays unknown.

Serve only explicitly registered run/source roots with path containment checks.
Do not expose the repository, `.env`, auth caches or arbitrary filesystem paths.
Use loopback binding, origin checks and a local session token for mutating actions;
launch/stop use POST, never a GET/EventSource URL. Render source HTML and model
content safely, prevent script execution and isolate report previews. Links to
external sources open separately; passive previews must not fetch remote content
in fixed-corpus mode. No cleanup/delete/upload/indexing interface in this scope.

## Artifact integration and observed gaps

| Existing evidence | Studio use | Required integration |
| --- | --- | --- |
| `execution-freeze.json`, `corpus-freeze.json` | Code/settings/model resolution and source inventory | Redacted display projection; distinguish recorded versus current capacity. |
| `manifest.json`, `command-result.json` | Stage list and separate execution/coverage/review/export states | Running state can lag in-call activity; combine ledger and latest complete artifacts, display last update. |
| `execution-ledger.json` | Admitted attempts, invocation usage, limits and failures | No duplicate accounting; aggregate linked runs once by identity, label unknown historical totals. |
| `stages/**/input.json`, `output.json`, `output.md` | Tasks and outputs | Do not assume fixed researcher count or role from ordinal names; use saved task/role. |
| Per-call `request.txt`, `settings.json`, `context.json`, `limits.json`, failure records | Exact saved request, capacity, model/operation diagnosis | Lazy-load; hide credentials and sanitize unsafe content without altering stored originals. |
| Stage retrieval traces, `writing-context.json`, selection manifests, `handoff.json` | Retrieval layers and evidence preservation | Derive lineage only from IDs/versions and saved selection records; do not infer unavailable quality grades. |
| Manifest coverage, review/recheck scopes, unresolved and supplemental findings | Requirement/issue routing and actual decision | Scope is often narrative, not exhaustive structured checks. Show narrative faithfully; do not synthesize a certification grid. |
| `reports/`, source map, figures, render records; selected local delivery bundles | Report preview, comparison and downloads | Older curated deliveries may live outside normal reports paths; explicit registration and provenance, not guessed “latest” symlinks. |

The existing function `review.route()` supplies correction actions. Studio displays
those decisions, it does not reroute based on its own interpretation. A completed
run with failed export remains different from a failed run with a useful draft.
The UI must show both useful artifacts and the failure without changing either.

## Implementation order and focused validation

1. Build read-only run projection and navigation against the preserved recovered
   report plus one failure artifact. Confirm unsupported historical formats fail
   clearly, without modifying them.
2. Implement workflow, stage inspector, coverage/evidence and rubric/correction
   views. Verify a saved follow-up/revision/recheck chain and one omitted-support
   example; keep all observations labelled historical.
3. Add report preview, source links and version comparison; verify safe rendering,
   usable Chinese text and precise source/version selection.
4. Wire launch/stop/recovery to the normal command. Use an injected subprocess or
   deterministic fixture for admission, reconnect, cancellation and failure tests.
   Confirm view/playback cannot invoke a provider and closed ledgers remain intact.
5. Perform one offline browser walkthrough on saved artifacts, including a narrow
   viewport and keyboard navigation. No live research or benchmark is needed for
   UI acceptance; any later live demonstration needs its own authorization.

Acceptance: the user can inspect the brief and assigned tasks, follow evidence
into the actual writer request, see the five rubric assessments and correction
outcomes, open the matching report/source versions, and understand why a run is
ready, partial or failed. CLI and Studio use the same execution path and outcomes.
A failed run and recovery must remain distinguishable from uninterrupted success.

## Scope boundary and review decision

This proposal includes an operational local Studio, not just a static architecture
page. It does not include collaborative accounts, remote hosting, drag-and-drop
workflow editing, arbitrary agent creation, corpus cleanup, automatic source
acquisition, exhaustive claim certification or a new research engine.

The user approved the overall scope and authorized necessary instrumentation.
The refinement below is part of that approved scope, not another approval gate.
It adds topic/reference fields to existing contracts where needed; it does not
change factual acceptance, historical results or execution budgets.


## Approved refinement: make the system understandable from the inside

The Studio must answer six linked questions: What was asked? How was it broken
into topics? Who investigated each topic? What did they answer and leave open?
What originals support those answers? How did the answers and corrections change
the delivered report? A stage diagram and a log viewer alone do not meet this goal.

### Planning and topic-to-answer view

Show an expandable tree: **brief → topics/subquestions → assigned task → researcher
answer → supporting originals → report section**. Selecting a topic filters the
research, retrieval and review panels without losing its original wording.

Each topic card presents its question, brief requirement links, priority and
expected deliverable. Each dispatched task shows role and all assigned topic IDs.
Show planner output alongside dispatched input, with any actual changes or rejected
allocation. Do not imply one company, question or topic requires its own invocation.
One researcher task can contain several questions and return several answers.

Each researcher answer card presents the actual answer/explanation, citations,
remaining uncertainty and follow-up result. Preserve the initial partial answer;
recovery adds a linked answer revision rather than rewriting history. Provide a
full-notes tab so structured cards do not hide context. Unanswered topics stay
visible even when a researcher returns successful prose.

Current limitation: `prompts/plan.md` and `protocol.py` expose tasks primarily as
`role` and `question`; research scope records supply explanations/references, but
not a reliable fine-grained topic-to-answer mapping. Do not manufacture this mapping
from historical prose and label it recorded.

For new runs, extend the existing planner/research protocol minimally:

- Plan output: topic definitions with local stable ID, question, optional parent,
  requirement IDs, priority and expected deliverable; task entries reference IDs.
- Dispatched inputs retain those IDs and all questions. Validate references and
  show explicit unassigned requirements; structural validation cannot certify
  semantic completeness.
- Research output: answer entries keyed by topic ID with answer text, status,
  evidence references and remaining gap. Extend existing scope/coverage records
  where semantics match rather than creating a competing coverage model.
- Store substantive answer text once in the canonical output. Full notes are a
  deterministic rendering of structured answers plus shared analysis, not another
  model-written duplicate. If section references are used instead, bind them to
  the exact content hash/version and reject dangling references.
- Follow-up/revision records reference original topic/issue IDs. Many-to-many links
  are valid: one original can support several answers; one answer can use several
  sources. Never hardcode this familiar report's topics into runtime logic.

These fields are produced in existing role invocations. No extra decomposition,
summary or explanation model calls are needed just to populate Studio. Existing
records display their full saved task/notes with “topic mapping not recorded.”

### RAG subsystem A: source preparation and storage

Provide a nested workflow canvas reachable from both Sources and the main graph:

```text
Authorized file / explicitly captured URL
    → preserve original bytes and content hash
    → parse pages, paragraphs, headings and tables
    → canonical text + structural blocks + exact chunk spans
    → versioned file-backed SourceStore
        ├─ source identity, parser/chunker versions, warnings
        ├─ optional generated navigation context (separate)
        └─ reusable in-memory reading indexes when needed
```

Click each step to compare the original page/document, extracted text, block and
chunk boundaries, and stored metadata. Show source identity, origin, publication
versus acquisition dates, parser version, chunk settings, hash and parse failures.
Rejected/failed extraction must still point to the retained original bytes.

**Database terminology:** today's active `SourceStore.ingest()` writes
`original.<suffix>`, `text.txt` and `source.json` under a source-version directory.
It records a lexical index descriptor; lexical candidates are scored from original
passages, not a persisted vector index. There is no current Chroma embedding-write
step or SQLite research-state transaction to animate. Label the view **Source
store (file-backed)**, with physical paths in diagnostics. Historical databases
remain preserved and outside the new runtime path. This upgrade does not add a
vector database to satisfy a visual expectation.

Fixed-corpus runs generally reuse/copy a prepared corpus: show preparation as
“prepared previously / imported,” not live ingestion. Future source preparation
observations must distinguish captured, parsed, stored, reused and failed. An
existing source file does not prove that each preparation step's timing was saved.

### What is the generated source summary?

A dedicated source tab shows **Original | Structure/chunks | Generated context |
Provenance**. The optional `context.json` contains generated navigation text about
subject, reporting period and section structure, plus covered block IDs, model,
prompt version, cache key and `evidence: false`.

Current workflow contextualization is conditional and bounded to selected sources
and a prefix of original text. It is not automatically a full-source summary, nor
necessarily produced before the researchers run. Display the actual recorded
coverage and execution order. If the exact supplied prefix is not reconstructible
from recorded block IDs, show that limitation and link the context-stage input.
Do not represent “no context.json” as an error or generate missing summaries on open.

For new observations, retain the exact input span references/input hash and whether
input was partial in the existing context record, rather than copying its text
into a separate Studio file. Show actual model as unreported where appropriate.
Generated context accompanies passage metadata and currently participates in
lexical matching (`retrieval.candidates` combines original text and generated
context). Neural reranking uses original structural reading context. Generated
context remains navigation, not evidence; Studio must expose its role in matching.

### RAG subsystem B: retrieval, reading and evidence settlement

```text
Topic-linked researcher/reviewer query + source scope
    → lexical candidate matching on originals
    → structural reading windows around candidate anchors
    → local contextual reranking (or explicitly degraded lexical mode)
    → ranked selection + overlap deduplication
    → returned reading blocks and original locators
    → StageContext evidence settlement
    → payload-bounded writing/review selection
    → answer/report citations

Direct original / page / surrounding / continuation opens
    → original reading context → StageContext (no neural scoring)
```

The canvas expands a real tool call. Show query, topic ID when supplied, scope,
candidate count, lexical rank/score, neural rank/score, actual returned blocks and
selection/omission reasons when recorded. A side-by-side reader highlights the
candidate anchor inside its structural context; click through to the original.
Show repeat/cache behavior without labeling every repeated query unnecessary.

Separate preparation, initialization, scoring, structural reading and handoff
measurements. Show cache hits, sampled RSS, worker outcomes and cancellation.
A score is not a probability or assessor relevance grade. Candidate inclusion,
returned context completeness and writing selection are separate observations.
The source text is already in the source store; a search saves result references,
observations and settled evidence, not a new independent source document for each
hit. Current artifacts do include repeated payload text for audit/recovery; do not
claim existing storage is perfectly deduplicated.

### One canonical stage record, multiple views

“One stage save serves multiple functions” is the design rule: the workflow,
research cards, diagnostics, playback and evidence views project from the same
stage artifacts. It does not require one enormous JSON file. Separate immutable
originals, exact request snapshots and append-only events have different jobs.

| Canonical owner | Stored once for this purpose | Reused by Studio |
| --- | --- | --- |
| Plan/stage output | Topic definitions, task assignment, answer content and reference IDs | Plan tree, answer cards, coverage, report lineage |
| SourceStore | Original bytes/text and source-version metadata | Source reader, RAG views, citations, all stages |
| StageContext and selection manifests | Settled evidence state, gaps, selected/omitted reference sets | Handoff, coverage, recovery, writing inspection |
| Existing stage event stream and retrieval trace | Operation IDs, transitions, timings, score/reference observations | Live activity, retrieval details, playback, diagnosis |
| Exact request/response artifacts | Actual per-invocation payload and provider output | Capacity inspection and reproducibility |
| Ledger | Admissions, usage and overall accounting | Every usage display; no Studio budget counters |
| Review/output manifest | Rubric, issues, routes, resolutions and artifact hashes | Review board, report readiness and comparison |

Add a compact schema-versioned stage descriptor/reference in the existing manifest
only for missing joins: run/stage/attempt/task/topic/operation IDs, upstream refs,
artifact paths/hashes and event sequence. Do not copy answers, source text, full
configuration or usage into it. UI indexes are disposable in-memory projections;
no mandatory Studio database or separate full event stream.

Existing `events.jsonl` already records provider/tool results. Reuse it. Add only
missing start/finish/failure/cancel observations and subsystem timings at their
actual boundaries in `workflow.py`, `documents.py`, `retrieval.py` and
`preparation.py`/`reranking.py` as needed. Common operation IDs join these records.
A long operation needs a small start event before completion so Studio can say
“reranking running,” not just “research running.” Do not infer this from silence.
Use monotonic durations and recorded timestamps; avoid double-counting nested time.

New events should reference existing results rather than embed a second copy of
every passage. Save references only after the target artifact is durable; keep
incomplete/failed operations visible. Never rewrite historical records to the new
schema. Keep exact model requests and self-contained recovery evidence where
required: removing these to reduce bytes would undermine the product. Broader
storage deduplication/migration is outside this Studio change.

Observability must not alter ranking, context selection, routing or acceptance.
No additional model call on UI navigation, no hidden reasoning reconstruction,
and no claim that recorded tool actions reveal private model deliberation. Explain
module purpose from maintained static descriptions; explain a particular run from
its recorded inputs, decisions and outputs.

### Revised implementation acceptance

Add these focused checks to the previously approved implementation order:

1. One fixture task contains several topics; another shares a source. All assigned
   questions have visible answers or explicit unresolved state, and follow-up
   retains topic identity. No separate call per topic is introduced.
2. A saved historical run without topic IDs remains readable but explicitly lacks
   fine-grained mapping. No background model enrichment or historical mutation.
3. One small deterministic ingest/retrieve fixture demonstrates original → parsed
   block → candidate → returned block → writing reference. Inject scorer outputs;
   no broad benchmark, downloads or neural inference for UI validation.
4. Context absent, partial and present are distinct; direct opens bypass scoring;
   source reuse is not shown as new parsing. Failure/cancellation has a terminal
   observation or an explicit interrupted/unknown label.
5. All views resolve the same answer/source IDs. Refresh/playback only reads;
   duplicate display events do not duplicate usage or original storage. New probes
   preserve unchanged candidate identities, source spans and handoff content in
   the focused fixture.

This makes Studio an observable view of the real system, from topic decomposition
through RAG and correction to delivery, without building a parallel workflow.


### Chroma research follow-on

[Chroma integration research](CHROMA-RESEARCH.md) recommends a local dense candidate
index alongside lexical retrieval. This is a proposed retrieval extension, not
implemented behavior. The current-state RAG canvases above remain accurate; if
this extension is adopted, Studio must show both candidate branches, their merge,
index version/readiness and verified source resolution. It must not animate a
Chroma query for historical runs that never executed one.
