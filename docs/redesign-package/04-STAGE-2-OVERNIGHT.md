# Stage 2 — fresh-session, unattended test and refinement

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

## Authorization and limits

The user starts this stage explicitly in a fresh session and permits autonomous local fixes, tests and the bounded model/source campaign below. Do not wait for per-run confirmation. Do not push, merge, deploy, send messages, purchase credits, change credentials, or activate paid API fallback. Honor actual platform/tool restrictions; record and work around a block only through supported routes.

The numerical limits and model profiles in 07 are authoritative. They replace the former C/S campaign; old allowances are not additive. Load the persisted RUN_BUDGET.json and reconcile prior consumption before starting. Do not reset counters when resuming, changing providers or starting a fresh debugging session.

Enforce time/call limits through supported controls and record observed consumption. Missing token fields remain unknown. If a runtime cannot bound or terminate charged child calls, mark that live path blocked and continue offline. Distinguish the main coding session's usage from measured test/report calls. Stop charged work when the relevant allowance is exhausted; do not wait for quota resets or activate paid API fallback.

Inside a 30-minute full attempt, initial soft allocations: plan 2m; research 10m; synthesis/figures 8m; review 4m; revision/recheck 4m; export 2m. These are engineering starting budgets, not benchmark results. Reallocate unused time, but stop research near its boundary so writing actually happens. Research may be incomplete; the report explains gaps. Do not emit a blank report just because exhaustive coverage is unavailable.

Use short role outputs: plans roughly <=800 words, researcher notes roughly <=1,500 words per task, review <=1,200 words and targeted recheck <=600 words. Synthesis must have room for a real report (initial output budget around 8,000 tokens if the runtime supports it); never silently truncate the final report to meet an arbitrary word quota. These are prompt targets except where a supported SDK setting enforces a limit. Record effective limits and budget exhaustion honestly.

## Step 1: Load only active context

Read the generated Stage 2 kickoff, Stage 1 HANDOFF/ACTIVE_CODE_MAP, 07 and this file. Consult 00 and relevant contracts in 01/03 as needed; apply 08 to all changes. Verify HEAD/working tree, absence of stray live jobs, actual CLI commands, fixture paths, model settings and supported auth. Do not read all archived audits or rebuild the former upgrade. If Stage 1 is incomplete, repair its concrete prerequisites and record this; do not automatically restart implementation from scratch.

Confirm the reviewer uses `gpt-5.6-sol` medium. If unavailable, continue fixture work and record the blocked live reviewer; do not invent availability or switch to GPT-6. Ensure a configured supported Claude model before optional bounded Claude probes. Full report trials use the low_claude_quota all-GPT profile.

## Step 2: Run the cheap offline checks first

Use concise test output; inspect only failures. Test:
- A compact real document corpus gives valid source IDs and reopenable locations; summary references do not masquerade as quotes.
- Chinese text, a multi-entity table, a reporting-period mismatch and a table header/unit are retained and retrievable.
- No-op fixture replay performs no model/network calls and produces the same intended report content/assets (ignore nondeterministic PDF metadata).
- A changed source/draft makes affected downstream outputs stale; unrelated stages remain reusable.
- Empty/malformed provider output and timeouts preserve draft/errors and do not enter a repeated loop.
- Review with material issues triggers one revision/recheck; optional polish alone does not trigger a research cycle; final recheck issues do not start a third review.
- Markdown/PDF has body, table, source links and readable figure(s); a PDF failure still retains Markdown.
- Failed/interrupted attempts count toward campaign usage, including subprocess cleanup.

Use a small synthetic error fixture for mechanism tests, clearly labeled; no fabricated external facts in real research reports. Tests should target observable behavior rather than mirror implementation details.

## Step 3: Exercise real stages with frozen inputs

Choose a small source pack covering the photomask brief; use saved real sources when available. Do not claim a compact pack covers the entire industry. If no adequate real pack exists, acquire a few primary sources within the acquisition budget and preserve original bytes. Record source publication and acquisition dates. Do not backdate reacquired sources.

