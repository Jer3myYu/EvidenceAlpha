# EvidenceAlpha

One source-grounded research workflow: lead planning → optional industry/company research → synthesis and sourced figures → independent review → at most one revision/recheck → Markdown/PDF. Fixture output validates software plumbing, not research quality.

## Project layout and current local setup

Open `/home/cobot/cobot_storage/webproject/EvidenceAlpha` for the canonical
`main` checkout. Application code lives in `src/evidencealpha/`; tests and
intentional fixtures remain versioned under `tests/`. Alternate Git checkouts
are under ignored `worktrees/`. Generated data, environments, local settings,
model files and test outputs are ignored; they are preserved locally, not
included in Git backups.

The existing isolated runtime and pinned model are available through
`runtime/environment` and `runtime/reranker`. Use an explicit import path so an
editable installation cannot accidentally select another checkout's source:

```bash
# Run from the canonical project root; help does not call a provider.
PYTHONPATH="$PWD/src" runtime/environment/bin/python -m evidencealpha --help

# For an explicitly authorized new research run, use a new output directory.
PYTHONPATH="$PWD/src" runtime/environment/bin/python -m evidencealpha fixed-corpus \
  --execution configs/photomask.fixed-corpus.example.json \
  --output data/redesign/new-photomask-run
```

The example reuses the original brief and corpus, with no historical answers or
stage imports. It is offline with respect to research-source acquisition; a live
research run still calls the configured generative provider. No run is launched
by folder reorganization. Corpus/model paths resolve relative to the configuration
file; the local `.env` path resolves from the project root. Secrets are never part
of the example. To enable authorized online verification, make a local copy under
`.local/`, explicitly set `web_verification: true`, and use `verify-report`.

Development checks use `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest`;
pytest is not installed in the separate research runtime. On another machine,
provision an authorized environment/model and adjust local paths; these ignored
links and data are not created by cloning the repository.

Latest preserved report: [Chinese PDF](data/reports/latest-photomask/report.pdf),
[Markdown](data/reports/latest-photomask/report.md),
[source mapping](data/reports/latest-photomask/source-map.json).
These are local artifact links; GitHub does not host the ignored report files.
See the [reorganization receipt](docs/REORGANIZATION-RESULTS-20260912.md) for the
worktree map, compatibility aliases, preservation checks and rollback information.
The [delivery handoff](docs/redesign/presentation-live-20260912/HANDOFF.md) records
the actual reviewed report, usage and remaining limitations.

Use Python 3.11/3.12 in `.venv`. Install with `.venv/bin/pip install -e '.[dev]'`; Graphviz `dot` is required for relationship diagrams. Local reranking uses `.[retrieval]` and an explicitly supplied local model. Downloads and provider calls require execution authorization; degraded lexical mode must be selected explicitly.

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m evidencealpha --help
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest
PYTHONPATH="$PWD/src" .venv/bin/python -m evidencealpha run --fixture tests/fixtures/redesign/manufacturing.json --output data/redesign/example
PYTHONPATH="$PWD/src" .venv/bin/python -m evidencealpha show-run data/redesign/example
```

New runs need a new output directory. `resume`, `replay-stage` and `render` operate on saved artifacts. `stage2` without `--execute` only inspects the cumulative ledger. Charged execution is reserved for the user's fresh Stage 2 session and package 07 limits.

[Stage 1 handoff](docs/redesign/HANDOFF.md) · [Stage 2 kickoff](docs/redesign/STAGE2-KICKOFF.md) · [Active code map](docs/redesign/ACTIVE_CODE_MAP.md) · [Design package](docs/redesign-package/00-START-HERE.md)

The previous Studio and old workflow entrypoints are retired. The CLI provides the run/report view. Historical sources, runs and databases stay in place; old code is recoverable from Git. [Archive index](docs/archive/README.md).

For the integrated fixed-corpus command, supplied environment/settings, versioned industry import, and bounded saved-output replay, see [the integration handoff](docs/redesign/coherent-retrieval/integration/IMPLEMENTATION.md). `fixed-corpus` uses the same workflow and stage runner; it never enables external acquisition. Execution, coverage, review and export statuses are separate. The reviewer uses five user-focused criteria with targeted source checks. The orchestrator routes essential evidence gaps to one post-review follow-up, then revision/recheck; unresolved issues prevent readiness. This is not exhaustive fact verification. See [rubric review implementation and validation](docs/redesign/coherent-retrieval/rubric-review/IMPLEMENTATION.md).
