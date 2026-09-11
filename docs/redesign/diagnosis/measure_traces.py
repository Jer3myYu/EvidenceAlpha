"""Measure preserved Stage 2 JSON traces without invoking any provider."""

import collections
import collections.abc
import datetime
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
DESTINATION = ROOT / "data/redesign/stage2-diagnosis/measurements.json"


def size(value: object) -> int:
    """Return UTF-8 bytes using the runtime's JSON serialization convention."""
    return len(json.dumps(value, ensure_ascii=False).encode())


def passages(value: object) -> collections.abc.Iterator[dict]:
    """Yield source-text objects embedded in a saved tool result."""
    if isinstance(value, dict):
        if "text" in value and ("source_id" in value or "source" in value):
            yield value
        else:
            for child in value.values():
                yield from passages(child)
    elif isinstance(value, list):
        for child in value:
            yield from passages(child)


def measure(folder: pathlib.Path) -> dict:
    """Measure prompt composition, tool payloads and repeated passages."""
    recorded = json.loads((folder / "input.json").read_text())
    event_file = folder / "events.jsonl"
    events = [json.loads(line) for line in event_file.read_text().splitlines()]
    calls = []
    tool_messages = {}
    components = collections.Counter()
    for request in sorted(
        folder.glob("call-*/request.txt"),
        key=lambda path: int(path.parent.name.split("-")[-1]),
    ):
        raw = request.read_bytes()
        prompt = json.loads(raw)
        parts = collections.Counter()
        for index, message in enumerate(prompt["messages"]):
            category = (
                "instructions"
                if index == 0
                else (
                    "portable_input"
                    if index == 1
                    else (
                        "assistant_history"
                        if message["role"] == "assistant"
                        else "tool_result_history"
                    )
                )
            )
            parts[category] += size(message)
            if category == "tool_result_history":
                tool_messages[message["content"]] = size(message)
        parts["framing_tools_turn_controls"] = len(raw) - sum(parts.values())
        components.update(parts)
        calls.append(
            {
                "path": str(request.relative_to(ROOT)),
                "bytes": len(raw),
                "components": dict(parts),
                "normalized_output_exists": (
                    request.parent / "normalized.json"
                ).exists(),
                "raw_bytes": (request.parent / "raw.jsonl").stat().st_size,
            }
        )
    tools = []
    seen = set()
    totals = collections.Counter()
    for line_number, event in enumerate(events, 1):
        if event["kind"] != "tool":
            continue
        result = event["result"]
        row = {
            "line": line_number,
            "tool": event["name"],
            "arguments": event["arguments"],
            "result_bytes": size(result),
            "seconds": event.get("seconds", 0),
            "trace_only_source_map_bytes": size(event.get("sources", {})),
            "passages": [],
            "text_bytes": 0,
            "snippet_text_bytes": (
                sum(
                    len(item.get("content", "").encode())
                    for item in result.get("results", [])
                )
                if event["name"] == "search_web"
                else 0
            ),
            "repeated_passage_text_bytes": 0,
        }
        for passage in passages(result):
            source = passage.get("source_id") or passage["source"]["id"]
            text = passage["text"]
            digest = hashlib.sha256(text.encode()).hexdigest()
            identity = (source, passage.get("chunk_id", "full"), digest)
            repeated = identity in seen
            seen.add(identity)
            row["text_bytes"] += len(text.encode())
            if repeated:
                row["repeated_passage_text_bytes"] += len(text.encode())
            row["passages"].append(
                {"source": source, "chunk": identity[1], "repeated": repeated}
            )
        row["nontext_and_json_bytes"] = (
            row["result_bytes"] - row["text_bytes"] - row["snippet_text_bytes"]
        )
        for key in (
            "result_bytes",
            "text_bytes",
            "snippet_text_bytes",
            "nontext_and_json_bytes",
            "repeated_passage_text_bytes",
            "trace_only_source_map_bytes",
        ):
            totals[key] += row[key]
        tools.append(row)
    results = [e for e in events if e["kind"] == "provider_result"]
    return {
        "path": str(folder.relative_to(ROOT)),
        "stage": recorded["stage"],
        "role": recorded["role"],
        "seconds_cap": recorded["seconds"],
        "settings": recorded["settings"],
        "instruction_sha256": hashlib.sha256(
            recorded["instructions"].encode()
        ).hexdigest(),
        "identity_guidance_present": "identifying aid"
        in recorded["instructions"],
        "identifying_passage_in_catalog": any(
            "identifying_passage" in s
            for s in recorded["portable"].get("sources", [])
        ),
        "portable_fields_bytes": {
            key: size(value) for key, value in recorded["portable"].items()
        },
        "calls": calls,
        "aggregate_prompt_components": dict(components),
        "unique_exact_tool_message_bytes": sum(tool_messages.values()),
        "retransmitted_tool_message_bytes": components["tool_result_history"]
        - sum(tool_messages.values()),
        "tool_totals": dict(totals),
        "tools": tools,
        "observed_input_tokens": sum(
            e["usage"].get("input_tokens", 0) for e in results
        ),
        "observed_cached_input_tokens": sum(
            e["usage"].get("cached_input_tokens", 0) for e in results
        ),
        "observed_output_tokens": sum(
            e["usage"].get("output_tokens", 0) for e in results
        ),
        "unknown_usage_calls": len(calls)
        - sum(e["usage"].get("output_tokens") is not None for e in results),
        "successful_provider_seconds": sum(e["seconds"] for e in results),
        "provider_events": results,
    }


def main() -> None:
    """Write deterministic measurements plus ledger-linked timeout evidence."""
    ledger_path = ROOT / "docs/redesign/RUN_BUDGET.json"
    ledger = json.loads(ledger_path.read_text())
    stages = []
    revisions = []
    for attempt in ledger["attempts"]:
        run = ROOT / "data/redesign/runs" / attempt["id"]
        for folder in sorted(run.glob("stages/*/*")):
            if (folder / "input.json").exists():
                measured = measure(folder)
                measured["attempt"] = attempt["id"]
                stages.append(measured)
        if attempt["kind"] == "full":
            invocations = [
                i
                for i in ledger["invocations"]
                if i["attempt"] == attempt["id"]
            ][-3:]
            first = invocations[0]
            expiry = datetime.datetime.fromisoformat(first["invoked"])
            expiry += datetime.timedelta(seconds=first["reserved_seconds"])
            revisions.append(
                {
                    "attempt": attempt["id"],
                    "invocations": invocations,
                    "wall_expiry_reconstructed_from_reservation": (
                        expiry.isoformat()
                    ),
                    "note": "Actual monotonic deadline was not persisted.",
                }
            )
    output = {
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "units": (
            "bytes=UTF-8; prompt components include message JSON escaping; "
            "tool nontext includes JSON syntax/escaping, not just metadata"
        ),
        "scope": (
            "All saved model stages in the exhausted campaign; "
            "no provider calls or corpus mutations"
        ),
        "stages": stages,
        "full_revision_timeouts": revisions,
    }
    DESTINATION.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
