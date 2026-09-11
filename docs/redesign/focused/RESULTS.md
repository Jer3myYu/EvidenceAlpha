# Focused correction results — 2026-09-11

**Charged validation stopped on case A's completion failure. No factual model improvement or full-report acceptance is established.** B and C were not run. No retry, further runtime patch, external acquisition or full report followed the failure.

Candidate commit: `79b997e` (`79b997e` is the evaluated code/prompt/settings version; later commits contain records only). All 47 accumulated offline tests passed, with Black and pylint checks clean after the final lint fix. The new read-only freeze contains 72 hashed files: `data/redesign/focused-diagnostic/frozen/`; its seal is `data/redesign/focused-diagnostic/freeze.json`. The earlier diagnosis freeze and historical source corpus were preserved.

## Outcomes

| Case | Outcome | What was established |
|---|---|---|
| A: company, 180s | Failed after 115.14s elapsed | Five tool-request responses, then a sixth invocation timed out. No final notes, comparison table or figure proposal. |
| B: preserved faulty draft review, 180s | Not run | A failed; no new reviewer findings or false-objection rate can be claimed. |
| C: preserved draft + preserved faulty findings, 300s | Not run | A/B adequacy prerequisite was not met. The 300s revision allocation is offline-tested only. |

Every observed search used an explicit issuer-source filter. Tool results retained the correct document identity and original locators. The joined Longtu c206/c207 passage and c186 mass-production statement were actually retrieved, as were Qingyi total revenue (c246) and semiconductor revenue (c695), Longtu total revenue (c280), and Luw's Luxin/technical passages (c43–c47). The model supplied **no final factual assertions**, so absence of observed swaps is not evidence that model attribution was fixed. No native tool calls were present in the preserved raw events; requested model/effort remained `gpt-5.6-sol`/`medium`. Server-side effective model/effort fields were not reported.

Luw's total-revenue row c30 was never retrieved. Both source-filtered queries combined financial and many technical terms and returned technical passages. An offline replay with the single query `营业收入` returned c30 first, with its original 115,523.17万元 value. See `data/redesign/focused-diagnostic/query-comparison.json`. This confirms a query-specific retrieval omission; it does not establish what the missing final answer would have said.

## Confirmed deadline and handoff failures

The outer A deadline was 14:56:58.659 UTC. The runner allocated 115s for evidence, 60s for final notes and 5s margin. The sixth call was admitted at 14:55:30.589 UTC with only 23.10s reserved to the evidence deadline. All six calls still had tools enabled; none entered the tool-free writing phase. The longest earlier completed invocation had already taken 30.21s. The nine-second early-transition threshold allowed this later 23-second evidence call to start despite that observed duration.

The child was killed at about 14:55:53.664 UTC, at the evidence cutoff, rather than at the 180-second outer deadline. Its 101-byte raw trace contains only `thread.started` and `turn.started`; there is no last message, normalized response or usable partial prose. The failure path exited before using the 60-second writing reserve. What the model was doing during that final call is unknown; “it was writing the final report” is a hypothesis, not a trace finding.

The new failed-worker handoff was emitted and correctly labeled `unsynthesized_evidence`. However, its first-12-unique-passages selection filled entirely with Longtu passages from the first tool round. It omitted all 27 retrieved Qingyi passages and all 13 retrieved Luw passages, plus 15 later Longtu passages. All 67 distinct passages remain recoverable from the unchanged event trace; only the compact fallback is incomplete. Thus the offline handoff path works, but the live selection policy is insufficient for a multi-company worker.

## Input growth and usage

| Invocation | Request UTF-8 bytes | Prior conversation bytes | Recorded model seconds | Output tokens |
|---|---:|---:|---:|---:|
| 0 | 10,558 | 2 | 12.13 | 321 |
| 1 | 20,732 | 10,174 | 30.21 | 377 |
| 2 | 33,446 | 22,888 | 14.23 | 462 |
| 3 | 50,234 | 39,676 | 12.03 | 427 |
| 4 | 62,945 | 52,387 | 15.18 | 466 |
| 5, failed | 74,052 | 63,494 | 22.98 | Unknown |

