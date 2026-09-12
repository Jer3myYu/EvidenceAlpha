# Bounded readiness and evaluation proposal — not executed

Implementation is complete at `0aa3f2fd71373ba35f7d974d575848f5846dfe8a`.
Actual reranker CPU feasibility and retrieval quality remain unevaluated.
Reuse the completed 56 deterministic checks and saved 103-passage replay;
neither proves neural performance. This amendment prepares the existing proposal
for one execution, not another design or test campaign. No preparation or
inference is authorized merely by reading this file.

## Frozen inputs and judgments

[EVALUATION.json](EVALUATION.json) freezes all 16 exact query strings, source
scopes, order, original support spans/text, required claim/context annotations,
source-file hashes, baseline query results and the synthetic control fixture.
Its SHA-256 is
`84de8e38b690095d9b6d65347e701bf7bb1f01d52ddf524c76f5723ca25c46c0`.
Verify it before admission; do not edit it after observing scores. Freeze this
proposal's hash in the attempt manifest as well. Any correction after inference
is a disclosed annotation defect, not a revised passing denominator.

S01–S12 are the 12 historical searches in chronological order, including their
exact source filters. Required bundles cover financial totals, technology
states, management explanations and named relationships, as mapped per query.
This is a finite minimum-support benchmark, not a complete annotation of every
facet of the broad queries or the report brief. Report other relevant facets
separately, without changing its denominator.

Controls, selected from existing originals without new ranking or inference:

| ID | Exact query | Frozen target |
|---|---|---|
| C01 | 为什么掩膜版核心人才培养周期长，公司扩张面临什么人才风险？ | Qingyi annual report c1791–c1795: training, cross-domain expertise, scarcity and expansion-driven shortage |
| C02 | 清溢光电2026年7月10日厂区参观由哪些机构组织，任新航以什么职务陪同？ | Qingyi investor record c49–c52: organizers and accompanying officer; these are not customer/supplier relationships |
| C03 | 路维光电如何通过barcode自动化和ODB++数据处理提升图档处理效率？ | Luw c83–c86: automation and processing mechanisms, without invented measured gains |
| C04 | What precedes hosted operation, and is customer retention the same as factory qualification? | Existing service.html fixture: configuration precedes operation; retention differs from factory qualification; synthetic identity |

These are pre-inference controls, not independently blinded/held-out evidence.
C02 tests named relationship discrimination, not commercial-relationship recall.
The saved-query bundles separately test commercial relationships. C04 is a
synthetic mechanism control, not evidence of real-world cross-domain quality.
Historical diagnostic targets remain labeled diagnostic, never held-out.

Use the unchanged five-source frozen corpus for S01–S12. For the control group,
use an isolated derivative containing those same sources plus the existing
service fixture, with the frozen source scopes. Do not reparse/migrate the five
historical sources. Parse only the synthetic fixture locally; bind its frozen
raw-text annotations to canonical spans before any inference. Hash the resulting
control corpus. No extra source acquisition. Assessor annotations, prior notes,
selected passages and coverage assignments never enter scoring inputs or later
production task state. Only query, source scope and normal original context do.

## Acceptance fixed before inference

All judgments use frozen claims and original references, not runtime coverage
labels or logits as factual confidence. Equivalent same-version original support
may count if every required meaning/qualifier is cited; record the adjudication
without rewriting the frozen targets. Missing association stays unknown.

For each query, record these independently:

1. **Candidate coverage at 64:** for each required bundle, does at least one raw
   candidate contain direct claim-bearing support (an anchor)? Also report the
   fraction of annotated supporting spans in the raw pool. Then separately record
   whether the union of candidate structural views contains the complete bundle.
   An anchor alone is not complete support. Candidate-view failure cannot be
   blamed on reranking. No new scorer/BM25 comparison is run.
