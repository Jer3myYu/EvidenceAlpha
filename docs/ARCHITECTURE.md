# Architecture and module guide

EvidenceAlpha has one active CLI research workflow. Infrastructure preserves
source identity and execution state; language models perform research, synthesis
and user-focused review. This guide describes the code inspected at `560662e`.

![Architecture](diagrams/architecture.png)

## Modules

Paths below are relative to `src/evidencealpha/`.

| Module | Responsibility |
| --- | --- |
| `__main__.py`, `cli.py` | Command entry points, argument parsing and dispatch. |
| `execution.py` | Fixed-corpus/web-enabled admission, frozen settings, checkpoint/replay compatibility and command result. |
| `workflow.py` | Stage runner, planning/research routing, synthesis, review-driven correction, recheck and delivery state. |
| `config.py` | Typed settings, model selections, retrieval parameters, capacity and execution controls. |
| `budget.py` | Persistent admission and usage settlement; deadline/call accounting and crash reservations. |
| `providers.py`, `claude_runner.py` | Codex CLI and Claude SDK boundaries, provider events, isolated calls and cancellation. Fixed-corpus currently admits the Codex profile without fallback. |
| `protocol.py`, `prompts/` | Structured tool/output contracts and role-specific instructions. |
| `documents.py` | Versioned source store, parsing and original source/chunk identity. |
| `retrieval.py` | Lexical candidate generation and contextual reranking integration. Candidate depth is a retrieval parameter, not a campaign quota. |
| `reranking.py` | Explicit local neural scorer subprocess and resource supervision. Uncached search initializes its scorer; do not assume a resident warm model. |
| `reading.py` | Structural reading windows, chunk bindings and bounded surrounding/continuation context. |
| `preparation.py` | Cooperative cancellation/deadline checks during evidence preparation. |
| `tools.py`, `tool_runner.py` | Shared source search/open tools and bounded acquisition process boundary; web verification is explicit. |
| `stage_context.py` | Durable research evidence and compact context selection, separate from audit logs. |
| `handoff.py` | Original-preserving cross-stage assembly, scope bookkeeping and explicit evidence omissions. |
| `review.py` | Five-criterion assessment, material issue routing and unresolved finding handling; no sentence-by-sentence certification gate. |
| `presentation.py` | Reusable Markdown presentation transformations, including keyed table notes. |
| `render.py` | Source-linked figures, report export and text-preservation checks. |
| `layout.py` | PDF typography, table layout and pagination through PyMuPDF. |
| `artifacts.py` | Atomic files, fingerprints, portable artifacts and trace replay. |
| `__init__.py` | Package boundary. |

## Evidence path

1. Parsing stores original source versions and locators.
2. Candidate search finds possible anchors; neural ranking orders contextual
   candidates. These are different quality questions from context completeness.
3. Researchers open original chunks, nearby passages or continuations when needed.
4. Stage context retains originals and gaps. Handoff compacts metadata and bounds
   payloads without replacing original evidence with generated summaries.
5. Writer and reviewer receive supporting originals. The reviewer can independently
   search the authorized corpus; opted-in web checks must capture source text.
6. Newly found support follows correction into revision and recheck. Unresolved
   material issues survive even when export succeeds.

A retrieval miss is not evidence that the full document omits a fact. Likewise,
a model's scope labels are provisional bookkeeping, not factual certification.
Payload admission cannot make an incomplete evidence bundle complete.

## Routing and completion

![Workflow](diagrams/workflow.png)

Research can trigger a bounded essential-gap follow-up before synthesis. After
review, available factual evidence and editorial changes go directly to revision;
unresolved essential evidence or conflicts can route to a focused researcher.
The existing correction cycle ends with consolidated revision and focused recheck,
not an indefinite loop until approval. Actual execution limits may leave a
partial deliverable.

The five review criteria serve an investor unfamiliar with the industry. Decisions
are ready, ready with disclosed limitations or needs revision. Examined scope and
unresolved issues matter independently of whether the findings list is empty.
Export status describes files; review readiness describes the report.

## Boundaries and limitations

- Runtime settings and prompts are configurable; example company names belong in
  the brief/configuration, not generic retrieval or reviewer logic.
- Fixed-corpus disables source acquisition. Its provider transport still needs
  access to the configured generative service.
- Offline fixtures and saved-output replays prove contracts and routing, not
  autonomous judgment, retrieval quality or model feasibility.
- Historical results span code versions. Read their recorded version and scope
  before treating them as evidence for current behavior.
- The current interface is a CLI. The documentation index is navigation, not a
  web application or deployment requirement.
