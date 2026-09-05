"""A research agent with planning, local search, web search, and acquisition.

The caller plans first (``research.plan``), then Claude chooses among
three tools::

    question + selected approach   (research_prompt)
      -> Claude decides: search_documents, search_web, ingest_url, or none
      -> observations come back as numbered evidence
           [D1], [D2], ...  passages from the local documents
           [W1], [W2], ...  web results with their URLs
      -> grounded answer with citations, or an explicit evidence gap

A small local collection is expected: when it lacks the topic, the web
is the normal next step, and a useful source can be acquired with
ingest_url so that search_documents covers it afterwards. Compare with
``research.answer``, where retrieval always happens first. The tools are
registered through the SDK's in-process MCP server, its supported
mechanism for local Python tools.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

import claude_agent_sdk

from rag import models
from rag import retrieve
from research import acquire
from research import plan as plan_module
from research import web

MODEL = "claude-sonnet-5"
MAX_TURNS = 12  # Safety cap only; a normal run is two to six turns.

EVIDENCE_GAP = (
    "The available evidence does not sufficiently support an answer to "
    "this question."
)

SYSTEM_PROMPT = f"""\
You are a research assistant. You have three tools:

- search_documents: the user's local document collection. Small and
  specific; it may not cover the topic at all.
- search_web: a web search returning titles, URLs, and extracts. These
  are discovery evidence: short extracts, not the full source.
- ingest_url: download one HTML page or digital PDF and add it to the
  local collection, so search_documents can retrieve its full text.

For each question:
1. Understand what is being asked.
2. Decide what evidence it needs. A question about material the user
   has stored locally calls for search_documents. A question about a
   topic that is unlikely to be in a small local collection, or that
   depends on current events or recent developments, calls for
   search_web directly. Some questions need both. A general question
   about a concept or definition needs neither.
