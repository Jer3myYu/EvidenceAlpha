# Stage 1 handoff — IMPLEMENTED WITH NAMED BLOCKERS

Stage 1 is finished. **STOP: the user starts Stage 2 in a fresh session.** No rehearsal campaign, provider smoke, Claude call, live report, peer agent, overnight task, push, merge or deployment was executed or scheduled. This is implementation/fixture validation, not product validation.

Checkout: `/home/cobot/cobot_storage/webproject/EvidenceAlpha`. Branch: `research-quality-upgrade`. Recoverable base: `3abe9692f3b5f3bbe20390a8d8971af994d3f07b`. Validated implementation HEAD: **`02069a6ac0dc7de7a8bdbab31bb93c6018afa150`**. Working tree was clean after that local commit. A subsequent documentation-only commit adds this handoff/kickoff and validation record; the closing response reports its exact HEAD. Verify current HEAD/status before mutation rather than trusting historical claims.

The supplied package was found under `tmp/docs/redesign-package/`, preserved there and copied to canonical `docs/redesign-package/`. The old starting prompt is archived unchanged at `docs/archive/starting-prompt.md` (SHA256 `9072297fa9277a2f05ae7463a0a9445b99b21e2eba37b98610cc424f99c40233`). Its old location now points to current instructions; root AGENTS/CLAUDE/README and local tracker navigation identify the redesign. Original documents, historical runs/databases and existing ignored files were preserved.

The active entrypoint is `.venv/bin/python -m evidencealpha`. One shared workflow supports planning, optional industry/company workers (maximum two concurrent), original-source retrieval, synthesis/figures, independent review, at most one revision/recheck, Markdown/PDF and stage replay. Failed review retains an unreviewed draft. Draft and revised figure versions have separate retained assets. Portable requests, observable events, settings, outputs, hashes and failed attempts are recorded. The budget ledger reserves charged time before launch, survives resume/provider changes, and retains unknown token values.

Working inspection/check commands:

```bash
cd /home/cobot/cobot_storage/webproject/EvidenceAlpha
.venv/bin/python -m evidencealpha --help
.venv/bin/pytest
.venv/bin/black --check src/evidencealpha tests/redesign
.venv/bin/pylint --jobs=1 src/evidencealpha tests/redesign
.venv/bin/python -m evidencealpha show-run data/redesign/stage1-final-service
.venv/bin/python -m evidencealpha resume data/redesign/stage1-final-service --fixture tests/fixtures/redesign/service.json
.venv/bin/python -m evidencealpha render data/redesign/stage1-final-manufacturing/reports/report.md
.venv/bin/python -m evidencealpha stage2 --help
```

`TEST_PLAN.md` contains tested creation/replay commands, actual fixture/corpus paths and executable Stage 2 case syntax. Existing creation output directories must not be deleted or reused as new runs. The Stage 2 driver command was checked through help/syntax only; no case was executed. It admits one case at a time, not an automatic overnight queue. Live resume is an explicit fork via a full case's `resume_from`; it consumes a new full-attempt slot. Prefer isolated replay for localized failures.

Validation: **21 focused pytest tests passed**; active imports, CLI/help, Black, pylint and diff checks passed. Manufacturing and service fixture exports produced readable Markdown/PDF, tables, source links, a Chinese relationship diagram and a quantitative chart. Rendered pages and figures were visually inspected; Unicode DOT escaping and PDF text-read-back ligatures were corrected. An existing four-page Chinese issuer PDF was parsed/retrieved offline with reopenable Unicode spans. See `VALIDATION.json` and `TEST_PLAN.md`. Fixtures do not establish research intelligence, source sufficiency or real independent review quality.

Configuration lives in `src/evidencealpha/config.py`: default `low_claude_quota`, Codex `gpt-5.6-sol` medium for production/reviewer, `gpt-5.5` medium for rehearsals. Explicit rehearsal fallback to 5.6 is configurable. Contextualization is disabled by default. `RUN_BUDGET.json` has a null campaign start, zero attempts/invocations/searches/fetches and zero Stage 1 smoke calls. Stage 2 retains its full ceilings: 8 hours, 10 isolated attempts (6 minutes each), 2 sequential full attempts (30 minutes each), 120 aggregate invocation minutes, 100,000 observable tokens, 40 searches, 60 fetches, 2 workers, optional 2 peer checks and 3 Claude probes (2 minutes each/6 total) **within** the isolated/aggregate caps. Coding-session consumption is unavailable; no subscription balance or dollar estimate is claimed.

Named integration blockers/gaps:

- Codex CLI/catalog/login are available, but actual calls, effective model/effort and native tool enforcement are untested. Do not claim guaranteed fixed-evidence execution until controls are verified. Both providers use portable application tool rounds, not faithful private-session continuation.
- Claude SDK/CLI are installed, but no supported model is configured and actual login/retry/quota-event behavior is unvalidated. No Claude call was made. Fixture exhaustion tests validate orchestration only.
- Tavily key is not exported. `.env` was preserved and not printed. Use the user's supported existing configuration; no account changes, token extraction or API-billed fallback. Live acquisition remains untested.
- Reviewers receive figure data/provenance/hashes, not native multimodal pixels. Fresh-session visual inspection is required. Digital PDF extraction is not OCR; optional embeddings/token-aware chunking and real service-domain research remain unvalidated.

Python is 3.12.13. Exact CLI/library versions are in `VERSIONS.json`; reproducible active dependency pins are in `constraints.txt`. Install instructions are in TEST_PLAN. Existing unrelated venv packages were not purged.

Code quality/cleanup: retired industry/research/RAG workflows, CrewAI/LangGraph wrappers, old entrypoints, Studio and architecture-only tests were removed from active code; Git preserves them at the base revision. No duplicate production path remains. Shared providers/tools/provenance/rendering and centralized configuration replace them. Active imports contain no legacy dependencies or report-specific names/paths. The 68-package installed active dependency closure excludes CrewAI. Intentional deferrals are a new Studio, actual provider validation, native multimodal review and optional embeddings; there is no old-workflow compatibility exception.

All Stage 1-owned command sessions and child work were completed; no report/model jobs or agents remain. Next context: `STAGE2-KICKOFF.md`, this file, `ACTIVE_CODE_MAP.md`, package 07/04; consult 08 for every fix. Do not load archived audits by default.
