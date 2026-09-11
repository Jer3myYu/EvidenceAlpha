# Ready-to-paste Stage 2 kickoff

Paste the following into a **fresh session**. This file's creation does not authorize execution in Stage 1. Select GPT-5.6 Sol medium for the coding session in the client where available; application configuration cannot change the host model.

```text
Continue EvidenceAlpha in STAGE 2 in this fresh session. Proceed autonomously within the redesign package's limits; finish early when sufficiently validated.

Checkout: /home/cobot/cobot_storage/webproject/EvidenceAlpha
Expected branch: research-quality-upgrade
Validated implementation revision: 02069a6ac0dc7de7a8bdbab31bb93c6018afa150
A later documentation-only commit contains the completed handoff; verify current HEAD and the intervening diff. Preserve user work, never reset it.
Package: /home/cobot/cobot_storage/webproject/EvidenceAlpha/docs/redesign-package/
Handoff: /home/cobot/cobot_storage/webproject/EvidenceAlpha/docs/redesign/HANDOFF.md
Active map: /home/cobot/cobot_storage/webproject/EvidenceAlpha/docs/redesign/ACTIVE_CODE_MAP.md
Budget: /home/cobot/cobot_storage/webproject/EvidenceAlpha/docs/redesign/RUN_BUDGET.json

Read HANDOFF and ACTIVE_CODE_MAP first, then package 07-LOW-QUOTA-OVERRIDE.md and 04-STAGE-2-OVERNIGHT.md. Apply 08-CODE-QUALITY.md to every fix. Consult 01/03 only for relevant contracts. The archived old Starting Prompt/C-S campaign does not govern this work; do not load legacy code or old audit logs by default.

First commands, from the checkout:
git status --short
git branch --show-current
git rev-parse HEAD
.venv/bin/python -m evidencealpha --help
.venv/bin/pytest
.venv/bin/black --check src/evidencealpha tests/redesign
.venv/bin/pylint --jobs=1 src/evidencealpha tests/redesign
.venv/bin/python -m evidencealpha show-run data/redesign/stage1-final-service
.venv/bin/python -m evidencealpha stage2 --help

Stage 1 passed 21 focused tests, CLI/import/lint/format checks and two synthetic Markdown/PDF exports with rendered-page/figure inspection. Active commands also include resume, replay-stage and render; exact tested arguments are in TEST_PLAN.md. Reports are data/redesign/stage1-final-manufacturing/reports/report.{md,pdf} and data/redesign/stage1-final-service/reports/report.{md,pdf}. These are fixture reports, not accepted real research. Fixture packs are tests/fixtures/redesign/{manufacturing,service}.json. Preserve their existing output directories.

The saved real-source corpus is data/redesign/stage1-real-corpus/ (one existing captured Chinese issuer PDF; limited coverage). TEST_PLAN.md identifies original bytes and historical URL/date metadata. Saved inputs and one-case driver configurations are docs/redesign/inputs/ and docs/redesign/cases/. For example, after verifying controls, the first rehearsal command is:
.venv/bin/python -m evidencealpha stage2 --execute --case docs/redesign/cases/plan.json
That charged command was NOT executed in Stage 1. It starts/resumes the persistent Stage 2 clock and admits one case. Other prepared cases are industry.json, company.json and synthesis.json. Inspect stage usefulness/source fidelity before moving on; prepare the independent review case from the exact resulting draft/figures. Contextualization is disabled by default. Use revision/recheck only when needed. The full-report case deliberately lacks readiness evidence and is rejected until actual stage readiness is recorded. Live resume forks through an explicit resume_from field and uses another full attempt; prefer isolated reruns for a localized failure.

Use low_claude_quota: production roles/reviewer are Codex gpt-5.6-sol medium; rehearsals use gpt-5.5 medium first, except the production reviewer/recheck. Escalate only a concrete failed case after inspecting inputs/tools. No GPT-6 or API-billed fallback. Host model selection is a client setting, not something to pretend to change through application config.

Known gaps: Codex CLI 0.154.0 reports ChatGPT login and its bundled catalog includes both requested models/medium, but actual calls/effective settings/native tool restrictions are untested. Verify those before claiming a fixed-corpus comparison; otherwise label best-effort tool restriction. Claude Code 2.1.268 / SDK 0.2.151 are installed but no supported model is configured or live-tested. Tavily's key is not exported; use only the user's existing supported configuration without printing .env or credentials. No paid fallback or account changes. Reviewer inputs currently include figure data and hashes rather than native pixels: inspect rendered visuals yourself. Optional embeddings and real service-domain product validation are pending. RUNTIME_NOTES.md explains these limits. Repair concrete prerequisites without rebuilding the project from historical code.

At handoff, Stage 2 campaign_started is null and all charged counters are zero. Stage 1 smoke usage is separately zero (unused optional allowance; not additive to Stage 2). Preserve and reconcile the ledger before admission. Remaining ceilings: 8 hours; 10 isolated attempts, each <=6 minutes; 2 sequential full attempts, each <=30 minutes; 120 summed invocation minutes; 100000 observable output/reasoning tokens; 40 searches; 60 fetch attempts; 2 concurrent researchers. Optional 2 peer checks and 3 Claude probes (<=2 minutes each, <=6 summed minutes) are subsets, not extra allowances. Missing token values remain unknown. Never reset counters after failure, resume, provider switch or a new debugging session. Failed/interrupted work and conservative unsettled reservations count.

Follow 04: offline checks, compact saved-input rehearsals, production reviewer check, then one genuine all-GPT photomask report after readiness. Use the second full attempt only for a concrete integration need. Add a compact real service-source case where feasible within the same limits. Preserve useful reports and truthful statuses. Use one review, at most one revision and one focused recheck; no repeat-until-pass or per-claim certification graph.

You may fix code and run the authorized local/source/model work without asking before each ordinary action, subject to platform restrictions. Debug the smallest failing stage and reuse valid upstream artifacts. If providers are blocked or caps reached, stop charged work and finish useful offline artifacts. Finish docs/redesign/COMPLETION.md, NEXT_SESSION.md and the results/usage ledger with report/source/figure paths, measured usage, unknowns, final HEAD and dirty state. Commit relevant local work, stop all children and return the outcome. No push, merge, deployment, publication, credential changes or purchased quota.
```
