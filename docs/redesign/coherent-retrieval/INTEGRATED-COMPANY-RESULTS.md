# Integrated company evaluation and Chinese report delivery

A usable Chinese industry/company report has been delivered as Markdown, a
sourced revenue chart and a six-page PDF. One company stage, one focused follow-up,
one synthesis, one independent review, one consolidated revision and one focused
recheck completed. The independent review was limited to Longtu financial data;
the focused recheck covered the specified corrections. This is qualified delivery,
not exhaustive independent certification or general retrieval reliability.

The frozen retrieval benchmark remains **9 passes / 7 partial** across its saved
versions. It was neither rerun nor reclassified. This separate evaluation assessed
research coverage, source grounding, evidence handoff and completion.

## Exact delivery paths

Worktree root:
`/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval`

Final files under its
`data/redesign/coherent-retrieval/integrated-company-20260912/delivery/final/`:

- `photomask-report.md` and `photomask-report.pdf`: final Chinese report.
- `revision/figures/figure-1.png`: sourced 2025 company-total revenue chart.
- `revision/figures/figure-1.json`: chart values, sources, period and caveats.
- `source-map.json`: short report labels to full source IDs, versions and URLs.
- `company-notes.md`, `followup-notes.md`: preserved distinct research outputs.
- `review-notes.md`, `recheck-notes.md`: actual review findings and coverage limits.
- `export.json`, `layout-correction.json`, `pages/`: export and visual evidence.
- `usage-summary.json`: stage totals and explicitly scoped cumulative usage.

The execution root above `delivery/` contains `continuation.json`, admissions,
`execution-freeze.json`, `production-input-freeze.json`, exact harness versions
in `harness-freezes/`, original provider requests/results/tool traces under
`report/stages/`, source-check and preservation artifacts. No secrets or auth
caches are delivery inputs. Reused industry evidence remains in the shared
checkout's `data/redesign/existing-corpus-campaign-2/delivery/`.

## Coverage and source-based findings

The initial company stage completed within its allocation but was **partial**:
financial comparisons and Luw/Longtu technical states were useful; Qingyi technical
states, equipment-supplier context and risk explanations were missing. That
partial result is preserved in `company-assessment.json`, not retrospectively
changed into a passing initial stage.

The single focused follow-up used the original brief and omissions stated by the
researcher. It independently selected a Qingyi technology/project query and a
supplier/risk query. It recovered 180nm scale production, 150nm small-scale
production, 130–40nm research, 28nm planning, trial-production projects, named
Mycronic/Heidelberg equipment relationships, and conditional import/export risks.
No frozen query, annotation, expected number, supplier answer or assessor locator
was injected. Its 65 original passages all reached follow-up writing unchanged.
The researcher's choices and recovered notes are actual observed behavior, not
hypothetical follow-up success.

Combined company notes and the existing industry evidence were adequate for a
scoped synthesis: industry mechanism/value chain, upstream equipment/material
constraints, downstream applications, three-company financial and technology
comparisons, management explanations, and explicit limits. Remaining gaps include
comparable semiconductor-only revenue, capacity/utilization/yield measures, Qingyi
adjusted profit in the delivered writing evidence, Longtu profit-decline causes,
and some Luw/Longtu supplier and company-risk detail. The report does not claim
these facts are absent from complete source documents. Currency for Luw remains
an explicitly qualified inference, including in the chart caption. No unsupported
names, technical rankings or unqualified advanced-node mass-production claims
were introduced to fill gaps.

The independent reviewer examined Longtu's annual financial original blocks and
confirmed revenue, profits, growth rates and chart conversion. It identified a
currency-citation wording improvement. It did **not** independently cover the
full industry discussion or all company claims. A separate primary-agent source
check identified two material wording issues: an unsupported whole-document
“not disclosed” claim and quality-risk consequences extending beyond the cited
lines. The one revision qualified the coverage claim and used the original
conditional contractual-compensation/business-interruption explanation. The
focused recheck opened original Qingyi context, confirmed those corrections,
and confirmed the Longtu annual-unit wording against the supplied review evidence.
No new material error was identified in that limited recheck scope.

## Handoff findings: recovered support versus remaining weakness

Saved canonical-text/version checks found no changed original text or source
version mismatch in company, follow-up, synthesis or revision evidence.

| Stage | Durable passages | Delivered to writing | Meaning |
|---|---:|---:|---|
| Company | 705 | 202 | Payload selection omitted 503 references; not all retrieved evidence fit |
| Follow-up | 65 | 65 | All follow-up evidence reached writing |
| Synthesis | 318 | 318 | All supplied downstream originals fit |
| Revision | 318 | 318 | Same originals preserved through revision |

There is a real remaining efficiency weakness: Luw financial support was durable
but absent from intermediate prompts under metadata/payload pressure. The agent
repeated revenue searches, including an identical cache hit. Those figures were
present in final company writing and correctly used with currency qualifications.
Thus this was a demonstrated intermediate handoff problem, not a neural failure
or final financial omission. The full company stage was not rerun.

