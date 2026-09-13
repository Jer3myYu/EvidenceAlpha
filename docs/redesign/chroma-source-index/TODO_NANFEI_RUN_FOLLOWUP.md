# TODO: Nanfei live-run problems and follow-up

This record preserves observed problems from `data/campaigns/nanfei-20260912`.
A recovered report is not evidence of uninterrupted autonomous completion.
Historical failures and closed ledgers must remain unchanged.

| Problem | Action so far | Evidence / remaining work |
| --- | --- | --- |
| HTML ordinary-container text omitted | Fixed generic traversal (`8117e2c`) | HTML visible-body preservation checked on 14 captured sources. More layouts remain untested. |
| Nested layout tables interpreted as one huge financial table | Fixed structural classification (`36107da`) | Earlier extraction/index attempt preserved; final parser structural-4. General table extraction still needs representative validation. |
| Virtualenv path resolved to system Python | Keep configured interpreter path (`87c96f5`) | Focused import/interpreter test and subsequent live hybrid search. |
| Queued calls started after cancellation | Admission latch (`87c96f5`) | Deterministic check. Interrupted live attempt has unknown usage; broader live interruption behavior not certified. |
| Company researcher repeated financial searches without new support | Operator stopped loop; recovered partial notes; generic no-new-evidence guidance (`4c00dd6`) | **Not fully solved autonomously.** Investigate repeated query/context visibility and evidence novelty before claiming unattended convergence. |
| Missing financial, customer/supplier and product commercialization evidence | Retained scoped gaps | Do not infer document-wide absence or invent figures/relationships. Distinguish limited corpus coverage from a retrieval miss. |
| Source inventory duplication blocked synthesis | Metadata inheritance (`4eb3343`) | Successful synthesis after correction; all mandatory originals preserved. |
| Writer S-labels mapped to wrong exporter sources | Resolve explicit unique source hashes before canonical numbering (`f2d6797`) | Faulty draft retained in `reports-before-citation-correction`; focused alias test and corrected export. Check mixed/undeclared alias behavior on other reports. |
| Review payload too large | Lossless span tables and metadata compaction (`f2d6797`) | Saved replay 1,264 originals, zero omissions; live GPT-6 review subsequently ran. |
| Transport encoding prevented completed-stage checkpoint reuse | Normalize evidence representation while checking original input/output hashes (`c3eb281`) | Successful reuse of follow-up/synthesis. A later revision checkpoint mismatch remains under investigation; do not generalize this fix to all resume paths. |
| Revision request exceeded conservative capacity | Encode the plain-text request once, inherit duplicate source metadata (`16e0999`) | Actual revision completed. Replay preserved 1,327 mandatory originals; 246 optional omissions disclosed. |
| Recheck still exceeded capacity after revision | Remove duplicate preliminary follow-up narrative only from recheck (`521985e`) | Replay retains all 1,327 mandatory originals; live recheck has not yet completed. Keep actual source support, current findings and unresolved gaps. |
| Request sizing is conservative UTF-8 byte upper estimate | No capacity increase or silent truncation | Not a confirmed provider byte ceiling. Verified provider context metadata and reserved output remain authoritative; investigate a supported tokenizer/counting mechanism separately. |
| Legacy test module not fully passing | Failures saved in `single-encoding-check.log` | Ten fixtures lack now-required writer capacity, one assumes an older grouped representation, one assumes compression must cause omissions. Do not report a green suite; update fixtures without weakening factual/cancellation checks. |
| Corpus metadata lacks human-readable issuer/title fields | Original identity and URLs retained; writer provides names in prose | Links repeat “机构未核实 / 文档标题未核实”. Improve ingestion metadata from grounded source identity; do not fabricate issuer certification. |
| Source summary observability | Explicitly `not_generated` | Do not display navigation/title text as a generated or comprehensive source summary. |
| Studio completeness | Reference manifest links actual records | UI upgrade itself is not delivered by this campaign. Show stage inputs/tasks/answers, originals, retrieval, omissions, review routing, recovery and usage without another duplicate data store. |
| Reviewer missed/qualified source scope | Initial rubric identified UALink omission and domestic comparison gap | Targeted review, not exhaustive certification. Follow-up recovered historical competitor context; current-state comparisons remain qualified. |
| Delivery after failed continuation can fall back to an older draft | Older and revised artifacts both preserved | Confirm final selected report hash; export success must not imply acceptance. Never replace a better candidate silently. |
| Reproducibility and accounting | Additive continuations retain IDs and enclosing deadline | Deduplicate copied invocation IDs. Forced-interruption usage remains unknown; requested model identity often has no provider-confirmed actual identity. |

## Before any later reliability claim

- Reconcile the final run outcome with saved manifests, not conversational status.
- Resolve the remaining checkpoint/recheck and autonomous repetition concerns.
- Reuse this run as regression evidence; a future fresh run is a separate test.
- Keep report coverage, rubric readiness, execution completion and PDF checks separate.
- Preserve Chinese and English variants with source maps and visible limitations.

Final state will be appended after this campaign ends.

## Final Chinese review outcome (2026-09-13)

The live recheck subsequently completed: **ready with disclosed limitations**,
with both material findings resolved and no unresolved material issues. This
supersedes the earlier “not yet completed” recheck observation without erasing
its failed admissions. `manifest-final.json` is the authoritative Chinese result.

The revision checkpoint mismatch was caused by **shared figure metadata being
overwritten by the revised report**. Commit `c808a5a` binds figure manifests to
each report version; saved draft/revision reproduction passes, and normal
continuation then completed recheck/export. The diagnostic is preserved in
`run-finish/checkpoint-conflict-revision-fe8c6e2910b7.json`.

All 12 final Chinese PDF pages were inspected. Text preservation passed and
Chinese fonts are embedded. Remaining presentation TODOs: keep section/table
titles with the first table row (page 7→8); reduce excess whitespace and repeated
caption/source wording; reconcile generated September 13 report date with the
writer's September 12 report-date line (cutoff is consistently September 12);
replace generic source metadata labels with grounded readable titles.
PCIe Switch still needs a clearer first-use explanation, as the rechecker noted.
These are not hidden factual certification failures; they remain usability work.

The reviewer/rechecker performed targeted checks, not exhaustive verification.
English delivery is a faithful translation with offline fidelity/layout checks,
not another independent factual review. Its actual outcome is recorded separately.

Additional engineering limits to revisit: mandatory evidence can still exceed
actual context capacity on a larger or longer campaign; these transport fixes
are not unlimited-context support. Source/index validation and rendering are
also observable costs (one reviewer query used roughly 18 seconds for candidate
preparation and 114 seconds for scoring). Source count alone does not establish
coverage. Preserve failed/omitted outcomes rather than increasing top-K or
relaxing evidence checks to claim success.

## English presentation observations

The first English PDF kept the whole glossary list together and left a
heading-only page. The normal renderer now paginates complete list items and
preserves ordered-list numbering (focused deterministic check passed). Its
old every-five-character ASCII breaks also disrupted ordinary English words.
A first coarse replacement failed on a 70.14-point “Gongqingcheng” token in a
67.07-point content area; that failure is preserved in `english/final-export.json`.
The final correction measures words with the actual embedded font and adds
breaks only when they exceed cell width. The next export passed full text
preservation and produced 17 pages, all inspected. No neural call was repeated.

Minor table-title separation still occurs (e.g. English pages 2→3 and 3→4);
this remains a pagination TODO. The English submission copy removes duplicated
figure-number prefixes and has readable clickable source titles. The Chinese
historical reviewed PDF was not silently rerendered with these later changes.
