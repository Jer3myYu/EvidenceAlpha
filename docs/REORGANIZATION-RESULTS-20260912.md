# Folder consolidation completed — 2026-09-12

The approved [proposal](REORGANIZATION-PROPOSAL-20260912.md) is implemented locally.
`/home/cobot/cobot_storage/webproject/EvidenceAlpha` is now the canonical checkout
of **main**, containing the latest application code directly in `src/evidencealpha/`.
The source implementation remains unchanged from `dd7bb70`; this migration changes
layout, ignore rules, examples and current usage documentation. Nothing was pushed.

## Actual layout

All paths below are relative to the canonical project root unless stated otherwise.

| Checkout | Branch | Preserved starting commit / state |
|---|---|---|
| `.` | `main` | `dd7bb70`, plus this migration commit |
| `worktrees/coherent-retrieval/` | `coherent-retrieval-implementation` | `5607a21`; tracked files clean, historical untracked review retained |
| `worktrees/company-stage-20260911/` | `company-stage-timing-navigation` | `e80e141`, clean |
| `worktrees/reviewer-contract-fix/` | `reviewer-contract-fix` | `dd7bb70`, clean |
| `worktrees/research-quality-upgrade/` | `research-quality-upgrade` | `5715b5a`; all earlier unfinished edits restored |

The retrieval worktree also retains an untracked
`docs/redesign/coherent-retrieval/PATH_REVIEW.md` dated 04:04 UTC, before this
migration. Its bytes match the tracked main-branch copy. It was neither removed
nor automatically committed to the historical branch; its hash is in the local
receipt. The company-stage and reviewer worktrees are clean.

The three existing linked worktrees were relocated using `git worktree move`.
Git metadata remains in the primary `.git/`. They share repository history but
retain their own branch checkouts, indexes and local artifacts.

The old sibling names under `/home/cobot/cobot_storage/webproject/` are now
**symlinks**, not physical duplicate project directories:

- `EvidenceAlpha-coherent-retrieval` → `EvidenceAlpha/worktrees/coherent-retrieval`
- `EvidenceAlpha-company-stage-20260911` → `EvidenceAlpha/worktrees/company-stage-20260911`
- `EvidenceAlpha-fixed-corpus-integration` → `EvidenceAlpha/worktrees/reviewer-contract-fix`

Keep these compatibility aliases for now. Historical absolute links, virtual
environment scripts and saved execution descriptions still use them. No archived
configuration, report, ledger or source path string was rewritten to make an old
run appear newer.

## Preserved unfinished work and artifacts

The original root contained **10 modified tracked files and 29 untracked development
files**. All 39 were independently copied and hashed, then transferred with an
audited path-scoped stash and restored under `worktrees/research-quality-upgrade/`.
Their file hashes, working-tree patch and index patch match the pre-migration state.
The approved proposal was kept separately as a new main-branch document.

Recovery copies remain in `.local/reorganization-20260912/`, including
`before.json`, `wip-files/`, `working.patch`, `index.patch` and `pathspec.nul`.
The transfer stash is retained at commit
`930a3cd9fa6e1e00fd2c38727e323cbf20564586`; it was applied, not popped.
It contains only the audited development files, not `.env`, runtime data or caches.
No unfinished work was guessed to be obsolete or silently merged into main.

A before/after inventory verified **7,871 artifact files, 5,920,759,185 bytes**,
with **zero hash/symlink mismatches**. This covers existing data/legacy artifact
trees, including sources, model artifacts, reports and ledgers; installed virtual
environment libraries and cache directories were excluded from bulk hashing.
Their operational checks are recorded separately below. No database cleanup,
source deduplication, model download or historical ledger reopening occurred.

Detailed local verification records:

- `.local/reorganization-20260912/artifact-hashes-before.json`
- `.local/reorganization-20260912/artifact-verification.json`
- `.local/reorganization-20260912/environment-check.json`
- `.local/reorganization-20260912/path-check.json`
- `.local/reorganization-20260912/ignore-check.json`
- `.local/reorganization-20260912/receipt.json`

## Ignore rules and tracked fixtures

The parent checkout now ignores `/data/`, `/worktrees/`, `/runtime/`, `/.local/`,
`/tmp/` and `/test-results/`. Existing Python/build/coverage/cache protections
remain. `.env` variants are ignored, with sanitized `.env.example` and
`.env.*.example` templates explicitly allowed. Private local tool settings and
legacy database sidecars are also protected.

