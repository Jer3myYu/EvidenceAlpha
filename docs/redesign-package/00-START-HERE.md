# EvidenceAlpha redesign — two-session implementation package

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

Status: proposed implementation instructions, not implemented software.
Prepared 2026-09-11. This package defines a new product path; it is not another round of the former C/S upgrade.

Read `08-CODE-QUALITY.md` for implementation and cleanup requirements in both stages.

## Product goal

Deliver a coherent, sourced industry/company research report for an investor who understands investing but is unfamiliar with the field. Chinese terminology first for Chinese requests. Cover the requested value chain, technology, commercialization, company comparisons, economics and risks. Include useful tables, diagrams and quantitative charts when supported. No trading or unsupported price predictions.

The user accepts residual errors. Do not build a zero-error certification system. Prioritize a useful complete report, truthful limitations, bounded research/review, and cheap stage-level iteration.

## Decisions already made

- Four roles: Research Lead, Industry Researcher, Company Researcher, Independent Reviewer. Company researchers can have multiple instances; no additional editor or mandatory coverage-judge agent.
- Lead owns scope, synthesis, writing, figures and one revision. Research specialists remain available and are used when the brief benefits from them.
- Two interchangeable runtime adapters: Claude and Codex. The default `low_claude_quota` campaign uses Codex/GPT-5.6 Sol medium for all roles; the `preferred` profile uses Claude for lead/researchers and Codex for review. GPT-5.5 medium is for economical stage rehearsals. Exact configuration and fallback policy are in 07. All research/review roles need source access.
- Document preparation is ordinary parsing/chunking plus selective bounded LLM contextualization. RAG returns original passages and source locations. Generated summaries are navigation aids, not evidence.
- Reuse built-in tools first. A small custom retrieval interface is justified. Source capture and replay logging belong to infrastructure.
- One independent review, at most one consolidated revision and one focused recheck. No automatic repeat-until-pass.
- Record stages and rerun affected stages before full workflows. Development surrogate-model outputs must be labeled.
- No GPT-6 use in this campaign; model changes remain configuration changes for later.

## Read order

Stage 1: this file → 07-LOW-QUOTA-OVERRIDE.md → 01-DESIGN.md → 02-STAGE-1-BUILD.md → 03-STAGE-REPLAY.md → 08-CODE-QUALITY.md. Consult 04 for the required handoff fields and acceptance cases; do not begin its campaign.

Stage 2: start with the generated `docs/redesign/STAGE2-KICKOFF.md`; read `HANDOFF.md` and `ACTIVE_CODE_MAP.md`, then 07 and 04. Apply 08 to fixes. Read 01/03 only for the relevant contract. Never load the entire legacy tree or all historical audit logs by default.

Copy/paste launch instructions are in 05-SESSION-PROMPTS.md. Reference links are in 06-REFERENCES.md. The two PNGs illustrate topology; this written specification controls model assignments and delivery details.

## Session boundary

1. Stage 1 implements, removes obsolete active paths, performs focused checks, and writes a clean handoff plus a ready-to-paste `STAGE2-KICKOFF.md` with actual paths and commands. Then STOP. Do not launch, schedule or leave Stage 2 running in the background. The user explicitly wants to switch sessions.
2. The user starts a fresh Codex session with the Stage 2 prompt. That invocation authorizes the bounded unattended campaign in 04. Continue implementation fixes, testing and debugging autonomously within those limits.

No external push, merge, deployment, publication, account changes, credential extraction or purchased quota. Local branches, local commits, reversible code cleanup, tests, source retrieval and the bounded runs are within the requested work. Follow actual higher-priority platform constraints. An old project instruction to ask before every ordinary test is superseded by the user's requested unattended Stage 2 scope; this does not bypass tool approval enforcement. Record any unavoidable external block and continue useful offline work.

## Model selection

Use the explicit reviewer default `gpt-5.6-sol`, reasoning `medium`. Verify the installed Codex runtime accepts both; record requested and reported effective settings. Do not substitute GPT-6 or an API-billed provider if unavailable. Temporary Codex substitution for Claude is authorized by 07. If one provider is blocked, continue with the other already authorized profile where available; report which integration remains untested. If neither is available, continue offline.

Recommended development session model: GPT-5.6 Sol medium as well; the implementer must not pretend to change its own host model. It can tell the user the selection before Stage 2 starts. Do not default to Max/Ultra or launch repeated independent audit agents.

Claude model: discover and record the user's current supported configured model. Do not invent a model ID from old notes or silently upgrade it. Document preparation uses the selected profile; cheaper alternatives require explicit configuration. Do not introduce an extra provider or silent model selection.

## What this package does not assume

The local code inspected while preparing this package is an older repository snapshot. The implementer must inspect the actual branch, HEAD, working tree and installed runtimes. Proposed module/command names below are interface targets, not claims those files exist. Current model access, credentials and subscription balances must be established locally, without reading secrets into logs.

No promise of a particular runtime or cost reduction. No completion claim based solely on a green test count. Success needs an actual readable report.

## Consistency review outcome

This edition consolidates model/budget policy in 07, removes fixed-Claude role assignments from the default campaign, and separates offline fixture checks, GPT rehearsals, actual provider validation and full live reports. Stage 1 must generate the handoff and Stage 2 kickoff and stop. Stage 2 must inherit usage counters rather than reset them. The old C/S campaign and its allowances are retired. This is a document review, not a code or runtime validation.
