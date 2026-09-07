# Industry Research System: Refined Design and Claude Implementation Handoff

Date: 2026-09-07  
Project: ai_agent_CMU  
Implementer: Claude Code, using the user's selected Claude 5.1 Fable session  
Independent reviewer: Codex at the checkpoints below  
Priority: report quality, evidence integrity, and clean maintainable code

## 1. Instructions to Claude Code

Treat this entire document as the implementation brief. Implement the approved design on top of the actual repository. Do not merely produce a proposal or rebuild the project from scratch.

Begin by reading repository instructions, inspecting the current branch and working tree, and tracing the actual workflow, agent adapter, tools, persistence, prompts, tests, and Studio. Historical filenames and commits below are orientation, not proof of current code. Preserve unrelated user changes. Use an isolated branch or worktree when appropriate; do not reset the user's tree.

Prepare a concrete implementation plan, module/state changes, compatibility strategy, and meaningful test plan. Run Codex checkpoint C0 before major implementation. Resolve routine decisions independently. Ask the user one consolidated set of questions only if genuinely material product or compatibility decisions remain; otherwise continue. The overall design is already authorized. Subsequent Codex checkpoints are automated engineering reviews, not requests for user permission at every step.

After C0, implement, test, obtain reviews, fix substantiated findings, and continue autonomously through final evaluation. Do not stop after each phase to ask whether to proceed. Report brief progress and keep a durable implementation log. If Codex is unavailable, create the review packet, label the review pending, perform a clearly labeled self-review, and continue reversible work. Never claim an independent review happened when it did not. Final independent review remains pending until actually performed.

Do not push, merge, publish packages, deploy, buy credits, switch to paid API billing, or upgrade subscriptions as part of this handoff. Local implementation, relevant live research tests through configured services, and local checkpoint commits consistent with repository rules are in scope. Do not change the research runtime model merely because the coding session uses Fable. Inspect its actual configured model and adapter first.

## 2. Product goal and evidence behind the design

The user is an investor who understands basic investing but is unfamiliar with the industry. A short question such as “光掩模产业调研” must be enough to produce an accessible, evidence-backed industry report. The system must discover 产业链信息 and 上下游企业信息 without requiring the user to supply an outline or company list.

The current system reportedly uses LangGraph plan → research → evaluate → finish → verify, a maximum of two research rounds, one report revision, CrewAI single-role calls, a Claude Agent SDK research loop, in-process MCP tools, Tavily, Chroma, SQLite checkpoints, and a read-only Workflow Studio. References supplied by the user include workflow.py, agent.py, crew.py, persist.py, scripts/studio.py, and scripts/studio.html. Historical commits: e68d5e4 for the supplied run and 4e00b02 for Studio; verify actual HEAD.

The supplied photomask run demonstrated discovery across materials, equipment, manufacturing, applications, and companies; it resumed after a planner schema failure. It also showed weak source dependence, irrelevant RAG results, inconsistent market definitions, lenient sufficiency evaluation, and a remaining conflict at the revision cap. The reported 121/121 supported claims is an internal verifier result, not an independently established accuracy rate. The artifact does not reproduce the original input and references user-listed priorities, so it does not prove bare-question performance.

The preferred GPT-generated PDF is an editorial reference: coherent comparisons, commercialization stages, business mechanisms, and monitoring indicators. It is not factual ground truth. Re-research its numbers and conclusions rather than copying them into prompts or test expectations.

Earlier course checkpoints establish progressive research, RAG, selective alternative-hypothesis reasoning, independent verification, and centralized coordination. Their earlier framework choices and agent counts are design history, not requirements to reproduce obsolete complexity. Use supplied files if available; do not block on them because this brief is self-contained.

## 3. Default report contract

For an unspecified industry-research request, use an investor-oriented industry brief with substantial coverage, not a shallow summary and not an automatic exhaustive deep dive. Chinese input defaults to Chinese output. State scope and information cutoff. Explain unfamiliar terms on first use. Honor explicit geography, depth, language, and company constraints. With no geography specified, use global structure with a China comparison where relevant; include listed and private participants without assuming only A-shares matter.

Required learning questions:

