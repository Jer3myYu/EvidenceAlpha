"""Immutable source versions."""

import dataclasses
import math
import pathlib
import re
import threading

import bs4
import pymupdf

from evidencealpha import artifacts

PARSER_VERSION = "structural-1"
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


def _blocks(data: bytes, suffix: str) -> tuple[list[dict], list[str]]:
    blocks = []
    warnings = []
    if suffix == ".pdf":
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page_number, page in enumerate(doc, 1):
                tables = page.find_tables().tables
                for table in tables:
                    rows = [
                        " | ".join(str(cell or "") for cell in row)
                        for row in table.extract()
                    ]
                    blocks.append(
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
                    blocks.append(
                        {
                            "text": block[4].strip(),
                            "kind": "paragraph",
                            "page": page_number,
                            "bbox": list(block[:4]),
                        }
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
        source = artifacts.read(folder / "source.json")
        text = (folder / source["text_path"]).read_text(encoding="utf-8")
        if (
            artifacts.digest(text.encode()) != source["text_hash"]
            or artifacts.digest((folder / source["original_path"]).read_bytes())
            != source["hash"]
        ):
            raise ValueError("Source version was changed in place")
        if chunk_id is None:
            return {"source": source, "text": text}
        chunk = next((c for c in source["chunks"] if c["id"] == chunk_id), None)
        if chunk is None:
            raise ValueError("Unknown chunk")
        for span in chunk["spans"]:
            if not 0 <= span["start"] < span["end"] <= len(text):
                raise ValueError("Invalid source span")
        context_path = folder / "context.json"
        context = (
            artifacts.read(context_path)["generated"]
            if context_path.exists()
            else None
        )
        return dataclasses.asdict(
            Passage(
                source_id,
                chunk_id,
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
        self, query: str, limit: int = 6, embedding_model: str | None = None
    ) -> list[dict]:
        """Rank original passages lexically."""

        def tokens(value: str) -> set[str]:
            words = set(
                re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", value.lower())
            )
            words.update(
                value[i : i + 2]
                for i in range(len(value) - 1)
                if "\u3400" <= value[i] <= "\u9fff"
            )
            return words

        passages = [
            self.open_source(s["id"], c["id"])
            for s in self.sources()
            for c in s["chunks"]
        ]
        wanted = tokens(query)
        scores = [
            len(
                wanted
                & tokens(p["text"] + " " + (p["generated_context"] or ""))
            )
            / math.sqrt(max(1, len(tokens(p["text"]))))
            for p in passages
        ]
        if embedding_model and passages:
            # Explicit opt-in: never download or introduce an embedding API.
            # Optional dependency stays lazy to keep lexical startup small.
            # pylint: disable=import-outside-toplevel
            import sentence_transformers

            model = sentence_transformers.SentenceTransformer(
                embedding_model, local_files_only=True
            )
            vectors = model.encode(
                [query] + [p["text"] for p in passages],
                normalize_embeddings=True,
            )
            scores = [
                score + float(vectors[0] @ vector)
                for score, vector in zip(scores, vectors[1:])
            ]
        ranked = sorted(zip(scores, passages), key=lambda pair: -pair[0])
        return [p for score, p in ranked[:limit] if score > 0]
