# Fixed-corpus integration handoff

Implemented in the isolated `fixed-corpus-integration` branch/worktree at
`/home/cobot/cobot_storage/webproject/EvidenceAlpha-fixed-corpus-integration`.
Base HEAD is documentation commit `5607a21184f4654ab9490438b95546259532fa70`;
the previously evaluated retrieval runtime is `cad87ed9fe865ea93e8b329543c805e4578d2bd3`.
Their historical results are unchanged. This integration has **offline plumbing
validation, not a new autonomous research or neural-quality result**.

## One command

From the integration worktree, using the already installed neural environment:

```bash
PYTHONPATH="$PWD/src" /home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python -m evidencealpha fixed-corpus --execution docs/redesign/coherent-retrieval/integration/photomask.execution.json --output data/redesign/fixed-corpus-integration/live-acceptance-01
```

This is the live command for a separately authorized acceptance execution;
**it was not run during implementation**. It needs an unused output directory.
No separate stage launches, source assembly, environment installation or report
export command is required. The explicit Python executable selects the existing
installation; `PYTHONPATH` selects this checkout rather than its older editable
installation. There are no machine-specific paths or company answers in runtime
logic. The supplied photomask configuration intentionally records this machine's
existing corpus/model/import paths; update those explicit input paths if moving
it elsewhere. Credential files are neither loaded by configuration nor frozen.

`photomask.execution.json` supplies the original brief, hash-bound scoped company
task, essential questions derived from that brief, model/settings and offline
model environment. `industry-import.json` binds historical notes, original
passages and citation mapping by SHA-256 and verifies source versions/text spans
against the corpus. Industry originals are imported only after company research,
for synthesis; company inputs do not receive old answers or assessor queries.
Omit `tasks`/`tasks_sha256` to invoke lead planning instead of explicit scoped-task
reuse. Optional industry reuse is explicit; a duplicate industry plan is rejected.
The five-source corpus excludes the synthetic benchmark control.

## Shared path and contracts

| Component | Integrated behavior |
|---|---|
| `cli.py`, `execution.py` | `fixed-corpus` admits one additive ledger, freezes actual code/settings/Python/package/source identities, and calls the existing `workflow.run`. No external-acquisition tools or provider fallback. Existing fixture commands remain offline callers of that same workflow. |
| `config.py`, `budget.py` | One worker and sequential generative admission; configurable enclosing and stage limits; unknown usage blocks subsequent admission. Research reserves writing time/calls/tokens. Review leaves calls for revision/recheck. Cancellation covers setup, stages and export; draft and failed reservations remain saved. |
| `workflow.py`, `handoff.py` | Validate original text at source/version/spans, union durable research evidence, retain notes and explicit upstream omissions, and import version-bound industry evidence. Original passages used in research writing/import are mandatory downstream; insufficient payload raises an explicit error. Review findings and examined-scope quotations add mandatory originals for revision/recheck. Other available evidence remains eligible under the same byte bound. |
| `stage_context.py`, `documents.py` | Remove redundant block IDs and chunk-reference geometry from transport, retaining original text, source identity/version, primary spans, chunk locators and pages. Include all eligible evidence if the complete envelope fits. Under pressure, existing priority/adequacy precedence remains; recent tool evidence precedes older peers within its tier. No first-N gate. Exact version-bound scorer cache is shared across stages; uncached searches still load a fresh worker. |
| Follow-up | One stage from the researcher's unresolved essential scope, notes, originals and search history. The initial partial assessment is retained separately; explicit supported recovery is merged. No assessor answers. Remaining gaps remain partial in the report inputs. |
| Review/revision | Fresh reviewer gets draft, source map, originals, figure metadata and scope IDs. `scope` and `issues` are separate; absent scope remains unexamined even with no issues. Material independent and supplemental findings use the same verified-quotation contract and one revision/recheck. A narrow recheck does not upgrade the initial review's scope. |
| Delivery | Shared source aliases plus `reports/source-map.json`; original source handles remain in evidence and figure inputs. Accepted flowing-image PDF CSS is integrated. Existing text-preservation rejection remains intact. `execution_status`, `coverage_status`, `review_status`, `revision_resolution` and `export_status` are separate. Exit zero means execution/export completed, not full factual review. |

Coverage declarations remain provisional. Exact quotation validation does not
certify interpretation, completeness, management attribution or undisclosed
status. The reviewer must actually examine those claims. PDF success does not
certify either factual review or general reliability.

## Configured ceilings

- Enclosing window: 10,800 seconds, 16 generative invocations, 3,600 summed
  invocation seconds, 40,000 observable output/reasoning tokens. Reasoning is
  added only when explicitly disjoint; in-flight token limits remain
  unenforceable with the existing provider interface. Unknown usage blocks
  later calls. No historical ledger is reopened or reset.
- Company: 1,620-second stage (leaving 180 seconds within the proposed 30-minute
  allowance for immediate assessment); six calls, 600 summed provider seconds,
  12,000 observable tokens, 32 tools, and 300 seconds reserved for its final
  response. Retrieval: 900 cumulative seconds, 300/search, 2,048 charged pairs,
  one worker/four threads, unchanged 8 GiB sampled worker RSS limit.
