"""Immutable source versions."""

import dataclasses
import copy
import pathlib
import re
import threading
import typing


import bs4
import pymupdf

from evidencealpha import artifacts
from evidencealpha import preparation
from evidencealpha import retrieval
from evidencealpha import reading

PARSER_VERSION = "structural-2-reading-order"
CHUNK_VERSION = "spans-1"


@dataclasses.dataclass(frozen=True)
class Passage:
    """An original Unicode span; generated context is never evidence text."""

    source_id: str
    chunk_id: str
    text: str
    spans: list[dict]
    section: str
    url: str
    generated_context: str | None = None


def group_passages(passages: list[dict]) -> dict:
    """Group passages by source identity without rewriting text."""
    groups = {}
    for passage in passages:
        source_id = passage["source_id"]
        if source_id not in groups:
            groups[source_id] = {
                key: passage.get(key)
                for key in (
                    "source_id",
                    "version",
                    "title",
                    "issuer",
                    "url",
                    "identity_scope",
                    "acquired_at",
                    "document_date",
                    "external_verification",
                )
            }
            groups[source_id]["passages"] = []
        elif groups[source_id].get("version") != passage.get("version"):
            raise ValueError("Conflicting source versions in one stage")
        groups[source_id]["passages"].append(
            {
                key: passage[key]
                for key in (
                    "chunk_id",
                    "text",
                    "spans",
                    "block_ids",
                    "chunk_refs",
                )
                if key in passage
            }
        )
    return {"sources": list(groups.values())}


def compact_passages(result: dict) -> dict:
    """Remove navigation geometry, preserving text and canonical locators.

    Durable evidence is never modified. Offsets, pages, chunk references and
    source versions remain available in the transport view.
    """
    result = copy.deepcopy(result)
    for source in result.get("sources", []):
        for passage in source["passages"]:
            passage.pop("block_ids", None)
            if "spans" in passage and all(
                set(span) == {"start", "end", "page"}
                for span in passage["spans"]
            ):
                passage["original_spans"] = [
                    [span["start"], span["end"], span["page"]]
                    for span in passage.pop("spans")
                ]
            for record in passage.get("chunk_refs", []):
                if "spans" in record:
                    record["spans"] = [
                        {
                            k: span[k]
                            for k in ("start", "end", "page")
                            if k in span
                        }
                        for span in record["spans"]
                    ]
            primary = passage.get("spans") or [
                {"start": x[0], "end": x[1], "page": x[2]}
                for x in passage.get("original_spans", [])
            ]
            if passage.get("chunk_refs") and all(
                x["spans"] == primary for x in passage["chunk_refs"]
            ):
                passage["chunk_ids"] = [
                    x["chunk_id"] for x in passage.pop("chunk_refs")
                ]
            if "chunk_refs" in passage:
                passage["chunk_bindings"] = [
                    [
                        entry["chunk_id"],
                        [
                            [
                                span.get("start"),
                                span.get("end"),
                                span.get("page"),
                            ]
                            for span in entry["spans"]
                        ],
                    ]
                    for entry in passage.pop("chunk_refs")
                ]
    return result


def ungroup_passages(result: dict) -> list[dict]:
    """Recover explicit source bindings from grouped tool or handoff data."""
    result_passages = []
    for source in result.get("sources", []):
        for stored in source["passages"]:
            passage = dict(stored)
            if "original_spans" in passage:
                passage["spans"] = [
                    {"start": span[0], "end": span[1], "page": span[2]}
                    for span in passage.pop("original_spans")
                ]
            if "chunk_ids" in passage:
                passage["chunk_refs"] = [
                    {
                        "chunk_id": chunk_id,
                        "spans": copy.deepcopy(passage["spans"]),
                    }
                    for chunk_id in passage.pop("chunk_ids")
                ]
            if "chunk_bindings" in passage:
                passage["chunk_refs"] = [
                    {
                        "chunk_id": chunk_id,
                        "spans": [
                            {"start": span[0], "end": span[1], "page": span[2]}
                            for span in spans
                        ],
                    }
                    for chunk_id, spans in passage.pop("chunk_bindings")
                ]
            result_passages.append(
                {
                    **{
                        key: value
                        for key, value in source.items()
                        if key != "passages"
                    },
                    **passage,
                }
            )
    return result_passages


