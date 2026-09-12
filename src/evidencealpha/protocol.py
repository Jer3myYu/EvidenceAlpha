"""Strict provider output envelope for the existing portable tool protocol."""

import json

from evidencealpha import review


def output_schema(allowed_tools: tuple[str, ...] | None = None) -> dict:
    """Return the shared tool envelope and user-focused review rubric."""
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
            "question_id": {"type": ["string", "null"]},
            "source_id": {"type": ["string", "null"]},
        },
        "open_source": {
            "source_id": string,
            "question_id": {"type": ["string", "null"]},
            "page": {"type": ["integer", "null"], "minimum": 1},
            "continuation": {"type": ["string", "null"]},
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
            "rubric": array(
                record(
                    {
                        "criterion": choice(list(review.CRITERIA)),
                        "rating": choice(list(review.RATINGS)),
                        "explanation": string,
                    }
                )
            ),
            "decision": choice(["", *review.DECISIONS]),
            "review_scope": string,
            "review_limitations": string,
            "resolutions": array(
                record(
                    {
                        "id": string,
                        "status": choice(["resolved", "unresolved"]),
                        "explanation": string,
                    }
                )
            ),
            "scope": array(
                record(
                    {
                        "id": string,
                        "status": choice(
                            [
                                "supported",
                                "partial",
                                "unresolved",
                                "undisclosed",
                                "examined",
                                "unexamined",
                            ]
                        ),
                        "explanation": string,
                        "original_passages": array(
                            record(
                                {
                                    "source_id": string,
                                    "chunk_id": string,
                                    "quote": string,
                                }
                            )
                        ),
                    }
                )
            ),
            "content": string,
            "stop_reason": {"type": ["string", "null"]},
            "coverage_updates": array(
                record(
                    {
                        "question_id": string,
                        "parent_id": {"type": ["string", "null"]},
                        "question": string,
                        "state": choice(
                            [
                                "unresolved",
                                "partial",
                                "supported",
                                "conflicting",
                            ]
                        ),
                        "bundle_ids": array(string),
                        "adequacy": choice(["adequate", "unassessed"]),
                        "exploration": choice(["active", "exhausted"]),
                        "next_gap": string,
                        "next_action": string,
                    }
                )
            ),
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
                        "kind": choice(list(review.ISSUE_KINDS)),
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


def encoded_schema(allowed_tools: tuple[str, ...] | None = None) -> str:
    """Encode the unchanged schema identically for admission and provider."""
    return (
        json.dumps(
            output_schema(allowed_tools),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )
