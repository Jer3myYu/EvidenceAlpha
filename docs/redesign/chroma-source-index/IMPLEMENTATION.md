# Structural chunks and local hybrid retrieval

This extends the existing SourceStore → candidates → original reading → contextual
reranking → StageContext writing path. The prototype and injected-vector results
remain unchanged in DESIGN.md and RESULTS.md.

## Storage and chunking

Original bytes, parsed text, legacy chunk IDs and citations remain authoritative
on disk. A new Chroma directory holds vectors and immutable references, without
another document-text copy. `units.json` maps derived units to original spans;
`ready.json` binds model/tokenizer artifacts, policy, corpus and stored vectors.
Existing databases are never migrated or cleaned by these commands.

`structural-token-units-1` packs small elements within the same source, section,
page and kind, up to 384 encoder tokens including prefix/special tokens. Headings
and tables stay separate. Oversized paragraphs prefer sentence boundaries; an
oversized sentence uses explicit lossless character fragments. This is structural
and token chunking, not LLM semantic segmentation.

Table rows repeat the first original row when capacity allows. Header association
remains unknown: navigation context is not certified table semantics. Parsing and
layout quality still limit recognition. Original pages and continuations remain
accessible. We do not add fixed overlap everywhere; reading windows supply context.

Installed multilingual E5-base uses `query: ` / `passage: ` prefixes, attention-mask
mean pooling, L2 normalization and CPU float32. Inputs are checked against its
512-token capacity without truncation. These conventions follow the
[official model card](https://huggingface.co/intfloat/multilingual-e5-base).

## Retrieval and preservation

Each branch nominates up to `candidate_limit` items. Equal-weight reciprocal rank
fusion (constant 60) deduplicates original anchors and retains the configured final
pool. Multiple dense units sharing an anchor use the highest-ranked match.
This is not a first-N passage gate on writing evidence.

Dense matches resolve through SourceStore. Reading retains existing structural
context plus every original span of the nominated embedding unit. Those spans
remain mandatory in bounded reranker input construction. Oversized required
support is reported rather than silently truncated. Final selection, source opens,
evidence settlement and payload-aware writing use existing runtime contracts.

Every uncached search starts an offline encoder worker and closes it before
starting the reranker worker; the reranker also reloads per uncached search.
Traces distinguish preparation, snapshot verification, encoder initialization,
embedding, index validation/query, reranker initialization/scoring, total latency
and sampled RSS. No warm resident-model benchmark is substituted.

## Normal commands

Use an environment with the declared `vector-index` and `retrieval` extras and
explicit installed model paths. Commands do not download models.

```bash
PYTHONPATH=src .venv/bin/python -m evidencealpha.cli \
  --config /absolute/settings.json index-corpus \
  --corpus /absolute/corpus --output /absolute/new-index

PYTHONPATH=src .venv/bin/python -m evidencealpha.cli fixed-corpus \
  --execution /absolute/execution.json --output /absolute/new-run
```

The first configuration is a normal Settings object. In execution.json these
same fields go inside `settings`, alongside the original brief and `corpus`:

```json
{
  "vector_index_path": "/absolute/new-index",
  "dense_model_path": "/absolute/installed-e5-snapshot",
  "dense_model_revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
  "dense_python": "/absolute/python-with-vector-extra",
  "embedding_unit_tokens": 384,
  "dense_operation_seconds": 900,
  "candidate_limit": 64,
  "retrieval_limit": 6,
  "reading_window_characters": 8000,
  "reranker_search_seconds": 300,
  "reranker_threads": 4,
  "reranker_memory_bytes": 8589934592,
  "workers": 1
}
```

Retain explicit installed reranker path/revision and normal provider settings.
Preflight checks index/corpus compatibility before planning; query workers verify
full model/vector contents. `vector-index-freeze.json` records the snapshot.
Without an index path the existing lexical-candidate mode remains selected; old
Chroma databases are never selected implicitly.

Capacity limits protect actual encoder input, reading representation, total search
latency and sampled 8 GiB worker RSS. The existing workflow deadline and provider
controls remain authoritative. The dense-operation watchdog does not add a new
campaign quota; search cancellation/deadline can stop the worker earlier.

This version supports a frozen corpus snapshot. New/changed sources require a new
explicit index build. Web acquisition that changes the corpus cannot silently use
a stale index as coverage of those new sources. Incremental indexing and global
admission across multiple application processes are not implemented.

## Evaluation

The eight questions in `data/hybrid-evaluation/EVALUATION.json` were frozen before
inference. Both variants use the same final candidate/block settings and BGE
reranker. GPT-6 judges blind A/B originals for investor usefulness and material
qualifiers; irrelevant extras alone do not fail a query. Missing retrieval is not
document-wide absence. There is no exhaustive claim certification or recall claim.

`scripts/evaluate_hybrid_rag.py` uses normal EvidenceTools and StageContext and
checks exact original → returned → writing preservation. `judge_hybrid_rag.py`
uses the installed GPT-6 provider without source acquisition or answer keys.
Requests, capacity checks, requested/reported model and usage are preserved.
The measured outcome and exact local commands are in LIVE-RESULTS.md.

This familiar corpus does not establish unseen-industry generalization. All older
benchmarks and report campaigns retain their recorded outcomes.
