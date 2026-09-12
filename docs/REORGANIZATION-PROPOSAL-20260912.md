# EvidenceAlpha folder reorganization proposal

**Status: proposal only, for your review.** No files have been moved, ignore rules changed, worktrees switched, environments modified or historical records rewritten for this proposal.

## 1. What these folders actually are

They are **four checkouts of one Git repository**, created as Git worktrees so implementation and evaluations could run in isolation. They share the Git history and branch references stored in `EvidenceAlpha/.git`, but each has its own checked-out files and local artifacts.

| Current folder under `/home/cobot/cobot_storage/webproject/` | Current branch / commit | Why it exists | Approximate disk usage |
|---|---|---|---|
| `EvidenceAlpha/` | `research-quality-upgrade` / `5715b5a` | Original repository and Git metadata owner; also holds shared corpus, local configuration and unfinished earlier changes | 3.9 GB |
| `EvidenceAlpha-coherent-retrieval/` | `coherent-retrieval-implementation` / `5607a21` | Isolated retrieval implementation/evaluation; contains the installed reranker and its environment | 3.8 GB |
| `EvidenceAlpha-company-stage-20260911/` | `company-stage-timing-navigation` / `e80e141` | Preserved evaluated company-stage baseline | 7.6 MB |
| `EvidenceAlpha-fixed-corpus-integration/` | `main` / `dd7bb70` | Latest integrated workflow, reviewer and report-presentation code; contains the delivered report and recent run artifacts | 2.3 GB |

These sizes include local data/environments and are not a deduplicated storage estimate.

**The confusing part today:** the folder called `EvidenceAlpha` is not currently checked out on `main`. The latest main code is in the integration worktree. The original folder has ten modified tracked files plus untracked documents/tests. We must preserve that work before changing its branch.

## 2. Recommended destination

Make `EvidenceAlpha/` the normal project users open, with the latest `main` code directly in `src/`. Put the other checkouts under an ignored `worktrees/` directory. Keep their history and artifacts; do not flatten or copy their source trees over the main source tree.

```text
EvidenceAlpha/                       # canonical checkout of main
├── .git/                            # shared Git metadata; never manually move
├── src/evidencealpha/               # current application code
├── tests/                           # tracked test code and intentional fixtures
├── docs/                            # tracked design, usage and handoff documents
├── configs/                         # future portable, non-secret examples
├── pyproject.toml
├── README.md
├── AGENTS.md
├── .gitignore
├── .env                             # ignored local secrets
├── .env.example                     # tracked, sanitized example
├── .venv/                           # ignored development environment
├── data/                            # ignored corpus, databases, runs and reports
├── runtime/                         # ignored stable links to model/environment
├── .local/                          # ignored migration backup, local config/cache
├── tmp/                             # ignored scratch files
└── worktrees/                       # ignored by the parent checkout
    ├── coherent-retrieval/          # existing retrieval worktree and artifacts
    ├── company-stage-20260911/      # preserved e80e141 baseline
    ├── reviewer-contract-fix/       # existing integration checkout and artifacts
    └── research-quality-upgrade/   # earlier unfinished work from original root
```

`configs/` is for genuinely reusable examples as they are added; this migration should not move every historical execution configuration there. Closed-run configurations remain historical evidence at their original relative locations.

The extra worktrees remain useful for history and isolation. They are not additional production applications. Their existence inside the parent folder does not make their files part of the parent Git commit; `/worktrees/` will be ignored. Each linked checkout still has its own Git index and ignore rules.

### Physical move map

| Existing directory | Proposed directory |
|---|---|
| `EvidenceAlpha-coherent-retrieval` | `EvidenceAlpha/worktrees/coherent-retrieval` |
| `EvidenceAlpha-company-stage-20260911` | `EvidenceAlpha/worktrees/company-stage-20260911` |
| `EvidenceAlpha-fixed-corpus-integration` | `EvidenceAlpha/worktrees/reviewer-contract-fix` |

Use **`git worktree move`**, not a file-manager rename or an ordinary recursive copy. The primary `EvidenceAlpha` directory remains in place. No branch history is deleted or rewritten.

## 3. What `.gitignore` should and should not do

Ignore runtime data, downloaded models, private settings, environments, generated test results and caches. **Do not ignore test source code or all fixtures.** Those are part of the reproducible implementation. Ignoring `tests/`, `test_*.py`, all JSON, all PDFs or all Markdown would hide useful project assets and future changes.

The current ignore file already covers Python caches, environments, coverage output, logs and several named data directories. However, it does not ignore the entire root `data/`, nested worktrees or `.env` variants. It contains obsolete, narrowly scoped data rules. There are two tracked sample documents under `data/documents/` and two tracked SQLite test fixtures; these need explicit treatment.

Proposed project-specific rules, alongside a concise Python/build/cache section:

```gitignore
# Local runtime artifacts and alternate checkouts
/data/
/worktrees/
/runtime/
/.local/
/tmp/

# Python environments, caches and generated build/test output
.venv/
venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
.nox/
.cache/
build/
dist/
*.egg-info/
.coverage
.coverage.*
htmlcov/
coverage.xml
/test-results/
*.log

# Private environment variants; keep sanitized templates versioned
.env
.env.*
!.env.example
!.env.*.example
```

Retain any other still-applicable protections, including private tool configuration. Put future runtime databases under `data/`; do not add a blanket database rule that obscures intentional fixture updates. If a model/cache tool currently writes somewhere else inside the repository, either configure it to use an ignored runtime directory or add a precise rule after inventorying it. Do not change account-wide caches just to reorganize this project.

