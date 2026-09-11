# Single saved-evidence writing test

The user separately authorized this one-call test after the offline correction.
Candidate `7b87dc93a79aaa0c7f116091bfa5a0ad23c16d16` completed company notes,
but the result has factual qualifications and is not full-report acceptance.
No implementation, prompt, setting, source or prepared-input changes occurred
during execution. No research-to-writing transition was exercised.

## Verification and admission

Before admission, HEAD and the clean checkout matched the candidate; every
runtime/prompt hash in `proposal-manifest.json` matched. All 72 frozen files
matched the failed candidate's preservation manifest. All 67 prepared passages
matched original text, source versions and exact spans in that frozen corpus.

- Prepared input SHA256: `5e3271c50a66f1c58d9a3fdef01dba06d0fd79b3bd6c430a5e10ae38268e5f08`.
- Source packet SHA256: `8a70ee71b066f81db134d3bfe5ae08ee4f6a42b3d3b9c0a657bdbf9fb23ef1aa`.
- Separate authorization/usage: `data/redesign/saved-writing-test/authorization-usage.json`.
- Historical Stage 2 ledger hash: `b3912add49941ed78906fe495ea7481f5809f5ae4a5ac6340c9328bba12a6c5d`.
- Historical diagnostic ledger hash: `d75f2858af8cf828e888146bdf12501abeb686c5358c7eb46d7a8817666412a2`.

Both historical ledgers and campaign clocks remain byte-for-byte unchanged.
The separate ledger admits only one attempt and its harness refuses a second
invocation. Stage ceiling was 180 seconds; writing reserved 174.782493 seconds.
The harness also retained a conservative 16,000 observable-token ceiling;
post-call token reporting cannot enforce an in-flight token limit.

## Completion and accounting

Exactly one Codex invocation completed, 2026-09-11 16:15:30–16:16:21 UTC.
Stage elapsed: **50.734284 seconds**. Ledger invocation: **50.185141 seconds**.
There were no tool requests, executions, acquisitions, retries, reviewers or
full reports. The actual context contained all 67 originals (27/27/13), with
none omitted. Output contains final notes, a comparison table and one structured
bar-chart proposal; no figure was rendered.

Requested configuration was GPT-5.6 Sol / medium, recorded in settings and CLI
arguments, using the existing subscription transport and isolation controls.
The provider did not echo effective model or effort; those remain unknown.
Raw events show thread start, turn start, one completed answer, turn completion;
no native tool activity is recorded.

Actual application prompt: **30,642 UTF-8 bytes**. Separately supplied output
schema: **8,424 bytes**, including `tool_calls.maxItems=0`. This is not a complete
wire-payload measurement: CLI-added context and transport serialization are
unobserved. Usage reports **19,452 input**, **2,467 output** and **516 separately
reported reasoning-output tokens**, zero cached input. Reasoning overlap is
unspecified, so 516 is not added to 2,467. Account quota and outer-session usage
are unknown.

## Original-source inspection, without another model

Source handles below expand through the unchanged output's source index.

| Checked material claim | Original support and outcome |
|---|---|
| Qingyi total revenue 1,239,670,132.81 CNY; semiconductor revenue 2.04亿元 | S1 c246 and c695 support the values and distinct scopes. c660 contains 20,414.61 without a unit in its supplied fragment; the output's 万元 unit is consistent with c695 but is an inference, not an explicit unit in c660. |
| Longtu total revenue 246,658,302.88 CNY | S2 c280 supports it; no automatic semiconductor-segment reassignment. |
| Financial chart | Correct conversions to 12.3967013281 and 2.4665830288亿元; Luw is null. Full source IDs, period, units and scope caveats supplied. |
| Qingyi technology | S1 c896–c899 supports 180nm scale production, 150nm small-batch production, 130–40nm development and 28nm planning. |
| Longtu technology | S2 c185–c187 and c205–c207 support 90nm PSM production, 65nm sampling and 40nm equipment layout. The split sentence is correctly joined. |
| Luw / Luxin attribution and status | S3 c43–c47 supports Luw ownership, 90nm+ sets validated/supplied, 40/28nm single masks validated/supplied, 40nm sets still sampling and future 28–14nm plans. No false Qingyi reassignment. |

The requested Luw total revenue remains blank, correctly. However, the financial
prose says the action assessment report contains no annual revenue. That exceeds
the packet's evidence: the preserved full source S3 c30 actually contains
115,523.17万元. This original was inspected only afterward, offline; it was never
added to the model packet. The output's figure caption correctly limits the gap
to the supplied settled evidence. Thus missing-data handling is inconsistent
between prose and figure, not a fabricated Luw number.

The output omits requested disclosure dates. It identifies the 2026 plan as a
future plan, but does not establish its disclosure date. Another narrower
qualification: the table assigns future MCU/SiPh/CIS/BCD/DDIC applications to
phase two specifically; c47–c49 refers to future project products without an
unambiguous phase-two-only restriction.

Other gaps are retained: Luw semiconductor revenue, Longtu's separate segment
revenue, specific certification/set-supply evidence, stable-production details
and construction dates. These are packet limitations, not proof that the full
original documents never disclose them. Company notes do not establish complete
coverage of the broader industry-report brief or visual quality.

## Preserved result and stop

- Notes: `data/redesign/saved-writing-test/stages/company/31ced4a7166f/output.md`.
- Structured figure and notes: same directory, `output.json`.
- Exact prompt, schema, command, raw output, stderr and normalized usage: `call-0/`.
- Original bindings and writing view: `context-state.json`, `writing-context.json`.
- Verification, result, assessment, one-use harness and preservation hashes:
  `data/redesign/saved-writing-test/`.

This demonstrates that this supplied evidence packet can produce completed
company notes in one tool-free call. Checked major issuer/technology assignments
are correct, with the overclaim and omissions above. It does not establish
repeatability, general factual accuracy, research completion or full-report
acceptance. No timeout occurred. No patch or further model test is proposed or
executed here. All child work ended; the one-call allowance is consumed.
