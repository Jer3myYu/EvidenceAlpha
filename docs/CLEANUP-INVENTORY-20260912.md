# Cleanup inventory — 2026-09-12

Read-only inventory following approval of the cleanup assessment. No files were
deleted or moved. Sizes are logical file bytes, not guaranteed disk reclamation.
Directory symlinks were not followed; virtual environments, model directories and
Git internals were excluded. This is a cache inventory, not a full disk audit.

## Regenerable candidates

Found 42 cache/build-name candidates totaling 7,599,080 bytes.
Names alone do not establish safe deletion; review ownership before removal.

| Local relative path | Bytes |
| --- | ---: |
| `tests/__pycache__` | 3,262,868 |
| `src/industry/__pycache__` | 913,650 |
| `worktrees/reviewer-contract-fix/src/evidencealpha/__pycache__` | 365,878 |
| `src/evidencealpha/__pycache__` | 365,354 |
| `worktrees/reviewer-contract-fix/tests/redesign/__pycache__` | 295,240 |
| `legacy/original/tests/unit/ingestion/parsing/__pycache__` | 272,955 |
| `worktrees/coherent-retrieval/tests/redesign/__pycache__` | 266,840 |
| `worktrees/coherent-retrieval/src/evidencealpha/__pycache__` | 247,787 |
| `tests/redesign/__pycache__` | 244,134 |
| `legacy/original/ingestion/parsing/__pycache__` | 151,079 |
| `src/research/__pycache__` | 138,076 |
| `.pytest_cache` | 133,545 |
| `legacy/original/tests/unit/ingestion/__pycache__` | 104,951 |
| `legacy/original/tests/unit/ingestion/parsing/conformance/__pycache__` | 90,327 |
| `legacy/original/tests/unit/ingestion/parsing/converters/__pycache__` | 81,528 |
| `legacy/original/tests/unit/ingestion/parsing/adapters/__pycache__` | 75,589 |
| `scripts/__pycache__` | 72,510 |
| `legacy/original/tests/unit/contracts/__pycache__` | 65,000 |
| `legacy/original/ingestion/parsing/adapters/__pycache__` | 60,442 |
| `legacy/original/tests/integration/__pycache__` | 57,720 |
| `legacy/original/ingestion/__pycache__` | 53,096 |
| `legacy/original/contracts/__pycache__` | 47,876 |
| `legacy/original/ingestion/parsing/converters/__pycache__` | 39,076 |
| `tmp/9-10-26/eval/__pycache__` | 36,414 |
| `data/redesign/report-production/__pycache__` | 25,994 |
| `data/redesign/existing-corpus-campaign-2/__pycache__` | 20,204 |
| `worktrees/coherent-retrieval/data/redesign/coherent-retrieval/integrated-company-20260912/__pycache__` | 16,476 |
| `tmp/9-7-26/c1/corpus/__pycache__` | 14,862 |
| `tmp/9-9-26/eval/__pycache__` | 12,733 |
| `src/rag/__pycache__` | 9,697 |
| `tmp/9-7-26/fixed/__pycache__` | 9,579 |
| `data/redesign/autonomous-corpus-eval/__pycache__` | 9,116 |
| `docs/redesign/focused/__pycache__` | 7,788 |
| `worktrees/coherent-retrieval/.pytest_cache` | 7,405 |
| `worktrees/company-stage-20260911/src/evidencealpha/__pycache__` | 6,299 |
| `worktrees/coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/observer/__pycache__` | 4,820 |
| `worktrees/reviewer-contract-fix/.pytest_cache` | 4,730 |
| `worktrees/coherent-retrieval/data/redesign/coherent-retrieval/preparation-correction-20260912/neural-1/observer/__pycache__` | 3,628 |
| `worktrees/coherent-retrieval/data/redesign/coherent-retrieval/preparation-correction-20260912/neural-3/observer/__pycache__` | 3,267 |
| `worktrees/research-quality-upgrade/src/evidencealpha/__pycache__` | 212 |
| `legacy/original/tests/unit/__pycache__` | 170 |
| `legacy/original/tests/__pycache__` | 165 |

## Retention decision

Keep source corpora, databases, frozen evaluations, closed ledgers, model files,
installed environments, historical failed runs and best-report evidence intact.
Keep unfinished work and migration backups/stash. Compatibility aliases still
serve environment and historical path dependencies.

Old preview PDFs/page images may be candidates for later deduplication, but have
not been proved redundant by this cache inventory. No historical artifact is
classified disposable merely because it is old. A deletion pass should use an
explicit reviewed path list, never blanket `git clean` or database cleanup.

The detailed local inventory is `.local/cleanup-inventory-20260912.json`.
