# Stage 1 — implement, clean up, hand off

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

Apply `08-CODE-QUALITY.md` throughout implementation and cleanup; include its evidence in the handoff.

## Boundary

Implement the entire small product path and remove superseded active code/tasks. Include basic tests and smoke checks needed to establish runnable code. Do not perform the overnight model evaluation campaign. Stop at the explicit fresh-session boundary, even if time remains.

## A. Establish the actual checkout

Record HEAD, branch, working-tree state and relevant local instructions. Preserve existing edits; never reset or overwrite them. Create an isolated local redesign branch/worktree if necessary. Record the base commit so removed tracked code is recoverable. The user's current checkout is authoritative; this package's older inspection is not.

Inspect current entrypoints, dependency definitions, source capture, RAG and rendering only as needed. Write `docs/redesign/CLEANUP_MAP.md` with keep/replace/remove actions and callers. Historical task plans are context, not an active backlog. Do not read every former audit before coding.

## B. Build a working vertical slice first

Implement a small canonical pipeline with provider interfaces, source storage, stage artifacts, lead/research roles, independent GPT reviewer, optional revision/recheck and report export. First run it using deterministic fixtures so report content and figure paths survive all the way to delivery. Fixtures prove plumbing, not research intelligence.

Next implement the real SDK adapters and shared retrieval, with explicit model/settings and tool configuration. Wire observable tool events and outputs to stage recording. Give each worker a distinct output path and merge source registration deterministically to avoid concurrent writes clobbering records. Keep the controller simple.

Implement document structure/locations and selective contextualization, sourced tables/figures, a readable Markdown/PDF renderer, and independent stage replay commands. Reuse existing working functions when appropriate; no obligation to rewrite sound utilities. Do not re-import old approval/remediation graphs.

Proposed package: `src/evidencealpha/` with small `workflow`, `providers`, `documents`, `retrieval`, `artifacts`, `render` modules and role prompts. Equivalent compact organization is fine. Avoid one module for every noun and avoid giant all-purpose modules.

## C. Clean the active project, not user evidence

Remove obsolete runtime entrypoints, imports, dependencies and tests whose only purpose is the retired architecture. Remove CrewAI from the new active dependency graph if no retained function needs it. Keep useful source, math, persistence and renderer regression cases that express real product behavior; adapt them to the new interface.

Do not carry two complete production workflows, a default-old/candidate-new selector and the former C/S campaign into the redesign. Preserve old tracked implementation through Git history and an explicit base commit, rather than copying it wholesale into the new package. Historical run outputs, source corpora, archives and user documents must not be deleted. Keep historical material outside default test collection and ordinary handoff reading, with an archive index where necessary. Never delete outside the project, rewrite history or run broad cleanup commands.

Mark superseded tasks as retired in the active tracker. Move stale planning documents out of the active documentation navigation; retain them as historical references. Update README, package metadata, CLI help and fresh-session instructions to name only the new active path. If Studio remains, connect its basic run/report view to the new artifacts; defer a Studio redesign. Do not silently leave its default execution pointing at old code.

## D. Checks before handoff

Run import/CLI help, formatting/lint on changed active code, meaningful unit tests for provenance/replay/budget transitions, fixture-backed complete report export, and a rendered-page/figure inspection. Use the repo's established checks where still applicable. Do not restore obsolete tests simply to preserve the old test count, or delete failing relevant tests to claim success.

Use only the Stage 1 smoke allowance in 07: one tiny Codex call with no external research, reading a tiny local evidence file and writing a short artifact. No Claude calls or model-driven rehearsal campaign in Stage 1. Use the supported configured auth path and record usage. If credentials/tooling are missing, record the exact integration block; never pretend a fixture smoke validates the provider. Provider smokes are not a full report run.

## E. Fresh-session handoff

Create under `docs/redesign/`:
- `HANDOFF.md`: <=1,200 words; actual branch/HEAD, dirty state, active entrypoint, exact working commands, completed/deferred items, supported credential mode without secrets, model configuration and remaining risks.
- `ACTIVE_CODE_MAP.md`: <=800 words; active source/prompts/tests/tools only, with purpose and paths; explicitly exclude archived paths from default reading.
- `CLEANUP_MAP.md`: removals/replacements, retained regression rationale and old base commit.
- `TEST_PLAN.md`: links to fixtures/cases and executable commands for 04.
- `RUN_BUDGET.json`: limits copied exactly from 07, active profile, consumed counters and provider availability. Initialize Stage 2 counters only if no Stage 2 campaign exists; preserve existing consumption on resume. Record Stage 1 smoke usage separately.
- `STAGE2-KICKOFF.md`: a ready-to-paste prompt for a fresh session, adapted from 05. Fill in actual checkout/package paths, branch, validated code revision, active profile, handoff paths, working initial commands and budget ledger. No unresolved placeholder commands. Tell the new session to verify current HEAD and use only active context before proceeding autonomously within 07. Do not execute this prompt in Stage 1.

Commands must actually exist and match CLI help. Cover `run`, `replay-stage`, `resume`, `render`, `show-run`, and the Stage 2 driver, whether as subcommands or scripts. Provide example arguments with actual fixture paths. Record installed runtime/library versions and a dependency lock or reproducible install instructions. List known auth blocks before the user leaves, but do not require a new permission dialog for already authorized work.

Commit task changes locally after checking the diff, without including secrets or unrelated edits. Respect actual higher-priority commit requirements; report any unavoidable conflict rather than inventing attribution. Leave no report runs or background agents active. End with READY FOR STAGE 2 or IMPLEMENTED WITH NAMED BLOCKERS, not 'product validated'. Report the final HEAD and any dirty files, the validation results, and links to HANDOFF.md and STAGE2-KICKOFF.md. Record the validated code revision in the handoff; if a later documentation-only commit changes HEAD, distinguish those revisions.

**Mandatory STOP:** return control to the user immediately after this handoff. Do not run the Stage 2 driver, launch its agents, start full report trials, schedule an overnight task, or continue debugging beyond Stage 1 checks. Only the user starting the fresh Stage 2 session activates that campaign. If Stage 1 is blocked, still provide a truthful handoff and kickoff for the remaining work.
