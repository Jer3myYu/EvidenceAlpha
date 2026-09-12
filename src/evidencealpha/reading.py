"""Bounded original reading windows without changing source/chunk bindings."""

from __future__ import annotations

import json
import re
import typing

from evidencealpha import artifacts

if typing.TYPE_CHECKING:
    from evidencealpha import documents


def reference(passage: dict) -> str:
    """Identify original spans independently of arrival and annotations."""
    return artifacts.digest(
        {k: passage.get(k) for k in ("source_id", "version", "spans")}
    )


def _units(block: dict, text: str, limit: int) -> list[tuple[int, int]]:
    if block["kind"] != "table" and block["end"] - block["start"] <= limit:
        return [(block["start"], block["end"])]
    pattern = (
        r"[^\n]+" if block["kind"] == "table" else r"[^。！？.!?]+[。！？.!?]*"
    )
    return [
        (block["start"] + m.start(), block["start"] + m.end())
        for m in re.finditer(pattern, text[block["start"] : block["end"]])
    ]


def window(
    store: documents.SourceStore,
    source_id: str,
    chunk_id: str | None = None,
    *,
    surrounding: int = 1,
    page: int | None = None,
    continuation: str | None = None,
    characters: int = 8000,
) -> dict:
    """Read whole structural units, with version-bound continuation cursors.

    Associations in legacy PDF metadata are unknown, never certified headers.
    Oversized indivisible units are explicit omissions rather than truncations.
    """
    if (
        not isinstance(surrounding, int)
        or isinstance(surrounding, bool)
        or not 0 <= surrounding <= 2
    ):
        raise ValueError("surrounding must be 0..2")
    if sum(x is not None for x in (chunk_id, page, continuation)) != 1:
        raise ValueError("Choose exactly one chunk, page or continuation")
    original = store.open_source(source_id)
    source, text = original["source"], original["text"]
    identity = store.source_context(source_id)
    blocks = sorted(
        source["blocks"],
        key=lambda b: (
            b.get("page") or 0,
            (b.get("bbox") or [0, b["start"]])[1],
            (b.get("bbox") or [0])[0],
            b["start"],
        ),
    )
    units = [(b, a, z) for b in blocks for a, z in _units(b, text, characters)]
    if not units:
        raise ValueError("No readable structural units")
    cursor = None
    if continuation is not None:
        cursor = json.loads(continuation)
        if (
            cursor.get("source_id") != source_id
            or cursor.get("version") != identity["version"]
        ):
            raise ValueError("Continuation source/version mismatch")
        focus = cursor["offset"]
        if (
            not isinstance(focus, int)
            or isinstance(focus, bool)
            or not any(a == focus for _, a, _ in units)
        ):
            raise ValueError("Invalid continuation offset")
    elif page is not None:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("Page must be a positive integer")
        found = [a for b, a, _ in units if b.get("page") == page]
        if not found:
            raise ValueError("Unknown page")
        focus = found[0]
    else:
        chunk = next((c for c in source["chunks"] if c["id"] == chunk_id), None)
        if chunk is None:
            raise ValueError("Unknown chunk; use exact chunk_id")
        # The last span is the focal row when a chunk repeats its table header.
        focus = chunk["spans"][-1]["start"]
    center = next(i for i, (_, a, z) in enumerate(units) if a <= focus < z)
    block = units[center][0]
    bi = blocks.index(block)
    eligible_blocks = blocks[max(0, bi - surrounding) : bi + surrounding + 1]
    if page is not None:
        eligible_blocks = [b for b in blocks if b.get("page") == page]
    eligible = [i for i, (b, _, _) in enumerate(units) if b in eligible_blocks]
    # Repeat the first original row; its header association remains unknown.
    required = {center}
    if block["kind"] == "table":
        required.add(next(i for i, (b, _, _) in enumerate(units) if b == block))

    def size(indexes: set[int]) -> int:
        return sum(units[i][2] - units[i][1] for i in indexes)

    selected = set(required) if size(required) <= characters else set()
    if selected:
        for i in sorted(eligible, key=lambda i: (abs(i - center), i)):
            if size(selected | {i}) <= characters:
                selected.add(i)
    omitted = [i for i in eligible if i not in selected]
    passages = []
    for i in sorted(selected):
        b, a, z = units[i]
        bindings = [
            {"chunk_id": c["id"], "spans": c["spans"]}
            for c in source["chunks"]
            if b["id"] in c["block_ids"]
            and any(s["start"] < z and s["end"] > a for s in c["spans"])
        ]
        passages.append(
            {
                **identity,
                "text": text[a:z],
                "spans": [{"start": a, "end": z, "page": b.get("page")}],
                "block_ids": [b["id"]],
                "kind": b["kind"],
                "required_context": i in required and i != center,
                "chunk_refs": bindings,
            }
        )
    cursors = [
        json.dumps(
            {
                "source_id": source_id,
                "version": identity["version"],
                "offset": units[i][1],
            },
            sort_keys=True,
        )
        for i in omitted
    ]
    refs = [reference(p) for p in passages]
    focal_refs = [
        reference(p)
        for p in passages
        if any(s["start"] <= focus < s["end"] for s in p["spans"])
    ]
    return {
        "focus": focus,
        "focal_refs": focal_refs,
        "identity_text": " ".join(
            (identity.get(k) or {}).get("value", "")
            for k in ("title", "issuer")
        ),
        "id": artifacts.digest(refs),
        "passages": passages,
        "refs": refs,
        "status": (
            "oversized_unit"
            if not selected
            else "partial_parent" if omitted else "complete_window"
        ),
        "association": (
            "unknown"
            if any(
                b["kind"] == "table" or b.get("bbox") for b in eligible_blocks
            )
            else "structural"
        ),
        "continuations": cursors,
        "original_page": {
            "source_id": source_id,
            "page": block.get("page"),
            "path": str(store.root / source_id / source["original_path"]),
        },
    }
