# Development and repository conventions

## Public tree

| Directory | Versioned contents |
|---|---|
| `src/evidencealpha/` | Active implementation and role prompts |
| `tests/redesign/` | Focused regression tests; directory name retained for compatibility |
| `tests/fixtures/` | Intentional deterministic source/role examples |
| `configs/` | Generic shareable templates with placeholder local paths |
| `scripts/` | Explicit evaluation utilities; see their README |
| `docs/` | Maintained setup, architecture, retrieval and evaluation guides |

The package uses the standard Python `src/` layout; `pyproject.toml` declares
runtime/dev/optional dependencies and installs the `evidencealpha` entry point.
Do not move package modules, fixtures or worktrees merely for cosmetic symmetry.

Local-only directories include `data/`, `runtime/`, `worktrees/`, `tmp/`, `.local/`,
environments, caches, `legacy/`, and historical documentation under
`docs/redesign/`, `docs/redesign-package/`, `docs/archive/` and `docs/presentation/`.
They are ignored, not deleted. Git history still preserves previously committed
files; ignored local data needs its own backup policy. A fresh checkout does not
need historical instructions or closed campaign ledgers.

## Focused checks

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest tests/redesign/test_evidence.py
.venv/bin/python -m black --check src/evidencealpha tests/redesign
.venv/bin/python -m pylint --jobs=1 src/evidencealpha
```

Select the relevant test files for the change. Full formatting/lint commands are
shown as contributor tools, not a claim that the complete historical suite is
currently green. Some older fixtures still assume obsolete capacity/encoding
contracts and need modernization. Do not weaken evidence or cancellation checks
to make them pass.

For documentation/configuration changes, validate relative links against the
**tracked tree**, load example settings without provider calls, and use CLI help
or the deterministic fixture when necessary. Local ignored files must not mask
missing dependencies in a fresh checkout. Do not run live research for a docs fix.

## Coding and evidence contracts

Use typed public APIs, Google-style docstrings, absolute/module imports and
80-column Black formatting. Extend the existing workflow instead of adding a
second execution architecture. Keep case-specific topics, answers and source IDs
out of generic runtime logic.

Original evidence is immutable. Preserve source/version identity, exact text,
locators, units, periods and qualifiers across selection and correction. Generated
summaries and provisional coverage labels are not factual certification. Maintain
explicit omissions and fail admission when mandatory support exceeds capacity.

Checkpoints, ledgers and versioned report assets must remain consistent. Preserve
successful stages and closed historical records; charge only newly admitted calls.
A successful PDF export does not overwrite review readiness or coverage status.

Keep credentials in local provider configuration or ignored `.env` files. Never
commit source datasets, model weights, tokens, runtime logs or generated reports.
Test **code and deliberate fixtures** remain tracked; test caches/results do not.

## Review and contribution scope

Explain the concrete problem, final behavior, focused validation and limitations
in changes. Distinguish deterministic checks, saved-artifact replay and actual
provider evaluation. Use explicit authorization for external calls, source
acquisition, model downloads, push/merge and deployment. Avoid incidental account,
Git identity or historical-data changes.
