# Operational retrieval campaign — setup complete, readiness blocked

The isolated dependency environment and pinned reranker artifacts are prepared.
The production-path evaluation failed its first search's time budget before
model initialization. **No new reviewed photomask report was produced.**
Company research, follow-up, synthesis, review and export were not admitted:
the user's frozen readiness/quality gate did not pass. Existing Chinese notes
and PDFs remain useful historical outputs, not newly reviewed deliverables.

Runtime is unchanged at `0aa3f2f`; frozen proposal/annotations are from `5bda1fb`.
The user authorized continuation beyond proposal-only boundaries, with one new
three-hour campaign, at most 16 sequential generative calls/3,600 summed seconds/
40,000 observable output-reasoning tokens, one correction and targeted rerun.
That continuation remained conditional on readiness/quality. No old allowance or
ledger was reset. No completed deterministic tests were repeated.

## Exact artifacts

New artifact directory:
`/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/`

- [Campaign record](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/campaign.json)
- [Assessment and first divergence](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/assessment.json)
- [Raw evaluation output](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/neural-results.json)
- [Evaluation usage](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/neural-usage.json)
- [Frozen observer/runtime hashes](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/execution-seal.json)
- [Resolved dependency versions, wheel URLs and hashes](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/dependency-manifest.json)
- [Installed versions](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/installed-versions.json)
- [Model revision and artifact hashes](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/model/snapshot.json)
- [Preservation check](../../../data/redesign/coherent-retrieval/campaign-20260912T005532Z/preservation.json)

Environment: the artifact directory's `preparation/.venv` is a real isolated
virtual environment. The existing worktree `.venv` symlink/shared installation
was not modified. Installed CPU PyTorch `2.6.0+cpu`, Transformers `4.57.6`,
SentencePiece `0.2.1`; all resolved transitive packages and wheel hashes are in
the manifest. Source imports still use the unchanged worktree `src`.

