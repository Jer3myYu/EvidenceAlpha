# Setup and usage

## Prerequisites

- Python 3.11 or 3.12 and an isolated virtual environment.
- Graphviz `dot` for relationship diagrams; compatible installed fonts for PDF
  output. Noto/Source Han fonts are recommended for Chinese text.
- For live research: an installed, authenticated Codex CLI accepted by the
  application, an available configured model, and explicit local reranker files.
- For hybrid retrieval: an installed encoder snapshot and the `vector-index`
  dependency extra. See [Retrieval](RETRIEVAL.md).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m evidencealpha --help
```

Live local reranking also requires:

```bash
.venv/bin/pip install -e '.[retrieval]'
```

Dependencies are declared in [pyproject.toml](../pyproject.toml). Neural runtime
compatibility depends on the installed snapshots and packages; the project does
not install or download model weights on launch. Configure provider authentication
through its normal local flow. Never put credentials in an execution JSON,
source document, report or commit.

## Try the deterministic example

```bash
.venv/bin/python -m evidencealpha run \
  --fixture tests/fixtures/redesign/quickstart.json \
  --output data/examples/manufacturing
.venv/bin/python -m evidencealpha show-run data/examples/manufacturing
```

Use a new directory. `run --fixture` supplies example model outputs and performs
no generative calls. Open the report paths in the result. It is a workflow/export
example, not an evaluation of autonomous reasoning.

## Prepare a source corpus

`fixed-corpus` expects an EvidenceAlpha SourceStore, not a directory of arbitrary
PDFs. Capture local PDF, HTML or text documents through the source API:

```python
import pathlib

from evidencealpha import documents

store = documents.SourceStore(pathlib.Path("data/corpora/example"))
source = store.ingest(pathlib.Path("data/incoming/annual-report.pdf"))
print(source["id"])
```

Execute this snippet using the project virtual environment after placing your
own document at that path. `ingest` reads local bytes; it does not fetch the web.
Supply optional `url` and `document_date` arguments only when known, to preserve
provenance. Repeat for each authorized document. Verify extracted text and table
context before relying on them; parsing is not factual certification.

The store preserves originals, canonical text, source metadata and locators.
Generated summaries are optional navigation context, not original evidence or
necessarily whole-document summaries. OCR and complex layout recovery should
not be assumed from successful file ingestion.

## Configure live execution

```bash
mkdir -p data/local-configs
cp configs/research.fixed-corpus.example.json data/local-configs/research.json
```

Edit the copy before launching:

| Field | Required choice |
|---|---|
| `brief.text`, `brief.scope` | Research question, audience, depth, source boundaries and information cutoff |
| `required_scope`, `required_research_roles` | Essential questions and role assignments; preserve every requirement in the brief |
| `corpus` | Absolute path to your prepared source store |
| `settings.runtime_model`, `settings.reviewer_model` | Model identifiers actually supported by the configured provider |
| `settings.writer_context_tokens` | Verified effective writer context capacity; the template deliberately leaves this null |
| `settings.writer_output_tokens`, `writer_transport_tokens` | Output and provider-framing headroom within that capacity |
| `settings.reranker_path`, `reranker_revision` | Installed local model directory and full matching revision |
| `settings.command_seconds`, `command_calls` | Overall elapsed deadline and optional total call ceiling |
| `settings.information_cutoff` | Actual cutoff, consistent with the brief |

The example model requests are `gpt-5.6-sol` and `gpt-6-astra`; they are not a
promise of availability. Reviewer capacity is resolved against the installed
provider catalog. Do not transfer writer/reviewer capacity assumptions between
models. Requested and provider-reported identity are recorded separately; some
providers do not report effective identity or a hard output-token limit.

Use absolute source/model/index paths for portability. In execution files,
relative corpus and supported model/index paths resolve from the execution
JSON's directory. `search_env_file`, if used, resolves from the working directory.
Keep machine-specific configuration under ignored `data/local-configs/`.

## Run and inspect

**The following command makes provider calls.** Source search remains within the
prepared corpus; generative processing uses the configured provider service.

```bash
.venv/bin/python -m evidencealpha fixed-corpus \
  --execution data/local-configs/research.json \
  --output data/runs/my-research
```

Default output records include:

| Artifact | Purpose |
|---|---|
| `command-result.json` | Execution/export outcome and failure information |
| `manifest.json` | Stage paths, coverage, review/readiness and selected report |
| `execution-freeze.json` | Code, settings, environment and provider-capacity provenance |
| `execution-ledger.json` | Invocation admission, settlement and measured/unknown usage |
| `stages/` | Actual inputs, outputs, tool events and stage evidence |
| `reports/` | Markdown, figures, source mapping and PDF artifacts |

Read report paths from the manifest rather than choosing the newest-looking PDF.
Exit code zero establishes execution/export completion, not a full quality pass.
Inspect `coverage_status`, `review_status`, `readiness` and unresolved issues.
`show-run` reads the default manifest and gives a compact summary; custom manifest
filenames must be inspected directly.

`--continue-existing` validates compatibility before reusing completed stages.
It is not a clock reset, a way to reopen closed ledgers, or interchangeable with
fixture `resume` / `replay-stage`. Preserve failed attempts and use explicit
recovery settings where needed. Do not restart successful research just to make
the execution history look uninterrupted.

## Optional web verification

Set `settings.web_verification` to `true` in an explicitly authorized execution
configuration and use `verify-report` instead of `fixed-corpus`:

```bash
.venv/bin/python -m evidencealpha verify-report \
  --execution data/local-configs/web-verification.json \
  --output data/runs/web-verification
```

This is the web-enabled workflow entry point, not a promise of a standalone
review of any arbitrary PDF. Use compatible saved-stage configuration when
continuing an existing report. Configure the required search service locally;
[.env.example](../.env.example) lists the optional key name. The setting alone
does not make `fixed-corpus` acquire external sources.

Web evidence must be opened/captured with supporting text and provenance;
snippets are not evidence. Later disclosures must retain their dates and not
silently change the brief's cutoff. A changed corpus requires a new compatible
vector index; do not claim a frozen index covers newly acquired documents.

## Controls and troubleshooting

The hard-limit inventory is `EXECUTION_HARD_LIMITS` in
[config.py](../src/evidencealpha/config.py). Live execution retains the overall
deadline, optional call ceiling, one in-flight provider invocation, provider
capacity, watchdogs, cancellation and hardware guards. Stage allocations and
cumulative time/token targets are scheduling guidance/telemetry where redundant.

| Symptom | Check |
|---|---|
| Model unavailable | Installed provider catalog and explicit model request; there is no silent fallback |
| Context admission fails | Actual model capacity, headroom, serialized request and mandatory originals; do not drop support to force admission |
| Neural packages missing | Configured Python environment; preserve its virtualenv path rather than resolving it to system Python |
| Source/index mismatch | Corpus version and frozen index; create a new explicit index snapshot |
| Slow search | Preparation, initialization and scoring separately; vector-query time is not total retrieval latency |
| Missing or unreadable PDF | Export error, Graphviz/fonts, text-preservation result and rendered pages |

The selector's conservative UTF-8 byte estimate is not a confirmed provider byte
ceiling. Output reserves are not proof of enforceable in-flight output caps.
Record unknown usage rather than inventing cost measurements.

The older `stage2` CLI subcommand is retained for explicit diagnostic cases with
separately supplied ledgers/case files. It is not an installation step or a
required phase before `fixed-corpus`; historical campaign files are not bundled.
