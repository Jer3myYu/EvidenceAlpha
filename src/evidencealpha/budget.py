"""Locked, persistent admission and settlement; crashes retain reservations."""

import contextlib
import fcntl
import pathlib
import time
import uuid
from typing import Iterator

from evidencealpha import artifacts
from evidencealpha import config


class BudgetExceeded(RuntimeError):
    """An enforceable campaign limit prevents admission."""


class Ledger:
    """A single cumulative ledger shared by all workers and sessions."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    @contextlib.contextmanager
    def locked(self) -> Iterator[dict]:
        """Serialize read-modify-write across processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = artifacts.read(self.path)
            try:
                yield data
            finally:
                artifacts.write(self.path, data)
                fcntl.flock(lock, fcntl.LOCK_UN)

    def initialize(self) -> None:
        """Initialize only a new ledger; never reset existing consumption."""
        if self.path.exists():
            return
        artifacts.write(
            self.path,
            {
                "limits": self.limits,
                "profile": "low_claude_quota",
                "campaign_started": None,
                "attempts": [],
                "invocations": [],
                "search_calls": 0,
                "fetch_attempts": 0,
                "claude_disabled": False,
                "stage1_smoke": {
                    "attempts": 0,
                    "limit": 1,
                    "seconds_limit": 90,
                    "seconds": 0,
                    "tokens": None,
                    "status": "not_run",
                },
                "provider_availability": {},
                "coding_session_usage": "not observable by application",
                "enforcement_notes": [
                    "Unknown tokens stay unknown; in-flight usage may overrun.",
                    "Crashed calls retain reservations until reconciled.",
                ],
            },
        )

    @property
    def limits(self) -> dict:
        """Return the fixed policy for this ledger type."""
        return config.LIMITS

    def _check(self, data: dict) -> float:
        if data["limits"] != self.limits:
            raise BudgetExceeded("Ledger limits differ from policy; reconcile")
        started = data["campaign_started"]
        if started is None:
            raise BudgetExceeded("Stage 2 has not been explicitly started")
        remaining = self.limits["session_seconds"] - (time.time() - started)
        if remaining <= 0:
            raise BudgetExceeded("Session window exhausted")
        tokens = sum(
            x.get("observable_tokens") or 0 for x in data["invocations"]
        )
        if tokens >= self.limits["observable_tokens"]:
            raise BudgetExceeded("Observable token allowance exhausted")
        return remaining

    def start(self) -> None:
        """Start the Stage 2 clock on explicit driver invocation only."""
        with self.locked() as data:
            if data["campaign_started"] is None:
                data["campaign_started"] = time.time()
            self._check(data)

    def admit(self, kind: str, provider: str = "codex") -> dict:
        """Persist an isolated/full/peer/probe admission before launching."""
        if kind not in ("isolated", "full", "peer", "claude"):
            raise ValueError("Unknown attempt kind")
        with self.locked() as data:
            remaining = self._check(data)
            attempts = data["attempts"]
            full = kind == "full"
            count = sum((a["kind"] == "full") == full for a in attempts)
            if (
                count
                >= self.limits["full_attempts" if full else "isolated_attempts"]
            ):
                raise BudgetExceeded("Attempt allowance exhausted")
            if (
                kind in ("peer", "claude")
                and sum(a["kind"] == kind for a in attempts)
                >= self.limits[f"{kind}_attempts"]
            ):
                raise BudgetExceeded(f"{kind} sub-budget exhausted")
            if full and any(
                a["kind"] == "full" and a["status"] == "running"
                for a in attempts
            ):
                raise BudgetExceeded("A full report is already running")
            if full and provider != "codex":
                raise BudgetExceeded("Full reports must use Codex")
            if provider == "claude" and (
                kind != "claude" or data["claude_disabled"]
            ):
                raise BudgetExceeded("Claude allowed only in bounded probes")
            cap = self.limits["full_seconds" if full else "isolated_seconds"]
            if kind == "claude":
                cap = self.limits["claude_attempt_seconds"]
            entry = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "started": time.time(),
                "deadline": time.time() + min(cap, remaining),
                "status": "running",
            }
            attempts.append(entry)
            return dict(entry)

    def reserve(self, attempt: dict, provider: str, seconds: float) -> dict:
        """Reserve aggregate invocation time before each provider process."""
        with self.locked() as data:
            window = self._check(data)
            if not any(
                a["id"] == attempt["id"] and a["status"] == "running"
                for a in data["attempts"]
            ):
                raise BudgetExceeded("Attempt is not active")
            if (
                sum(x["status"] == "running" for x in data["invocations"])
                >= self.limits["research_workers"]
            ):
                raise BudgetExceeded("Invocation concurrency exhausted")
            used = sum(
                x.get("seconds", x["reserved_seconds"])
                for x in data["invocations"]
            )
            limits = [
                (seconds, "requested_allowance"),
                (window, "campaign_elapsed"),
                (attempt["deadline"] - time.time(), "attempt_elapsed"),
                (
                    self.limits["invocation_seconds"] - used,
                    "aggregate_invocation",
                ),
            ]
            if provider == "claude":
                if data["claude_disabled"] or attempt["kind"] != "claude":
                    raise BudgetExceeded("Claude admissions disabled")
                used_claude = sum(
                    x.get("seconds", x["reserved_seconds"])
                    for x in data["invocations"]
                    if x["provider"] == "claude"
                )
                limits.append(
                    (
                        self.limits["claude_seconds"] - used_claude,
                        "claude_budget",
                    )
                )
            cap, limiting_resource = min(limits, key=lambda item: item[0])
            if cap <= 0:
                raise BudgetExceeded("Invocation time exhausted")
            entry = {
                "id": uuid.uuid4().hex,
                "attempt": attempt["id"],
                "provider": provider,
                "invoked": artifacts.now(),
                "reserved_seconds": cap,
                "limiting_resource": limiting_resource,
                "observable_tokens": None,
                "status": "running",
            }
            data["invocations"].append(entry)
            return dict(entry)

    def settle(
        self,
        reservation: dict,
        seconds: float,
        status: str,
        usage: dict | None = None,
    ) -> None:
        """Account failed, partial and successful work exactly once."""
        with self.locked() as data:
            entry = next(
                x for x in data["invocations"] if x["id"] == reservation["id"]
            )
            if entry["status"] != "running":
                raise ValueError("Invocation already settled")
            usage = usage or {}
            entry.update(
                seconds=seconds,
                status=status,
                usage=usage,
                completed=artifacts.now(),
                observable_tokens=usage.get("output_tokens"),
            )
            if usage.get("reasoning_in_output") is False and usage.get(
                "reasoning_tokens"
            ):
                entry["observable_tokens"] = (
                    entry["observable_tokens"] or 0
                ) + usage["reasoning_tokens"]

    def finish(self, attempt: dict, status: str) -> None:
        """Settle an outer attempt without erasing its admission."""
        with self.locked() as data:
            entry = next(
                x for x in data["attempts"] if x["id"] == attempt["id"]
            )
            entry.update(status=status, completed=artifacts.now())

    def acquire(self, kind: str) -> None:
        """Count every external search/fetch attempt, including failures."""
        if kind not in ("search_calls", "fetch_attempts"):
            raise ValueError("Unknown acquisition kind")
        with self.locked() as data:
            self._check(data)
            if data[kind] >= self.limits[kind]:
                raise BudgetExceeded(f"{kind} exhausted")
            data[kind] += 1

    def disable_claude(self, reason: str) -> None:
        """Persist an explicit exhaustion/blocked-provider fallback."""
        with self.locked() as data:
            data["claude_disabled"] = True
            data["profile"] = "low_claude_quota"
            data["fallback_reason"] = reason


