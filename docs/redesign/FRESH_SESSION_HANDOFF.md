# Fresh-session handoff — transition test awaiting authorization

Checkout: `/home/cobot/cobot_storage/webproject/EvidenceAlpha`.
Branch: `research-quality-upgrade`.
HEAD verified before saving this handoff:
`451d00fb6a122575233342f439410a2a612ce422`; working tree was clean.
This handoff is saved in a subsequent **documentation-only commit**. That commit
is not the frozen test candidate. Resolve its exact HEAD with
`git log -1 --format=%H -- docs/redesign/FRESH_SESSION_HANDOFF.md`, then verify
`git rev-parse HEAD` and `git status --short`; preserve any later user work.

## Current instructions and authoritative paths

The prompt clarification and transition-test preparation are **complete**.
Do not repeat either, rerun writing-only polishing, or restart historical work.
The next task is the proposed research-to-writing transition test, **only after
explicit authorization in the fresh session**. This handoff grants none.

Paths below are relative to the checkout:

- `docs/redesign/transition-test/PROPOSAL.md`: current test scope, ceilings,
  predeclared assessor outcomes, normal-transition versus timeout classification.
- `docs/redesign/transition-test/case.json`: proposed input; no seeded passages,
  prior answer, target chunk or expected value in the worker task.
- `data/redesign/transition-test/freeze.json`: authoritative full candidate,
  code/prompt/settings/input/corpus hashes and links to unchanged ledgers.
- `data/redesign/transition-test/frozen/`: read-only code, prompts, settings,
  case and proposal for candidate **451d00f** (full SHA above). This candidate
  has offline validation only; it has not received a model evaluation.
- `data/redesign/focused-diagnostic/frozen/corpus/`: existing immutable corpus.
- `docs/redesign/ACTIVE_CODE_MAP.md`: runtime navigation.
- `AGENTS.md` and `docs/redesign-package/00-START-HERE.md`: project conventions;
  package 07 owns historical numerical policy, 08 code quality. Current user
  scope and any fresh explicit allowance control the next bounded test.

Verify freeze hashes before any future admission. The case SHA256 is
`7d5e4bb12149a070d40461c876ba6c6aa980a1a460f7bb310fb9a4ca47fd78a5`.
Never edit artifacts read by an active evaluation. No new driver/admission has
been activated; any authorized execution must enforce the proposed single-attempt
limits and link its separate allowance to the three ledgers below.

## Proposed next test, not authorized yet

One focused Luw company stage using GPT-5.6 Sol / medium and the existing corpus:
180 seconds elapsed, at most three sequential calls, 175 summed invocation
seconds, 16,000 observable output/reasoning tokens without double counting,
one concurrent call. No acquisition, retries, fallback, reviewer or full report.
`final_notes_only=False`, `tool_rounds=3`; current allocation is approximately
115 seconds evidence, at most 60 seconds writing, five seconds margin.

Success requires focused retrieval of the missing financial evidence, preservation
into durable context, a **distinct tool-free writing request**, and complete,
supported notes within the caps. Assess completion and factual support separately.
If evidence times out, preserve the failed call and stop further model admission
under the proposed diagnostic policy. This is not normal-transition success or
live timeout-recovery validation. Ordinary recovery remains tested offline.

## Historical evidence and consumed allowances

These records are evidence, **not current execution authorization**:

- `docs/redesign/RUN_BUDGET.json`: original campaign exhausted; preserve clock
  and counters. No further full runs.
- `docs/redesign/FOCUSED_DIAGNOSTIC_BUDGET.json`: A failed; stopped by policy.
  Unused B/C numbers do not authorize continuation.
- `data/redesign/saved-writing-test/authorization-usage.json`: explicit separate
  authorization for the completed single writing call; consumed. The results
  document already records this authorization. Any recap implying otherwise
  was incorrect. All three ledger hashes are in the transition freeze.
- `docs/redesign/saved-writing-test/RESULTS.md`: accepted **successful completion
  test with factual qualifications**, not full product acceptance. Evaluated
  candidate was `7b87dc9`, not the new `451d00f` prompt candidate.
- Original output, unchanged:
  `data/redesign/saved-writing-test/stages/company/31ced4a7166f/output.{md,json}`.
  Exact calls/context/accounting remain alongside it; preservation hashes are
  in `data/redesign/saved-writing-test/preservation-manifest.json`.

That call completed in 50.73 seconds (50.19 invocation seconds), no tools;
19,452 input and 2,467 output tokens, with 516 separately reported reasoning
not added because overlap is unknown. It did not test research-to-writing.
Key company/technical attributions passed inspection. Qualifications: prose
mistook packet absence for full-document absence of Luw revenue; requested
disclosure dates were omitted; phase-specific scope was not fully supported.
The original answer is preserved, not retrospectively corrected.

The single general company-prompt paragraph now addresses those three issues.
Existing 17 phase/context tests passed; Black checked 21 files and focused pylint
was clean. Reuse these checks; no new semantic rules, roles or review loop.

Remaining limitations: normal live research-to-writing completion is unvalidated;
repeatability and general factual accuracy are unknown; full product acceptance
has not been achieved. Effective model/effort were not echoed by the provider;
full wire context, reasoning overlap and account usage remain unobservable.
No native visual-review acceptance is established. Historical failed freezes,
corpora and outputs must remain intact. Older HANDOFF/NEXT_SESSION sections and
Stage 1 kickoff describe earlier states, not permission to relaunch campaigns.

No model calls were made while preparing this handoff. No children were launched.
No push, merge, deployment or credential/account changes are authorized.
