# Cleanup map

Actual base: `3abe9692f3b5f3bbe20390a8d8971af994d3f07b`, branch `research-quality-upgrade`; starting tracked/untracked working tree was clean. Ignored source data, original documents and historical runs were preserved. No isolated worktree was needed.

| Previous path/dependency | Action and callers |
|---|---|
| `src/industry/` | Removed retired approval, coverage, quantity, reservation and graph workflow. Its callers were the old industry CLI, Studio and old industry tests; those callers are removed. |
| `src/research/` | Removed parallel reference workflow, CrewAI wrappers, persistence/checkpoint adapters and old tool loop. Replaced by shared new workflow/adapters/tools/artifacts. |
| `src/rag/` | Replaced text-only loading/chunking with immutable raw capture, structured locations and lexical retrieval. Optional local embeddings remain configurable; no paid embeddings. |
| `scripts/{agent,ask,ingest,query,workflow,industry_workflow}.py` | Removed superseded runtime entrypoints. The single packaged CLI is `python -m evidencealpha`. |
| `scripts/studio.py`, `studio.html` | Retired old Studio instead of leaving it pointed at obsolete code. Current run/report view is CLI. A new UI is deferred. |
| Old `tests/*.py` | Removed architecture-only tests and imports. Retained behavioral rationale in new tests: source fidelity, period mismatch, arithmetic, failed review/draft preservation, stale reuse, PDF omissions, cancellation and cumulative usage. Original tests remain recoverable in Git. |
| CrewAI, LangGraph, checkpoint SQLite, LangChain wrappers, unconditional embeddings, standalone Studio dependencies | Removed from declared active requirements. None occur in active imports. New rendering dependencies are declared explicitly. Existing venv not destructively purged; active dependency closure has no CrewAI. |
| `tmp/docs/meta/starting-prompt.md` | Original copied byte-for-byte to tracked `docs/archive/starting-prompt.md`; former location replaced with a short active pointer, not layered overrides. |
| Old docs navigation and C/S trackers | Original local copies in `tmp/docs/archive/`; active local README/upgrade-status/upgrade-ledger now mark the old campaigns retired and link to redesign. Root AGENTS/CLAUDE/README point only to current navigation. |
| `legacy/`, `data/`, historical `tmp/`, old database test fixtures, `docs/industry-research-brief.md` | Preserved as historical/user material, excluded from active test discovery. |
| Supplied `tmp/docs/redesign-package/` | Preserved untouched; copied to the canonical tracked `docs/redesign-package/` path required by the launch instructions. |

No permanent old/new selector or compatibility workflow remains. The historical PDF renderer's omission-detection and Chinese-font regression intent informed the new renderer; it is not imported. The new path has no C/S eligibility gates, per-sentence certification, semantic approval ledger or report-specific runtime conditions.

Checks: active import/settings/name searches; explicit dependency closure; `git diff --check`; Black/pylint; focused pytest; two-domain fixture exports and visual inspection. No source archives, historical run outputs, credential files or unrelated edits were staged.
