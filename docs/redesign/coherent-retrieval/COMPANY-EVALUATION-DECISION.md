# Decision: proceed with a separate integrated company-stage evaluation

This decision reuses the completed assessment; it does not amend READINESS.md,
EVALUATION.json, their frozen criteria, or the closed execution ledgers. The
retrieval benchmark remains 9 passes / 7 partial, assessed across preserved code
versions. No benchmark, provider call or test was executed for this decision.
Runtime remains cad87ed; no model substitution or retrieval tuning is required
before the separately scoped evaluation described here.

## Why the old gate blocked research

READINESS.md lines 81–105 require every individual query to have every bundle's
candidate anchor, a returned direct hit, >=50% relevant returned blocks and
complete supporting context. Its “Quality pass” paragraph explicitly makes any
partial query insufficient for provider-test admission. EVALUATION.json freezes
the queries and minimum-support annotations, including four controls, and repeats
the direct/context/unrelated grading rule. This was a conservative experimental
admission policy, not a runtime dependency or demonstrated necessary condition
for useful research notes. It evaluates single-query behavior; it does not test
whether a researcher selects evidence, opens context and follows up across turns.
The finite bundles also are not exhaustive coverage of the original brief.

Therefore a new integrated evaluation is justified as a different question,
not as a reinterpretation or pass of that benchmark. It must retain the original
failure and separately report its own outcome.

## What remains missing, and what existing tools can plausibly do

| Failure type | Saved observation | Integrated implication |
|---|---|---|
| Essential evidence missing from a query | S04 misses supplier evidence; S10 misses technology/driver/supplier anchors. These originals exist in the saved corpus. | A context open cannot recover a distant missing topic without a locator. Researcher-selected focused searches are plausible, but supplier/driver recovery has not been demonstrated. Missing essential coverage after the stage remains partial. |
| Complete support plus irrelevant results | S08, S11, C01 and C03 carry required meanings but fail the 50% relevance ratio. | The researcher can potentially retain the answer and discard unrelated blocks. These are efficiency/context-pressure defects, not absent answers. Actual notes and writing payload must demonstrate correct selection. |
| Units/relationships ambiguous | S07 returns equivalent consolidated figures, but unit association remains unverified; parent-company unit context cannot certify consolidated data. S11 retains core meanings while a trailing marketing sentence is incomplete. | Use original-page/surrounding/continuation opens where the returned locator provides a starting point. Qualify uncertain currency as the original brief permits; never infer a table subject or customer/supplier role from proximity. Do not complete missing sentences by guessing. |
| Runtime cost | Fresh initialization ~2.9s; repaired non-synthetic searches ~22–112s, mostly ~22–45s. Original 30s/search and 120s/stage failed. | The old 600s worker proposal is too tight for the previous 12-search workflow plus reasoning/writing. Use the bounded allocation below; completion is an observed outcome, not guaranteed by this estimate. |

Actual model-selected context recovery was demonstrated in preserved e80e141:
the researcher opened Qingyi technical context and Longtu c205–c209. The latter
was retrieved successfully but lost at the old 96-passage writing selection.
The existing 103-passage deterministic handoff replay now preserves it; that is
contract evidence, not a new live company-stage success. No baseline model test
is repeated. That researcher did not demonstrate a focused supplier/customer or
financial-driver search, so those follow-ups remain untested possibilities.

Current tools expose exact chunk opens, surrounding windows, original pages and
version-bound continuations. These bypass neural scoring but remain bounded;
a chunk open without surrounding returns only that chunk. Whole-source opens
above 24,000 characters reject rather than truncate, so opening the entire long
Qingyi annual report is not an assumed workaround. Page/continuation reading can
resolve local context; it cannot guarantee finding an unrelated missing topic.

## Separate scope and acceptance

Provide the original brief, task and full five-source inventory. Let the company
researcher choose its own focused queries and context opens. Do not supply frozen
query strings, assessor spans, expected figures, supplier names, old company
answers or coverage judgments as recovery hints. Existing industry notes and
original evidence remain preserved for later synthesis, not inserted as company
answer keys. The synthetic control is excluded from the production corpus.

