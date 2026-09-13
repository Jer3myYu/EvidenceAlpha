# EvidenceAlpha contributor instructions

## Start here

Read README.md, docs/ARCHITECTURE.md and the relevant maintained guide in docs/.
The current product is the CLI and normal research/review workflow. Historical
redesign packages, campaign handoffs and retired code are local reference only;
do not load old task lists or launch historical campaigns by default.

## Implementation

- Keep deterministic orchestration separate from provider reasoning. Extend the
  existing workflow, tools, StageContext and evidence contracts.
- Preserve exact originals, source versions, locators, units and qualifiers.
  Generated notes and provisional coverage labels are not source evidence.
- Fixed-corpus runs never acquire external sources implicitly. Model changes,
  web-enabled runs and paid fallback require explicit task authorization.
- Keep execution, coverage, review readiness and export outcomes distinct.
- Do not hardcode case-specific answers, source IDs or machine paths in runtime.

## Code quality

Use four-space indentation, 80-column Black, module/absolute imports, typed
public APIs and Google-style docstrings. Use .venv/bin/python and .venv/bin/pip;
declare dependencies in pyproject.toml. Run focused pytest and Black/pylint checks
for affected code. Fixtures/replays do not establish live research quality.
Do not install system dependencies or log secrets.

## Preservation and scope

Preserve user edits, original sources, databases, historical outputs and closed
ledgers. Do not reset usage or restart successful research to obtain a clean run.
Keep data/, runtime/, worktrees/, .local/, environments and historical archives
out of commits; retain test code and intentional fixtures. .env and authentication
caches are never report artifacts. Git does not back up ignored local files.

Local commits are permitted when implementing an authorized task. Push, merge,
deployment, provider calls and destructive cleanup require authorization from the
current task or session. Do not change Git identity or account configuration.
