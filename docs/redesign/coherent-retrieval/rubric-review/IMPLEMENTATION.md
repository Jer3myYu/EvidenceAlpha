# User-focused reviewer and orchestrated corrections

Implemented on `reviewer-contract-fix`, based on `2b962cc`. Prompt/schema version:
`rubric-review-1`. This replaces active claim certification; historical results,
closed ledgers, frozen reports and prior implementation documents are unchanged.

## Behavior

The reviewer evaluates answers to the brief, newcomer understanding, useful
analysis, responsible evidence and clear communication. Each criterion receives
Meets / Partly meets / Does not meet with an explanation. There is no score or
weighted aggregate. Completion requires the five assessments and described actual
review scope, not an exact-text claim inventory or a verification record per
sentence. Synthesis no longer creates that inventory; the separate review-record
completion loop and claim-resolution machinery were removed.

Targeted source checks still focus on pivotal figures, commercialization status,
central conclusions, citation support and suspicious absence claims. Factual
objections require exact source references/quotations. Editorial issues and
requests for missing evidence do not invent quotations. Source quotation matching
checks provenance, not semantic entailment. The full authorized corpus remains
accessible through existing tools; fixed-corpus mode never enables the network.
Review navigation receives the brief's scoped requirements where available.

Normal `workflow.run` owns the following deterministic routing:

| Material issue | Action |
|---|---|
| Missing essential evidence | One shared `review-followup` research stage, then revision |
| Factual correction with available evidence | Revision, without redundant research |
| Explanation, comparison or organization | Revision |
| Genuine source limitation needing disclosure | Qualification in revision |

A negative complete rubric without an actionable issue list still routes one
consolidated revision based on that rubric; this routing is explicitly marked
`rubric_routing`, not an autonomous factual finding. Missing/incomplete rubric
output cannot become ready just because its issue list is empty.

The original pre-synthesis follow-up is retained. A reviewer-discovered gap can
now trigger one post-synthesis follow-up in the same bounded correction cycle.
There is no second post-review research round or third review. This reuses the
existing company researcher interface, scoped to the assigned gaps (including
industry questions), and the same deadline, call ledger, provider capacity,
writing protection and cancellation. No new model, agent or budget layer.

The initial issues remain in `initial_review_issues`. New follow-up originals,
writing-selected mandatory references, notes and selection omissions enter the
existing evidence assembly and reach both revision and recheck. Earlier follow-up
notes remain separate. Failed research preserves available handoff evidence and
its explicit failure; cancellation propagates to the enclosing workflow.

Recheck returns an explicit resolved/unresolved record for each routed issue.
Omitted records remain unresolved even when the new issue list is empty. New
material recheck findings also survive. Research coverage labels do not resolve
issues automatically. Recheck carries the initial rubric for unaffected criteria,
while distinguishing inherited assessment from newly examined scope.

`readiness` is ready / ready with disclosed limitations / needs revision.
Material unresolved issues, missing rubric assessment and a Does not meet rating
prevent readiness. Partial ratings prevent an unqualified ready decision.
Execution completion, research coverage, review assessment, readiness and PDF
export remain separate manifest fields. CLI output now includes readiness and
unresolved issues. Its exit code continues to describe execution/export success,
not report acceptance. `factual_status` explicitly says `targeted_checks_only`.

## Validation actually performed

- Focused pytest: `tests/redesign/test_review_contract.py` plus the existing
  `tests/redesign/test_workflow.py`: **13 passed**. After the final routing cleanup,
  the three directly affected contract tests passed again.
- Normal-workflow fixture checks used real local source opens and injected
  reviewer/researcher/rechecker outputs. They verified post-review research,
  delivery of new originals and notes to revision/recheck, a failed follow-up,
  omitted resolution retention, and distinct readiness outcomes.
- Existing workflow checks covered report/figure preservation, bounded revision,
  incomplete review, checkpoint reuse and invalidation. No retrieval benchmark,
  live provider, neural inference or successful research stage was repeated.
- Black, pylint on affected runtime and replay code, and `git diff --check`.

Saved-data normal-workflow replay:
`data/redesign/fixed-corpus-integration/rubric-review-replay-20260912-2/ASSESSMENT.json`
and `RESULT.json`. Its actual stage order was plan → research-0 → research-1 →
synthesis → review → review-followup → revision → recheck, followed by export.
All outputs were replayed or explicitly injected, not newly generated research.
The fixture isolates post-review routing by clearing historical pre-review scope
IDs; it is not an assertion that the old research fulfilled every requirement.

Synthesis received 814 originals; focused follow-up supplied 26 new originals.
All 26 reached revision and recheck with identical original reference/text pairs.
Their payloads contained 842 originals each. PDF export completed using saved
report/figure outputs. No new rendered-appearance or factual-quality judgment is
claimed. Saved-stage hashes match their historical descriptor, and corpus bytes
match the replay's copied corpus.

The first replay attempt failed on incompatible historical scope IDs; preserved
at `rubric-review-replay-20260912/`. The corrected orchestration completed once.
Its final checker initially assumed a single chunk ID and failed on structural
passages. The checker was corrected to use canonical original references, then
run against those existing payloads without repeating completed orchestration.
Both failures remain visible. New generative calls: **0**; neural calls: **0**.

## Entry point and limits

The normal entry point remains:

```sh
PYTHONPATH=src .venv/bin/python -m evidencealpha fixed-corpus \
  --execution /absolute/path/to/authorized-execution.json \
  --output /absolute/path/to/new-additive-run
```

Use the already-installed campaign environment when the execution configuration
requires it. No existing closed run should be relaunched. A saved old reviewer
assessment is not retroactively a rubric pass; old historical reviewer drivers
remain tied to their recorded commits. The unused `review_completion_calls`
configuration field is accepted only to load existing saved configurations; it
no longer controls execution.

The reproducible offline plumbing driver is `replay_saved.py` in this directory:

```sh
PYTHONPATH=src .venv/bin/python \
  docs/redesign/coherent-retrieval/rubric-review/replay_saved.py \
  --output /absolute/path/to/new-offline-replay
```

No live evaluation of the new rubric has been performed. Its ratings, prioritizing
useful gaps and resolving source interpretations remain model behaviors requiring
observation. The saved replay includes injected judgments and known historical
support; it cannot establish autonomous discovery or generalization. The next
live acceptance should reuse a compatible draft/research checkpoint and exercise
review → necessary focused follow-up → revision/recheck under an authorized active
window, without restarting research. The product claim is **rubric-reviewed with
targeted source checks**, never exhaustively fact-verified.
