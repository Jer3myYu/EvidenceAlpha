# Bounded readiness and evaluation proposal — not executed

The implementation and deterministic checks are complete. This proposal does
not authorize installs, downloads, inference or provider calls. Existing campaign
ledgers and the consumed e80e141 test allowance remain unchanged.

1. **Explicitly authorize dependency/model preparation.** Inspect the local
   environment without modifying shared packages. Resolve a compatible isolated
   environment from the declared `retrieval` extra; pin actual versions. Resolve
   `BAAI/bge-reranker-v2-m3@953dc6f` to its full SHA. Acquire only its safetensors,
   tokenizer/config/license files, at most 4 GiB and 15 minutes, one attempt.
   Record `snapshot.json` in the local model directory with `model`, full
   `revision`, and relative filename→SHA-256 `files`. Set `reranker_path` to that
   directory. No moving revision, hidden network fallback or alternative model.
2. **Authorize one local neural readiness/evaluation attempt separately.** Freeze
   12 saved company-stage queries and four independently selected controls before
   inference. Record selection/annotations outside production inputs; historical
   diagnostic targets are not held-out controls. One configuration, at most 16
   queries/2,048 pairs/10 minutes total, 8 GiB sampled RSS and four CPU threads.
   No parameter sweep, model comparison or generative-provider call. Measure
   load/score time and peak observed RSS; score candidate support, returned-block
   relevance and complete bundles separately. Current per-search limits include
   cold loading (30 seconds); stage limits are 120 seconds/2,048 pairs. If those
   provisional settings fail, preserve results and stop for a concrete resource
   decision, not automatic tuning or a silent model substitution.
3. **Confirm writer admission without a provider probe.** Verify the supported
   writer's context capacity from available runtime metadata/documentation; set
   `writer_context_tokens`. Current admission uses a 64,000-token input ceiling,
   conservatively estimated using UTF-8 bytes, clipped by known capacity minus
   12,000 output and 4,096 transport-reserve tokens. This is not exact provider
   tokenization or knowledge of hidden transport context. If those facts cannot
   support safe admission, record the blocker; do not call a provider to guess.
4. **Only after readiness, authorize one company-stage evaluation.** Freeze the
   implementation commit, dependency/model manifests, original brief/task and
   full eligible corpus, with a separate explicit non-resetting ledger. Use
   GPT-5.6 Sol medium on the existing supported subscription path. At most eight
   calls including one tool-free writing call; 32 tool executions; 600 seconds
   worker and summed provider time; 180-second protected writing reserve;
   300 seconds per invocation; 780 seconds execution/export; 12,000 observable
   output tokens, adding reasoning only if explicitly nonoverlapping. Neural
   work also consumes worker time and its own pair/time caps. No retry, external
   acquisition, extra reviewer, full report, provider fallback or model switch.

Do not seed previous notes, selected passages, coverage assignments, assessor
answers or industry-stage findings into the company test. Changed eight-versus-six
call effort prevents attributing improvement solely to retrieval. Assess required
coverage, source support, handoff/notes preservation, completion and PDF delivery
separately. Essential missing explanations/relationships remain partial coverage.
One stage cannot establish repeatability, full-report acceptance or broad quality.

Stop after the bounded attempt. Diagnose from saved artifacts; no automatic
patch/rerun campaign. If the user instead requests only remaining deterministic
work, no neural/provider allowance is implied.

A ready-to-use next instruction:

```text
Read coherent-retrieval/HANDOFF.md and READINESS.md and verify the current
isolated branch, diff and prior usage records. Prepare the exact dependency and
snapshot manifest for review using local inspection only. Do not install,
download, run inference or call providers unless my message explicitly
includes the corresponding numbered readiness step and its resource budget.
Do not rerun the completed e80e141 company test or change historical ledgers.
```
