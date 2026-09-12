# Prospective live-run budget simplification

Applies to new `fixed-corpus` executions. No historical outcome, ledger, clock or report is changed. Existing failed acceptance remains failed/partial/unreviewed. No model, provider, benchmark or research stage was run for this change.

## Enforcement map and changes

| Site | Before | Prospective behavior |
|---|---|---|
| `budget.ExecutionLedger._check/reserve` | Overall time/calls plus cumulative tokens, unknown token usage, summed provider time, stage calls/time/tokens and downstream reserves could each reject admission. | Only overall deadline, admitted call ceiling, active attempt, one in-flight invocation and invocation watchdog reject admission. Settlement still records all measured/unknown usage. Reservation is atomic. |
| `workflow.StageRunner` | Stage deadline, stage turns/tool quota, research evidence deadline and separate final-writing time constrained work. | Live stages share the command deadline; stage call/time targets are supplied as scheduling guidance. A final tool-free researcher response is retained. Shared remaining-call guidance encourages writing, without a second reserve-based rejection. Stage targets cannot suppress useful context-dependent work. |
| `workflow.run` | Research/follow-up deadlines subtracted downstream stage allocations; role quotas independently restricted rounds. | ExecutionLedger stages use the overall deadline, including research and follow-up. Stage allocations and reserve settings remain guidance/compatible configuration fields. One follow-up stage and one revision/recheck remain workflow shape, not a new cumulative budget. |
| `retrieval.Retriever.search` | Separate cumulative retrieval seconds and pair ceilings rejected later searches. | Cumulative time/pairs remain trace telemetry. Per-search deadline/cancellation, sampled RSS protection and CPU threads remain. Candidate count, window size and scorer token windows remain retrieval parameters, not campaign stop rules. |
| `StageContext.request` / normal and replay callers | `writer_input_tokens` and `stage_context_bytes` imposed separate conservative payload gates, including the 240,000-byte estimate. | Live assembly uses supplied context capacity minus output/framing headroom and a distinct configurable request-memory limit. All mandatory originals must fit or admission explicitly fails. Existing all-evidence-first and explicit omission behavior is preserved. |
| `handoff.scope/merge_scope`, follow-up routing, prompts | `undisclosed` could complete essential coverage and bypass follow-up. | `undisclosed` remains provisional/partial and is included in essential follow-up gaps; only supported recovery resolves a gap. Researchers/reviewers are told to distinguish failure to find support from source-proven nondisclosure. |

The sole configuration inventory of remaining hard limits and their concrete purposes is **`src/evidencealpha/config.py: EXECUTION_HARD_LIMITS`**, alongside `Settings` defaults. Default provider watchdog is now 900 seconds; explicit configurations can override it. The new 16 MiB request-memory bound is a resource guard, not a provider context claim. Legacy diagnostic `Ledger` policy is retained for historical/isolated commands; `ExecutionLedger` carries a new policy marker and rejects mismatched old ledgers. Closed attempts cannot admit invocations. This change does not authorize resuming an old campaign.

Guidance fields remain readable for configuration compatibility: stage allocations/time/call targets, review rounds, company/provider/token targets, cumulative invocation/token targets, writing reserves, stage tool targets and cumulative retrieval pairs/time. Stage/cumulative targets do not independently terminate prospective live work. Actual deadline, admitted calls, per-request resource/watchdog limits, cancellation and explicit access failures still do. Unknown cumulative token usage is disclosed rather than used as a stop rule. No uncharged retry or parallel worker was added.

## Request capacity and review assembly

The prior 240,000 value was **not a confirmed provider byte limit**. The selector conservatively estimates one token per UTF-8 byte, including the serialized request and separate schema. It does not measure actual tokens. Prospective live callers no longer take the minimum with the separate `writer_input_tokens` target. They use `writer_context_tokens - writer_output_tokens - writer_transport_tokens`, while keeping memory protection separate.

The supplied historical capacity of 258,400 tokens, with 12,000 output headroom and 4,096 framing headroom, yields a conservative application allowance of 242,304. This is reuse of the supplied capacity, not new provider-capacity verification. Provider-added context remains partly unobservable; the provider's own context/output restrictions still apply. The Codex adapter does not expose an independently verified output-token stop knob: `writer_output_tokens` reserves headroom, it is not a claim of exact in-flight output enforcement. A future request that cannot fit mandatory originals must still fail explicitly. No support is silently truncated.

Offline reassembly of the saved tool-enabled review request with current prompts retained **814/814 originals**, with equal source identities, text, versions, original spans and chunk bindings: **241,418 bytes**, within 242,304. The tool-free view is 216,988 bytes. These are assembly probes before dynamic scheduling guidance, not a new reviewer result or proof every future request fits. Actual requests remain measured at admission. Evidence is saved in `data/redesign/fixed-corpus-integration/budget-simplification/REVIEW-TOOLS-ASSEMBLY.json` and `REVIEW-ASSEMBLY.json`; old review inputs/results are unchanged.

This removes the observed redundant gate without asserting that the Luw omission is repaired. The new absence handling makes such a gap eligible for investigation; actual recovery, broader independent review and material revision remain untested live. Explicit original evidence of nondisclosure can be described, but a coverage label alone does not certify corpus absence.

## Focused validation

- Integration checks: quota/telemetry overages and unknown usage no longer block; overall calls, expired deadline, inactive attempts and concurrency still block; tool-free writing survives a one-turn/0.001-second stage target.
- Injected retrieval check: cumulative pair/time targets can be exceeded, duplicate cache does not consume more pairs, cancellation still blocks work. No neural inference.
- Existing focused orchestration checks: follow-up/evidence/review/revision routing, supplemental original preservation, partial review and cancellation/failure propagation pass.
- Saved-review assembly preserves all originals; no historical provider stage is replayed live.
- Black, pylint and diff whitespace checks passed for affected modules. Saved artifacts are outside old campaign directories.

The final validation is deterministic plumbing and admission evidence. Relaxed budgets do not establish factual quality, review success or general reliability. No run is launched by this implementation.
