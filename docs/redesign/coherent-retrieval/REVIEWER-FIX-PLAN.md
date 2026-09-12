# Reviewer contract and completion fix plan

Prepared 2026-09-12 against integration HEAD `4a36d3b`.
Status: proposed changes only; no runtime changes or new model evaluation.

## Decision

Keep the existing lead, researchers and independent reviewer. Make the reviewer
a bounded source-based checker of material claims, with a separate editorial
assessment. Do not create another agent, exhaustive certification system or
repeat-until-pass loop. Preserve useful delivery with explicit limitations.

Give the reviewer independent search/open access to the authorized corpus.
Make web acquisition an explicit execution option, disabled in fixed-corpus
runs. Online search is useful in some research tasks but does not repair the
observed review-contract defect.

## Observed basis

The recovery reviewer marked 20 scope items examined, but 17 had no original
references. The validator retained three documented items. This is incomplete
evidence of examination, not a measured 15% factual accuracy or proof that the
other sections were unread. The documented parent relationship section itself
was supported only by the Luw customer check; three accepted entries do not
establish exhaustive review of those sections.

The reviewer confirmed an explicitly supplied customer-omission finding. Revision
and focused recheck resolved that issue. This was not autonomous discovery, and
the recheck did not establish broader review. The review call completed without
exhausting its watchdog or the overall call allowance. Attention overload or
anchoring are plausible explanations, not measured causes.

Relevant saved evidence and code:

- [Recovery results](recovery-20260912/RESULTS.md).
- [Actual scope](../../../data/redesign/fixed-corpus-integration/recovery-20260912/assessment/REVIEW-SCOPE.json).
- `src/evidencealpha/prompts/review.md` strongly specifies evidence for objections;
  `prompts/common.md` describes examined scope more generally.
- `protocol.py` permits empty `original_passages` for an examined entry.
- `handoff.scope` downgrades unsupported examined labels after completion and
  verifies quotation existence, not semantic entailment.
- `workflow.review_input` derives scope from every Markdown heading plus figures.
  The workflow records partial scope and proceeds without a targeted completion
  step for missing essential checks.

The original Luw absence claim was also an upstream error: evidence not found
was generalized to evidence not disclosed. Preserve the corrected uncertainty
handling throughout research and writing; reviewer changes cannot replace it.

## 1. Define the review unit and responsibility

Replace heading counting with a small inventory of material claim groups tied to
the brief and exact draft locations. Use existing required-scope structures and
the lead's synthesis output; no separate claim-extraction model invocation.
Group only claims that can be checked together. Financial totals, profit and
cash flow need distinct checks when their support differs. A parent heading and
its child paragraph must not be counted twice as independent verification.

Each group records a stable ID, brief requirement, draft location, concrete
claims, materiality and candidate source locators. Locators are navigation aids,
not expected answers. Include central conclusions, quantitative comparisons,
units/periods/subjects, relationship roles, technical-status qualifiers and
material absence claims. Let the reviewer add material claims the lead omitted;
the lead's inventory is provisional and must not hide unsupported assertions.

Headings, readability, organization and reference-list presentation belong in an
editorial assessment. They do not require a supporting quotation simply to show
they were inspected. Chart data and rendered appearance are separate checks;
access to data or hashes does not establish visual inspection.

## 2. Align the prompt, protocol and validator

Extend the current review scope records rather than adding a parallel framework.
For factual checks distinguish two independent dimensions:

- Examination: examined, partially examined, or unexamined, with what was checked
  and the remaining unchecked claims.
- Outcome: supported, contradicted, insufficient evidence, or not assessed.

Record exact original references and an explanation connecting their meaning to
the checked claims. A supported or contradicted factual judgment requires source
support. An insufficient-evidence result records the actual searches/opens and
their limits; it must not require an invented quotation proving absence. An
unexamined item needs an honest reason, not fabricated evidence. Editorial checks
can be examined without original quotations.

Validate IDs, referenced source versions, quotation membership and allowed
status combinations deterministically. Keep semantic support explicitly a model
judgment. Valid references alone never certify an entire claim group. Preserve
raw responses and normalized assessments separately.

