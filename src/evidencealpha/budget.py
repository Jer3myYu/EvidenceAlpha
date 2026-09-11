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
                "limits": config.LIMITS,
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

    @staticmethod
    def _check(data: dict) -> float:
        if data["limits"] != config.LIMITS:
            raise BudgetExceeded("Ledger limits differ from policy; reconcile")
        started = data["campaign_started"]
        if started is None:
            raise BudgetExceeded("Stage 2 has not been explicitly started")
        remaining = config.LIMITS["session_seconds"] - (time.time() - started)
        if remaining <= 0:
            raise BudgetExceeded("Session window exhausted")
        tokens = sum(
            x.get("observable_tokens") or 0 for x in data["invocations"]
        )
        if tokens >= config.LIMITS["observable_tokens"]:
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
                >= config.LIMITS[
                    "full_attempts" if full else "isolated_attempts"
                ]
            ):
                raise BudgetExceeded("Attempt allowance exhausted")
            if (
                kind in ("peer", "claude")
                and sum(a["kind"] == kind for a in attempts)
                >= config.LIMITS[f"{kind}_attempts"]
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
            cap = config.LIMITS["full_seconds" if full else "isolated_seconds"]
            if kind == "claude":
                cap = config.LIMITS["claude_attempt_seconds"]
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
            used = sum(
                x.get("seconds", x["reserved_seconds"])
                for x in data["invocations"]
            )
            cap = min(
                seconds,
                window,
                attempt["deadline"] - time.time(),
                config.LIMITS["invocation_seconds"] - used,
            )
            if provider == "claude":
                if data["claude_disabled"] or attempt["kind"] != "claude":
                    raise BudgetExceeded("Claude admissions disabled")
                used_claude = sum(
                    x.get("seconds", x["reserved_seconds"])
                    for x in data["invocations"]
                    if x["provider"] == "claude"
                )
                cap = min(cap, config.LIMITS["claude_seconds"] - used_claude)
            if cap <= 0:
                raise BudgetExceeded("Invocation time exhausted")
            entry = {
                "id": uuid.uuid4().hex,
                "attempt": attempt["id"],
                "provider": provider,
                "invoked": artifacts.now(),
                "reserved_seconds": cap,
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
            if data[kind] >= config.LIMITS[kind]:
                raise BudgetExceeded(f"{kind} exhausted")
            data[kind] += 1

    def disable_claude(self, reason: str) -> None:
        """Persist an explicit exhaustion/blocked-provider fallback."""
        with self.locked() as data:
            data["claude_disabled"] = True
            data["profile"] = "low_claude_quota"
            data["fallback_reason"] = reason
