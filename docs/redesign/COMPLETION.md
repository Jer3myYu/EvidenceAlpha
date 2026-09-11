# Stage 2 completion — attempt caps reached; product validation incomplete

Charged work has stopped at **10/10 isolated attempts and 2/2 full attempts**.
Permissions are working. This is **not an access-blocked campaign and not a
completed product validation**. Company, synthesis, production reviewer and one
revision rehearsals completed, but both genuine full reports ended
`draft_review_incomplete` when their single revision exceeded its deadline.
Material factual errors remain in the preserved drafts. No additional model
attempt, quota purchase, account change, push, merge or deployment occurred.

The original campaign start remains `1789098914.7327895`; it was never reset.
The prior access-blocked handoff is preserved in
`data/redesign/stage2-prior-completion/`. No continuation is scheduled.

## Permissions and implementation

Separate non-model probes verified writes to the checkout, `.git`, `~/.codex`
and `~/.codex/tmp`. A separate Codex app-server initialization and ephemeral
thread/start succeeded with `readOnly`, network access false and approval policy
never, without a model turn. Evidence:
`data/redesign/stage2-permission-check/result.json`. Local commits succeeded.
Intentional child evidence isolation was retained; native tool restrictions are
still described as best effort, not a proven fixed-corpus security guarantee.

The five uploaded review findings were addressed:

1. One absolute research deadline covers queued and active workers, including
   provider and external-acquisition subprocesses. Downstream synthesis,
   review/revision/recheck and export retain time. Fake-clock, two slow workers,
   downstream-reservation and process-group tests cover these boundaries.
2. The fresh-process CLI loop was measured before retention: eight model calls,
   109.315 model seconds, 23 tool calls and 0.245 tool seconds in the compact
   industry rehearsal; prompt bytes grew from 3,565 to 124,421. It remains an
   explicit SDK-first exception. No untested SDK replacement was introduced.
3. Claude quota events now cross the actual installed SDK RateLimitEvent /
   RateLimitInfo serialization-to-adapter boundary. Rejected named quota windows
   propagate; warnings and generic limits do not. Live Claude is untested.
4. Source validation/text and optional embedding vectors are cached by source
   and index versions. Queries do not re-embed an unchanged corpus. CRLF source
   reopening preserves original Unicode spans. Actual embeddings remain off.
5. Reviewer inputs explicitly disclose specifications/hashes/text only, with no
   native pixels. The operator inspected source pages, report pages and figures.
   Export defects found visually were repaired offline and retained separately.

Concrete integration repairs also added strict output framing after malformed
reviewer JSON, source-specific retrieval before top-k, exact chunk-ID guidance,
a final response round inside the existing tool-round cap, and original
identifying passages in source inventories. The latter addresses the anonymous
hash/URL inventory that facilitated issuer confusion. It is **offline-tested,
not successfully live-validated**.

The second full process loaded workflow code at `4052658`. Plan/research used
its original common prompt; synthesis/review/revision read the later identity
instruction from disk while still using the old inventory representation.
Exact stage inputs are preserved. This mixed prompt provenance is a limitation;
the run does not validate the combined later fix or establish a controlled
fixed-corpus comparison. Final code/documentation HEAD and dirty state are in
`data/redesign/stage2-final-state.json`, recorded after the final local commit.

## Reports and product findings

| Artifact | Path and status |
|---|---|
| First full draft | `data/redesign/runs/7b9f8b808c7648f68a9be24c56be69db/reports/report.{md,pdf}` — incomplete, not accepted |
| Second full draft | `data/redesign/runs/57bd6a8282dd494db15e13394ba3c4fc/reports/report.{md,pdf}` — incomplete, not accepted |
| Useful rehearsal revision | `data/redesign/runs/cc5883d627ba47c0928c4a630b548592/reports/revised.{md,pdf}` — single revision completed and visually inspected; no independent live recheck |
| Offline layout validation | `data/redesign/stage2-layout-reassembled/report.{md,pdf}` — clearly labeled derivative; factual errors retained, no model calls |

Each full run preserves its sources, stage inputs, raw model/tool traces,
`reports/figures.json`, figure specifications and generators. The second PDF has
six pages. Original pages 1, 3 and 4 were inspected; the diagram had collapsed at
the page bottom and long hashes squeezed table columns. Explicit figure size and
page placement, wrapped table hashes and adjacent captions now produce readable
render-only derivatives. Original exports were not replaced. Table pagination
can still separate a header from later rows; export quality is not certification.

