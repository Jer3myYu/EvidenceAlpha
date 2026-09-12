"""Local-only reranker process with finite resource supervision.

No model is imported or loaded until score() is explicitly invoked with a
verified local snapshot. Defaults are provisional, not feasibility evidence.
"""

from __future__ import annotations

import dataclasses
import json
import re
import hashlib
import multiprocessing
import pathlib
import threading
import time
import typing

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import preparation

_SLOT = threading.BoundedSemaphore(1)
_ACTIVE: set[LocalReranker] = set()
_LOCK = threading.Lock()


class RerankerError(RuntimeError):
    """An explicit failure status, never silent fallback."""


class Scorer(typing.Protocol):
    """Injectable query/context scoring boundary."""

    def score(
        self, query: str, views: list[dict], deadline: float
    ) -> list[dict]:
        """Return query-local scores and scored original views."""

    def close(self) -> None:
        """Release resources."""


def cancel_all() -> None:
    """Cancel local inference alongside provider cancellation."""
    preparation.cancel_all()
    with _LOCK:
        active = list(_ACTIVE)
    for scorer in active:
        scorer.cancelled.set()
        process = scorer.process
        if process is not None and process.is_alive():
            process.terminate()


def bounded_views(
    query: str, view: dict, count: typing.Callable[[str, str], int], limit: int
) -> list[str]:
    """Build at most two whole-original windows without tokenizer truncation."""
    passages = view["passages"]
    if not passages:
        return []
    identity = view.get("identity_text", "")
    full = identity + "\n" + "\n".join(p["text"] for p in passages)
    if count(query, full) <= limit:
        return [full]
    # For tables, preserve focal row, original first row and nearby context.
    # Paragraphs may use whole sentences; never slice a tokenized string.
    units = []
    focal = view.get("focus", passages[0]["spans"][0]["start"])
    for passage in passages:
        text = passage["text"]
        start = passage["spans"][0]["start"]
        is_table = passage.get("kind") == "table"
        parts = (
            [(0, len(text))]
            if is_table
            else [
                (m.start(), m.end())
                for m in re.finditer(r"[^。！？.!?]+[。！？.!?]*", text)
            ]
        )
        for a, z in parts:
            units.append(
                (
                    text[a:z],
                    start + a <= focal < start + z,
                    passage.get("required_context", False)
                    or any(
                        start + a < span["end"] and start + z > span["start"]
                        for span in view.get("dense_required_spans", [])
                    ),
                )
            )
    centers = [i for i, u in enumerate(units) if u[1]]
    if not centers:
        return []
    center = centers[0]
    required = {i for i, u in enumerate(units) if u[2]} | {center}
    # A sentence tail can require its preceding subject; retain both neighbors.
    if center:
        required.add(center - 1)
    if center + 1 < len(units):
        required.add(center + 1)

    def assemble(indices: set[int]) -> str:
        return identity + "\n" + "\n".join(units[i][0] for i in sorted(indices))

    if count(query, assemble(required)) > limit:
        return []
    windows = []
    for direction in (-1, 1):
        chosen = set(required)
        for i in sorted(
            range(len(units)),
            key=lambda i, direction=direction: (abs(i - center), direction * i),
        ):
            if count(query, assemble(chosen | {i})) <= limit:
                chosen.add(i)
        text = assemble(chosen)
        if text not in windows:
            windows.append(text)
    return windows


