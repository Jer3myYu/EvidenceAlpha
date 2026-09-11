# Stage artifacts, replay and debugging contract

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

## Record enough to reproduce an observable stage

Use a compact manifest plus files. JSONL events are sufficient; do not build a new tracing platform.

Suggested layout:
- `runs/<run-id>/manifest.json`: brief, code revision/dirty diff hash, prompt/settings versions, source set, parent/fork, statuses and artifact paths.
- `stages/<stage-id>/<attempt-id>/input.json`: exact assembled messages visible to the application or their referenced files, source IDs/versions, available tool definitions/capabilities, model, effort and limits.
- `events.jsonl`: observable SDK requests/results, tool arguments, tool outputs or content-addressed references, timestamps, errors and usage.
- `output.*`: raw returned content, parsed small control record if any, report/findings/artifact paths.
- `sources/`: originals, canonical extracted text and locators; immutable per source version.
- `reports/`: draft, revised report, final report, PDF, figures, figure inputs/code, and version hashes.

Never record credentials, environment dumps, auth caches or private hidden reasoning. Save provider-exposed reasoning summaries only if actually available and appropriate; do not promise access to internal chain of thought. Distinguish complete logs from portions hidden by the SDK. Compact console output points to full local artifacts; logs do not get pasted into every next model prompt.

Record the actual final model request inputs where observable, not merely a high-level description. Record SDK session IDs for faithful continuation; also store a portable stage input consisting of brief, selected notes, evidence refs and current draft so another model can run a controlled approximation.

## Four modes

1. Fixture replay: inject recorded outputs and tool events; no network/model calls. Test storage, stage transitions, version checks and rendering.
2. Original-provider stage rerun: freeze upstream files and rerun just the failing Claude/Codex stage. Continuation in the original session and fresh-session replay are distinct modes and must be labeled.
3. Surrogate stage experiment: run the same portable inputs with GPT-5.5 medium first. Label provider/tool differences. It can expose unclear prompts or inadequate evidence, but does not validate Claude SDK behavior, source acquisition or timing.
4. Live run: allow actual search/fetch and model work; record its source set and environment. Replay results never count as independent live research.

On replay, write a new attempt/run directory; never overwrite original evidence/results. Editing an upstream artifact invalidates reuse of downstream artifacts that consumed it. This is stage/file dependency tracking using hashes, not a semantic sentence graph. Resume verifies input hashes and records which stages were rerun or skipped. A cached reviewed report cannot silently attach to a changed draft or changed figure.

## Isolate tools as well as models

Fixed-evidence mode must enforce no external acquisition at the tool boundary. Disable built-in network search, restrict shell/network access through supported runtime settings, and serve retrieval from recorded material. A prompt saying 'do not browse' is insufficient. If enforcement is unavailable, label the run tool-restricted/best-effort rather than claiming guaranteed offline execution; do not count it as the fixed-evidence comparison.

Exact tool replay returns a recorded result only for matching tool/arguments/source version. An unmatched request produces an explicit replay miss, not fabricated evidence. A model may choose a different valid tool path: optionally allow local retrieval over the fixed corpus and label it fixed-corpus execution rather than exact trace replay.

## Usage accounting

Record queued, invoked, first-output and completed/cancelled times where available. Separate wall-clock duration from summed concurrent invocation time. Keep input/output/reasoning/cached tokens as distinct fields when reported. Missing fields remain unknown. Do not call subscription consumption a verified dollar amount. API-price estimates require explicit pricing provenance and must be separate from actual billed cost.

Record partial and failed attempts. Cancel child processes when a stage or campaign deadline expires. Do not report an interrupted run as free or remove it from comparison. Persist counters before starting a charged operation so resume cannot reset budgets.

## Debugging routine

Read the first concrete failure and the exact stage inputs/output, not the full run history. Classify: provider/auth, tool access, extraction, retrieval, prompt/input, output parsing, orchestration or rendering. Reproduce at the smallest layer, change one cause, rerun the affected stage and necessary descendants. Independent stable artifacts are reused.

If two repairs reproduce the same failure family without progress, pause that repair and write a concise representation/design diagnosis. One bounded GPT-5.5 peer check may help in Stage 2, within the shared isolated-attempt budget in 07; escalate that case to GPT-5.6 only if necessary; do not start an endless series of code-audit gates. Continue unrelated useful work when possible. Never patch the code to match an unverified reviewer assertion.

## Suggested compact interfaces

The implementer supplies working commands for:
- Run one stage from a saved input with a selected provider/model and fixed-corpus/live mode.
- Replay recorded outputs with zero model calls.
- Render an existing Markdown report and figure manifest without research.
- Inspect per-stage statuses/consumption without printing all logs.
- Resume interrupted work without re-running completed stages whose inputs match.

Use SDK continuation for the production lead where useful. Do not turn recordability into forced statelessness, excessive prompt duplication or a model call per bookkeeping operation.
