"""Answer a question from retrieved evidence, using the Claude Agent SDK.

The flow is deliberately linear so every stage can be inspected::

    question
      -> retrieve.search_documents()   list[RetrievedChunk]
      -> build_prompt()                the exact text Claude receives
      -> ask_claude()                  one model turn, no tools
      -> grounded answer               prose with [n] citations

Phase 2 keeps Claude constrained: a fixed model, no tools, one turn, and
no project settings, so the answer depends only on the evidence, the
prompt, and the model.
"""

import logging

import claude_agent_sdk

from rag import models
from rag import retrieve

MODEL = "claude-sonnet-5"

INSUFFICIENT_EVIDENCE = (
    "The retrieved evidence is not sufficient to answer this question."
)

SYSTEM_PROMPT = f"""\
You answer questions using only the numbered evidence supplied in the
message. Do not use any other knowledge, even if you are confident.

Rules:
- Write plain prose.
- Cite every claim with the evidence number in square brackets, like [2].
- If the evidence does not answer the question, reply with exactly:
  {INSUFFICIENT_EVIDENCE}
"""

logger = logging.getLogger(__name__)


def build_prompt(question: str, chunks: list[models.RetrievedChunk]) -> str:
    """Lay out the evidence and the question as one message for Claude.

    Args:
      question: The user's question.
      chunks: Retrieved chunks, closest first. Chunk ``i`` becomes
        evidence ``[i + 1]``.

    Returns:
      The prompt text, exactly as it will be sent.
    """
    evidence = "\n\n".join(
        f"[{number}] source: {chunk.source}\n{chunk.text}"
        for number, chunk in enumerate(chunks, start=1)
    )
    return f"Evidence:\n\n{evidence}\n\nQuestion: {question}"


async def ask_claude(prompt: str) -> str:
    """Send one prompt to Claude and return its text reply.

    Runs a single turn with no tools, so Claude can only respond to the
    prompt. Authentication is resolved by the SDK's bundled Claude Code
    transport from the existing local login.

    Args:
      prompt: The message to send.

    Returns:
      The concatenated text of Claude's reply.

    Raises:
      RuntimeError: If the SDK reports an error or returns no text.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        max_turns=1,
        # SDK isolation: no settings files, no CLAUDE.md, no auto-memory, so
        # Claude sees only this prompt and the message.
        setting_sources=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    texts: list[str] = []
    async for message in claude_agent_sdk.query(prompt=prompt, options=options):
        if isinstance(message, claude_agent_sdk.AssistantMessage):
            for block in message.content:
                if isinstance(block, claude_agent_sdk.TextBlock):
                    texts.append(block.text)
        elif isinstance(message, claude_agent_sdk.ResultMessage):
            logger.info(
                "model=%s turns=%d cost_usd=%s",
                MODEL,
                message.num_turns,
                message.total_cost_usd,
            )
            if message.is_error:
                raise RuntimeError(f"Claude call failed: {message.errors}")
    if not texts:
        raise RuntimeError("Claude returned no text")
    return "".join(texts)


async def answer_question(question: str, k: int = 5) -> str:
    """Retrieve evidence for the question and answer from it.

    Args:
      question: The user's question.
      k: How many chunks to retrieve.

    Returns:
      Claude's grounded answer with ``[n]`` citations into the retrieved
      chunks, or the fixed insufficient-evidence sentence.
    """
    chunks = retrieve.search_documents(question, k=k)
    return await ask_claude(build_prompt(question, chunks))