2. **Returned-block relevance at six:** grade each returned block 2 for direct
   evidence for a frozen claim, 1 for its necessary context, 0 for unrelated
   material. Report the grades, direct-hit bundles and relevant/returned ratio
   (grades 1 or 2 count relevant; empty output has ratio zero). The denominator
   is actual returned blocks, capped at six; deduplication is not padded with
   fictitious results. Unannotated but useful facets are disclosed separately.
3. **Complete supporting context:** score each required bundle complete only if
   the union of delivered original blocks carries the full claim plus necessary
   subject, period, units, row labels/headers, relationship and status qualifiers.
   Count it partial if any required support is absent or structurally ambiguous.
   Inspect scored views separately from returned originals: omitted qualifiers
   in neural windows remain a scoring-context limitation even when the returned
   reading block is complete. An unknown association cannot earn completeness.

Per-query **pass** requires anchors for every required bundle, at least one
returned grade-2 block per bundle, relevance ratio >=0.50, and complete delivered
context for every bundle. **Partial coverage** means some required direct support
is delivered but one of those coverage/relevance/context requirements is unmet.
**Failure** means no required direct support is delivered, or evidence has altered
text, wrong source/version binding, or a misleading claim/context association.
Tool/model/resource errors are execution failures, not zero-relevance judgments;
unexecuted cases are unassessed. Record component outcomes even when overall fails.

Candidate-component pass requires anchors for every required bundle in every
executed case; separately report candidate-view completeness. Reranking-component
pass requires every candidate-supported bundle to have a returned direct hit and
every executed query to meet the relevance ratio. It does not conceal bundles
missing from candidates. Reading-component pass requires complete delivered
context for every required bundle; partial-scoring-window limitations are reported
separately. None of these alone implies integrated acceptance.

**Quality pass:** all 16 cases executed, all 16 per-query passes, zero fidelity or
false-association failures, and no loss of a comparable frozen bundle that the
historical six search results completely supported. This intentionally strict
minimum-support gate is not a statistical claim or proof of broad superiority.
Any partial query makes overall quality partial and insufficient for provider-test
admission; any query failure makes it failed. Missing cases make suite quality
incomplete, even if the executed subset passes. Do not lower criteria after seeing
results. Quality insufficiency is assessed after the single bounded attempt;
no automatic fixing, additional queries, tuning or rerun follows.

## Comparison with preserved evidence

Reuse shared checkout `data/redesign/company-stage-corrected/`:
`retrieval-trace.json`, `source-checks.json`, `RESULTS.md`'s linked artifacts,
and the original requests/writing view/notes. The summary itself is at
`docs/redesign/company-stage-corrected/RESULTS.md` in that shared checkout.
S01–S12 match query/source/version; score the saved six original results using
the same frozen support rubric. New six structural blocks are larger result
units: report text bytes and supported bundles, not a misleading precision
comparison between identically sized units. The baseline has no top-64 trace;
candidate@64 is unmatched. Baseline opens are a separate research outcome, not
part of its six search hits. C01–C04 have no historical query match.

Baseline: 12 searches/6 opens, 103 durable passages, 96 delivered to writing;
financial totals retrieved but driver/relationship/context gaps remained.
Completed deterministic replay includes all 103 in 51,669 UTF-8 bytes, and
preserves protected support under a smaller payload. Reuse those results without
rerunning them. They establish handoff preservation, not candidate recall or
neural quality. Preserve prior BM25 findings without another comparison run.
No new notes, provider or PDF evaluation belongs to this local retrieval attempt.

## Production lifecycle and measurement

Invoke the unchanged production `Retriever.search` with its default local
`LocalReranker`, not a direct warm-model scoring loop. Every uncached nonempty
search admitted to scoring verifies snapshot hashes, spawns a fresh child,
imports dependencies, loads tokenizer/model, scores and terminates/reaps it.
Missing snapshot/admission failure starts no model. Cache hits reuse scores, not
resident model weights. No preloading, warm resident worker or extra warm-up call.
Operating-system file cache may warm naturally; record it as uncontrolled rather
than calling later searches cold-disk measurements.

