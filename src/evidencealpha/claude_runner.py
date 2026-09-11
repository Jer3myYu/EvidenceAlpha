"""Subprocess boundary for the installed official Claude Agent SDK."""

import asyncio
import dataclasses
import json
import sys

import claude_agent_sdk


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
        if isinstance(message, claude_agent_sdk.ResultMessage):
            value = dataclasses.asdict(message)
            print(
                json.dumps(
                    {
                        "kind": "result",
                        "text": value.get("result"),
                        "usage": value.get("usage"),
                        "session_id": value.get("session_id"),
                        "is_error": value.get("is_error"),
                        "subtype": value.get("subtype"),
                    }
                ),
                flush=True,
            )
        elif isinstance(message, claude_agent_sdk.AssistantMessage):
            for block in message.content:
                if isinstance(block, claude_agent_sdk.TextBlock):
                    print(
                        json.dumps(
                            {
                                "kind": "text",
                                "text": block.text,
                                "model": message.model,
                            }
                        ),
                        flush=True,
                    )


if __name__ == "__main__":
    asyncio.run(main())