For downstream writing, the execution harness combined originals actually supplied
to company/follow-up writing with all existing industry evidence. A transport copy
omitted repeated bounding-box/basis metadata and block IDs; exact text, source
versions, codepoint/page spans and chunk references remained. Full raw metadata
stays in original records. This reduced the evidence payload from 540,073 bytes
for all durable originals to 81,545 bytes for the compact writing/industry set.
The full synthesis request was 179,815 bytes with zero selected-evidence omissions.
Its 240,000-byte conservative input allowance remains below locally recorded
258,400 effective context minus 12,000 output and 4,096 transport reserve.
No generic runtime or ranking code changed in this execution.

## Timing, resource limits and usage

The new user-authorized window launched at **2026-09-12 02:31:56 UTC**, with a
three-hour enclosing deadline. Final elapsed time is in `continuation.json`.
Company execution used the proposed 1,620s stage/180s assessment allocation,
900s local-retrieval ceiling, 600s summed provider ceiling with protected writing,
six-call limit and 12,000-token allowance. Actual company retrieval was 304.04s
and provider time 162.74s. The full sequence completed early within the new window.

| Stage | Calls | Provider seconds | Reported output tokens | Searches | Retrieval seconds |
|---|---:|---:|---:|---:|---:|
| Company | 6 | 162.74 | 6,239 | 12 | 304.04 |
| Focused follow-up | 3 | 58.62 | 2,156 | 2 | 80.34 |
| Synthesis | 1 | 142.95 | 7,527 | 0 | 0 |
| Independent review | 2 | 64.65 | 1,791 | 1 | 31.73 |
| Revision | 1 | 141.34 | 7,470 | 0 | 0 |
| Focused recheck | 2 | 44.78 | 1,338 | 0 | 0 |
| **Total** | **15** | **615.08** | **26,521** | **15** | **416.12** |

There were **482 newly charged neural pairs**. Including the preserved closed
preparation/neural continuation: **1,857 charged pairs and 1,585.71 retrieval/neural
seconds**, with 15 generative calls / 615.08s / 26,521 output tokens across those
two records (the prior continuation used zero generative calls). These are scoped
subtotals, not account-wide lifetime usage. The separate e80e141 baseline remains
six calls / 130.33s / 5,220 output tokens and was not rerun; other historic campaigns
are not silently folded into or erased from this subtotal.

The CLI separately reported 3,160 reasoning tokens with unspecified overlap.
They are not added to output as though known disjoint; even the conservative
fully-disjoint upper bound is 29,681, below 40,000. No hard in-flight output-token
cap is available in the subscription CLI; host-assistant/account-wide usage is
unobservable. Calls and elapsed deadlines were supervised; one generative call
and one local reranker worker ran at a time.

Production scoring retained the 300s/search engineering ceiling and fresh scorer
reload for uncached searches, CPU float32, batch one and four threads. Runtime
samples worker RSS against 8 GiB and reported no resource-limit failure. A sampled
peak was **not persisted for this execution**; the previous benchmark's 2.04 GiB
peak is not relabeled as this run's measurement. Original 30s/search/120s-stage
feasibility remains failed; success here uses the separately admitted budget.

## Versions, validation and repeatability

Runtime remains `cad87ed9fe865ea93e8b329543c805e4578d2bd3`, incorporating base
`0aa3f2f` and preparation correction `0ab1c04`. Frozen documentation `5bda1fb`,
EVALUATION.json and historical ledgers remain unchanged. Final checks matched
all frozen corpus/input hashes and runtime source hashes.

Reused installed Python 3.12, torch **2.6.0+cpu**, transformers **4.57.6** and
sentencepiece **0.2.1**. Exact dependencies/wheel records are at
`data/redesign/coherent-retrieval/campaign-20260912T005532Z/dependency-manifest.json`
and `installed-versions.json` in that same campaign directory. The model is
BAAI/bge-reranker-v2-m3 revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; its artifact inventory/hashes are at
`campaign-20260912T005532Z/preparation/model/snapshot.json`.
The safetensors SHA-256 is
`d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.
Requested generative model was GPT-5.6 Sol, medium, through the existing Codex
subscription path. Effective server model/effort was not independently emitted
by the CLI. No model substitution, install, download or external-source acquisition.

Completed deterministic checks were reused; no benchmark, broad suite, baseline
model test or successful research stage was rerun. Validation here inspected actual
saved evidence and outputs. The first seven-page PDF passed text preservation but
had a mostly blank citation page caused by a forced chart break. It remains in
`delivery/revision/`. A layout-only CSS derivative removed that forced break,
retained explicit image dimensions and identical Markdown bytes, and passed the
unchanged text validator. All six final pages were inspected (first two are
byte-identical rendered images to the inspected first export). No clipped text
or missing Chinese glyphs was observed; table continuations can cross pages
without repeated headers. This pagination limitation is not hidden as perfect
publication layout. Chart data and caption retain the Luw currency qualification.

This demonstrates an operational fixed-corpus retrieval/research/report path
under the measured engineering budget, with important intermediate payload and
review-coverage limitations. It does not establish benchmark acceptance,
comprehensive factual certification or repeatability across new corpora/tasks.
All provider/scorer/export processes finished; no background jobs remain.
