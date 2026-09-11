# Runtime validation after Stage 2

Outer-session and child runtime permissions were separately verified after
the user resumed the campaign. Company, synthesis, production review and
author revision rehearsals ran; both full attempts ended draft_review_incomplete after revision deadlines.
The attempt caps are exhausted. Full integration results and usage are in
COMPLETION.md and STAGE2_RESULTS.json. Earlier access failures are preserved.

## Measured tool-loop decision

Retain the existing Codex CLI portable JSON loop for this bounded campaign.
This is an explicit SDK-first architecture exception, not SDK continuation.
The real industry rehearsal used eight fresh model calls, 109.315 summed model
seconds, and 23 evidence-tool calls totaling 0.245 seconds. Prompt bytes grew
from 3,565 to 124,421; observable input tokens across that stage were 170,678.
The output was useful within its single-issuer scope and sampled statements
matched original passages. Startup versus inference latency cannot be separated
from these measurements. Eight turns reached the configured round allowance;
large source payloads and repeated prompt transmission remain limitations.

The [official Codex SDK documentation](https://learn.chatgpt.com/docs/codex-sdk)
now describes a stable Python SDK controlling app-server and persistent threads.
The installed application does not have that SDK. Its absence alone is not an
architectural justification. Here the measured small stage completed within its
six-minute allowance, so replacing the transport during the capped campaign
would add unvalidated runtime/settings/session behavior without evidence that
it resolves a product-blocking timing defect. No SDK or account changes were
made. The first full run later exhausted company tool rounds and timed out during
revision. Source scoping, payload control and a final response round address
observed tool-contract defects; persistent SDK sessions remain a future
measured optimization. Reconsider the transport against the saved multi-tool
workload rather than introducing it without validation; do not claim this loop is
native SDK-first or that Claude has been validated by GPT output.

## Codex controls and access

Codex CLI 0.154.0 reports ChatGPT login. Successful rehearsals requested
GPT-5.5 medium; independent reviewer and full-report calls requested GPT-5.6 Sol
medium and received model responses. Per-call CLI events did not report effective
model/effort; those fields remain unknown. A non-model app-server thread/start
returned the requested model and medium effort, readOnly sandbox with network
access false, and approvalPolicy never. This verifies runtime configuration,
not independent inference routing or entitlement.

Outer write probes succeeded for the checkout, Git metadata, ~/.codex and
~/.codex/tmp. The separate non-model app-server check initialized and created an
ephemeral thread without a model turn. Evidence:
`data/redesign/stage2-permission-check/result.json`. Local commits now succeed.
Earlier readonly failures remain charged and preserved; no model attempts were
repeated merely to diagnose permissions. Intentional child evidence isolation
was retained: read-only, ephemeral, forced ChatGPT login, ignore user/project
config, disabled shell/web/apps/multi-agent/JS tools. Observed traces have no
native evidence acquisition, but fixed-corpus restrictions remain **best effort**.

The initial provider override rejection was repaired by removing unsupported
built-in retry overrides, without custom providers or API fallback. Internal
CLI retries cannot be claimed disabled; hard invocation deadlines bound observed
time. The current strict output schema was added after a production reviewer
returned malformed tool-call JSON; its next authorized isolated attempt worked.
The last bounded tool round now requests final notes and prohibits new tool calls
in the Codex schema. Source-specific searches filter before top-k; the observed
`source_id:<hash>` syntax is supported explicitly. Exact chunk IDs are required.
These are shared runtime fixes, with no issuer-specific conditions.

## Claude boundary

Installed Claude Code 2.1.268 / Agent SDK 0.2.151 remain live-untested, with no
supported configured model discovered. The runner now serializes the installed
SDK's `RateLimitEvent` / `RateLimitInfo` dataclasses. A `rejected` named
subscription window is propagated across the subprocess wire and recognized as
exhaustion; warnings and unspecified/generic rate limits are not. The runner
leaves the SDK stream immediately; the parent kills/reaps the process group.
Result usage and partial raw events are retained where emitted. Tests cover
actual SDK dataclass serialization into the adapter, plus the existing bounded
portable-context fallback. This is offline boundary evidence, not a live quota
probe or a claim about hidden SDK retries. No quota was intentionally exhausted.

## Sources, caching and deadlines

Tavily remains the only search provider. `stage2-config.json` explicitly selects
the existing `.env` path; only TAVILY_API_KEY is consumed, without exporting
other settings or logging credentials. python-dotenv is now an explicit project
dependency (already installed and pinned in constraints). Search/fetch counters
include the sandbox DNS failure. Five newly captured originals and the historical
issuer PDF are preserved across photomask and service corpora. Full cases can
copy a source corpus with original URL/date metadata, without reusing stage
outputs. Publication dates not established from originals remain null.

Queued and active research share one monotonic deadline, shortened to preserve
synthesis/review/revision/recheck and export time. It reaches subprocess timeout
controls as an absolute deadline, so launch work cannot reset it. External tools
run in separate cancellable process groups under the same deadline, bounding
socket waits and parsing. The default export reserve is 120 seconds. Fake-clock,
two-slow-worker, downstream-reserve and slow-acquisition tests cover these paths.

Validated source bytes/text are cached until file identity, size, nanosecond
mtime or ctime changes; mutations are revalidated and rejected. Search builds
all passages from each source once. Optional local-only embeddings reuse the
model and corpus vectors, keyed by model/source/parser/chunker/index versions;
only query vectors are recomputed. Offline encoder tests establish cache
behavior; no actual embedding model was loaded. Models at a configured local
path are treated as immutable during a SourceStore lifetime.

Real Microsoft HTML exposed universal-newline translation on reopening CRLF
canonical text. Reading UTF-8 bytes preserves exact hashes and Unicode spans;
original files and indexes needed no rewrite. The larger photomask query improved
from 3.888/3.656 seconds cold/warm to 0.628/0.445 seconds locally. These are small
local measurements, not general benchmarks. Broad lexical queries can rank
irrelevant financial headings; targeted terms and reopening originals remain
necessary. Digital extraction is not OCR; multilevel table/heading associations
are heuristic. Contextualization remains disabled.

## Visual and product limits

Reviewer inputs explicitly say: text, figure specifications and hashes only;
no native pixels. Do not claim layout/readability review by that model. The
independent review/recheck prompts also state this limit. The coding session
inspected exported synthesis/revision pages and figures directly. Long graphs
are laid out vertically to retain readable labels. Reviewer findings are not
pixel review, even when the report is marked reviewed. The first full draft
remains incomplete after revision timed out; its reviewer also missed a Longtu
90nm/130nm reading error later found against originals by the operator. Final
product assessment, report paths and any remaining limitations are in COMPLETION.md.
Real Microsoft source extraction and CRLF span checks passed; a live service
report remains unvalidated because isolated slots were consumed by the core
photomask rehearsals. Main coding-session usage and subscription balance are
not observable. Contextualization and real local embeddings remain disabled.

## Final offline repairs and reproducibility

Source catalogs now include the first original passage with its source ID and
spans. It is an identifying aid, not an asserted issuer label. The common prompt
requires verification against originals. Tests cover the actual stage-input
boundary. The second live process retained the older inventory implementation,
while synthesis/review/revision read the newer instruction from disk; those
exact prompts are saved per stage. The combined identity change has no live
product validation. Do not claim a homogeneous fixed-corpus comparison.

Both full revisions reached their 120-second stage deadline. The second reviewer
also made a false issuer objection, so the presence of review findings is not
acceptance. All 10 isolated and 2 full slots are consumed. Further transport,
reviewer or service model work cannot use this campaign's remaining time as
extra attempts.

Visual inspection found a figure shrinking into the page remainder and long
source hashes collapsing neighboring table columns. The offline exporter now
assigns bounded figure dimensions and a new-page start, balanced table cells,
and wrap opportunities inside long alphanumeric table tokens. Canonical Markdown
and link targets remain unchanged by the exporter; PDF text read-back ignores
only whitespace and inserted zero-width wrap characters. The assembler places
captions beside referenced figures. A synthetic tall-figure/table regression
checks real PDF geometry and text preservation. A labeled real-draft derivative
is retained in data/redesign/stage2-layout-reassembled/. It is layout validation,
not factual correction. Original full-run exports were preserved. Pagination may
still separate a table header from following rows.
