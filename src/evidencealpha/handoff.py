"""Original-preserving stage assembly and explicit, provisional scope."""

import copy
import json
import pathlib
import shutil

from evidencealpha import artifacts
from evidencealpha import documents
from evidencealpha import reading


def originals(store: documents.SourceStore, evidence: dict) -> dict:
    """Check exact source bindings; compact only transport metadata."""
    checked = []
    sources = {}
    for passage in documents.ungroup_passages(evidence):
        sid = passage["source_id"]
        if sid not in sources:
            sources[sid] = (store.open_source(sid), store.source_context(sid))
        source, identity = sources[sid]
        if passage.get("version") and passage["version"] != identity["version"]:
            raise ValueError("Handoff source version mismatch")
        spans = passage["spans"]
        segments = [source["text"][s["start"] : s["end"]] for s in spans]
        if not spans or passage["text"] not in (
            "".join(segments),
            "\n".join(segments),
        ):
            raise ValueError("Handoff original text differs at its spans")
        for span in spans:
            if not 0 <= span["start"] < span["end"] <= len(source["text"]):
                raise ValueError("Handoff span outside source")
        checked.append({**identity, **passage, "version": identity["version"]})
    return documents.compact_passages(documents.group_passages(checked))


def merge(*evidence: dict) -> dict:
    """Union by canonical original reference; reject conflicting text."""
    by_ref = {}
    blocks = {}
    for group in evidence:
        for block in group.get("reading_blocks", []):
            blocks[artifacts.digest(block)] = block
        for passage in documents.ungroup_passages(group):
            ref = reading.reference(passage)
            if ref in by_ref and by_ref[ref]["text"] != passage["text"]:
                raise ValueError("Conflicting originals at one reference")
            by_ref[ref] = passage
    return {
        **documents.compact_passages(
            documents.group_passages(list(by_ref.values()))
        ),
        "reading_blocks": list(blocks.values()),
    }


def collect(
    root: pathlib.Path, records: dict, store: documents.SourceStore
) -> dict:
    """Collect originals and explicit upstream selection omissions."""
    evidence = {"sources": []}
    omissions = {}
    lineage = {}
    searches = []
    required_refs = set()
    for name, record in records.items():
        folder = root / record["path"]
        state_path = folder / "context-state.json"
        if not state_path.exists():
            omissions[name] = {"reason": "No saved original evidence"}
            continue
        state = artifacts.read(state_path)
        events = folder / "events.jsonl"
        if events.exists():
            for line in events.read_text().splitlines():
                event = json.loads(line)
                if event.get("name") == "search_evidence":
                    searches.append(
                        {
                            "stage": name,
                            "arguments": event["arguments"],
                            "returned": bool(
                                event.get("result", {}).get("sources")
                            ),
                        }
                    )
        checked = originals(store, state["evidence"])
        checked["reading_blocks"] = [
            {
                "refs": b["refs"],
                "status": b.get("structure", "unassessed"),
                "continuations": b.get("continuations", []),
                "association": b.get("association", "unknown"),
            }
            for b in state.get("bundles", {}).values()
        ]
        evidence = merge(evidence, checked)
        writing = folder / "writing-context.json"
        view = artifacts.read(writing) if writing.exists() else {}
        selected = view.get("settled_evidence", {})
        required_refs.update(
            reading.reference(p) for p in documents.ungroup_passages(selected)
        )
        omissions[name] = {
            "count": selected.get("omitted_reference_count"),
            "manifest": selected.get("selection_manifest"),
            "stop_reason": state.get("stop_reason"),
            "questions": state.get("questions", {}),
        }
        lineage[name] = {
            "state": str(state_path),
            "state_hash": artifacts.digest(state_path.read_bytes()),
            "output_hash": record.get("output_hash"),
            "writing_hash": (
                artifacts.digest(writing.read_bytes())
                if writing.exists()
                else None
            ),
        }
    return {
        "settled_evidence": evidence,
        "required_original_refs": sorted(required_refs),
        "upstream_omissions": omissions,
        "lineage": lineage,
        "prior_searches": searches,
    }


def import_bundle(path: pathlib.Path, store: documents.SourceStore) -> dict:
    """Load a versioned, hash-bound notes/originals/citation-map package."""
    bundle = artifacts.read(path)
    if bundle["schema_version"] != 1:
        raise ValueError("Unknown evidence import schema")
    values = {}
    for name in ("notes", "evidence", "citation_map"):
        entry = bundle[name]
        file = (path.parent / entry["path"]).resolve()
        if artifacts.digest(file.read_bytes()) != entry["sha256"]:
            raise ValueError("Evidence import hash mismatch")
        values[name] = (
            file.read_text() if name == "notes" else artifacts.read(file)
        )
    citation_evidence = documents.group_passages(
        [
            p
            for entry in values["citation_map"]
            for p in entry.get("original_passages", [])
        ]
    )
    values["evidence"] = merge(
        originals(store, values["evidence"]),
        originals(store, citation_evidence),
    )
    values["citation_map"] = [
        {
            **{k: v for k, v in entry.items() if k != "original_passages"},
            "original_locations": [
                {"source_id": p["source_id"], "chunk_id": p["chunk_id"]}
                for p in entry.get("original_passages", [])
            ],
        }
        for entry in values["citation_map"]
    ]
    values["provenance"] = {
        "manifest": str(path),
        "hash": artifacts.digest(path.read_bytes()),
    }
    return values


