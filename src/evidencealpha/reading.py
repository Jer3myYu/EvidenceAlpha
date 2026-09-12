"""Bounded original reading windows without changing source/chunk bindings."""

from __future__ import annotations

import json
import dataclasses
import types
import re
import typing

from evidencealpha import artifacts
from evidencealpha import preparation

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


def _same_paragraph(
    previous: typing.Mapping, current: typing.Mapping, text: str
) -> bool:
    """Join adjacent PDF lines using indentation, spacing and column geometry.

    This is navigation context, not a certified semantic association. Original
    spans remain separate; ambiguous layout boundaries are not crossed.
    """
    a, b = previous.get("bbox"), current.get("bbox")
    if (
        previous["kind"] != "paragraph"
        or current["kind"] != "paragraph"
        or not a
        or not b
        or previous.get("page") != current.get("page")
    ):
        return False
    height = max(a[3] - a[1], b[3] - b[1])
    if height <= 0 or not 0 <= b[1] - a[3] <= height * 1.5:
        return False
    if (
        b[0] > a[0] + height * 0.5
        or abs(b[3] - b[1] - (a[3] - a[1])) > height * 0.2
    ):
        return False
    if abs(b[2] - a[2]) > max(height * 3, (a[2] - a[0]) * 0.2):
        return False
    if a[2] - a[0] < 0.7 * (b[2] - b[0]) and text[
        previous["start"] : previous["end"]
    ].rstrip().endswith(("。", ".", "！", "？")):
        return False
    return True


@dataclasses.dataclass(frozen=True)
class Index:
    """Immutable structural and chunk-binding indexes for one source version."""

    text: str
    original_path: str
    blocks: tuple
    units: tuple
    block_units: typing.Mapping[str, tuple[int, ...]]
    block_chunks: typing.Mapping[str, tuple]
    chunk_focus: typing.Mapping[str, int]
    groups: tuple
    group_for_block: typing.Mapping[str, int]

    def __init__(
        self,
        source: dict,
        text: str,
        limit: int,
        check: typing.Callable[[], None] = preparation.noop,
    ) -> None:
        blocks = []
        for block in source["blocks"]:
            check()
            blocks.append(
                types.MappingProxyType(
                    {
                        k: tuple(v) if isinstance(v, list) else v
                        for k, v in block.items()
                    }
                )
            )
        blocks.sort(
            key=lambda b: (
                b.get("page") or 0,
                (b.get("bbox") or [0, b["start"]])[1],
                (b.get("bbox") or [0])[0],
                b["start"],
            )
        )
        groups = []
        for block in blocks:
            check()
            previous = groups[-1][-1] if groups else None
            if previous is not None and _same_paragraph(previous, block, text):
                groups[-1].append(block)
            else:
                groups.append([block])
        group_for_block = {
            block["id"]: i for i, group in enumerate(groups) for block in group
        }
        units, block_units, block_chunks, focus = [], {}, {}, {}
        for block in blocks:
            check()
            indexes = []
            for a, z in _units(block, text, limit):
                check()
                indexes.append(len(units))
                units.append((block, a, z))
            block_units[block["id"]] = tuple(indexes)
        for chunk in source["chunks"]:
            check()
            focus[chunk["id"]] = chunk["spans"][-1]["start"]
            binding = (
                chunk["id"],
                json.dumps(chunk["spans"]),
                tuple((span["start"], span["end"]) for span in chunk["spans"]),
            )
            for block_id in chunk["block_ids"]:
                block_chunks.setdefault(block_id, []).append(binding)
        for name, value in {
            "groups": tuple(tuple(group) for group in groups),
            "group_for_block": types.MappingProxyType(group_for_block),
            "text": text,
            "original_path": source["original_path"],
            "blocks": tuple(blocks),
            "units": tuple(units),
            "block_units": types.MappingProxyType(block_units),
            "block_chunks": types.MappingProxyType(
                {key: tuple(value) for key, value in block_chunks.items()}
            ),
            "chunk_focus": types.MappingProxyType(focus),
        }.items():
            object.__setattr__(self, name, value)

    def bindings(
        self,
        block_id: str,
        start: int,
        end: int,
        check: typing.Callable[[], None] = preparation.noop,
    ) -> list[dict]:
        """Return fresh bindings without exposing cached mutable state."""
        found = []
        for chunk_id, encoded, spans in self.block_chunks.get(block_id, ()):
            check()
            if any(a < end and z > start for a, z in spans):
                found.append(
                    {"chunk_id": chunk_id, "spans": json.loads(encoded)}
                )
        return found


def window(
    store: documents.SourceStore,
    source_id: str,
    chunk_id: str | None = None,
    *,
    surrounding: int = 1,
    page: int | None = None,
    continuation: str | None = None,
    characters: int = 8000,
    check: typing.Callable[[], None] = preparation.noop,
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
    check()
    index = store.reading_index(source_id, characters, check)
    text, blocks, units = index.text, index.blocks, index.units
    identity = store.source_context(source_id)
    check()
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
        if chunk_id not in index.chunk_focus:
            raise ValueError("Unknown chunk; use exact chunk_id")
        # The last span remains the focal row of a repeated-header chunk.
        focus = index.chunk_focus[chunk_id]
    center = next(i for i, (_, a, z) in enumerate(units) if a <= focus < z)
    block = units[center][0]
    group = index.group_for_block[block["id"]]
    eligible_blocks = [
        b
        for g in index.groups[
            max(0, group - surrounding) : group + surrounding + 1
        ]
        for b in g
    ]
    if page is not None:
        eligible_blocks = [b for b in blocks if b.get("page") == page]
    eligible = sorted(
        i for b in eligible_blocks for i in index.block_units[b["id"]]
    )
    # Repeat the first original row; its header association remains unknown.
    required = (
        {i for b in index.groups[group] for i in index.block_units[b["id"]]}
        if block["kind"] == "paragraph"
        else {center}
    )
    if block["kind"] == "table":
        required.add(index.block_units[block["id"]][0])

    def size(indexes: set[int]) -> int:
        return sum(units[i][2] - units[i][1] for i in indexes)

    selected = set(required) if size(required) <= characters else set()
    if selected:
        for i in sorted(eligible, key=lambda i: (abs(i - center), i)):
            check()
            if size(selected | {i}) <= characters:
                selected.add(i)
    omitted = [i for i in eligible if i not in selected]
    passages = []
    for i in sorted(selected):
        b, a, z = units[i]
        check()
        bindings = index.bindings(b["id"], a, z, check)
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
    check()
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
            "path": str(store.root / source_id / index.original_path),
        },
    }
