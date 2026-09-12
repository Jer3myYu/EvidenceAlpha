"""Command line for the active workflow, offline replay and bounded Stage 2."""

import argparse
import dataclasses
import json
import os
import pathlib
import shutil
import signal
import time

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import execution
from evidencealpha import providers
from evidencealpha import render
from evidencealpha import tools
from evidencealpha import workflow


def fixture(
    path: pathlib.Path,
) -> tuple[dict, providers.FixtureProvider, list[pathlib.Path]]:
    """Load a labeled fixture pack; paths are relative to the pack."""
    data = artifacts.read(path)
    return (
        data["brief"],
        providers.FixtureProvider(data["outputs"]),
        [(path.parent / source).resolve() for source in data["sources"]],
    )


def _driver(args: argparse.Namespace, settings: config.Settings) -> dict:
    ledger = budget.Ledger(pathlib.Path(settings.ledger))
    if not args.execute:
        return {
            "status": "not_started",
            "budget": artifacts.read(ledger.path),
            "instruction": "Fresh Stage 2 session only: --execute --case PATH",
        }
    if not args.case:
        raise ValueError("An explicit saved case is required")
    case = artifacts.read(args.case)
    if case["kind"] == "full" and not case.get("readiness_evidence"):
        raise ValueError(
            "Full report requires recorded stage readiness evidence"
        )
    for evidence in case.get("readiness_evidence", []):
        if not pathlib.Path(evidence).is_file():
            raise ValueError("Readiness evidence is missing")
    ledger.start()
    attempt = ledger.admit(case["kind"], case.get("provider", "codex"))
    root = pathlib.Path(settings.runs_dir) / attempt["id"]
    status = "failed"

    def deadline_expired(signum, frame):
        del signum, frame
        providers.cancel_all()
        ledger.finish(attempt, "deadline_exceeded")
        artifacts.write(
            root / "interrupted.json",
            {
                "reason": "Outer attempt wall-clock deadline",
                "time": artifacts.now(),
                "accounting": "Unsettled reservations remain charged",
            },
        )
        # Stop acquisition threads too; all prior artifact writes are atomic.
        os._exit(124)  # pylint: disable=protected-access

    previous_alarm = signal.signal(signal.SIGALRM, deadline_expired)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.001, attempt["deadline"] - time.time())
    )
    try:
        provider = providers.CodexProvider()
        if case["kind"] == "full":
            settings = dataclasses.replace(settings, profile="low_claude_quota")
            resume_from = case.get("resume_from")
            if resume_from:
                parent = pathlib.Path(resume_from)
                saved = artifacts.read(parent / "manifest.json")
                if saved["mode"] != "live":
                    raise ValueError(
                        "A live resume cannot reuse fixture results"
                    )
                shutil.copytree(parent, root)
                saved.update(id=root.name, parent=str(parent))
                artifacts.write(root / "manifest.json", saved)
            result = workflow.run(
                case["brief"],
                settings,
                provider,
                [pathlib.Path(p) for p in case.get("sources", [])],
                root,
                "live",
                ledger,
                attempt,
                resume=bool(resume_from),
                source_corpus=(
                    pathlib.Path(case["corpus"]) if case.get("corpus") else None
                ),
            )
            status = result["status"]
        else:
            if case.get("provider") == "claude":
                settings = dataclasses.replace(settings, profile="preferred")
            input_path = pathlib.Path(case["input"])
            store = documents.SourceStore(pathlib.Path(case["corpus"]))
            record = artifacts.read(input_path)
            root.mkdir(parents=True)
            # Frozen inputs contain explicit originals; tool access is bounded.
            shutil.copytree(store.root, root / "sources")
            runner = workflow.StageRunner(
                settings,
                provider,
                tools.EvidenceTools(
                    documents.SourceStore(root / "sources"),
                    settings,
                    "fixed-corpus",
                    ledger,
                ),
                ledger,
                attempt,
            )
            result = runner.run(
                record["stage"],
                record["role"],
                record["portable"],
                root,
                rehearsal=(
                    case.get("provider", "codex") == "codex"
                    and case.get("execution", "surrogate") == "surrogate"
                ),
            )
            artifacts.write(root / "result.json", result)
            status = "complete"
        return {"run": str(root), "status": status}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        ledger.finish(attempt, status)


