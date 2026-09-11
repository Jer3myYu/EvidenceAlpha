"""One authorized company stage with frozen imports and bounded accounting."""

import dataclasses
import json
import pathlib
import signal
import sys
import time

# The launcher supplies the sealed package; no shared-checkout imports.
PACK = pathlib.Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
sys.path.insert(0, str(PACK / "frozen/src"))

# Frozen path must be selected before importing the runtime.
# pylint: disable=wrong-import-position
from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import render
from evidencealpha import tools
from evidencealpha import workflow

LEDGER = PACK / "authorization-usage.json"


def verify() -> dict:
    """Check the sealed candidate and inputs without launching anything."""
    seal = artifacts.read(PACK / "freeze.json")
    for name, digest in seal["files"].items():
        if artifacts.digest(pathlib.Path(name).read_bytes()) != digest:
            raise ValueError("Frozen input changed: " + name)
    for path in pathlib.Path(seal["corpus"]).rglob("*"):
        if path.stat().st_mode & 0o222:
            raise ValueError("Evidence must remain read-only: " + str(path))
    if not seal["readiness_resolved"]:
        raise ValueError("Readiness is unresolved")
    return seal


class CountedProvider:
    """Admit sequential calls; stop after any failure."""

    def run(self, request: providers.Request) -> providers.Result:
        """Bound the existing provider by worker, aggregate and call budgets."""
        verify()
        data = artifacts.read(LEDGER)
        entries = data["invocations"]
        if data["stopped"] or any(e["status"] != "complete" for e in entries):
            raise RuntimeError("Prior failure or active call stops admission")
        if any(e["observable_tokens"] is None for e in entries):
            raise RuntimeError("Unknown usage stops admission")
        if len(entries) >= 6:
            raise RuntimeError("Six invocation allowance exhausted")
        if sum(e["observable_tokens"] for e in entries) >= 12000:
            raise RuntimeError("Observable token budget exhausted")
        if request.settings != config.ModelSettings("codex", "gpt-5.6-sol"):
            raise ValueError("Unexpected model or effort")
        now = time.monotonic()
        used = sum(e["seconds"] for e in entries)
        deadline, limit = min(
            (request.deadline, request.deadline_limit),
            (data["worker_deadline_monotonic"], "worker_elapsed"),
            (now + 600 - used, "aggregate_invocation"),
            key=lambda pair: pair[0],
        )
        if deadline <= now:
            raise RuntimeError("Time allowance exhausted")
        request = dataclasses.replace(
            request,
            seconds=min(request.seconds, deadline - now),
            deadline=deadline,
            deadline_limit=limit,
        )
        entry = {
            "index": len(entries) + 1,
            "status": "running",
            "workspace": str(request.workspace),
            "started": time.time(),
            "reserved_seconds": request.seconds,
            "deadline": deadline,
            "limiting_resource": limit,
            "settings": dataclasses.asdict(request.settings),
        }
        entries.append(entry)
        artifacts.write(LEDGER, data)
        started, usage = time.monotonic(), {}
        try:
            result = providers.CodexProvider().run(request)
            usage = result.usage
            entry.update(
                status="complete",
                effective_model=result.effective_model,
                effective_effort=result.effective_effort,
            )
            return result
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            usage = getattr(exc, "usage", {})
            entry.update(
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                ended_by=getattr(exc, "limit", None),
            )
            raise
        finally:
            entry["seconds"] = time.monotonic() - started
            entry["usage"] = usage
            observed = usage.get("output_tokens")
            if (
                observed is not None
                and usage.get("reasoning_in_output") is False
            ):
                observed += usage.get("reasoning_output_tokens", 0)
            entry["observable_tokens"] = observed
            artifacts.write(LEDGER, data)
            providers.cancel_all()


def run() -> None:
    """Start a fresh clock only after sealed readiness and refusal to resume."""
    seal = verify()
    if LEDGER.exists():
        raise ValueError("Attempt already exists; no resume or reset")
    started = time.monotonic()
    data = {
        "authorization": seal["authorization"],
        "candidate": seal["candidate"],
        "run_id": "company-stage-corrected",
        "started": time.time(),
        "started_monotonic": started,
        "worker_deadline_monotonic": started + 600,
        "execution_deadline_monotonic": started + 780,
        "limits": {
            "calls": 6,
            "worker_seconds": 600,
            "summed_seconds": 600,
            "writing_reserve_seconds": 180,
            "invocation_seconds": 300,
            "elapsed_seconds": 780,
            "observable_tokens": 12000,
        },
        "token_policy": "Count output plus explicitly nonincluded reasoning; "
        "unknown usage stops admission. No hard in-flight CLI token cap.",
        "invocations": [],
        "stopped": False,
    }
    # Exclusive creation prevents two controllers from launching this attempt.
    with LEDGER.open("x") as handle:
        json.dump(data, handle, indent=2)
    result = None
    state = {"status": "running"}
    run_dir = PACK / "attempt"
    artifacts.write(run_dir / "state.json", state)

    def cancel(signum: int, frame: object) -> None:
        del signum, frame
        providers.cancel_all()
        raise providers.ProviderCancelled(
            "Controller cancelled or export deadline reached"
        )

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGALRM, cancel)
    try:
        settings = config.load(
            PACK / "frozen/docs/redesign/company-stage-test/settings.json"
        )
        store = documents.SourceStore(pathlib.Path(seal["corpus"]))
        runner = workflow.StageRunner(
            settings,
            CountedProvider(),
            tools.EvidenceTools(store, settings, "fixed-corpus"),
        )
        result = runner.run(
            "company",
            "company",
            artifacts.read(
                PACK / "frozen/docs/redesign/company-stage-test/input.json"
            ),
            run_dir,
            seconds=600,
            deadline=started + 600,
        )
        state.update(status="completed", result=result)
    except BaseException as exc:  # pylint: disable=broad-exception-caught
        state.update(
            status="failed", error=str(exc), error_type=type(exc).__name__
        )
        artifacts.write(run_dir / "failure.json", state)
    finally:
        providers.cancel_all()
        data = artifacts.read(LEDGER)
        data.update(
            stopped=True,
            model_work_closed=time.time(),
            model_work_elapsed_seconds=time.monotonic() - started,
        )
        artifacts.write(LEDGER, data)
        artifacts.write(run_dir / "state.json", state)
    if result and time.monotonic() < started + 780:
        # The provider has stopped; this timer bounds export only, not calls.
        signal.setitimer(signal.ITIMER_REAL, started + 780 - time.monotonic())
        # Preserve exact model Markdown before generic, unedited export.
        note = PACK / "delivery/company-notes.md"
        artifacts.write(note, result["output"]["content"])
        try:
            report = (
                workflow._prepare_report(  # pylint: disable=protected-access
                    result["output"], PACK / "delivery", store, "report.md"
                )
            )
            artifacts.write(
                PACK / "delivery/export.json", render.export(report)
            )
        except (OSError, ValueError, RuntimeError) as exc:
            artifacts.write(
                PACK / "delivery/export-failure.json", {"error": str(exc)}
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    data = artifacts.read(LEDGER)
    data.update(
        wrapper_closed=time.time(), elapsed_seconds=time.monotonic() - started
    )
    artifacts.write(LEDGER, data)
    verify()
    print(
        json.dumps(
            {"status": state["status"], "elapsed": data["elapsed_seconds"]}
        )
    )


if __name__ == "__main__":
    if sys.argv[2:] == ["run"]:
        run()
    elif sys.argv[2:] == ["verify"]:
        print(json.dumps({"verified": verify()["candidate"]}))
    else:
        raise ValueError("Use package_path verify|run")
