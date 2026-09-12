# Continuation result: real inference works; frozen quality gate is not met

Implementation is complete. This continuation measured real CPU inference,
corrected preparation and paragraph context, and assessed all 16 frozen cases.
The result is **9 passes and 7 partial cases**, not integrated acceptance.
Company research, synthesis, independent report review and new Markdown/PDF
production were **not admitted**. The latest instruction retains the agreed
quality gate; READINESS.md requires all 16 passes. No assessor answers were fed
into a company researcher. No new report or report-quality claim is made.

## Preserved versions and artifacts

Runtime base: `0aa3f2fd71373ba35f7d974d575848f5846dfe8a`.
Frozen documentation: `5bda1fb`; EVALUATION.json remains SHA-256
`84de8e38b690095d9b6d65347e701bf7bb1f01d52ddf524c76f5723ca25c46c0`.
Preparation correction: `0ab1c04`.
Paragraph and duplicate-window correction:
`cad87ed9fe865ea93e8b329543c805e4578d2bd3`.

Worktree: `/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval`.
All execution evidence below is under its
`data/redesign/coherent-retrieval/preparation-correction-20260912/` directory:

- `continuation.json`: one additive continuation ledger, including failed work.
- `FINAL-ASSESSMENT.json`: all cases, grades, component judgments, original-span
  counts, baseline counts/bytes, source integrity, timing and memory evidence.
- `neural-1/`, `neural-2/`, `neural-3/`: retained admissions, outputs, traces,
  worker phase telemetry, sampled memory and usage. Failures remain failures.
- `before-profile.json`, `before-payload.json`, `after-replay.json`: preparation
  comparison; `luw-financial-paragraph.png` is the inspected original-page view.
- `baseline-original-search-blocks.json`: reconstructed original text for saved
  baseline search IDs, without executing search or model calls.
- `support-inventory-neural-2.json`, `support-inventory-neural-3.json`: full returned
  block text and separate candidate/view/returned literal-span inventories.
- `report_stage.py`: an unexecuted harness, not a completed company/report stage.

Shared work, frozen sources, evaluated e80e141 results, completed deterministic
results and the closed `campaign-20260912T005532Z/campaign.json` are preserved.
All frozen corpus/input hashes checked unchanged; no pushes or merges.

## Three distinct findings

**Preparation:** S01 statement-boundary profile took 17.806 seconds, including
10.929 seconds of repeated metadata copying. Reusing validated immutable source
indexes reduced scorer entry to 1.023 seconds (1.174 including saved trace).
All 64 candidate identities, original spans and complete contexts matched that
pre-paragraph-fix comparison. The older global-tracing result of 61.51 seconds
has different observer overhead and is not a clean speedup denominator.
Cooperative deadline/cancellation checks cover preparation; individual I/O/JSON/
sort calls are not hard-preemptible. The outer supervisor remains necessary.

**Reading:** the PDF parser labeled individual visual lines as paragraphs.
Commit cad87ed groups adjacent same-page lines using indentation, line spacing,
font height and column geometry, retaining each original span/chunk binding.
It does not cross page/column/ambiguous boundaries or enlarge the 8,000-character
window ceiling. Geometry is provisional, not factual association certification.
There are no frozen case IDs, source IDs, queries or expected answers in this
runtime correction. Code review and focused checks covered generic geometry,
source immutability, cancellation and identical-window caching.

Restoration reached **returned original blocks**, not just candidate contexts:

| Case/bundle | Before returned spans | After returned spans | After candidate-view spans |
|---|---:|---:|---:|
| S01 financial | 2/3 | 3/3 | 3/3 |
| S02 financial | 3/4 | 4/4 | 4/4 |
| S05 technology / customers | 4/10, 5/6 | 10/10, 6/6 | 10/10, 6/6 |
| S06 technology/status | 0/6 | 6/6 | 6/6 |
| S08 revenue/explanation | 3/6 | 6/6 | 6/6 |
| S12 technology / customers / financial | 6/10, 0/6, 0/4 | 10/10, 6/6, 4/4 | 10/10, 6/6, 4/4 |
| C01 talent mechanism | 3/5 | 5/5 | 5/5 |