def _worker(connection: typing.Any, settings: dict) -> None:
    """Load only explicit local files; invoked solely in a supervised child."""
    try:
        # Optional dependencies must not be imported by deterministic tests.
        import torch  # pylint: disable=import-outside-toplevel
        import transformers  # pylint: disable=import-outside-toplevel

        initialized = time.monotonic()
        torch.set_num_threads(settings["reranker_threads"])
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            settings["reranker_path"],
            local_files_only=True,
            trust_remote_code=False,
        )
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            settings["reranker_path"],
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.float32,
        ).eval()
        initialization_seconds = time.monotonic() - initialized
        while True:
            query, views = connection.recv()
            if (
                len(tokenizer.encode(query, add_special_tokens=False))
                > settings["reranker_query_tokens"]
            ):
                connection.send({"error": "focused_query_required"})
                continue
            scoring_started = time.monotonic()
            results = []
            window_scores = {}
            for view in views:
                windows = bounded_views(
                    query,
                    view,
                    lambda q, t: len(
                        tokenizer(q, t, truncation=False)["input_ids"]
                    ),
                    settings["reranker_pair_tokens"],
                )
                logits = []
                evaluated = 0
                for text in windows:
                    if text in window_scores:
                        logits.append(window_scores[text])
                        continue
                    encoded = tokenizer(
                        query, text, truncation=False, return_tensors="pt"
                    )
                    with torch.inference_mode():
                        value = float(model(**encoded).logits.reshape(-1)[0])
                    window_scores[text] = value
                    logits.append(value)
                    evaluated += 1
                results.append(
                    {
                        "score": max(logits) if logits else None,
                        "pairs": evaluated,
                        "scored_views": windows,
                        "status": (
                            (
                                "context_incomplete"
                                if logits
                                and windows
                                != [
                                    view.get("identity_text", "")
                                    + "\n"
                                    + "\n".join(
                                        p["text"] for p in view["passages"]
                                    )
                                ]
                                else "ready"
                            )
                            if logits
                            else "context_too_large"
                        ),
                    }
                )
            connection.send(
                {
                    "results": results,
                    "metrics": {
                        "initialization_seconds": initialization_seconds,
                        "scoring_seconds": time.monotonic() - scoring_started,
                    },
                }
            )
    except (ImportError, OSError, ValueError, RuntimeError, EOFError) as exc:
        try:
            connection.send(
                {"error": "reranker_unavailable", "detail": str(exc)}
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


class LocalReranker:
    """Stage-owned, globally serialized and cancellable local inference."""

    def __init__(self, settings: config.Settings) -> None:
        self.settings = settings
        self.process: typing.Any = None
        self.connection: typing.Any = None
        self.cancelled = threading.Event()

    def _snapshot(self) -> None:
        path = pathlib.Path(self.settings.reranker_path or "")
        manifest = path / "snapshot.json"
        if not self.settings.reranker_path or not manifest.is_file():
            raise RerankerError("reranker_unavailable")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sha = data.get("revision", "")
        if (
            data.get("model") != self.settings.reranker_model
            or len(sha) != 40
            or not sha.startswith(self.settings.reranker_revision)
            or not data.get("files")
        ):
            raise RerankerError("reranker_snapshot_mismatch")
        for name, digest in data["files"].items():
            file = artifacts.contained(path, name)
            if not file.is_file():
                raise RerankerError("reranker_snapshot_mismatch")
            hasher = hashlib.sha256()
            with file.open("rb") as stream:
                for block in iter(
                    lambda stream=stream: stream.read(1024 * 1024), b""
                ):
                    hasher.update(block)
            if hasher.hexdigest() != digest:
                raise RerankerError("reranker_snapshot_mismatch")

    def score(
        self, query: str, views: list[dict], deadline: float
    ) -> list[dict]:
        """Supervise elapsed time and RSS; never download or change scorer."""
        started = time.monotonic()
        self.last_metrics = {"sampled_peak_rss": 0}
        self._snapshot()
        if not _SLOT.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RerankerError("reranker_deadline")
        try:
            if time.monotonic() >= deadline:
                raise RerankerError("reranker_deadline")
            if self.cancelled.is_set():
                raise RerankerError("reranker_cancelled")
            if self.process is None:
                ctx = multiprocessing.get_context("spawn")
                self.connection, child = ctx.Pipe()
                self.process = ctx.Process(
                    target=_worker,
                    args=(child, dataclasses.asdict(self.settings)),
                    daemon=True,
                )
                self.process.start()
                child.close()
                with _LOCK:
                    _ACTIVE.add(self)
            self.connection.send((query, views))
            while not self.connection.poll(0.02):
                if self.cancelled.is_set():
                    raise RerankerError("reranker_cancelled")
                if time.monotonic() >= deadline:
                    raise RerankerError("reranker_deadline")
                if not self.process.is_alive():
                    raise RerankerError("reranker_unavailable")
                status = pathlib.Path(
                    f"/proc/{self.process.pid}/status"
                ).read_text(encoding="utf-8")
                rss = next(
                    int(line.split()[1]) * 1024
                    for line in status.splitlines()
                    if line.startswith("VmRSS:")
                )
                self.last_metrics["sampled_peak_rss"] = max(
                    rss, self.last_metrics["sampled_peak_rss"]
                )
                if rss > self.settings.reranker_memory_bytes:
                    raise RerankerError("reranker_resource_exhausted")
            if self.cancelled.is_set():
                raise RerankerError("reranker_cancelled")
            if time.monotonic() >= deadline:
                raise RerankerError("reranker_deadline")
            result = self.connection.recv()
            if "error" in result:
                raise RerankerError(result["error"])
            self.last_metrics.update(result.get("metrics", {}))
            return result["results"]
        except (OSError, EOFError, StopIteration) as exc:
            self.close()
            raise RerankerError("reranker_unavailable") from exc
        except RerankerError:
            self.close()
            raise
        finally:
            self.last_metrics["total_seconds"] = time.monotonic() - started
            self.close()
            _SLOT.release()

    def close(self) -> None:
        """Terminate and reap a child on success, failure or cancellation."""
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        with _LOCK:
            _ACTIVE.discard(self)