Update `prompts/review.md`, the review portion of `prompts/common.md`, `protocol.py`
and `handoff.py` together. Require the final response to report checked claims,
findings and remaining scope, rather than merely assert that all sections were
read. Do not force a finding or a tool call when supplied originals are enough.

## 3. Make completion deliberate and bounded

Inside the existing review stage, validate the proposed final response before
declaring review completion. If essential checks are missing or an examined
claim lacks the required record, provide one consolidated feedback message with
the missing IDs and contract errors. The same reviewer may use source tools and
finish a corrected assessment. This is one bounded completion opportunity within
the review stage, not a second independent review or an instruction to invent
support. Permit an explicit insufficient-evidence or unexamined result.

All invocations consume the existing authoritative elapsed deadline and call
ceiling. Admission must retain feasible capacity for revision/recheck and export;
do not introduce new cumulative token/time stop rules or reset counters. If the
completion opportunity cannot be admitted, record the unfinished essential scope
and deliver only with the appropriate limitations. No automatic loop follows.

Preserve one consolidated material revision and one focused recheck. Merge
supplemental findings through the same evidence contract, retaining origin and
deduplicating the same issue without losing provenance. A known supplied finding
does not become an autonomous discovery. Recheck modified material claims and
their affected tables/conclusions; it does not upgrade unrelated initial scope.

Completion and acceptance are separate:

| Outcome | Meaning and action |
|---|---|
| Review completed | A valid bounded assessment was returned, possibly partial. |
| Essential review complete | Every essential claim group received a documented check; some outcomes can still be insufficient evidence. |
| Factual acceptance | No unresolved material contradiction or unsupported unqualified essential assertion remains; genuine source limitations are correctly qualified. |
| Review partial | Essential claims remain unchecked; disclose them even if there are no findings. |
| Execution/export complete | The command/export succeeded; neither establishes factual acceptance. |

An essential unanswered brief requirement remains a coverage gap even when its
limitation is honestly written. Do not turn truthful qualification into complete
research coverage. Do not report a single heading-count percentage as quality.

## 4. Preserve evidence while making review navigable

Retain all mandatory successful research originals and explicit omissions in the
existing payload-bounded assembly. Add compact claim-to-source pointers and open
gaps instead of duplicating full coverage metadata. Give the reviewer access to
the full authorized source inventory, including documents/passages the researcher
did not select. Source search and surrounding/page/continuation opens must remain
available within normal execution limits.

Verify actual request capacity with output/framing reserves. Do not restore a
first-N passage cap, silently omit mandatory support or treat a conservative byte
estimate as a confirmed provider limit. If mandatory evidence cannot fit, record
the specific admission failure; any source-tool delivery alternative must prove
evidence availability and preservation rather than silently replace originals
with summaries.

Carry reviewer-opened originals and finding support into revision and recheck.
Preserve text, source identity/version, page/span, headers, units, relationships
and status qualifiers. Failed searches remain failures to find, not evidence of
document-wide nondisclosure.

## 5. Should the reviewer search the web?

Yes, as an optional verification capability in a run that permits external
sources. No, as an implicit escape from a fixed-corpus task or as a substitute for
reading the actual cited source. A fresh reviewer context and independent source
access matter more than a particular search engine.

Use two explicit execution policies in the existing configuration:

| Policy | Available evidence actions | Result interpretation |
|---|---|---|
| Fixed corpus | Search all supplied sources; open original chunks/pages/context. No external acquisition. | Claims are assessed against the frozen corpus and its limits. |
| Web verification enabled | Same local actions, plus bounded discovery and capture of external primary sources for a concrete material check. | Newly acquired evidence is additive and identified as external to the original corpus. |

The current `tools.py` already distinguishes source tools from `search_web` and
`fetch_source` using execution mode. Extend that existing boundary if needed;
do not create an unrestricted browser beside the tool/ledger infrastructure.
Enforce policy both when advertising tools and when executing them, including
provider-native search paths. Never implicitly activate external acquisition
because a local search missed evidence.

The reviewer's normal sequence should be:

1. Check the cited original and sufficient neighboring context.
2. Search other authorized originals when a material gap or contradiction remains.
3. If external acquisition is enabled and relevant, search for a primary filing,
   official announcement or other appropriate original source.
