# EvidenceAlpha

One source-grounded research workflow: lead planning → optional industry/company research → synthesis and sourced figures → independent review → at most one revision/recheck → Markdown/PDF. Fixture output validates software plumbing, not research quality.

Use Python 3.11/3.12 in `.venv`. Install with `.venv/bin/pip install -e '.[dev]'`; Graphviz `dot` is required for relationship diagrams. Optional local embeddings: install `.[embeddings]` with a permitted local model; lexical retrieval remains the default. No paid embedding API is used.

```bash
.venv/bin/python -m evidencealpha --help
.venv/bin/pytest
.venv/bin/python -m evidencealpha run --fixture tests/fixtures/redesign/manufacturing.json --output data/redesign/example
.venv/bin/python -m evidencealpha show-run data/redesign/example
```

New runs need a new output directory. `resume`, `replay-stage` and `render` operate on saved artifacts. `stage2` without `--execute` only inspects the cumulative ledger. Charged execution is reserved for the user's fresh Stage 2 session and package 07 limits.

[Stage 1 handoff](docs/redesign/HANDOFF.md) · [Stage 2 kickoff](docs/redesign/STAGE2-KICKOFF.md) · [Active code map](docs/redesign/ACTIVE_CODE_MAP.md) · [Design package](docs/redesign-package/00-START-HERE.md)

The previous Studio and old workflow entrypoints are retired. The CLI provides the run/report view. Historical sources, runs and databases stay in place; old code is recoverable from Git. [Archive index](docs/archive/README.md).
