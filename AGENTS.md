# EvidenceAlpha active project instructions

The user-authorized redesign package at `docs/redesign-package/00-START-HERE.md` governs architecture, roles, budgets and the two-session process. Follow its reading order. Numerical policy is in 07; code quality is in 08. Stage 1 ends after handoff, without launching or scheduling Stage 2. A fresh user-started session activates Stage 2.

The old “EvidenceAlpha — Starting Prompt” is preserved unchanged at `docs/archive/starting-prompt.md` for historical reference only. Do not load archived instructions or old C/S task lists by default. Active handoff navigation is `docs/redesign/`.

Retain compatible Google Python style: four-space indentation, 80-column Black, module imports, absolute imports, typed public APIs and Google-style docstrings. Run focused pytest and pylint/Black checks. Use `.venv/bin/python` and `.venv/bin/pip`; declare dependencies in `pyproject.toml`. No system installs or secret logging. `.env` and authentication caches are never report artifacts or commit inputs.

Preserve user edits, original source documents, source corpora, databases and historical run outputs. Recover retired tracked implementation from base commit `3abe9692f3b5f3bbe20390a8d8971af994d3f07b`; do not import it into the new path. Local task commits are authorized by the redesign request; no push, merge or deployment. Do not change git identity or account configuration.
