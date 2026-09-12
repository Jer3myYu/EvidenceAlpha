"""Inspect saved originals through the new selector without model execution."""

import argparse
import copy
import hashlib
import json
import pathlib
import random

from evidencealpha import artifacts
from evidencealpha import documents
from evidencealpha import reading
from evidencealpha import stage_context


def validate(baseline: pathlib.Path, output: pathlib.Path) -> dict:
    """Create new replay artifacts; never modify the frozen company run."""
    if output.exists():
        raise ValueError("Use a new validation directory")
    frozen = artifacts.read(baseline / "freeze.json")
    mismatches = [
        name
        for name, digest in frozen["files"].items()
        if hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() != digest
    ]
    if mismatches:
        raise ValueError("Frozen baseline changed")
    assessment = artifacts.read(baseline / "assessment.json")
    stage = baseline / "attempt/stages/company" / assessment["stage_id"]
    saved = artifacts.read(stage / "context-state.json")
    request = json.loads((stage / "call-5/request.txt").read_text())
    originals = documents.ungroup_passages(saved["evidence"])
    protected = {reading.reference(p) for p in assessment["omitted"]}
    # Assessment refs contain the same locator/version fields as originals.
    assert len(originals) == 103 and len(protected) == 7
    chosen_sets = []
    results = []
    for name in ("original", "reversed", "shuffled"):
        values = copy.deepcopy(originals)
        if name == "reversed":
            values.reverse()
        if name == "shuffled":
            random.Random(17).shuffle(values)
        state = stage_context.StageContext(
            output / name / "state.json", saved["task"]
        )
        qid = next(iter(state.data["questions"]))
        state.settle(documents.group_passages(values), qid)
        ids = [
            bid
            for bid, b in state.data["bundles"].items()
            if protected.intersection(b["refs"])
        ]
        # Assessor-only fixture mapping tests selection, not model judgment.
        state.update_coverage(
            [
                {
                    "question_id": qid,
                    "state": "partial",
                    "adequacy": "adequate",
                    "bundle_ids": ids,
                }
            ]
        )
        prompt, full = state.request(
            request["messages"][0]["content"],
            {},
            "final_notes",
            1,
            100000,
            64000,
        )
        full_passages = documents.ungroup_passages(full["settled_evidence"])
        assert {reading.reference(p) for p in full_passages} == {
            reading.reference(p) for p in originals
        }
        assert full["settled_evidence"]["omitted_reference_count"] == 0
        artifacts.write(output / name / "full-request.txt", prompt)
        artifacts.write(output / name / "full-view.json", full)
        full_size = artifacts.read(output / name / "request-size.json")
        # A single deliberately smaller budget; the real envelope is unchanged.
        small_budget = int(full_size["application_utf8_bytes"] * 0.8)
        small_prompt, small = state.request(
            request["messages"][0]["content"],
            {},
            "final_notes",
            1,
            small_budget,
            64000,
        )
        small_refs = {
            reading.reference(p)
            for p in documents.ungroup_passages(small["settled_evidence"])
        }
        assert protected <= small_refs
        assert small["settled_evidence"]["omitted_reference_count"] > 0
        assert len(documents.ungroup_passages(state.data["evidence"])) == 103
        chosen_sets.append(small_refs)
        artifacts.write(output / name / "bounded-request.txt", small_prompt)
        artifacts.write(output / name / "bounded-view.json", small)
        results.append(
            {
                "order": name,
                "full": len(full_passages),
                "full_size": full_size,
                "bounded_bytes": small_budget,
                "bounded_passages": len(small_refs),
                "protected_omissions_restored": len(protected),
            }
        )
    assert chosen_sets[0] == chosen_sets[1] == chosen_sets[2]
    result = {
        "baseline": frozen["candidate"],
        "frozen_files_unchanged": len(frozen["files"]),
        "orders": results,
        "arrival_invariant": True,
        "validation": "deterministic selection; no model or quality evaluation",
    }
    artifacts.write(output / "results.json", result)
    return result


def main() -> None:
    """Accept explicit existing baseline and new destination paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.baseline, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
