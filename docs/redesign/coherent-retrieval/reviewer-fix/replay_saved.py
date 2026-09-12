"""Replay saved recovery through normal orchestration; no neural/provider calls.

The one-claim inventory and completion response are fixture adaptations.
They are not new research, independent discovery or model-quality evidence.
"""

import argparse
import copy
import dataclasses
import json
import pathlib

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import execution
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import review
from evidencealpha import tools
from evidencealpha import workflow


class Replay(execution.SavedStages):
    """Use saved stages, exercising the actual reviewer completion loop."""

    def __init__(self, descriptor, settings, store, responses):
        super().__init__(descriptor, settings, store)
        self.provider = providers.FixtureProvider({"review": responses})
        self.review_runner = workflow.StageRunner(
            settings,
            self.provider,
            tools.EvidenceTools(store, settings, "fixed-corpus"),
        )

    def run(self, stage, role, portable, root, **kwargs):
        if stage == "review":
            self.used.append(stage)
            return self.review_runner.run(stage, role, portable, root, **kwargs)
        return super().run(stage, role, portable, root, **kwargs)


def hashes(root):
    """Fingerprint every historical artifact without rewriting it."""
    return {
        str(p): artifacts.digest(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def review_only(previous, root, settings, store):
    """Replay changed completion, reusing completed downstream work."""
    prior = artifacts.read(previous / "result.json")
    stage = previous / "run" / prior["stages"]["review"]["path"]
    portable = artifacts.read(stage / "input.json")["portable"]
    provider = providers.FixtureProvider(
        {"review": artifacts.read(previous / "fixtures/review-responses.json")}
    )
    runner = workflow.StageRunner(
        settings, provider, tools.EvidenceTools(store, settings, "fixed-corpus")
    )
    result = runner.run("review", "review", portable, root)
    assessment = review.assess(
        result["output"], portable["review_inventory"], store, portable["draft"]
    )
    folder = root / result["path"]
    contexts = sorted(folder.glob("call-*/context.json"))
    refs = [
        sorted(
            reading.reference(p)
            for p in documents.ungroup_passages(
                artifacts.read(path)["settled_evidence"]
            )
        )
        for path in contexts
    ]
    summary = {
        "validation": "Targeted saved-data review replay; fixture completion",
        "reused_downstream": str(previous / "ASSESSMENT.json"),
        "fixture_calls": len(provider.calls),
        "generative_calls": 0,
        "neural_calls": 0,
        "review_status": assessment["status"],
        "examination_items": assessment["items"],
        "request_bytes": [
            p.stat().st_size for p in sorted(folder.glob("call-*/request.txt"))
        ],
        "original_counts": [len(x) for x in refs],
        "original_references_unchanged": all(x == refs[0] for x in refs),
    }
    artifacts.write(root / "ASSESSMENT.json", summary)
    assert len(provider.calls) == 2
    assert summary["original_references_unchanged"]
    assert assessment["items"][0]["outcome"] == "contradicted"
    assert assessment["status"] == "partial"
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    """Exercise normal orchestration with identified saved outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved", type=pathlib.Path, required=True)
    parser.add_argument("--execution", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--review-only-from", type=pathlib.Path)
    args = parser.parse_args()
    saved, root = args.saved.resolve(), args.output.resolve()
    if root.exists():
        raise ValueError("Choose a new additive replay directory")
    before = hashes(saved)
    result = artifacts.read(saved / "command-result-continuation-2.json")
    spec = artifacts.read(args.execution)
    store = documents.SourceStore(pathlib.Path(spec["corpus"]))
    corpus_before = hashes(store.root)
    settings = dataclasses.replace(
        config.Settings(**spec["settings"]),
        tool_rounds=5,
        review_rounds=5,
        stage_seconds=900,
    )
    if args.review_only_from:
        review_only(args.review_only_from.resolve(), root, settings, store)
        assert before == hashes(saved) and corpus_before == hashes(store.root)
        return
    descriptor = {}
    for name, record in result["stages"].items():
        folder = saved / record["path"]
        descriptor[name] = {}
        for key, filename in (
            ("output", "output.json"),
            ("state", "context-state.json"),
            ("writing", "writing-context.json"),
        ):
            path = folder / filename
            if key == "writing" and not path.exists():
                path = sorted(folder.glob("call-*/context.json"))[-1]
            descriptor[name][key] = {
                "path": str(path),
                "sha256": artifacts.digest(path.read_bytes()),
            }
    initial = artifacts.read(
        pathlib.Path(descriptor["review"]["output"]["path"])
    )
    claim = {
        "id": "fixture-customer-absence",
        "claim": "没有具名客户",
        "location": "没有具名客户",
        "requirement_id": "company-7",
    }
    synthesis = artifacts.read(
        pathlib.Path(descriptor["synthesis"]["output"]["path"])
    )
    assert claim["location"] in synthesis["content"]
    synthesis["review_claims"] = [claim]
    adapted = root / "fixtures/synthesis.json"
    artifacts.write(adapted, synthesis)
    descriptor["synthesis"]["output"] = {
        "path": str(adapted),
        "sha256": artifacts.digest(adapted.read_bytes()),
    }
    completion = {
        "content": "Injected completion of the already supplied Luw finding; "
        "all other essential requirements remain unassessed.",
        "issues": copy.deepcopy(initial["issues"]),
        "inventory_assessment": "Fixture checks only the saved known omission. "
        "The other brief requirements remain unmapped, not certified.",
        "editorial_assessment": "No new editorial or pixel review.",
        "review_checks": [
            {
                "id": claim["id"],
                "checked_claim": claim["claim"],
                "status": "examined",
                "outcome": "contradicted",
                "explanation": initial["issues"][0]["evidence"],
                "remaining": "",
                "checks_performed": "Reused saved customer quotations.",
                "original_passages": initial["issues"][0]["original_passages"],
            }
        ],
    }
    artifacts.write(
        root / "fixtures/review-responses.json", [initial, completion]
    )
    artifacts.write(root / "descriptor.json", descriptor)
    runner = Replay(descriptor, settings, store, [initial, completion])
    clean_spec = {
        key: value
        for key, value in spec.items()
        if key not in ("recovery", "continuation", "industry_import", "tasks")
    }
    output = workflow.run(
        spec["brief"],
        settings,
        providers.FixtureProvider({}),
        [],
        root / "run",
        mode="fixed-corpus",
        source_corpus=store.root,
        execution=clean_spec,
        replay_runner=runner,
    )
    artifacts.write(root / "result.json", output)
    review_stage = output.get("stages", {}).get("review")
    summary = {
        "validation": "Saved-output plumbing replay with injected completion; "
        "no autonomous research or new model-quality evidence",
        "stages": runner.used,
        "fixture_reviewer_invocations": len(runner.provider.calls),
        "generative_calls": 0,
        "neural_calls": 0,
        "execution_status": output["execution_status"],
        "review_status": output["review_status"],
        "revision_resolution": output.get("revision_resolution"),
        "export_status": output["export_status"],
        "historical_files_unchanged": before == hashes(saved),
        "corpus_files_unchanged": corpus_before == hashes(store.root),
        "settings": dataclasses.asdict(settings),
    }
    if review_stage:
        folder = root / "run" / review_stage["path"]
        summary["initial_review_preserved"] = (
            folder / "initial-review.json"
        ).exists()
        requests = sorted(folder.glob("call-*/request.txt"))
        summary["request_bytes"] = [p.stat().st_size for p in requests]
        refs = {
            (r["source_id"], r["chunk_id"], r["quote"])
            for r in initial["issues"][0]["original_passages"]
        }
        preserved = {}
        for stage in ("review", "revision", "recheck"):
            record = output["stages"].get(stage)
            if not record:
                continue
            stage_root = root / "run" / record["path"]
            context_path = stage_root / "writing-context.json"
            if not context_path.exists():
                context_path = sorted(stage_root.glob("call-*/context.json"))[
                    -1
                ]
            context = artifacts.read(context_path)
            originals = documents.ungroup_passages(context["settled_evidence"])
            preserved[stage] = all(
                any(
                    p["source_id"] == sid and quote in p["text"]
                    for p in originals
                )
                for sid, _, quote in refs
            )
            summary[f"{stage}_original_count"] = len(originals)
            summary[f"{stage}_reference_hash"] = artifacts.digest(
                sorted(reading.reference(p) for p in originals)
            )
        summary["customer_originals_in_actual_payloads"] = preserved
    artifacts.write(root / "ASSESSMENT.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    assert (
        summary["historical_files_unchanged"]
        and summary["corpus_files_unchanged"]
    )
    assert output["execution_status"] == "complete", output.get("error")
    assert runner.used == [
        "plan",
        "research-0",
        "research-1",
        "followup",
        "synthesis",
        "review",
        "revision",
        "recheck",
    ]
    assert len(runner.provider.calls) == 2
    assert summary["initial_review_preserved"]
    assert output["review_status"] == "partial"
    assert output["revision_resolution"] == "complete"
    assert all(summary["customer_originals_in_actual_payloads"].values())
    assert output["export_status"] == "complete"


if __name__ == "__main__":
    main()