def validate_quotes(items: list[dict], store: documents.SourceStore) -> dict:
    """Check quotation references, without certifying interpretation."""
    passages = []
    for item in items:
        for ref in item.get("original_passages", []):
            passage = store.open_source(ref["source_id"], ref["chunk_id"])
            if not ref.get("quote") or ref["quote"] not in passage["text"]:
                raise ValueError("Scope/finding quote not in its original")
            passages.append(store.concise_passage(passage))
    return documents.group_passages(passages)


def scope(
    output: dict,
    required: list[dict],
    store: documents.SourceStore,
    review: bool = False,
) -> dict:
    """Assess scope separately from issues; missing labels stay open."""
    entries = output.get("scope", [])
    if not isinstance(entries, list):
        raise ValueError("Scope must be a list")
    by_id = {}
    for item in entries:
        if item["id"] in by_id or item["id"] not in {r["id"] for r in required}:
            raise ValueError("Unknown or duplicate scope id")
        by_id[item["id"]] = item
    validate_quotes(entries, store)
    accepted = {"examined"} if review else {"supported"}
    result = []
    for item in required:
        claim = by_id.get(item["id"], {})
        status = claim.get("status", "unexamined" if review else "unresolved")
        if status in ("supported", "examined") and not claim.get(
            "original_passages"
        ):
            status = "unexamined" if review else "unresolved"
        if not claim.get("explanation"):
            status = "unexamined" if review else "unresolved"
        result.append({**item, **claim, "status": status})
    return {
        "status": (
            "complete"
            if result and all(r["status"] in accepted for r in result)
            else "partial"
        ),
        "items": result,
        "provisional": True,
        "limitation": (
            "References checked; model coverage is not factual "
            "certification. Undisclosed is an attributed corpus "
            "limitation, not proof of absence; it remains an open gap."
        ),
    }


def merge_scope(initial: dict, followup: dict) -> dict:
    """Keep the initial outcome intact and overlay only explicit recovery."""
    result = copy.deepcopy(initial)
    recovered = {
        x["id"]: x for x in followup["items"] if x["status"] in ("supported",)
    }
    result["items"] = [recovered.get(x["id"], x) for x in result["items"]]
    result["status"] = (
        "complete"
        if result["items"]
        and all(x["status"] in ("supported",) for x in result["items"])
        else "partial"
    )
    return result


def require_support(
    assembly: dict, support: dict, refs: list[str] | None = None
) -> None:
    """Carry newly examined originals as mandatory downstream support."""
    assembly["settled_evidence"] = merge(assembly["settled_evidence"], support)
    incoming = (
        refs
        if refs is not None
        else [reading.reference(p) for p in documents.ungroup_passages(support)]
    )
    assembly["required_original_refs"] = sorted(
        set(assembly.get("required_original_refs", []) + incoming)
    )


def recover_stages(
    descriptor: dict,
    root: pathlib.Path,
    brief: dict,
    store: documents.SourceStore,
) -> dict:
    """Import explicit completed checkpoints into a new run, never ledgers."""
    old_root = pathlib.Path(descriptor["root"]).resolve()
    manifest_path = artifacts.contained(old_root, descriptor["manifest"])
    if artifacts.digest(manifest_path.read_bytes()) != descriptor["sha256"]:
        raise ValueError("Recovery manifest changed")
    old = artifacts.read(manifest_path)
    if old["brief"] != brief:
        raise ValueError("Recovery brief changed")
    if {s["id"]: s["hash"] for s in store.sources()} != {
        s["id"]: s["hash"]
        for s in documents.SourceStore(old_root / "sources").sources()
    }:
        raise ValueError("Recovery source inventory/version changed")
    result = {}
    for name, files in descriptor["stages"].items():
        if name not in ("plan", "synthesis") and not name.startswith(
            "research-"
        ):
            raise ValueError(
                "Only completed planning/research/draft can recover"
            )
        record = old["stages"][name]
        folder = artifacts.contained(old_root, record["path"])
        if (
            not {
                "input.json",
                "output.json",
                "context-state.json",
                "writing-context.json",
            }
            <= files.keys()
        ):
            raise ValueError("Incomplete recovery checkpoint")
        for filename, digest in files.items():
            if (
                artifacts.digest(
                    artifacts.contained(folder, filename).read_bytes()
                )
                != digest
            ):
                raise ValueError("Recovery checkpoint changed")
        if (
            artifacts.digest(artifacts.read(folder / "output.json"))
            != record["output_hash"]
        ):
            raise ValueError("Recovery output hash mismatch")
        originals(
            store, artifacts.read(folder / "context-state.json")["evidence"]
        )
        target = root / "recovered-stages" / name
        shutil.copytree(folder, target)
        result[name] = {
            **record,
            "path": str(target.relative_to(root)),
            "recovery_origin": str(folder),
        }
    artifacts.write(root / "recovery-provenance.json", descriptor)
    return result
