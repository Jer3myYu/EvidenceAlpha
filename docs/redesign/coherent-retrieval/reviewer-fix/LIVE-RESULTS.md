# Live reviewer acceptance — partial quality, recovered execution

The six-call test finished review, one revision, one focused recheck and export
after two evidence-backed integration corrections. **This is not a full-review
quality pass.** The reviewer found two useful issues but missed known customer
support in the authorized corpus, and its claim-location records did not conform
to the new contract. No fresh research pipeline or retrieval benchmark ran.

## Inputs and boundary

The reviewer received the original photomask brief, unchanged saved draft, five
source identities and 814 pre-correction research originals. Previous reviewer
findings, assessor answers, supplemental findings and correction notes were
excluded. The corpus remains the frozen `structural-1` / `spans-1` extraction;
searches used current candidate retrieval, contextual reranking and reading code.
No corpus cleanup, reparse, downloads, external acquisition or model substitution.

The old draft had no writer-generated material-claim inventory. Its inventory was
frozen as missing, with all brief requirements visible; the reviewer had to
identify claims as part of review. This tests legacy-draft recovery, not fresh
synthesis producing the new inventory or generalization to an unfamiliar task.

## Observed modules

| Module | Actual result | Limit |
|---|---|---|
| Admission | Initial request 219,218 bytes including schema, below the unchanged 242,304 conservative allowance. Provider reported 83,621 input tokens. | Byte accounting is an upper estimate, not a provider byte limit. |
| Independent evidence access | Two searches in Qingyi's investor-relations record and one page-4 open. All actions chosen by reviewer. | Both searches returned the same four blocks; second search produced the same selected reference set. |
| Retrieval/context | 66 charged pairs, 218.260 seconds inside retrieval; tool totals approximately 106.54 and 113.23 seconds. Final request retained all 28 page-open passages. | No new quality benchmark or isolated initialization/scoring/RSS characterization. Existing one-worker/four-thread/8 GiB supervision remained enabled. |
| Evidence transport | Request passage counts: 814, 905, 905, 904. All original 814 survived. Additional omitted references were disclosed. | Successful retrieval does not establish the reviewer checked those originals. |
| Review content | 17 claim/check records, 53 original quotations, two material findings. All quoted originals validated. Raw statuses: 12 examined, five partial. | All 17 locations were descriptive labels, not exact draft excerpts; all checked-claim strings were paraphrases. Several partial checks also claimed a whole-claim supported outcome. Contractual examination remains unverified. |
| Revision/recheck | Two live calls corrected/rechecked the two findings. Recheck returned two examined finding records with valid originals and no remaining material issue in that scope. | Focused recheck does not resolve the other report claims or the known Luw miss. |
| Export | Six-page Markdown/PDF candidate; text-preservation check passed, all rendered pages inspected via contact sheet. Chart/table readable. | Minor pagination: Luw subsection heading ends page 4 before body on page 5; technical table continues across pages. No model pixel review. |

The two findings were autonomous in this run:

1. Qualify the technical explanation connecting shrinking nodes with every item
   in a company capability list. Revision separates the source-supported
   precision trend from projects at different development/application stages.
2. Incorporate newly read Qingyi investor-relations evidence and update the
   source-coverage statement. Revision explicitly attributes the July 2026
   response, retains ramp-up / imminent-use wording and does not infer 2025
   high-end mass production. This is partly a coverage update made possible by
   review's new source reading, not proof the original draft lied about its
   then-available evidence.

The reviewer **did not recover Luw's named customers at c24–c29**, despite access
to that document. It correctly marked the relationship claim partial rather than
fully supported, but treated it as a remaining coverage limitation instead of
finding the available support. The revised candidate still contains the flawed
customer-absence wording. This assessment uses the known finding after execution;
it was never passed to the reviewer or reviser as a recovery hint.

Do not replace the previously corrected recovery report with this candidate.
The candidate is an acceptance artifact with a material known omission.

## Failures and bounded corrections

