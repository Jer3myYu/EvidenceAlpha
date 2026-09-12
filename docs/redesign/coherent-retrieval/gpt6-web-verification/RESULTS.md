# GPT-6 rubric review with optional web verification

The normal command completed recovery from the original saved draft and research. It did not restart planning or successful research. Evaluated runtime: **b1e48c3**, branch `reviewer-contract-fix`. The post-run prompt clarification described below was not part of the live evaluation.

Outcome: execution complete, evidence coverage partial, rubric review complete, **ready with disclosed limitations**, export complete. This is rubric-reviewed with targeted source checks, not exhaustive factual verification. Historical reports remain unchanged; this is a separate candidate.

## Artifacts and command

All relative paths below are rooted at `/home/cobot/cobot_storage/webproject/EvidenceAlpha-fixed-corpus-integration`.

- Run: `data/redesign/fixed-corpus-integration/gpt6-web-live-20260912/`
- Candidate: `reports/report.md`, `reports/report.pdf`; sourced chart: `reports/revised/figures/figure-1.png` and its `.json` input, relative to the run.
- Initial review: `stages/review/08e984054a5a/output.json`.
- Revision: `stages/revision/2e4acfaea87f/output.json`.
- Focused recheck: `stages/recheck/a2cf1d06519f/output.json`.
- Frozen settings and code: `execution-freeze.json`; final outcomes: `command-result.json`, `manifest.json`.
- Usage: `execution-ledger.json`; independent offline lineage/usage checks: `assessment/CHECKS.json`; rendered-page inspection: `assessment/pages.png` and individual `page-*.png`.
- Every invocation has `call-*/model-identity.json`, `request.txt`, `context.json`, `command.json`, `normalized.json` and raw events.

The exact completed command, from the worktree root:

```bash
PYTHONPATH=src /home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python -m evidencealpha verify-report --execution docs/redesign/coherent-retrieval/gpt6-web-verification/execution.json --output data/redesign/fixed-corpus-integration/gpt6-web-live-20260912
```

Do not rerun into this preserved directory. Any future authorized run requires a fresh output directory. The committed execution configuration retains the original recovery descriptors, full five-source corpus, 13 questions and original brief. No previous reviews, expected answers, corrected candidate or supplemental findings were inserted. Information cutoff: **2026-09-12**; financial comparisons remain 2025, with Photronics' fiscal-year distinction retained.

## Model and capacity

Installed provider catalog resolved `gpt-6-astra`, medium effort, for review and recheck. Revision requested `gpt-5.6-sol`. No substitution, installations or downloads occurred. Reused export versions: PyMuPDF 1.28.2, markdown-it-py 4.2.0 and matplotlib 3.11.2. `MODEL-RESOLUTION.json` records catalog identity/hash and capacity discovery.

The installed catalog gives GPT-6 a 272,000-token context and 95% effective fraction: 258,400 tokens. The application independently reserves 12,000 output tokens and 4,096 transport tokens, leaving a conservative input allowance of 242,304. These are application reservations; the catalog does not expose a confirmed CLI output maximum. The official API page's 128,000 output maximum was **not** applied as a CLI guarantee. Largest actual request was 236,432 bytes; largest reported input was 92,415 tokens. No mandatory evidence was removed to admit it.

All six CLI responses omitted actual backend model identity. Each invocation honestly records `actual_model: null`, `not_reported_by_provider`, separately from its requested model. The explicit installed/CLI selection was GPT-6 for five review/recheck calls, but backend identity cannot be independently confirmed from these responses. No configured fallback supplies another model.

## Live behavior and rubric

| Stage | Actual behavior | Assessment |
|---|---|---|
| Recovery | Imported original draft, research and 13 questions; no new planning/research | Compatible saved-stage recovery, not a fresh uninterrupted pipeline |
| Review | Four GPT-6-requested calls; original corpus page/context opens; three material factual findings and one optional explanation issue | Independent targeted findings; no assessor answers in inputs |
| Routing | All three material issues had supporting originals; each routed directly to revision | No redundant focused research; the research-gap branch was not exercised live |
| Revision | One Sol-requested writing call; corrected facts and affected comparisons/conclusions | Original units, periods, customer roles and technical qualifiers retained |
| Recheck | One GPT-6-requested call; explicitly resolved the three findings; carried forward unaffected rubric judgments | Bounded recheck, not a new full-report review |
| Export | Chinese Markdown, sourced revenue chart and seven-page PDF | Text-preservation check passed; visual shortcomings remain |
| Optional web | Tools enabled, zero searches and zero fetches; reviewer found sufficient original-corpus support | Actual public-source acquisition and cutoff handling were **not exercised live** |

