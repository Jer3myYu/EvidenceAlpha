"""Run exactly one frozen A/B/C stage, with the linked additive ledger."""

import argparse
import dataclasses
import json
import pathlib
import time

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import tools
from evidencealpha import workflow


def verify(snapshot: pathlib.Path) -> None:
    """Reject changed evaluation inputs, including source annotations."""
    seal = artifacts.read(snapshot.parent / "freeze.json")
    if (
        artifacts.digest((snapshot / "manifest.json").read_bytes())
        != seal["manifest_hash"]
    ):
        raise ValueError("Frozen manifest changed")
    for relative, expected in artifacts.read(
        snapshot / "manifest.json"
    ).items():
        path = snapshot / relative
        if (
            artifacts.digest(path.read_bytes()) != expected
            or path.stat().st_mode & 0o222
        ):
            raise ValueError(f"Frozen input changed: {relative}")
    if (
        pathlib.Path(config.__file__).resolve()
        != snapshot / "src/evidencealpha/config.py"
    ):
        raise ValueError("Runtime must import the frozen code")


def main() -> None:
    """Execute once; assessment must explicitly settle adequacy afterward."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=("A", "B", "C"))
    parser.add_argument("--snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--ledger", type=pathlib.Path, required=True)
    parser.add_argument("--parent-ledger", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    verify(snapshot)
    case = artifacts.read(snapshot / "cases" / f"{args.case}.json")
    ledger = budget.DiagnosticLedger(args.ledger.resolve())
    ledger.initialize_linked(args.parent_ledger.resolve())
    ledger.start()
    attempt = ledger.admit(args.case)
    root = args.output.resolve() / args.case
    root.mkdir(parents=True, exist_ok=False)
    settings = config.Settings(**artifacts.read(snapshot / "settings.json"))
    settings = dataclasses.replace(settings, ledger=str(ledger.path))
    runner = workflow.StageRunner(
        settings,
        providers.CodexProvider(),
        tools.EvidenceTools(
            documents.SourceStore(snapshot / "corpus"),
            settings,
            "fixed-corpus",
            ledger,
        ),
        ledger,
        attempt,
    )
    started = time.monotonic()
    status = "failed"
    result = {}
    try:
        result = runner.run(
            case["stage"],
            case["role"],
            case["portable"],
            root,
            seconds=case["seconds"],
            deadline=time.monotonic()
            + max(0, attempt["deadline"] - time.time()),
        )
        status = "completed_unassessed"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        result = {"error": type(exc).__name__, "message": str(exc)}
    finally:
        providers.cancel_all()
        ledger.finish(attempt, status)
        verify(snapshot)
        artifacts.write(
            root / "result.json",
            {
                "case": args.case,
                "attempt": attempt,
                "status": status,
                "elapsed_seconds": time.monotonic() - started,
                "result": result,
            },
        )
    print(json.dumps({"case": args.case, "status": status, "root": str(root)}))


if __name__ == "__main__":
    main()