- One optional follow-up: up to 900 seconds, three calls; still within enclosing
  limits and protected downstream time. Synthesis/revision are tool-free final
  writing calls. Review has up to four turns, reduced when needed to preserve
  revision/recheck calls. All stage deadlines also respect remaining outer time.
- Protect 900 provider seconds, four calls and 16,000 observable tokens through
  research. Per-call maximum 300 seconds. Export reserves 120 seconds of the
  enclosing time. These ceilings do not promise completion.
- Same pinned local reranker revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; no model substitution, download or
  reranker inference occurred here. Input estimate remains conservative UTF-8
  bytes, capped at 240,000 including application schema; context capacity is
  explicitly supplied as 258,400 with output/transport reserves.

## Validation and exact artifacts

One complete saved-output orchestration replay was executed:

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m evidencealpha fixed-corpus --execution docs/redesign/coherent-retrieval/integration/photomask.replay-execution.json --replay docs/redesign/coherent-retrieval/integration/saved-stages.replay.json --output data/redesign/fixed-corpus-integration/offline-replay-20260912
```

The worktree's `.venv` reuses the existing development environment. The replay
configuration alone includes attributed historical supplemental findings;
they are **not present in the live configuration or company research input**.
All saved stage output/state/writing files are hash-bound in the replay manifest.
The replay injects completed stage envelopes, not new model decisions, retrieval
results or a warm-model benchmark. Research writing selections remain their
historical selections; generated `request.txt` shows the current assembled input.
Future replay records also name `assembled-context.json` and
`historical-writing-context.json` separately to make that distinction explicit.

Replay elapsed **84.99 seconds**, zero generative/neural calls. Research,
follow-up, synthesis, review, revision and recheck all routed, followed by a
six-page PDF. Execution/export complete; coverage/review partial and recheck
resolution unverified because old outputs lack the new scope declarations.
No old assessment was relabeled. All six pages were inspected: readable text,
financial chart and tables; tables cross pages and review remains factually
limited. The unchanged exporter text-preservation check passed.

The replay's selection audit found **three supplemental originals omitted in
revision and two in recheck**. That failed preservation observation remains
saved. A targeted correction makes originals cited by findings/examined scope
mandatory, rather than protecting every unrelated passage visible to a reviewer.
An intermediate overbroad protection attempt exceeded the same payload budget;
its failed state is retained. Only the affected payload assembly was rechecked:
**321 required originals retained, zero missing**, with revision/recheck envelopes
of **239,996 / 239,808 bytes**. No full replay or model stage was repeated after
this correction. The final code therefore has targeted preservation validation,
not a second full-command execution claim.

Exact local result locations, relative to this worktree:

- `data/redesign/fixed-corpus-integration/offline-replay-20260912/command-result.json`
- `data/redesign/fixed-corpus-integration/offline-replay-20260912/execution-freeze.json`
- `data/redesign/fixed-corpus-integration/offline-replay-20260912/selection-assessment.json`
- `data/redesign/fixed-corpus-integration/offline-replay-20260912/reports/report.md`
- `data/redesign/fixed-corpus-integration/offline-replay-20260912/reports/report.pdf`
- `data/redesign/fixed-corpus-integration/offline-replay-20260912/reports/source-map.json`
- `data/redesign/fixed-corpus-integration/targeted-handoff-check/` (failed attempt)
- `data/redesign/fixed-corpus-integration/targeted-handoff-check-corrected/RESULTS.json`

Focused checks: nine new deterministic integration cases passed, plus two
existing payload-selection contracts, one saved-writing-only contract and three
fixture workflow cases with corrected partial-review expectations (**15 distinct
cases**, not a broad suite). Black, focused pylint and `git diff --check` passed.
The tests cover lineage, payload refusal, limited review, writing reserves,
concurrency, unknown usage, capacity guards, follow-up/revision routing, material
support, failure propagation and cancellation. Injected outputs prove contracts,
not autonomous reasoning or retrieval quality.

## Remaining limits and bounded live acceptance

The implementation is complete; live behavior of this integrated command remains
untested. Historical neural evaluation remains **9 pass / 7 partial** across its
preserved versions. Neither new scope compliance nor broad independent review
has been demonstrated by a model. Saved output replay does not validate planner
quality, researcher query choice, production inference cost, provider availability
or repeatability. Payload pressure may still refuse a stage when required
originals and the fixed request cannot fit; it does not silently discard them.
Coverage can remain partial after the one follow-up, with explicit gaps in a
useful draft. Rendering emits a PDF but automated visual review is not claimed.

For live acceptance, use the single live command above under its frozen limits,
without another benchmark. Require: essential brief coverage assessed from actual
notes and sources; correct relationships/units/technical qualifiers; all mandatory
originals present in actual writing inputs; source-based examined/unexamined
review scope; every material finding resolved or explicitly retained through
revision/recheck; preserved Markdown/PDF text and inspected pages; honest separate
statuses, settled usage and no remaining workers. Partial coverage or review stays
partial, even if delivery succeeds. Stop on unavailable access, unknown usage,
exhausted allowance, mandatory-payload failure, or a persistent material blocker;
preserve drafts and diagnostics. No paid fallback, acquisition or whole-pipeline
restart. A single acceptance campaign would demonstrate that run only, not general
reliability. Live execution requires separate authorization; none was used here.
