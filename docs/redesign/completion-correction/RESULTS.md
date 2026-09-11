# Local completion correction — offline only

The runner now derives research, final-writing and fallback inputs from one durable `context-state.json`. Raw provider output, requests and tool events remain separate audit artifacts. This is a local change to context assembly and phase control; provider transport, original source storage, roles and ledger policy are retained.

## What changed

- `StageContext` owns deduplicated settled originals, the unchanged task, recent outcomes and unsuccessful-query records. Source identity/version appears once per group; each passage keeps its text, chunk ID and exact spans. Conflicting text/version at a settled locator fails rather than silently replacing evidence. Source/text hashes and parser/chunker versions are included in tool headers; full provenance remains in the source store.
- Every model request uses the same builder, including research requests. It preserves explicit unresolved questions, the last eight compact outcomes and up to sixteen unresolved unsuccessful-query records. An unsuccessful query is a retrieval status, not a judgment that a research question is answered. Long navigation metadata has an explicit preview/hash; original passages and user requirements are not silently truncated.
- The default request bound is 100,000 UTF-8 bytes, including instructions, tool definitions and JSON escaping. Repeated retrievals deduplicate instead of accumulating raw conversation. A task too large for that bound fails clearly. Evidence text is allocated across sources before redistributing unused capacity. Omitted text and all locators remain in the durable record; bounded reference previews disclose any omitted references. Source balancing is a coverage aid, not semantic completeness.
- Evidence and final-note phases have explicit transitions/outcomes. A conservative prior-call duration can trigger earlier writing. Independently, a supervisor-confirmed timeout at the evidence cutoff can end evidence collection and request one distinct tool-free writing call if time/rounds remain. It never retries the failed request. Cancellation, provider errors, quota handling and smaller deadline/cap failures do not become recoverable phase cutoffs.
- Failed invocations remain `failed`, with unknown usage preserved. Writing still requires ordinary ledger admission. The diagnostic ledger's stop-after-failure rule is unchanged: it denies writing after that failure even when nominal time remains. The existing stopped diagnostic cannot be reopened by this correction.
- Financial retrieval guidance keeps one metric and an explicit source filter per query; the saved broad/narrow comparison remains a regression. No company names, expected figures, new agent roles or semantic-certification rules were added to generic runtime code.

## Offline evidence

The accumulated suite passed: **64 tests in 9.91 seconds**. Concrete checks cover:

1. The prior 30.21s call / 23.10s remaining window and an unexpectedly admitted call reaching its cutoff. Both lead to a separate tool-free writing invocation under the ordinary ledger. The failed invocation remains failed. Under the diagnostic ledger, the same cutoff is preserved and writing admission is denied; no third provider call occurs.
2. Provider error, quota, cancellation, exhausted outer deadline, a different timeout deadline and exhausted rounds cannot gain recovery. Local sleeping subprocesses distinguish supervisor timeout from controller cancellation without invoking models.
3. The saved 27/27/13 source distribution retains all 67 distinct originals when they fit. Under a twelve-passage text view, all three sources receive four passages and all 55 omitted references survive. Character allocation also prevents a large first-source passage from erasing the smaller sources.
4. Durable reload preserves task, explicit questions and source versions. Repeated retrievals stabilize request size; older unsuccessful searches remain visible even after recent outcomes rotate. A smaller byte bound keeps the durable evidence intact and explicitly omits text/references in the model view. Final writing and fallback use the same builder.
5. The saved broad queries omit the financial row while the focused metric query retrieves it. The previously flat-format test was adapted only after retaining its assertions: a document issuer remains distinct from the other company discussed in its unchanged original passage.
6. A fixture-only writing invocation receives all 67 saved passages and zero available tools. This demonstrates the completion path and input delivery, not factual model competence.

Black and pylint results, the candidate commit and preservation hashes are recorded in `data/redesign/completion-correction/final-state.json`. No model calls, charged validation, research campaign, push or merge was performed. Existing deterministic fixture workflow tests are offline plumbing checks, not new research runs.

## Exact next proposed test — not executed or authorized here

Prepared input: `data/redesign/completion-correction/writing-only-case.json`; source/code/input hashes: `proposal-manifest.json` in the same directory. `prepare_case.py` verifies the 67 original passages against the immutable failed candidate's corpus before preparing the case. It does not add the later narrow-query financial row.

- One **company final-notes-only** stage using the diagnosed **GPT-5.6 Sol / medium** configuration.
- Invoke `StageRunner.run(..., final_notes_only=True, seconds=180)` with `tool_rounds=1`, fixed-corpus mode and one concurrent call. The writing call has at most 175 seconds after the five-second margin and remains bounded by any enclosing deadline. All research tools are absent from the request and the output schema permits zero tool calls.
- Supply the preserved company task, all 67 settled original passages with version/locator bindings, recent saved research outcomes and an explicit question about unsupported requirements. No source acquisition, additional searches, retries, reviewer or full report.
- **Completion success:** one complete final-notes response, with no requested/executed tools or additional calls.
- **Factual success, assessed separately:** correct company/subject attribution and source support for stated metrics; clearly retain missing information. Luw annual total revenue is absent from this packet and must remain a gap. A finished response alone does not establish factual accuracy.
- **Stop:** timeout, cancellation, admission denial, tool request, malformed/incomplete output, unsupported material assertion or any applicable cap. Preserve output and accounting; no repair-and-rerun loop.

This is a proposal requiring separate authorization and a permitted admission arrangement. Neither historical ledger supplies permission to execute it. No stronger model, larger campaign allowance, SDK migration or full-report acceptance is implied.