1. What is the product/service, why is it needed, and what belongs inside or outside this industry?
2. How do upstream, midstream, downstream, and relevant adjacent activities connect?
3. Which representative companies participate, what do they supply or buy, and which relationships are documented?
4. Who pays whom, what drives demand, and where do costs, differentiation, and bargaining power arise?
5. What barriers protect existing suppliers, and how are technical capabilities commercialized?
6. How do global leaders and Chinese participants differ in capability and commercial progress?
7. How do representative companies compare on business-relevant, consistent dimensions?
8. What conclusions are supported, what could invalidate them, and what should the reader monitor next?

Support navigation, brief, and deep-dive modes through evidence and coverage requirements. Do not enforce length as a proxy for depth. Choose company comparison dimensions from the industry economics; do not force manufacturing metrics onto software or services. Treat unavailable data as unknown, not zero. Do not force numeric value-chain shares when no comparable evidence exists.

Suggested report structure: executive understanding; industry/value-chain and participant map; economics and competitive barriers; global/China and company comparison; conclusions, risks, monitoring, and limitations. Adapt naturally; avoid many tiny chapters. Include concise comparable tables and an evidenced chain map where useful. Every named commercial relationship needs evidence; a generic industry dependency must be labeled as such. No buy/sell instructions or unsupported price targets.

## 4. Six agent roles, one controller

| Role | Responsibility | Output | Tool access |
|---|---|---|---|
| Research Lead | Scope, research questions, task allocation, coverage decisions | Research brief, tasks, follow-up recommendations | Normally structured reasoning over state |
| Industry Researcher | Products, value chain, technology, suppliers, applications, demand | Evidence-backed industry findings and relationships | Search, fetch/ingest, document retrieval |
| Company Researcher | Comparable business profiles, exposure, financials, commercial progress | Company findings and metrics | Same research tools |
| Investment Analyst | Explain economics, compare businesses, challenge conclusions | Analytical findings, counterarguments, evidence gaps | Evidence access and deterministic calculations; request acquisition through tasks |
| Evidence Verifier | Validate material claims, relevance, dates, scope, contradictions | Claim assessments and actionable issues | Evidence retrieval and bounded independent source acquisition |
| Report Editor | Build a cohesive explanation from reviewed findings | Report sections and claim/citation mapping | Reviewed evidence access; no unrestricted research loop |

These are roles, not six permanent services. One role may execute at several graph nodes. Create multiple task-scoped researcher instances only for independent work. Keep sessions isolated and pass relevant context explicitly. Do not share mutable SDK sessions across workers.

LangGraph owns scheduling, budgets, routing, and persistence. Reuse CrewAI role framing where helpful and the SDK tool loop where needed. Do not add a second hierarchical controller or require network A2A to communicate within one process. Structured task/result envelopes satisfy local coordination. Preserve the existing adapter and subscription isolation unless an inspected incompatibility requires a localized change.

## 5. Workflow and routing

Normal flow:

Scope → initial industry map → task preparation → focused research → analysis → pre-draft evidence review → writing → final review → delivery.

1. The Lead produces a typed brief: audience, language, mode, boundary, geography, cutoff, required questions, evidence expectations, and budget policy.
2. Initial industry discovery establishes segment boundaries and candidate participants. Use shallow planning alternatives when the boundary is genuinely ambiguous; source-backed preliminary findings remain provisional.
3. The Lead creates bounded tasks with objective, scope, dependencies, required fields, relevant references, and completion criteria. Select representative companies by relevance and business model, not arbitrary fixed names.
4. Industry and company research can run concurrently after dependencies are satisfied. Start with at most three simultaneous tool-using tasks, configurable after SDK/service testing. Breadth may be larger through queued tasks.
5. Merge findings deterministically. Lead coverage assessment creates concrete missing-evidence tasks rather than only a sufficient/insufficient label.
6. Analyst builds material conclusions from evidence, identifies missing analytical inputs, and requests targeted work when necessary.
7. Verifier reviews material findings before drafting. Independent verification means inspecting evidence, not merely reading researcher summaries.
8. Editor writes from supported and explicitly qualified findings. Each factual assertion must map to evidence; new substantive claims reopen review.
9. Final verification checks the exact draft and section dependencies. Lead assesses coverage and beginner usefulness. Deterministic routing chooses targeted research, analysis revision, editorial revision, or delivery.

Issue routing:

| Issue | Owner/action |
|---|---|
| Missing potentially obtainable evidence | Relevant researcher task |
| Material contradictory sources | Verifier source inspection, then focused acquisition if required |
| Weak inference or comparison | Analyst revision |
| Wrong wording or poor organization | Editor revision |
| Unsupported optional statement | Remove or qualify and recheck dependent conclusions |
| Unavailable evidence after productive attempts | Explicit limitation or incomplete result |

