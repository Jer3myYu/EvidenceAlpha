# Live hybrid-RAG results

Integration is implemented and operational on the five-source corpus. The blind
GPT-6 assessment found a modest usefulness gain, with a substantial latency cost.
Hybrid: **4 Useful / 3 Partial** substantive questions; lexical baseline:
**3 Useful / 4 Partial**. Both boundary controls were Useful. The frozen target of
at least five Useful substantive questions **was not met**. No criteria were
relaxed and no cases were tuned or rerun to improve this result.

This is a useful optional retrieval path, not evidence that one broad search can
complete every report requirement. Keep focused research and original-source opens
for unresolved questions. We did not change the default automatically or produce
another company report. The single-query evaluation target is not a new runtime
gate on normal research: combining evidence across questions and opening originals
remain valid workflow actions, but their recovery outcome was not tested here.

## What ran

- Runtime `1f00566`, following integration commit `5f1ccd3`, on branch
  `chroma-source-index`. Runtime source hashes matched the retrieval freeze after
  all queries. Later changes only document results and refine evaluation tooling.
- One real offline E5 index build from all five original production documents:
  10,627 legacy chunks → 6,973 derived search units. Originals and old databases
  were not rewritten. No model downloads, dependency installs, source acquisition,
  old benchmark reruns, full research runs, push or merge occurred.
- Eight frozen questions × two variants through normal `EvidenceTools` →
  `Retriever` → `StageContext`, with actual E5/BGE inference where applicable.
  All 16 searches completed within the configured 300-second search watchdog.
- Two sequential GPT-6 application invocations judged anonymous A/B evidence.
  They saw original returned text and locators, not implementation labels,
  reference answers or historical researcher notes. No source tools/web calls.
- One offline combined writing-handoff replay from saved search results. This is
  plumbing/capacity validation, not an autonomous researcher or writer success.

The original 9-pass/7-partial retrieval benchmark remains a separate historical
result. These new familiar questions do not establish generalization.

## Frozen questions and quality

Full wording and acceptance are versioned in [EVALUATION.json](EVALUATION.json).
Useful means the evidence enables a useful, qualified investor answer; it does
not require perfect precision or verification of every claim. Partial means a
material part of the asked question remains unsupported in the returned evidence.
Missing retrieval is not treated as proof of document-wide absence.

| Question | Topic | Lexical + BGE | Hybrid + BGE |
| --- | --- | --- | --- |
| Q01 | Industry function and value chain | Useful | Useful |
| Q02 | Technical barriers, qualification and risks | Partial | Partial |
| Q03 | Qingyi semiconductor scale and technical status | Partial | Useful |
| Q04 | Luw milestones and customer relationships | Useful | Useful |
| Q05 | Longtu operating changes and financial scope | Partial | Partial |
| Q06 | Comparable three-company financial totals | Partial | Partial |
| Q07 | Supplier/customer roles and industry relationships | Useful | Useful |
| Q08 | Unsupported future-price boundary | Useful | Useful |

Concrete findings:

- **Q03 improved:** hybrid retained Qingyi's technical-status distinctions in the
  returned blocks and writing evidence. The 180nm/150nm/28nm locators were already
  present in baseline candidate and scored contexts, but absent from its returned
  blocks. This is a final selection/context improvement, not proof that baseline
  candidate recall was zero. Hybrid nominated more views carrying that support.
- **Q02 remained Partial:** hybrid supplied more complete operating-risk context,
  but neither returned enough about qualification steps/cycles and commercial
  conversion. GPT-6 also distinguished a person's prior-employer experience from
  the reporting company's own technology status.
- **Q05 remained Partial:** hybrid returned directly qualified monetary amounts;
  the baseline's annual financial table lacked its own unit heading. Neither
  established the specific causes of the reported operating change. General
  industry conditions were not promoted into company-specific causal claims.
- **Q06 remained Partial:** neither returned all three companies' comparable
  financial totals, periods, units and consolidation scope. Customer concentration
  rules and customer-sales subsets were correctly kept separate from consolidated
  company totals.
- **Q04/Q07 were useful in both:** the assessor retained single-mask versus
  complete-set, sampling versus supply, planned versus achieved, and supplier
  versus customer distinctions. Extra unrelated results alone did not cause failure.
