# Photomask report execution-path review

**Verdict: requires specific integration fixes.** The normal entry point cannot
currently reproduce the delivered workflow from one documented command. Shared
retrieval, StageRunner and rendering components ran successfully; the orchestration
and evidence assembly depended on an execution harness and manual steps.
Reproducibility means the same controlled workflow/evidence lineage, not identical
stochastic prose or general factual reliability.

Reviewed checkout: `/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval`,
branch `coherent-retrieval-implementation` (not the original checkout’s uncommitted edits).
Verified HEAD: `5607a21184f4654ab9490438b95546259532fa70` (documentation commit).
`git diff cad87ed..HEAD -- src pyproject.toml` is empty: evaluated runtime remains
`cad87ed9fe865ea93e8b329543c805e4578d2bd3`. The worktree was initially clean.
This review inspected saved artifacts and current code only. No model calls,
downloads, benchmark, successful stage, pipeline or tests were repeated; explicit
caller branches and saved requests resolved the material uncertainties without
needing a deterministic reproduction. Historical files and code are unchanged.

## Evidence navigation

- [Execution results](INTEGRATED-COMPANY-RESULTS.md).
- **E** = [execution directory](../../../data/redesign/coherent-retrieval/integrated-company-20260912/).
- **H** = [saved harness](../../../data/redesign/coherent-retrieval/integrated-company-20260912/report_stage.py);
  exact stage-era versions: `E/harness-freezes/{initial,synthesis,revision,recheck}.py`.
- **C/F/S/V/R/K** = `E/report/stages/` followed respectively by
  `company/315e542c529b`, `followup/e7aa0a96afcf`, `synthesis/73236a20d6b8`,
  `review/8755ca0d8507`, `revision/4497f0859ebf`, `recheck/15aef08bb8cc`.
  Each contains inputs, requests, output, status and work-usage records.
- [Final report](../../../data/redesign/coherent-retrieval/integrated-company-20260912/delivery/final/photomask-report.md);
  export, source mapping and layout evidence: `E/delivery/final/`.

## Stage table

| Stage / expected behavior | Observed caller, input → output; completion | Evidence | Normal-path match / limitation |
|---|---|---|---|
| Brief / freeze | External launcher + H loaded historical production brief/task and five-source inventory → company portable input; code/settings frozen. | E/production-input-freeze.json; H:150–170 | Original fields unchanged; no benchmark answers. CLI full-case construction differs. |
| Planning / scoped tasks | **Bypassed**: reused an already scoped company task; no plan invocation. | E/report/company-portable.json; saved stage inventory | `workflow.run`:785 requires a plan and creates jobs from its tasks. This report did not evaluate that planner path. |
| Industry research / reuse | **Reused** notes, evidence and citation map from shared `data/redesign/existing-corpus-campaign-2/delivery/`. | H:197–205 | Normal resume reuses matching stages within its own manifest; no explicit import of this separate historical result. |
| Company research | H → StageRunner, original brief/corpus → C notes and durable originals; six calls, 12 searches; terminal response completed with **partial coverage**. | C/work-usage.json; E/company-assessment.json | Same candidate/reranker/reading code, custom fixed-corpus settings/accounting. Initial queries still mixed topics despite focused-query guidance. |
| Follow-up / close gaps | **Manually admitted**: `followup-question.txt` + initial notes → F supplement; three calls/two researcher-selected searches recovered Qingyi technology, suppliers and risks. | H:179–191; F/output.md | No stage-level follow-up branch in normal `workflow.run`. Question state guides prompts, not cross-stage orchestration. No expected facts/locators injected. |
| Evidence handoff | External transport preparation + H loaded `synthesis-originals.json`: company/F writing evidence + historical industry originals → 318 supplied passages. | E/synthesis-admission.json; E/evidence-preservation.json; H:136–146 | Assembly/compaction are harness-only; normal successful research handoff passes note strings, not this original-evidence set. |
| Synthesis | H sets `final_notes_only=True`; notes, citation map and 318 originals → S Markdown/chart specification; one call, zero supplied-evidence omissions. | H:192–212; S/writing-context.json; S/request-size.json | Normal synthesis can use tools but starts from notes/inventory/gaps without successful-stage originals. That potential re-retrieval is untested, not equivalent preservation. |
| Independent review | H supplies full draft/figure specification and all five source handles, **no pre-settled originals** → V limited review; two calls/one Longtu search. | H:213–219; V/call-0/normalized.json; V/call-1/limits.json; V/output.md | Normal review adds asset metadata/hashes and defaults to more turns, but also lacks coverage-based completion. Actual independent coverage: Longtu financials only. |
| Revision/recheck | Operator combined optional reviewer finding with two primary-agent source findings. H supplied originals and `additional-source-check.json` → R revision, then K focused recheck; one + two calls. K opened two Qingyi contexts and reported corrections resolved. | H:220–242; E/additional-source-check.json; K/output.md | Normal revision triggers only on independent review's material issues. V had **zero material issues**, so normal code would skip the actual revision/recheck. Supplemental evidence was source checking, not benchmark answer injection. |
| Markdown/chart/PDF | Separate export script → `_prepare_report`, chart, short source-label mapping, seven-page PDF; manual CSS derivative → six-page final PDF. Text preservation and external pixel inspection passed. | E/export_report.py; E/delivery/{revision,final}/ | Core renderer shared; label mapping, CSS derivative, visual inspection and consolidated closure are outside normal orchestration. Export success does not establish full factual review. |

## Confirmed defects, ranked by impact

