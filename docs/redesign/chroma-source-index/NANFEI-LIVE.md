# New-topic campaign: 深圳楠菲微电子

Campaign artifacts (not Git inputs):
`data/campaigns/nanfei-20260912/` in the canonical project root.
The current Chroma implementation was merged into `main` and pushed as
`4ba2beb`. Existing user documentation changes were preserved unstaged.

## Scope and provenance

The report brief asks for an investor-oriented Chinese explanation of the
company, industry, products, value chain, commercial differences, drivers and
risks, with financial/relationship uncertainty preserved. Information cutoff:
2026-09-12. This campaign uses 17 newly captured public originals (14 HTML,
three PDF), not the earlier five-document photomask corpus. Capture was
operator-led; planning and research use the normal fixed-corpus command with
no imported historical answers. Online research inside the application is off.

The source acquisition receipts, original response bytes, extraction versions,
model/index configuration and source catalogue are preserved. No model or
package downloads were required. Source summaries were not generated; Studio
must show that state rather than invent a document summary.

## Observed integration corrections

| Cause | Correction and evidence |
| --- | --- |
| HTML prose in ordinary containers was skipped | Generic DOM traversal preserves text in order. Nested layout tables are traversed rather than treated as one financial table. Parser `structural-4-html-layout-tables`, commits `8117e2c`, `36107da`; original bytes retained. All 14 HTML visible-body checks passed, excluding non-content script/style/navigation. |
| Resolving a virtualenv Python symlink launched the system interpreter without its packages | Preserve the configured interpreter path; verify actual imports in that environment. `87c96f5`. |
| Cancellation allowed queued work to start | Latch cancellation before admitting another invocation. Interrupted attempts and unknown usage remain recorded. `87c96f5`. |
| Company research repeated financial searches without new originals | Preserve the interrupted context and finish partial notes tool-free; generic prompt guidance discourages repeated label variants without new evidence. `4c00dd6`. This required operator intervention, not demonstrated autonomous convergence. |
| Duplicate source metadata blocked synthesis capacity admission | Losslessly inherit identical metadata and retain mandatory originals. `4eb3343`. |
| Draft S-label declarations differed from exporter ordering | Resolve explicit unique source hashes before assigning canonical links; preserve multi-source declarations and locators. Faulty export remains saved. `f2d6797`. |
| Repeated span coordinates inflated review input | Source-local span tables preserve exact text, original coordinates and chunk bindings. Real saved review replay: 1,264 originals, zero omissions, 230,346 request bytes against unchanged conservative 242,304 capacity estimate. `f2d6797`. |
| Compact transport encoding changed checkpoint hashes | Validate original saved input/output hashes and compare losslessly normalized evidence before explicit completed-stage reuse. `c3eb281`. Successful follow-up/synthesis remain reused. |

Focused pytest, Black and pylint checks cover changed paths; saved real-evidence
replays check transport equality. These are contract checks, not a new retrieval
benchmark or evidence of general quality.

## Retrieval and Studio

The final E5/Chroma build contains 13,229 units, with no fallback splitting.
Build wall time was 1,795.314 seconds: initialization 3.633, chunking 8.873,
embedding 1,660.172 and indexing 116.997 seconds. Sampled peak RSS was
4,211,945,472 bytes. Installed E5 revision
`d128750597153bb5987e10b1c3493a34e5a4502a`; BGE revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

`studio-manifest.json` references canonical stage inputs/outputs and events,
source capture, index units/build, retrieval operations, selected writing
originals, omission manifests, rubric decisions and exports. The plan's tasks
and each dispatched task/required scope link topics to research answers.
This is saved observability data, not a claim that the upgraded Studio UI has
been implemented. Do not sum copied ledgers: deduplicate invocation IDs.

The repaired NFNOS architecture sentence reached original-context opens and
writing handoffs. This demonstrates structural recovery and preservation;
it does not isolate Chroma ranking as the cause of recovery.

## Execution command

From `worktrees/nanfei-live`, the original fresh invocation used the frozen
`execution-final.json` and output `run/`. Measured recovery reuses compatible
completed stages under the same campaign deadline. Current continuation:

```bash
PYTHONPATH="$PWD/src" ../../runtime/environment/bin/python -m evidencealpha.cli fixed-corpus \
  --continue-existing \
  --execution ../../data/campaigns/nanfei-20260912/execution-final-review.json \
  --output ../../data/campaigns/nanfei-20260912/run-finish
```

Do not rerun that command after its ledger closes. It documents the executed
continuation, not permission to reset the campaign or reproduce a fresh success.
Settings use GPT-5.6 Sol research/writing and GPT-6 Astra review/recheck, medium
effort, one worker, 8 GiB sampled neural memory protection, 300-second search
watchdog and the original three-hour enclosing deadline including setup.
Provider-reported actual model identity is recorded separately; unreported
identity is never asserted to match the request.

## Final Chinese result

The normal continuation completed at runtime `c808a5a`: execution complete,
coverage partial, review complete, **ready with disclosed limitations**, no
unresolved material issues, PDF export complete. Its authoritative record is
`run-finish/manifest-final.json`; execution uses `execution-final-review.json`.
This is recovery from saved stages after engineering intervention, not an
uninterrupted fresh run of the final code.

