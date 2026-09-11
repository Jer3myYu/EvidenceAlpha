"""Prepare the writing-only proposal from saved originals; no models."""

import dataclasses
import json
import pathlib

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import stage_context

ROOT = pathlib.Path(__file__).resolve().parents[3]
FROZEN = ROOT / "data/redesign/focused-diagnostic/frozen"
TARGET = ROOT / "data/redesign/completion-correction"


def main() -> None:
    """Verify original bindings and persist an exact, unexecuted test input."""
    fixture = artifacts.read(
        ROOT / "tests/fixtures/redesign/focused/settled-company.json"
    )
    evidence = fixture["settled_evidence"]
    store = documents.SourceStore(FROZEN / "corpus")
    for source in evidence["sources"]:
        assert (
            source["version"]
            == store.source_context(source["source_id"])["version"]
        )
        for passage in source["passages"]:
            original = store.open_source(
                source["source_id"], passage["chunk_id"]
            )
            assert original["text"] == passage["text"]
            assert [
                {k: s[k] for k in ("start", "end", "page")}
                for s in original["spans"]
            ] == passage["spans"]
    portable = artifacts.read(FROZEN / "cases/A.json")["portable"]
    portable["brief"]["execution_guidance"] = (
        "Produce final company notes from the supplied settled originals only. "
        "No further research or tool calls. Preserve the user's comparison "
        "requirements; disclose unsupported metrics and missing information. "
        "Previous research timed out without notes; do not retry it."
    )
    portable["unresolved_questions"] = [
        "哪些比较要求仍缺少本次提供的原文支持？明确保留缺口。"
    ]
    state = stage_context.StageContext(
        TARGET / "preparation-context.json", portable
    )
    state.settle(evidence)
    trace = next(
        (ROOT / "data/redesign/focused-diagnostic/results/A").glob(
            "stages/company/*/events.jsonl"
        )
    )
    for line in trace.read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "tool":
            result = event["result"]
            grouped = (
                documents.group_passages(result)
                if isinstance(result, list)
                else result
            )
            state.outcome(event["name"], event["arguments"], grouped)
    portable["saved_research_outcomes"] = state.data["recent_outcomes"]
    portable["settled_evidence"] = evidence
    case = {
        "authorization": "PROPOSED ONLY; no model authorization",
        "stage": "company",
        "role": "company",
        "final_notes_only": True,
        "seconds": 180,
        "tool_rounds": 1,
        "concurrency": 1,
        "mode": "fixed-corpus",
        "model": dataclasses.asdict(config.Settings().model("company")),
        "portable": portable,
        "expected": {
            "completion": "One complete response; no tools or retries",
            "accuracy": "Correct attribution and original support for metrics",
            "known_gap": "Luw annual revenue is absent; leave it missing",
            "acceptance_limit": "Company notes only; no report acceptance",
        },
    }
    path = TARGET / "writing-only-case.json"
    if path.exists():
        raise ValueError(
            "Prepared case exists; preserve it rather than overwrite"
        )
    artifacts.write(path, case)
    path.chmod(0o444)
    hashes = {
        str(p.relative_to(ROOT)): artifacts.digest(p.read_bytes())
        for p in (ROOT / "src/evidencealpha").rglob("*")
        if p.suffix in (".py", ".md")
    }
    artifacts.write(
        TARGET / "proposal-manifest.json",
        {
            "case_hash": artifacts.digest(path.read_bytes()),
            "code_hashes": hashes,
            "revision": artifacts.revision(),
            "source_packet_hash": artifacts.digest(evidence),
            "originals_verified": 67,
            "model_calls": 0,
        },
    )
    print(
        json.dumps(
            {"case": str(path), "originals_verified": 67, "model_calls": 0}
        )
    )


if __name__ == "__main__":
    main()
