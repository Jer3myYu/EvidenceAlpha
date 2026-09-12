"""Local-only supervised embedding/index operations for normal retrieval."""

# Optional local inference dependencies are loaded only when selected.
# pylint: disable=import-outside-toplevel

import dataclasses
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import typing

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import preparation

_SLOT = threading.Lock()


def supervised(
    request: dict,
    python: str,
    deadline: float,
    memory_bytes: int,
    check: typing.Callable[[], None] = preparation.noop,
    record_dir: pathlib.Path | None = None,
) -> dict:
    """Supervise local work with cancellation, memory and elapsed checks."""
    while not _SLOT.acquire(timeout=0.05):
        check()
        if time.monotonic() >= deadline:
            raise TimeoutError("Dense worker admission deadline")
    process = None
    try:
        check()
        if time.monotonic() >= deadline:
            raise TimeoutError("Dense worker admission deadline")
        with tempfile.TemporaryDirectory(prefix="evidencealpha-dense-") as temp:
            folder = record_dir or pathlib.Path(temp)
            folder.mkdir(parents=True, exist_ok=True)
            request_path = folder / "request.json"
            artifacts.write(request_path, request)
            env = dict(os.environ)
            env.update(
                PYTHONPATH=str(pathlib.Path(__file__).resolve().parent.parent),
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                TOKENIZERS_PARALLELISM="false",
                HF_HUB_DISABLE_PROGRESS_BARS="1",
            )
            started = time.monotonic()
            peak = 0
            with (folder / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [
                        python,
                        "-m",
                        "evidencealpha.dense_worker",
                        str(request_path),
                    ],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                while process.poll() is None:
                    check()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Dense worker deadline exceeded")
                    try:
                        status = pathlib.Path(
                            f"/proc/{process.pid}/status"
                        ).read_text()
                        rss = next(
                            (
                                int(x.split()[1]) * 1024
                                for x in status.splitlines()
                                if x.startswith("VmRSS:")
                            ),
                            0,
                        )
                        peak = max(peak, rss)
                        if rss > memory_bytes:
                            raise RuntimeError(
                                "Dense worker memory limit exceeded"
                            )
                    except FileNotFoundError:
                        pass
                    time.sleep(0.02)
                check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Dense worker deadline exceeded")
            if process.returncode:
                raise RuntimeError(
                    "Dense worker failed: "
                    + (folder / "worker.log").read_text()[-3000:]
                )
            result = artifacts.read(folder / "response.json")
            result["supervision"] = {
                "seconds": time.monotonic() - started,
                "sampled_peak_rss": peak,
                "exitcode": process.returncode,
            }
            if record_dir:
                artifacts.write(folder / "result.json", result)
            return result
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()
        _SLOT.release()


class Candidates:
    """Normal-path candidate provider using a frozen source/index snapshot."""

    def __init__(
        self, settings: config.Settings, store: documents.SourceStore
    ) -> None:
        self.settings = settings
        self.store = store
        self.last_metrics = {}
        self.last_digest = None

    def __call__(
        self,
        store: documents.SourceStore,
        query: str,
        source_id: str | None,
        limit: int,
        check: typing.Callable[[], None],
    ) -> list[dict]:
        """Resolve worker references before passing originals to reading."""
        from evidencealpha import (
            retrieval,
        )  # pylint: disable=import-outside-toplevel

        check()
        started = time.monotonic()
        lexical = retrieval.candidates(store, query, source_id, limit, check)
        result = supervised(
            {
                "operation": "query",
                "settings": dataclasses.asdict(self.settings),
                "corpus": str(store.root.resolve()),
                "query": query,
                "source_id": source_id,
                "limit": limit,
            },
            self.settings.dense_python or sys.executable,
            time.monotonic() + self.settings.dense_operation_seconds,
            self.settings.reranker_memory_bytes,
            check,
        )
        self.last_metrics = {
            **result["metrics"],
            **result["supervision"],
            "total_seconds": time.monotonic() - started,
        }
        self.last_digest = result["index_hash"]
        return fuse(
            store, lexical, result["hits"], limit, result["index_hash"], check
        )


def fuse(
    store: documents.SourceStore,
    lexical: list[dict],
    dense: list[dict],
    limit: int,
    index_hash: str,
    check: typing.Callable[[], None],
) -> list[dict]:
    """Share deterministic equal-weight rank fusion with injected trials."""
    merged = {}
    for branch, items in (("lexical", lexical), ("dense", dense)):
        for rank, item in enumerate(items, 1):
            p = item.get("passage") or store.open_source(
                item["source_id"], item["chunk_id"]
            )
            key = (p["source_id"], p["chunk_id"])
            entry = merged.setdefault(
                key,
                {
                    "passage": p,
                    "lexical_rank": None,
                    "lexical_score": None,
                    "candidate_provenance": {"ranks": {}, "rrf": 0.0},
                },
            )
            prov = entry["candidate_provenance"]
            # Multiple embedding units can point to one original anchor.
            if branch in prov["ranks"]:
                continue
            prov["ranks"][branch] = rank
            prov["rrf"] += 1 / (60 + rank)
            if branch == "lexical":
                entry.update(
                    lexical_rank=item["lexical_rank"],
                    lexical_score=item["lexical_score"],
                )
            else:
                entry["embedding_unit"] = item["unit"]
                prov.update(
                    distance=item["distance"],
                    unit_id=item["unit_id"],
                    index_hash=index_hash,
                )
    check()
    keys = sorted(
        merged, key=lambda k: (-merged[k]["candidate_provenance"]["rrf"], k)
    )
    return [merged[k] for k in keys[:limit]]


def preflight(settings: config.Settings, store: documents.SourceStore) -> dict:
    """Check the immutable index/corpus contract before generative admission."""
    path = pathlib.Path(settings.vector_index_path)
    manifest = artifacts.read(path / "ready.json")
    expected = {s["id"]: artifacts.digest(s) for s in store.sources()}
    signature = manifest["signature"]
    if (
        manifest["status"] != "ready"
        or manifest["schema"] != 2
        or manifest["corpus"] != expected
        or signature["revision"] != settings.dense_model_revision
        or signature["unit_tokens"] != settings.embedding_unit_tokens
        or not (path / "chroma/chroma.sqlite3").is_file()
    ):
        raise ValueError("Dense index configuration/corpus mismatch")
    return {"manifest": manifest, "manifest_hash": artifacts.digest(manifest)}
