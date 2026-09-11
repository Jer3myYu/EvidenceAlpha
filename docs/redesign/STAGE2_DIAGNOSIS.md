# Stage 2 trace diagnosis and bounded proposal

**Offline only. No model calls, retrieval reruns, new sources, full reports or
ledger changes. Existing allowances remain exhausted.** F1 = `7b9f8b…`, F2 =
`57bd6a…`. [TRACE_INDEX.json](diagnosis/TRACE_INDEX.json) resolves every stage and
source abbreviation below to its preserved path. Event references are 1-based
lines in that stage's `events.jsonl`; call numbers refer to `normalized.json`.

## 1. Where attribution first broke

The originals identify Qingyi (`b81b85…`, annual c0), Luw (`fbbfaa…`, assessment
c0) and Longtu (`25ae4a…`, summary c0). Their canonical text and historical tool
results agree. The initial inventories contained hashes/URLs, but no identifying
passage. Most returned financial/technical chunks said only “公司”; their source
IDs stayed correct, while `section` was often empty. This is the first **identity
ambiguity**, not evidence that retrieval changed the issuer.

| Observed error | Original → retrieved passage → first wrong assertion → propagation |
|---|---|
| Luw revenue assigned to Qingyi | Luw c30 says 115,523.17万元. F2 company event 4 returns that exact text under `fbbfaa…`. Company **call-1** labels it Qingyi. Synthesis retains that number in Qingyi's row and explicitly calls Luw's assessment a Qingyi document. Review **call-2** endorses that identification. First wrong assertion: company notes. |
| Qingyi semiconductor revenue assigned to Luw | Qingyi c660/c695 say 20,414.61万元 / approximately 2.04亿元. F2 company event 3 returns them under `b81b85…`; **call-1** labels them Luw. Synthesis repeats this in its summary while correctly labeling the table's semiconductor figure Qingyi. Review catches that internal contradiction, but leaves the total-revenue issuer error above. |
| Luw technical milestones assigned to Longtu | Luw c45–46 disclose 90nm-and-above sets, 40/28nm single masks and 40nm set sampling. F2 industry event 15 opens `fbbfaa…/c45`. Industry **call-3** calls this Longtu's disclosure. Synthesis retains the Longtu attribution and substitutes Longtu c185/c206 citations. Review treats this primarily as incomplete citation support, rather than identifying Luw as the issuer. |
| Longtu definition/manufacturing attributed to Luw | Longtu c50/c109 describe its product and manufacturing. F2 industry event 12 opens `25ae4a…/c50`; search results also contain c109. Industry **call-3** calls both Luw disclosures. Synthesis copies that attribution. Review does not flag it. |
| Qingyi Foshan and Luw project details merged | F2 company event 5 supplies Qingyi investor-record c107 about Foshan. Event 4 supplies Luw c41/c44 about its project's ramp-up/130–40nm coverage. **Call-1 combines these under Qingyi.** Synthesis later correctly assigns the named Luxin project to Luw but retains the mistaken document/revenue identification. |
| Reviewer falsely moves Luxin to Qingyi | Original Luw c43–47 describe Luxin. F2 review event 8 retrieves those passages under `fbbfaa…`. Review **call-2 explicitly reasons that the draft already called this source Qingyi**, then recommends moving Luxin from Luw to Qingyi. The specific false correction begins in review; it inherits the earlier wrong issuer premise. No completed revision applies or rejects it. |

Important boundaries: F2 synthesis **did receive** the explicit Qingyi issuer
name from `b81b85…/c1` at event 15. Merely supplying some identity evidence did
not ensure consistent attribution. F2 company finished after **two calls**, with
six rounds unused; its wrong notes were not forced by the final-round limit.

Two related failures should not be mislabeled as issuer swaps:

- **F1 missing Luw financials:** company event 2 proves the inline `source_id:`
  query was not a filter: a Longtu-scoped query returned Qingyi chunks. However,
  events **39–40 eventually reopened the correct Luw revenue/profit**. All eight
  calls requested tools; no final company notes were saved. Synthesis received
  a failure gap, not that worker's tool transcript, and declared the figures
  unavailable. Review correctly recovered them. Scope failure caused extra work;
  lost final notes explain the missing handoff more directly.
- **F1 130nm / F2 fiscal date:** F1 synthesis event 39 returns Longtu c207's
  sentence tail without c206's “90nm” lead-in. Its final output asserts 130nm;
  review repeats it. F2 industry's retrieved Photronics passages do not contain
  the claimed November 2 fiscal date; its final notes introduce it, and synthesis
  repeats it. The preserved original says October 31. Neither is source-byte
  corruption. Inferring 130nm from surrounding industry discussion, or importing
  a fiscal date from model memory, remains a hypothesis.