1. **High — successful-research originals are not integrated into synthesis.**
   [workflow.py:852](../../../src/evidencealpha/workflow.py#L852) passes successful
   workers' note strings; only failed workers supply `unsynthesized_evidence`.
   StageRunner seeds settled originals only with `final_notes_only` (`:121`).
   H explicitly supplies/settles the joined originals. Normal synthesis could
   retrieve again, but that recovery was not evaluated. The reported 540,073 →
   81,545-byte reduction combines **selection and metadata compaction**; it is
   not a lossless reduction of every durable passage.

2. **High — completion/status can overstate coverage and review.**
   [workflow.py:919](../../../src/evidencealpha/workflow.py#L919) derives `reviewed`
   from the absence of remaining material issues, without examined-scope checks.
   Research failures become gaps and may still reach synthesis; ordinary partial
   notes trigger no essential-gap follow-up. StageRunner's complete status means
   a valid terminal response, not essential coverage. PDF failure can coexist
   with `reviewed`, since export status is attached afterward (`:952–977`).
   The successful harness's coverage decisions were external.

3. **High — normal CLI/budgets do not express the admitted workflow.**
   [cli.py:146](../../../src/evidencealpha/cli.py#L146) makes `run`/`resume`
   fixture-only. Charged `stage2` full cases force **live** mode (`:91`), enabling
   acquisition tools even when a corpus is supplied. Isolated cases are
   fixed-corpus but do not orchestrate the report. Standard Ledger's fixed policy
   includes 360s isolated/1,800s full attempts and different aggregate ceilings
   (`config.py:10`, `budget.py:70`), not the three-hour/16-call window with a
   1,620s company stage plus follow-up/report stages. Defaults lack model path
   and confirmed writer capacity, retain failed 30s/search/120s-stage settings,
   and allow two research workers. Merely changing a stage timeout is insufficient.

4. **High — intermediate payload selection hides useful findings.**
   C/call-2 through call-4 requests omit Luw revenue/profit already durable;
   call-5 final request includes them. Company writing receives 202/705 passages,
   omitting 503 references. Repeated revenue searches include an identical cache
   hit. [stage_context.py:380](../../../src/evidencealpha/stage_context.py#L380)
   repeats bundle locators during research but removes that catalog in final
   notes; selection uses provisional priority/adequacy and smaller incremental
   bundles under pressure (`:420–539`). Saved checks found intact original text,
   source versions and supplied qualifiers, not corruption. Final F evidence
   was 65/65, synthesis/revision 318/318. Downstream compaction and enlarged
   settings are not integrated into normal assembly.

5. **Medium — review scope was constrained by turns, not source access/time.**
   The review request covered the brief and all five source handles. The model
   chose one mixed Longtu search instead of opens. With `tool_rounds=2`, the next
   call became tool-free final notes (`workflow.py:163–218`), before exhaustion
   of 600s: 64.65s provider + 31.73s retrieval. No original support was preloaded.
   More turns alone would not prove broader coverage; examined/unexamined scope
   must survive into completion status. The independent review did not identify
   the two material issues later found by the primary agent.

6. **Medium — harness/finalization are not one portable, supervised command.**
   H accepts one stage name, uses absolute historical paths, externally prepared
   synthesis inputs/findings and a closed dated ledger. It is ignored under
   `data/`, not included in the pushed tracked implementation. Unchanged reruns
   reject completed stages; deleting prerequisites changes behavior (including
   an uncompacted fallback), not a supported fresh execution. CountedProvider
   is not a locked scheduler; wrapping the provider also bypasses StageRunner's
   provider-class capacity guard (capacity was explicitly supplied here).
   There is no outer alarm across setup, assembly, assessment and export. Normal
   CLI has an outer alarm but different budgets. `export_seconds` is a planning
   reserve, not a standalone render supervisor. No overrun/leaked job was observed;
   whole-harness failure/timeout behavior remains untested. Retrieval errors can
   become recorded tool errors and research can continue (`workflow.py:432–482`);
   cancellation and terminal provider failure do propagate/close the retriever.

## Required changes versus optional improvements

**Required for a reproducible normal entry point:**

- Support one explicit fixed-corpus report case/command, existing environment/model
  paths, versioned historical-industry import and scoped-task reuse. Freeze inputs
  and settings; use a new admitted ledger, never reopen a closed record or enable
  acquisition implicitly. Connect existing stages rather than manual launches.
- Carry successful research originals and explicit omissions through synthesis
  and revision. Integrate bounded transport compaction and validated per-stage
  payload settings; resolve the demonstrated intermediate visibility loss without
  changing ranking or supplying expected answers.
- Admit one bounded follow-up from essential research gaps; preserve the initial
  partial outcome and merge recovered support. Coverage labels remain provisional,
  not factual certification. Returned prose alone must not close known gaps.
- Preserve review scope separately from issue severity; provide usable original
  support and bounded checking opportunities. Route evidenced supplemental
  material findings through the revision contract. Do not require perfect
  relevance for each query or declare broad review from an empty issue list.
- Unify campaign/stage counters, one-worker admission, writing protection and
  end-to-end termination. Expose distinct execution, coverage, review and export
  outcomes to the caller. Integrate source mapping and accepted PDF layout
  configuration, retaining earlier exports and text/visual validation records.

**Optional:** repeated table headers/page numbers, more compact citation styling,
persisted peak-memory/phase telemetry and improved query efficiency. Broader
independent review would improve the report but cannot be claimed from this run.
No benchmark tuning, model substitution, broad test expansion or new architecture
cycle is implied. Document the single command after these specific transitions
and inputs exist in the normal path; there is no truthful equivalent command now.

The delivered report remains useful with stated gaps and limited independent
review. Functioning retrieval and successful PDF delivery do not establish
normal-entry-point reproducibility, complete factual review or general reliability.
