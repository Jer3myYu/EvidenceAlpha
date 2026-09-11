"""Durable evidence and bounded stage context, separate from audit logs."""

import copy
import json
import pathlib

from evidencealpha import artifacts
from evidencealpha import documents


def _compact(value: object, limit: int = 1200) -> object:
    """Bound navigation metadata; keep originals and requirements intact."""
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) <= limit:
        return value
    return {
        "preview": encoded[:limit],
        "truncated": True,
        "hash": artifacts.digest(value),
    }


class StageContext:
    """Derive model and fallback views from one durable collection."""

    def __init__(self, path: pathlib.Path, task: dict) -> None:
        self.path = path
        if path.exists():
            self.data = artifacts.read(path)
            if self.data["task"] != task:
                raise ValueError("Saved stage task changed")
        else:
            self.data = {
                "task": copy.deepcopy(task),
                "evidence": {"sources": []},
                "recent_outcomes": [],
                "unsuccessful_queries": {},
            }
            self._save()

    def _save(self) -> None:
        artifacts.write(self.path, self.data)

    def settle(self, result: dict) -> None:
        """Deduplicate by immutable source version and locator."""
        passages = documents.ungroup_passages(self.data["evidence"])
        by_locator = {
            (p["source_id"], p.get("chunk_id"), artifacts.digest(p["spans"])): p
            for p in passages
        }
        for passage in documents.ungroup_passages(result):
            key = (
                passage["source_id"],
                passage.get("chunk_id"),
                artifacts.digest(passage["spans"]),
            )
            old = by_locator.get(key)
            if old and old != passage:
                raise ValueError(
                    "Settled original/version changed at its locator"
                )
            by_locator[key] = passage
        self.data["evidence"] = documents.group_passages(
            list(by_locator.values())
        )
        self._save()

    def outcome(
        self,
        name: str,
        arguments: dict,
        result: object,
        status: str | None = None,
    ) -> None:
        """Retain recent actions and unsuccessful queries."""
        passages = (
            documents.ungroup_passages(result)
            if isinstance(result, dict)
            else []
        )
        if status is None:
            status = (
                "error"
                if isinstance(result, dict) and "error" in result
                else (
                    "no_results"
                    if name == "search_evidence" and not passages
                    else "returned"
                )
            )
        entry = {
            "tool": name,
            "arguments": _compact(arguments),
            "status": status,
            "passage_count": len(passages),
        }
        if not passages:
            entry["result"] = _compact(result)
        self.data["recent_outcomes"] = (self.data["recent_outcomes"] + [entry])[
            -8:
        ]
        if name == "search_evidence":
            key = artifacts.digest(arguments)
            if status in ("error", "no_results", "not_executed"):
                self.data["unsuccessful_queries"][key] = entry
            elif status == "returned":
                # This tracks whether a query returned passages, not whether
                # the underlying research question has been answered.
                self.data["unsuccessful_queries"].pop(key, None)
        self._save()

    def build(self, max_bytes: int) -> dict:
        """Build research, writing and fallback context under one byte bound.

        Task and explicit unresolved questions stay intact. Omitted original
        text and locators remain durable, with previews when they fit.
        """
        task = copy.deepcopy(self.data["task"])
        fixed = {
            **task,
            "unresolved_questions": task.get("unresolved_questions", []),
            "recent_tool_outcomes": self.data["recent_outcomes"],
            "unsuccessful_queries": {
                "items": list(self.data["unsuccessful_queries"].values())[-16:],
                "omitted": max(0, len(self.data["unsuccessful_queries"]) - 16),
            },
            "context_record": str(self.path),
        }
        if (
            len(json.dumps(fixed, ensure_ascii=False).encode()) + 1000
            > max_bytes
        ):
            raise ValueError(
                "Task and recent outcomes exceed stage context limit"
            )
        passages = documents.ungroup_passages(self.data["evidence"])
        characters = 16000
        while True:
            view = documents.evidence_handoff(
                passages, max_characters=characters
            )
            omitted = view["omitted_passages"]
            view["omitted_reference_count"] = len(omitted)
            view["full_evidence_record"] = str(self.path)
            payload = {**fixed, "settled_evidence": view}
            if (
                len(json.dumps(payload, ensure_ascii=False).encode())
                <= max_bytes
            ):
                return payload
            if characters:
                characters //= 2
                continue
            # References are never deleted from the durable collection. A
            # bounded preview cannot pretend all omitted originals were read.
            while (
                omitted
                and len(json.dumps(payload, ensure_ascii=False).encode())
                > max_bytes
            ):
                omitted.pop()
            view["unlisted_reference_count"] = view[
                "omitted_reference_count"
            ] - len(omitted)
            if (
                len(json.dumps(payload, ensure_ascii=False).encode())
                > max_bytes
            ):
                raise ValueError("Stage context cannot fit required disclosure")
            return payload

    def request(
        self,
        instructions: str,
        tools: dict,
        phase: str,
        remaining_calls: int,
        max_bytes: int,
    ) -> tuple[str, dict]:
        """Include framing/escaping in the bound, not just passage text."""
        budget = max_bytes
        while True:
            view = self.build(budget)
            request = {
                "phase": phase,
                "messages": [
                    {"role": "system", "content": instructions},
                    {
                        "role": "user",
                        "content": json.dumps(view, ensure_ascii=False),
                    },
                ],
                "tools": tools,
                "remaining_calls": remaining_calls,
                "turn_instruction": (
                    "Final call: use settled evidence; disclose gaps; no tools."
                    if phase == "final_notes"
                    else "Gather efficiently. Consult recent outcomes and "
                    "unsuccessful queries before repeating work."
                ),
            }
            prompt = json.dumps(request, ensure_ascii=False)
            excess = len(prompt.encode()) - max_bytes
            if excess <= 0:
                return prompt, view
            budget -= excess
