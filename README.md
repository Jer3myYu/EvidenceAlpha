# EvidenceAlpha

One source-grounded research workflow: lead planning → optional industry/company research → synthesis and sourced figures → independent review → at most one revision/recheck → Markdown/PDF. Fixture output validates software plumbing, not research quality.

Use Python 3.11/3.12 in `.venv`. Install with `.venv/bin/pip install -e '.[dev]'`; Graphviz `dot` is required for relationship diagrams. Local reranking uses `.[retrieval]` and an explicitly supplied local model. Downloads and provider calls require execution authorization; degraded lexical mode must be selected explicitly.

```bash
.venv/bin/python -m evidencealpha --help
.venv/bin/pytest
.venv/bin/python -m evidencealpha run --fixture tests/fixtures/redesign/manufacturing.json --output data/redesign/example
.venv/bin/python -m evidencealpha show-run data/redesign/example
```

New runs need a new output directory. `resume`, `replay-stage` and `render` operate on saved artifacts. `stage2` without `--execute` only inspects the cumulative ledger. Charged execution is reserved for the user's fresh Stage 2 session and package 07 limits.

[Stage 1 handoff](docs/redesign/HANDOFF.md) · [Stage 2 kickoff](docs/redesign/STAGE2-KICKOFF.md) · [Active code map](docs/redesign/ACTIVE_CODE_MAP.md) · [Design package](docs/redesign-package/00-START-HERE.md)

The previous Studio and old workflow entrypoints are retired. The CLI provides the run/report view. Historical sources, runs and databases stay in place; old code is recoverable from Git. [Archive index](docs/archive/README.md).

For the integrated fixed-corpus command, supplied environment/settings, versioned industry import, and bounded saved-output replay, see [the integration handoff](docs/redesign/coherent-retrieval/integration/IMPLEMENTATION.md). `fixed-corpus` uses the same workflow and stage runner; it never enables external acquisition. Execution, coverage, review and export statuses are separate. An empty issue list without examined scope leaves review partial.
