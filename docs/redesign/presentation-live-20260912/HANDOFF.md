# Presentation and normal-workflow delivery — 2026-09-12

Best report: the **fresh report’s presentation edition**, rubric-reviewed with targeted source checks, with disclosed coverage limitations. This is not exhaustive factual certification. Normal planning and research ran fresh; engineering failures required checkpoint recovery before follow-up. It was **not an uninterrupted run of the final code**.

Worktree: `/home/cobot/cobot_storage/webproject/EvidenceAlpha-fixed-corpus-integration`, branch `reviewer-contract-fix`. All paths below are relative to this worktree. Nothing pushed or merged. Shared sources and historical reports/ledgers remain unchanged.

## Deliverables

- Best Chinese Markdown/PDF: `data/redesign/presentation-live-20260912/delivery/report.md` and `report.pdf` (**11 pages**).
- Sourced chart and value-chain diagram: `delivery/report/figures/figure-1.png`, `figure-2.png`, with original specifications and generators alongside them; `delivery/figures.json` records provenance. These paths share the preceding data root.
- Source identities, URLs and versions: `delivery/source-map.json`; original five-source corpus remains in `continued-2/sources/`. Citation locators remain visible in the report.
- Final page images and inspection: `delivery/page-01.png` through `page-11.png`, `delivery/inspection.json`, `delivery/report.render.json`.
- Actual live rubric/recheck: `continued-2/stages/review/714e7b792da1/output.json` and `continued-2/stages/recheck/9a63680c2ad9/output.json`.
- Assessment/usage/lineage: `data/redesign/presentation-live-20260912/ASSESSMENT.json`, `PAYLOAD-LINEAGE.json`, `work-ledger.json`, `HISTORICAL-USAGE.json`.
- Earlier corrected report preserved at `data/redesign/fixed-corpus-integration/gpt6-web-live-20260912/reports/report.md` and `.pdf`. Its separately improved presentation copy remains at `data/redesign/presentation-live-20260912/presentation-ready/`. Neither was included in fresh research inputs.

The best edition retains Qingyi semiconductor revenue **2.04亿元 / +5.63%**, Luw’s named customers and distinct complete-set/single-mask/validation/supply/project milestones, and Longtu’s financial and technical qualifications. It also adds the reviewer’s supported substrate comparison and Qingyi display progress. The raw live export remains at `continued-2/reports/`; do not confuse its duplicate-image layout with the final delivery edition.

## Reusable changes and verification

Runtime/report code: **10c2436**; principal preceding commits: `60f0e25` (layout/fonts), `5d22cb0` (unlimited-call telemetry), `0f40d1c` (lossless evidence compaction), `6aaf541` (planner checkpoint import/page locators), `f57322d` (revision figures/Chinese citation notes), `47d2708` (measured heading placement). Reviewed diff: `data/redesign/presentation-live-20260912/implementation.patch` against `76b5dbf`.

Normal writer/revision prompts and exporter now use navy headings, charcoal body, embedded Noto Sans CJK SC regular/bold, 10.5pt body/9.5pt table text, measured continuous table grids, content-based widths, numeric alignment, repeated headers and intact rows. Table citations/commentary move into keyed notes. Bar values, one caption/source block, actual source names/links, report date/cutoff/version and page numbers are generated consistently. Revision images bind to the current figure manifest; headings reserve actual following-block height. Bold-prefix normalization no longer consumes adjacent inline emphasis.