The execution-only harness must collect observational timing at unchanged
production boundaries, including in the spawned child, without replacing scoring,
window construction, process policy or budget checks. Use an external bootstrap
observer (for example stdlib tracing restricted to frozen worker line boundaries)
to record dependency import/load start and model-ready before the first receive,
then request receive through tokenization/window building/forward/result send.
Record snapshot verification, candidate/context construction, process startup,
initialization, scoring (including tokenizer/window work), cleanup, total search
wall time, paired window count and sampled peak RSS separately. Do not sum nested
parent and child intervals as disjoint costs. Observer overhead consumes budgets.
No inference timing is inferred by subtracting an unrelated warm benchmark.

`0aa3f2f` does not expose separate initialization/scoring telemetry by itself;
the external observer/harness is execution preparation, not a claimed completed
feature. Its source/hash must be sealed before the first search. If observation
cannot be established without modifying runtime or scorer behavior, stop before
inference and report the measurement blocker. No extra model call is allowed to
test instrumentation. Missing phase timing after launch means measurement is
incomplete, not proof of readiness.

## Preparation and execution ceilings

All steps below require the consolidated authorization at the end. They create
new artifacts only, preserve commit/history/shared environments, and use a new
non-resetting attempt ledger. Record admission before each charged operation.

**Isolated dependencies:** one resolver/install attempt, <=15 minutes wall time,
<=3 GiB downloaded dependency bytes (including metadata and transitive wheels),
<=8 GiB installed environment, four CPU threads and 8 GiB sampled process-tree
RSS. Use a new real `.venv` inside an isolated preparation directory, never the
worktree's symlink to the shared environment. Use its `.venv/bin/python` and
`.venv/bin/pip`. Resolve declared `torch>=2.6,<3`, `transformers>=4.38,<6`,
`sentencepiece>=0.2,<1` plus required application/transitive dependencies; pin
versions and wheel hashes. CPU-only wheels, no CUDA payload or source compilation.
No broad unrelated upgrades, system installs, automatic fallback or retry. Count
failed/partial transfers; if enforceable byte accounting is unavailable, stop.

**Model preparation:** model `BAAI/bge-reranker-v2-m3`, revision prefix `953dc6f`.
Full 40-character SHA, exact file inventory, sizes and SHA-256 values remain
unresolved. Resolve these remote facts only during authorized preparation; never
invent a complete manifest from local metadata. One metadata/acquisition attempt,
<=15 minutes and <=4 GiB total downloaded bytes, including metadata/partial files.
Acquire only safetensors and required tokenizer/config/license files from that
resolved revision, no duplicate alternate-format weights. Record origin, revision,
file sizes/hashes and `snapshot.json`; verify local files. Use local-only loading,
no remote code or moving `main`. Resolution or budget failure stops preparation.
The combined preparation wall ceiling is 30 minutes and download ceiling 7 GiB;
unused dependency allowance cannot enlarge the model allowance or vice versa.

**Local evaluation:** one attempt/configuration, 16 queries maximum, 2,048 charged
pairs maximum across both groups, 10 minutes continuous wall time including
admission checks, hashing, tracing and cleanup from evaluation start. Pre-inference
fixture binding/harness preparation is local preparation; no model imports or
loading may be hidden there. CPU float32, batch 1, four threads, one active child,
8 GiB sampled worker RSS, with process-tree RSS also reported. Sampled RSS is not
an absolute memory cap; terminate on observed excess. No neural work follows a
resource/cancellation/model/integrity error; preserve completed and unexecuted IDs.

Use two fixed, honest stage groups: S01–S12 share one Retriever and its cumulative
120-second/2,048-pair stage counters; C01–C04 share a second Retriever for the
separate control corpus. Do not reset inside either group. Both groups share the
outer 10-minute and 2,048-pair ledger, including reserved charges on failures.
Each search keeps its 30-second deadline including initialization and hash work;
the effective deadline is the earliest of search, remaining stage and remaining
outer deadline. Stop the whole attempt at the first resource deadline; do not
start controls to sidestep a failed saved-query stage. No query retries.