Assess four outcomes, jointly, after the company stage:

1. **Essential coverage:** for each company, usable financial totals/period/units,
   products/applications and technical/project status; grounded operating-driver
   and risk explanations; representative relationship evidence with its correct
   role and scope. Named entities are required only where the source supplies
   them. Distinguish mass production, supply, validation, sampling and future
   plans. A genuinely undisclosed detail can remain an explicit corpus limitation;
   failure to retrieve known essential support is still partial, not “absent.”
2. **Grounded notes:** material comparisons and explanations trace to original
   source/version/locations; management explanations remain attributed. No
   unsupported technical upgrade, invented relationship, unit transfer or
   confusion between total and semiconductor revenue. Currency uncertainty can
   remain explicit under the original brief; it cannot become an unqualified
   comparable chart value.
3. **Evidence preservation:** the final writing input retains the original support
   used for essential claims, including explanations, headers, units and status
   qualifiers. Check actual retrieved → selected writing evidence → notes, not
   model-assigned coverage labels. A material dropped qualifier fails this outcome.
4. **Completion:** coherent Chinese company notes and sourced financial/technical
   comparison inputs finish within the admitted stage budget, with recorded usage
   and no surviving workers. Irrelevant results are recorded as cost/noise; no
   per-query precision threshold applies to this distinct evaluation.

Integrated pass means all four outcomes hold. Essential unresolved coverage gives
partial notes and a concrete gap; altered evidence or materially unsupported claims
fail grounding/preservation. Execution failure is recorded separately. A stage
pass permits downstream synthesis/review but is not itself an independently
reviewed final report. If one material gap remains, the already-authorized single
focused follow-up stage may address it from the brief and the researcher's own
notes; preserve the first stage's partial result and separately judge recovery.
No full benchmark or whole research-stage restart follows.

## Feasible bounded allocation

Allocate **30 minutes** to company execution plus immediate source/handoff
assessment: **27 minutes (1,620s) stage**, **3 minutes (180s) assessment**.
Within the stage, cap local retrieval at **900s cumulative**, provider invocation
time at **600s summed** (300s research decisions + protected 300s final writing),
and allow **120s** for opens, state assembly, startup and cleanup. All consume
the enclosing wall deadline; these are ceilings, not additive allowances beyond it.
Unused research time can reach writing within the provider/stage caps.

At observed costs, 12 mostly focused searches at 22–45s consume roughly 264–540s;
12 searches at the observed 112s long-table cost would exceed 900s and must stop
at the budget. This supports a trial, not a promise that all chosen searches fit.
Retain 300s/search as an engineering ceiling, with the effective deadline also
bounded by remaining retrieval/stage time and protected writing. One local worker,
four threads, CPU float32/batch one, sampled worker RSS <=8 GiB; no resident-model
benchmark substitution. Keep 2,048 charged pairs as a company-stage ceiling,
recorded separately from the already-consumed 1,375 evaluation pairs.

Use at most **six generative calls including final writing**, **32 tool calls**,
**300s/invocation**, and **12,000 observable output/reasoning tokens** without double
counting. Unknown usage prevents later admissions; in-flight token enforcement
limitations remain disclosed. This leaves ten calls, 3,000 generative seconds and
28,000 observable tokens from the prior 16/3,600/40,000 enclosing allowance for
follow-up/synthesis/review/revision, subject to its actual remaining elapsed time.
No counters or elapsed clock reset: the old continuation is closed; any execution
must retain its original deadline and consumed totals in an additive admission
record, and must not mutate/reopen the historical closed ledger. If elapsed
capacity is unavailable, this decision does not create a replacement allowance.

The saved report harness is unexecuted and is not the admission record. Before
launch, its execution-only settings/accounting must match this allocation and
current enclosing limits; this is not a retrieval-runtime defect or another design
cycle. No speculative reliability claim or perfect-query requirement is added.

Evidence: READINESS.md; EVALUATION.json; CONTINUATION-20260912-RESULTS.md;
`data/redesign/coherent-retrieval/preparation-correction-20260912/FINAL-ASSESSMENT.json`;
shared `docs/redesign/company-stage-corrected/RESULTS.md` and its saved trace.
