"""Section-aware chunking of parsed documents (04 §3).

:func:`chunk` is a pure function of ``(ParsedDocument, counter,
policy)``: no I/O, no model calls, no randomness, no wall clock. The
same input under the same chunking signature produces byte-identical
chunks and IDs (04 §9).

The grouping rules (04 §3.1) in brief: a block's *effective path* is
its ``heading_path``, plus its own text when the block is a heading —
03 §5.3 defines ``heading_path`` as *enclosing* headings only, so a
heading block never contains itself. Any change of effective path is a
section boundary; chunks never span sections. Within a section, blocks
accumulate greedily up to ``max_tokens``, with trailing-block overlap
between consecutive chunks. Blocks are atomic, with two oversize
exceptions that produce ``segment`` chunks: a paragraph-like block
splits on line, then sentence (then, as a last resort against the
model window, word) boundaries, and a table splits at row boundaries
of its canonical rendering with its header lines repeated per piece.
Citation text is always a verbatim block text or a verbatim selection
of it — never re-rendered (03 §5.4).

``min_tokens`` is the packing floor the greedy rules aim for; a chunk
falls below it only when its section ended first or when block
atomicity forces a short close (a short section is a short chunk,
never merged across headings).
"""

import hashlib
import re
from typing import Protocol, cast

import pydantic

from contracts import chunk as chunk_contract
from contracts import document
from contracts import quality

#: Version of the chunking rules in this module (04 §3.5). Any rule
#: change bumps this, which changes every chunk ID.
CHUNKER_VERSION = "chunk-1.0"

#: Version of the deterministic context-prefix template (04 §3.3). It
#: participates in the *embedding* signature: reformatting the prefix
#: re-embeds, visibly.
CONTEXT_PREFIX_VERSION = "ctx-v1"

#: Separator between member-block texts inside one citation.
_SEPARATOR = "\n\n"

#: Sentence boundaries: ASCII and CJK sentence enders followed by
#: whitespace.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?。！？])\s+")

_WORD = re.compile(r"\S+")

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")


class TokenCounter(Protocol):
    """Counts budget tokens for the chunker (04 §3.4).

    Injected so the chunker stays model-free: production uses the
    embedding model's tokenizer, unit tests a whitespace counter. The
    counter's name participates in the chunking signature, so swapping
    counters visibly changes every chunk ID.
    """

    @property
    def name(self) -> str:
        """A stable name identifying this counting scheme."""
        raise NotImplementedError

    def __call__(self, text: str) -> int:
        """Return the number of tokens in ``text``."""
        raise NotImplementedError


class WhitespaceTokenCounter:
    """Counts whitespace-separated words — the unit-test counter."""

    @property
    def name(self) -> str:
        """The counter name recorded in the chunking signature."""
        return "whitespace"

    def __call__(self, text: str) -> int:
        """Return the number of whitespace-separated words.

        Args:
          text: The text to count.

        Returns:
          The word count.
        """
        return len(text.split())


class ChunkPolicy(pydantic.BaseModel):
    """The versioned chunking constants (04 §3.5).

    The v0 budget is derived from multilingual-e5-base's 512-token
    input window: ``420 (content) + ~40 (context prefix) + ~4 (role
    prefix) + margin < 512``, so a chunk is never silently truncated
    at embedding time. Changing any constant is a policy change and
    must come with a new ``version`` string — the version is what the
    chunking signature records.
    """

    model_config = _MODEL_CONFIG

    version: str = "policy-v0"
    max_tokens: int = pydantic.Field(default=420, ge=1)
    min_tokens: int = pydantic.Field(default=240, ge=0)
    overlap_tokens: int = pydantic.Field(default=50, ge=0)

    @pydantic.model_validator(mode="after")
    def _check_v0_constants(self) -> "ChunkPolicy":
        """Refuse silently drifted constants under the v0 label."""
        v0 = (420, 240, 50)
        mine = (self.max_tokens, self.min_tokens, self.overlap_tokens)
        if self.version == "policy-v0" and mine != v0:
            raise ValueError(
                "policy-v0 constants are fixed (04 §3.5); changed "
                "constants require a new policy version"
            )
        return self


#: The chunking policy in force for the MVP (04 §3.5).
POLICY_V0 = ChunkPolicy()


def make_chunking_signature(policy: ChunkPolicy, counter: TokenCounter) -> str:
    """Build the chunk-policy identity in force (04 §3.5).

    Args:
      policy: The chunking policy.
      counter: The token counter in force.

    Returns:
      ``chunk-<rules>|<policy-version>|counter:<name>`` — the string
      that participates in every chunk ID (04 §2.1).
    """
    return f"{CHUNKER_VERSION}|{policy.version}|counter:{counter.name}"


