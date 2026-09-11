"""Subprocess boundary for the installed official Claude Agent SDK."""

import asyncio
import dataclasses
import json
import sys

import claude_agent_sdk


def normalize(message: object) -> list[dict]:
    """Serialize supported SDK events across the subprocess boundary."""
    if isinstance(message, claude_agent_sdk.RateLimitEvent):
        return [{"kind": "rate_limit", **dataclasses.asdict(message)}]
    if isinstance(message, claude_agent_sdk.ResultMessage):
        value = dataclasses.asdict(message)
        return [{"kind": "result", "text": value.pop("result", None), **value}]
    if isinstance(message, claude_agent_sdk.AssistantMessage):
        return [
            {"kind": "text", "text": block.text, "model": message.model}
            for block in message.content
            if isinstance(block, claude_agent_sdk.TextBlock)
        ]
    return []


def usage_exhausted(event: dict) -> bool:
    """Recognize a rejected subscription window, not an arbitrary HTTP 429."""
    info = event.get("rate_limit_info", {})
    return (
        event.get("kind") == "rate_limit"
        and info.get("status") == "rejected"
        and info.get("rate_limit_type")
        in {
            "five_hour",
            "seven_day",
            "seven_day_opus",
            "seven_day_sonnet",
            "overage",
        }
    )


async def main() -> None:
    """Stream visible text/tool-free result metadata without hidden
    reasoning.
    """
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=sys.argv[1],
        effort=sys.argv[2],
        tools=[],
        allowed_tools=[],
        mcp_servers={},
        strict_mcp_config=True,
        setting_sources=[],
        skills=[],
        max_turns=1,
        permission_mode="dontAsk",
        plugins=[],
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    async for message in claude_agent_sdk.query(
        prompt=sys.stdin.read(), options=options
    ):
        for event in normalize(message):
            print(json.dumps(event), flush=True)
            if usage_exhausted(event):
                # Exit the SDK stream immediately; no wait for quota reset.
                return


if __name__ == "__main__":
    asyncio.run(main())
