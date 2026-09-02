"""Stable source identity across research rounds.

Inside a round the agent's tools label evidence ``[D1]``, ``[W1]``, ...
and the numbering restarts with every tool call, so two observations
can both say ``[D1]`` about different sources. As observations enter
workflow state, ``normalize_observations`` rewrites those labels to
graph-level ids ``[S1]``, ``[S2]``, ... where one id means one
underlying source, however many tool results showed it.

The only source metadata that reaches the workflow is what the agent's
own formatters wrote into the observation text, so this module parses
exactly those shapes and nothing else: a line that is not a complete,
formatter-produced header is left untouched and registers nothing.
Identity is exact: a canonical URL for web, ingested, and acquired
sources; the ingested path for local files. When identity cannot be
proven, a new id is allocated rather than guessed.
"""

import dataclasses
import re
import urllib.parse


@dataclasses.dataclass(frozen=True)
class SourceRecord:
    """One underlying source, however many tool results showed it.

    Attributes:
      source_id: The stable label, ``"S3"``.
      title: The web title when known, otherwise the path or URL.
      canonical_url: For web results, ingested URLs, and acquired
        chunks; ``None`` for local files.
      local_document_id: The source path as ingested, for local files;
        ``None`` otherwise.
      seen_via: Which tool kinds have surfaced this source, unique, in
        first-seen order: ``"documents"``, ``"web"``, ``"ingest"``.
    """

    source_id: str
    title: str
    canonical_url: str | None
    local_document_id: str | None
    seen_via: tuple[str, ...]


# The complete header shapes written by agent.format_chunks,
# agent.format_results, and the ingest_url tool handler. A line must
# match one of these in full to be treated as metadata.
_DOCUMENT_HEADER = re.compile(
    r"^\[D\d+\] source: (?P<source>.+?)(?P<page> \(page \d+\))?"
    r" \(distance -?\d+\.\d{4}\)$"
)
_WEB_HEADER = re.compile(r"^\[W\d+\] (?P<title>.+) - (?P<url>https?://\S+)$")
_INGEST_LINE = re.compile(
    r"^Ingested \d+ chunks from (?P<url>https?://\S+) into the local "
    r"document collection\. Use search_documents to retrieve from it\.$"
)


def canonical_url(url: str) -> str:
    """Return a URL's identity form: lowercase scheme and host, no fragment.

    Everything else (path, query, trailing slash, ``www``) is preserved,
    so two URLs that differ there are treated as different sources.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",
        )
    )


def _register(
    registry: dict[str, SourceRecord],
    kind: str,
    title: str,
    url: str | None,
    local_document_id: str | None,
) -> str:
    """Find or create the record for one sighting; return its id."""
    for record in registry.values():
        same_url = url is not None and record.canonical_url == url
        same_file = (
            local_document_id is not None
            and record.local_document_id == local_document_id
        )
        if same_url or same_file:
            seen_via = record.seen_via
            if kind not in seen_via:
                seen_via = seen_via + (kind,)
            new_title = record.title
            if record.title == record.canonical_url and title != url:
                new_title = title  # A real title replaces a bare URL.
            if seen_via != record.seen_via or new_title != record.title:
                registry[record.source_id] = dataclasses.replace(
                    record, seen_via=seen_via, title=new_title
                )
            return record.source_id
    source_id = f"S{len(registry) + 1}"
    registry[source_id] = SourceRecord(
        source_id=source_id,
        title=title,
        canonical_url=url,
        local_document_id=local_document_id,
        seen_via=(kind,),
    )
    return source_id


def _relabel(line: str, source_id: str) -> str:
    """Replace the leading ``[D#]``/``[W#]`` label and keep the rest."""
    return f"[{source_id}]" + line[line.index("]") + 1 :]


def _normalize_line(line: str, registry: dict[str, SourceRecord]) -> str:
    """Register a header line's source and relabel it; else return it as is."""
    match = _DOCUMENT_HEADER.match(line)
    if match:
        source = match["source"]
        if source.startswith(("http://", "https://")):
            url = canonical_url(source)
            source_id = _register(registry, "documents", url, url, None)
        else:
            source_id = _register(registry, "documents", source, None, source)
        return _relabel(line, source_id)
    match = _WEB_HEADER.match(line)
    if match:
        url = canonical_url(match["url"])
        source_id = _register(registry, "web", match["title"], url, None)
        return _relabel(line, source_id)
    match = _INGEST_LINE.match(line)
    if match:
        url = canonical_url(match["url"])
        _register(registry, "ingest", url, url, None)
    return line


def normalize_observations(
    observations: list[str],
    sources: dict[str, SourceRecord],
) -> tuple[list[str], dict[str, SourceRecord]]:
    """Rewrite tool labels to stable ids and extend the source registry.

    Args:
      observations: One round's tool observations, verbatim.
      sources: The registry so far; not mutated.

    Returns:
      The observations with each formatter header's ``[D#]``/``[W#]``
      replaced by its ``[S#]`` and every other character unchanged, and
      a new registry holding the previous records plus this round's.
    """
    registry = dict(sources)
    normalized = [
        "\n".join(_normalize_line(line, registry) for line in text.split("\n"))
        for text in observations
    ]
    return normalized, registry
