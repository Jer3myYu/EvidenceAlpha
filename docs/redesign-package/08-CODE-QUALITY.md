# Implementation and cleanup quality requirements

Applies to Stage 1 implementation and Stage 2 fixes. Supplements the design; does not add another full-run or model-review gate. Low-quota policy in 07 remains controlling for model usage.

## Keep the architecture small

- One active research workflow. Share orchestration, artifacts, retrieval and rendering across Claude/Codex; provider adapters handle only SDK-specific differences.
- One configuration definition with validated defaults and explicit overrides. Keep model IDs, reasoning effort, budgets, concurrency, paths and retrieval settings there. Store role prompts separately from orchestration logic.
- No industry/company names, report-specific source IDs, recorded-run IDs, absolute developer-machine paths or photomask-specific conditions in generic runtime logic. These belong in user inputs, fixtures or clearly named report templates.
- Fixed protocol values, mathematical constants and sensible defaults are legitimate constants; do not create a configuration framework for every literal.
- Use small typed records at external boundaries and readable functions with clear responsibilities. Prefer composition and direct code over deep inheritance, registries, dynamic dispatch or speculative plugin systems.
- Factor repeated behavior when it has the same semantics. Do not force unrelated SDK behaviors into a misleading universal abstraction; keep exceptions explicit inside adapters.

## Reliability without redundant machinery

- Separate I/O/provider calls from parsing, normalization and state decisions. Inject providers/tool interfaces so fixtures require no monkeypatching of application internals.
- Normalize provider events once. Keep raw provider output separately; do not repeatedly parse/stringify nested JSON through each stage.
- Catch errors at the appropriate boundary. Preserve useful context; no broad exception swallowing, fabricated successful outputs or silent model changes.
- One owner for retry policy and attempt accounting. Provider retries must be disabled where supported or made visible/accounted for; avoid hidden SDK retries multiplied by application retries.
- Close sessions, files and child processes on failure/cancellation. Use unique attempt directories and atomic final artifact writes where needed. Concurrent workers must not overwrite each other's work.
- Comments explain decisions and constraints. Avoid narration of obvious code, stale phase histories in active functions, and disabled code blocks.

## Cleanup means removal from the active project

- Remove obsolete imports, wrappers, entrypoints, flags, prompts, unused dependencies, duplicate helpers and retired task lists after confirming references.
- Keep prior tracked implementation recoverable in Git; preserve user documents, source corpora, run artifacts and unrelated working-tree changes.
- Do not leave an old and new implementation selected by a permanent migration flag when only the new path is required. Retain compatibility only for a named current caller; document its purpose and planned removal.
- Keep archived material outside active imports and default test collection. Update README, CLI help, install instructions and package exports consistently.
- Avoid broad dependency upgrades unrelated to the new path. Ensure explicitly used dependencies are declared rather than accidentally inherited from removed packages.

## Evidence before Stage 1 handoff

1. Inspect the diff and active import/caller graph for duplicate implementations, dead paths and duplicated settings.
2. Search the active runtime for fixture names, company names, machine-specific paths, TODO bypasses and copied legacy imports; classify matches rather than deleting legitimate examples.
3. Run formatting/lint and meaningful offline tests of active behavior, plus fixture report rendering and CLI/import checks. No test-count target or requirement to preserve obsolete architecture tests.
4. Cover actual boundaries: provider substitution, source locations, replay/version reuse, bounded review flow, cancellation and artifact preservation. Test expected behavior rather than mirroring every implementation branch.
5. Use a second-domain fixture to check generic behavior. Do not invent real-world facts for it.
6. Record a brief code-quality section in HANDOFF.md: what was removed, what remains shared, where configuration lives, intentional compatibility exceptions and any known technical debt.

Stage 2 retains these standards. Fix root causes at the appropriate layer, rerun relevant tests, and avoid adding an exception for each observed sentence or report. After two ineffective fixes in the same failure family, inspect the representation and inputs before another patch. Do not launch an additional audit panel solely to certify code style.
