# Model and execution policy — authoritative for both stages

This is the single source of truth for model profiles and numerical campaign limits. The filename is retained for existing links. These conservative ceilings are engineering limits, not a conversion of the user's approximately 10% remaining Claude allowance. They replace the former C/S campaign; prior allowances are not additive. No GPT-6, purchased quota, account rotation, credential changes or automatic API-billed fallback.

## 1. Model assignments

| Purpose | Provider/model | Effort |
|---|---|---|
| Default campaign profile: `low_claude_quota` | Codex for all four roles; `gpt-5.6-sol` | medium |
| Optional `preferred` profile | Supported configured Claude model for lead/industry/company/contextualizer; Codex `gpt-5.6-sol` reviewer | medium where supported; record effective settings |
| Stage rehearsals and optional development peer checks | Codex `gpt-5.5` first | medium |
| Concrete failed rehearsal escalation | Codex `gpt-5.6-sol`, only that case | medium |
| Production reviewer and focused recheck | Codex `gpt-5.6-sol`, independent session | medium |

Verify identifiers/settings through the installed supported runtime. If 5.5 is unavailable, record this and use 5.6 within the same budget. Do not silently substitute another family. The production reviewer's ordinary isolated test satisfies its rehearsal requirement; no redundant 5.5 reviewer call is required. Host development-session selection is the user's client setting; application configuration cannot change it.

Both profiles share prompts, tools, artifacts and one workflow. Model selection belongs in one configuration definition. Document contextualization is a bounded operation using the chosen profile, not an additional autonomous agent role.

## 2. Stage 1 limit and mandatory stop

Stage 1 implements and cleans up, runs meaningful offline fixture/code/render checks, and may make **one Codex smoke call using GPT-5.5 medium, at most 90 seconds, with no external research**. Availability fallback to 5.6 is allowed only if 5.5 cannot be selected before the call. No automatic second smoke attempt. No Claude calls, model-driven rehearsal campaign, peer-agent audit campaign or full live reports in Stage 1.

Record smoke usage separately from Stage 2. Generate every handoff artifact in 02, including a populated `STAGE2-KICKOFF.md`, stop all child work and STOP. Do not execute or schedule Stage 2. The user starts it in a fresh session.

## 3. Stage 2 campaign ceilings

| Resource | Maximum |
|---|---|
| Elapsed session window | 8 hours from recorded campaign start; finish earlier when done |
| Isolated model attempts | 10 total; each at most 6 minutes |
| Full live report attempts | 2 sequential; each at most 30 minutes wall-clock |
| Aggregate model invocation time | 120 minutes summed across all test/report/peer calls; concurrent calls count separately |
| Observable output/reasoning tokens | 100,000 total; add reasoning only when not already included in output |
| Concurrent research workers | 2; no concurrent full reports |
| Optional development peer checks | At most 2, as a subset of the 10 isolated attempts, not an extra allowance |
| External acquisition | 40 search calls and 60 source-fetch attempts across the campaign; failures count |
| Review per report | One review, at most one author revision and one focused recheck |
| Optional Claude probes | At most 3 attempts, 2 minutes each, 6 summed invocation minutes; a subset of isolated attempts |

A submitted isolated stage, probe, peer check, retry or escalation consumes one isolated attempt, including failures. A full report start consumes one full-report attempt; its internal model stages consume the aggregate time/token/source budgets but not isolated-attempt slots. Rerunning an individual stage outside that full attempt consumes an isolated slot. A provider fallback within a full report stays within that report's deadline and counts as a new recorded internal stage attempt; restarting the full workflow consumes another full-report allowance. Never split an operation to evade limits.

Persist admissions and consumption before launching charged work. Resume and provider switches preserve counters; existing consumption is never initialized to zero. Cancel children on deadline/stop before replacement calls. Disable hidden SDK retries where supported or account for them explicitly. Include interrupted attempts and review overhead.

Tokens may be reported only after completion, and subscription usage may be opaque. Record unknown values as unknown, possible in-flight overrun and enforcement limitations. Maintain enforceable wall-time/call ceilings even when tokens cannot be measured. Main coding-session usage is reported separately where observable; these subprocess caps do not guarantee an account quota lasts overnight. If Codex is exhausted, stop charged work and finish offline artifacts where useful.

No full Claude report in this campaign. Full live reports use `low_claude_quota`; optional probes establish only narrow Claude compatibility. Any previously consumed Claude probes documented at handoff reduce the remaining sub-budget rather than being forgotten.

## 4. Rehearsal before expensive execution

During Stage 2, rehearse distinct enabled model stages using saved portable inputs: planning, industry research, company research, selective contextualization, synthesis/figures, production review, and revision/recheck when needed. Use GPT-5.5 first except the production reviewer. Share representative successful results across equivalent task instances with unchanged prompt/tool/input contracts. All rehearsals fit within the isolated-attempt cap; they are not free additions.

Inspect source fidelity and task usefulness. Synthesis, financial comparability and source support require judgment; valid JSON alone is insufficient. If 5.5 fails, inspect inputs, tools and parsing before escalating that same case to 5.6. Do not repeat successful stages merely to use a stronger model. Optional probes/peer checks yield priority to required product-stage validation when the allowance is tight.

Use deterministic fixtures for code-only behavior. Enforce fixed-corpus source boundaries through available runtime controls. Label surrogate experiments honestly: GPT output does not demonstrate Claude behavior, SDK compatibility, timing or quality. A successful GPT rehearsal can be reused as an artifact when its inputs/versions match, but cannot be relabeled a live research result or actual Claude output.

## 5. Small provider interface and quota fallback

Implement two adapters behind one application contract: role, portable inputs, workspace, allowed capabilities, settings and budget → events, artifacts, status and usage. SDK-specific sessions/events/errors stay inside adapters. No generalized plugin framework and no translation of private session state.

On an explicit Claude usage-exhausted response, save the partial attempt, cancel its children, stop new Claude admissions and switch unfinished work to the authorized Codex profile within remaining budgets. Reconstruct a fresh stage session from the brief, selected notes, sources, draft, figure manifest and outstanding issues. Reuse completed source downloads; avoid duplicate tool side effects. Never copy credential files or hidden context.

Timeouts, auth errors, malformed output and generic HTTP 429 are not automatically quota exhaustion. Preserve the actual cause. A transient error may receive one bounded retry only within the existing counters and deadlines. The already authorized GPT profile may continue when Claude is blocked; this does not bypass access controls or validate Claude. Stay on GPT for the rest of the campaign after fallback. If both are unavailable, stop charged work; do not wait for a reset or enable API billing.

Test fallback using injected exhaustion/interruption fixtures, not by intentionally consuming a real subscription. Check artifact preservation, fresh-context reconstruction, independent reviewer context, no duplicate writes and cumulative accounting.

## 6. Honest acceptance

A complete all-GPT report can satisfy this campaign's product outcome. It validates that profile only. Report fixture checks, surrogate rehearsals, real GPT runs, actual Claude probes, fallback stages/reasons and remaining Claude validation separately. Preserve useful reports with truthful review status and limitations; no zero-error certification.