There were 17 tool results: 90 passage occurrences, 67 distinct passages and 23 repeats. Their JSON occupied 53,568 bytes: 8,293 original-text bytes, 36,494 bytes of repeated source identity fields, and 8,781 remaining locator/JSON bytes. Metadata figures use a documented field-partition estimate; conversation bytes include JSON escaping. Removing large source/index structures did not remove repetition: full title, issuer, URL and source handle were repeated per passage, and the accumulated assistant/tool history was resent on every fresh CLI invocation. Across six requests the client sent 251,967 bytes. The measured relationship to timeout is increased context and fewer remaining seconds; the trace cannot isolate model latency attributable to context size.

The frozen portable inputs are A 6,623 bytes (previously 7,752), B 21,727 (22,856) and C 26,893 (44,118). C is 39.0% smaller after removing plan/worker notes/gaps and compacting the source inventory; the draft and preserved findings are unchanged. B/C sizes are preparation measurements, not executed results.

New allowance used: **1/3 stage attempts, 6 model invocations, 106.7616/660 summed invocation seconds, 115.14s case elapsed, 2,053 known output tokens, and one invocation with unknown token usage**. A further 649 reasoning tokens were separately reported with unknown overlap; they were not added to output tokens. Known input tokens total 100,047 across the five completed calls. Tool execution took 4.60s. Concurrency was one; external searches/fetches and full runs were zero. The observable token total is incomplete, not a certified actual total below 16,000.

Historical plus additive invocation time is 2,125.5147s across 71 calls. The exhausted historical ledger remains byte-identical, SHA-256 `b3912add49941ed78906fe495ea7481f5809f5ae4a5ac6340c9328bba12a6c5d`; its original clock and attempts were not reset. The additive ledger is `docs/redesign/FOCUSED_DIAGNOSTIC_BUDGET.json`. Unused numerical allowance does not reopen this stopped experiment.

## Smallest remaining corrections, not implemented after the freeze

1. Transition a research worker to final notes before admitting an evidence call whose remaining evidence window is shorter than a conservative observed call duration. Preserve the enclosing deadline. Add the exact 30.21s-prior-call / 23.10s-remaining fake-clock case, including the transition to a tool-free final response. Do not recover by retrying the failed call.
2. Keep bounded fallback text distributed across retrieved documents and retain compact references for omitted passages. Test the observed first-source saturation with the saved 27/27/13 distribution; avoid a claim-certification graph.
3. Present identity once per source within a tool result, with each passage still explicitly bound to that source and its exact locator. Use single-metric searches for financial rows; the saved broad/narrow Luw comparison is a sufficient offline regression case. No new source acquisition or retrieval architecture is needed.

These are offline follow-up proposals, not a new patch/model campaign or additional charged authorization. The existing frozen candidate and failed case remain the comparison baseline. Any future model evaluation requires separate direction after this stop; no full report should be launched from this result.

## Artifacts and handoff

- Exact run: `data/redesign/focused-diagnostic/results/A/stages/company/654981fbb635/` (`input.json`, `timing.json`, `events.jsonl`, `call-*`, `handoff.json`, `status.json`).
- Case status: `data/redesign/focused-diagnostic/results/A/result.json`.
- Measurements: `data/redesign/focused-diagnostic/measurements.json`, reproducible with `docs/redesign/focused/measure_results.py` (offline only).
- Original query comparison, identity/header checks and access probes: `query-comparison.json`, `offline-originals.json`, `access.json` under the same diagnostic directory.
- Preserved faulty draft/figures and all case inputs are in the frozen snapshot. No new report or figure was completed. Reviewer visual capability remains text/data/hashes only; native pixel review was not validated.
- Final HEAD, working-tree status, frozen-hash check and child-process checks: `data/redesign/focused-diagnostic/final-state.json`, written after the records commit.