**Confirmed:** the wrong issuer assertions originate in generated notes/review,
not changed source bytes; F1 lost a worker handoff despite retrieving the figures;
revision stopped at its own deadline; requests repeatedly carried prior payloads.
**Hypotheses:** missing identifying passages and short sentence fragments made
misbinding easier; stale notes reinforced mistakes; context pressure or provider
latency contributed. None has a controlled causal measurement here. The prior
successful company rehearsal is a counterexample to “anonymous inventories
always fail”; it read full originals including their titles.

## 2. Context growth

Decimal kB; **first → last request (sum across calls)**. These are exact UTF-8
portable request bytes, including JSON escaping, not token estimates or the
entire native Codex context. All 65 saved requests and each tool result are
measured in [measurements.json](../../data/redesign/stage2-diagnosis/measurements.json)
by [measure_traces.py](diagnosis/measure_traces.py).

| Stage | F1: calls; first → last (sum), kB | F2: calls; first → last (sum), kB |
|---|---:|---:|
| Plan | 1; 6.2 → 6.2 (6.2) | 1; 7.0 → 7.0 (7.0) |
| Industry | 5; 10.1 → 135.3 (366.6) | 4; 10.5 → 46.4 (127.5) |
| Company | 8; 10.2 → 173.5 (747.0) | 2; 10.6 → 27.6 (38.1) |
| Synthesis | 5; 15.8 → 167.6 (401.9) | 4; 23.8 → 60.8 (173.5) |
| Review | 3; 36.6 → 62.9 (151.6) | 3; 26.8 → 36.4 (92.7) |
| Revision | 3; 49.2 → 62.6 (162.0) | 3; 47.9 → 78.7 (180.3) |

F1 transmitted **1,835,350 bytes**: instructions 56,547; portable starting input
410,005; previous assistant responses 73,778; tool-result history **1,286,365**;
framing/tool definitions 8,655. F2 transmitted **619,137 bytes**, including
337,722 starting-input bytes and **210,223 tool-history bytes**.

What repeats, and where:

- Every fresh CLI call resends the stage's instructions, initial portable input,
  prior model tool requests and accumulated tool replies. Raw worker tool history
  is **not** forwarded to synthesis; only final notes are. Review receives the
  draft, not worker notes. Revision unnecessarily receives **draft + findings +
  plan + worker notes**: F2's notes alone are 13,393 bytes, plan 2,670, draft
  15,570, before outer escaping.
- F1 tool replies contain 438,260 bytes: 61,911 original-passage text, 31,264 web
  snippet text and 345,085 other fields/JSON overhead. F2: 107,878 total, 17,490
  original text and 90,388 other/JSON bytes. Repeated source IDs, URLs, spans,
  bounding boxes, section/context fields and table headers dominate short
  passages. These residual counts are **not pure metadata**: JSON escaping and
  structure are included.
- Exact repeated source/chunk/text contributes at least **20,519 text bytes in
  F1** and **1,593 in F2**, before conversation replay. F1 company repeats 11,362
  of its 22,100 passage-text bytes. These lower bounds exclude partial overlap
  between different chunks or a chunk and a full document.
- The earlier industry rehearsal's full-source reply was **64,960 bytes for
  7,159 bytes of canonical text**, including the old block/chunk metadata. The
  successful company rehearsal opened full Longtu and Luw sources (30,927 and
  22,532-byte replies), which included their identifying titles. It was slower
  to transmit but avoided these particular issuer swaps.
- F1 synthesis's two largest replies were web snippets of **17,211 and 16,896
  bytes**. These were not original-source acquisitions. Per-event `sources`
  version maps add 97,240/F1 and 35,360/F2 bytes to trace logs, but **are not
  included in model prompts**. They must not be counted as context growth.

Local source/embedding caching saves repeated file/index work; it does not
remove serialized payload/history retransmission. F2's smaller context still
failed attribution. A causal claim that context size alone caused the errors,
or that an SDK switch would fix them, is unsupported by this uncontrolled pair.

## 3. Revision deadlines and recoverable progress

| | F1 revision | F2 revision |
|---|---|---|
| Configured stage deadline | 120 seconds | 120 seconds |
| First invocation UTC | 04:52:50.949609 | 05:05:12.357708 |
| Reconstructed expiry UTC | 04:54:50.949595 | 05:07:12.357695 |
| Three request sizes | 49,219 / 50,163 / 62,593 bytes | 47,891 / 53,717 / 78,652 bytes |
| First two settled call durations | 7.780 + 8.121 seconds | 14.084 + 14.379 seconds |
| Tool progress | Three invalid opens (`30`, `36`, `195`, missing `c`), then three searches | Seven exact opens, then six searches |
| Measured tool execution | 1.462 seconds | 2.917 seconds |
| Last call's remaining reservation | 101.422 seconds | 85.359 seconds |
| Last call's settled execution | 101.334 seconds | 84.511 seconds |

