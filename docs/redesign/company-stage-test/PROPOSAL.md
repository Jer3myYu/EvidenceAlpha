# Proposed single company-stage test — not launched

Purpose: distinguish **retrieval coverage**, **agent follow-up**, and
**completed useful notes** under the corrected timing/navigation. This is one
company-stage evaluation, not report production or a full pipeline rerun.

## Candidate and inputs

Freeze the current corrected runtime/configuration/prompts and record hashes
after separate authorization, before the first invocation. Keep the current
production scorer, source filters and top-six limit; do not run a BM25 arm.
Use the unchanged five-source full corpus at
`data/redesign/focused-diagnostic/frozen/corpus`, checking every original and
metadata hash. Evidence remains read-only; use the demonstrated runtime-state
access, without credential copying or relocation.

Reuse the saved company-stage **brief and assigned question**, plus original
source inventory/identity metadata. The question already covers all three
companies, finances, technology, drivers and representative relationships.
Preserve its wording and document that its reference to prior industry work
does not supply any industry findings in this isolated test. Omit the old
plan prose, notes, reports, tool results, selected passages, BM25 diagnostics
and assessor targets. Rebuild a fresh portable context with no settled
evidence. No planning or helper model invocation is needed.

The input origin is
`data/redesign/existing-corpus-campaign-2/attempt/stages/company/1644ce21fdd6/input.json`;
copy only the specified brief/task/source metadata fields, never the prior
stage state or execution clock. Record the reduced handoff explicitly.

## Proposed limits

- GPT-5.6 Sol, medium; one invocation at a time, no escalation or fallback.
- Six total model invocations maximum, matching the earlier company-stage
  turn allowance: at most five evidence turns and one tool-free writing turn.
  Earlier substantive completion is allowed; do not make filler calls.
- Worker elapsed limit 600 seconds; final writing reserve 180 seconds;
  invocation allowance 300 seconds, always clipped to remaining worker time.
  Writing may use unused research capacity, not just the reserve.
- At most 600 summed invocation seconds. Startup and API waiting count.
- Separate execution window of 780 seconds: 600 for the stage and 180 protected
  for saving/export/inspection. Record preflight separately and start the new
  clock only after readiness/any platform approval is resolved. No throwaway
  model probe, reused campaign clock or overlapping new phase timer.
- Proposed observable output/reasoning budget: 12,000 tokens without double
  counting. Record each call, including failed/unknown usage. Stop admission
  if exhausted; this is not a claim that a subscription CLI can enforce a
  hard mid-call output-token cap. The execution wrapper must disclose that
  limitation before launch if no enforceable output cap is available.

Use the shared StageRunner allocation, finite provider supervisor and
cancellation/cleanup. No retries, correction rerun or full workflow restart
is included in this proposal. Any timeout, quota/auth or launcher failure
stops model work and preserves all partial artifacts and its precise cause.

## Separate observations and acceptance

| Dimension | Observation | Material interpretation |
|---|---|---|
| Retrieval coverage | Save every actual query/filter, ranked results and subsequent opens; compare requested facts/relationships/drivers with originals offline. | Distinguish original absence from index presence, top-six exclusion and insufficient surrounding context. A successful open chosen by the assessor is not agent success. |
| Follow-up behavior | Trace what follows a heading, split sentence or incomplete table: targeted query, context open, informed completion or abandonment. | Useful narrowing/context recovery is positive. Repeated headings or abandoning an important gap despite remaining turns/time is a behavioral omission; disclose any turn/time constraint. Do not require a specific assessor query. |
| Writing completion | Preserve request allowance, phase/termination reason, final output, usage and complete notes. Trace retrieved explanation → writing context → notes. | Require usable Chinese company notes with separate financial and technical tables, exact references, representative relationships, issuer-attributed explanations where retrieved, and explicit material gaps. Completion without useful evidence and retrieval without completed notes are different outcomes. |

Assess a small representative set, not exhaustive recall. Correct issuer,
period/unit and company-total versus semiconductor-segment attribution are
material; retain Luw's currency qualification where needed. Distinguish
sample/validation/mass-production states. Management explanations remain
attributed opinion. Missing retrieved explanations do not prove full-document
absence. Minor style issues and disclosed nonessential gaps are nonblocking.

Produce notes Markdown and a generic PDF export if notes complete, plus raw
calls, ranked results, opens, timing/usage and a short original→retrieval→notes
trace. No manual factual polishing or independently reviewed-report claim.
If writing fails, deliver the saved stage evidence with its actual status.

This test can show whether the corrected path produces useful company notes.
It cannot isolate the causal effect of timing versus navigation, validate a
new ranker, prove general follow-up reliability, or validate synthesis/web
acquisition. No run or new authorization ledger has been started by preparing
this proposal; record separate additive authorization only when granted.
