"""Evaluate frozen RAG queries through normal source tools."""

import dataclasses
import pathlib
import sys
import time

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import reading
from evidencealpha import stage_context
from evidencealpha import tools


def run(root: pathlib.Path, corpus: pathlib.Path) -> None:
    """Preserve each query and exact writing-handoff result independently."""
    ledger_path = root / "ledger.json"
    if (
        artifacts.read(ledger_path)["status"] != "active"
        or (root / "retrieval-freeze.json").exists()
    ):
        raise ValueError("Preserve existing evaluation; use a fresh record")
    settings = config.Settings(**artifacts.read(root / "settings.json"))
    questions = artifacts.read(root / "EVALUATION.json")["questions"]
    artifacts.write(
        root / "retrieval-freeze.json",
        {
            "code": {
                str(p): artifacts.digest(p.read_bytes())
                for p in sorted(pathlib.Path("src/evidencealpha").rglob("*.py"))
            },
            "settings": dataclasses.asdict(settings),
            "questions_hash": artifacts.digest(questions),
            "python": sys.executable,
            "frozen_at": artifacts.now(),
        },
    )
    for question in questions:
        for label in ("lexical", "hybrid"):
            folder = root / question["id"] / label
            if folder.exists():
                raise ValueError("Additive evaluation refuses existing results")
            ledger = artifacts.read(ledger_path)
            remaining = ledger["deadline"] - time.time()
            if remaining < 360:
                raise TimeoutError(
                    "Preserve capacity for assessment; no query admitted"
                )
            folder.mkdir(parents=True)
            actual_settings = dataclasses.replace(
                settings,
                vector_index_path=(
                    settings.vector_index_path if label == "hybrid" else None
                ),
            )
            store = documents.SourceStore(corpus)
            source_tools = tools.EvidenceTools(
                store, actual_settings, "rag-evaluation"
            )
            source_tools.retriever.trace_dir = folder / "traces"
            started = time.monotonic()
            ledger["local_operations"].append(
                {
                    "operation": "search",
                    "question": question["id"],
                    "variant": label,
                    "admitted": artifacts.now(),
                }
            )
            artifacts.write(ledger_path, ledger)
            try:
                result = source_tools.call(
                    "search_evidence",
                    {
                        "query": question["question"],
                        "question_id": question["id"],
                    },
                    time.monotonic()
                    + min(remaining, settings.reranker_search_seconds),
                )
                artifacts.write(folder / "result.json", result)
                state = stage_context.StageContext(
                    folder / "context.json", {"questions": [question]}
                )
                state.settle(result, question["id"])
                _, writing = state.request(
                    "Prepare sourced investor notes; "
                    "preserve evidence boundaries.",
                    {},
                    "final_notes",
                    1,
                    settings.request_memory_bytes,
                )
                artifacts.write(folder / "writing.json", writing)
                original = documents.ungroup_passages(state.data["evidence"])
                selected = documents.ungroup_passages(
                    writing["settled_evidence"]
                )

                def identity(passages):
                    return {
                        reading.reference(p): (
                            p["source_id"],
                            p["version"],
                            p["text"],
                            [
                                (s["start"], s["end"], s.get("page"))
                                for s in p["spans"]
                            ],
                        )
                        for p in passages
                    }

                exact = identity(original) == identity(selected)
                for p in selected:
                    text = store.reading_index(p["source_id"], 8000).text
                    assert all(
                        text[s["start"] : s["end"]] in p["text"]
                        for s in p["spans"]
                    )
                trace = artifacts.read(pathlib.Path(result["trace"]))
                assessment = {
                    "question": question,
                    "variant": label,
                    "seconds": time.monotonic() - started,
                    "retrieval_status": result["retrieval_status"],
                    "candidate_count": result["candidate_count"],
                    "candidate_sources": sorted(
                        {c["source_id"] for c in trace["candidates"]}
                    ),
                    "returned_sources": sorted(
                        {p["source_id"] for p in selected}
                    ),
                    "returned_blocks": len(result["reading_blocks"]),
                    "returned_passages": len(original),
                    "writing_passages": len(selected),
                    "original_and_writing_exact": exact,
                    "candidate_metrics": trace.get("candidate_metrics"),
                    "reranker_metrics": trace.get("reranker_metrics"),
                    "preparation_seconds": trace.get("preparation_seconds"),
                }
                assert exact, "Writing handoff lost original evidence"
                artifacts.write(folder / "assessment.json", assessment)
                print(
                    question["id"],
                    label,
                    assessment["retrieval_status"],
                    round(assessment["seconds"], 2),
                    flush=True,
                )
            # Keep every failed case instead of selecting only successes.
            # pylint: disable-next=broad-exception-caught
            except Exception as exc:
                artifacts.write(
                    folder / "failure.json",
                    {
                        "error": str(exc),
                        "type": type(exc).__name__,
                        "seconds": time.monotonic() - started,
                    },
                )
                print(question["id"], label, "FAILED", str(exc), flush=True)
            finally:
                source_tools.retriever.close()
                ledger = artifacts.read(ledger_path)
                ledger["local_operations"][-1].update(
                    completed=artifacts.now(),
                    seconds=time.monotonic() - started,
                    result=str(folder),
                )
                artifacts.write(ledger_path, ledger)


if __name__ == "__main__":
    run(
        pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
    )