class DiagnosticLedger(Ledger):
    """The separately authorized A/B/C allowance; never admits full reports."""

    @property
    def limits(self) -> dict:
        """Return the additive diagnostic ceilings, not Stage 2 ceilings."""
        return config.DIAGNOSTIC_LIMITS

    def initialize_linked(self, parent: pathlib.Path) -> None:
        """Create once and bind to the exhausted historical ledger bytes."""
        if self.path.exists():
            return
        self.initialize()
        with self.locked() as data:
            data.pop("stage1_smoke", None)
            data["parent"] = str(parent.resolve())
            data["parent_hash"] = artifacts.digest(parent.read_bytes())
            data["authorization"] = "User additive focused A/B/C diagnosis only"

    def _check(self, data: dict) -> float:
        if (
            artifacts.digest(pathlib.Path(data["parent"]).read_bytes())
            != data["parent_hash"]
        ):
            raise BudgetExceeded("Historical ledger changed; reconcile")
        if any(
            x["status"] not in ("running", "complete", "adequate")
            for x in data["attempts"] + data["invocations"]
        ):
            raise BudgetExceeded("Diagnostic failure stops charged work")
        if any(
            x["status"] == "complete" and x.get("observable_tokens") is None
            for x in data["invocations"]
        ):
            raise BudgetExceeded(
                "Unknown diagnostic usage requires reconciliation"
            )
        return super()._check(data)

    def admit(self, kind: str, provider: str = "codex") -> dict:
        """Admit A then B then conditional C, exactly once and sequentially."""
        with self.locked() as data:
            remaining = self._check(data)
            cases = config.DIAGNOSTIC_CASE_SECONDS
            previous = data["attempts"]
            if (
                provider != "codex"
                or len(previous) >= 3
                or kind != list(cases)[len(previous)]
                or any(x["status"] != "adequate" for x in previous)
            ):
                raise BudgetExceeded(
                    "Only the next adequately preceded case is allowed"
                )
            entry = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "started": time.time(),
                "deadline": time.time() + min(cases[kind], remaining),
                "status": "running",
            }
            previous.append(entry)
            return dict(entry)

    def reserve(self, attempt: dict, provider: str, seconds: float) -> dict:
        """Refuse concurrency, provider switches and retries after failure."""
        with self.locked() as data:
            self._check(data)
            if provider != "codex" or any(
                x["status"] == "running" for x in data["invocations"]
            ):
                raise BudgetExceeded("One Codex invocation at a time")
        return super().reserve(attempt, provider, seconds)

    def acquire(self, kind: str) -> None:
        """External acquisition is outside this allowance."""
        raise BudgetExceeded(f"Diagnostic acquisition prohibited: {kind}")


