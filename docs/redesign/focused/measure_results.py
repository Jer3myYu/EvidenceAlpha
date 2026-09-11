"""Measure preserved diagnostic traces only; never invoke or edit a run."""

import collections
import json
import pathlib

from evidencealpha import artifacts

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / "data/redesign/focused-diagnostic"


def encoded(value: object) -> int:
    """Count UTF-8 bytes in the application's unindented JSON encoding."""
    return len(json.dumps(value, ensure_ascii=False).encode())


def main() -> None:
    """Write derived request, retrieval, usage and omission measurements."""
    ledger = artifacts.read(
        ROOT / "docs/redesign/FOCUSED_DIAGNOSTIC_BUDGET.json"
    )
    parent = artifacts.read(pathlib.Path(ledger["parent"]))
    root = next((BASE / "results/A/stages/company").iterdir())
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text().splitlines()
    ]
    seen = set()
    retrieved = collections.Counter()
    repeated = 0
    result_bytes = text_bytes = identity_bytes = 0
    tool_rows = []
    for event in events:
        if event["kind"] != "tool":
            continue
        result = event["result"]
        items = result if isinstance(result, list) else [result]
        texts = identity = duplicates = 0
        for passage in items:
            if "text" not in passage:
                continue
            key = (
                passage["source_id"],
                passage.get("chunk_id"),
                passage["text"],
            )
            texts += len(passage["text"].encode())
            identity += encoded(
                {
                    k: passage[k]
                    for k in (
                        "source_id",
                        "title",
                        "issuer",
                        "url",
                        "identity_scope",
                    )
                }
            )
            if key in seen:
                repeated += 1
                duplicates += 1
            else:
                retrieved[passage["source_id"]] += 1
                seen.add(key)
        size = encoded(result)
        result_bytes += size
        text_bytes += texts
        identity_bytes += identity
        tool_rows.append(
            {
                "name": event["name"],
                "arguments": event["arguments"],
                "result_bytes": size,
                "original_text_bytes": texts,
                "identity_metadata_bytes": identity,
                "repeated_passages": duplicates,
                "seconds": event["seconds"],
            }
        )
    calls = []
    for call in sorted(root.glob("call-*")):
        prompt = json.loads((call / "request.txt").read_text())
        history = prompt["messages"][2:]
        calls.append(
            {
                "call": call.name,
                "request_bytes": (call / "request.txt").stat().st_size,
                "history_bytes": encoded(history),
                "tools_available": bool(prompt["tools"]),
                "complete": (call / "normalized.json").exists(),
                "raw_bytes": (call / "raw.jsonl").stat().st_size,
            }
        )
    handoff = artifacts.read(root / "handoff.json")
    handoff_counts = collections.Counter(
        p["source_id"] for p in handoff["passages"]
    )
    invocations = ledger["invocations"]
    usage = {
        "model_seconds": sum(
            x.get("seconds", x["reserved_seconds"]) for x in invocations
        ),
        "known_output_tokens": sum(
            x.get("observable_tokens") or 0 for x in invocations
        ),
        "separately_reported_reasoning_tokens": sum(
            x.get("usage", {}).get("reasoning_output_tokens", 0)
            for x in invocations
        ),
        "reasoning_overlap": "unknown; not added to output tokens",
        "known_input_tokens": sum(
            x.get("usage", {}).get("input_tokens", 0) for x in invocations
        ),
        "unknown_usage_calls": sum(
            x.get("observable_tokens") is None for x in invocations
        ),
    }
    artifacts.write(
        BASE / "measurements.json",
        {
            "case": "A",
            "status": "failed",
            "calls": calls,
            "tool_results": tool_rows,
            "usage": usage,
            "result_bytes": result_bytes,
            "original_text_bytes": text_bytes,
            "identity_metadata_bytes": identity_bytes,
            "remaining_json_bytes": result_bytes - text_bytes - identity_bytes,
            "repeated_passage_occurrences": repeated,
            "distinct_passages_by_source": dict(retrieved),
            "fallback_passages_by_source": dict(handoff_counts),
            "tools_seconds": sum(row["seconds"] for row in tool_rows),
            "historical_ledger_unchanged": artifacts.digest(
                pathlib.Path(ledger["parent"]).read_bytes()
            )
            == ledger["parent_hash"],
            "historical_plus_additive_model_seconds": sum(
                x.get("seconds", x["reserved_seconds"])
                for x in parent["invocations"]
            )
            + usage["model_seconds"],
            "historical_plus_additive_calls": len(parent["invocations"])
            + len(invocations),
        },
    )
    print(
        json.dumps(
            {
                "usage": usage,
                "tools": len(tool_rows),
                "distinct": dict(retrieved),
                "fallback": dict(handoff_counts),
                "repeated": repeated,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