No stage may interpret reaching a retry limit as passing verification. Keep execution status (running/interrupted/completed/failed) separate from report status (complete/complete_with_limitations/incomplete). A complete-with-limitations report cannot retain an unsupported central conclusion as established fact. Operational failure must not masquerade as ordinary research uncertainty.

## 6. Typed evidence and state contracts

Use the project's existing validation library and naming patterns. Define small typed records rather than a generic knowledge-graph framework. Recommended fields below are semantic requirements, not a demand for one class per row.

| Record | Required semantics |
|---|---|
| Source | Stable identity, original publisher, document title/URL, publication and retrieval dates, content version/hash, provenance and original-source relation |
| Evidence | Exact passage/table excerpt, source version, page/section or other locator, entity, period, unit/currency where relevant, scope, extraction method/limitations |
| Claim | Stable ID, statement, fact/inference/forecast distinction, evidence references, materiality, review state, version/supersession |
| Relationship | From/to entity or segment, relation type, generic dependency versus confirmed commercial relationship, evidence and date |
| Task | ID, objective, owner role, scope, dependencies, relevant references, status, attempts, acceptance criteria |
| Issue | ID, affected claim/question/section, category, severity, requested action, attempts, resolution and evidence |
| Analysis finding | Conclusion, supporting claim IDs, reasoning summary, counterevidence, uncertainty, observable follow-up |
| Report section | Stable section identity, text, referenced claim IDs and review version |

Record confidence through evidence and limitations rather than uncalibrated numeric certainty. Materiality means a finding changes the main industry explanation, comparison, or conclusion.

Keep raw observations and source snapshots immutable where available. Supersede corrected findings; invalidate prior approval when claim text or supporting evidence changes. Avoid extracting every sentence into a record; prioritize substantive facts and conclusions while still checking factual assertions in the final text.

Prefer serialized typed records in existing checkpointed state and original-source files referenced by stable IDs. Add relational tables only where a concrete query or persistence requirement warrants them. Never store SDK clients or CrewAI objects in checkpoints. Never create a second competing workflow-state authority.

Workers return local task results. A deterministic coordinator merges them in stable task order, assigns canonical IDs, and updates the registry. Duplicate delivery or resumed execution must not append duplicate evidence, spend the same logical budget twice, or silently replace a different source version. Distinguish harmless repeated reads from irreversible side effects; do not promise exactly-once external calls when the provider cannot supply it.

## 7. Retrieval, provenance, and context

Use discovery sources to locate original evidence. For material company numbers and commercial milestones, prefer actual filings/disclosures. For market sizes or shares, retain year, geography, denominator, definitions, and methodology. Primary company statements establish what the company disclosed, not automatic independent proof of every marketing claim.

Do not count syndicated copies as independent corroboration. Do not rank quality solely by hosting domain: an official filing mirrored by a media site remains a filing, while an article hosted by a reputable platform is not automatically primary. Search snippets are leads; obtain adequate original context for material claims or qualify them.

Improve chunking to preserve sections, sentences, and table headers where feasible with current loaders. Capture extraction limitations; never silently convert broken tables into trustworthy numerical evidence. Add metadata filtering and calibrated relevance checks. Do not choose an arbitrary universal similarity cutoff without testing the embedding/distance behavior. Add reranking or a new parser only when a measured failure justifies it.

Persist fetched content versions needed for historical evidence. If extraction configuration changes, version the index/metadata and rebuild safely rather than mixing incompatible chunks. Serialize or coordinate Chroma writes; keep retrieval available as supported. Fetching URLs must reject local/private targets and unsafe redirects, bound size/time, and treat page instructions as untrusted data. Preserve existing protections and test relevant cases.

Give each agent only its brief, assigned task, relevant evidence, open issues, and output schema. Summaries must preserve links to raw evidence. Context truncation must be visible and must not drop unresolved material issues. Do not log credentials or request hidden reasoning traces.

## 8. Analysis and editorial requirements

For each main conclusion, require observation → mechanism → business implication → counterargument → observable test. Separate reported facts, company claims, analyst inference, and forecasts in both state and language.

Explicitly distinguish R&D, sample delivery, customer qualification, small-batch production, stable production, and material revenue. Preserve the date of each milestone. Do not infer a confirmed supplier relationship from product compatibility. Do not use different fiscal periods, denominators, currencies, or business mixes as if comparable without explanation.