Times are 2026-09-11 UTC. Exact monotonic deadline values were not saved; expiry
is reconstructed from the persisted first invocation plus its reservation.
Full-run time remaining at revision start was **1,183.7 / 1,328.5 seconds**:
the 120-second stage allocation, not the full/campaign cap, stopped these calls.

Both last-call raw files contain only `thread.started` and `turn.started`;
stderr is empty and no last-message/normalized revised output exists. Earlier
responses contain tool requests with empty content. **Usable preserved material
is tool evidence and the pre-revision draft, not partial revised prose.** Unknown
last-call usage remains unknown. The traces cannot separate server queueing,
reasoning and generation, or establish that prose generation had begun.

Proposed isolated revision allocation: **300 seconds**, with up to 60 seconds
for evidence checks, **210 seconds reserved for the final response**, and 30
seconds overhead/margin; at most two evidence rounds then one final call.
The completed no-tool rehearsal revision took **135.3 seconds**; completed
full-synthesis final calls took **188.5 / 119.2 seconds**. This supports a larger
writing reserve than 85–101 seconds, but does not guarantee completion. Enforcing
the time-based writing reserve is a small proposed runner change, not yet
implemented or validated. Current final-round enforcement is count-based only.

## 4. Frozen evaluation boundary

[FROZEN_EVALUATION.json](diagnosis/FROZEN_EVALUATION.json) identifies a **60-file,
read-only, SHA-256-checked snapshot** and archive under
`data/redesign/stage2-diagnosis/`. It contains code/prompts from `f699743`, pinned
dependency records, the five existing originals/indexes, exact baseline inputs,
candidate inputs, draft/figure assets and proposed fixed-corpus settings.
Credentials and `.env` are excluded. Settings contain a non-executable ledger
sentinel; this is not an admitted campaign.

The prior F2 run loaded old workflow code while later stages reread changed
prompt files. Its exact per-stage instructions remain preserved, but it is not
a homogeneous evaluation of the later identity fix. **Never edit code, prompts,
settings, corpus or inputs used by an active run.** Future approved evaluations
must use a dedicated snapshot checkout, explicit settings and separate writable
outputs. A change requires a new snapshot/evaluation ID; verify hashes before
admission. File permissions/checksums detect edits, not privileged tampering.
Server-side model routing and mutable installed dependencies remain limitations;
use the saved dependency pins in an isolated environment without account changes.

Verification, with no model call:
`.venv/bin/python docs/redesign/diagnosis/verify_freeze.py`.

## 5. Smallest correction and proposed charged cases

Use the already-added original identifying passages, retain explicit source
scope, and remove plan/worker notes from **revision input only**. Reopen adjacent
original chunks when a sentence is split; do not reinterpret a sentence tail as
an independent milestone. Preserve raw traces. Defer transcript deduplication or
persistent SDK transport until these small representation changes are measured;
neither is needed to establish the first incorrect attribution.

The following is **a proposal requiring new explicit authorization**, not use of
remaining historical allowances:

| Case | Frozen saved input and purpose | Ceiling |
|---|---|---:|
| A: company | F2 company input, with original identifying passages. Check whether issuer-bound company comparison becomes useful. Reuse existing planning; no planning/industry/synthesis rerun. | 180s |
| B: reviewer | Exact preserved F2 draft/figures and reviewer input, with identifying passages. Observe whether it detects the issuer errors and avoids the false Luxin reassignment. | 180s |
| C: revision, conditional | Preserved F2 revision input/findings, with identifying passages and plan/notes/gaps removed. Test correction versus false-objection handling and the 300s allocation. Its deliberately bad draft is a saved negative case. | 300s |

Production **GPT-5.6 Sol medium** matches the failed cases. At most **3 isolated
attempts, 660 summed invocation seconds, 16,000 observable output/reasoning
tokens, zero external searches/fetches, one concurrent call, no retries and a
30-minute evaluation window**. C runs only if A/B support useful identity
handling. Stop on a concrete failure or cap; no automatic replacement attempt,
full report or repeat-until-pass. These diagnostic cases do not establish a live
recheck or full product acceptance. A newly authorized additive allowance record
must link to the preserved exhausted ledger; its original clock and counters
must not be reset or replaced. The allocation change would require a new frozen
candidate version before execution; the current snapshot records it as proposed.

The snapshot preserves baseline settings plus explicit proposed per-case caps.
It is intentionally not an executable driver configuration. Before any approved
execution, bind those caps and the additive authorization record in a new frozen
candidate; do not accidentally use the baseline 360-second stage default or the
old campaign ledger. This setup change must happen before any child starts.
