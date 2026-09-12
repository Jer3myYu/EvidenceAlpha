"""Token-bounded embedding units mapped to unchanged original source spans."""

import re
import typing

from evidencealpha import artifacts
from evidencealpha import documents

VERSION = "structural-token-units-1"


def text_for(store: documents.SourceStore, unit: dict) -> str:
    """Assemble originals; added delimiters are not part of source text."""
    text = store.reading_index(unit["source_id"], 8000).text
    pieces = []
    for span in unit["spans"]:
        start, end = span["start"], span["end"]
        if not 0 <= start < end <= len(text):
            raise ValueError("Invalid embedding span")
        pieces.append(text[start:end])
    return "\n".join(pieces)


def build_units(
    store: documents.SourceStore,
    count: typing.Callable[[str], int],
    limit: int,
    check: typing.Callable[[], None],
) -> dict[str, dict]:
    """Pack same-section/page originals; split oversized elements without loss.

    Tables stay separate and repeat their first original row as navigation;
    that row's header association is explicitly unverified. Full source tables
    and multirow headers remain available to the existing reading tools.
    """
    units = {}
    for source in store.sources():
        index = store.reading_index(source["id"], 8000, check)
        text = index.text
        pending = []
        previous_key = None

        # Both helpers are consumed synchronously within this source loop.
        # pylint: disable=cell-var-from-loop
        def emit(spans, kind, fallback=False):
            if not spans:
                return
            first = spans[-1] if kind == "table" else spans[0]
            bound = index.bindings(
                first["block_id"], first["start"], first["end"], check
            )
            if not bound:
                raise ValueError("Embedding unit lacks original chunk binding")
            unit = {
                "source_id": source["id"],
                "chunk_id": bound[0]["chunk_id"],
                "spans": spans,
                "kind": kind,
                "fallback_split": fallback,
                "association": "unknown" if kind == "table" else "structural",
            }
            unit["text_hash"] = artifacts.digest(text_for(store, unit))
            if count(text_for(store, unit)) > limit:
                raise ValueError("Embedding unit exceeds capacity")
            units[artifacts.digest(unit)] = unit

        def split(span, prefix):
            """Prefer sentence boundaries, then lossless character splits."""
            a, z = span["start"], span["end"]
            sentence_ends = [
                a + m.end()
                for m in re.finditer(r"[。！？!?；;\n]|\.(?=\s|$)", text[a:z])
            ]
            while a < z:
                check()
                leading = "\n".join(text[s["start"] : s["end"]] for s in prefix)
                leading = leading + "\n" if leading else ""
                if count(leading + text[a:z]) <= limit:
                    yield {**span, "start": a}, False
                    return
                lo, hi = a, z
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if count(leading + text[a:mid]) <= limit:
                        lo = mid
                    else:
                        hi = mid - 1
                if lo == a:
                    raise ValueError(
                        "Header leaves no capacity for original row"
                    )
                ends = [end for end in sentence_ends if a < end <= lo]
                end = max(ends) if ends else lo
                yield {**span, "start": a, "end": end}, not bool(ends)
                a = end

        for group in index.groups:
            check()
            for block in group:
                kind = block["kind"]
                key = (block.get("section"), block.get("page"), kind)
                if key != previous_key or kind in ("table", "heading"):
                    emit(pending, "paragraph")
                    pending = []
                previous_key = key
                base = {"block_id": block["id"], "page": block.get("page")}
                if kind == "table":
                    rows = [
                        {
                            **base,
                            "start": block["start"] + m.start(),
                            "end": block["start"] + m.end(),
                        }
                        for m in re.finditer(
                            r"[^\n]+", text[block["start"] : block["end"]]
                        )
                    ]
                    if not rows:
                        continue
                    header = rows[0]
                    # Keep oversized first rows in lossless fragments.
                    # Full tables remain in SourceStore; association is unknown.
                    if count(text[header["start"] : header["end"]]) >= limit:
                        for row in rows:
                            for part, fallback in split(row, []):
                                emit([part], "table", fallback)
                    else:
                        emit([header], "table")
                        for row in rows[1:]:
                            for part, fallback in split(row, [header]):
                                emit([header, part], "table", fallback)
                    continue
                span = {**base, "start": block["start"], "end": block["end"]}
                for part, fallback in split(span, []):
                    trial = pending + [part]
                    joined = "\n".join(
                        text[s["start"] : s["end"]] for s in trial
                    )
                    if count(joined) > limit or fallback:
                        emit(pending, "paragraph")
                        pending = []
                    if fallback:
                        emit([part], kind, True)
                    else:
                        pending.append(part)
                if kind == "heading":
                    emit(pending, kind)
                    pending = []
        emit(pending, "paragraph")
    return units


def extend_reading(
    store: documents.SourceStore,
    unit: dict,
    view: dict,
    characters: int,
    check: typing.Callable[[], None],
) -> dict:
    """Retain every dense-match original in the existing reading view.

    Additional spans are exact evidence, not generated embedding summaries.
    Existing required paragraph context is never removed to make them fit.
    """
    from evidencealpha import reading  # pylint: disable=import-outside-toplevel

    if artifacts.digest(text_for(store, unit)) != unit["text_hash"]:
        raise ValueError("Dense-match source changed")
    index = store.reading_index(unit["source_id"], characters, check)
    identity = store.source_context(unit["source_id"])
    passages = list(view["passages"])
    focal = list(view["focal_refs"])
    for span in unit["spans"]:
        check()
        covered = [
            p
            for p in passages
            if any(
                s["start"] <= span["start"] and s["end"] >= span["end"]
                for s in p["spans"]
            )
        ]
        if covered:
            focal.extend(reading.reference(p) for p in covered)
            continue
        original_span = {k: span[k] for k in ("start", "end", "page")}
        passage = {
            **identity,
            "text": index.text[span["start"] : span["end"]],
            "spans": [original_span],
            "block_ids": [span["block_id"]],
            "kind": unit["kind"],
            "required_context": True,
            "chunk_refs": index.bindings(
                span["block_id"], span["start"], span["end"], check
            ),
        }
        passages.append(passage)
        focal.append(reading.reference(passage))
    if sum(len(p["text"]) for p in passages) > characters:
        raise ValueError("Dense original context exceeds reading capacity")
    passages.sort(key=lambda p: p["spans"][0]["start"])
    refs = [reading.reference(p) for p in passages]
    return {
        **view,
        "passages": passages,
        "refs": refs,
        "id": artifacts.digest(refs),
        "focal_refs": list(dict.fromkeys(focal)),
        "embedding_unit": artifacts.digest(unit),
        "dense_required_spans": unit["spans"],
    }
