"""Bounded live review of a saved draft via the production StageRunner.

No prior review, correction notes, or assessment answers enter model inputs.
This is a review-only recovery driver, not fresh end-to-end research.
"""

import argparse
import dataclasses
import json
import os
import pathlib
import shutil
import signal
import sys
import time

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import handoff
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import render
from evidencealpha import reranking
from evidencealpha import review
from evidencealpha import stage_context
from evidencealpha import tools
from evidencealpha import workflow


def main():
    """Freeze and supervise one authorized reviewer acceptance window."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved", type=pathlib.Path, required=True)
    parser.add_argument("--settings-source", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    saved = args.saved.resolve()
    prior = artifacts.read(args.settings_source)
    settings = dataclasses.replace(
        config.Settings(**prior["settings"]),
        command_seconds=1800,
        command_calls=6,
        writing_calls_reserve=3,
        invocation_seconds=600,
        tool_rounds=6,
        review_rounds=6,
        final_writing_reserve_seconds=300,
    )
    ledger = budget.ExecutionLedger(root / "execution-ledger.json", settings)
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("full")
    started = time.monotonic()
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false",
    )
    records = {}
    result = {
        "status": "running",
        "stages": records,
        "validation": "Live reviewer recovery on preserved extraction",
    }
    store = documents.SourceStore(pathlib.Path(prior["corpus"]))
    source_files = [p for p in store.root.rglob("*") if p.is_file()]
    source_hashes = {
        str(p): artifacts.digest(p.read_bytes()) for p in source_files
    }
    evidence_tools = tools.EvidenceTools(
        store, settings, "fixed-corpus", ledger
    )
    runner = workflow.StageRunner(
        settings, providers.CodexProvider(), evidence_tools, ledger, attempt
    )

    def expired(signum, frame):
        del signum, frame
        providers.cancel_all()
        reranking.cancel_all()
        raise providers.ProviderCancelled("Review acceptance deadline expired")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.001, attempt["deadline"] - time.time())
    )
    reports = root / "reports"
    reports.mkdir()
    current = None
    try:
        saved_input = saved / "recovered-stages/synthesis/input.json"
        upstream = artifacts.read(saved_input)["portable"]
        evidence = handoff.originals(store, upstream["settled_evidence"])
        draft_path = saved / "reports/draft.md"
        draft = draft_path.read_text()
        current = reports / "draft.md"
        artifacts.write(current, draft)
        shutil.copytree(saved / "reports/draft", reports / "draft")
        sources = workflow._source_inputs(  # pylint: disable=protected-access
            store, [s["id"] for s in store.sources()]
        )
        original_figure = saved / "recovered-stages/synthesis/output.json"
        figure_specs = artifacts.read(original_figure).get("figures", [])
        portable = {
            "brief": prior["brief"],
            "draft": draft,
            "sources": sources,
            "review_mode": True,
            "review_inventory": review.inventory(
                {}, draft, prior["required_scope"]
            ),
            "settled_evidence": evidence,
            "required_original_refs": sorted(
                reading.reference(p)
                for p in documents.ungroup_passages(evidence)
            ),
            "upstream_omissions": {
                "instruction": "The saved evidence is a "
                "research selection, not the entire corpus. Search/open any "
                "authorized source. No previous gap verdicts supplied."
            },
            "source_map": artifacts.read(saved / "reports/source-map.json"),
            "figures": figure_specs,
            "visual_review_capability": "Figure data only; no rendered pixels.",
            "instruction": "This saved draft predates claim inventories. "
            "Identify material assertions from the whole draft and brief "
            "as part of this review; add review_claims and their checks. "
            "No prior reviewer findings or correction notes are supplied. "
            "Use focused source opens/searches as needed. At most four "
            "review invocations including completion/tool continuations; "
            "leave two calls for revision and recheck. Finish a candid "
            "bounded assessment, not an exhaustive certification claim.",
        }
        artifacts.write(root / "input.json", portable)
        frozen = {
            "code": artifacts.revision(),
            "settings": dataclasses.asdict(settings),
            "script_hash": artifacts.digest(
                pathlib.Path(__file__).read_bytes()
            ),
            "started": attempt["started"],
            "deadline": attempt["deadline"],
            "python": sys.executable,
            "sources": sources,
            "input_hash": artifacts.digest(portable),
            "saved_inputs": {
                str(p): artifacts.digest(p.read_bytes())
                for p in (saved_input, draft_path, original_figure)
            },
            "excluded": [
                "prior reviews",
                "supplemental findings",
                "followup " "correction notes",
                "evaluation annotations",
            ],
            "acceptance": [
                "documented material-claim examination",
                "grounded findings without invented objections",
                "honest unexamined scope",
                "original preservation",
                "scoped correction/recheck within limits",
            ],
        }
        artifacts.write(root / "execution-freeze.json", frozen)
        context = stage_context.StageContext(
            root / "preflight/state.json",
            {k: v for k, v in portable.items() if k != "settled_evidence"},
        )
        context.settle(evidence)
        prompts = pathlib.Path(workflow.__file__).parent / "prompts"
        context.request(
            (prompts / "common.md").read_text()
            + "\n"
            + (prompts / "review.md").read_text(),
            evidence_tools.definitions(),
            "evidence",
            6,
            settings.request_memory_bytes,
            settings.writer_context_tokens
            - settings.writer_output_tokens
            - settings.writer_transport_tokens,
        )
        ledger.stage, ledger.research = "review", True
        records["review"] = runner.run("review", "review", portable, root)
        output = records["review"]["output"]
        assessment = review.assess(
            output, portable["review_inventory"], store, draft
        )
        artifacts.write(root / "REVIEW-ASSESSMENT.json", assessment)
        result["review_status"] = assessment["status"]
        result["initial_factual_status"] = assessment["factual_status"]
        result["factual_status"] = assessment["factual_status"]
        extra = handoff.collect(root, records, store)
        evidence = handoff.merge(
            evidence,
            extra["settled_evidence"],
            handoff.validate_quotes(
                output["issues"] + output.get("review_checks", []), store
            ),
        )
        portable["settled_evidence"] = evidence
        portable["required_original_refs"] = sorted(
            reading.reference(p) for p in documents.ungroup_passages(evidence)
        )
        material = [
            i
            for i in review.findings(output["issues"], [])
            if i["severity"] == "material"
        ]
        if material:
            ledger.stage, ledger.research = "revision", False
            records["revision"] = runner.run(
                "revision",
                "revision",
                workflow.revision_input(
                    portable, {**output, "issues": material}
                ),
                root,
                final_notes_only=True,
            )
            current = (
                workflow._prepare_report(  # pylint: disable=protected-access
                    records["revision"]["output"], reports, store, "revised.md"
                )
            )
            focused = {
                **portable,
                "draft": current.read_text(),
                "prior_issues": material,
                "required_scope": [
                    {"id": f"finding-{i}", "question": issue["location"]}
                    for i, issue in enumerate(material)
                ],
            }
            ledger.stage = "recheck"
            records["recheck"] = runner.run(
                "recheck", "recheck", focused, root, final_notes_only=True
            )
            checked = handoff.scope(
                records["recheck"]["output"],
                focused["required_scope"],
                store,
                review=True,
            )
            artifacts.write(root / "RECHECK-ASSESSMENT.json", checked)
            remaining = [
                i
                for i in records["recheck"]["output"]["issues"]
                if i["severity"] == "material"
            ]
            result["revision_resolution"] = (
                "complete"
                if (checked["status"] == "complete" and not remaining)
                else "unverified_or_unresolved"
            )
            result["remaining_findings"] = remaining
            if result["revision_resolution"] == "complete":
                result["factual_status"] = review.resolution(
                    assessment, material, checked
                )["status"]
        result["status"] = "complete"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        providers.cancel_all()
        reranking.cancel_all()
        evidence_tools.retriever.close()
        if current and time.time() < attempt["deadline"]:
            artifacts.write(reports / "report.md", current.read_bytes())
            try:
                result["export"] = render.export(reports / "report.md")
            except (OSError, ValueError, RuntimeError) as exc:
                result["export"] = {"error": str(exc)}
        signal.setitimer(signal.ITIMER_REAL, 0)
        result["elapsed_seconds"] = time.monotonic() - started
        result["corpus_unchanged"] = all(
            artifacts.digest(pathlib.Path(p).read_bytes()) == h
            for p, h in source_hashes.items()
        )
        ledger.finish(attempt, result["status"])
        result["usage"] = artifacts.read(ledger.path)["invocations"]
        artifacts.write(root / "RESULT.json", result)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in ("stages", "usage")
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
