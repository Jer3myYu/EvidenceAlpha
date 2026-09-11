# Active code map

Only `src/evidencealpha/` is packaged. Start with this map, HANDOFF and package 07/04; archived code, audit logs and old trackers are excluded from default reading.

| Path | Responsibility |
|---|---|
| `src/evidencealpha/config.py` | Validated shared settings, two profiles, model IDs, effort, execution ceilings. Rehearsal fallback is an explicit config override. |
| `src/evidencealpha/cli.py`, `__main__.py` | `run`, `resume`, `replay-stage`, `render`, `show-run`; one-case Stage 2 driver, explicit admission and outer wall-clock alarm. |
| `src/evidencealpha/workflow.py` | Portable stage runner, tool rounds, optional specialist workers, bounded review/revision/recheck, source/draft hashes, identifying source passages and delivery. |
| `src/evidencealpha/providers.py` | Injectable provider contract, deterministic fixtures, Codex CLI, Claude SDK subprocess adapter, process-group termination and normalized metadata. |
| `src/evidencealpha/protocol.py` | Strict shared output envelope; allowed tool shapes and final-round response constraint. |
| `src/evidencealpha/claude_runner.py` | Official SDK process boundary; tool-free model messages, current supported login, selected model/effort. |
| `src/evidencealpha/tool_runner.py` | One metered external acquisition in a cancellable process group; shares the worker deadline, makes no model calls. |
| `src/evidencealpha/documents.py` | Original-byte capture, HTML/digital-PDF structural parsing, Unicode spans, lexical retrieval, optional local-only embeddings, generated-context cache. |
| `src/evidencealpha/tools.py` | Shared retrieval/open-source, arithmetic, one Tavily search provider and metered raw HTTP capture. Fixed-corpus dispatch rejects external tools. |
| `src/evidencealpha/artifacts.py` | Atomic files, exact trace matching, source/file hashes, code revision/dirty metadata, path containment. |
| `src/evidencealpha/budget.py` | Locked cumulative admissions and invocation reservations; unknown tokens remain unknown. |
| `src/evidencealpha/render.py` | Matplotlib/Graphviz assets, retained figure inputs/generators, Chinese-capable Markdown/PDF export, bounded figure layout, wrapped source hashes in tables and text read-back. |
| `src/evidencealpha/prompts/` | Common protocol and role instructions; no report-specific company names. Contextualization is a bounded operation. |
| `tests/redesign/` | Focused evidence, workflow, budget, failure recovery and process cancellation regression checks. |
| `tests/fixtures/redesign/` | Explicitly synthetic manufacturing and service source/output packs. |
| `docs/redesign/inputs/`, `cases/` | Portable inputs and JSON cases for isolated Stage 2 work. Original full-report case remains unready; stage2-prefixed cases record actual rehearsal readiness and bounded integration attempts. |

`pyproject.toml` owns dependencies; `constraints.txt` records the installed active closure, and `VERSIONS.json` records runtimes. Old packages may still exist in the preserved virtual environment but are not active dependency requirements.

`data/redesign/` contains local run artifacts and a compact, existing-source PDF corpus. These paths are ignored by Git and preserved in this checkout. Reports retain a mode/validation label independent of review status. The previous Studio is retired; CLI inspection is the current run/report view.

Stage 2 outcome and current navigation: `COMPLETION.md`, `NEXT_SESSION.md`,
`STAGE2_RESULTS.json`. `documents.py` now caches validated sources and optional
embedding indexes, builds passages per source, and preserves CRLF spans.
`workflow.py` shares one absolute research deadline across active/queued workers.
`RUNTIME_NOTES.md` records the measured CLI-loop decision, separate permission checks and remaining runtime limitations.