Test source and intentional fixtures remain tracked. The two tracked examples
moved, byte-for-byte, from `data/documents/` to `tests/fixtures/documents/`.
A preserved legacy database fixture contains an old sample-path reference, so
ignored symlinks at the two old sample locations retain compatibility. The
historical database fixture itself was not edited. There are now **zero tracked
files under data/** and **25 tracked test/fixture files**; no tracked Python
bytecode was found. No blanket test, JSON, Markdown or database ignore was added.

The parent rule excludes all nested worktree contents from main's staging and
ordinary repository searches. A linked checkout still has its own historical
`.gitignore` when used directly; changing all old branches' ignore files would
alter preserved checkouts and was deliberately not part of this migration.

## Current commands and useful links

Stable local links reuse the existing installations without moving files again:

- `runtime/environment` → installed isolated Python environment in the retrieval worktree.
- `runtime/reranker` → the existing pinned BGE model in that same preparation directory.
- `data/reports/latest-photomask` → the preserved best delivery under the reviewer worktree.

Best report: [PDF](../data/reports/latest-photomask/report.pdf),
[Markdown](../data/reports/latest-photomask/report.md),
[source map](../data/reports/latest-photomask/source-map.json).
These links work locally; the files are ignored and are not hosted by GitHub.

From the project root:

```bash
# Read-only CLI check
PYTHONPATH="$PWD/src" runtime/environment/bin/python -m evidencealpha --help

# Only for a separately authorized new live run; not executed by this migration
PYTHONPATH="$PWD/src" runtime/environment/bin/python -m evidencealpha fixed-corpus \
  --execution configs/photomask.fixed-corpus.example.json \
  --output data/redesign/new-photomask-run
```

The new example preserves the original brief, full five-source inventory,
essential scope and model/resource settings, uses relative corpus/model paths,
and explicitly disables external verification. Live generative provider calls
are still required for research: fixed-corpus means no external research-source
acquisition, not “no provider.” An explicitly authorized web-enabled run requires
a local configuration copy with `web_verification: true` and the `verify-report`
command. Old frozen execution configurations remain unchanged.

Always specify the current checkout's `PYTHONPATH`. An existing editable install
points to the canonical root; without an override it could select main's source
when operating inside an older checkout. Root `.venv` remains the development
interpreter with pytest; `runtime/environment` is the separate research environment.
Neither ignored environments nor model/corpus files are provisioned by cloning
this repository onto another machine.

## Verification actually completed

- Verified all five registered worktrees, preserved branches and explicit module
  import origins. No active application/provider/reranker workers were found.
- Normal CLI help runs using the relocated runtime link. Configuration resolves
  the existing corpus, model and local environment-file path from the root.
- Imported torch/transformers successfully without constructing a model or running
  inference. Versions remain torch **2.6.0+cpu**, transformers **4.57.6**, PyMuPDF
  **1.28.2**, fontTools **4.65.0**. The development environment reports pytest **9.1.1**.
- Read the installed GPT-6 reviewer catalog locally; no provider invocation.
- Opened one existing original source chunk read-only; verified the original brief
  and all essential scope fields are preserved in the new configuration.
- Checked 15 generated/private path examples and nine source/fixture/template
  exceptions with `git check-ignore --no-index`, plus the tracked-file inventory.
  Git cannot check descendants beyond a symlink, so the runtime symlink entry and
  a separate hypothetical runtime subtree were checked explicitly.
- Verified every inventoried artifact and all restored WIP file hashes. Existing
  reports remain reachable through both compatibility and canonical links.
- Reviewed the staged diff and whitespace; confirmed no application source or
  dependency specification changed. No broad tests, saved-stage orchestration,
  export, neural benchmark or successful research stage was repeated.

An initial environment inventory attempted to query pytest in the research
runtime; pytest belongs to the development environment. That diagnostic was
corrected without installing packages. Likewise, ignore verification was adjusted
to Git's symlink semantics. Neither required a runtime code change.

## Rollback and remaining caveats

The ignored migration backup and retained stash are local recovery aids, not a
remote backup of the approximately 5.9 GB inventoried artifacts. Keep them until
this layout is accepted in normal use. Do not delete a worktree just because its
branch is merged; it still contains valuable local artifacts and installations.

If a move must be reversed, stop active work, verify that each old path is the
expected compatibility symlink, unlink only that alias, and use `git worktree move`
to return the corresponding checkout. Do not recursively delete aliases, run
`git clean`, prune worktree registrations or restore dirty files over main.
Moving the old WIP back into the primary checkout would also require releasing
its branch and deliberately transferring its verified patch/untracked files;
the current nested WIP checkout is the safer default.

Physical moves and ignored runtime links are local state, recorded here and in
the local receipt; Git commits carry the ignore rules, relocated examples,
configuration and documentation. Historical results retain their original code,
paths, outcome and usage. This organization check is not a new live acceptance
or evidence of improved retrieval/report quality.
