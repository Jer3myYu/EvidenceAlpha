"""Run the research agent on a question and show its observable steps.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/agent.py "What risks does Acme disclose?"
"""

import asyncio
import sys

import claude_agent_sdk

from research import agent
from research import plan as plan_module
from research import web


def show(title: str, body: str) -> None:
    """Print one stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


def observation_text(block: claude_agent_sdk.ToolResultBlock) -> str:
    """Flatten a tool result's content to plain text."""
    if isinstance(block.content, str):
        return block.content
    return "\n".join(part.get("text", "") for part in block.content or [])


async def main() -> None:
    """Stream the agent's messages and print each observable stage."""
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/agent.py "<question>"')
    try:
        web.api_key()
    except RuntimeError as error:
        sys.exit(str(error))
    question = sys.argv[1]
    show("USER QUESTION", question)

    plan = await plan_module.plan_research(question)
    show("TREE-OF-THOUGHT TRIGGER", "yes" if plan.use_tot else "no")
    if plan.use_tot:
        show(
            "RESEARCH ALTERNATIVES",
            "\n\n".join(
                f"{c.label}. {c.approach}\n   scope: {c.scope}\n"
                f"   evidence: {c.evidence}\n   coverage: {c.coverage}"
                for c in plan.candidates
            ),
        )
        chosen = plan.chosen()
        show(
            "SELECTED APPROACH",
            f"{chosen.label}. {chosen.approach}" if chosen else plan.selected,
        )
        show("REASON", plan.reason)

    actions = 0
    observations: list[str] = []
    final_answer = ""
    async for message in claude_agent_sdk.query(
        prompt=agent.research_prompt(question, plan), options=agent.OPTIONS
    ):
        if isinstance(message, claude_agent_sdk.AssistantMessage):
            for block in message.content:
                if isinstance(block, claude_agent_sdk.ToolUseBlock):
                    actions += 1
                    title = "AGENT ACTION" if actions == 1 else "NEXT ACTION"
                    show(title, block.name.removeprefix("mcp__research__"))
                    show("TOOL INPUT", str(block.input))
        elif isinstance(message, claude_agent_sdk.UserMessage):
            for block in message.content:
                if isinstance(block, claude_agent_sdk.ToolResultBlock):
                    observations.append(observation_text(block))
                    show("TOOL OBSERVATION", observations[-1])
        elif isinstance(message, claude_agent_sdk.ResultMessage):
            if message.is_error:
                sys.exit(f"Agent run failed: {message.errors}")
            final_answer = message.result or ""

    if actions == 0:
        show("AGENT ACTION", "no tool called")
    show("FINAL ANSWER", final_answer)
    sources = [
        line
        for text in observations
        for line in text.splitlines()
        if line.startswith(("[D", "[W"))
    ]
    show("SOURCES", "\n".join(sources) or "none (no tool called)")


if __name__ == "__main__":
    asyncio.run(main())