class ExecutionLedger(Ledger):
    """Configurable fixed-corpus window; historical ledgers remain untouched."""

    def __init__(self, path: pathlib.Path, settings: config.Settings) -> None:
        super().__init__(path)
        self.settings = settings
        self.stage = ""
        self.research = False
        self.final_writing = False
        self.stage_calls = settings.tool_rounds
        self.stage_seconds = settings.command_provider_seconds
        self.stage_tokens = settings.command_observable_tokens

    @property
    def limits(self) -> dict:
        """Freeze supplied ceilings in the additive ledger."""
        return {
            **config.LIMITS,
            "policy": "overall-controls-v2",
            "session_seconds": self.settings.command_seconds,
            "full_seconds": self.settings.command_seconds,
            "full_attempts": 1,
            "research_workers": 1,
            "invocation_seconds": self.settings.command_provider_seconds,
            "observable_tokens": self.settings.command_observable_tokens,
            "generative_calls": self.settings.command_calls,
            "search_calls": None if self.settings.web_verification else 0,
            "fetch_attempts": None if self.settings.web_verification else 0,
        }

    def acquire(self, kind: str) -> None:
        """Meter enabled public verification under the overall controls."""
        if not self.settings.web_verification:
            raise BudgetExceeded("Fixed-corpus acquisition prohibited")
        if kind not in ("search_calls", "fetch_attempts"):
            raise ValueError("Unknown acquisition kind")
        with self.locked() as data:
            self._check(data)
            data[kind] += 1

    def _check(self, data: dict) -> float:
        if data["limits"] != self.limits:
            raise BudgetExceeded("Historical policy differs; use a new run")
        if data["campaign_started"] is None:
            raise BudgetExceeded("Execution clock has not started")
        remaining = self.settings.command_seconds - (
            time.time() - data["campaign_started"]
        )
        if remaining <= 0:
            raise BudgetExceeded("Session window exhausted")
        if (
            self.settings.command_calls is not None
            and len(data["invocations"]) >= self.settings.command_calls
        ):
            raise BudgetExceeded("Generative call ceiling reached")
        return remaining

    def writing_due(self) -> bool:
        """Offer writing before the shared call supply runs out."""
        if not self.research or self.settings.command_calls is None:
            return False
        data = artifacts.read(self.path)
        return len(data["invocations"]) >= (
            self.settings.command_calls - self.settings.writing_calls_reserve
        )

    def reserve(self, attempt: dict, provider: str, seconds: float) -> dict:
        """Atomically admit against the overall deadline and watchdog only."""
        with self.locked() as data:
            window = self._check(data)
            if not any(
                a["id"] == attempt["id"] and a["status"] == "running"
                for a in data["attempts"]
            ):
                raise BudgetExceeded("Attempt is not active")
            if any(x["status"] == "running" for x in data["invocations"]):
                raise BudgetExceeded("Invocation concurrency exhausted")
            cap, resource = min(
                (window, "campaign_elapsed"),
                (attempt["deadline"] - time.time(), "campaign_elapsed"),
                (self.settings.invocation_seconds, "invocation_watchdog"),
                (seconds, "caller_deadline"),
            )
            if cap <= 0:
                raise BudgetExceeded("Invocation deadline expired")
            entry = {
                "id": uuid.uuid4().hex,
                "attempt": attempt["id"],
                "provider": provider,
                "invoked": artifacts.now(),
                "reserved_seconds": cap,
                "limiting_resource": resource,
                "observable_tokens": None,
                "status": "running",
                "stage": self.stage,
            }
            data["invocations"].append(entry)
            return dict(entry)
