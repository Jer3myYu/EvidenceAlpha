"""Small isolated Codex CLI / Claude SDK adapters and injectable fixtures."""

import dataclasses
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from typing import Protocol

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import claude_runner
from evidencealpha import protocol
from evidencealpha import reranking

_ACTIVE: set[int] = set()
_CANCELLED: set[int] = set()
_ACTIVE_LOCK = threading.Lock()


def cancel_all() -> None:
    """Terminate active provider groups before controller cancellation exits."""
    reranking.cancel_all()
    with _ACTIVE_LOCK:
        for pid in _ACTIVE:
            _CANCELLED.add(pid)
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class ProviderError(RuntimeError):
    """A provider attempt failed, with preserved observable usage."""

    def __init__(self, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage = usage or {}


class ProviderTimeout(ProviderError):
    """The local process supervisor reached this exact monotonic deadline."""

    def __init__(
        self, message: str, deadline: float, limit: str = "request_deadline"
    ) -> None:
        super().__init__(message)
        self.deadline = deadline
        self.limit = limit


class ProviderCancelled(ProviderError):
    """Explicit controller cancellation; never a recoverable phase cutoff."""


class QuotaExhausted(ProviderError):
    """An explicit usage-exhausted response, not a generic rate limit."""


@dataclasses.dataclass
class Request:
    """Portable application-visible request with explicit allowed tools."""

    stage: str
    prompt: str
    settings: config.ModelSettings
    workspace: pathlib.Path
    seconds: float
    deadline: float | None = None
    allowed_tools: tuple[str, ...] | None = None
    deadline_limit: str = "request_deadline"


@dataclasses.dataclass
class Result:
    """Normalized final text and observable provider metadata."""

    text: str
    usage: dict = dataclasses.field(default_factory=dict)
    session_id: str | None = None
    effective_model: str | None = None
    effective_effort: str | None = None


class Provider(Protocol):
    """Application boundary; SDK session internals never escape adapters."""

    def run(self, request: Request) -> Result:
        """Execute one bounded request; persist raw output in its workspace."""


class FixtureProvider:
    """Inject saved responses without any network or model calls."""

    def __init__(self, outputs: dict[str, dict | list[dict]]) -> None:
        self.outputs = outputs
        self.calls: list[Request] = []
        self._positions: dict[str, int] = {}

    def run(self, request: Request) -> Result:
        """Return an explicit fixture; missing responses fail loudly."""
        self.calls.append(request)
        output = self.outputs[request.stage]
        if isinstance(output, list):
            index = self._positions.get(request.stage, 0)
            self._positions[request.stage] = index + 1
            output = output[index]
        if "fixture_error" in output:
            error = (
                QuotaExhausted
                if output["fixture_error"] == "quota"
                else ProviderError
            )
            raise error(output["fixture_error"])
        return Result(
            json.dumps(output, ensure_ascii=False),
            {"input_tokens": 0, "output_tokens": 0},
            effective_model="fixture",
        )


def execute(command: list[str], request: Request) -> tuple[list[dict], int]:
    """Run a process group and kill/reap descendants on every exit path."""
    request.workspace.mkdir(parents=True, exist_ok=True)
    artifacts.write(request.workspace / "request.txt", request.prompt)
    artifacts.write(request.workspace / "command.json", command)
    # Preserve supported CLI login; explicitly remove API/provider fallbacks.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_BASE_URL",
            "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        }
    }
    environment["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    environment["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
    raw = request.workspace / "raw.jsonl"
    started = time.monotonic()
    deadline, limit = min(
        (started + request.seconds, "invocation_allowance"),
        (
            request.deadline if request.deadline is not None else float("inf"),
            request.deadline_limit,
        ),
        key=lambda item: item[0],
    )
    if time.monotonic() >= deadline:
        raise ProviderTimeout(
            "Provider deadline expired before launch", deadline, limit
        )
    with (
        raw.open("w", encoding="utf-8") as stdout,
        (request.workspace / "stderr.txt").open(
            "w", encoding="utf-8"
        ) as stderr,
    ):
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            cwd=request.workspace,
            env=environment,
            start_new_session=True,
            text=True,
        )
        with _ACTIVE_LOCK:
            _ACTIVE.add(process.pid)
        artifacts.event(
            request.workspace / "events.jsonl", "invoked", pid=process.pid
        )
        timed_out = False
        try:
            process.communicate(
                request.prompt, timeout=max(0, deadline - time.monotonic())
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            with _ACTIVE_LOCK:
                _ACTIVE.discard(process.pid)
                cancelled = process.pid in _CANCELLED
                _CANCELLED.discard(process.pid)
            artifacts.event(
                request.workspace / "events.jsonl",
                "completed",
                seconds=time.monotonic() - started,
                returncode=process.returncode,
                cancelled=cancelled,
                deadline=deadline,
                ended_by=(
                    "cancellation"
                    if cancelled
                    else limit if timed_out else "exit"
                ),
            )
    if cancelled:
        raise ProviderCancelled("Provider cancelled by controller")
    if timed_out:
        raise ProviderTimeout("Provider deadline expired", deadline, limit)
    events = []
    for line in raw.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "unparsed", "text": line})
    return events, process.returncode


