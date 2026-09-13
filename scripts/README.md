# Evaluation utilities

These are explicit research-evaluation helpers, not normal installation or
report-generation steps:

| Script | Purpose | Resources used |
|---|---|---|
| `evaluate_hybrid_rag.py` | Run frozen questions through lexical and hybrid variants and record originals/handoff results | Local encoder/reranker inference; requires prepared corpus, index, settings and an active evaluation ledger |
| `judge_hybrid_rag.py` | Assess saved paired results against the supplied usefulness criteria | Generative provider calls; requires explicit authorization and recorded capacity/usage |

Both expect a deliberately prepared evaluation directory containing
`EVALUATION.json`, `settings.json` and `ledger.json`; they are not one-command
benchmark setup tools. Historical evaluation inputs/ledgers are local-only.
Do not reuse a closed record or rerun successful model evaluations as part of
installation, documentation checks or ordinary unit testing.

For report generation use the normal CLI described in [Setup](../docs/SETUP.md).
For interpretation of measured results see [Evaluation](../docs/EVALUATION.md).
