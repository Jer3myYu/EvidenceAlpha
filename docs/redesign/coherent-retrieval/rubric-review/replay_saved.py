"""Replay normal routing with saved outputs and explicitly injected judgments.

No autonomous research, provider calls or neural inference. The injected gap
and source opens are test inputs, never reviewer discovery or runtime answers.
"""

import argparse
import copy
import json
import pathlib

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import execution
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import review
from evidencealpha import workflow


def main() -> None:
    """Verify saved-evidence transport through a new post-review correction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    saved = pathlib.Path("data/redesign/fixed-corpus-integration")
    prior = artifacts.read(saved / "reviewer-fix-replay-20260912/result.json")
    descriptor = artifacts.read(
        saved / "reviewer-fix-replay-20260912/descriptor.json"
    )
    corpus = saved / "recovery-20260912/sources"
    store = documents.SourceStore(corpus.resolve())
    settings = config.Settings(**prior["settings"])
    before = {
        str(p): artifacts.digest(p.read_bytes())
        for p in corpus.rglob("*")
        if p.is_file()
    }
    before.update(
        {
            entry["path"]: artifacts.digest(
                pathlib.Path(entry["path"]).read_bytes()
            )
            for record in descriptor.values()
            for entry in record.values()
        }
    )

    def fixture(name: str, key: str, value: dict) -> None:
        path = root / "fixtures" / f"{name}-{key}.json"
        artifacts.write(path, value)
        descriptor[name][key] = {
            "path": str(path),
            "sha256": artifacts.digest(path.read_bytes()),
        }

    # This replay isolates post-review routing. Historical scope IDs are not
    # assertions about this fixture's deliberately empty pre-review scope.
    for name in ("research-0", "research-1"):
        output = artifacts.read(
            pathlib.Path(descriptor[name]["output"]["path"])
        )
        fixture(name, "output", {**output, "scope": []})
    descriptor["review-followup"] = copy.deepcopy(descriptor["followup"])
    recovered_output = artifacts.read(
        pathlib.Path(descriptor["review-followup"]["output"]["path"])
    )
    fixture("review-followup", "output", {**recovered_output, "scope": []})

    assessment = {
        "content": "Injected rubric assessment, not a new live review.",
        "rubric": [
            {
                "criterion": key,
                "rating": "Meets",
                "explanation": "Fixture judgment.",
            }
            for key in review.CRITERIA
        ],
        "decision": "ready",
        "review_scope": "Fixture customer relationship check only.",
        "review_limitations": "No new factual or rendered review.",
        "issues": [],
    }
    gap = {
        "severity": "material",
        "kind": "missing_evidence",
        "location": "路维客户关系",
        "evidence": "Coverage not established.",
        "impact": "The brief requests representative relationships.",
        "suggestion": "Investigate representative customer relationships.",
        "original_passages": [],
    }
    initial = {**assessment, "decision": "needs revision", "issues": [gap]}
    fixture("review", "output", initial)
    # Initial reviewer adds no assessor-selected evidence to the old draft.
    fixture("review", "state", {"evidence": {"sources": []}})
    fixture("review", "writing", {"settled_evidence": {"sources": []}})
    fixture(
        "recheck",
        "output",
        {
            **assessment,
            "decision": "ready with disclosed limitations",
            "resolutions": [
                {
                    "id": "finding-0",
                    "status": "resolved",
                    "explanation": "Injected saved-correction check.",
                }
            ],
        },
    )
    artifacts.write(root / "descriptor.json", descriptor)
    runner = execution.SavedStages(descriptor, settings, store)
    result = workflow.run(
        prior["brief"],
        settings,
        providers.FixtureProvider({}),
        [],
        root / "run",
        mode="fixed-corpus",
        source_corpus=store.root,
        replay_runner=runner,
    )
    artifacts.write(root / "RESULT.json", result)
    assert result["execution_status"] == "complete", result.get("error")
    assert runner.used == [
        "plan",
        "research-0",
        "research-1",
        "synthesis",
        "review",
        "review-followup",
        "revision",
        "recheck",
    ]
    contexts = {}
    for name in ("synthesis", "revision", "recheck", "review-followup"):
        folder = root / "run" / result["stages"][name]["path"]
        contexts[name] = artifacts.read(folder / "assembled-context.json")

    def refs(name: str) -> dict:
        return {
            reading.reference(p): p["text"]
            for p in documents.ungroup_passages(
                contexts[name]["settled_evidence"]
            )
        }

    new = set(refs("review-followup")) - set(refs("synthesis"))
    assert new, "Replay must add actual originals after the draft"
    assert all(
        refs("revision").get(k) == refs("review-followup")[k]
        and refs("recheck").get(k) == refs("review-followup")[k]
        for k in new
    )
    assert result["readiness"] == "ready with disclosed limitations"
    assert not result["unresolved_issues"]
    assert result["initial_review_issues"]
    assert all(
        artifacts.digest(pathlib.Path(p).read_bytes()) == digest
        for p, digest in before.items()
    )
    summary = {
        "basis": "Saved-output plumbing replay with injected rubric/gap/"
        "resolution; not autonomous discovery or quality acceptance",
        "stages": runner.used,
        "new_originals_preserved": len(new),
        "historical_files_unchanged": True,
        "generative_calls": 0,
        "neural_calls": 0,
        "readiness": result["readiness"],
        "export_status": result["export_status"],
    }
    artifacts.write(root / "ASSESSMENT.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
