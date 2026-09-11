# Proposed focused research-to-writing test — not authorized to run

The writing-only test is accepted as a successful completion test with documented
factual qualifications. Its original output is preserved. This next case tests
the normal research-to-writing path; it does not repeat writing-only polishing.

Candidate: the local commit containing this proposal and the single additional
company-prompt paragraph. The exact full commit, code/prompt hashes, settings,
input hash and existing immutable corpus manifest are sealed in
`data/redesign/transition-test/freeze.json` after commit. Use the read-only
snapshot's case and code; verify hashes before any future admission. No active
run may read changing inputs. No runtime code, roles or ledger policy changed.

Input: `case.json` in this directory (identical frozen copy under
`data/redesign/transition-test/frozen/`). A compact Luw company task starts with
source identity and unresolved financial/date questions, without seeded passages,
prior answers, plan, prior transcript, target chunk or expected financial value.
It uses the existing five-source frozen corpus; the task identifies the relevant
issuer/source and calls for focused metric queries with explicit source filters.
This isolates retrieval of the previously missing financial information and its
handoff into notes. It does not test company selection or multi-company coverage.

Proposed ceiling: **one stage attempt, 180 seconds elapsed, at most three
sequential GPT-5.6 Sol / medium calls, 175 summed invocation seconds, 16,000
observable output/reasoning tokens without double counting, one concurrent call**.
Use `StageRunner.run(..., final_notes_only=False, seconds=180)` and
`Settings(tool_rounds=3, workers=1, stage_seconds=180)`; unchanged 100,000-byte
request bound. There are at most two evidence calls and one tool-free writing
call. The runner may transition earlier. No external acquisition, retries,
reviewer, full report, model fallback or automatic rerun. Local fixed-corpus
search/open/calculation use the existing bounded tools and shared stage deadline.
No new execution driver or ledger is activated by preparation.

Under the current company allocation, evidence ends approximately 115 seconds
from stage start, writing has at most 60 seconds, and five seconds remain as
margin. The preceding successful writing-only call took 50.19 invocation seconds;
that supports trying the existing 60-second reserve for this smaller task, not a
guarantee of completion. An enclosing admission deadline may shorten the window.
The user must authorize this separate allowance before execution; record it
linked to all three existing ledgers, leaving counters and clocks unchanged.
Unknown usage stays unknown. Token reporting is post-call; stop further admission
at a known cap or unresolved usage, never assume an unknown value is zero.

## Predeclared outcomes — assessor only, not sent to the worker

1. Retrieval must actually return Luw source
   `fbbfaa667b9e5166472aa329bf48aa53890d3d43c9b1d54958fe8fe9faf6f394`,
   c30, with unchanged text/version/locator. It contains 2025 report-period
   revenue 115,523.17万元. Inspect period support too; a matching number alone
   is insufficient. Expected conversion is 11.552317亿元. No answer is seeded.
2. That evidence must survive into durable context and a **distinct tool-free
   final-writing request**, followed by complete notes within the stage/call/time
   caps. A research call that directly emits final prose is a completion result,
   but does not satisfy the intended distinct writing-transition observation.
3. Notes must bind the figure to Luw company total revenue, preserve any missing
   semiconductor split, provide requested dates with support or mark them
   unknown, and avoid document-absence or unsupported project-phase claims.
4. Record each request size, calls, tool outcomes, phase transitions, deadlines,
   elapsed time, available usage and fidelity findings separately from completion.
   Assess against saved originals offline, with no additional model calls.

**Normal transition success** requires no failed provider call: focused retrieval
settles, the ordinary phase controller enters writing (including an early reserve
or last-round transition), and a separate tool-free call completes supported notes.
Retrieval success without final notes is partial; completed notes with unsupported
material claims are completion-only, not factual success.

**Timeout recovery is distinct.** Do not intentionally cause a timeout in this
case. If an evidence call hits its cutoff, retain its failed status, partial audit,
settled evidence and usage; the proposed diagnostic stop-after-failure arrangement
must deny any new writing admission. Record normal-transition validation as
incomplete, not a demonstrated recovery or proof of poor reasoning. Ordinary-ledger
recovery remains covered offline; live recovery would need separate authorization
and an explicitly permitted policy. Cancellation, quota, provider error or any cap
also stops charged work. No failure relabeling, patch-and-rerun loop or automatic
second case.

## Reused offline evidence

Reuse `tests/redesign/test_completion_phases.py`: ordinary and diagnostic ledger
paths for 30.21s/23.10s early transition and unexpected cutoff; terminal failures;
source distribution, shared context, and saved broad/narrow financial queries.
No new tests or semantic rules are needed for the prompt-only clarification.
Focused results and preservation checks are recorded in the freeze artifact.