These inspected/repaired cases are regressions, not independent generalization
samples. The controls were never blinded. C04 is synthetic. Literal-span counts
are diagnostic; semantic judgments and explicit qualifications remain separate.

**Neural ranking:** real pinned-model scores now complete searches, but candidate
recall and top-six relevance remain insufficient. Identical scored text is cached
within a query, preserving logits and view order. This saves duplicate forwards;
it is not a warm resident model or a change to candidate depth/ranking formula.
Each uncached search still verifies the snapshot and reloads a fresh scorer.

## Frozen quality assessment

Grades follow the original rubric: 2 direct, 1 necessary context, 0 unrelated;
ratio counts grades 1/2 over actual returned blocks. Required meanings and their
qualifiers must survive, and each required bundle needs a raw anchor. Source
identity metadata can identify the document, not silently certify a table subject.

| Case | Returned grades in order | Result | Material observation |
|---|---|---|---|
| S01 | 2,1,2,0,2,0 | Pass | Three financial totals/growth; currency caveat retained |
| S02 | 2,2,2,2,0,0 | Pass | Financial paragraph restored; currency caveat retained |
| S03 | 1,2,2,2,2,0 | Pass | Annual financial table, year and units present |
| S04 | 2,2,2,2,2,2 | Partial | Supplier bundle absent before ranking; technology context partial |
| S05 | 2,2,2,0,2,2 | Pass | Customer domains and supply/sampling/planned states intact |
| S06 | 2,2,0,0,0,2 | Pass | 90nm mass production, 65nm sampling, 40nm equipment layout; expectation retained |
| S07 | 0,2,0,2,2,0 | Partial | Equivalent consolidated revenue/growth; complete unit binding unverified |
| S08 | 2,2,0,0,0,0 | Partial | Full explanation delivered, relevance only 2/6 |
| S09 | 1,2,2,2,0,0 | Pass | Revenue year/units/growth delivered |
| S10 | 0,2,0,0,0,0 | Partial | Broad query misses technology/driver/supplier anchors; only partial research-stage evidence |
| S11 | 0,2,0,0,0,0 | Partial | Core status/expectation survives, relevance only 1/6 |
| S12 | 2,2,2,0,2,2 | Pass | All three bundles delivered; currency caveat retained |
| C01 | 2,0,0,0,0,0 | Partial | Full talent explanation, relevance only 1/6 |
| C02 | 2,2,2,1,1 | Pass | Organizer/visit/officer roles retained, not commercial relationships |
| C03 | 2,2,0,0,0,0 | Partial | Barcode/ODB++ mechanism complete, relevance only 2/6 |
| C04 | 2,1 | Pass | Synthetic mechanism and identity delivered |

S04/S10 broad-query failures are preserved in the denominator. They are not
rerun merely to improve the final table. S03/S07/S09 reuse previous completed
results; the other eleven use cad87ed. Thus this is an all-case, **mixed-version
assessment**, not a clean sixteen-case final-code validation. Earlier resource
failures and earlier partial outputs remain independently recorded.

Candidate component fails on missing bundles in S04/S10. Reranking component
fails relevance in S08/S10/S11/C01/C03 even when direct support exists. Reading
component is partial on the broad-query omissions and S07 unit binding.
No altered returned text or source-version mismatch was found in the saved
results. Unknown runtime association labels were not treated as certification.

Scored windows are distinct from delivered originals: annotations fully match
scored text for the restored narrative bundles, but whole annotated table-item
matches are only 2/9 for S03, 2/3 for S09 and 0/4 for C02. These are conservative
whitespace-normalized literal matches, affected by table/header representation,
not evidence that every relevant token was absent. Full scored views are saved;
no complete scoring-context claim is made for those tables merely because the
returned original blocks contain complete support.

## Baseline comparison

