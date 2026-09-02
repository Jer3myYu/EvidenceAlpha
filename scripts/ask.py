"""Ask a question and show every stage on the way to the answer.

Usage::

    .venv/bin/python scripts/ask.py "What risks does Acme disclose?"
"""

import asyncio
import sys

from rag import retrieve
from research import answer


def show(title: str, body: str) -> None:
    """Print one numbered stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


async def main() -> None:
    """Run the Phase 2 flow step by step and print each stage."""
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/ask.py "<question>"')
    question = sys.argv[1]
    show("1. USER QUESTION", question)

    chunks = retrieve.search_documents(question, k=5)
    show(
        "2. RETRIEVED CHUNKS",
        "\n\n".join(
            f"[{n}] source: {c.source}\n    distance: {c.score:.4f}\n{c.text}"
            for n, c in enumerate(chunks, start=1)
        ),
    )

    prompt = answer.build_prompt(question, chunks)
    show(
        "3. PROMPT / EVIDENCE SENT TO CLAUDE",
        f"[system prompt]\n{answer.SYSTEM_PROMPT}\n[user message]\n{prompt}",
    )

    show("4. CLAUDE ANSWER", await answer.ask_claude(prompt))

    show(
        "5. SOURCES",
        "\n".join(f"[{n}] {c.source}" for n, c in enumerate(chunks, start=1)),
    )


if __name__ == "__main__":
    asyncio.run(main())