1. Validate deterministic source parsing/locations/retrieval without a model where possible.
2. Rehearse each distinct enabled model stage on compact saved inputs: planning, industry research, company research, selective contextualization, and synthesis/figures. Start with GPT-5.5 medium. Inspect usefulness and source fidelity, not just parseable output. Share a successful representative rehearsal across identical task instances.
3. Run the production GPT-5.6 reviewer on the saved draft with the same source access. This satisfies its rehearsal requirement; do not add a redundant GPT-5.5 reviewer call. Check representative objections against originals.
4. Exercise revision and focused recheck only if needed. The author rehearsal can use GPT-5.5; the production reviewer recheck remains GPT-5.6. Disabled contextualization does not need a model call. These attempts, escalations and any optional peer/Claude probes share 07's isolated-attempt allowance.
5. Escalate only a concrete failed GPT-5.5 case to GPT-5.6 after checking inputs, tools and parsing. If the shared allowance cannot cover required remaining validation, finish with named gaps; do not quietly expand the budget or claim untested stages passed.

A representative rehearsal before a Claude probe diagnoses prompt/tool problems; it does not predict identical Claude behavior. Optional Claude compatibility probes occur only under 07. If Claude is unavailable, continue the all-GPT campaign and mark Claude integration pending.

Add a compact software/service case from real evidence where feasible to test that manufacturing assumptions are not hardcoded. A synthetic service fixture may establish schema/mechanism flexibility only; label real-source product validation pending if missing. Do not expand into a large benchmark-building project.

## Step 4: Full workflow only after stage readiness

Once the stages compose and produce a useful report, run one genuine live photomask report end-to-end. Let industry and company researchers work with an actual brief. Fixed-corpus stage outputs cannot be substituted and then called a live run.

Example user brief: Chinese deep-dive for an investor new to photomasks; explain value chain/upstream-downstream players, technology barriers, China/global gaps, demand/risks, development-to-qualification-to-production, and compare 清溢光电、路维光电、龙图光罩 using sourced comparable information. No price prediction. Include useful visuals.

Inspect the final Markdown, PDF and figures. If a real defect blocks delivery, save the attempt and reproduce the affected stage. Use the second full attempt only after a specific change warrants integration validation. If first run is successful and no material integration risk remains, skip the second; do not spend allowance just because it exists.

## Step 5: Acceptance and finish

A successful product result is a coherent actual report with source-linked analysis, useful company comparison, an appropriate table and visual where evidence supports it, and clear limitations. Missing evidence must be explained rather than concealed. Review status must be truthful. No requirement for zero minor errors; no claim of full factual certification.

Score the observed outcome briefly on:
- usefulness for a newcomer;
- response to the requested questions and material omissions;
- checked factual/citation accuracy, including reviewer false objections;
- financial/technical comparison validity;
- visual usefulness/readability;
- end-to-end time, per-stage cost/usage and failed-attempt overhead.

A headings-only report, diagnostics-only artifact, mocked report or inaccessible PDF is not full acceptance. Markdown delivery with a PDF issue is a partial implementation outcome, not a total research failure. Preserve the best available report without falsely calling it complete/reviewed.

Stop once enough evidence resolves these questions; no repeated full audit panels. At the time/budget cap, preserve artifacts and report named remaining work. Quota exhaustion, missing auth or source outages should not be relabeled code defects. Do not promise to continue after the execution session has stopped.

## Completion packet

Write `docs/redesign/COMPLETION.md` and a concise `NEXT_SESSION.md`, plus a machine-readable results/usage ledger. Include exact final commit and dirty state; what changed; tests actually run; failed/interrupted attempts; final report/PDF/figures paths; source manifests; honest live versus fixture/surrogate status; measured duration and known/unknown consumption; limitations and any remaining blockers. List deliberately retired/deferred work. Commit task changes locally, leave no live children running, and stop. No push/merge/deploy.
