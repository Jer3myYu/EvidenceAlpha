# Session wrap-up — evidence, review and report delivery

This closes the work culminating in the Chinese photomask report on 2026-09-12. The product is a useful industry explanation for an investor unfamiliar with the field: industry structure, commercial relationships, company differences, growth drivers and risks, supported by traceable sources. It is not an exhaustive certification of every sentence.

The latest implementation and presentation work is committed on `reviewer-contract-fix` and is being integrated into local `main` by fast-forward. This document accompanies that integration. No remote push is part of this closeout. Historical records retain their original status and code versions; earlier statements such as “not merged” describe their recording time.

## What we redesigned, and why

| Problem we encountered | Change and reason | What we learned |
|---|---|---|
| Relevant evidence could be retrieved but lost before writing, including context opened by the researcher. | Integrated candidate retrieval, contextual reranking, structural reading and evidence-preserving handoff. Replaced passage-count selection with payload-bounded assembly, original references and explicit omissions. | More passages alone do not solve lost support. The important unit is a usable claim with its original context, units, subject and qualifiers. |
| A delivered report depended on custom harness assembly and separate stage launches. | Added a normal fixed-corpus command, explicit configuration, evidence import/recovery contracts, follow-up routing and integrated export. External acquisition requires an explicit mode. | A successful harness proves its own execution path. It does not establish that the product entry point behaves the same way. |
| Essential gaps and reviewer findings did not consistently trigger action. | The orchestrator now routes missing evidence to focused research, available corrections directly to revision, and genuine limitations to qualification. New originals reach writer and rechecker; unresolved issues survive transitions. | Feedback must change the workflow, not merely appear in an appendix. Do not research again when the reviewer already recovered sufficient evidence. |
| Review drifted toward exact-text claim inventories and exhaustive certification, while initially examining too little of the report. | Replaced claim-by-claim completion with five user-focused criteria: answers the brief, builds understanding, useful analysis, responsible evidence, clear communication. Retained targeted checks of pivotal facts and suspicious absence claims. | The reviewer’s job is to identify material obstacles to a useful, fairly supported report. Neither an empty issue list nor a large verification checklist establishes that outcome. |
| Retrieval misses became “not disclosed” judgments. | Made absence/coverage judgments provisional, retained unresolved gaps and gave the reviewer independent access to originals and surrounding pages. | “We did not retrieve it” is not “the document does not contain it.” The live reviewer disproved two such gaps using existing sources. |
| Overlapping stage quotas could stop useful work while overall capacity remained. | Made stage/cumulative targets guidance and telemetry; retained the authoritative overall deadline, configured call ceiling where applicable, provider capacity, watchdogs, cancellation and hardware guards. This campaign authorized a null call ceiling. | Scheduling preferences and hard safety/resource limits serve different purposes. Simplifying controls helps execution; it does not establish factual quality. |
| Review needed access beyond the supplied excerpts and an optional verification route. | Configured GPT-6 for reviewer/rechecker and explicit optional web verification, with original-source capture, provenance and cutoff handling. Fixed-corpus mode remains offline. | Record requested versus reported model identity. A combined model/tool change cannot isolate a model’s contribution; unused web capability is not a demonstrated success. |
| PDF delivery looked successful despite typography, source-label, table and pagination problems. | Moved reusable presentation into the normal writer/exporter: embedded Chinese fonts, measured rows, repeated headers, content-based widths, numeric alignment, keyed notes, chart values, source links and measured heading placement. | Export completion, text preservation and readable appearance require separate checks. Presentation is part of the product, not decoration added after acceptance. |

These changes extend the existing workflow, source store, StageContext, reviewer and revision path. They do not add another agent hierarchy or an indefinite review loop. The detailed historical rationale remains in [PATH_REVIEW.md](coherent-retrieval/PATH_REVIEW.md), [rubric implementation](coherent-retrieval/rubric-review/IMPLEMENTATION.md) and [budget simplification](coherent-retrieval/BUDGET-SIMPLIFICATION.md); read their claims at their recorded versions, not as current live outcomes.

## Concrete problems solved in the final campaign

- **Nullable call ceiling:** the normal stage request performed arithmetic on a null call quota. Corrected the telemetry/admission path while preserving deadline and concurrency checks.
- **Metadata expansion:** 946 original fragments contained only 59,016 bytes of original text, but repeated geometry inflated the request. Shared location indexes and compact columns preserved exact text/spans while fitting the request. No ranking changes or evidence truncation were used to force admission.
- **Planner recovery:** the importer demanded a writing-context file that a completed planner does not create. Recovery now validates the files appropriate to each stage and their hashes.
- **Revision figures:** draft image paths were mistaken for missing revised images, causing duplicate charts. Known figure filenames now bind to the current manifest before placement.
- **Citation and emphasis formatting:** Chinese citation brackets could be split into notes; punctuation normalization could consume adjacent emphasis. Both were corrected without changing underlying facts.
- **Pagination and fonts:** nominal heading spacing orphaned headings before whole charts/lists. Actual following-block measurement fixes placement. Font glyph aliases caused extraction errors and one Chinese fallback; canonical/common Chinese glyph priorities fixed those cases. Full font embedding avoids the malformed subset output we observed. Rejected PDFs remain saved; text-preservation checks were not weakened.

