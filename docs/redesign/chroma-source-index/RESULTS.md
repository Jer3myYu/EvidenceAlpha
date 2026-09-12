# Chroma source-index experiment: results and handoff

Branch: `chroma-source-index`, isolated worktree
`/home/cobot/cobot_storage/webproject/EvidenceAlpha/worktrees/chroma-source-index`.
Base main: `560662e`. See [design and research](DESIGN.md).

## Implemented and tried

- Optional Chroma 1.1.1 reference index: vectors and immutable chunk metadata,
  no copied document text. Explicit supplied embeddings, no default embedder.
- New-directory build, complete coverage validation and atomic ready manifest.
  Exact corpus metadata, signature, stored vector/metadata digest and version
  checks prevent accidental reuse of incompatible or incomplete indexes.
- Scoped vector queries resolve original SourceStore text and spans before use.
- Equal-weight rank fusion retains lexical/dense ranks and distances. The existing
  Retriever accepts an injected candidate provider, then uses the same structural
  windows and reranker path. Default lexical behavior is unchanged.
- Source tools group returned originals normally; StageContext settles them and
  selects them for writing without losing text, source identity or span bindings.

This is a working storage/query prototype, **not a production-enabled hybrid
fixed-corpus command**. Live settings, actual embedding generation and supervision
remain outside this experiment. No historical database was opened or modified.
Main's uncommitted documentation/PNG changes remain untouched.

## Actual validation

Four focused new checks passed across retained attempts:

| Check | Saved result |
| --- | --- |
| Real Chroma build/reopen/filter/query → normal Retriever → source tools → StageContext → writing selection | `data/trial-06.log`; `data/chroma-trial-06/test_persistent_trial_and_norm0/TRIAL.json` |
| Incomplete index, mismatched signature and modified vector rejection | Passed in `data/trial-02.log` |
| Invalid scope/dimension and changed-original rejection | Passed in `data/trial-02.log` |
| Default versus explicitly selected lexical candidate equivalence; cancellation check propagation | Passed in `data/trial-04.log` |

A separate fresh Python process reopened the final persisted index and queried it:
`data/FRESH-PROCESS.json`. Six indexed chunk records contain no document text in
Chroma. The three-source fixture uses hand-assigned vectors and an injected scorer;
zero lexical candidates for the trial query ensure dense nomination is actually
exercised. This is deliberately artificial and **does not demonstrate semantic
understanding, Chinese retrieval quality or embedding-model performance**.

A targeted preexisting test,
`test_contextual_candidates_and_returned_blocks_are_distinct`, fails at its final
assertion after `engine.close()`: it expects an invalid-source exception, whereas
the cancelled retriever returns cancellation handling first. It failed identically
on unchanged main `560662e`, saved in `data/baseline-check-01.log`. Its preceding
candidate/reading assertions pass. No unrelated behavior or historical test was
changed to obtain a green result.

Failed trial observations are retained:

- 01: missing `data/` parent prevented pytest fixture startup; no index created.
- 02: trial passed raw retrieval output directly to StageContext, bypassing the
  existing source-tool grouping contract. Changed the trial to use EvidenceTools.
- 03: storage-to-settlement trial passed; existing closed-retriever assertion failed.
- 04/05: writing comparison initially required identical ordering/metadata. Inspection
  showed the existing selector sorts originals and compacts redundant chunk locator
  `basis`/`bbox` fields. Final checks compare exact text, source/version/URL, passage
  spans and nested chunk start/end/page bindings. No runtime preservation checks
  were weakened. Copied-state diagnosis is in `data/selection-diagnosis/`.
- 06: affected writing preservation check passed. Successful negative checks were
  reused, not repeatedly run. No full pipeline or retrieval benchmark was executed.

Black, focused pylint and whitespace checks were run on changed Python files.
Installed development environment: Python 3.12; Chroma 1.1.1; pytest 9.1.1;
Black 26.5.1; pylint 4.0.8. No dependency installation or model download. Chroma
telemetry is disabled. Tests use 120-second outer supervisors; fresh-process check
uses 60 seconds. All invoked processes are allowed to exit before delivery.

## Reproduce the bounded experiment

From the worktree, use the existing development environment with explicit imports.
Choose a **new nonexistent** basetemp: pytest deletes a reused basetemp directory.
The example refuses reuse to preserve prior evidence.

```bash
cd /home/cobot/cobot_storage/webproject/EvidenceAlpha/worktrees/chroma-source-index
mkdir -p data
trial_path="data/chroma-trial-$(date -u +%Y%m%dT%H%M%SZ)"
if test -e "$trial_path"; then
  echo "Refusing to reuse trial directory" >&2
  exit 1
fi
PYTHONPATH="$PWD/src" timeout 120 \
  /home/cobot/cobot_storage/webproject/EvidenceAlpha/.venv/bin/python -m pytest \
  tests/redesign/test_vector_index.py --basetemp="$trial_path" -q
```

On another machine, the optional dependency is `.[vector-index]`; the exact
experiment pin is Chroma 1.1.1. This is not a claim that it is the newest release.
Do not point this prototype at existing historical Chroma databases.

## Limits and next decision

The reusable pattern is demonstrated: search vector references, resolve originals,
retain context and share the resulting evidence across existing consumers.
Semantic benefit is untested. No generative or neural calls were made.

Before enabling a live hybrid command: select and verify a local embedding model,
handle input capacity without truncation, supervise synchronous index/model work,
freeze index settings in normal execution and compare candidate recall, returned
relevance, context completeness and resource costs separately. Full index scans
are acceptable for this tiny trial, not proven for large corpora. Current prototype
assumes a single owner and immutable admitted index; it does not provide concurrent
index-update transactions, online incremental indexing or deployed server operation.
The embedding signature describes caller-supplied vectors, not independently proven
model provenance. Equal RRF weights/constant 60 are provisional, not tuned results.

Keep the active evaluated path and frozen 9-pass/7-partial benchmark unchanged
until a separately recorded quality/resource assessment supports promotion.