Move the two small tracked examples, `data/documents/acme_risks.md` and `acme_robotics.txt`, to `tests/fixtures/documents/` with `git mv` and update any references. Retain the existing database fixtures until their usage is assessed; deleting tests or fixtures is not part of folder cleanup. The inspection found no tracked Python bytecode or runtime log files; the tracked databases are fixture files.

**Important:** ignore rules do not stop tracking files already committed, and ignored files are not backups. Inventory tracked artifacts before applying rules. Any actual runtime artifact that needs untracking should be removed only from the Git index, with its local bytes preserved and its history left intact. Never use a blanket `git rm --cached` across the project.

## 4. Dependencies and path compatibility

The normal run configuration currently points to:

- The shared production corpus under `EvidenceAlpha/data/redesign/focused-diagnostic/frozen/corpus`.
- The model and isolated Python environment under `EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/`.
- Saved reports, traces and recovery descriptors under the integration worktree.

There is also an editable installation in the integration checkout whose `.pth` points to **`EvidenceAlpha/src`**. This is why the documented command explicitly uses `PYTHONPATH=src`. Moving folders without checking import origins could execute the wrong checkout’s code.

Plan:

1. Preserve historical artifacts and relative directory structures inside each moved worktree. Do not merge similarly named `data/` trees, deduplicate sources, clean databases or rewrite closed ledgers.
2. Use stable ignored `runtime/` links for the installed reranker and interpreter where helpful; reuse existing model files. Do not assume a moved virtual environment is portable: entry-point shebangs, activation scripts and editable paths can contain absolute paths.
3. Update **active** commands/configuration to the new paths, with explicit source-code import paths. Verify `evidencealpha.__file__`, interpreter identity and installed versions from the intended checkout.
4. Preserve frozen configurations byte-for-byte. Add an old-to-new path map and a migration receipt. Future recovery should use a new descriptor referencing the relocated files and their unchanged hashes.
5. For the first migration, keep temporary sibling symlinks from the three old names to the new nested directories. Physical projects/data are then inside `EvidenceAlpha`; the old names are compatibility aliases only. This keeps old environment prefixes and historical absolute links usable while dependencies are verified. Removing those aliases can be a later explicit cleanup after checking every remaining dependency.

Avoid leaving symlinks inside a worktree that resolve back to an ancestor and cause recursive scans. Search, packaging and backup commands should exclude `worktrees/`, environments and generated data unless those are deliberately being inventoried. No dependency install, model download or live model evaluation is needed merely to approve this proposal; any environment repair during implementation must be justified by a concrete failed check.

## 5. Safe implementation order after approval

1. **Freeze and inventory:** confirm branches, clean/dirty states, available disk space and inactive workers. Save a manifest of paths, Git heads, original corpus/model/report hashes and closed-ledger hashes. Preserve an independent copy of the dirty root’s patch and untracked work; do not log secret contents or accidentally include `.env` in a stash/commit.
2. **Preserve unfinished root work:** prepare an audited, scoped temporary stash or equivalent transfer of tracked/untracked development files. Release `main` from the integration checkout by switching that clean worktree back to `reviewer-contract-fix`. Switch the primary root to `main`, then create the nested `research-quality-upgrade` worktree and restore its unfinished changes there. Keep the transfer backup until verification succeeds. Do not force checkout, hard reset or silently overwrite colliding untracked files.
3. **Apply ignore rules first:** exclude the new nested runtime/worktree locations before creating them. Relocate the two tracked example documents and update applicable references. Preserve historical docs rather than reorganizing the whole history tree in this pass.
4. **Move the three linked worktrees:** use Git’s registered move operation, retaining their branches, commits, environments and data. Add the temporary compatibility aliases and check Git metadata from both parent and child checkouts.
5. **Repair active paths only:** point the normal command at the canonical checkout and explicit installed environment/model. Keep shared corpus location unchanged. Add one top-level usage section linking to the best report and the worktree/path map.
6. **Verify, record and commit:** perform the bounded checks below; save one migration receipt and commit the actual reorganization changes. Remote push is a separate action, not implied by this proposal. If blocked, roll back using the path map and retained transfer backup rather than deleting data or restarting research.

Do not create the WIP archive by guessing which old edits were superseded. Its purpose is to preserve all unfinished work for later comparison, not silently merge it into `main`.

## 6. Acceptance checks

- `EvidenceAlpha/` is checked out on current `main`; `src/evidencealpha/` matches the intended committed implementation.
- All four alternate worktrees are registered at their nested paths; the earlier dirty branch retains its edits and untracked work. No sibling physical project copies remain; any temporary sibling paths are documented symlinks.
- Every preserved source/model/report/closed-ledger hash matches; no historical run has been reopened.
- `git check-ignore` covers representative generated data, model/cache files, environments, `.env` variants, Python caches and test outputs. `git ls-files` still includes test source, intentional fixtures and sanitized examples. Neither check is treated as a substitute for the other.
- From the canonical root, the explicit environment imports the current module and the normal CLI help/configuration resolves. Run only focused deterministic path/config checks and, if needed, a small saved-output export; no provider calls, neural inference, retrieval benchmark or successful research rerun.
- The current report and sources remain reachable, and old environment entry points are either verified usable through compatibility aliases or explicitly excluded in favor of the verified command.
- The only committed differences are the reviewed ignore rules, sample-file relocation/reference updates, current usage/path documentation and any necessary small path-resolution fixes. The migration receipt lists local-only moves separately.

## Recommendation

Approve a **conservative consolidation**: canonical `main` at `EvidenceAlpha/`, alternate worktrees under `EvidenceAlpha/worktrees/`, ignored runtime data, and versioned test code/fixtures. Keep old artifact layouts and temporary compatibility links initially. This gives us one obvious main project without sacrificing the evidence, installations or unfinished work that the current workflow depends on.