- Initial execution at `6a248f7` (reviewer runtime introduced in `dc6bd86`) failed
  on `Review claim identity/location/requirement invalid` after the fourth call.
  No revision had run. The raw 9,857-token review response remains preserved.
- `0ad2338` lets nonliteral locations survive as explicitly unverified checks
  rather than abort the entire workflow. It does not accept those locations or
  change source-quotation requirements. Focused checks passed. The original
  review was not rerun.
- The first continuation failed before invocation because mandatory revision
  evidence plus metadata exceeded capacity. Measurement with all originals:
  246,839 bytes unchanged; 243,282 without the review inventory; 239,044 also
  removing redundant source-identification excerpts from navigation.
- `449ed43` applies that compaction to shared revision/recheck assembly. Source
  identities/maps and all original support stay present. Actual admitted requests
  were 239,984 and 240,524 bytes. Revision and recheck each received all 949
  accumulated originals with zero omissions. Input allowance stayed 242,304.

Closed failed ledgers were not reopened. Each continuation was additive,
inherited the original start/deadline and four consumed call IDs, and charged
only its own new invocations. Corpus and parent-ledger hashes remained unchanged.
These are recovered stages across recorded versions, not an uninterrupted pass
of the original implementation. No push or merge during acceptance.

## Usage and saved work

The original execution window began at 08:55:49 UTC on 2026-09-12 and retained
its 09:25:49 UTC deadline. Execution/export completed in **1,170.082 seconds
(19m30s)**. Offline source/format assessment continued within that window.

- Six unique generative calls: four review, one revision, one recheck.
- **392.859 summed generative seconds; 20,169 observable output tokens.**
- Separately reported reasoning-output tokens: 2,126. Overlap is unknown, so
  these are not added again. Host coding-session usage is not measured here.
- Requested model: GPT-5.6 Sol, medium; installed reranker revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`. No model replacement.
- Six provider input counts ranged from 83,621 to 92,929 tokens.
- No running campaign invocations or campaign driver processes remain.

All paths below are relative to the isolated integration worktree:

- Initial frozen input, raw review and failed ledger:
  `data/redesign/fixed-corpus-integration/reviewer-live-20260912/`.
- Preserved failed revision admission and its measurement:
  `data/redesign/fixed-corpus-integration/reviewer-live-continuation-20260912/`.
- Authoritative cumulative six-call ledger and final execution result:
  `data/redesign/fixed-corpus-integration/reviewer-live-continuation-2-20260912/execution-ledger.json`
  and `RESULT.json` in the same directory.
- Actual scope: `REVIEW-ASSESSMENT.json` and `RECHECK-ASSESSMENT.json` there.
- Source-based assessment and page inspection:
  `assessment/FINAL-ASSESSMENT.json`, `assessment/PDF.json`, `assessment/pages.png`.
- Candidate artifacts: `reports/report.md`, `reports/report.pdf`,
  `reports/revised/figures/figure-1.png` and its saved inputs.
- Drivers: [live_review.py](live_review.py) and
  [continue_live_review.py](continue_live_review.py). Their hashes were frozen.

The live commands used `PYTHONPATH=src` and the installed campaign preparation
environment at
`/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python`.
Do not relaunch a closed output directory or reset its clock.

## Conclusion

Source access, original preservation and bounded correction work, with the two
recorded integration fixes. The reviewer now supplied references for every
reported check, but this run does not establish complete or reliable factual
review. Exact-text location/claim echo requirements remain brittle when the
reviewer creates an inventory for an old draft; raw checks must not be discarded
or reclassified as factually wrong solely for that reason. At the same time,
finding the known Luw support is a substantive coverage problem, not formatting.

Do not repeat the full pipeline merely to obtain a pass. The next narrow work is
to reconcile stable claim IDs with human-readable locations/checked explanations
and improve prioritization of unresolved essential claims over repeated searches
of one source. Preserve this failed/partial quality outcome. Fresh writer-produced
inventory behavior and unfamiliar-task performance remain untested.