def parser() -> argparse.ArgumentParser:
    """Build the supported CLI; charged actions live only in stage2."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=pathlib.Path)
    commands = result.add_subparsers(dest="command", required=True)
    start = commands.add_parser(
        "run", help="Complete deterministic fixture report (no models)"
    )
    start.add_argument("--fixture", type=pathlib.Path, required=True)
    start.add_argument("--output", type=pathlib.Path, required=True)
    resume = commands.add_parser(
        "resume",
        help="Resume unchanged fixture stages; changed dependencies rerun",
    )
    resume.add_argument("run", type=pathlib.Path)
    resume.add_argument("--fixture", type=pathlib.Path, required=True)
    replay = commands.add_parser(
        "replay-stage",
        help="Replay a saved stage with fixture output into a new directory",
    )
    replay.add_argument("input", type=pathlib.Path)
    replay.add_argument("--fixture", type=pathlib.Path, required=True)
    replay.add_argument("--corpus", type=pathlib.Path, required=True)
    replay.add_argument("--output", type=pathlib.Path, required=True)
    rendering = commands.add_parser(
        "render", help="Render canonical Markdown without research"
    )
    rendering.add_argument("markdown", type=pathlib.Path)
    show = commands.add_parser(
        "show-run", help="Show status and artifact paths without full logs"
    )
    show.add_argument("run", type=pathlib.Path)
    stage2 = commands.add_parser(
        "stage2",
        help="Inspect ledger; explicit --execute admits one Stage 2 case",
    )
    stage2.add_argument("--execute", action="store_true")
    stage2.add_argument("--case", type=pathlib.Path)
    fixed = commands.add_parser(
        "fixed-corpus",
        help="One bounded fixed-corpus report; no external acquisition",
    )
    fixed.add_argument("--execution", type=pathlib.Path, required=True)
    fixed.add_argument("--output", type=pathlib.Path, required=True)
    fixed.add_argument(
        "--replay",
        type=pathlib.Path,
        help="Hash-bound saved stage outputs; no model calls",
    )
    return result


def main() -> None:
    """Execute one explicit command and print compact artifact-oriented
    output.
    """

    def stop(signum, frame):
        del signum, frame
        providers.cancel_all()
        raise KeyboardInterrupt("Provider children stopped")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    args = parser().parse_args()
    settings = config.load(args.config)
    if args.command == "fixed-corpus":
        data = execution.run(args.execution, args.output, args.replay)
        output = {
            key: data.get(key)
            for key in (
                "run",
                "execution_status",
                "coverage_status",
                "review_status",
                "export_status",
                "error",
                "elapsed_seconds",
            )
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit(
            0
            if data.get("execution_status") == "complete"
            and data.get("export_status") == "complete"
            else 1
        )
    if args.command == "stage2":
        output = _driver(args, settings)
    elif args.command == "render":
        output = render.export(args.markdown)
    elif args.command == "show-run":
        data = artifacts.read(args.run / "manifest.json")
        output = {
            key: data.get(key)
            for key in ("id", "status", "error", "render", "validation")
        }
    else:
        brief, provider, sources = fixture(args.fixture)
        if args.command == "replay-stage":
            output = workflow.replay_stage(
                args.input,
                args.output,
                settings,
                provider,
                documents.SourceStore(args.corpus),
            )
            output = {
                "path": output["path"],
                "status": "fixture replay complete",
            }
        else:
            root = args.run if args.command == "resume" else args.output
            data = workflow.run(
                brief,
                settings,
                provider,
                sources,
                root,
                resume=args.command == "resume",
            )
            output = {
                "run": str(root),
                "status": data["status"],
                "error": data.get("error"),
                "render": data.get("render"),
            }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