Calculate arithmetic deterministically, retaining input references, units, formula, and handling for zero/negative denominators. Provide a narrow calculation utility, not arbitrary model-generated code execution.

Use alternative-hypothesis exploration only for consequential uncertainty. Check differing dates, definitions, or methodology before generating speculative explanations. Retain unresolved conflicts if evidence cannot distinguish explanations. No mandatory depth-three thought tree on every task.

Editor should lead with what the investor needs to understand, connect numbers to mechanisms, compare on common dimensions, and omit adjacent-industry trivia. Prefer fewer well-supported findings to exhaustive unsupported precision. Revisions target affected sections and their dependent conclusions; final consistency review still covers the whole report. Preserve clear source links and nearby limitations.

## 9. Quality gates and bounded autonomy

Pre-draft gate: required questions covered or explicitly unresolved; material findings substantiated; relevant relationships evidenced; comparisons comparable; source scope/date appropriate; counterarguments considered.

Final gate: actual wording and citations checked; no new unsupported material assertions; conclusions consistent across text/tables; limitations attached to affected claims; value chain intelligible to a newcomer; no unexplained tangents or repeated data dumps.

Initial tunable control policy: two targeted follow-ups per material issue, a third only with new useful evidence and a concrete next acquisition step. Prevent duplicate issues from resetting attempt limits by canonicalizing affected question/claim and issue type. Limit total remediation cycles, model calls/tool calls, and wall time across all agents, including nested SDK retries, verifier research, and editorial loops. Reserve capacity for final verification and graceful incomplete delivery. Choose generous concrete defaults during C0 based on baseline duration and configured service limits; these limits prevent runaway execution, not enforce low-cost writing.

Track usage where actually exposed; label estimates and unavailable costs honestly. Retry transient transport/service failures with bounded backoff. Distinguish schema failures from transient service failures; avoid multiplying SDK retries with graph retries. Persist budget consumption and completed tasks. No-progress and exhausted-budget paths must terminate with honest status.

## 10. Persistence and Workflow Studio compatibility

Inspect existing checkpoint formats before schema/topology changes. Record workflow version and schema version for new runs. Preserve old SQLite data and support legacy replay through a compatible adapter where practical. Do not resume an old interrupted thread into a new incompatible graph. Either provide and test explicit migration or retain its legacy execution path; if neither is feasible, explain the incompatibility and preserve read-only replay with a clear resume error. Back up before migrations and test on copied fixtures.

Checkpoint task-level progress so one worker failure does not require repeating all completed research. Test the actual LangGraph execution/persistence behavior instead of assuming concurrent node semantics.

Studio remains observational. Show role/task identity, live tool events, evidence/claim references, coverage gaps, review issues and resolutions, active budgets, execution status, and report status. Support multiple concurrent task cards without ambiguous ordering. Record application-supplied messages, output schema, tool definitions, prompt/config/model versions, and SDK-visible events where exposed. Label reconstructed historical context; do not claim visibility into provider-internal messages or hidden reasoning. One CLI/UI event representation should prevent divergent explanations of routing.

## 11. Delivery phases and Codex review checkpoints

| Phase | Scope and exit evidence | Review |
|---|---|---|
| 0 — Inspect and design | Actual repository map, baseline tests, implementation plan, compatibility strategy, concrete budget policy, risks | C0 architecture review before major implementation |
| 1 — Contracts and foundation | Typed brief/evidence/tasks/issues, deterministic merge, source provenance, versioning and status semantics; old flow still usable | C1 foundation review |
| 2 — Research and analysis | Initial mapping, company/industry research, bounded concurrency, analyst, acquisition/context improvements | Included in C2 |
| 3 — Quality loops | Pre-draft review, editor, final review, targeted remediation, no-progress/limit behavior, safe resume | C2 integrated workflow review |
| 4 — Studio and evaluation | Version-aware replay, task visibility, bare-question evaluation, final cleanup/documentation | C3 final review |

All five phases are in scope. Cross-question project memory, monitoring schedules, notifications, automated trading, network A2A, and a replacement UI are future work. Document their extension points briefly; do not implement them now. Deliver Markdown reports through the current reporting path. A polished new PDF renderer is not required for this iteration; preserve any existing export support.

### Reviewer model policy