Completed research was preserved through these corrections. No retrieval benchmark was rerun. The earlier benchmark remains **9 passes / 7 partial**, not a retrospectively declared pass.

## What the live run demonstrated

The normal command performed fresh planning and industry/company research from the original brief and five-source corpus, without historical answers or assessor findings. After engineering recovery, it completed follow-up, synthesis, independent rubric review, revision, focused recheck and export. It was **not an uninterrupted run of the final code**.

The researcher’s follow-up restored the beginning of Longtu’s split customer list. That original reached synthesis. The independent reviewer then opened original pages and found three material omissions:

1. Qingyi’s 2025 semiconductor-mask revenue of **2.04亿元**, with **5.63%** growth, distinct from total company revenue.
2. Existing source support for the qualitative quartz-versus-soda substrate comparison.
3. Qingyi’s display-product progress, with **mass production, successful development and ongoing research** distinguished.

The normal orchestrator routed these directly to revision because the reviewer had already supplied sufficient evidence. Actual revision/recheck requests contained 1,036 original fragments, including the recovered support; checked texts matched canonical source spans. The recheck resolved all three findings. The four substantive rubric criteria were **Meets**; communication was **Partly meets**, followed by local presentation corrections and page inspection.

Outcome: **ready with disclosed limitations**, with **partial research coverage**. The final 11-page edition passed unchanged Markdown-to-PDF text preservation, every page was visually inspected, all font programs are embedded, and all five source URLs are active PDF links. Two post-review editorial changes—separating commercialization dimensions and adding sourced acronym explanations—are disclosed as local source-checked edits, not another independent model review.

This campaign used **20 model calls**, **1,290.829 generative seconds**, **58,579 observable output tokens** and about **1h44m total elapsed time**. Reasoning tokens were not added twice. Research/writing requested `gpt-5.6-sol`; review/recheck requested `gpt-6-astra`. Actual model identity was unreported by the provider. Historical ledgers were not reset or reopened.

## Lessons to carry forward

1. **Measure the real path.** Cold model initialization, preparation, inference, returned relevance and complete context are separate concerns. Mocked contracts cannot prove CPU feasibility or research quality.
2. **Inspect the first divergence.** Saved failed requests, rejected PDF bytes and original spans made targeted corrections possible. Increasing limits or restarting the pipeline would have hidden the actual causes.
3. **Check evidence at the receiving boundary.** A useful passage in a candidate pool is not proof that the researcher saw it, nor that the writer received it. Inspect actual returned blocks and serialized requests.
4. **Keep dimensions compatible.** Product scope, customer validation, production scale and revenue contribution are different facts. A convenient universal commercialization ladder can mislead even when individual labels are correct.
5. **Use bounded review for material improvement.** Broadly useful analysis plus targeted source checks served this report better than an exhaustive claim-certification requirement. Preserve examined/unexamined scope and unresolved material issues.
6. **Do not confuse status layers.** Execution complete, coverage complete, review complete, report ready and PDF exported are distinct outcomes. Provisional coverage labels can become stale; consult original evidence and recorded resolutions.
7. **Preserve expensive success.** Stage-aware recovery and immutable evidence let us repair orchestration and presentation without paying for successful research again.

## Remaining limits and where to resume

Comparable segment margins/utilization, some supplier detail, global market quantification and a complete explanation of Longtu’s profit decline remain unsupported by the delivered originals. Some provisional coverage descriptions remain stale after successful local recovery; they are not authoritative absence claims. Optional web verification and reviewer-triggered research were not needed in this final run and remain untested here. Full fonts make the PDF roughly 30 MB. The final presentation/prompt version has not completed another uninterrupted live run, and this familiar task does not establish generalization to unseen questions or industries.

Do not restart successful research or clean the database to create a clean-looking result. Any future acceptance should target a concrete remaining uncertainty under new authorization, while retaining these observations.

The best report, exact normal command/configuration, validation, usage and artifact paths are in [the delivery handoff](presentation-live-20260912/HANDOFF.md). Runtime/report implementation is `10c2436`; delivery documentation is `c6cb320`; this wrap-up adds documentation only. Large local reports, original corpora, environments and raw execution records remain preserved in their existing artifact directories rather than being bulk-added to Git. The original checkout’s unrelated unfinished edits remain untouched. No tests, provider calls or research stages were repeated for this Git/documentation closeout.
