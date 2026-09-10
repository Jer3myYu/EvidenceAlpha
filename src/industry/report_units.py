"""Stored report occurrences, validated references and dependency traversal."""

import hashlib
import json
import re
from typing import Any

from industry import records

_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def digest(value: Any) -> str:
    """Hash structured data without delimiter ambiguity."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def render(blocks: list[records.Block]) -> str:
    """Render the authoritative ordered occurrences exactly."""
    return "".join(block.prefix + block.text for block in blocks)


def index(sections: list[records.Section]) -> dict[str, records.Block]:
    """Index globally qualified occurrence IDs; reject duplicates."""
    blocks = [b for section in sections for b in section.blocks]
    indexed = {block.id: block for block in blocks}
    if len(indexed) != len(blocks):
        raise ValueError("duplicate report unit id")
    return indexed


def validate(sections: list[records.Section], claim_ids: set[str]) -> None:
    """Validate stored references, table ownership and acyclicity.

    This validates declarations, never their semantic completeness.

    Args:
      sections: The entire draft, including forward referenced sections.
      claim_ids: Claim identities available to this draft.

    Raises:
      ValueError: The stored graph or rendered projection is invalid.
    """
    blocks = index(sections)
    if len({s.id for s in sections}) != len(sections):
        raise ValueError("duplicate section id")
    for section in sections:
        if not section.blocks or render(section.blocks) != section.text:
            raise ValueError(f"{section.id}: missing or drifting report units")
        declared = {c for b in section.blocks for c in b.claim_ids}
        if declared != set(section.claim_ids):
            raise ValueError(f"{section.id}: inconsistent claim mapping")
        containers: dict[str, list[records.Block]] = {}
        for block in section.blocks:
            if block.prefix.strip() or not block.text.strip():
                raise ValueError("unit separator carries unreviewed text")
            table_kind = block.kind in ("row", "header", "rule")
            has_row = any(
                line.strip().startswith("|") for line in block.text.splitlines()
            )
            if table_kind != has_row or (table_kind and "\n" in block.text):
                raise ValueError("table structure hidden inside another unit")
            if block.kind == "rule" and not re.fullmatch(
                r"\|(?:\s*:?-+:?\s*\|)+", block.text.strip()
            ):
                raise ValueError("invalid table separator rule")
            if not block.id.startswith(section.id + ":"):
                raise ValueError("foreign unit owner")
            if block.sha256 != digest(block.text) or block.version < 1:
                raise ValueError("invalid unit content identity")
            if len(set(block.claim_ids)) != len(block.claim_ids):
                raise ValueError("duplicate claim reference")
            if not set(block.claim_ids) <= claim_ids:
                raise ValueError("unknown claim reference")
            deps = block.depends_on or []
            if len(deps) != len(set(deps)) or not set(deps) <= blocks.keys():
                raise ValueError("duplicate or unknown premise reference")
            if block.container_id:
                containers.setdefault(block.container_id, []).append(block)
            elif block.kind in ("row", "header", "rule"):
                raise ValueError("table unit without container")
        for members in containers.values():
            headers = [b for b in members if b.kind == "header"]
            rules = [b for b in members if b.kind == "rule"]
            rows = [b for b in members if b.kind == "row"]
            if len(headers) != 1 or len(rules) != 1 or not rows:
                raise ValueError("table needs one header, one rule and rows")
            positions = [section.blocks.index(b) for b in members]
            if positions != list(range(min(positions), max(positions) + 1)):
                raise ValueError("table container is not contiguous")
            if members.index(headers[0]) >= members.index(rules[0]):
                raise ValueError("table rule precedes header")
            if any(members.index(b) <= members.index(rules[0]) for b in rows):
                raise ValueError("data row precedes table rule")
            table_start = section.blocks.index(headers[0])
            if table_start:
                preceding = section.blocks[table_start - 1]
                separator = "\n\n" if preceding.kind == "row" else "\n"
                if not headers[0].prefix.endswith(separator):
                    raise ValueError("table has no distinct line boundary")
            table_end = section.blocks.index(rows[-1]) + 1
            if table_end < len(section.blocks):
                if not section.blocks[table_end].prefix.startswith("\n"):
                    raise ValueError("text is fused to the last table row")
            for member in members[members.index(headers[0]) + 1 :]:
                if member.prefix != "\n":
                    raise ValueError("table lines need exactly one newline")
            structural = {b.id for b in members if b.kind != "row"}
            for row in rows:
                if row.depends_on is not None and not structural <= set(
                    row.depends_on
                ):
                    raise ValueError("row omits header/rule/caption dependency")
    pending = set(blocks)
    settled: set[str] = set()
    while pending:
        ready = {
            key
            for key in pending
            if set(blocks[key].depends_on or []) <= settled
        }
        if not ready:
            raise ValueError("cyclic report premise references")
        settled.update(ready)
        pending.difference_update(ready)


def build(
    specs: list[Any],
    previous: list[records.Section],
    version: int,
    claim_ids: set[str],
) -> list[records.Section]:
    """Bind editor keys to stable IDs, stamp versions and validate a draft.

    Args:
      specs: Ordered section specifications from the editor.
      previous: The preceding draft, for stable versions.
      version: This draft's version.
      claim_ids: Available registry claim IDs.

    Returns:
      Sections containing the authoritative stored units.

    Raises:
      ValueError: A declaration, reference or projection is invalid.
    """
    old = index(previous)
    sections = []
    for spec in specs:
        if not _KEY.fullmatch(spec.id):
            raise ValueError("invalid section key")
        blocks = []
        for item in spec.blocks:
            if not _KEY.fullmatch(item.key):
                raise ValueError("invalid report unit key")
            key = f"{spec.id}:{item.key}"
            deps = (
                None
                if item.depends_on is None
                else [
                    ref if ":" in ref else f"{spec.id}:{ref}"
                    for ref in item.depends_on
                ]
            )
            block = records.Block(
                id=key,
                kind=item.kind,
                text=item.text,
                prefix=item.prefix,
                sha256=digest(item.text),
                claim_ids=item.claim_ids,
                container_id=item.container_id,
                depends_on=deps,
                version=version,
            )
            before = old.get(key)
            if before:
                fields = (
                    "kind",
                    "text",
                    "claim_ids",
                    "container_id",
                    "depends_on",
                )
                changed = any(
                    getattr(before, f) != getattr(block, f) for f in fields
                )
                block = block.model_copy(
                    update={"version": version if changed else before.version}
                )
            blocks.append(block)
        sections.append(
            records.Section(
                id=spec.id,
                title=spec.title,
                text=spec.text,
                blocks=blocks,
                claim_ids=list(
                    dict.fromkeys(c for b in blocks for c in b.claim_ids)
                ),
                review_version=version,
            )
        )
    validate(sections, claim_ids)
    return sections


def closure(blocks: dict[str, records.Block], seeds: set[str]) -> set[str]:
    """Return seeds and all explicitly declared reverse dependencies."""
    reached = set(seeds)
    while True:
        added = {
            key
            for key, block in blocks.items()
            if set(block.depends_on or []) & reached
        } - reached
        if not added:
            return reached
        reached.update(added)


def ancestors(blocks: dict[str, records.Block], seeds: set[str]) -> set[str]:
    """Return the explicit transitive premise scope, including seeds."""
    reached = set(seeds)
    pending = list(seeds)
    while pending:
        block = blocks.get(pending.pop())
        for key in (block.depends_on or []) if block else []:
            if key not in reached:
                reached.add(key)
                pending.append(key)
    return reached


def remove(
    section: records.Section, doomed: set[str], note: str
) -> records.Section:
    """Remove exact stored occurrences, keeping notes outside tables."""
    kept = []
    pending_note = False
    removed_container = None
    for block in section.blocks:
        if pending_note and block.container_id != removed_container:
            kept.append(
                records.Block(
                    id=f"{section.id}:removal_{len(kept)}",
                    kind="paragraph",
                    text=note,
                    prefix="\n",
                    sha256=digest(note),
                    depends_on=[],
                )
            )
            pending_note = False
        if block.id not in doomed:
            kept.append(block)
        elif block.container_id is not None:
            pending_note = True
            removed_container = block.container_id
        else:
            kept.append(
                block.model_copy(
                    update={
                        "text": note,
                        "sha256": digest(note),
                        "claim_ids": [],
                        "depends_on": [],
                        "version": block.version + 1,
                    }
                )
            )
    if pending_note:
        kept.append(
            records.Block(
                id=f"{section.id}:removal_{len(kept)}",
                kind="paragraph",
                text=note,
                prefix="\n",
                sha256=digest(note),
                depends_on=[],
            )
        )
    return section.model_copy(
        update={
            "blocks": kept,
            "text": render(kept),
            "claim_ids": list(
                dict.fromkeys(c for b in kept for c in b.claim_ids)
            ),
        }
    )