def _blocks(data: bytes, suffix: str) -> tuple[list[dict], list[str]]:
    blocks = []
    warnings = []
    if suffix == ".pdf":
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page_number, page in enumerate(doc, 1):
                page_blocks = []
                tables = page.find_tables().tables
                for table in tables:
                    rows = [
                        " | ".join(str(cell or "") for cell in row)
                        for row in table.extract()
                    ]
                    page_blocks.append(
                        {
                            "text": "\n".join(rows),
                            "kind": "table",
                            "page": page_number,
                            "bbox": list(table.bbox),
                        }
                    )
                for block in page.get_text("blocks", sort=True):
                    if block[6] != 0 or any(
                        pymupdf.Rect(block[:4]).intersects(pymupdf.Rect(t.bbox))
                        for t in tables
                    ):
                        continue
                    page_blocks.append(
                        {
                            "text": block[4].strip(),
                            "kind": "paragraph",
                            "page": page_number,
                            "bbox": list(block[:4]),
                        }
                    )
                blocks.extend(
                    sorted(
                        page_blocks, key=lambda b: (b["bbox"][1], b["bbox"][0])
                    )
                )
        warnings.append(
            "Digital extraction only; heading/footnote associations "
            "are heuristic; no OCR"
        )
    elif suffix in (".html", ".htm"):
        soup = bs4.BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            if tag.find_parent(["table", "li"]):
                continue
            if tag.name == "table":
                rows = [
                    " | ".join(
                        cell.get_text(" ", strip=True)
                        for cell in row.find_all(["th", "td"])
                    )
                    for row in tag.find_all("tr")
                ]
                text = "\n".join(rows)
                kind = "table"
            else:
                text = tag.get_text(" ", strip=True)
                kind = "heading" if tag.name.startswith("h") else "paragraph"
            blocks.append({"text": text, "kind": kind})
        if not blocks:
            blocks.append(
                {"text": soup.get_text("\n", strip=True), "kind": "paragraph"}
            )
    else:
        text = data.decode("utf-8")
        for block in re.split(r"\n\s*\n", text):
            blocks.append(
                {
                    "text": block.strip(),
                    "kind": (
                        "heading"
                        if block.startswith("#")
                        else "table" if block.startswith("|") else "paragraph"
                    ),
                }
            )
    blocks = [b for b in blocks if b["text"]]
    if not blocks:
        raise ValueError("No extractable text; OCR or acquisition is required")
    return blocks, warnings


def _chunks(block: dict, limit: int) -> list[list[tuple[int, int]]]:
    start, end = block["start"], block["end"]
    if block["kind"] != "table":
        return [[(p, min(p + limit, end))] for p in range(start, end, limit)]
    lines = block["text"].splitlines(keepends=True)
    header = (start, start + len(lines[0].rstrip("\n")))
    if header[1] - header[0] >= limit:
        raise ValueError("Table header exceeds chunk limit; increase limit")
    rows, offset = [], start + len(lines[0])
    for line in lines[1:]:
        row_end = offset + len(line.rstrip("\n"))
        available = max(1, limit - (header[1] - header[0]) - 1)
        for part in range(offset, row_end, available):
            rows.append([header, (part, min(part + available, row_end))])
        offset += len(line)
    return rows or [[header]]