3. If search_documents returns nothing relevant, that is normal: the
   collection is small. Move on to search_web rather than giving up.
   Web results are discovery evidence: short extracts, not sources.
   When the answer will rest mainly on web findings, pick the one
   result that looks like the most useful actual source, call
   ingest_url with its URL, then search_documents again with a refined
   query so you can cite its full text as [D#]. Ingest one source, or a
   second only if the first was not enough; never every result.
4. Answer only from the evidence the tools returned. Cite each claim
   with its label in square brackets: [D2] for a document passage,
   [W1] for a web result. Do not fill gaps from your own knowledge.
5. If the evidence still does not support an answer, reply starting
   with exactly this sentence:
   {EVIDENCE_GAP}
   Then say in one sentence what you searched and what was missing.

If the message includes a selected research approach, structure your
evidence gathering and your answer around it.

Keep searches few and focused. Write plain prose.
"""


def format_chunks(chunks: list[models.RetrievedChunk]) -> str:
    """Render retrieved passages as ``[Dn]`` evidence for Claude to read.

    Args:
      chunks: Retrieved chunks, closest first.

    Returns:
      One block per chunk: ``[Dn] source: ... (distance ...)`` then the
      text. A fixed sentence if there are no chunks.
    """
    if not chunks:
        return "No passages found."
    return "\n\n".join(
        f"[D{number}] source: {chunk.source} (distance {chunk.score:.4f})\n"
        f"{chunk.text}"
        for number, chunk in enumerate(chunks, start=1)
    )


def format_results(results: list[web.WebResult]) -> str:
    """Render web results as ``[Wn]`` evidence for Claude to read.

    Args:
      results: Web results, most relevant first.

    Returns:
      One block per result: ``[Wn] title - url`` then the snippet. A
      fixed sentence if there are no results.
    """
    if not results:
        return "No web results found."
    return "\n\n".join(
        f"[W{number}] {result.title} - {result.url}\n{result.snippet}"
        for number, result in enumerate(results, start=1)
    )


@claude_agent_sdk.tool(
    "search_documents",
    "Search the user's local document collection and return the passages "
    "most similar to the query, labelled [D1], [D2], ... with their source "
    "file. The collection is small; an empty or off-topic result means the "
    "topic is not covered locally. Optional 'k' (default 5) sets how many "
    "passages to return.",
    {"query": str},
)
async def search_documents(args: dict[str, Any]) -> dict[str, Any]:
    """Tool handler: run the Phase 1 retriever and format the result."""
    chunks = retrieve.search_documents(args["query"], k=args.get("k", 5))
    return {"content": [{"type": "text", "text": format_chunks(chunks)}]}


@claude_agent_sdk.tool(
    "search_web",
    "Search the web and return the most relevant pages, labelled [W1], "
    "[W2], ... with title, URL, and an extract. Use it for topics not in "
    "the local documents and for anything current. Optional 'max_results' "
    "(default 5).",
    {"query": str},
)
async def search_web(args: dict[str, Any]) -> dict[str, Any]:
    """Tool handler: run the web search and format the result."""
    results = web.search_web(
        args["query"], max_results=args.get("max_results", 5)
    )
    return {"content": [{"type": "text", "text": format_results(results)}]}


@claude_agent_sdk.tool(
    "ingest_url",
    "Download one HTML page or digital PDF at the given http(s) URL and add "
    "it to the local document collection, so search_documents can retrieve "
    "its full text. Use it only after search_web has identified a source "
    "that appears to contain evidence the research task needs; never for a "
    "search-result snippet. Returns how many chunks were indexed.",
    {"url": str},
)
async def ingest_url(args: dict[str, Any]) -> dict[str, Any]:
    """Tool handler: acquire the source with the Phase 1 pipeline."""
    url = args["url"]
    count = acquire.ingest_url(url)
    text = (
        f"Ingested {count} chunks from {url} into the local document "
        "collection. Use search_documents to retrieve from it."
    )
    return {"content": [{"type": "text", "text": text}]}


SERVER = claude_agent_sdk.create_sdk_mcp_server(
    name="research", tools=[search_documents, search_web, ingest_url]
)

OPTIONS = claude_agent_sdk.ClaudeAgentOptions(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    tools=[],
    mcp_servers={"research": SERVER},
    allowed_tools=[
        "mcp__research__search_documents",
        "mcp__research__search_web",
        "mcp__research__ingest_url",
    ],
    max_turns=MAX_TURNS,
    # SDK isolation: no settings files, no CLAUDE.md, no auto-memory, so
    # the agent sees only this prompt, the question, and the tools.
    setting_sources=[],
    env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
)


def research_prompt(question: str, plan: plan_module.ResearchPlan) -> str:
    """Attach the selected research approach, if any, to the question."""
    chosen = plan.chosen() if plan.use_tot else None
    if chosen is None:
        return question
    return (
        f"{question}\n\nSelected research approach ({chosen.label}): "
        f"{chosen.approach}"
    )


@dataclasses.dataclass(frozen=True)
class ResearchResult:
    """One agent run: the answer and the tool observations behind it.

    Attributes:
      answer: Claude's cited answer, or the fixed evidence-gap sentence.
      observations: Every tool result Claude saw, verbatim and in order.
    """

    answer: str
    observations: list[str]


def _observation_text(block: claude_agent_sdk.ToolResultBlock) -> str:
    """Flatten a tool result's content to plain text."""
    if isinstance(block.content, str):
        return block.content
    return "\n".join(part.get("text", "") for part in block.content or [])


def format_observations(observations: list[str]) -> str:
    """Render tool observations as numbered blocks, or a fixed sentence."""
    return (
        "\n".join(
            f"--- observation {number} ---\n{observation}"
            for number, observation in enumerate(observations, start=1)
        )
        or "none: no tool was called"
    )


def followup_prompt(
    question: str,
    plan: plan_module.ResearchPlan,
    evidence: list[str],
    gaps: list[str],
) -> str:
    """Build a follow-up round's message with the gaps as the task.

    Layout: question and approach, a framing sentence, the evidence
    already collected, the unresolved gaps as separate numbered items,
    then the instruction. Tool choice is left to the agent; the message
    gives heuristics, not an order.

    Args:
      question: The user's question.
      plan: The planning result; its chosen approach is repeated.
      evidence: Every observation from the earlier rounds, in order.
      gaps: The evaluator's unresolved gaps, kept verbatim.

    Returns:
      The message for ``research``.
    """
    gap_lines = "\n".join(
        f"{number}. {gap}" for number, gap in enumerate(gaps, start=1)
    )
    return (
        f"{research_prompt(question, plan)}\n\n"
        "This is a follow-up research round. Your task is the numbered "
        "list of unresolved evidence gaps below; the evidence already "
        "collected is shown so you can reuse it instead of repeating it."
        "\n\n"
        f"Evidence already collected:\n{format_observations(evidence)}\n\n"
        f"Unresolved evidence gaps:\n{gap_lines}\n\n"
        "Address each unresolved gap. For every gap, decide where its "
        "evidence is most likely to be, and prefer authoritative and "
        "current sources for that gap: use search_documents when existing "
        "or local sources are likely to contain the evidence; use "
        "search_web when the evidence is likely external, missing, or "
        "current; use ingest_url when a useful web source needs "
        "full-document retrieval. Do not re-research claims the evidence "
        "above already supports. Report what you found for each gap with "
        "citations, and state plainly which gaps you could not resolve."
    )


def tool_events(message: Any) -> list[dict[str, Any]]:
    """Describe what one SDK message shows of the agent's tool loop.

    Args:
      message: Any message from ``claude_agent_sdk.query``.

    Returns:
      Zero or more events, in the message's order. ``tool_use`` carries
      the tool's short name and input, ``tool_result`` the observation
      text, ``assistant_text`` the text Claude wrote between tool calls
      or as its answer. Other messages give no event.
    """
    events: list[dict[str, Any]] = []
    if isinstance(message, claude_agent_sdk.AssistantMessage):
        for block in message.content:
            if isinstance(block, claude_agent_sdk.ToolUseBlock):
                tool = block.name.removeprefix("mcp__research__")
                events.append(
                    {"event": "tool_use", "tool": tool, "input": block.input}
                )
            elif isinstance(block, claude_agent_sdk.TextBlock):
                events.append({"event": "assistant_text", "text": block.text})
    elif isinstance(message, claude_agent_sdk.UserMessage):
        for block in message.content:
            if isinstance(block, claude_agent_sdk.ToolResultBlock):
                text = _observation_text(block)
                events.append({"event": "tool_result", "text": text})
    return events


async def research(
    prompt: str, on_event: Callable[[dict[str, Any]], Any] | None = None
) -> ResearchResult:
    """Run the agent once and return its answer with the evidence it saw.

    Args:
      prompt: The finished user message, normally from ``research_prompt``.
      on_event: Called with each ``tool_events`` event as it happens, so
        a caller can show the tool loop while it runs. ``None`` shows
        nothing; the result is the same either way.

    Returns:
      The answer and the tool observations in the order Claude received
      them.

    Raises:
      RuntimeError: If the SDK reports an error or returns no result.
    """
    observations: list[str] = []
    result = None
    async for message in claude_agent_sdk.query(prompt=prompt, options=OPTIONS):
        if on_event is not None:
            for event in tool_events(message):
                on_event(event)
        if isinstance(message, claude_agent_sdk.UserMessage):
            for block in message.content:
                if isinstance(block, claude_agent_sdk.ToolResultBlock):
                    observations.append(_observation_text(block))
        elif isinstance(message, claude_agent_sdk.ResultMessage):
            result = message
    if result is None or result.is_error or result.result is None:
        errors = result.errors if result else "no result"
        raise RuntimeError(f"Agent run failed: {errors}")
    return ResearchResult(answer=result.result, observations=observations)
