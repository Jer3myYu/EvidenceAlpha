# Authorized recovery admission

Base: 1ad8ea9. New two-hour/12-call additive execution; no inherited invocation charges, no cumulative output-token stop, one provider/local reranker worker, 900s provider watchdog, existing 8 GiB/four-thread reranker and 300s/search watchdog. Existing model/dependencies/corpus only. Closed acceptance ledger and failed outcome remain unchanged.

Checkpoint descriptor in execution.json freezes every file of completed plan, industry, company and synthesis stages, plus parent manifest hash. Normal workflow imports only those stages into a new run, validates source inventory/version, exact original spans/text, brief and research task scope, recalculates coverage, then follows up and reviews the saved draft. It does not import historical coverage decisions or ledgers. Prior source-check finding is explicit supplemental input, not autonomous discovery. Revision/recheck receive the same finding contract.

Narrow integration delta from base: explicit hash-checked recovery import and supplemental/current-gap inputs to follow-up/review. Research navigation labels for inherited mandatory originals remain on disk rather than being repeated in later requests; reviewers likewise receive originals/locators/reading limitations and review scope, without redundant research adequacy bookkeeping. No original text, source/version, span, technical/unit qualifier or required support is removed. New evidence can still create active navigation bundles. This is a capacity correction, not a factual-quality pass.

Provider capacity is recorded from installed model metadata in CAPACITY.json: 272000 context, 95% effective, 258400 available; reserve 12000 output +4096 framing, application conservative UTF8 upper estimate <=242304, distinct 16 MiB memory bound. Provider-owned overhead remains partly unobservable; native provider limits still apply. No larger experimental window is used. Exact request/schema is measured before every live invocation. In-flight output is observable only after completion; no fabricated exact output stop is claimed.

Preflight directories under data/redesign/fixed-corpus-integration/recovery-preflight*-20260912 preserve both the initially rejected review request assembly and corrected assembly. These are offline boundary checks, not reviewer calls. All 814 inherited originals remain present. A real follow-up may add evidence; actual later request admission, not this initial estimate, determines whether it fits.

Normal command (from this worktree; output must be new):

```bash
PYTHONPATH=src /home/cobot/cobot_storage/webproject/EvidenceAlpha-coherent-retrieval/data/redesign/coherent-retrieval/campaign-20260912T005532Z/preparation/.venv/bin/python -m evidencealpha fixed-corpus --execution docs/redesign/coherent-retrieval/recovery-20260912/execution.json --output data/redesign/fixed-corpus-integration/recovery-20260912
```

This is recovery from saved stages, never an uninterrupted fresh run. No benchmark or successful research restart; no new models, paid fallback, external acquisition, push or merge.