- **Q08 is an answer-boundary check:** GPT-6 declined a source-grounded future-price
  prediction. The retriever still returns nearest matches; this is not a tested
  automatic abstention classifier or a new autonomous researcher result.

Follow-up targets above are findings, not demonstrated recovery successes. We did
not infer that the missing mechanisms or financial information are absent from
full documents. A better final report still requires targeted research/opening
where the brief needs them.

## Preparation, candidates, ranking and reading are separate

1. **Storage coverage:** every non-whitespace character of the original parsed
   structural blocks is represented in derived units: 233,237 characters, zero
   omissions. This does not certify PDF extraction, table semantics or topic recall.
   There are 6,247 table units, 723 paragraph units and three heading units; the
   corpus's financial tables remain highly granular. No fallback character splits
   were needed in this corpus.
2. **Candidates:** both configurations retained 64 candidates per query and
   returned six reading blocks. Hybrid uses lexical plus dense nominations with
   equal-weight rank fusion. Candidate source counts/provenance are saved in
   PERFORMANCE.json and the original traces. There are no exhaustive relevance
   annotations, so no recall, precision or NDCG percentage is claimed.
3. **Neural ranking:** BGE weights and scoring limits stayed identical. All
   candidates were scorable. Q03's post-hoc diagnostic follows candidate → scored
   view → returned original → writing evidence; its terms never entered runtime
   logic or queries. The combined chunk/candidate/context change is evaluated,
   rather than attributing the gain to Chroma alone.
4. **Reading/handoff:** every individual query preserved its returned originals
   into the tested writing view. Combined replay retained all 812 hybrid passages
   in a 117,702-byte request, versus 633 baseline passages in 92,625 bytes, with
   zero omissions. The checked visible-input allowance was 242,304 tokens using
   the application's conservative byte upper estimate, not a provider byte limit.
   These are original-span counts, not 812 independent facts. Full paragraph or
   window status does not certify complete supporting meaning or table units.

## Actual performance

CPU float32, four Torch inference threads, one local inference worker at a time
in this evaluation, sampled worker RSS limit 8 GiB. Each uncached search reloads
the encoder/reranker; no resident-model shortcut was benchmarked. File caches may
be warm, and this is one sequential pass, not a statistical latency study.

| Measure | Lexical + BGE | Hybrid + BGE |
| --- | ---: | ---: |
| Median complete search | 43.2 s | 74.7 s |
| Range | 36.3–71.0 s | 58.3–90.9 s |
| Median preparation | 0.82 s | 15.20 s |
| Median BGE initialization | 1.52 s | 1.50 s |
| Median scoring | 36.22 s | 53.87 s |
| Actual scored pairs, eight queries | 410 | 407 |
| Mean scored-view characters | 357.2 | 516.2 |
| Peak sampled BGE RSS | 2.17 GiB | 2.20 GiB |

Hybrid has roughly 73% higher median end-to-end latency. Its median encoder
initialization was 3.65 s, full index open/validation 5.47 s, and vector query
0.257 s. Advertising the vector-query time as complete retrieval latency would
be misleading. Longer scored views accompany the extra BGE time; pair count alone
does not explain inference cost.

The one-time build took 789.3 s: chunking 4.55 s, embedding 660.85 s, indexing
99.09 s, plus initialization/snapshot/startup. Peak sampled build RSS was 2.92 GiB;
query encoder peak was 1.71 GiB. RSS sampling is not an instantaneous peak or
measurement of total system memory. Original 30-second search assumptions would
not fit either variant here; the admitted setting was 300 seconds.

## Versions, model identity and usage

- Encoder: `intfloat/multilingual-e5-base`, revision
  `d128750597153bb5987e10b1c3493a34e5a4502a`; artifact SHA-256 hashes, pooling,
  normalization, prefixes and 384-token unit policy are in index/ready.json.
- Chroma `1.1.1`; encoder environment: Python 3.12.13, Torch 2.14.0+cpu,
  Transformers 5.16.1, tokenizers 0.23.1, NumPy 2.5.2. The fast tokenizer uses the
  installed tokenizer.json; sentencepiece is not installed in that environment.
