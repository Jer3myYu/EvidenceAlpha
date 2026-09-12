# Preparation correction and continuation

The closed campaign remains unchanged. New work and its additive continuation
ledger are in `data/redesign/coherent-retrieval/preparation-correction-20260912/`.
The later user authorization allows measured resource corrections and conditional
report production within three hours/16 generative calls/3,600 generative seconds/
40,000 observable output-reasoning tokens, one neural worker and 8 GiB sampled RSS.

One S01 preparation profile ran without inference under a 120-second supervisor.
A statement-boundary observer measured 17.8059 seconds: candidates4.6677,
metadata snapshots/copy10.9291, structural sorting0.2718, units0.6630,
chunk binding0.6701, serialization0.0300. The original global tracer's61.51-second
result remains a failed result; it is not comparable instrumentation. Observer
bookkeeping is recorded separately; timestamp/dispatch overhead cannot be isolated
exactly from a single execution.

SourceStore now reuses version-validated immutable structural indexes. Window
construction no longer deep-copies full source metadata for every candidate;
block-to-unit/chunk maps avoid repeated source-wide binding scans. Candidate work
iterates one validated snapshot without repeated per-chunk lookups. Fresh output
bindings protect the cached originals from caller mutation. Source revalidation
invalidates the index; interrupted builds are never published.

Preparation registers cancellation before candidate work, checks deadlines and
cancellation between original passages, structural units, window selections and
bindings, and checks around cache-key serialization before scorer admission.
These are cooperative boundaries, not OS hard preemption of an individual file
read, JSON parse, sort or encoder operation. The outer supervisor remains needed.
No ranking, candidate depth, unit selection, context/annotation or quality-policy
change was made.

One post-change S01 preparation replay stopped at an injected scorer boundary:
1.0228 seconds to admission,1.1736 seconds including trace delivery, leaving28.9772
seconds of the original30-second limit. All64 candidate identities/scores/spans
and all64 complete reading contexts matched exactly. This was not neural inference.
Sixteen focused cache/cancellation/navigation checks passed; Black/pylint clean.
Prior broad/deterministic suites were reused, not rerun.

Actual neural continuation subsequently loaded the scorer in2.8792 seconds and
completed31 forwards averaging0.7846 seconds before the30-second search deadline.
That failure is preserved. The new authorization permits engineering settings:
150-second searches,1500-second stage groups and1800 cumulative neural seconds
were recorded before the targeted continuation, retaining2048 total charged pairs
including the failed128-pair reservation. CPU/model/ranking/quality are unchanged.
A statement-boundary worker observer replaces global tracing; no resident warm
model or hidden warmup is used. See the continuation ledger and separate neural-1
and neural-2 directories for actual outcomes; these settings are not themselves
a readiness or quality pass.

## Context and duplicate-window follow-up

Real evaluation showed the legacy PDF parser's individual visual lines were
being treated as complete paragraphs. Rendered Luw page2 confirms the financial
paragraph spans c30–c39; a window at c36 omitted its revenue/causal context.
Reading indexes now group adjacent same-page PDF lines by indentation, spacing,
font height and column geometry. They retain separate exact original spans and
chunk bindings; ambiguous boundaries remain separate. The8000-character ceiling
is unchanged; oversized indivisible groups remain explicit gaps. This changes
reading context to address observed omissions, not ranking or candidate depth.

Recorded scoring also repeated identical texts (S01:64windows,42unique texts).
The local worker now caches identical window logits per query. Scored views and
candidate order remain unchanged; only actual forwards are charged. A fake-module
check confirms two identical views invoke one forward and retain both scores.
Seven paragraph/cache/deadline checks and the separate window-cache check passed.

C02's long table windows averaged2.90seconds per forward and hit150seconds after49
forwards. Before targeted continuation, search allowance became300seconds within
1800 cumulative neural seconds/2048 charged pairs, including previous failures.
Completed cases were not blindly rerun: neural-3 contains only affected quality
failures and remaining controls. Broad-query candidate misses stay recorded as
failures; no frozen criterion is relaxed. Actual subsequent results live in the
additive continuation ledger and separate attempt directories.
