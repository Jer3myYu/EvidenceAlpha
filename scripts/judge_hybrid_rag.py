"""GPT-6 usefulness assessment of frozen paired retrieval artifacts."""

import dataclasses
import json
import pathlib
import sys
import time

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import providers


def run(root: pathlib.Path) -> None:
    """Judge all saved cases blind to candidate implementation labels."""
    evaluation = artifacts.read(root / "EVALUATION.json")
    catalogue = providers.installed_model(config.REVIEW_MODEL)
    mapping = {"A": "hybrid", "B": "lexical"}
    artifacts.write(root / "judge-label-key.json", mapping)
    for batch in (0, 1):
        folder = root / f"judge-{batch+1}"
        if folder.exists():
            raise ValueError(
                "Judge output exists; do not repeat successful calls"
            )
        cases = []
        for question in evaluation["questions"][batch * 4 : (batch + 1) * 4]:
            variants = {}
            for label, variant in mapping.items():
                path = root / question["id"] / variant
                if not (path / "result.json").exists():
                    variants[label] = {
                        "failure": artifacts.read(path / "failure.json")
                    }
                    continue
                result = artifacts.read(path / "result.json")
                # Exactly the returned originals; no assessor answer keys.
                variants[label] = {
                    "status": result["retrieval_status"],
                    "sources": [
                        {
                            **{
                                k: v
                                for k, v in source.items()
                                if k != "passages"
                            },
                            "passages": [
                                {
                                    "text": p["text"],
                                    "spans": p["spans"],
                                    "chunk_ids": [
                                        r["chunk_id"]
                                        for r in p.get("chunk_refs", [])
                                    ],
                                }
                                for p in source["passages"]
                            ],
                        }
                        for source in result["sources"]
                    ],
                    "reading_statuses": [
                        b["status"] for b in result["reading_blocks"]
                    ],
                }
            cases.append({**question, "variants": variants})
        prompt = (
            "Evaluate RAG evidence for an investor familiar with investing but new to "
            "the photomask industry. This is targeted retrieval assessment, not a complete "
            "report review or exhaustive factual certification. Use only supplied original "
            "passages, never prior knowledge as missing evidence. A and B are anonymous "
            "retrieval configurations. Do not infer which implementation they represent. "
            "Apply frozen criteria below fairly: useful supporting context matters more "
            "than perfect precision, and irrelevant extras alone do not fail a query. "
            "Preserve company, period, unit, total-versus-segment scope and technical status. "
            "A retrieval miss is not a full-document absence claim. You have not inspected "
            "the full corpus. For each question and variant give rating Useful/Partial/"
            "Insufficient, a short sourced answer where support allows, useful evidence "
            "locations, material missing information, qualifier risks, and whether a "
            "focused follow-up is warranted. Rate evidence available for answering, not "
            "mere quantity. For Q08 assess the boundary rather than requiring future price "
            "data. Return a JSON object inside the envelope content with a cases array. "
            "Each case has id and A/B assessment objects. Keep other unused envelope "
            "arrays empty; no tool calls. Explain in Chinese. Include assessment limitations."
            "\nFROZEN_CRITERIA\n"
            + json.dumps(evaluation["assessment"], ensure_ascii=False)
            + "\nCASES\n"
            + json.dumps(cases, ensure_ascii=False)
        )
        # UTF-8 bytes conservatively upper-bound visible BPE input; output +
        # protocol reserves are protected. Actual provider output cap is unreported.
        size = len(prompt.encode())
        capacity = int(
            catalogue["context_window"] * catalogue["effective_percent"] / 100
        )
        if size + 16000 + 4096 > capacity:
            raise ValueError(
                f"Judge input {size} bytes exceeds conservative admission"
            )
        ledger_path = root / "ledger.json"
        ledger = artifacts.read(ledger_path)
        remaining = ledger["deadline"] - time.time()
        if remaining < 180:
            raise TimeoutError(
                "Overall evaluation deadline leaves no assessment capacity"
            )
        entry = {
            "stage": f"rag-judge-{batch+1}",
            "requested_model": config.REVIEW_MODEL,
            "admitted": artifacts.now(),
            "input_bytes": size,
            "capacity": catalogue,
            "status": "admitted",
        }
        ledger["generative_invocations"].append(entry)
        artifacts.write(ledger_path, ledger)
        artifacts.write(folder / "request.json", {"prompt": prompt, **entry})
        started = time.monotonic()
        try:
            result = providers.CodexProvider().run(
                providers.Request(
                    stage=entry["stage"],
                    prompt=prompt,
                    settings=config.ModelSettings(
                        "codex", config.REVIEW_MODEL, "medium"
                    ),
                    workspace=folder,
                    seconds=min(600, remaining),
                    deadline=time.monotonic() + remaining,
                    allowed_tools=(),
                )
            )
            artifacts.write(folder / "result.json", dataclasses.asdict(result))
            envelope = json.loads(result.text)
            artifacts.write(
                folder / "assessment.json", json.loads(envelope["content"])
            )
            entry.update(
                status="complete",
                actual_model=result.effective_model or "unreported",
                usage=result.usage,
            )
        except Exception as exc:
            entry.update(
                status="failed", error=str(exc), usage=getattr(exc, "usage", {})
            )
            artifacts.write(folder / "failure.json", entry)
        finally:
            entry["seconds"] = time.monotonic() - started
            entry["completed"] = artifacts.now()
            ledger = artifacts.read(ledger_path)
            ledger["generative_invocations"][-1] = entry
            artifacts.write(ledger_path, ledger)
        print(
            entry["stage"],
            entry["status"],
            round(entry["seconds"], 1),
            flush=True,
        )
        if entry["status"] == "failed":
            break


if __name__ == "__main__":
    run(pathlib.Path(sys.argv[1]).resolve())
