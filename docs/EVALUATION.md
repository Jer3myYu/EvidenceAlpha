# Evaluation and limitations

EvidenceAlpha is evaluated primarily on whether its report serves the brief:
explains an unfamiliar industry, makes meaningful comparisons, uses sources
responsibly and discloses important unknowns. A retrieval benchmark and a
successful export answer different questions from report quality.

## Review contract

The independent reviewer assigns **Meets**, **Partly meets** or **Does not meet**
to five criteria, with explanations:

1. Answers the brief.
2. Builds understanding.
3. Provides useful analysis.
4. Uses evidence responsibly.
5. Communicates clearly.

There is no weighted score. Targeted source checks focus on pivotal figures,
technical/commercial status, central conclusions and suspicious absence claims.
The reviewer records examined scope and limitations. Material findings route to
focused research, revision or explicit qualification; recheck preserves unresolved
issues. An empty findings list alone is not a completed review.

## Latest report case: Nanfei Microelectronics

The September 2026 Nanfei campaign used a newly prepared public-source corpus,
fresh planning and industry/company research, followed by corrective review.
Sources were discovered/captured by an operator; the application ran fixed-corpus
research. Engineering recovery reused completed stages rather than restarting
the whole pipeline.

| Outcome | Recorded result |
|---|---|
| Chinese report | Ready with disclosed limitations; coverage partial |
| Material review findings | UALink development omission and insufficient domestic competitor comparison |
| Corrections | UALink evidence went directly to revision; the competitor gap received focused source opens, then revision |
| Focused recheck | Both material findings resolved; four criteria Meets, understanding Partly meets |
| Remaining explanation issue | PCIe Switch insufficiently defined |
| Delivery | 12-page Chinese PDF and 17-page English submission translation, with source mapping and figures |
| English evaluation | Targeted fidelity and rendered/text-preservation checks, not independent factual review |

The report distinguishes FPGA/protocol validation from ASIC silicon validation
and mass production. It uses historical Centec comparisons without extrapolating
them to a current competitive ranking. A sourced ES8000 chart compares stated
8.0/6.4/3.2 Tbps product configurations, not measured throughput or sales.

Nanfei audited financials, named trading relationships and model-level commercial
status remain unresolved. Company representations are not independent performance
testing. The run does not establish that missing information is absent from every
public source.

**Provenance:** final Chinese continuation `c808a5a`; later English presentation
fixes/handoff `eee4fe0`, integrated at `46edcb4`. Requested models were GPT-5.6 Sol
for research/writing/translation and GPT-6 Astra for review/recheck; actual model
identity was unreported. The preserved record reports **169.59 minutes wall
elapsed**, **47 unique invocations**, **33.74 minutes summed recorded invocation
time** and **73,992 observable output tokens**. Interruption accounting is partly
unknown. These include preparation, recovery and English translation; they are
not a promise of future runtime or a complete monetary cost measurement.

The original
[Nanfei handoff at its recorded commit](https://github.com/Jer3myYu/EvidenceAlpha/blob/46edcb4/docs/redesign/chroma-source-index/NANFEI-LIVE.md)
provides historical provenance. Raw reports, source corpora, traces and ledgers
are local assets, not included in a clone.

## Retrieval evidence is separate

A prior five-document hybrid evaluation found **4 Useful / 3 Partial** substantive
answers, versus **3 Useful / 4 Partial** for lexical candidates with the same BGE
reranker. Both variants answered the additional boundary question usefully.
The target of five Useful substantive answers was **not met**. The same test
observed median full-search latency of 74.7 seconds hybrid versus 43.2 seconds
lexical. This was one sequential CPU evaluation, not a statistical latency study.

The combined chunk/candidate/context path changed, so the gain cannot be
attributed to Chroma alone. Candidate presence, returned-block relevance,
supporting context and writing preservation are distinct checks. Source counts
are not accuracy, and returned-span counts are not independent facts.

The older **9 pass / 7 partial** benchmark is another historical result; neither
benchmark is relabelled by later report delivery. Details remain in the
[recorded hybrid results](https://github.com/Jer3myYu/EvidenceAlpha/blob/46edcb4/docs/redesign/chroma-source-index/LIVE-RESULTS.md).

## What is and is not established

- **Implemented and exercised:** normal workflow, source-preserving handoff,
  targeted reviewer source access, focused correction/recheck and sourced export.
- **Case-study evidence:** useful explanatory reports with actual corrections and
  disclosed gaps, after engineering/operator recovery.
- **Not established:** uninterrupted autonomous reliability, exhaustive factual
  accuracy, human-investor comprehension, or generalization across unseen briefs.
- **Operational limits:** expensive uncached neural search, finite context,
  incomplete source metadata, frozen rather than incremental indexes, and no
  global worker admission across separate application processes.
- **Known follow-up work:** research repetition, broader parsing/table validation,
  compatible checkpoint/cancellation regressions, legacy fixture modernization,
  table-title pagination and the proposed Studio interface.

Use focused deterministic checks for contracts and saved-output replay for
orchestration. Neither replaces live quality evaluation. Future work should
preserve failed outcomes and test genuinely new briefs and target-user usefulness,
rather than tune known examples toward a perfect score.