class CodexProvider:
    """Subscription CLI fallback; no Python Codex SDK is installed."""

    def run(self, request: Request) -> Result:
        """Use isolated read-only."""
        if request.settings.model not in (
            config.RUNTIME_MODEL,
            config.REHEARSAL_MODEL,
        ):
            raise ValueError("Model is outside the authorized campaign")
        output = request.workspace / "last-message.txt"
        schema = request.workspace / "output-schema.json"
        artifacts.write(schema, protocol.output_schema(request.allowed_tools))
        overrides = {
            "model_reasoning_effort": request.settings.effort,
            "forced_login_method": "chatgpt",
            "web_search": "disabled",
            "approval_policy": "never",
            "features.shell_tool": False,
            "features.unified_exec": False,
            "features.multi_agent": False,
            "features.apps": False,
            "features.shell_snapshot": False,
            "features.js_repl": False,
            "features.apply_patch_freeform": False,
            "project_doc_max_bytes": 0,
        }
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--model",
            request.settings.model,
            "-o",
            str(output),
            "--output-schema",
            str(schema),
        ]
        for key, value in overrides.items():
            command.extend(["-c", f"{key}={json.dumps(value)}"])
        command.append("-")
        events, returncode = execute(command, request)
        usage, session_id, effective_model = {}, None, None
        for event in events:
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id")
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
            effective_model = event.get("model", effective_model)
        if returncode or not output.exists():
            raise ProviderError(
                f"Codex exited {returncode}; see raw.jsonl/stderr.txt", usage
            )
        return Result(output.read_text(), usage, session_id, effective_model)


class ClaudeProvider:
    """Official Python SDK, isolated in a cancellable process group."""

    def run(self, request: Request) -> Result:
        """Use existing supported login without API fallback or inferred
        model.
        """
        if not request.settings.model.startswith("claude-"):
            raise ValueError("A supported configured Claude model is required")
        command = [
            sys.executable,
            "-m",
            "evidencealpha.claude_runner",
            request.settings.model,
            request.settings.effort,
        ]
        events, returncode = execute(command, request)
        final = next(
            (e for e in reversed(events) if e.get("kind") == "result"), {}
        )
        if any(claude_runner.usage_exhausted(event) for event in events):
            raise QuotaExhausted(
                "Claude explicitly reported usage exhaustion",
                final.get("usage"),
            )
        if returncode or final.get("is_error") or not final.get("text"):
            cause = final.get("subtype", returncode)
            raise ProviderError(
                f"Claude failed: {cause}",
                final.get("usage"),
            )
        return Result(
            final["text"],
            final.get("usage", {}),
            final.get("session_id"),
            final.get("model"),
            final.get("effort"),
        )
