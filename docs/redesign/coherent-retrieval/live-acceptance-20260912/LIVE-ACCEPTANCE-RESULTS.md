# Fresh normal-command acceptance — incomplete

The run produced useful Chinese industry/company notes and a sourced draft, but **did not pass integrated acceptance**. Recorded outcomes are **execution failed; coverage partial; review not started; export complete**. A PDF is not evidence of independent factual review. This familiar photomask task does not establish generalization to unseen questions or industries.

## Artifacts and execution identity

All paths below are relative to `/home/cobot/cobot_storage/webproject/EvidenceAlpha-fixed-corpus-integration`. Let `R` mean `data/redesign/fixed-corpus-integration/live-acceptance-20260912`.

- Unreviewed Chinese draft: `R/delivery-layout-corrected/report.md` and `report.pdf`; figure inputs/image/generator under `R/delivery-layout-corrected/draft/figures/`; `source-map.json` maps citations to the original inventory.
- Original normal-command export, unchanged: `R/reports/report.md`, `report.pdf`, `report.render.json`.
- Final machine outcome: `R/command-result-continuation-2.json`.
- Cumulative usage: `R/assessment/USAGE.json`; source-backed omission: `R/assessment/LUW-CUSTOMER-OMISSION.json`; rendering comparison: `R/assessment/RENDER-CHECK.json`.
- Authoritative cumulative ledger: `R/execution-ledger-continuation-2.json`. Its inherited invocation IDs are already charged; never add parent totals again. Original closed `R/execution-ledger.json` is preserved.
- Requests, raw provider events, normalized responses, evidence states and phase outcomes: `R/stages/`. Controller logs copied into `R/assessment/`.

Base integration was `77c67f58403c83acbe6a07caeac468ef475a9e70`. Admission/role routing was frozen at `59adef2`; same-run checkpoint continuation at `95ea72b`; lossless payload correction at `32f9b1800c2494cf793d4c216bffe7289bb5b522`. The three execution-freeze JSON files record actual code/settings. This acceptance therefore evaluates those recorded versions, not an unchanged 77c67f5. Earlier retrieval benchmark runtime cad87ed and documentation 5607a21 remain separate historical results.

Initial launch, from the worktree root:

```bash
PYTHONPATH=src /home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python -m evidencealpha fixed-corpus --execution docs/redesign/coherent-retrieval/live-acceptance-20260912/execution.json --output data/redesign/fixed-corpus-integration/live-acceptance-20260912
```

The live 22-call amendment used `execution-22.json` with `--continue-existing`. The final actual continuation used the same executable and output path with:

```text
--continue-existing --execution docs/redesign/coherent-retrieval/live-acceptance-20260912/execution-payload-corrected.json
```

These are historical commands, not instructions to relaunch a closed run. Continuations reused only completed outputs from this fresh run, with identity checks. No historical industry imports, scoped-task answers, evaluator queries/annotations, or selected passages were supplied. Original brief and full five-source production inventory are frozen in the execution configuration and `R/corpus-freeze.json`. External acquisition remained disabled. The planning constraint's original prose still says three turns, while its amended numeric field says six; the already-completed planner was not rerun. Actual researcher admission allowed six each.

## Module assessment

| Module | Actual behavior and evidence | Assessment / limitation |
|---|---|---|
| Planning and routing | Fresh plan `stages/plan/415e04dcf5b7`; exactly one comprehensive task per industry/company role. Role-based required-scope routing was corrected before affected research. | Completed. Assigned questions were retained, not silently dropped to fit scheduling. |
| Industry research | Six real calls including a final tool-free writing call; completed `stages/research-0/8c071b03ae70`. First two calls/checkpoint originated in `00660b57c410`; successful work was not repeated. | Useful value-chain, technology, commercialization and risk coverage. Market/China-global comparisons remain source-limited. No historical notes imported. |
| Company research | Six real calls including final tool-free writing; `stages/research-1/869063c09279`. Chose focused queries and Longtu context opens from its own findings. | Financial/technical tables and attributed explanations produced; essential relationship coverage remains incomplete. No assessor answers supplied. |
| Retrieval / reading | `R/actual-retrieval-summary.json`: 20 successful neural searches, 817 pairs, 597.384s total, 16.752–43.768s/search. Industry six searches, company fourteen. Original source identities and locators retained. | Actual functioning search, not perfect relevance or coverage. Fresh-worker production path used. These traces do not supply separately measured initialization/scoring time or a sampled peak-RSS summary; configured 8 GiB admission is not a measured peak claim. No benchmark rerun. |
| Follow-up | Initial partial coverage preserved. After payload correction, `stages/followup/8ccb90bd1f51` made one call, chose no tool calls, returned provisional discussion/coverage. Required final writing was denied by protected token allowance. | Incomplete, with no demonstrated new retrieval recovery. Model `undisclosed` status excluded Luw relationships from the essential-gap set despite known source support. It is not factual certification. |
| Evidence handoff | All 814 mandatory originals admitted after lossless transport correction; `R/payload-transport-verified/RESULTS.json` checks exact text, spans, versions, chunk bindings and support-reference sets. Actual synthesis `writing-context.json` retains 814 passages. | No first-N cap or text truncation introduced. Preservation applies to retrieved originals, not facts never found. Overlapping/redundant evidence still imposes payload pressure. |
| Synthesis | One actual call, `stages/synthesis/deb9e3d2d160`, produced Chinese narrative, separate financial/technical tables and sourced revenue chart. Original evidence and explicit upstream omissions were supplied. | Useful draft, not quality pass. Correctly distinguishes display/total/semiconductor revenue and technical stages; contains a material unsupported absence claim described below. |
| Independent review | `stages/review/5e567da447c4`; zero reviewer invocations. Minimum mandatory request 240,730 bytes versus frozen 240,000 (`R/review-payload-blocker.json`). | Entire review scope unexamined by the independent reviewer. No empty-findings/full-review inference is permitted. |
| Revision / recheck | Not invoked because review never admitted. | Untested live; no material-finding resolution demonstrated. Offline routing checks remain plumbing evidence only. |
| Markdown / chart / PDF | Original six-page export passed normalized text preservation. Visual inspection found the chart shrunk at page 3. Rendering-only fresh-page figure correction produced a readable page-4 chart with identical Markdown and six pages. | Corrected export saved separately under `delivery-layout-corrected`. It is an unreviewed draft with a render-only fix, not an end-to-end successful rerun. |
| Completion / cancellation | Failure recorded and useful draft exported; all invocations settled and workers exited. | Status separation worked. One uninterrupted documented-command success was not demonstrated: midrun admission amendment and payload correction required checkpoint continuation. |

