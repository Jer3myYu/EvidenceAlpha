"""Fixed-corpus admission and saved-output replay for the shared workflow."""

import dataclasses
import importlib.metadata
import json
import os
import pathlib
import signal
import sys
import time

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import handoff
from evidencealpha import providers
from evidencealpha import stage_context
from evidencealpha import workflow


class SavedStages:
    """Replay completed stage envelopes, never simulate autonomous research."""

    def __init__(
        self,
        descriptor: dict,
        settings: config.Settings,
        store: documents.SourceStore,
    ) -> None:
        self.descriptor = descriptor
        self.settings = settings
        self.store = store
        self.used = []

    def run(
        self,
        stage: str,
        role: str,
        portable: dict,
        root: pathlib.Path,
        **kwargs: object,
    ) -> dict:
        """Exercise current assembly with old outputs and original evidence."""
        del kwargs
        entry = self.descriptor[stage]
        files = {}
        for key in ("output", "state", "writing"):
            path = pathlib.Path(entry[key]["path"])
            if artifacts.digest(path.read_bytes()) != entry[key]["sha256"]:
                raise ValueError("Saved-stage replay hash mismatch")
            files[key] = artifacts.read(path)
        output = workflow.parse_output(json.dumps(files["output"]), role)
        folder = root / "stages" / stage / "saved-output-replay"
        context = stage_context.StageContext(
            folder / "context-state.json",
            {k: v for k, v in portable.items() if k != "settled_evidence"},
        )
        context.settle(
            handoff.originals(self.store, files["state"]["evidence"])
        )
        context.settle(portable.get("settled_evidence", {}))
        prompts = pathlib.Path(workflow.__file__).parent / "prompts"
        instructions = (prompts / "common.md").read_text() + (
            prompts / f"{role}.md"
        ).read_text()
        prompt, view = context.request(
            instructions,
            {},
            "final_notes",
            1,
            self.settings.stage_context_bytes,
            min(
                self.settings.writer_input_tokens,
                self.settings.writer_context_tokens
                - self.settings.writer_output_tokens
                - self.settings.writer_transport_tokens,
            ),
        )
        artifacts.write(folder / "request.txt", prompt)
        artifacts.write(
            folder / "input.json", {"portable": portable, "replay": entry}
        )
        artifacts.write(folder / "assembled-context.json", view)
        # Research completion is replayed exactly. Downstream payload selection
        # uses the current code, with historical writing selections protected.
        if stage.startswith("research-") or stage == "followup":
            view = files["writing"]
            artifacts.write(folder / "historical-writing-context.json", view)
        artifacts.write(folder / "writing-context.json", view)
        artifacts.write(folder / "output.json", output)
        artifacts.write(
            folder / "status.json",
            {"status": "saved-output replay", "provider_calls": 0},
        )
        self.used.append(stage)
        return {
            "path": str(folder.relative_to(root)),
            "input_hash": artifacts.digest(portable),
            "output_hash": artifacts.digest(output),
            "output": output,
        }


def _paths(spec: dict, parent: pathlib.Path) -> dict:
    for key in ("corpus", "industry_import", "reranker_path"):
        target = spec["settings"] if key == "reranker_path" else spec
        if target.get(key):
            target[key] = str((parent / target[key]).resolve())
    return spec


def run(
    path: pathlib.Path,
    root: pathlib.Path,
    replay_path: pathlib.Path | None = None,
) -> dict:
    """Admit one command, freeze inputs, supervise setup through export."""
    if root.exists():
        raise ValueError(
            "Output exists; choose a new additive execution directory"
        )
    spec = _paths(artifacts.read(path), path.resolve().parent)
    settings = config.Settings(**spec["settings"])
    if settings.profile != "low_claude_quota":
        raise ValueError("Fixed-corpus execution has no provider fallback")
    if settings.workers != 1 or not settings.writer_context_tokens:
        raise ValueError(
            "Fixed-corpus execution requires one worker "
            "and explicit provider capacity"
        )
    if (
        not settings.reranker_path
        or not pathlib.Path(settings.reranker_path).is_dir()
    ):
        raise ValueError("An existing local reranker directory is required")
    if not spec.get("required_scope"):
        raise ValueError("Explicit essential scope from the brief is required")
    if spec.get("tasks"):
        if artifacts.digest(spec["tasks"]) != spec.get("tasks_sha256"):
            raise ValueError("Scoped task reuse hash mismatch")
        if spec.get("industry_import") and any(
            t["role"] == "industry" for t in spec["tasks"]
        ):
            raise ValueError(
                "Imported industry scope must not be researched again"
            )
    environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    supplied = spec.get("environment", {})
    if any(
        k not in environment or v != environment[k] for k, v in supplied.items()
    ):
        raise ValueError(
            "Only explicit offline model environment settings are accepted"
        )
    previous_env = {k: os.environ.get(k) for k in environment}
    os.environ.update(environment)
    root.mkdir(parents=True)
    ledger = budget.ExecutionLedger(root / "execution-ledger.json", settings)
    ledger.initialize()
    ledger.start()
    attempt = ledger.admit("full")
    status = "failed"
    previous_alarm = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        del signum, frame
        providers.cancel_all()
        raise providers.ProviderCancelled("Command wall deadline expired")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.001, attempt["deadline"] - time.time())
    )
    result = {}
    try:
        frozen = {
            "code": artifacts.revision(),
            "execution": spec,
            "settings": dataclasses.asdict(settings),
            "environment": environment,
            "python": sys.executable,
            "started": artifacts.now(),
            "replay": str(replay_path) if replay_path else None,
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("pymupdf", "markdown-it-py", "matplotlib")
            },
        }
        artifacts.write(root / "execution-freeze.json", frozen)
        store = documents.SourceStore(pathlib.Path(spec["corpus"]))
        sources = workflow._source_inputs(  # pylint: disable=protected-access
            store, [s["id"] for s in store.sources()]
        )
        artifacts.write(root / "corpus-freeze.json", sources)
        runner = None
        if replay_path:
            descriptor = artifacts.read(replay_path)
            artifacts.write(root / "replay-freeze.json", descriptor)
            runner = SavedStages(descriptor, settings, store)
        result = workflow.run(
            spec["brief"],
            settings,
            (
                providers.FixtureProvider({})
                if runner
                else providers.CodexProvider()
            ),
            [],
            root,
            "fixture" if runner else "fixed-corpus",
            ledger,
            attempt,
            source_corpus=pathlib.Path(spec["corpus"]),
            execution=spec,
            replay_runner=runner,
        )
        status = result["execution_status"]
        if runner:
            result["replayed_stages"] = runner.used
        if (
            artifacts.revision()["active_code_hash"]
            != frozen["code"]["active_code_hash"]
        ):
            raise ValueError("Active code changed during execution")
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        KeyboardInterrupt,
    ) as exc:
        result.update(
            execution_status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        status = "failed"
    finally:
        providers.cancel_all()
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        ledger.finish(attempt, status)
        result["usage"] = artifacts.read(ledger.path)
        result["elapsed_seconds"] = time.time() - attempt["started"]
        result["run"] = str(root)
        artifacts.write(root / "command-result.json", result)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return result
