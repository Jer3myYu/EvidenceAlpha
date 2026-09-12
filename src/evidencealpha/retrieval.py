"""Lexical candidates and contextual reranking without implicit inference."""

from __future__ import annotations

import dataclasses
import functools
import math
import pathlib
import re
import time
import threading
import typing

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import reading
from evidencealpha import preparation
from evidencealpha import reranking

if typing.TYPE_CHECKING:
    from evidencealpha import documents


@functools.lru_cache(maxsize=32768)
def tokens(value: str) -> frozenset[str]:
    """Preserve the evaluated binary tokenizer and its pair behavior."""
    words = set(re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", value.lower()))
    words.update(
        value[i : i + 2]
        for i in range(len(value) - 1)
        if "\u3400" <= value[i] <= "\u9fff"
    )
    return frozenset(words)


def candidates(
    store: documents.SourceStore,
    query: str,
    source_id: str | None,
    limit: int,
    check: typing.Callable[[], None] = preparation.noop,
) -> list[dict]:
    """Score eligible originals with query-local ranks."""
    check()
    sources = store.sources()
    check()
    if source_id is not None and source_id not in {s["id"] for s in sources}:
        raise ValueError("Unknown source scope")
    wanted = tokens(query)
    found = []
    for source in sources:
        if source_id is not None and source["id"] != source_id:
            continue
        for p in store.iter_passages(source["id"], check):
            check()
            score = len(
                wanted
                & tokens(p["text"] + " " + (p["generated_context"] or ""))
            ) / math.sqrt(max(1, len(tokens(p["text"]))))
            if score > 0:
                found.append({"passage": p, "lexical_score": score})
    check()
    found.sort(
        key=lambda c: (
            -c["lexical_score"],
            c["passage"]["source_id"],
            c["passage"]["spans"][0]["start"],
            c["passage"]["chunk_id"],
        )
    )
    check()
    return [{**c, "lexical_rank": i + 1} for i, c in enumerate(found[:limit])]


class Retriever:
    """Stage-local traces, neural budgets and injectable scoring."""

    def __init__(
        self,
        store: documents.SourceStore,
        settings: config.Settings,
        scorer: reranking.Scorer | None = None,
    ) -> None:
        self.cancelled = threading.Event()
        self.store = store
        self.settings = settings
        self.scorer = scorer or reranking.LocalReranker(settings)
        self.pairs = 0
        self.seconds = 0.0
        self.trace_dir: pathlib.Path | None = None
        self.cache: dict[str, list[dict]] = {}

    def close(self) -> None:
        """Close/reap the stage's optional local scorer."""
        self.cancelled.set()
        self.scorer.close()

    def search(
        self,
        query: str,
        source_id: str | None,
        question_id: str | None,
        deadline: float | None,
    ) -> dict:
        """Return selected original blocks, never the entire candidate pool."""
        started = time.monotonic()
        deadline = min(
            deadline or float("inf"),
            started + self.settings.reranker_search_seconds,
        )
        trace = {
            "query": query,
            "question_id": question_id,
            "configuration": dataclasses.asdict(self.settings),
            "status": "ready",
            "candidates": [],
            "pairs": 0,
        }
        ranked, pool, views = [], [], []
        try:
            with preparation.guard(deadline, self.cancelled) as check:
                pool = candidates(
                    self.store,
                    query,
                    source_id,
                    self.settings.candidate_limit,
                    check,
                )
                for candidate in pool:
                    check()
                    p = candidate["passage"]
                    view = reading.window(
                        self.store,
                        p["source_id"],
                        p["chunk_id"],
                        characters=self.settings.reading_window_characters,
                        check=check,
                    )
                    # Context includes originals, never generated descriptions.
                    views.append(view)
                    trace["candidates"].append(
                        {
                            "source_id": p["source_id"],
                            "chunk_id": p["chunk_id"],
                            "version": self.store.source_context(
                                p["source_id"]
                            )["version"],
                            "spans": p["spans"],
                            "lexical_rank": candidate["lexical_rank"],
                            "lexical_score": candidate["lexical_score"],
                            "context": view,
                        }
                    )
                check()
                if self.settings.retrieval_mode == "degraded_lexical":
                    trace["status"] = "degraded_lexical"
                    ranked = list(range(len(pool)))
                elif pool:
                    key = artifacts.digest(
                        {
                            "query": query,
                            "views": views,
                            "settings": trace["configuration"],
                        }
                    )
                    check()
                    if key in self.cache:
                        scores = self.cache[key]
                        trace["cache_hit"] = True
                    else:
                        reserve = 2 * len(pool)
                        if time.monotonic() >= deadline:
                            raise reranking.RerankerError("reranker_deadline")
                        # Failed work retains its reserved pair ceiling.
                        self.pairs += reserve
                        trace["pairs_reserved"] = reserve
                        scores = self.scorer.score(query, views, deadline)
                        if time.monotonic() >= deadline:
                            raise reranking.RerankerError("reranker_deadline")
                        if any(
                            s["score"] is not None
                            and not math.isfinite(s["score"])
                            for s in scores
                        ):
                            raise ValueError("Nonfinite relevance score")
                        actual = sum(s["pairs"] for s in scores)
                        if (
                            len(scores) != len(pool)
                            or not 0 <= actual <= reserve
                        ):
                            raise ValueError("Invalid scorer result")
                        self.pairs -= reserve - actual
                        trace["pairs"] = actual
                        self.cache[key] = scores
                    for c, score in zip(trace["candidates"], scores):
                        c["reranking"] = score
                    ranked = sorted(
                        (
                            i
                            for i, s in enumerate(scores)
                            if s["score"] is not None
                        ),
                        key=lambda i: (-scores[i]["score"], i),
                    )
        except (reranking.RerankerError, preparation.Stopped) as exc:
            trace["status"] = str(exc)
            trace["error"] = str(exc)
        finally:
            elapsed = time.monotonic() - started
            self.seconds += elapsed
            trace["seconds"] = elapsed
            trace["stage_pairs"] = self.pairs
            trace["stage_seconds"] = self.seconds
        selected, seen = [], set()
        for i in ranked:
            block = views[i]
            if not block["refs"] or set(block["refs"]) <= seen:
                continue
            selected.append(block)
            seen.update(block["refs"])
            if len(selected) >= self.settings.retrieval_limit:
                break
        trace["selected_blocks"] = [b["id"] for b in selected]
        manifest = None
        if self.trace_dir:
            manifest = self.trace_dir / (artifacts.digest(trace) + ".json")
            artifacts.write(manifest, trace)
        originals = {
            reading.reference(p): p for b in selected for p in b["passages"]
        }
        return {
            "passages": list(originals.values()),
            "reading_blocks": selected,
            "retrieval_status": trace["status"],
            "question_id": question_id,
            "candidate_count": len(pool),
            "trace": str(manifest) if manifest else None,
            "error": trace.get("error"),
        }