## Material findings and stop reason

1. **Known customer evidence missed, then incorrectly called absent.** Luw original source `fbbfaa667b9e5166472aa329bf48aa53890d3d43c9b1d54958fe8fe9faf6f394`, c24–c29, explicitly names display and semiconductor customers. For example c25 contains 京东方、天马微电子、信利、TCL华星 (the last name continues into c26). The draft instead says its material names no customers/suppliers. Exact c25 text is absent from both company and synthesis writing originals. This is a coverage/reading miss plus an overclaimed absence, not proof that a retrieved qualifier was dropped. The post-run finding was never fed to an agent. Supplier naming remains a separate question.
2. **Independent review cannot fit the frozen payload.** Lossless encoding made follow-up and synthesis feasible without changing their evidence, but draft-plus-review obligations still exceed the limit by 730 bytes. No mandatory context was discarded and no budget was enlarged to manufacture admission. Review and material revision therefore remain unvalidated live.
3. **Call reservation did not protect sufficient output capacity.** Follow-up used 5,413 observable tokens before its final writing was blocked; synthesis then used 8,972. Only 3,598 observable tokens remain. Six downstream call slots alone do not guarantee enough capacity for review plus a comparable full revision. Unknown reasoning overlap further limits what can safely be promised.

Other qualifications remain: Luw currency is inferred and visibly labeled, Longtu profit-decline explanation and supplier relationships are incomplete, and the corpus is asymmetric. Technical “layout”, “sampling/validation”, “small-scale production” and “mass production” qualifiers survive in the draft. These positive checks do not substitute for full independent review. The frozen historical retrieval benchmark remains **9 pass / 7 partial**, across its preserved code versions; this run neither replaces nor upgrades it.

Stop: persistent mandatory review-payload blocker plus insufficient demonstrated remaining output capacity for complete review/revision. Further model work was stopped; successful research and the benchmark were not restarted. The report is delivered as an explicitly unreviewed draft, alongside the concrete factual gap.

## Usage and resource limits

Original clock began **2026-09-12 05:33:59 UTC**, deadline **08:33:59 UTC**; it was never reset. Command completion including waiting/corrections occurred after **2,416.888s (40m17s)**. Offline assessment/rendering continued inside that same window; final closure time is recorded separately in `R/assessment/SESSION-CLOSURE.json`.

Cumulative unique application invocations: **15 / 22**, **766.774 / 3,600 generative seconds**, **36,402 / 40,000 observable output tokens**. Distribution: planning 1, industry 6, company 6, follow-up 1, synthesis 1, review/revision/recheck 0. Separately reported reasoning tokens total 2,718, with unknown overlap; do not double count them as disjoint usage. If wholly additional, the upper sum would be 39,120. In-flight token limits cannot be enforced exactly by this adapter; host coding-session usage is not observable by the application. One completed paused-controller invocation was conservatively reconciled from its saved completion event and charged 18s, as documented in the ledger amendment.

Actual provider: configured GPT-5.6 Sol, medium, existing Codex adapter; no fallback/model substitution. Reranker revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, installed local model, four threads, one local worker, CPU production path, 8 GiB sampled worker ceiling, 300s/search and 900s/2,048-pair researcher limits. No installations, downloads or external research acquisition occurred. Source/runtime/version inventories and provider effective-setting events are preserved in the freeze and call artifacts.

## Focused verification and reviewed changes

Reused existing offline validation; no retrieval benchmark or successful model stage rerun. Admission/checkpoint and lossless transport corrections have saved focused deterministic checks; three transport/lineage/routing checks passed, with Black/pylint on affected modules. These establish contracts, not autonomous research quality. Final render-only correction passed `tests/redesign/test_stage2_fixes.py::test_tall_figure_and_long_table_source_survive_pdf_layout`, Black and pylint. The actual corrected PDF passed unchanged text-preservation checks, and its chart/table pages were inspected.

Changes are generic: role admission, same-run checkpoint accounting, reversible source-locator encoding and request-schema serialization, and figure page placement. No company-specific query, source ID, expected answer or benchmark condition entered runtime logic. Closed ledgers, source corpus and original exports remain unchanged. No push, merge or deployment. No background jobs remain.