Report two separate decisions:

- **Evaluation completion:** all 16 cases yielded recorded, assessable results
  within 600 seconds and 2,048 charged pairs, with complete measurements.
- **Production-budget feasibility:** each search <=30 seconds and each actual
  stage group <=120 cumulative seconds, with unchanged production admissions,
  complete cleanup and memory/pair compliance. Report full observed end-to-end
  search times as well as runtime counters; post-counter assembly/trace writing
  must not be hidden. Failure of either timing measure is not a pass.

The ten-minute ceiling never grants extra search/stage time. It is an outer cap,
not permission to run all 16 after a production limit fails. A harness which
resets counters, bypasses deadlines or benchmarks a warm resident model produces
neither authorized evaluation nor production readiness. Completion alone does
not establish quality or feasibility for an actual research stage with other work.
The original design's separate 120-second load/preload suggestion is not used in
this attempt: each real reload must fit inside its search's remaining 30 seconds.

## Stop, deliver, and keep provider evaluation separate

Stop on dependency/model preparation failure, unverifiable revision/artifacts,
missing instrumentation, source/annotation mismatch, invalid results, resource
limit, cancellation, or model error. Cancel/reap children and retain partial bytes,
logs, telemetry and unexecuted IDs. Stop after the fixed attempt even on success.
No automatic tuning, alternate model, installs beyond limits or patch/rerun loop.
Insufficient feasibility requires a concrete resource/lifecycle decision under
new authorization; insufficient quality requires diagnosis by failed component
from saved artifacts. No new design cycle is implied and no provider test starts.

Only separately authorized later work may check writer admission and run one
company-stage provider evaluation. Retain the prior proposal: known writer
context minus 12,000 output and 4,096 reserve, input capped at 64,000 conservative
byte-estimated tokens; unknown capacity blocks admission without provider probes.
Later company test: GPT-5.6 Sol medium, <=8 calls including tool-free writing,
32 tools, 600 seconds worker/summed provider time, 180-second writing reserve,
300 seconds/invocation, 780 seconds execution/export, 12,000 observable output
tokens with reasoning added only if nonoverlapping. It needs separate permission
and ledger; e80e141's six-call allowance is consumed. Changed effort prevents
causal attribution solely to retrieval. No retry/full pipeline/provider fallback.

## Consolidated authorization prompt — not yet granted

> Authorize one bounded dependency/model preparation and local neural evaluation
> under the amended EvidenceAlpha-coherent-retrieval/docs/redesign/coherent-retrieval/
> READINESS.md and frozen EVALUATION.json (SHA-256
> 84de8e38b690095d9b6d65347e701bf7bb1f01d52ddf524c76f5723ca25c46c0).
> Reuse runtime commit 0aa3f2f and completed deterministic/baseline results.
> Prepare only an isolated dependency environment: one attempt, 15 minutes,
> 3 GiB download, 8 GiB installed size, CPU-only wheels, no source builds.
> Resolve BAAI/bge-reranker-v2-m3@953dc6f to its full remote revision and record
> artifact hashes; one model acquisition attempt, 15 minutes, 4 GiB download.
> Prepare/seal an external observational harness without changing runtime code.
> If preparation and measurement admission succeed, run the frozen 16 queries once
> through production Retriever.search and its fresh scorer reload per uncached
> search: CPU float32, batch 1, four threads, one worker, 8 GiB sampled RSS,
> 2,048 total charged pairs and 10 minutes evaluation wall time. Preserve the
> 30-second/search and 120-second/stage limits in the two fixed groups; stop the
> entire attempt on a resource/model/integrity failure without retry or resets.
> Report initialization and scoring separately, candidate coverage, returned-block
> relevance, complete context, quality status, evaluation completion and
> production-budget feasibility using the frozen criteria. Preserve historical
> evidence and new partial artifacts; do not rerun completed tests, change runtime,
> tune, substitute models, call providers, launch the later company test, push,
> merge or deploy. Finish the bounded assessment and stop.