The preserved e80e141 search IDs were read against the same hashed originals.
No baseline test, search, open or model call was repeated. Baseline six hits are
small chunks, whereas new six results are structural blocks; per-case bytes and
annotated support counts are saved, so this is not an equal-payload precision
comparison. Baseline has no top-64 pool; controls have no matched historical
queries. Baseline later source opens are a separate research outcome.

Examples of baseline-six-hit to new-returned annotated-span coverage: S01 1/3 to
3/3; S02 1/4 to 4/4; S03 10/17 to 17/17; S06 0/6 to 6/6; S09 3/5 to 5/5.
Supplier coverage for S04/S10 remains missing in both. S07's literal target stays
0/1, while equivalent consolidated numerical evidence is new; currency/unit
association is not borrowed from a parent-company table. These bounded gains do
not turn a failed integrated gate into superiority or general reliability.

## Resources, lifecycle and usage

Reused isolated environment and pinned model under
`data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/`:
Python 3.12, torch 2.6.0+cpu, transformers 4.57.6, sentencepiece 0.2.1.
Exact resolved dependencies/wheel hashes are in `dependency-manifest.json` and
`installed-versions.json`; model files/hashes in `model/snapshot.json`.
Model: BAAI/bge-reranker-v2-m3 revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
Safetensors SHA-256:
`d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.
No new installs or downloads in this continuation.

| Attempt | Wall seconds | Completed forwards | Initialization total | Forward interval total |
|---|---:|---:|---:|---:|
| neural-1 | 30.38 | 31 | 2.88s | 24.32s |
| neural-2 | 755.60 | 858 | 40.29s | 674.15s |
| neural-3 | 383.62 | 352 | 31.55s | 320.93s |

Total neural wall: **1,169.60s**; **1,375 charged pairs**, including failed
reservations, versus **1,241 completed actual forwards**. First attempt fails
30s S01; second fails C02 at 150s; third uses recorded 300s/search settings after
observed long-table scoring and duplicate work. The cumulative amended neural
ceiling was 1,800 seconds / 2,048 charged pairs, not reset between attempts.
Initialization ranges 2.855–2.922s. Final eleven searches range 5.91–112.05s.
Peak sampled worker RSS was **2,191,339,520 bytes (~2.04 GiB)**, below 8 GiB.
CPU float32, batch one, four threads, one worker at a time; all children reaped.

The original 600s evaluation and 30s/search/120s-stage production feasibility
**did not pass**. Authorized engineering limits allowed investigation and
completion; they do not retrospectively pass original budgets. All-case
assessment completion is also distinct from quality acceptance.

Initialization and forward timings are directly observed separately. Forward
intervals exclude tokenizer/window work and IPC; end-to-end wall includes those
plus hashing, preparation, startup, observers and cleanup. Do not sum nested
intervals. Separate process-tree/parent RSS was not captured; sampled worker RSS
is not a hard cap. OS file cache warmed without control. The host assistant's
own usage is unavailable; the continuation's controlled generative counters are
**0 calls, 0 invocation seconds, 0 observable provider tokens**. No report helper
was invoked. Final elapsed time is recorded in continuation.json.

## Review and stopping decision

Reused the completed 56 deterministic checks. Focused affected checks recorded
in PREPARATION-CORRECTION.md passed: 16 preparation/navigation checks, seven
paragraph/preparation checks after the context change, and one injected neural
window-cache contract check. These prove contracts, not neural quality. Black
and focused pylint results are saved. No broad test or historical model rerun.

Reviewed code changes are generic; the assessor annotations remain in offline
artifacts only. Full returned originals were checked against canonical spans
and version hashes. The remaining blockers have been localized: candidate recall
for broad multi-facet queries, excessive irrelevant returned blocks even when the
answer ranks first, and residual table/context ambiguity. Further tuning is not
performed to chase these cases. The frozen quality gate is material and blocks
the company/report stage under the latest instruction. Historical useful industry
notes and company evidence remain available unchanged, but are not relabeled as
a newly reviewed report. No background jobs remain.