def make_chunk_id(
    document_id: str,
    parse_id: str,
    chunking_signature: str,
    locator: document.Locator,
    ordinal: int,
) -> str:
    """Derive a stable chunk ID (04 §2.1).

    The ID hashes the parse identity, the chunking signature, the
    chunk's first-block locator (as the same canonical JSON dump
    ``make_block_id`` uses), and the chunk's ordinal — so a re-parse
    *or* a chunking-rule change mints new IDs rather than silently
    overwriting old ones.

    Args:
      document_id: The logical document identity.
      parse_id: The parse identity (03 §5.1).
      chunking_signature: The chunk-policy identity in force.
      locator: The chunk's locator (its first member block's).
      ordinal: The chunk's zero-based position within the parse.

    Returns:
      A ``chk_``-prefixed stable identifier.
    """
    payload = "|".join(
        [
            document_id,
            parse_id,
            chunking_signature,
            locator.model_dump_json(),
            str(ordinal),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"chk_{digest[:16]}"


class _Draft:
    """One chunk being assembled: member blocks and their texts."""

    def __init__(self) -> None:
        self.members: list[document.Block] = []
        self.texts: list[str] = []
        self.segment: chunk_contract.ChunkSegment | None = None
        self.locator: document.Locator | None = None

    def add(self, block: document.Block, text: str) -> None:
        """Append a member block with its citation text."""
        self.members.append(block)
        self.texts.append(text)

    @property
    def citation_text(self) -> str:
        """The draft's citation text so far."""
        return _SEPARATOR.join(self.texts)

    def all_headings(self) -> bool:
        """Whether every member so far is a heading block."""
        return all(
            member.type is document.BlockType.HEADING for member in self.members
        )


def chunk(
    parsed: document.ParsedDocument,
    counter: TokenCounter,
    policy: ChunkPolicy = POLICY_V0,
) -> list[chunk_contract.DocumentChunk]:
    """Chunk one parsed document (04 §3).

    Args:
      parsed: The parsed document; only admitted blocks are present.
      counter: The token counter in force (04 §3.4). Production injects
        the embedding model's tokenizer.
      policy: The chunking policy; v0 when omitted.

    Returns:
      The document's chunks, in order, with stable IDs. An empty
      document yields an empty list.
    """
    signature = make_chunking_signature(policy, counter)
    business = _business_for(parsed)
    document_codes = frozenset(
        warning.code for warning in parsed.parse_quality.warnings
    )
    chunks: list[chunk_contract.DocumentChunk] = []
    for path, blocks in _sections(parsed.blocks):
        for draft in _chunk_section(blocks, counter, policy):
            chunks.append(
                _finalize(
                    draft=draft,
                    path=path,
                    ordinal=len(chunks),
                    parsed=parsed,
                    signature=signature,
                    document_codes=document_codes,
                    business=business,
                    counter=counter,
                )
            )
    return chunks


def _effective_path(block: document.Block) -> tuple[str, ...]:
    """Return the block's effective enclosing path (04 §3.1 rule 1)."""
    if block.type is document.BlockType.HEADING:
        return tuple(block.heading_path) + (block.text,)
    return tuple(block.heading_path)


def _sections(
    blocks: list[document.Block],
) -> list[tuple[tuple[str, ...], list[document.Block]]]:
    """Group blocks into contiguous runs of equal effective path."""
    runs: list[tuple[tuple[str, ...], list[document.Block]]] = []
    for block in blocks:
        path = _effective_path(block)
        if runs and runs[-1][0] == path:
            runs[-1][1].append(block)
        else:
            runs.append((path, [block]))
    return runs


def _chunk_section(
    blocks: list[document.Block],
    counter: TokenCounter,
    policy: ChunkPolicy,
) -> list[_Draft]:
    """Assemble one section's chunk drafts (04 §3.1 rules 3–7)."""
    drafts: list[_Draft] = []
    current = _Draft()
    previous: _Draft | None = None
    for block in blocks:
        if counter(block.text) > policy.max_tokens:
            lead: _Draft | None = None
            if current.members and current.all_headings():
                lead = current
            elif current.members:
                drafts.append(current)
            drafts.extend(_split_block(block, counter, policy, lead))
            current = _Draft()
            previous = None
            continue
        if current.members and _joint_exceeds(current, block, counter, policy):
            if current.all_headings():
                # Rule 6: a heading opens a chunk, so attach it forward
                # by splitting the incoming block into the remaining
                # budget rather than emitting a heading-only chunk.
                drafts.extend(_split_block(block, counter, policy, current))
                current = _Draft()
                previous = None
                continue
            drafts.append(current)
            previous = current
            current = _Draft()
        if not current.members and previous is not None:
            _seed_overlap(current, previous, block, counter, policy)
            previous = None
        current.add(block, block.text)
    if current.members:
        drafts.append(current)
    return drafts


def _joint_exceeds(
    draft: _Draft,
    block: document.Block,
    counter: TokenCounter,
    policy: ChunkPolicy,
) -> bool:
    """Whether adding the block would push the draft over budget."""
    candidate = _SEPARATOR.join(draft.texts + [block.text])
    return counter(candidate) > policy.max_tokens


def _seed_overlap(
    current: _Draft,
    previous: _Draft,
    incoming: document.Block,
    counter: TokenCounter,
    policy: ChunkPolicy,
) -> None:
    """Seed the next chunk with the previous chunk's tail (rule 4).

    Overlap is trailing-block repetition, only within the section,
    never splitting a block, and never allowed to push the new chunk
    (tail plus the incoming block) over ``max_tokens``.
    """
    tail: list[document.Block] = []
    budget = policy.overlap_tokens
    for member in reversed(previous.members):
        cost = counter(member.text)
        if cost > budget:
            break
        tail.insert(0, member)
        budget -= cost
    while tail:
        candidate = _SEPARATOR.join(
            [member.text for member in tail] + [incoming.text]
        )
        if counter(candidate) <= policy.max_tokens:
            break
        tail.pop(0)
    for member in tail:
        current.add(member, member.text)


def _split_block(
    block: document.Block,
    counter: TokenCounter,
    policy: ChunkPolicy,
    lead: _Draft | None,
) -> list[_Draft]:
    """Split one block into segment drafts (04 §3.1 rule 5).

    ``lead`` carries heading blocks that must attach forward: when
    present (and small enough), its members join the first piece.
    """
    if block.type is document.BlockType.TABLE and isinstance(
        block.payload, document.TableBlock
    ):
        return _split_table(block, counter, policy, lead)
    return _split_text(block, counter, policy, lead)


def _lead_spill(
    lead: _Draft | None,
    first_piece_text: str,
    counter: TokenCounter,
    policy: ChunkPolicy,
) -> tuple[_Draft | None, list[_Draft]]:
    """Decide whether the lead can join the first piece.

    Returns:
      ``(lead, spilled)`` — the lead to attach to the first piece (or
      None), and any draft that must be emitted on its own because
      even the smallest first piece would not fit beside it.
    """
    if lead is None:
        return None, []
    candidate = _SEPARATOR.join(lead.texts + [first_piece_text])
    if counter(candidate) > policy.max_tokens:
        return None, [lead]
    return lead, []


def _piece_draft(
    block: document.Block,
    text: str,
    segment: chunk_contract.ChunkSegment,
    locator: document.Locator,
    lead: _Draft | None,
) -> _Draft:
    """Build one split-piece draft, attaching the lead when given."""
    draft = _Draft()
    if lead is not None:
        draft.members = list(lead.members)
        draft.texts = list(lead.texts)
        draft.locator = lead.members[0].locator
    else:
        draft.locator = locator
    draft.add(block, text)
    draft.segment = segment
    return draft


def _split_text(
    block: document.Block,
    counter: TokenCounter,
    policy: ChunkPolicy,
    lead: _Draft | None,
) -> list[_Draft]:
    """Split a text block into ``paragraph_span`` pieces.

    Pieces are verbatim ``[start, end)`` slices of the block's
    canonical text, cut on line, then sentence, then (only to protect
    the model window) word boundaries. Line locators are narrowed
    mechanically by counting newlines in the span (04 §2.2).
    """
    text = block.text
    atoms = _atom_spans(text, counter, policy.max_tokens)
    drafts: list[_Draft] = []
    span: tuple[int, int] | None = None
    for atom in atoms:
        if span is None:
            if not drafts:
                lead, spilled = _lead_spill(
                    lead, text[atom[0] : atom[1]], counter, policy
                )
                drafts.extend(spilled)
            span = atom
            continue
        candidate = text[span[0] : atom[1]]
        if not drafts and lead is not None:
            candidate = _SEPARATOR.join(lead.texts + [candidate])
        if counter(candidate) > policy.max_tokens:
            drafts.append(_close_text_piece(block, text, span, lead))
            lead = None
            span = atom
        else:
            span = (span[0], atom[1])
    if span is not None:
        drafts.append(_close_text_piece(block, text, span, lead))
    return drafts


def _close_text_piece(
    block: document.Block,
    text: str,
    span: tuple[int, int],
    lead: _Draft | None,
) -> _Draft:
    """Close one paragraph_span piece over ``span``."""
    start, end = span
    segment = chunk_contract.ChunkSegment(
        source_block_id=block.block_id,
        kind=chunk_contract.ChunkSegmentKind.PARAGRAPH_SPAN,
        text_start=start,
        text_end=end,
    )
    return _piece_draft(
        block=block,
        text=text[start:end],
        segment=segment,
        locator=_narrow_lines(block.locator, text, start, end),
        lead=lead,
    )


def _atom_spans(
    text: str, counter: TokenCounter, max_tokens: int
) -> list[tuple[int, int]]:
    """Return atomic split spans: lines, then sentences, then words."""
    spans: list[tuple[int, int]] = []
    for start, end in _line_spans(text):
        if counter(text[start:end]) <= max_tokens:
            spans.append((start, end))
            continue
        for s_start, s_end in _sentence_spans(text, start, end):
            if counter(text[s_start:s_end]) <= max_tokens:
                spans.append((s_start, s_end))
            else:
                spans.extend(
                    (s_start + match.start(), s_start + match.end())
                    for match in _WORD.finditer(text[s_start:s_end])
                )
    return spans


def _line_spans(text: str) -> list[tuple[int, int]]:
    """Return the stripped span of each non-blank line."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.split("\n"):
        lead_ws = len(line) - len(line.lstrip())
        start = offset + lead_ws
        end = offset + len(line.rstrip())
        if end > start:
            spans.append((start, end))
        offset += len(line) + 1
    return spans


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Return sentence spans inside ``text[start:end]``."""
    spans: list[tuple[int, int]] = []
    piece = text[start:end]
    previous = 0
    boundaries = [
        (match.start(), match.end())
        for match in _SENTENCE_BREAK.finditer(piece)
    ]
    for break_start, break_end in boundaries + [(len(piece), len(piece))]:
        if break_start > previous:
            spans.append((start + previous, start + break_start))
        previous = break_end
    return spans


def _narrow_lines(
    locator: document.Locator, text: str, start: int, end: int
) -> document.Locator:
    """Narrow a line locator to the piece's span (04 §2.2)."""
    if locator.line_start is None:
        return locator
    line_start = locator.line_start + text.count("\n", 0, start)
    line_end = locator.line_start + text.count("\n", 0, end)
    if locator.line_end is not None:
        line_end = min(line_end, locator.line_end)
    return locator.model_copy(
        update={"line_start": line_start, "line_end": line_end}
    )


def _split_table(
    block: document.Block,
    counter: TokenCounter,
    policy: ChunkPolicy,
    lead: _Draft | None,
) -> list[_Draft]:
    """Split a table at row boundaries of its canonical rendering.

    Each piece's citation text is the caption/unit line(s), the
    header-row lines, the delimiter line, and a contiguous slice of
    data-row lines — all verbatim lines of the block's canonical
    ``render_table_text`` output (line selection, never re-rendering;
    03 §5.4). Header lines repeat per piece so every piece reads as a
    table. Segments record ``[row_start, row_end)`` grid row indices.
    """
    # The Block validator guarantees a table block's payload type.
    payload = cast(document.TableBlock, block.payload)
    lines = block.text.split("\n")
    prefix_lines = (1 if payload.caption else 0) + (
        1 if payload.unit or payload.scale else 0
    )
    delimiter_lines = 1 if payload.header_rows else 0
    head_count = prefix_lines + payload.header_rows + delimiter_lines
    head_lines = lines[:head_count]
    data_lines = lines[head_count:]
    if len(data_lines) <= 1:
        # Nothing to split at: a single (or no) data row is atomic.
        draft = _Draft()
        if lead is not None:
            draft.members = list(lead.members)
            draft.texts = list(lead.texts)
        draft.add(block, block.text)
        return [draft]

    drafts: list[_Draft] = []
    row_range: tuple[int, int] | None = None
    for index in range(len(data_lines)):
        if row_range is None:
            if not drafts:
                lead, spilled = _lead_spill(
                    lead,
                    _table_piece_text(head_lines, data_lines, index, index + 1),
                    counter,
                    policy,
                )
                drafts.extend(spilled)
            row_range = (index, index + 1)
            continue
        candidate = _table_piece_text(
            head_lines, data_lines, row_range[0], index + 1
        )
        if not drafts and lead is not None:
            candidate = _SEPARATOR.join(lead.texts + [candidate])
        if counter(candidate) > policy.max_tokens:
            drafts.append(
                _close_table_piece(
                    block, head_lines, data_lines, row_range, lead
                )
            )
            lead = None
            row_range = (index, index + 1)
        else:
            row_range = (row_range[0], index + 1)
    if row_range is not None:
        drafts.append(
            _close_table_piece(block, head_lines, data_lines, row_range, lead)
        )
    return drafts


def _table_piece_text(
    head_lines: list[str],
    data_lines: list[str],
    row_start: int,
    row_end: int,
) -> str:
    """Join a table piece's verbatim line selection."""
    return "\n".join(head_lines + data_lines[row_start:row_end])


def _close_table_piece(
    block: document.Block,
    head_lines: list[str],
    data_lines: list[str],
    row_range: tuple[int, int],
    lead: _Draft | None,
) -> _Draft:
    """Close one table_rows piece over ``row_range`` data rows."""
    payload = cast(document.TableBlock, block.payload)
    segment = chunk_contract.ChunkSegment(
        source_block_id=block.block_id,
        kind=chunk_contract.ChunkSegmentKind.TABLE_ROWS,
        row_start=payload.header_rows + row_range[0],
        row_end=payload.header_rows + row_range[1],
    )
    return _piece_draft(
        block=block,
        text=_table_piece_text(head_lines, data_lines, *row_range),
        segment=segment,
        locator=block.locator,
        lead=lead,
    )


def _business_for(
    parsed: document.ParsedDocument,
) -> chunk_contract.ChunkBusiness:
    """Copy business metadata onto the chunk contract — never invent."""
    metadata = parsed.business_metadata
    source = parsed.source
    return chunk_contract.ChunkBusiness(
        company=metadata.company,
        ticker=metadata.ticker,
        cik=metadata.cik,
        document_type=metadata.document_type,
        reporting_period=metadata.reporting_period,
        published_at=metadata.published_at,
        source_type=source.source_type,
        url=source.canonical_url or source.original_url,
    )


def context_prefix(
    business: chunk_contract.ChunkBusiness, path: tuple[str, ...]
) -> str:
    """Build the deterministic context prefix (04 §3.3, ctx-v1).

    ``PHOTRONICS, INC. (PLAB) | 10-Q Q2 FY2026 | PART I > ITEM 1.``
    Missing parts are omitted, never invented; an empty prefix means
    the embedding text is the citation text alone.

    Args:
      business: The chunk's copied business metadata.
      path: The chunk's effective heading path.

    Returns:
      The prefix, possibly empty.
    """
    parts: list[str] = []
    if business.company and business.ticker:
        parts.append(f"{business.company} ({business.ticker})")
    elif business.company:
        parts.append(business.company)
    elif business.ticker:
        parts.append(business.ticker)
    filing = " ".join(
        part
        for part in (business.document_type, business.reporting_period)
        if part
    )
    if filing:
        parts.append(filing)
    if path:
        parts.append(" > ".join(path))
    return " | ".join(parts)


def _finalize(
    draft: _Draft,
    path: tuple[str, ...],
    ordinal: int,
    parsed: document.ParsedDocument,
    signature: str,
    document_codes: frozenset[quality.WarningCode],
    business: chunk_contract.ChunkBusiness,
    counter: TokenCounter,
) -> chunk_contract.DocumentChunk:
    """Turn one draft into a finished ``DocumentChunk``."""
    citation = draft.citation_text
    locator = draft.locator or draft.members[0].locator
    codes = set(document_codes)
    for member in draft.members:
        codes.update(warning.code for warning in member.extraction.warnings)
    prefix = context_prefix(business, path)
    embedding_text = f"{prefix}\n{citation}" if prefix else citation
    identity = parsed.identity
    return chunk_contract.DocumentChunk(
        chunk_id=make_chunk_id(
            document_id=identity.document_id,
            parse_id=identity.parse_id,
            chunking_signature=signature,
            locator=locator,
            ordinal=ordinal,
        ),
        document_id=identity.document_id,
        version_id=identity.version_id,
        parse_id=identity.parse_id,
        chunking_signature=signature,
        ordinal=ordinal,
        citation_text=citation,
        embedding_text=embedding_text,
        block_ids=[member.block_id for member in draft.members],
        segment=draft.segment,
        section=path[-1] if path else None,
        heading_path=list(path),
        locator=locator,
        locator_tier=max(member.locator_tier for member in draft.members),
        warning_codes=sorted(codes),
        token_count=counter(citation),
        business=business,
    )
