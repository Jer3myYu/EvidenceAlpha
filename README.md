# EvidenceAlpha

**Source-grounded industry research, from a brief to a reviewed report.**

EvidenceAlpha is a Python CLI for investors who understand investing but are new
to an industry. It coordinates specialist research, writing and independent
review to explain products, value chains, company differences, growth drivers
and risks. It delivers cited Markdown, sourced charts and Chinese-capable PDFs.

Original evidence accompanies findings through writing and correction. The
system records missing information and review limitations instead of treating a
generated report as proof that every question has been answered.

[Architecture](#architecture) · [Quick start](#quick-start) ·
[Live usage](#live-usage) · [Documentation](docs/README.md) ·
[Results and limitations](docs/EVALUATION.md)

## Architecture

![EvidenceAlpha architecture](docs/diagrams/architecture.png)

A deterministic **orchestrator** controls stage routing, resource admission,
checkpoint recovery and delivery. Four model roles perform the research work:

| Role | Responsibility |
|---|---|
| Research Lead / Writer | Interpret the brief, plan tasks, synthesize findings, produce figures and revise the report |
| Industry Researcher | Explain industry structure, technology, value chains, demand and risks |
| Company Researcher | Investigate products, finances, commercial relationships and competitive position |
| Independent Reviewer | Assess report usefulness and check pivotal claims against original sources |

The **filesystem is the source of truth**: original documents, parsed text,
source versions and locations stay in the source store. Optional **Chroma hybrid
retrieval** combines lexical and semantic candidates, resolves matches to
original spans, and applies local contextual reranking. Researchers can open
surrounding text or continuations. Generated summaries are navigation aids,
not original evidence.

The evidence handoff preserves supporting text, units, periods, source identity
and technical qualifiers within request capacity. Runtime adapters isolate
provider calls; saved stage artifacts make the work inspectable.

Read the [module guide](docs/ARCHITECTURE.md) and
[retrieval guide](docs/RETRIEVAL.md) for implementation details. The diagram is a
conceptual overview, not a concurrency schedule.

## Workflow

![EvidenceAlpha workflow](docs/diagrams/workflow.png)

1. **Configure and admit:** load the brief, prepared corpus and explicit model
   settings; check context capacity and local resources.
2. **Plan and research:** assign specialist tasks, retrieve and read originals,
   record findings and essential gaps, and use a bounded follow-up where needed.
3. **Synthesize:** write a cited report with useful comparisons and sourced figures.
4. **Review:** assess brief coverage, understanding, useful analysis, responsible
   evidence use and clear communication; check material claims against sources.
5. **Correct and deliver:** route missing evidence to focused research and supported
   corrections directly to revision; perform one consolidated revision and focused
   recheck, then export with the actual review outcome and remaining limitations.

The reviewer can return **ready**, **ready with disclosed limitations**, or
**needs revision**. Execution, coverage, review and export are separate statuses.
A retrieval miss does not establish that a document lacks the information.

## Quick start

Requires **Python 3.11 or 3.12**. Run these commands from the repository root:

```bash
git clone https://github.com/Jer3myYu/EvidenceAlpha.git
cd EvidenceAlpha
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m evidencealpha --help
```

Graphviz's `dot` executable is required for relationship diagrams. PDF export
needs compatible fonts; Noto or Source Han fonts are recommended for Chinese.
Reuse an existing environment when working in an established installation.

Try the versioned deterministic example in a **new output directory**:

```bash
.venv/bin/python -m evidencealpha run \
  --fixture tests/fixtures/redesign/quickstart.json \
  --output data/examples/manufacturing

.venv/bin/python -m evidencealpha show-run data/examples/manufacturing
```

Open `data/examples/manufacturing/reports/report.md` and its PDF. The fixture
uses saved example role outputs: **no provider calls or model downloads**. It
checks workflow and export behavior, not autonomous research quality.

## Live usage

Live research requires a prepared source-store corpus, installed local reranker,
a configured provider CLI and verified model capacity. A clone includes neither
model weights, research datasets, authentication nor past reports.

Follow [setup and configuration](docs/SETUP.md), then:

```bash
mkdir -p data/local-configs
cp configs/research.fixed-corpus.example.json data/local-configs/research.json
# Edit the brief, source/model paths and capacity settings before launching.
.venv/bin/python -m evidencealpha fixed-corpus \
  --execution data/local-configs/research.json \
  --output data/runs/my-research
```

**This command makes generative provider calls.** Fixed-corpus means no external
research-source acquisition; it does not mean the generative provider runs locally.
The current fixed-corpus path uses the Codex adapter. Model names in the example
are explicit requests, not a guarantee of availability or effective identity.
There is no implicit model download or paid-provider fallback.

Optional Chroma indexing is described in [Retrieval](docs/RETRIEVAL.md). Targeted
web verification requires both explicit configuration and the `verify-report`
command; see [Setup](docs/SETUP.md#optional-web-verification).

Inspect `command-result.json`, `manifest.json`, stage records and the report paths
recorded by the command. Use `show-run` for a compact summary. Saved-run
continuation requires compatible checkpoints and an active admitted execution;
it does not authorize restarting a closed campaign.

## Results and current limits

The latest documented Nanfei case produced a Chinese report rated **ready with
disclosed limitations** and a checked English translation. Two material review
findings led to corrections, while financial and commercialization coverage
remained partial. The campaign required engineering and operator recovery.

This is **rubric review with targeted source checks**, not exhaustive factual
verification. Local neural search can be slow; model-generated gaps can be wrong;
mandatory evidence may exceed context capacity. The proposed Workflow Studio is
not an implemented UI. There is no claim of broad reliability or uninterrupted
autonomous completion. See [evaluation and limitations](docs/EVALUATION.md).

## Repository layout

```text
EvidenceAlpha/
├── src/evidencealpha/    # CLI, workflow, source tools, retrieval and export
├── tests/               # Regression checks and versioned example fixtures
├── configs/             # Shareable configuration templates
├── scripts/             # Explicit evaluation utilities
├── docs/                # Maintained guides and diagram assets
├── pyproject.toml       # Package metadata and declared dependencies
├── AGENTS.md            # Contributor-agent instructions
└── LICENSE              # Project license
```

Local `data/`, `runtime/`, `worktrees/`, environments and historical archives are
ignored. Test code and intentional fixtures stay versioned. Historical plans,
run ledgers and retired implementation files are retained locally and in prior
commits; they are not part of the current published tree.

See [Development](docs/DEVELOPMENT.md) for focused checks and contribution
boundaries. Documentation works directly on GitHub or in a local editor; no
separate documentation server is required.