Font diagnosis preserved rejected PDFs before correction. Unicode aliases/alternate glyph mappings caused extraction errors; canonical SC glyph mapping fixes them. The real report exposed one extension-A alias taking priority over the common character 胶; common unified Chinese characters now take priority. All Chinese/Latin/numerical body glyphs use Noto Sans CJK SC; embedded punctuation/space fallbacks are recorded in `delivery/font-and-html-check.json`. Font subsetting produced malformed output, so full fonts remain embedded (approximately 30 MB PDF). Text-preservation requirements were not relaxed. The layout uses existing PyMuPDF APIs; its documented table limitations motivated explicit row layout ([official Story documentation](https://pymupdf.readthedocs.io/en/latest/recipes-stories.html)).

Focused validation: five presentation/admission checks, two existing compaction/preservation checks plus one new exact-roundtrip check; ten generic workflow checks completed, with only the two initially affected font-export cases rerun after correction. Black/pylint and diff checks passed on changed code. Saved 946-original assembly and three-stage checkpoint import replays passed. The final saved-output export is a real exporter check, **not additional autonomous research**. Every final PDF page was inspected for borders, fonts, captions, chart values, links and pagination; unchanged Markdown-to-PDF text preservation passed. Charts were inspected separately because raster text is outside the text-extraction comparison.

Two disclosed post-review content edits are recorded in `delivery/editorial-changes.json`: replace the mixed-dimension commercialization arrow with separate dimensions; add original-source acronym/HTM explanations. These received local source checks, not another independent model review. The corresponding generic prompt clarification is prospective and was not exercised by another expensive model stage.

## Actual normal workflow

| Module | Actual observation | Limitation |
|---|---|---|
| Planning | One live call produced one comprehensive industry task and one company task from the original brief. | Familiar task; no alternative-plan/generalization claim. |
| Industry/company research | Six/five calls respectively, including protected tool-free writing. Full original five-source corpus, no imported answers. | Several essential supports were missed; five search requests used undeclared question IDs and were rejected before neural work, then corrected by the researcher. |
| Retrieval | Fifteen scored searches, 612 charged pairs, 665.793s total; 23.121–105.457s/search. Original ranking/window settings retained. | Search total times are recorded; fresh initialization/scoring/peak RSS are not separately reported by this command. Earlier measured reranker evaluation is reused, not rerun or relabeled. |
| Follow-up | Three calls, one exact context open restored Longtu’s split customer-name prefix. Original count 946→947; the restored support reached synthesis. | It did not recover Qingyi’s semiconductor revenue or substrate comparison. No hypothetical recovery counted as success. |
| Synthesis | One live call assembled a cited draft from 947 original fragments and research notes. | Initial absence claims and uneven company comparison required correction. |
| Review | Two requested GPT-6 calls; three independent original-page opens (Qingyi pp23/26, Longtu p4). Found three material problems without assessor hints. | Targeted source review, not every claim. Online verification available but unused. |
| Revision/recheck | Evidence was already sufficient, so normal routing sent findings directly to one writer revision, then one focused recheck. 1,036 originals reached both actual requests. | Post-review researcher follow-up was unnecessary and remains untested in this run. |
| Delivery | Normal command exported MD/charts/PDF; reusable presentation fixes rerendered the completed output without restarting model stages. | Final typography/editorial edition received local inspection, not another model review. |

The live recheck rated the first four criteria **Meets**, communication **Partly meets**, and decided **ready with disclosed limitations**. Its three material findings were resolved: Qingyi segment revenue/growth; quartz versus soda qualitative differences; Qingyi display technical progress with mass-production/development/research distinctions. No supplemental assessor findings were injected. The recheck did not inspect pixels; the implementer’s later page inspection addresses presentation separately.

Coverage remains **partial**: nine provisional scope items supported, four partial. Global market quantification, compatible segment margins/utilization, some supplier detail and Longtu profit-decline explanation remain unproven by delivered originals. Some provisional coverage explanations are stale after recovery (e.g. the repaired customer-name prefix and substrate omission); actual payloads, notes and review resolutions demonstrate those recoveries. They do not justify marking the entire source exhausted. All checked stage originals match canonical source spans; actual revision/recheck requests retain recovered revenue and technical support. The original retrieval benchmark remains **9 pass / 7 partial** and was not repeated.

## Failures, recovery and controls

Four additive execution records, all under the original **11:13:37–17:13:37 UTC** six-hour window:

1. `fresh`: zero calls; nullable call-ceiling arithmetic failed before planning. Fixed at `5d22cb0`.
2. `fresh-resumed`: fresh plan/research completed; evidence metadata expansion blocked follow-up/synthesis admission. Preserved 946 originals had only 59,016 original-text bytes; repeated geometry inflated requests. Lossless shared location/column encoding fixed the cause, without dropping text, changing ranking or raising capacity.
3. `continued`: zero calls; importer incorrectly required planner writing-context. Planner has no separate writing phase; corrected stage-specific hash validation at `6aaf541`.
4. `continued-2`: imported only this campaign’s successful fresh stages, then completed follow-up through export. Evaluated model runtime **6aaf541**, presentation runtime **10c2436**.

No successful research was restarted. Closed records retain their outcomes, including the first prelaunch manifest’s stale “running” state documented by `prelaunch-failure.json`. All 34 historical ledger/report hashes in `PRESERVATION.json` matched at finish. Preparation/retrieval speed, neural relevance, complete reading support and report quality remain separate assessments.

Hard controls: original six-hour deadline, one provider/local reranker worker, 900s invocation watchdog, 300s/search ceiling, four CPU threads and sampled reranker RSS ≤8 GiB, actual context/output capacity, cancellation and 16 MiB request-memory guard. Stage and cumulative call/time/token/pair values are guidance/telemetry; no cumulative 40k-token stop was enforced. Current call ceiling is null, as authorized.

Requested models: **17 GPT-5.6 Sol invocations (`gpt-5.6-sol`)**, **3 GPT-6 reviewer/rechecker invocations (`gpt-6-astra`)**, medium effort. Actual model identity was **unreported by the provider for all 20**; no silent fallback was configured. Installed catalog capacity: 272,000 context, 258,400 effective; 12,000 output reserve plus 4,096 transport reserve. Largest admitted saved final request was 235,236 UTF-8 bytes; provider-reported input peaked at 92,377 tokens. Byte counts are conservative estimates, not confirmed provider byte limits.

New usage: **20 calls, 1,290.829 generative seconds, 58,579 observable output tokens, 1,223,909 input tokens**. Reasoning tokens are already included in output and are not added twice; no invocation has unknown reported usage. Host coding-assistant usage is not observable by this application. Historical records sampled for preservation contain 38 distinct earlier calls, 2,114.454s and 100,035 observable tokens after deduplicating snapshots: scoped historical-plus-new totals **58 calls, 3,405.283s, 158,614 observable tokens**; not an all-time billing total. Elapsed engineering/waiting through report acceptance was 6,189.7s (about 1h43m), recorded in `work-ledger.json`; `delivery-receipt.json` includes final documentation/commit time.

Installed versions reused: PyMuPDF 1.28.2, fontTools 4.65.0, markdown-it-py 4.2.0, matplotlib 3.11.2, torch 2.6.0+cpu, transformers 4.57.6. Reranker remains BAAI/bge-reranker-v2-m3 at `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; model/font hashes remain saved in preparation records and `delivery/fonts/manifest.json`. No installations, downloads, model substitution, paid fallback or external research acquisition occurred.

## Runnable normal command

From the worktree above, use the installed isolated Python and current configuration:

```bash
PYTHONPATH=src /home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python -m evidencealpha verify-report --execution docs/redesign/presentation-live-20260912/RUN.json --output data/redesign/presentation-live-20260912/next-normal-run
```

This is a prospective reproduction command, **not another run launched by this task**. `RUN.json` has the original brief/corpus, no recovery imports, optional web verification and six-hour controls. Current frozen historical launch configs remain `execution.json` and `continue.json`; their actual invocations used output directories `fresh`, `fresh-resumed`, `continued`, `continued-2`. Their inherited descriptive `acceptance_provenance` text contained old two-hour/12-call wording; actual frozen settings/ledgers used the authorized six-hour/null-call policy. `RUN.json` corrects that descriptive metadata without rewriting frozen records. Local presentation reproduction alone: run `data/redesign/presentation-live-20260912/finish_presentation.py` with the same Python/PYTHONPATH, selecting a new output folder to preserve this delivery.

This campaign demonstrates useful fresh research, targeted corrective review, evidence-preserving normal routing and delivery **with bounded engineering recovery**. It does not establish uninterrupted repeatability of the final revision, complete factual review, or generalization to unseen questions/industries. Online acquisition and reviewer-triggered research were not needed and remain untested here. All application workers were stopped before delivery.