Model: `BAAI/bge-reranker-v2-m3` at full revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, resolved from official remote metadata.
The 2,271,071,852-byte safetensors file has SHA-256
`d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.
Tokenizer/config/README hashes are recorded individually. License attribution is
Apache-2.0 from pinned repository metadata/README; no separate LICENSE file was
listed among acquired repository files. No moving-revision or alternate-model
loading occurred.

## Actual execution and limits

| Measure | Observed |
|---|---:|
| Campaign start | 2026-09-12 00:55:32 UTC |
| Dependency downloaded payload/metadata | 441,399,067 bytes |
| Dependency preparation recorded elapsed | 205.68 s, conservatively including post-install bookkeeping |
| Sampled peak pip RSS | 243,056,640 bytes |
| Installed bytes at setup monitor completion | 1,375,437,070 bytes |
| Successful model payload/metadata | 2,293,264,802 bytes |
| Model preparation elapsed | 190.49 s, including metadata failure/retry |
| Local evaluation elapsed | 61.52 s |
| S01 complete search wall time | 61.51 s; 30 s limit failed |
| Runtime search/stage counter | 60.55 s |
| Candidate phase | 11.85 s |
| Remaining pre-scoring context/trace preparation | approximately 48.70 s, derived from nested phase boundaries |
| Post-counter result/trace completion | approximately 0.96 s |
| Model initialization/scoring time | Unmeasured: neither started |
| Neural pairs / scorer processes | 0 / 0 |
| Generative calls / seconds / output tokens | 0 / 0 / 0 |
| Correction / targeted rerun | 1 / 1, metadata request only |

The first official metadata API request returned HTTP429. A single targeted
retry with a descriptive User-Agent returned HTTP200; this does not prove why
the server changed its response. The correction/retry allowance was explicitly
charged before that request. There was no remaining correction/rerun after the
readiness failure. The first error body was not retained/counted; successful
payload counts exclude that unknown error body and TLS overhead. Dependency
accounting covered pip response reads, including metadata; initial resolver RSS
preceded the monitor and is unknown. These are disclosed measurement limits,
not claims of exact wire-byte or transient-memory enforcement.

The 16 query strings, source scopes, relevance annotations and criteria were
reused unchanged. Control fixture preparation only wrote into a new derivative
corpus; inherited read-only permissions were relaxed on its new root, never on
the original corpus. The observer was sealed before evaluation and no neural
warm-up or alternate scoring path was run.

## First divergence and separate outcomes

S01's raw candidate pool contained Qingyi `c1919` and `c1920`; `c1921` was absent
from the raw 64 but present in the structural context around `c1920`. All three
frozen financial excerpts were available across candidate reading contexts.
Thus the S01 support anchor was present, and the missing output cannot be
attributed simply to absent source/index coverage. Structural associations were
still labeled unknown and are not factual certification.

The retrieval function constructs its deadline before candidate work, but only
checks expiry after all 64 reading windows have been prepared. It then returns
`reranker_deadline` without starting the scorer. The 30-second value is therefore
not a hard preemption boundary for candidate/context preparation. Static review
shows each window deep-copies source metadata, rebuilds sorted structural units
and repeatedly scans chunk bindings. The relative cost of those operations and
the external observer was not isolated. All reported time includes observer
overhead; no uninstrumented result or actual model latency is inferred.

- **Candidate coverage:** one observed case, direct anchors for 2/3 frozen raw
  excerpts; candidate views contain all three. Fifteen cases unassessed.
- **Reranking/relevance:** unassessed; zero neural pairs and zero returned blocks.
  An execution error is not a neural relevance score of zero.
- **Delivered complete context:** unassessed; no evidence returned to research.
  Candidate-context presence does not establish researcher/writer delivery.
- **Evaluation completion:** incomplete; S01 errored, S02–S12/C01–C04 unexecuted.
- **Production feasibility:** failed the observed search budget. The stage's
  120-second and outer 600-second ceilings do not override that failure.
- **Quality/report/repeatability:** not established. No independent review or new
  report-quality claim is made.

The saved baseline's exact S01 six-hit list includes `c1920`, with a recorded
0.66-second lexical search. Its candidate depth, result units and instrumentation
differ, so this is not a controlled latency or precision comparison. Baseline
opens subsequently supplied all three financial excerpts. No baseline top-64
trace exists; all control queries are unmatched. The prior 103-versus-96 handoff
loss and completed 103-passage deterministic preservation replay remain valid,
separate findings; neither establishes this scorer's quality or CPU feasibility.

The concrete next technical boundary is cooperative deadline enforcement and
bounded reuse of immutable per-source reading indexes, with lower-overhead phase
observation. That is a diagnosis, not an executed fix or a guarantee of adequacy.
No additional change/rerun was made after the allowance was consumed.

## Useful historical Chinese outputs, preserved unchanged

- [Industry notes](../../../../EvidenceAlpha/data/redesign/existing-corpus-campaign-2/delivery/industry-research-notes.md)
- [Industry notes PDF](../../../../EvidenceAlpha/data/redesign/existing-corpus-campaign-2/delivery/industry-research-notes.pdf)
- [Industry original evidence](../../../../EvidenceAlpha/data/redesign/existing-corpus-campaign-2/delivery/industry-retrieved-evidence.json)
- [Completed company notes](../../../../EvidenceAlpha/data/redesign/company-stage-corrected/delivery/company-notes.md)
- [Previously repaired company PDF derivative](../../../data/redesign/coherent-retrieval/pdf/repaired-derivative/report.pdf)

Industry notes cover definitions/value chain, imported equipment, barriers,
validation/commercialization, demand and risks. The baseline company notes contain
supported financial totals and useful technical distinctions but retain material
explanation/relationship gaps. These notes are not a complete independently
reviewed investor report. The PDF derivative and its prior text-preservation/page
inspection results were reused; no export/inspection was repeated this campaign.

All 56 baseline frozen files retained their hashes, as did the frozen evaluation
inputs. Runtime code, shared work, original source corpus and historical ledgers
were preserved. New logs, partial results and installed/downloaded artifacts remain
available. The campaign is closed, with no campaign background jobs or further
model/report work scheduled.