As checked on 2026-09-07, OpenAI's official pricing page lists GPT-6 Astra under Plus, and the model page documents `codex -m gpt-6-astra` and `codex -m gpt-5.6-sol`. Account-specific availability and remaining allowance cannot be established from this handoff. Check the actual signed-in client. ChatGPT subscription access and API billing are separate choices; do not silently switch billing.

Sources: [Official model selection](https://learn.chatgpt.com/docs/models), [Official Codex/Work pricing](https://learn.chatgpt.com/docs/pricing).

Recommended assignments (engineering choices, not an official OpenAI review policy):

| Checkpoint | Preferred model | Reasoning effort if available | Fallback |
|---|---|---|---|
| C0 architecture | GPT-6 Astra (`gpt-6-astra`) | High | GPT-5.6 Sol, High |
| C1 contracts/persistence | GPT-5.6 Sol (`gpt-5.6-sol`) | High | Astra if available; otherwise strongest accessible coding reviewer, disclosed |
| C2 integrated graph/concurrency | GPT-6 Astra | High; Extra High for unresolved cross-module failures | GPT-5.6 Sol, High |
| C3 final quality and regression | GPT-6 Astra | High | GPT-5.6 Sol, High |

Use Astra throughout if accessible and useful; Sol is a practical intermediate reviewer, not a mandatory downgrade. Verify the model actually used and record it. Do not label a review “GPT-6” based only on the requested setting. Inspect installed Codex help before constructing noninteractive/review commands; syntax can vary by version. Prefer a fresh read-only Codex session in the same checkout with the checkpoint prompt. Do not assume a built-in `/review` command inherits a particular model without confirming. Do not install a new framework solely to automate reviews.

For every checkpoint, record the baseline commit, candidate commit or exact working diff, model, prompt, findings, and resolution. Address all substantiated critical/high issues and material medium issues. Re-review affected areas after fixes; provide reasoned disagreement for false positives. Do not endlessly solicit reviews for style preferences. If review access is unavailable, save the packet, continue reversible implementation, and report the missing independent gate at completion.

## 12. Tests and evaluation

Use existing pytest/format/lint conventions; inspect actual project commands. Preserve working tests, updating those whose asserted behavior intentionally changes. Add tests for observable risks, not prompt wording or implementation mirrors unless exact adapter framing is an established compatibility contract.

Required deterministic coverage:

- Brief defaults and explicit user overrides; no hardcoded photomask company selection.
- Evidence references, version changes, stale approval invalidation, source deduplication, and irrelevant retrieval handling.
- Fact/inference distinctions; generic dependency versus documented customer relation.
- Unit/period validation and calculation behavior.
- Routing each issue to the right stage; global/per-issue limits including nested loops; no-progress termination.
- Idempotent result merge, concurrent task isolation, partial failure, and resume with completed tasks intact.
- Schema/transport failure handling without compounded runaway retries.
- Legacy checkpoint replay and explicit incompatible-resume behavior.
- Revision introducing a new claim triggers verification; budget exhaustion never yields an invented pass.
- URL acquisition boundaries and untrusted source content handling relevant to changed code.
- Studio event consistency and concurrent-task rendering behavior.

Use fixed source fixtures to isolate code/prompt effects from changing web results. Then run live end-to-end cases using configured services:

1. Exactly `光掩模产业调研` — no outline or company list.
2. Another manufacturing industry with a different value chain.
3. A software/service industry so the design cannot pass by repeating a manufacturing template.
4. A fixture with conflicting definitions and syndicated sources.
5. A fixture with insufficient evidence and a forced interruption/resume.

For the headline bare-question case, preserve the exact input, baseline/new reports, source snapshots where available, configuration, run IDs, review findings, timings, and usage. Run a second headline trial to assess variability; expand testing only to investigate a concrete unresolved risk. Compare live runs cautiously because source availability changes.

Evaluate report coverage, chain/relationship accuracy, original-source traceability for material claims, comparable metrics, analytical mechanisms, conflict handling, beginner readability, and unsupported material claims. Independently audit all headline conclusions and principal company comparisons, plus a sample of other facts against original evidence. Report denominator and method; automated self-verification is not ground truth. Use a blind A/B assessment where feasible and keep factual audit separate from editorial preference. User preference remains the eventual product validation, not something Claude can declare on their behalf.

Acceptance: no unresolved known critical/high software defects; requested workflow functional; no known unsupported central conclusion delivered as established fact; limits and failures honest; headline question produces an evidenced industry/participant map and useful economic explanation; new output improves the documented baseline on the stated rubric without relying on hardcoded case facts. If unmet, fix and rerun affected cases or clearly report the remaining limitation.

## 13. Clean-code requirements

- Fix root causes; preserve existing behavior outside intended changes.
- Keep changes localized to cohesive modules; avoid unrelated refactors and premature generic frameworks.
- Reuse current adapters, utilities, validation, logging, and tests before adding dependencies.
- Keep agent prompts/model decisions separate from deterministic state transitions, budget enforcement, calculations, persistence, and ID allocation.
- Prefer explicit types, small functions with clear ownership, and narrow interfaces. Avoid giant workflow nodes and unnecessary inheritance/factory layers.
- One authoritative definition for each schema, route, status, and budget rule. Do not duplicate routing logic in Studio.
- Validate at boundaries. Fail with useful errors; do not silently guess, swallow exceptions, fabricate evidence, or turn malformed output into empty success.
- Manage async cancellation, timeouts, client lifetimes, and concurrent writes explicitly.
- Preserve source provenance and checkpoint compatibility; no destructive database resets to make tests pass.
- Keep prompts versioned and readable; record concise observable decision rationales rather than hidden chain-of-thought.
- Document why a new module or dependency is needed. Choose names that describe domain responsibilities.
- Maintain formatting/lint quality with existing tools. Add type checking only if already present or clearly justified.
- Keep test output and logs concise in working context. Save full artifacts and inspect relevant excerpts.
- After each phase, update the implementation log with decisions, verification, review outcomes, and remaining work so a fresh session can resume without rereading every log.

## 14. Reusable Codex review prompt

Use the following text in a fresh Codex reviewer session, replacing the checkpoint fields with actual values. Provide this design document, repository access, the relevant diff, and test/evaluation artifacts. The reviewer should not rely solely on Claude's summary.

> You are the independent reviewer for checkpoint [C0/C1/C2/C3] of the industry research system upgrade. Review the actual repository and this design. Baseline: [actual commit]. Candidate: [actual commit or working diff]. Implementation summary and artifacts: [paths]. Requested model: [model]; record the actual model if exposed, otherwise state that it is unverified.
>
> Work read-only. Inspect affected code and callers. Run relevant non-mutating checks when helpful; do not edit code, contact services unnecessarily, or publish anything. For C0, review the implementation plan, contracts, dependency ordering, budgets, compatibility and testing before implementation. For C1, focus on provenance, typed records, deterministic merge, approval invalidation and checkpoint compatibility. For C2, focus on actual routing, independent evidence inspection, concurrency, cancellation, repeated side effects, context isolation, bounded retries, and honest completion. For C3, review the complete diff, regression evidence, Studio behavior, and actual report quality against the bare-question requirement.
>
> Prioritize reproducible defects, evidence integrity, maintainability, and report quality. Check whether the system truly discovers upstream/downstream companies and explains economics from a short request. Do not treat more agents, longer prose, more citations, or an internal 100% support score as proof of improvement. Do not propose speculative abstractions or unrelated refactors.
>
> Return findings ordered by severity, with file/location, concrete failure scenario, consequence, and minimal recommended remedy. Distinguish verified defects from hypotheses needing a test. Identify missing acceptance evidence. Finish with PASS, PASS WITH NONBLOCKING FINDINGS, or CHANGES REQUIRED and explain any gate failure. No findings is acceptable; state what was inspected and what remains unverified. Do not claim that this review establishes real-world report accuracy unless the relevant sources were actually checked.

## 15. Final handoff from Claude

Deliver a concise completion summary with:

1. Actual architecture and changed behavior, including any justified deviations from this brief.
2. Commit/branch and working-tree state; no claim of push/merge unless separately authorized.
3. Exact commands to run a new question, resume, inspect Studio, and run relevant checks.
4. Tests and end-to-end evaluation results with artifact paths and limitations.
5. Codex C0–C3 model/result records and disposition of findings; explicitly list pending reviews.
6. Old checkpoint compatibility and rollback instructions.
7. Baseline/new report comparison with evidence of improvement and remaining research weaknesses.
8. Deferred features: cross-question memory, scheduled updates, expanded delivery formats, and any evidence-backed parser/reranking follow-ups.

Start now with repository inspection and C0 preparation. Continue through the implemented, tested result without routine permission stops.