The initial GPT-6 review found an omitted UALink development announcement and an
inadequate domestic competitor comparison. It supplied UALink original text
itself; the orchestrator requested focused research only for the unresolved
competitor question. The researcher opened the existing filing locations,
recovered period-qualified 盛科通信 evidence, and the writer revised once.
The focused rechecker resolved both material findings. Its rubric is Meets on
brief coverage, useful analysis, responsible evidence and clear communication;
Partly meets on understanding because PCIe Switch remains insufficiently defined.

Chinese deliverables: `run-finish/reports/report.md`, `report.pdf`,
`source-map.json`, `figures.json`, and `revised/figures/`. All 12 PDF pages were
visually inspected and normal text preservation passed. The visual inspection
is hash-bound under `pdf-inspection/3df45653018b/`; remaining presentation issues
are in `TODO_NANFEI_RUN_FOLLOWUP.md`. The earlier stale/faulty PDFs remain saved.

Financial statements, named trading relationships and product-level commercial
status remain limited by the captured evidence. Procurement in the historical
competitor filing is not Nanfei revenue or a current competitive ranking.
UALink IC design/FPGA/protocol verification is not silicon validation or mass
production. This is rubric review with targeted source checks, not exhaustive
fact certification or evidence of general reliability.

English translation is separately recorded under `english/`, using the selected
revised Chinese report and its source mapping. It is not another research
campaign or independently fact-reviewed English report. The translation helper
uses the same provider adapter and an additive ledger, with the original
campaign deadline and all prior invocation IDs retained.

Revision exposed additional transport overhead after successful review and its
focused follow-up. `16e0999` encodes the plain-text request object once instead
of double-escaping its user payload, and lets duplicate inventory metadata
inherit from delivered source metadata. This does not change the provider API
or context allowance. The real revision replay retains all 1,327 mandatory
originals exactly, selects 1,338 passages, and explicitly records 246 optional
omissions (235,241 request bytes before separate schema overhead). No mandatory
support is removed. Research, synthesis, review and follow-up outputs are reused
with hash validation in `execution-revision.json`.

Validation disclosure: the focused transport file passes four checks and the
actual saved revision replay passes. A wider `test_completion_phases.py` run
was not all green: 12 failures are preserved in `single-encoding-check.log`.
Ten occur before mocked provider calls because those older fixtures do not
supply now-required writer capacity; one asserts an older grouped storage
representation and one assumes a fixed byte cap must force an omission even
when improved compaction allows all evidence. These failures were not relabeled
as passes or used to weaken live admission. Prompt-decoding expectations in
existing tests now reflect the once-encoded object. A broader test-suite update
is not evidence of autonomous report quality and was not pursued here.

## Usage and remaining limits

The final additive ledger is `run-finish/execution-ledger-english.json`:
47 unique generative invocations (44 complete, two failed, one cancelled),
73,992 observable output tokens and 3,028,586 reported input tokens. Recorded
invocation time totals 2,024.579 seconds. Forced-interruption usage is incomplete;
this total is not an assertion that all actual usage is known. Reasoning tokens
are not added a second time. Host-assistant usage is unavailable. Historical
copied ledgers are not summed. Stage/cumulative token targets were telemetry
under the previously authorized overall-controls policy, not new hard stops.

Requested models: GPT-5.6 Sol for research/writing/translation and GPT-6 Astra
for review/recheck. The provider did not report actual model identity; no
substitution is asserted. Model revisions and installed dependency versions
remain in the frozen configuration/index records. No new model downloads or
installs occurred.

English translation used one new invocation: 23,981 input and 10,668 output
tokens (reasoning included). Nineteen targeted fidelity checks preserve key
amount conversions, percentages, units, relationship roles and technical-status
qualifiers. All 17 source aliases and link URLs remain within the authorized
source mapping. Figure values and source IDs match the Chinese originals.
The submission copy removes a duplicated report-date line and revision-process
wording, retains the Chinese legal name in the body, and makes bibliography
links clickable. The raw translation and its first export remain preserved.

The latest shared `main` also contains the independently created documentation
commit `d00a76a`; it must be preserved when merging these campaign fixes.

## English delivery and presentation correction

Best English submission copy: `english/report-submission.md` and
`english/report-submission.pdf`, with English charts under `english/figures/`
and `english/source-map.json`. The first English export and unsuccessful layout
attempt remain saved. The normal renderer was corrected to paginate complete
list items and measure long ASCII words against actual cell width. This removed
a heading-only glossary page and unnecessary mid-word breaks without reducing
font size or weakening text preservation. The final English layout has 17 pages.
The source Chinese PDF retains its actual reviewed/exported version.

The two language variants share underlying evidence and qualifications. English
is a checked translation, not another independent review. See
`english/FIDELITY-CHECK.json`, `english/RESULTS.json`,
`english/submission-final-result.json`, and the hash-bound PDF inspection records.
The consolidated follow-up file is `TODO_NANFEI_RUN_FOLLOWUP.md`.
