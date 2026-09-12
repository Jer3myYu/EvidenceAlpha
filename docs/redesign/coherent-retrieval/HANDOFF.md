# Coherent retrieval implementation handoff

Implemented locally on `coherent-retrieval-implementation` in
`/home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval`, based on
`e80e1415ea3fd161503ea3532e7b5ec9cdaeaef9`. Thus this branch includes the previous
session's timing/navigation fixes. Nothing was pushed or merged to `main`.
The shared checkout and the clean company-stage test worktree were preserved.
The shared `.venv` is linked for existing tools; no packages were installed.

The user-authorized implementation supersedes the design document's earlier
“design only” stopping point. [DESIGN.md](DESIGN.md) is retained as the proposal;
this handoff records actual implementation and its limits.

## Implemented behavior

- `retrieval.py` owns the unchanged binary lexical scoring formula, a separate
  configurable candidate pool (default 64), source filtering before selection,
  stable ranking, contextual scoring, result deduplication and candidate traces.
  The runtime returns at most six structural reading blocks. Raw candidate-only
  text does not enter settled evidence. Explicit `degraded_lexical` uses the same
  structural/selection path; default reranking never silently degrades.
- `reading.py` provides original structural windows, whole rows/sentences,
  original version/spans/chunk bindings, page access, version-bound continuations
  and explicit oversized/partial/unknown-association statuses. The old
  `surrounding_passages` API delegates to it for compatibility. Source bytes,
  parser versions and historical citations were not migrated or rebound.
- `reranking.py` implements local-only Transformers loading behind an injectable
  scorer, whole-unit token windows, query-local logits, finite pair/time budgets,
  cancellation and child cleanup. Missing snapshot returns unavailable without
  starting a model process. The model path, resource limits and compatibility
  are provisional. No model was loaded in this session.
- Existing `StageContext` now holds provisional questions and support bundles.
  Updates validate known references/scope and accept semantic judgments only as
  provisional. All IDs in one support update form required support together;
  conflict sides are atomic. Exhausted exploration is distinct from supported
  coverage. Focused child questions represent separate required facts or
  explanations, avoiding a new facet ontology or evidence certification graph.
- The source-share/96-passage/16,000-character selector was removed. One selector
  serves research, writing and fallback. It first includes every eligible original
  if the complete request fits. Under pressure: task priority, adequate before
  unassessed within that priority, round-robin questions, conflict support, cost,
  then stable IDs. Adequate dependency closure also applies to older unassessed
  aliases, preventing orphan facts. Full omission manifests remain on disk;
  prompt previews are bounded. Delivered coverage is separate from durable
  provisional coverage and cannot upgrade it.
- Complete request accounting includes JSON escaping and the separate output
  schema. UTF-8 bytes are exact; token counts currently use a conservative byte
  estimate, not a writer tokenizer or BGE tokens. Unknown writer context capacity
  blocks real-provider admission. Final notes omit research-only bundle-update
  metadata while retaining originals, coverage and structural limitation counts.
- Tool/schema/prompt/runner contracts carry question IDs, coverage updates,
  next actions and stop reasons. Early research completion transitions to a
  separate tool-free writing call. Tool counts and evidence turns are separate;
  stage counters/traces are isolated even when one runner serves multiple stages.
  The 600/180/300-second worker/reserve/invocation allocation is retained.

## Validation and evidence

**56 focused deterministic tests passed; 10 unrelated cases were deselected.**
The command and complete result are recorded in
[validation-final.txt](../../../data/redesign/coherent-retrieval/validation-final.txt).
The selection checks were rerun after final envelope changes; the navigation
checks were rerun after making the legacy API delegate to the shared helper.
No full fixture or live pipeline was run. Earlier failing checks are retained
in the same artifact directory, not overwritten as successful runs.

Tests include injected relevance scores, unavailable snapshots, pair accounting,
cache hits, actual Python sleeper-process timeout/RSS/cancellation cleanup,
atomic support/conflict selection, strict schema behavior, tool budgets,
immutable spans, oversized reading windows and protected writing allocation.
Injected scoring and sleepers establish contracts/control flow only. They do
not establish CPU model feasibility, retrieval relevance or research quality.

The actual saved 103-passage context was checked with
[validate_saved.py](validate_saved.py), using new output directories only.
The final envelope includes all 103 passages in **51,669 UTF-8 bytes**, including
all seven references omitted from the historical writing view. At a deliberately
smaller **41,335-byte** budget it keeps 48 passages, including the protected
support, and discloses every omission. Original, reversed and fixed-seed shuffled
arrival orders yield the same selection. Assessor mappings are validation-only,
never production task initialization. See
[saved regression results](../../../data/redesign/coherent-retrieval/validated-saved-regression/results.json).
All 56 frozen baseline files matched their recorded SHA-256 hashes.

Black, focused pylint and diff whitespace checks are recorded beside the tests.
Review covered the shared call path, removed selectors/embedding fusion,
provisional coverage semantics, strict output schemas, dependency closure,
concurrent-stage state isolation and absence of issuer-specific runtime rules.
No tests or scores certify factual support assigned by a model.

## Separate PDF diagnosis

One reproduction from unchanged saved Markdown/figures failed as recorded.
The rejected PDF and diagnostics were saved **before** diagnosis:
[rejected PDF](../../../data/redesign/coherent-retrieval/pdf/original-reproduction/report.rejected-7e0b6a5fcb04.pdf).
Extracted text and rendered page 2 showed a long punctuated citation clipped
past the last table column. The prior line-breaking rule covered only long
alphanumeric runs, missing this citation.

The renderer now inserts zero-width break opportunities in long ASCII runs in
cells, including punctuation. The existing normalized text-preservation test
is unchanged. One repaired derivative export passed, and the financial table
was visually inspected with the citation fully visible:
[repaired PDF](../../../data/redesign/coherent-retrieval/pdf/repaired-derivative/report.pdf).
The Markdown hash is unchanged. Neither derivative replaces the original failed
export record, and the historical unsaved PDF was not reconstructed as history.

## Remaining limitations and implementation decisions

The first candidate retains lexical recall limitations and geometric structural
heuristics. Header/footnote association is not certified. Indivisible oversized
units remain explicit gaps. Packing is deterministic greedy selection, not
optimal packing. The minimum coverage unit is a focused question; authors must
split distinct requirements rather than treating an entire company as supported.

The optional local scorer currently closes/reaps its process after each uncached
search to enforce one resident worker; cache hits reuse scores, not model weights.
Consequently uncached searches include cold loading. This is a deliberate bounded
implementation boundary, not validated latency. RSS is sampled during supervision;
it is not a proof against transient memory overshoot. A later measured readiness
check must decide whether this process policy meets the provisional stage limits.

The full model SHA, artifact manifest and tested dependency lock remain unresolved.
The former optional raw embedding-score addition is explicitly rejected. Legacy
configuration fields and exact-chunk readers remain only for named compatibility;
no second production workflow is retained. Full-pipeline/provider integration and
new model output quality remain untested. The previous successful e80e141 model
test is reused, not repeated or relabeled as validation of this implementation.

See [READINESS.md](READINESS.md) for the concrete bounded next proposal. No further
work is scheduled or authorized by this handoff. Stop after local delivery.
