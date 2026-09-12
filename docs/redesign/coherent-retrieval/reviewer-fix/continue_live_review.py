"""Use saved live findings for the two remaining calls; never repeat review."""

import argparse
import copy
import json
import os
import pathlib
import signal
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
from evidencealpha import tools
from evidencealpha import workflow


def main():
    """Continue under the original elapsed deadline and cumulative call count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    parent, root = args.parent.resolve(), args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    frozen = artifacts.read(parent / "execution-freeze.json")
    settings = config.Settings(**frozen["settings"])
    prior_path = parent / "execution-ledger.json"
    prior_hash = artifacts.digest(prior_path.read_bytes())
    prior = artifacts.read(prior_path)
    ledger = budget.ExecutionLedger(root / "execution-ledger.json", settings)
    ledger.initialize()
    with ledger.locked() as data:
        data["campaign_started"] = prior["campaign_started"]
        data["invocations"] = copy.deepcopy(prior["invocations"])
        data["parent"] = {
            "path": str(prior_path),
            "sha256": prior_hash,
            "inherited_calls": len(prior["invocations"]),
        }
    attempt = ledger.admit("full")
    assert attempt["deadline"] <= frozen["deadline"] + 0.01
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false",
    )
    store = documents.SourceStore(
        pathlib.Path(
            artifacts.read(
                pathlib.Path(
                    "docs/redesign/coherent-retrieval/"
                    "recovery-20260912/execution-continuation-2.json"
                )
            )["corpus"]
        )
    )
    source_hashes = {
        str(p): artifacts.digest(p.read_bytes())
        for p in store.root.rglob("*")
        if p.is_file()
    }
    evidence_tools = tools.EvidenceTools(
        store, settings, "fixed-corpus", ledger
    )
    runner = workflow.StageRunner(
        settings, providers.CodexProvider(), evidence_tools, ledger, attempt
    )
    records = {}
    result = {
        "status": "running",
        "stages": records,
        "parent": str(parent),
        "review_status": "partial",
    }
    reports = root / "reports"
    reports.mkdir()
    current = None

    def expired(signum, frame):
        del signum, frame
        providers.cancel_all()
        raise providers.ProviderCancelled(
            "Original acceptance deadline expired"
        )

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.001, attempt["deadline"] - time.time())
    )
    try:
        portable = artifacts.read(parent / "input.json")
        folder = next(parent.glob("stages/review/*"))
        raw_path = folder / "call-3/normalized.json"
        output = workflow.parse_output(
            artifacts.read(raw_path)["text"], "review"
        )
        artifacts.write(root / "saved-review.json", output)
        assessment = review.assess(
            output, portable["review_inventory"], store, portable["draft"]
        )
        artifacts.write(root / "REVIEW-ASSESSMENT.json", assessment)
        viewed = artifacts.read(folder / "writing-context.json")[
            "settled_evidence"
        ]
        evidence = handoff.originals(
            store, artifacts.read(folder / "context-state.json")["evidence"]
        )
        support = handoff.validate_quotes(
            output["issues"] + output["review_checks"], store
        )
        assembly = {
            "settled_evidence": evidence,
            "required_original_refs": sorted(
                reading.reference(p) for p in documents.ungroup_passages(viewed)
            ),
        }
        handoff.require_support(assembly, support)
        portable.update(assembly)
        material = [
            x
            for x in review.findings(output["issues"], [])
            if x["severity"] == "material"
        ]
        artifacts.write(
            root / "execution-freeze.json",
            {
                "code": artifacts.revision(),
                "settings": frozen["settings"],
                "parent_ledger_hash": prior_hash,
                "deadline": frozen["deadline"],
                "review_response_hash": artifacts.digest(raw_path.read_bytes()),
                "script_hash": artifacts.digest(
                    pathlib.Path(__file__).read_bytes()
                ),
                "correction": "Nonliteral locations remain unverified; retain "
                "valid source-backed findings without repeating reviewer.",
                "mandatory_original_count": len(
                    assembly["required_original_refs"]
                ),
            },
        )
        ledger.stage = "revision"
        records["revision"] = runner.run(
            "revision",
            "revision",
            workflow.revision_input(portable, {**output, "issues": material}),
            root,
            final_notes_only=True,
        )
        current = workflow._prepare_report(  # pylint: disable=protected-access
            records["revision"]["output"], reports, store, "revised.md"
        )
        focused = {
            **workflow.review_followup_input(portable),
            "draft": current.read_text(),
            "prior_issues": material,
            "required_scope": [
                {"id": f"finding-{i}", "question": x["location"]}
                for i, x in enumerate(material)
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
        result["remaining_findings"] = records["recheck"]["output"]["issues"]
        result["revision_resolution"] = (
            "complete"
            if (
                checked["status"] == "complete"
                and not any(
                    i["severity"] == "material"
                    for i in result["remaining_findings"]
                )
            )
            else "unverified_or_unresolved"
        )
        result["status"] = "complete"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        result.update(
            status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
    finally:
        providers.cancel_all()
        reranking.cancel_all()
        evidence_tools.retriever.close()
        if current and time.time() < frozen["deadline"]:
            artifacts.write(reports / "report.md", current.read_bytes())
            try:
                result["export"] = render.export(reports / "report.md")
            except (OSError, ValueError, RuntimeError) as exc:
                result["export"] = {"error": str(exc)}
        signal.setitimer(signal.ITIMER_REAL, 0)
        result["elapsed_from_original_start"] = (
            time.time() - prior["campaign_started"]
        )
        result["parent_ledger_unchanged"] = (
            artifacts.digest(prior_path.read_bytes()) == prior_hash
        )
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
