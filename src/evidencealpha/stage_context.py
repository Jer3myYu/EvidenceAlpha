"""Durable evidence and bounded stage context, separate from audit logs."""

import copy
import json
import pathlib
import collections.abc

from evidencealpha import artifacts
from evidencealpha import documents
from evidencealpha import reading
from evidencealpha import protocol


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
        # Legacy records are upgraded in memory; callers replay into a new path.
        self.data.setdefault("schema_version", 2)
        self.data.setdefault("questions", {})
        self.data.setdefault("bundles", {})
        self.data.setdefault("stop_reason", None)
        if not self.data["questions"]:
            tasks = (
                task.get("questions")
                or task.get("unresolved_questions")
                or [
                    task.get("task", {}).get(
                        "question", task.get("brief", "Research task")
                    )
                ]
            )
            for question in tasks:
                text = (
                    question
                    if isinstance(question, str)
                    else json.dumps(question, ensure_ascii=False)
                )
                details = question if isinstance(question, dict) else {}
                text = details.get("question", text)
                qid = details.get("id", "q-" + artifacts.digest(text)[:12])
                self.data["questions"][qid] = {
                    "question": text,
                    "priority": details.get("priority", "essential"),
                    "state": "unresolved",
                    "source_id": details.get("source_id"),
                    "next_gap": text,
                    "next_action": "focused search",
                    "exploration": "active",
                    "provisional": True,
                }
        if not path.exists():
            self._save()

    def _save(self) -> None:
        artifacts.write(self.path, self.data)

    def settle(self, result: dict, question_id: str | None = None) -> None:
        """Preserve originals before selection; create provisional bundles."""
        incoming = documents.ungroup_passages(result)
        if not incoming:
            return
        qid = question_id or result.get("question_id")
        if qid is None and len(self.data["questions"]) == 1:
            qid = next(iter(self.data["questions"]))
        if qid and qid not in self.data["questions"]:
            raise ValueError("Unknown evidence question")
        by_ref = {
            reading.reference(p): p
            for p in documents.ungroup_passages(self.data["evidence"])
        }
        for passage in incoming:
            ref = reading.reference(passage)
            if ref in by_ref and by_ref[ref]["text"] != passage["text"]:
                raise ValueError("Settled original changed at its locator")
            by_ref[ref] = passage
        grouped = documents.group_passages(list(by_ref.values()))
        blocks = result.get("reading_blocks") or [
            {
                "id": reading.reference(p),
                "refs": [reading.reference(p)],
                "status": "unassessed",
            }
            for p in incoming
        ]
        bundles = dict(self.data["bundles"])
        for block in blocks:
            refs = block["refs"]
            if not set(refs) <= by_ref.keys():
                raise ValueError("Block references unavailable originals")
            bid = artifacts.digest({"refs": sorted(refs), "question_id": qid})
            bundles.setdefault(
                bid,
                {
                    "refs": sorted(refs),
                    "question_id": qid,
                    "adequacy": "unassessed",
                    "relation": "supports",
                    "structure": block.get("status", "unassessed"),
                    "association": block.get("association", "unknown"),
                    "continuations": block.get("continuations", []),
                },
            )
        self.data.update(evidence=grouped, bundles=bundles)
        self._save()

    def update_coverage(
        self, updates: list[dict], stop_reason: str | None = None
    ) -> None:
        """Validate references atomically, not semantic judgments."""
        questions = copy.deepcopy(self.data["questions"])
        bundles = copy.deepcopy(self.data["bundles"])
        for update in updates:
            qid = update["question_id"]
            if qid not in questions:
                if update.get("parent_id") not in questions or not update.get(
                    "question"
                ):
                    raise ValueError("New question requires an existing parent")
                questions[qid] = {
                    **questions[update["parent_id"]],
                    "question": update["question"],
                    "parent_id": update["parent_id"],
                    "state": "unresolved",
                }
            question = questions[qid]
            state = update.get("state", question["state"])
            if state not in (
                "unresolved",
                "partial",
                "supported",
                "conflicting",
            ):
                raise ValueError("Invalid provisional coverage state")
            adequacy = update.get("adequacy", "unassessed")
            if adequacy not in ("adequate", "unassessed"):
                raise ValueError("Invalid support adequacy")
            ids = update.get("bundle_ids", [])
            if not set(ids) <= bundles.keys():
                raise ValueError("Coverage references unknown bundles")
            if state in ("supported", "conflicting") and not ids:
                raise ValueError(
                    "Supported/conflicting coverage needs references"
                )
            if state == "conflicting" and len(ids) < 2:
                raise ValueError("Conflicting support requires both positions")
            scope = question.get("source_id")
            known = {
                reading.reference(p): p
                for p in documents.ungroup_passages(self.data["evidence"])
            }
            if scope and any(
                known[r]["source_id"] != scope
                for i in ids
                for r in bundles[i]["refs"]
            ):
                raise ValueError("Coverage reference is outside question scope")
            if ids:
                for old in bundles.values():
                    if old["question_id"] == qid:
                        old["adequacy"] = "unassessed"
                refs = sorted(
                    {ref for bid in ids for ref in bundles[bid]["refs"]}
                )
                # All IDs in an update are required together, not independent
                # adequate alternatives. Existing originals remain unassessed.
                relation = "conflicts" if state == "conflicting" else "supports"
                bid = artifacts.digest(
                    {"refs": refs, "question_id": qid, "relation": relation}
                )
                bundles[bid] = {
                    "refs": refs,
                    "question_id": qid,
                    "adequacy": adequacy,
                    "relation": relation,
                    "association": "provisional",
                    "structure": (
                        "complete_window"
                        if all(
                            bundles[i]["structure"] == "complete_window"
                            for i in ids
                        )
                        else "partial_parent"
                    ),
                    "continuations": sorted(
                        {c for i in ids for c in bundles[i]["continuations"]}
                    ),
                }
                if state == "supported" and adequacy != "adequate":
                    raise ValueError(
                        "Supported coverage needs adequate provisional support"
                    )
            exploration = update.get("exploration", question["exploration"])
            if exploration not in ("active", "exhausted"):
                raise ValueError("Invalid exploration status")
            question.update(
                state=state,
                exploration=exploration,
                next_gap=update.get("next_gap", ""),
                next_action=update.get("next_action", ""),
                provisional=True,
            )
        self.data.update(questions=questions, bundles=bundles)
        if stop_reason:
            self.data["stop_reason"] = stop_reason
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
        if passages:
            self.data["recent_refs"] = [reading.reference(p) for p in passages]
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

    def _fixed(self) -> dict:
        task = copy.deepcopy(self.data["task"])
        task.pop("required_original_refs", None)
        return {
            **task,
            "unresolved_questions": task.get("unresolved_questions", []),
            "recent_tool_outcomes": self.data["recent_outcomes"],
            "unsuccessful_queries": {
                "items": list(self.data["unsuccessful_queries"].values())[-16:],
                "omitted": max(0, len(self.data["unsuccessful_queries"]) - 16),
            },
            "context_record": str(self.path),
            "stop_reason": self.data["stop_reason"],
        }

    def _view(
        self, selected: set[str], originals: dict, phase: str
    ) -> tuple[dict, dict]:
        omitted = sorted(originals.keys() - selected)
        bundles = self.data["bundles"]
        coverage = {}
        for qid, question in sorted(self.data["questions"].items()):
            related = [b for b in bundles.values() if b["question_id"] == qid]
            available = [b for b in related if set(b["refs"]) <= selected]
            adequate = any(
                b["adequacy"] == "adequate"
                and b["structure"] == "complete_window"
                for b in available
            )
            delivered = question["state"]
            if delivered == "supported" and not adequate:
                delivered = "partial" if available else "unresolved"
            if delivered == "conflicting" and not any(
                b["relation"] == "conflicts" and len(b["refs"]) > 1
                for b in available
            ):
                delivered = "partial" if available else "unresolved"
            coverage[qid] = {**question, "delivered_state": delivered}
        manifest = {
            "policy": "coverage-payload-1",
            "phase": phase,
            "selected": sorted(selected),
            "omitted": [
                {
                    "ref": r,
                    "reason": "payload_limit",
                    "original": {
                        k: originals[r].get(k)
                        for k in ("source_id", "version", "chunk_id", "spans")
                    },
                }
                for r in omitted
            ],
            "omitted_bundles": sorted(
                bid
                for bid, b in bundles.items()
                if not set(b["refs"]) <= selected
            ),
        }
        digest = artifacts.digest(manifest)
        manifest_path = self.path.parent / "selections" / (digest + ".json")
        previews = []
        for r in omitted[:8]:
            item = manifest["omitted"][len(previews)]["original"]
            if (
                len(json.dumps(previews + [item], ensure_ascii=False).encode())
                > 2048
            ):
                break
            previews.append(item)
        ordered = sorted(
            (originals[r] for r in selected),
            key=lambda p: (
                p["source_id"],
                p["spans"][0]["start"],
                reading.reference(p),
            ),
        )
        evidence = {
            "status": "unsynthesized_evidence",
            **documents.compact_passages(documents.group_passages(ordered)),
            "omitted_passages": previews,
            "omitted_reference_count": len(omitted),
            "unlisted_reference_count": len(omitted) - len(previews),
            "full_evidence_record": str(self.path),
            "selection_manifest": str(manifest_path),
            "selection_hash": digest,
            "limitation": "Provisional support, not factual certification",
            "reading_limitations": {
                "incomplete_bundles": sum(
                    1
                    for b in bundles.values()
                    if set(b["refs"]) <= selected
                    and b["structure"] != "complete_window"
                ),
                "unknown_associations": sum(
                    1
                    for b in bundles.values()
                    if set(b["refs"]) <= selected
                    and b.get("association", "unknown") != "structural"
                ),
            },
        }
        # Compact bundle IDs are needed for model updates; original refs are
        # already bound in the immutable disk record, not repeated as text.
        visible_bundles = {
            bid: {
                "question_id": b["question_id"],
                "adequacy": b["adequacy"],
                "originals": [
                    {
                        "source_id": originals[r]["source_id"],
                        "chunk_id": originals[r].get("chunk_id"),
                    }
                    for r in b["refs"]
                ],
                "structure": b["structure"],
                "continuation": (b["continuations"] or [None])[0],
            }
            for bid, b in bundles.items()
            if phase != "final_notes" and set(b["refs"]) <= selected
        }
        priorities = {"essential": 0, "important": 1, "optional": 2}
        pending_questions = sorted(
            (
                qid
                for qid, q in coverage.items()
                if q["state"] != "supported" and q["exploration"] == "active"
            ),
            key=lambda qid: (priorities.get(coverage[qid]["priority"], 2), qid),
        )
        return {
            **self._fixed(),
            "next_question_id": (
                pending_questions[0] if pending_questions else None
            ),
            "questions": coverage,
            "support_bundles": visible_bundles,
            "settled_evidence": evidence,
        }, manifest

    def _select(
        self,
        max_bytes: int,
        phase: str,
        serialize: collections.abc.Callable[[dict], str],
        extra_bytes: int = 0,
        max_tokens: int | None = None,
    ) -> tuple[str, dict]:
        originals = {
            reading.reference(p): p
            for p in documents.ungroup_passages(self.data["evidence"])
        }
        limit = min(
            max_bytes, max_tokens if max_tokens is not None else max_bytes
        )

        def trial(refs: set[str]) -> tuple[str, dict, dict, bool]:
            view, manifest = self._view(refs, originals, phase)
            encoded = serialize(view)
            return (
                encoded,
                view,
                manifest,
                len(encoded.encode()) + extra_bytes <= limit,
            )

        all_refs = set(originals)
        if (
            not set(self.data["task"].get("required_original_refs", []))
            <= all_refs
        ):
            raise ValueError("Required writing originals are unavailable")
        encoded, view, manifest, fits = trial(all_refs)
        if not fits:
            chosen = set(self.data["task"].get("required_original_refs", []))
            if not chosen <= all_refs:
                raise ValueError("Required writing originals are unavailable")
            if not trial(chosen)[3]:
                raise ValueError(
                    "Task and required disclosure exceed context budget"
                )
            priority = {"essential": 0, "important": 1, "optional": 2}
            questions = self.data["questions"]
            bundles = dict(self.data["bundles"])
            # Legacy originals without bundles remain eligible background.
            linked = {r for b in bundles.values() for r in b["refs"]}
            for ref in all_refs - linked:
                bundles[ref] = {
                    "refs": [ref],
                    "question_id": None,
                    "adequacy": "unassessed",
                    "relation": "background",
                }
            for tier in range(4):
                # Adequate support precedes unassessed within each priority
                # tier, irrespective of arrival, size or issuer. Round-robin
                # questions prevents one question taking all peers' capacity.
                for adequacy in ("adequate", "unassessed"):
                    pending = {
                        bid: b
                        for bid, b in bundles.items()
                        if b["adequacy"] == adequacy
                        and priority.get(
                            questions.get(b["question_id"], {}).get("priority"),
                            3,
                        )
                        == tier
                    }
                    while pending:
                        progress = False
                        qids = sorted(
                            {b["question_id"] or "" for b in pending.values()},
                            key=lambda qid: (
                                phase == "evidence"
                                and questions.get(qid, {}).get("state")
                                == "supported",
                                qid,
                            ),
                        )
                        for qid in qids:
                            options = [
                                (bid, b)
                                for bid, b in pending.items()
                                if (b["question_id"] or "") == qid
                            ]
                            options.sort(
                                key=lambda pair: (
                                    -int(
                                        pair[1].get("relation") == "conflicts"
                                    ),
                                    (
                                        -len(
                                            set(pair[1]["refs"]).intersection(
                                                self.data.get("recent_refs", [])
                                            )
                                        )
                                        if phase == "evidence"
                                        else 0
                                    ),
                                    sum(
                                        len(originals[r]["text"].encode())
                                        for r in set(pair[1]["refs"]) - chosen
                                    ),
                                    pair[0],
                                )
                            )
                            for bid, bundle in options:
                                attempt = chosen | set(bundle["refs"])
                                # A known support dependency remains atomic even
                                # through an older unassessed alias of its fact.
                                while True:
                                    expanded = set(attempt)
                                    for support in bundles.values():
                                        adequate = (
                                            support["adequacy"] == "adequate"
                                        )
                                        overlaps = attempt.intersection(
                                            support["refs"]
                                        )
                                        if adequate and overlaps:
                                            expanded.update(support["refs"])
                                    if expanded == attempt:
                                        break
                                    attempt = expanded
                                if trial(attempt)[3]:
                                    chosen = attempt
                                    del pending[bid]
                                    progress = True
                                    break
                        if not progress:
                            break
            encoded, view, manifest, fits = trial(chosen)
        if not fits:
            raise ValueError("Context selection failed its final payload bound")
        artifacts.write(
            pathlib.Path(view["settled_evidence"]["selection_manifest"]),
            manifest,
        )
        artifacts.write(
            self.path.parent / "request-size.json",
            {
                "application_utf8_bytes": len(encoded.encode()) + extra_bytes,
                "token_estimate": len(encoded.encode()) + extra_bytes,
                "token_method": "UTF-8 byte estimate; not measured tokens",
                "transport_added_context": "unobservable",
                "max_bytes": max_bytes,
                "max_input_tokens": max_tokens,
            },
        )
        return encoded, view

    def build(self, max_bytes: int) -> dict:
        """Build a portable fallback using the authoritative selector."""
        return self._select(
            max_bytes,
            "final_notes",
            lambda view: json.dumps(view, ensure_ascii=False),
        )[1]

    def request(
        self,
        instructions: str,
        tools: dict,
        phase: str,
        remaining_calls: int,
        max_bytes: int,
        max_tokens: int | None = None,
    ) -> tuple[str, dict]:
        """Measure framing, escaping and the exact separate output schema."""

        def serialize(view: dict) -> str:
            return json.dumps(
                {
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
                        "Use delivered originals; disclose gaps. No tools."
                        if phase == "final_notes"
                        else "Follow the next gap; update provisional coverage."
                    ),
                },
                ensure_ascii=False,
            )

        schema = (
            json.dumps(
                protocol.output_schema(tuple(tools)),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return self._select(
            max_bytes, phase, serialize, len(schema.encode()), max_tokens
        )
