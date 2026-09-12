# Reviewer fix implementation and validation

Runtime commit: `dc6bd86`, branch `reviewer-contract-fix`.

The plan was committed as `6b35708`; local `main` was fast-forwarded from
`ce0e70e` to that integration history before creating the implementation branch.
No push occurred. The shared `EvidenceAlpha` worktree remains on
`research-quality-upgrade`; its uncommitted changes were left untouched.

## Implemented

Synthesis now supplies a provisional material-claim inventory tied to exact
draft excerpts and brief requirements. Source-ID aliases applied during export
are also applied to inventory locations. The reviewer can add omitted claims.
Headings are no longer treated as factual verification units. Editorial and
inventory assessments are separate from factual checks.

The new shared review contract distinguishes examination from support. A
supported/contradicted claim requires exact original quotations, a matching claim
and an explanation. An insufficient-evidence result can document actual checks
without fabricating a quotation proving absence. Partial checks cannot establish
whole-claim support. Missing inventory requirements stay visible. Exact quote
validation does not establish semantic entailment or exhaustive claim discovery.

Before completing review, the runner can schedule one consolidated completion
opportunity. It saves the initial partial response, retains prior findings and
checks, measures the actual next request and preserves revision/recheck capacity.
If capacity is unavailable, it retains the partial assessment. A repeated partial
response does not trigger another completion loop. The existing overall ledger,
deadline, concurrency and provider watchdog remain authoritative.

`review_completion_calls` in `Settings` is 0 or 1: it counts completion-feedback
opportunities, not a replacement generative-call budget. Tool continuations still
consume the enclosing command/round limits. No stage time/token targets became
new campaign stop rules.

Material findings follow the existing single revision/recheck path. Identical
finding records are deduplicated with origins retained; differently worded
findings are not assumed semantically identical. Explicit `claim_ids` permit
focused recheck resolution of affected claims only. Initial examination status,
factual status, revision resolution and export remain separate. Old unlinked
findings cannot upgrade unrelated claims. An empty issue list cannot establish
full review. Review checkpoint compatibility now includes the inventory contract.

Original-preserving assembly and full-corpus source opens remain in place. The
existing fixed-corpus tool boundary rejects web search/fetch both in advertisement
and dispatch; Codex native web search remains disabled. No new web acquisition
path was added. The existing explicit live source-tool mode remains separate;
its network behavior was not exercised here.

## Focused evidence

Six focused pytest checks passed: two new contract/completion checks plus four
existing orchestration/evidence/failure regressions. The new checks were repeated
after final completion/status edits and passed. Black and pylint passed on the
changed Python files. No benchmark or model stage was rerun.

All paths below are relative to this worktree:

| Evidence | Result |
|---|---|
| `data/redesign/fixed-corpus-integration/reviewer-fix-replay-20260912/ASSESSMENT.json` | Normal orchestration replayed saved planning, both researchers, follow-up, synthesis, review, revision/recheck and PDF export. Execution/export completed; review remained partial. Its final assertion failed because the completion request could not fit. This failed expectation is preserved. |
| Same run, `run/stages/review/*/events.jsonl` | First divergence: duplicated completion metadata exceeded the request allowance. Initial partial review was retained; mandatory originals were not dropped. |
| `data/redesign/fixed-corpus-integration/reviewer-fix-completion-20260912/ASSESSMENT.json` | After compacting redundant feedback, only the changed reviewer path was replayed: two fixture responses completed, with 840 identical original references in both inputs. The known customer absence was documented as contradicted; other requirements remained unmapped/partial. |
| Same directory, `FINAL-CAPACITY.json` | Saved views reserialized with final prompts/schema: 240,349 and 241,521 bytes including schema, below the existing 242,304 conservative input allowance. This is a UTF-8 upper estimate, not an exact provider tokenizer measurement. |

The orchestration replay retained customer originals in actual review, revision
and recheck inputs (840, 842 and 842 originals respectively). Saved historical
recovery files and source corpus hashes remained unchanged. Completed downstream
stages were reused after the feedback correction, not restarted. The final
claim-link resolution changes were checked deterministically; no new live
recheck is claimed.

The one-claim inventory and completion response were explicit fixture adaptations
of the known saved Luw finding. They were not autonomous discoveries or a new
research result. The replay PDF is an export-plumbing artifact, not a newly
independently reviewed report. All new generative calls and neural calls: **0**.

## Reproduce offline

Run from `/home/cobot/cobot_storage/webproject/EvidenceAlpha-fixed-corpus-integration`.
Use a new output directory; never reuse a closed campaign directory.

```bash
PYTHONPATH=src .venv/bin/python docs/redesign/coherent-retrieval/reviewer-fix/replay_saved.py \
  --saved data/redesign/fixed-corpus-integration/recovery-20260912 \
  --execution docs/redesign/coherent-retrieval/recovery-20260912/execution-continuation-2.json \
  --output data/redesign/fixed-corpus-integration/reviewer-fix-replay-local
```

This reads historical settings as fixture configuration; it does not open the old
ledger or invoke its provider. For the targeted completion replay, add
`--review-only-from data/redesign/fixed-corpus-integration/reviewer-fix-replay-20260912`
and choose another new output directory. `PYTHONPATH=src` is intentional: the
reused environment's editable installation can otherwise resolve another checkout.

## Remaining limits and live acceptance

The contracts and control flow are implemented. Model compliance, quality of the
writer's claim inventory, completeness of reviewer examination, semantic source
support and false-positive rates remain unmeasured under these new prompts.
The saved request has little spare room; longer inventories require actual
capacity checks and may yield an explicit partial/admission failure. There is no
new evidence-truncation fallback.

A separately authorized bounded acceptance can reuse a saved draft/originals
and exercise only review plus its optional completion, one revision and focused
recheck—without rerunning successful research. Freeze the claim inventory and
record any manually supplied findings as supplemental. Reserve up to six calls
and 30 minutes inside a fresh authorized overall record, checking actual requests
before invocation. Assess examined material claims, unsupported objections,
preserved qualifiers and unresolved scope independently of execution/export.
This familiar task can establish recovery behavior only; an unfamiliar held-out
task is needed before claiming generalization. No live acceptance was launched
by this implementation task.
