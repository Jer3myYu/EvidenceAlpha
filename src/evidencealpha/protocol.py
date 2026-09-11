"""Strict provider output envelope for the existing portable tool protocol."""


def output_schema(allowed_tools: tuple[str, ...] | None = None) -> dict:
    """Return a closed JSON schema without changing the shared role contract."""
    string = {"type": "string"}

    def record(properties: dict) -> dict:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    def array(items: dict) -> dict:
        return {"type": "array", "items": items}

    def choice(values: list[str]) -> dict:
        return {"type": "string", "enum": values}

    tools = {
        "search_evidence": {
            "query": string,
            "source_id": {"type": ["string", "null"]},
        },
        "open_source": {
            "source_id": string,
            "chunk_id": {"type": ["string", "null"]},
            "surrounding": {"type": "integer", "minimum": 0, "maximum": 2},
        },
        "calculate": {
            "operation": choice(["add", "subtract", "multiply", "divide"]),
            "values": array(string),
        },
        "search_web": {"query": string},
        "fetch_source": {"url": string},
    }
    common = {
        "title": string,
        "caption": string,
        "source_ids": array(string),
        "period": string,
        "unit": string,
        "caveats": string,
    }
    schema = record(
        {
            "content": string,
            "tool_calls": array(
                {
                    "anyOf": [
                        record(
                            {
                                "name": choice([name]),
                                "arguments": record(arguments),
                            }
                        )
                        for name, arguments in tools.items()
                        if not allowed_tools or name in allowed_tools
                    ]
                }
            ),
            "tasks": array(
                record(
                    {
                        "role": choice(["industry", "company"]),
                        "question": string,
                    }
                )
            ),
            "figures": array(
                record(
                    {
                        **common,
                        "kind": choice(["bar", "diagram"]),
                        "labels": array(string),
                        "values": array({"type": ["number", "null"]}),
                        "nodes": array(string),
                        "edges": array(array(string)),
                    }
                )
            ),
            "issues": array(
                record(
                    {
                        "severity": choice(["material", "optional"]),
                        "location": string,
                        "evidence": string,
                        "original_passages": array(
                            record(
                                {
                                    "source_id": string,
                                    "chunk_id": string,
                                    "quote": string,
                                }
                            )
                        ),
                        "impact": string,
                        "suggestion": string,
                    }
                )
            ),
        }
    )
    if allowed_tools == ():
        schema["properties"]["tool_calls"]["maxItems"] = 0
    return schema
