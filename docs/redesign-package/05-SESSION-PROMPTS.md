# Kickoff prompts — two separate sessions

Place this package at `docs/redesign-package/` in the actual EvidenceAlpha checkout. If you choose a different location, adjust the path in the initial prompt. Choose GPT-5.6 Sol, medium effort, for the coding session where available. Runtime and rehearsal models are separate settings defined in 07.

## Initial kickoff: Stage 1 only

```text
Implement the EvidenceAlpha redesign from docs/redesign-package/.

This session is STAGE 1 ONLY: implementation, cleanup, focused offline checks and handoff. Read 00-START-HERE.md, then the model/budget policy in 07, design in 01, Stage 1 instructions in 02, replay contract in 03 and code-quality requirements in 08. Consult 04 to implement the future test driver; do not execute its campaign.

Use the actual checkout and its applicable instructions. Preserve existing edits, source documents and historical runs; record a recoverable base commit. Build one clean active workflow, small interchangeable Claude/Codex adapters, shared RAG with original-source locations, replayable stage outputs and sourced report visuals. Remove superseded active code, dependencies and tasks without report-specific hardcoding.

Follow 07 exactly: low_claude_quota is the default application profile; GPT-5.5 is for economical rehearsals and GPT-5.6 Sol for the production reviewer/runtime. Stage 1 permits only its tiny Codex smoke; no Claude calls, full report trials or rehearsal campaign. No GPT-6 or paid API fallback.

Work autonomously on local implementation and meaningful checks. Finish all handoff artifacts required by 02, especially HANDOFF.md and a ready-to-paste STAGE2-KICKOFF.md populated with actual paths, branch/revision, commands, remaining budgets and next steps. Distinguish fixture validation from real model validation.

Commit only relevant work locally when permitted, report final HEAD/working-tree state, and leave no background jobs. Then STOP and return the handoff and Stage 2 kickoff. Do not launch, schedule or continue Stage 2 in this session. I will switch to a fresh session myself. No push, merge, deployment or credential changes.
```

## Stage 2 prompt template — Stage 1 must populate it

Write the completed version to `docs/redesign/STAGE2-KICKOFF.md`. Replace the placeholders using actual checkout state and tested commands. Include a concise first-action command list, fixture locations and known integration gaps. Do not paste whole logs or legacy source into it. A documentation-only commit may follow the validated code revision; record both accurately.

```text
Continue EvidenceAlpha in STAGE 2 in this fresh session. I am leaving it unattended; proceed autonomously within the package's limits.

Checkout: <actual absolute checkout path>
Expected branch: <actual branch>
Validated code revision: <actual hash>
Package: <actual package path>
Handoff: <actual HANDOFF.md path>
Active map: <actual ACTIVE_CODE_MAP.md path>
Budget ledger: <actual RUN_BUDGET.json path and consumed counters>
First commands: <actual tested inspection/offline validation commands>

Read the handoff and active map first, then package 07 and 04; apply 08 to every fix. Verify HEAD and working-tree state before mutation. If the checkout differs, inspect the relevant diff and adapt without resetting user work. Do not load old audit logs or retired code unless a concrete dependency requires it.

Run the bounded Stage 2 plan: offline checks, saved-input GPT-5.5 rehearsals, production GPT-5.6 reviewer test, then one all-GPT live report after stage readiness. Use another full attempt only for a concrete integration need. All numerical ceilings, retries, optional Claude probes, peer checks and provider fallback follow 07. Resume counters rather than resetting them. No old C/S campaign allowances.

Debug at the smallest stage, reuse valid upstream artifacts, and preserve inputs, sources, model outputs, figures and failed-attempt usage. Escalate only a concrete failed 5.5 case to 5.6 after checking inputs/tools. No GPT-6, account changes or API-billed fallback. A blocked Claude integration does not block authorized GPT work; report their validation separately.

Prioritize a useful sourced report with company comparison, appropriate tables/charts and readable Markdown/PDF. Use one review, at most one revision and one focused recheck. Accept residual minor errors with limitations; do not recreate repeat-until-pass loops. Do not call a fixture report or unreviewed draft a validated product.

You may fix code and run the authorized local/source/model work without asking before each run, subject to actual platform restrictions. Stop early when sufficiently validated, or at a limit; continue offline work if useful when providers are blocked. Finish COMPLETION.md, NEXT_SESSION.md and the results/usage ledger with report paths, actual checks, final HEAD and remaining limitations. Commit relevant local changes, stop children and return a concise summary. No push, merge or deploy.
```

Stage 1 must return the generated kickoff file to the user and stop. Producing that file does not authorize executing it in the same session.