The first company worker exhausted its tool rounds, and synthesis omitted
available Luw financials. Its reviewer caught that omission but missed a Longtu
90nm/130nm error. The second draft swapped issuer revenues, mixed Luw and Longtu
technical milestones, and used an incorrect Photronics fiscal date. Its reviewer
also made a false objection by trusting the draft's issuer label rather than
checking the original document. Both revisions timed out; no live recheck ran.

For the next focused investigation, the original-source checks establish:

- Qingyi's 2025 company revenue is CNY 1,239,670,132.81; attributable profit is
  CNY 187,305,592.42. Its semiconductor business revenue is approximately
  CNY 204.1461 million. Annual source `b81b85…272bf7` identifies Qingyi on c0.
- Luw's action-plan assessment discloses 2025 revenue of 115,523.17万元 and
  attributable profit of 25,198.43万元. Source `fbbfaa…6f394` identifies Luw on
  c0; c30/c36 contain the financial figures. Its Luxin project and 40/28nm
  single-mask milestones must not be assigned to Qingyi or Longtu.
- Longtu's annual summary `25ae4a…960596b` discloses 90nm mass production,
  including 90nm PSM at Zhuhai (c186/c206–207), 65nm sampling and 40nm equipment
  layout. Its 2025 revenue is CNY 246,658,302.88.
- The captured Photronics release states FY2025 ended **October 31, 2025**;
  the second draft's November 2 date does not match that original.

These are focused operator checks, not an exhaustive per-claim certification.
Assessments and passages are saved as `data/redesign/stage2-{first,second}-full-assessment.json`,
`stage2-final-financial-passages.json` and `stage2-original-financial-page.png`.
Issuer viewpoints, heuristic PDF table associations and incomplete global
coverage remain limitations. Real service-source extraction passed, but no live
service product report was run. Fixtures remain explicitly synthetic.

## Checks, usage and handoff

The final suite passed **38 tests**; Black checked 18 files. Pylint and diff whitespace checks passed. Final implementation HEAD is
`9f58c2ba8da7aa057499a956b7611c3dd7d288be`; the documentation closure HEAD and dirty state
are recorded in `data/redesign/stage2-final-state.json`.
Regression coverage includes source identity, scoped retrieval, deadline and
quota boundaries, embedding reuse, PDF image geometry/text preservation, and
existing two-domain workflow/export behavior. A process-cleanup test exposed a
`/proc` reaping race; it now accepts a process disappearing during the status read.

Cumulative usage: **65 model invocations, 2,018.753 summed seconds (33.646
minutes), 76,881 known output tokens, 8/40 searches and 5/60 fetch attempts**.
Another 7,057 reasoning tokens were reported with unknown output overlap;
2,153,085 input tokens are recorded separately. Five invocations have unknown
tokens, including both interrupted revisions. Unknowns remain unknown.
Failed invocations account for 186.625 seconds. No unsettled reservations, Claude
probes or peer checks remain. Main coding-session usage, subscription balance
and per-call effective model/effort are unobservable.

The attempt caps prevent more charged validation even though wall-clock,
invocation-time and observable-token ceilings were not reached. NEXT_SESSION.md
identifies the remaining work; it does not authorize another campaign or reset.
RUN_BUDGET.json and STAGE2_RESULTS.json preserve exact cumulative accounting.

## Focused additive correction — 2026-09-11

Offline changes committed as `79b997e`: 47 tests pass, formatting/lint clean. Source context/windows, failed-worker evidence handoff, original-backed objections and a 300-second revision allocation are implemented. See [focused/RESULTS.md](focused/RESULTS.md) for actual limits and outcomes.

The new diagnostic stopped after A failed at the evidence deadline without final notes. The saved fallback contains only the first source; all retrieved originals remain in the event trace. B/C were not run. This is a completed record of a failed diagnostic, not completed product validation. No further runtime patch, model retry, full report, external acquisition or account change followed. The old ledger/clock remain byte-identical; new usage is linked in `FOCUSED_DIAGNOSTIC_BUDGET.json` (106.7616 model seconds, 2053 known output tokens, one unknown-usage call). Final HEAD, dirty state and process/freeze checks are in `data/redesign/focused-diagnostic/final-state.json`.

## Local completion correction, offline only

The subsequent local correction uses one durable evidence collection and shared bounded research/writing/fallback context, with explicit phase outcomes and unchanged ledger admission. The accumulated suite passed 64 tests; details and the exact unexecuted writing-only proposal are in [completion-correction/RESULTS.md](completion-correction/RESULTS.md). No further model calls or campaigns were run. Completion behavior has offline evidence; model factual accuracy and full-report acceptance remain unvalidated. Historical ledgers and the frozen failed candidate are preserved. Final repository/preservation state is in `data/redesign/completion-correction/final-state.json`.