- Reranker: `BAAI/bge-reranker-v2-m3`, revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, reused from runtime/reranker.
  Separate preserved environment: Torch 2.6.0+cpu, Transformers 4.57.6,
  tokenizers 0.22.2, NumPy 2.5.3. Explicit `dense_python` keeps dependencies isolated.
- Assessor requested `gpt-6-astra`, medium, through codex-cli 0.154.0. Both calls
  succeeded; the provider **did not echo actual model/effort identity**. No silent
  fallback was used. The installed catalog reports 272,000 context tokens, 95%
  effective allowance, and no explicit output ceiling. Actual prompt/schema sizes
  were checked with output/transport reserves; the reserve is not a hard output cap.
- New application usage: **2 generative calls,
  287.0 summed seconds, 152,471 input tokens,
  9,100 reported output tokens**. Reported reasoning
  output was 138 tokens, listed separately
  rather than added again. Host coding-assistant usage is unavailable. Local build
  and retrieval consume elapsed time but are not generative invocations. Historical
  ledgers were neither reset nor reopened; final elapsed usage is in ledger.json.

## Validation, commands and artifacts

Focused deterministic checks cover original-span/token-unit coverage, immutable
index rejection, normal candidate wiring, writing lineage, bounded scoring and
child cancellation/reaping. Evaluation entry guards also refuse existing/closed records before any writes.
The relevant checks, Black and Pylint passed after
preserved setup/style corrections. No full test suite or old benchmark was repeated.
The 513-token tokenizer warning in build logs occurred during size counting;
actual model input checks reject oversized tensors and never truncate them.

Working directory:
`/home/cobot/cobot_storage/webproject/EvidenceAlpha/worktrees/chroma-source-index`

```bash
# Actual completed index build; use a NEW output path for another build.
PYTHONPATH=src ../../.venv/bin/python -m evidencealpha.cli \
  --config data/hybrid-evaluation/settings.json index-corpus \
  --corpus ../../data/redesign/focused-diagnostic/frozen/corpus \
  --output data/hybrid-evaluation/index

# Actual completed paired retrieval and GPT-6 assessment; not restart commands.
PYTHONPATH=src ../../runtime/environment/bin/python scripts/evaluate_hybrid_rag.py \
  data/hybrid-evaluation ../../data/redesign/focused-diagnostic/frozen/corpus
PYTHONPATH=src ../../runtime/environment/bin/python scripts/judge_hybrid_rag.py \
  data/hybrid-evaluation

# Normal report command configured for the new index; NOT launched in this task.
PYTHONPATH=src ../../runtime/environment/bin/python -m evidencealpha.cli fixed-corpus \
  --execution data/hybrid-evaluation/fixed-corpus.example.json \
  --output data/redesign/new-hybrid-report
```

Local artifacts below are ignored runtime data, not GitHub-hosted datasets:

- [Frozen runtime/settings](../../../data/hybrid-evaluation/retrieval-freeze.json)
- [New index and encoder hashes](../../../data/hybrid-evaluation/index/ready.json)
- [Performance](../../../data/hybrid-evaluation/PERFORMANCE.json),
  [quality with all eight judgments](../../../data/hybrid-evaluation/QUALITY.json)
- [GPT-6 batch 1](../../../data/hybrid-evaluation/judge-1/assessment.json),
  [batch 2](../../../data/hybrid-evaluation/judge-2/assessment.json); their directories
  also preserve exact requests, raw events and usage.
- [Q03 context diagnostic](../../../data/hybrid-evaluation/Q03-context-recovery.json)
- [Combined handoff replay](../../../data/hybrid-evaluation/combined-handoff/RESULTS.json)
- [Additive ledger](../../../data/hybrid-evaluation/ledger.json),
  [usage](../../../data/hybrid-evaluation/USAGE.json)
- Exact executed evaluation scripts: `data/hybrid-evaluation/retrieval-executed.py`
  and `judge-executed.py`; current helpers additionally protect existing records.
- Per-case originals, traces and selections: `data/hybrid-evaluation/Q01` through Q08.

The index is an immutable snapshot: changed/new corpus documents require a new
explicit build. Incremental online indexing, large-corpus scaling, full autonomous
research recovery and final report quality were not validated here. The existing
best report and historical runs remain unchanged. All evaluation workers were reaped.
