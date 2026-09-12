# Optional verification in normal rubric review

Implemented at `b1e48c3`; see [live results](RESULTS.md), [frozen example configuration](execution.json) and [model resolution](MODEL-RESOLUTION.json). The subsequent prompt-only clarification explicitly gives the current run's web flag precedence over imported historical corpus-only wording for targeted verification. No additional live run was performed for that clarification.

## Normal entry point

`verify-report` uses the existing execution runner, recovery import, reviewer, source tools, evidence store, orchestrator routing, revision/recheck and exporter. It is not a separate evaluation harness. Use the exact installed-environment command in RESULTS.md. The existing `fixed-corpus` command remains offline and rejects a conflicting web-enabled configuration.

Relevant settings in the same execution configuration:

```json
{
  "web_verification": true,
  "information_cutoff": "2026-09-12",
  "reviewer_model": "gpt-6-astra",
  "reviewer_effort": "medium",
  "reviewer_context_tokens": null,
  "reviewer_output_tokens": 12000
}
```

These fields belong inside the existing `settings` object. The execution entry point resolves reviewer context from the installed catalog and overwrites caller-supplied context estimates. Do not confuse the output reservation with a confirmed transport cap. Existing search credentials remain in the configured environment file, never copied into report artifacts. No account/provider fallback is introduced.

## Reviewed implementation changes

- `config.py`, `providers.py`, `execution.py`: independently resolve available GPT-6 review capacity from the installed catalog; reject unavailable model/effort; retain existing research/writer models. The existing provider receives an explicit model selection. GPT-6 is not silently replaced by the old `claude_disabled` branch.
- `workflow.py`: save requested and actual-or-unreported model identity for every invocation; reject a reported mismatch. Apply reviewer-specific capacity to review/recheck requests. Web tools are exposed only to review, recheck and review-followup when explicitly enabled, not to ordinary research/writing.
- `tools.py`, `documents.py`: retain existing search/fetch implementation; capture original bytes/text, source ID/version, requested/captured URL and acquisition date. `external.json` records external origin and cutoff, and says publication date/reporting period must be verified from originals. Date uncertainty stays explicit; an HTTP modification date is not a reporting date. Fetching returns a requirement to open originals before reliance. Grouped evidence carries external provenance.
- `workflow.py`: refresh source inventories after acquisitions and preserve existing source aliases while appending new ones. Existing evidence assembly transfers originals and explicit omissions into review-followup, revision and recheck without a new first-N cap.
- `review.py`, `protocol.py`, prompts: retain the five criteria and targeted checks. Add uncertainty and unresolved-conflict routing. Sufficient evidence supports direct revision; essential unresolved gaps/conflicts route to existing focused research; explanation issues route to revision; genuine limitations route to qualification. Supplemental origins and unresolved findings survive. No sentence-certification requirement or new routing LLM call was added.
- `budget.py`, `tool_runner.py`: reuse the authoritative execution ledger and overall cancellation rather than reconstructing the wrong legacy ledger in tool subprocesses. Enabled search/fetch are telemetry under overall controls; fixed-corpus acquisition remains blocked. Existing one-worker, request capacity, watchdog and capture-resource protections remain.

Search snippets never become stored supporting originals automatically. Publication-date/cutoff compliance and citation entailment require targeted review; metadata is not factual certification. External source access remains subject to HTTP availability and installed search credentials. Redirects are exposed for explicit follow-up; there is no silent retry or paid fallback.

## Validation boundary

`tests/redesign/test_web_review.py` checks catalog selection/unavailability, mocked capture-to-handoff provenance and role/tool gating in the normal StageRunner. Existing focused review/workflow cases validate revision/follow-up routing and preservation. Live evidence in RESULTS.md demonstrates corpus-first review → direct revision → recheck → export. The live model chose no web calls or unresolved research gaps; those branches remain deterministic integration evidence, not demonstrated autonomous online research.

No sources, frozen baselines, old ledgers or previous reports were changed. No push or merge occurred.