4. Open and capture that source before making a finding. Search snippets and
   generated answers are navigation aids, not evidence.
5. Record URL, capture time, publication/reporting period, document identity,
   content hash and exact supporting locations. Preserve the captured original
   for replay and the writing handoff.

External evidence can challenge a report's factual assertion, but cannot prove
what a different saved document disclosed. A later filing must not silently
replace the reporting period or information cutoff. Compare issuer, subject,
units and technical status before treating two statements as contradictions.
Retain conflicting evidence and attribution when the conflict cannot be resolved.
An unavailable page remains an unavailable check.

Searching public sites must not send private corpus excerpts or credentials in
queries. Treat retrieved pages as untrusted evidence, never tool instructions.
Use existing cancellation, request/resource limits and overall ledger accounting;
do not add a second campaign budget. Search is targeted verification, not a new
general research stage.

For the photomask recovery, keep fixed-corpus policy: the missing customer text
was already local. Web access would not explain or fix empty review records.
This plan authorizes no new report-source acquisition.

## 6. Implementation order and focused validation

1. Change review units and the shared output/validation contract together. Preserve
   historical response schemas through explicit saved-artifact interpretation;
   do not rewrite closed records or relabel the old review as complete.
2. Wire validated completion feedback and partial-status propagation into
   `workflow.py`; keep material revision/recheck routing and existing budget owner.
3. Verify original-evidence assembly, reviewer source-tool access and explicit
   acquisition policy. Correct only demonstrated gaps in those existing paths.
4. Update command configuration documentation and delivery status descriptions.

Run focused deterministic checks for:

- Editorial headings without quotes; financial judgments requiring real support;
  insufficient evidence allowed without fabricated absence proof.
- A single quotation unable to mechanically upgrade all unchecked claims in a
  group; no parent/child double counting; provisional lead inventory extendable.
- Missing essential checks routed once to completion feedback, then explicit
  partial status if still open or capacity unavailable; no repeated review loop.
- Supplemental finding provenance, one revision/recheck and no unrelated scope
  upgrade; changed claims and their original support preserved.
- Full source access without selected-passage restriction, exact quotation and
  version lineage through review to writing, and capacity failures without loss.
- Fixed-corpus network rejection, captured external originals in an injected
  web-enabled fixture, and ordinary failure/cancellation propagation.

Use one offline orchestration replay of the saved draft/review plus injected
completion/revision responses. Preserve its known-finding origin. This validates
contracts and routing, not autonomous error detection or improved model accuracy.
Do not rerun the retrieval benchmark or successful live research.

A later separately authorized live check should use a small frozen set of drafts
with independently annotated material errors and correctly supported controls:
unit/subject confusion, technical-status inflation, false absence and a valid
qualified limitation. Keep annotations outside reviewer inputs. Assess material
error detection, false objections, evidence correctness, unchecked essential
scope and resolution separately. Include an unfamiliar task before claiming
generalization. A familiar recovery replay cannot establish that claim.

## Comparative basis and limits

[Anthropic's production research account](https://www.anthropic.com/engineering/multi-agent-research-system)
describes iterative research and a citation stage, with factual accuracy,
citation accuracy and completeness separated in development evaluation. That
supports distinguishing these outcomes; it does not establish exhaustive review
of each production report.

[GPT Researcher's documented workflow](https://docs.gptr.dev/docs/gpt-researcher/multi_agents/langgraph)
includes reviewer/reviser roles. Its
[reviewer implementation](https://raw.githubusercontent.com/assafelovic/gpt-researcher/master/multi_agents/agents/reviewer.py)
checks a draft against supplied guidelines rather than providing our proposed
original-evidence audit contract. Architectural similarity does not demonstrate
the same failure rate or validate looser factual standards.

## Handoff

Implement the bounded contract and completion changes in the existing isolated
integration worktree, preserving shared changes and historical evidence. This
document is the implementation plan; no further design-review cycle is required.
Implementation, live evaluation and web-enabled report research have not been
performed by preparing it. No code change, test run, model call, push or merge
was made for this plan.