| Criterion | Initial | After revision/recheck |
|---|---|---|
| Answers the brief | Partly meets | Meets |
| Builds understanding | Partly meets | Partly meets |
| Provides useful analysis | Partly meets | Meets |
| Uses evidence responsibly | Partly meets | Meets |
| Communicates clearly | Partly meets | Partly meets |

Material corrections, independently found by the live reviewer:

1. Qingyi: add 2025 semiconductor-mask revenue **RMB 204 million (2.04亿元)** and **5.63% growth**, supported by annual-report c695–c696. Remove the incorrect missing-business-revenue statements while retaining the lack of a fully comparable three-company semiconductor-revenue series.
2. Luw: distinguish 90nm-and-above complete-set validation/supply, 40nm and 28nm single-mask validation/supply, 40nm complete-set sampling, and planned 28–14nm phase-two construction. Keep the separate 250–130nm expansion project separate. Original c43–c47 reaches revision and recheck, not merely candidate contexts.
3. Luw: add disclosed display and semiconductor customers from c25–c28, preserve anonymous customers, and distinguish downstream customers from upstream suppliers. Do not infer purchases or node-specific relationships from the customer list.

Post-run source/lineage inspection confirms every supporting quotation for these findings exists unchanged in both revision and recheck inputs. Mandatory original references increase **814 → 825 → 825**; the original set and source aliases survive. This demonstrates this handoff, not exhaustive citation validation. Initial review acknowledged some opened Qingyi IR context was represented by omission locators rather than retained text; it did not use that omitted text to justify a correction. Explicit omissions remain in subsequent inputs.

## Limitations and actual scope

Initial checks covered pivotal company figures, revenue-chart units, selected commercialization states, named customers, Qingyi semiconductor revenue and Photronics factory/fiscal-year context. Recheck examined the three changes and affected sections, inheriting other assessments. Neither model inspected rendered pixels or certified every sentence/the entire annual report.

Remaining gaps include supplier coverage, Luw semiconductor revenue/cash flow, and full verification of Longtu's profit-decline explanation. These are coverage gaps, not certified document-wide absences. Some local “未披露” wording remains broader than the actual checks; the reviewer recorded this as an optional wording issue, and it must not be read as absence certification. Core acronyms and display-generation terminology still need clearer newcomer explanations. No further automatic revision cycle was launched for these optional issues.

Human-side rendered-page inspection found readable Chinese and chart labels, but table continuations lack repeated headers, the final financial-table row occupies a sparse fourth page, and the forced fresh chart page increases whitespace. Duplicate chart-caption text remains. PDF export is technically complete, not a claim of polished layout or exhaustive review.

The imported historical brief retains corpus-only wording. Live reviewer instructions explicitly enabled optional verification; however, no web was used, so that run cannot establish how the model resolves the competing wording. After completion, review/recheck prompts were clarified prospectively: the explicit current-run verification flag governs targeted verification access, while substantive brief/cutoff remain unchanged. Historical configuration, requests and results were not rewritten. This clarification has not received another live invocation.

This is a combined model-and-web-capability change. The live candidate corrected more known omissions than the prior candidate, but no controlled experiment establishes that GPT-6 alone caused the improvement. The familiar photomask task does not establish generalization, and unused web capability is not evidence of successful web research. The historical retrieval benchmark remains 9 passes / 7 partial, unchanged.

## Usage and preservation

New run: **6 calls**, **338.141 seconds elapsed**, **302.052 summed generative seconds**, **11,421 observable output tokens**, with reported reasoning already included rather than added twice. Four review calls, one revision, one recheck. No unknown usage for these calls. Zero neural reranker work, web search or source fetch; no background workers remain. Application accounting excludes the host coding assistant's unobservable usage.

Across available integration ledgers, deduplicating invocation IDs and preferring completed reconciled records: **38 calls**, **2,114.454 summed generative seconds**, **100,035 observable output tokens**. This spans separate historical authorizations and excludes older differently structured campaigns. Counters were not reset or closed ledgers reopened. `PRESERVATION.json` hashes match all listed historical ledgers and both protected prior report files.

## Focused validation

Focused contract/workflow checks passed, including unavailable-model rejection, reviewer/rechecker selection, explicit offline/web boundaries, original capture with external provenance/cutoff, source alias stability and normal role-specific tool exposure. Three new web tests use injected provider/network results; they prove plumbing, not actual web reliability. The reused workflow/contract cases cover routing and unresolved finding preservation. Two initial fixture failures (HTML page locator and old reviewer-model expectation) were corrected and their affected checks passed. Black, pylint and diff-whitespace checks passed for the implementation. No broad benchmark or successful model stage was rerun.

Required live outcome is delivered with honest limits: improved separate candidate, actual rubric/recheck and preserved originals. Further public-source acquisition remains unproven in live execution; it was optional and was not forced merely to increase tool usage.