class SourceStore:
    """Content-addressed files; one manifest per source avoids lost updates."""

    def __init__(
        self, root: pathlib.Path, chunk_characters: int = 1600
    ) -> None:
        self.root = root
        self.chunk_characters = chunk_characters
        self._lock = threading.RLock()
        self._validated: dict[str, tuple] = {}
        self._reading_indexes: dict[tuple[str, int], tuple] = {}

    def _validated_source(self, source_id: str) -> tuple[dict, str]:
        folder = artifacts.contained(self.root, source_id)
        with self._lock:
            cached = self._validated.get(source_id)
            metadata = (folder / "source.json").stat()
            metadata_version = (
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            source = (
                cached[1]
                if cached and cached[0][0] == metadata_version
                else artifacts.read(folder / "source.json")
            )
            paths = [
                folder / name
                for name in (
                    "source.json",
                    source["text_path"],
                    source["original_path"],
                )
            ]
            version = tuple(
                (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                for s in (p.stat() for p in paths)
            )
            if cached and cached[0] == version:
                return cached[1], cached[2]
            # Preserve CRLF code points: spans/hash refer to captured text,
            # not Python's universal-newline translation.
            text = paths[1].read_bytes().decode("utf-8")
            if (
                artifacts.digest(text.encode()) != source["text_hash"]
                or artifacts.digest(paths[2].read_bytes()) != source["hash"]
            ):
                raise ValueError("Source version was changed in place")
            self._validated[source_id] = (version, source, text)
            return source, text

    def reading_index(
        self,
        source_id: str,
        characters: int,
        check: typing.Callable[[], None] = preparation.noop,
    ) -> reading.Index:
        """Reuse an immutable index only for a revalidated source version."""
        check()
        with self._lock:
            source, text = self._validated_source(source_id)
            check()
            key = (source_id, characters)
            cached = self._reading_indexes.get(key)
            if cached is None or cached[0] is not source:
                index = reading.Index(source, text, characters, check)
                check()
                self._reading_indexes[key] = (source, index)
            return self._reading_indexes[key][1]

    def iter_passages(
        self,
        source_id: str,
        check: typing.Callable[[], None] = preparation.noop,
    ) -> typing.Iterator[dict]:
        """Read one validated source snapshot without repeated chunk scans."""
        check()
        source, text = self._validated_source(source_id)
        context = self._context(artifacts.contained(self.root, source_id))
        check()
        for chunk in source["chunks"]:
            check()
            yield self._passage(source, text, chunk, context)
        check()

    def ingest(
        self,
        path: pathlib.Path,
        url: str | None = None,
        document_date: str | None = None,
    ) -> dict:
        """Capture original bytes and canonical Unicode text with exact
        spans.
        """
        data = path.read_bytes()
        identity = artifacts.digest(
            {
                "hash": artifacts.digest(data),
                "origin": url or path.name,
                "parser": PARSER_VERSION,
                "chunker": CHUNK_VERSION,
                "limit": self.chunk_characters,
            }
        )
        folder = self.root / identity
        with self._lock:
            if (folder / "source.json").exists():
                return artifacts.read(folder / "source.json")
            original = "original" + path.suffix.lower()
            artifacts.write(folder / original, data)
            try:
                blocks, warnings = _blocks(data, path.suffix.lower())
            except (ValueError, RuntimeError, UnicodeError) as exc:
                artifacts.write(
                    folder / "extraction-failure.json",
                    {
                        "url": url or path.name,
                        "hash": artifacts.digest(data),
                        "acquired_at": artifacts.now(),
                        "error": str(exc),
                        "original_path": original,
                    },
                )
                raise
            canonical, section = "", ""
            chunks = []
            for index, block in enumerate(blocks):
                if block["kind"] == "heading":
                    section = block["text"]
                block.update(
                    id=f"b{index}", start=len(canonical), section=section
                )
                canonical += block["text"]
                block["end"] = len(canonical)
                canonical += "\n\n"
                for spans in _chunks(block, self.chunk_characters):
                    chunks.append(
                        {
                            "id": f"c{len(chunks)}",
                            "block_ids": [block["id"]],
                            "section": section,
                            "spans": [
                                {
                                    "start": a,
                                    "end": b,
                                    "page": block.get("page"),
                                    "bbox": block.get("bbox"),
                                    "basis": (
                                        "canonical Unicode code points; "
                                        "[start,end)"
                                    ),
                                }
                                for a, b in spans
                            ],
                        }
                    )
            original = "original" + path.suffix.lower()
            source = {
                "id": identity,
                "url": url or path.name,
                "hash": artifacts.digest(data),
                "acquired_at": artifacts.now(),
                "original_path": original,
                "text_path": "text.txt",
                "text_hash": artifacts.digest(canonical.encode()),
                "parser_version": PARSER_VERSION,
                "chunker_version": CHUNK_VERSION,
                "document_date": document_date,
                "warnings": warnings,
                "blocks": blocks,
                "chunks": chunks,
                "index": {"kind": "lexical", "version": "unicode-bigram-1"},
            }
            artifacts.write(folder / original, data)
            artifacts.write(folder / "text.txt", canonical)
            artifacts.write(folder / "source.json", source)
            return source

    def sources(self) -> list[dict]:
        """List source versions deterministically."""
        return [
            artifacts.read(p) for p in sorted(self.root.glob("*/source.json"))
        ]

    def open_source(self, source_id: str, chunk_id: str | None = None) -> dict:
        """Reopen original passages and validate stored source/text versions."""
        folder = artifacts.contained(self.root, source_id)
        source, text = self._validated_source(source_id)
        if chunk_id is None:
            return {"source": copy.deepcopy(source), "text": text}
        chunk = next((c for c in source["chunks"] if c["id"] == chunk_id), None)
        if chunk is None:
            raise ValueError(
                "Unknown chunk; use the exact chunk_id returned by "
                "search_evidence (e.g. c30, not 30)."
            )
        return self._passage(source, text, chunk, self._context(folder))

    def source_context(self, source_id: str) -> dict:
        """Return compact identity; annotations must quote this original.

        Issuer identifies the document, never the subject of every statement.
        Unannotated documents expose an unknown issuer, not a guessed company.
        """
        source, _ = self._validated_source(source_id)
        path = self.root / source_id / "identity.json"
        identity = artifacts.read(path) if path.exists() else {}
        for field in ("title", "issuer"):
            entry = identity.get(field)
            if entry:
                original = self.open_source(source_id, entry["chunk_id"])
                if not entry["value"] or entry["value"] not in original["text"]:
                    raise ValueError(
                        "Identity annotation lacks original support"
                    )
        return {
            "source_id": source_id,
            "version": {
                key: source[key]
                for key in (
                    "hash",
                    "text_hash",
                    "parser_version",
                    "chunker_version",
                )
            },
            "title": identity.get("title"),
            "issuer": identity.get("issuer"),
            "url": source["url"],
            "identity_scope": "Document issuer; passage subjects may differ",
            "acquired_at": source["acquired_at"],
            "document_date": source.get("document_date"),
            "external_verification": (
                artifacts.read(self.root / source_id / "external.json")
                if (self.root / source_id / "external.json").exists()
                else None
            ),
        }

    def concise_passage(self, passage: dict) -> dict:
        """Present exact original text and locators without index metadata."""
        return {
            **self.source_context(passage["source_id"]),
            "chunk_id": passage["chunk_id"],
            "text": passage["text"],
            "spans": [
                {key: span[key] for key in ("start", "end", "page")}
                for span in passage["spans"]
            ],
        }

    def surrounding_passages(
        self,
        source_id: str,
        chunk_id: str,
        surrounding: int = 0,
        max_characters: int = 8000,
    ) -> list[dict]:
        """Open neighboring original blocks in document reading order.

        A nonzero window includes complete paragraph/table blocks, retaining
        every chunk's locator. Zero opens just the exact requested chunk.
        Oversized windows fail explicitly; no originals are truncated.
        """
        if (
            not isinstance(surrounding, int)
            or isinstance(surrounding, bool)
            or not 0 <= surrounding <= 2
        ):
            raise ValueError("surrounding must be an integer from 0 to 2")
        if surrounding == 0:
            return [self.concise_passage(self.open_source(source_id, chunk_id))]
        result = reading.window(
            self,
            source_id,
            chunk_id,
            surrounding=surrounding,
            characters=max_characters,
        )
        if result["status"] != "complete_window":
            raise ValueError(
                f"Window exceeds {max_characters} characters; narrow the window"
            )
        # Compatibility callers ask for exact old chunks. New runtime callers
        # use the same window directly, including continuations and block refs.
        ids = dict.fromkeys(
            ref["chunk_id"]
            for p in result["passages"]
            for ref in p["chunk_refs"]
        )
        return [
            self.concise_passage(self.open_source(source_id, cid))
            for cid in ids
        ]

    @staticmethod
    def _context(folder: pathlib.Path) -> str | None:
        path = folder / "context.json"
        return artifacts.read(path)["generated"] if path.exists() else None

    @staticmethod
    def _passage(
        source: dict, text: str, chunk: dict, context: str | None
    ) -> dict:
        for span in chunk["spans"]:
            if not 0 <= span["start"] < span["end"] <= len(text):
                raise ValueError("Invalid source span")
        return dataclasses.asdict(
            Passage(
                source["id"],
                chunk["id"],
                "\n".join(text[s["start"] : s["end"]] for s in chunk["spans"]),
                chunk["spans"],
                chunk["section"],
                source["url"],
                context,
            )
        )

    def add_context(
        self,
        source_id: str,
        generated: str,
        block_ids: list[str],
        model: dict,
        prompt_version: str,
    ) -> None:
        """Cache explicitly generated navigation separately from evidence."""
        source = self.open_source(source_id)["source"]
        if not set(block_ids).issubset({b["id"] for b in source["blocks"]}):
            raise ValueError("Context references unknown original blocks")
        key = artifacts.digest(
            [
                source["hash"],
                PARSER_VERSION,
                CHUNK_VERSION,
                prompt_version,
                model,
                block_ids,
            ]
        )
        path = self.root / source_id / "context.json"
        record = {
            "generated": generated,
            "block_ids": block_ids,
            "model": model,
            "prompt_version": prompt_version,
            "cache_key": key,
            "evidence": False,
        }
        if path.exists() and artifacts.read(path) != record:
            raise ValueError("Context is immutable; use a new versioned corpus")
        artifacts.write(path, record)

    def search_evidence(
        self,
        query: str,
        limit: int = 6,
        embedding_model: str | None = None,
        source_id: str | None = None,
    ) -> list[dict]:
        """Rank original passages lexically."""

        if embedding_model:
            raise ValueError(
                "Embedding fusion is not part of coherent retrieval"
            )
        return [
            item["passage"]
            for item in retrieval.candidates(self, query, source_id, limit)
        ]
