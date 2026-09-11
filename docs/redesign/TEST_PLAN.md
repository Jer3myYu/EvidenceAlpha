# Stage 2 test plan and Stage 1 checks

Run from `/home/cobot/cobot_storage/webproject/EvidenceAlpha`. Use the existing `.venv`; do not use system Python. Reproducible install:

```bash
.venv/bin/pip install -c docs/redesign/constraints.txt -e '.[dev]' --no-build-isolation
```

Python 3.12 and Graphviz `dot` are installed; details in VERSIONS.json. Optional embeddings are not part of the validated dependency closure.

Offline checks (executed during Stage 1):

```bash
.venv/bin/python -m evidencealpha --help
.venv/bin/pytest
.venv/bin/black --check src/evidencealpha tests/redesign
.venv/bin/pylint --jobs=1 src/evidencealpha tests/redesign
.venv/bin/python -m evidencealpha show-run data/redesign/stage1-final-service
.venv/bin/python -m evidencealpha resume data/redesign/stage1-final-service --fixture tests/fixtures/redesign/service.json
.venv/bin/python -m evidencealpha render data/redesign/stage1-final-manufacturing/reports/report.md
.venv/bin/python -m evidencealpha stage2 --help
```

The following creation commands were executed; their output directories now exist. Use a new directory for another fork (never erase the saved run):

```bash
.venv/bin/python -m evidencealpha run --fixture tests/fixtures/redesign/manufacturing.json --output data/redesign/stage1-final-manufacturing
.venv/bin/python -m evidencealpha run --fixture tests/fixtures/redesign/service.json --output data/redesign/stage1-final-service
.venv/bin/python -m evidencealpha replay-stage docs/redesign/inputs/fixture-synthesis.json --fixture tests/fixtures/redesign/service.json --corpus data/redesign/stage1-final-service/sources --output data/redesign/stage1-fixture-replay
```

Coverage: `test_evidence.py` checks Chinese source spans/table headers, publisher-versus-subject context, period mismatch, changed sources, generated-context separation, fixed-corpus dispatch, exact trace misses, arithmetic and failed-extraction original retention. `test_workflow.py` checks two-domain full exports, malformed output, independent review inputs, optional-polish behavior, one revision/recheck, unresolved findings, draft preservation, resume/fork and changed-draft invalidation. `test_budget.py` checks session admission, cumulative failed attempts, overlapping reservations, unknown tokens, probe sub-budgets, provider substitution and child-group timeout cleanup.

Both final PDFs and figures were visually inspected. The manufacturing diagram's Unicode escaping was corrected after visual inspection. Canonical report hashes are in run manifests. These are synthetic fixture reports, never product validation.

Existing-source check: `data/redesign/stage1-real-corpus-check.json` and `data/redesign/stage1-real-corpus/` contain offline extraction/retrieval from a preserved four-page issuer PDF. Original file is `data/sources/blobs/a842b88902a1f8b99ec212296c29af426293252c3b5501f4a1c7cfc30793160c.pdf`. Historical source metadata is `data/sources/versions/90c802ed3716cdf2.json`; preserve its original URL/date if preparing a live source pack. The new local parser import timestamp is not an external reacquisition date. One document does not cover the full photomask brief. A real service-source case remains pending; the service fixture establishes mechanics only.

Fresh Stage 2 only: read 07 and 04, verify native runtime controls/auth before counting a fixed-evidence comparison. The one-case driver is deliberately explicit; it never starts a whole campaign in the background. Example executable case command (syntax checked; NOT executed in Stage 1):

```bash
.venv/bin/python -m evidencealpha stage2 --execute --case docs/redesign/cases/plan.json
```

Other prepared cases: `industry.json`, `company.json`, `synthesis.json` in the same directory. They use GPT-5.5 medium and saved real-source inputs. Reuse a representative successful result. After synthesis, construct reviewer input from its exact draft and figure data/assets, and a `review` case with the same corpus; the reviewer is always GPT-5.6 Sol medium. Add revision/recheck cases only if required. Contextualization is disabled by default, so no rehearsal is charged for it. `execution: original-provider` reruns the configured production provider instead of a surrogate. Do not relabel surrogate results or unverified native controls as a guaranteed fixed-corpus comparison.

`cases/full-report.json` has an empty readiness list and is rejected until the fresh session records actual stage-readiness artifacts after inspecting their usefulness/source fidelity. Full attempts force the all-GPT profile. Fill source pack/brief as needed within acquisition ceilings. Full attempts are sequential, use one review/revision/recheck, and have an outer process alarm. Deadline interruption leaves partial files and conservative unsettled reservations; reconcile those without resetting counters. The direct `resume --fixture` command is offline. A full Stage 2 case can set `resume_from` to an existing live run: the driver forks its artifacts, verifies dependencies, and consumes a new full-attempt slot/deadline while preserving all campaign counters. A fixture run cannot be relabeled live. Prefer isolated saved-stage reruns for a localized failure.

Do not run every case reflexively. Stop at the package limits or sufficient product evidence. Write COMPLETION.md, NEXT_SESSION.md and results/usage artifacts in Stage 2. No push, merge, deployment or paid fallback.
