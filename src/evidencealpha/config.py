"""Validated application settings and campaign ceilings from package 07."""

import dataclasses
import json
import pathlib

RUNTIME_MODEL = "gpt-5.6-sol"
REHEARSAL_MODEL = "gpt-5.5"
PROMPT_VERSION = "redesign-3-phases"
LIMITS = {
    "session_seconds": 28800,
    "isolated_attempts": 10,
    "isolated_seconds": 360,
    "full_attempts": 2,
    "full_seconds": 1800,
    "invocation_seconds": 7200,
    "observable_tokens": 100000,
    "research_workers": 2,
    "peer_attempts": 2,
    "search_calls": 40,
    "fetch_attempts": 60,
    "reviews": 1,
    "revisions": 1,
    "rechecks": 1,
    "claude_attempts": 3,
    "claude_attempt_seconds": 120,
    "claude_seconds": 360,
}


@dataclasses.dataclass(frozen=True)
class ModelSettings:
    """Explicit provider selection."""

    provider: str
    model: str
    effort: str = "medium"


@dataclasses.dataclass(frozen=True)
class Settings:
    """Shared defaults with small, validated JSON overrides."""

    profile: str = "low_claude_quota"
    claude_model: str | None = None
    rehearsal_model: str = REHEARSAL_MODEL
    runs_dir: str = "data/redesign/runs"
    ledger: str = "docs/redesign/RUN_BUDGET.json"
    chunk_characters: int = 1600
    retrieval_limit: int = 6
    source_open_characters: int = 24000
    embedding_model: str | None = None
    search_env_file: str | None = None
    tool_rounds: int = 8
    workers: int = 2
    contextualize: bool = False
    context_documents: int = 2
    context_characters: int = 12000
    stage_context_bytes: int = 100000
    stage_seconds: int = 360
    stage_allocations: tuple[int, ...] = (120, 480, 420, 240, 300, 120)
    export_seconds: int = 120

    def __post_init__(self) -> None:
        if self.rehearsal_model not in (REHEARSAL_MODEL, RUNTIME_MODEL):
            raise ValueError("Rehearsals allow only policy-approved models")
        if self.profile not in ("low_claude_quota", "preferred"):
            raise ValueError("Unknown profile")
        if self.claude_model and not self.claude_model.startswith("claude-"):
            raise ValueError("Explicit supported Claude model required")
        if not 1 <= self.workers <= LIMITS["research_workers"]:
            raise ValueError("Research concurrency must be 1 or 2")
        if len(self.stage_allocations) != 6 or any(
            value <= 0 for value in self.stage_allocations
        ):
            raise ValueError("Six positive stage allocations required")
        for value in (
            self.chunk_characters,
            self.retrieval_limit,
            self.source_open_characters,
            self.tool_rounds,
            self.stage_seconds,
            self.stage_context_bytes,
            self.export_seconds,
        ):
            if value <= 0:
                raise ValueError("Limits must be positive")

    def model(self, role: str, rehearsal: bool = False) -> ModelSettings:
        """Select a model without silently upgrading or changing providers."""
        if role in ("review", "recheck"):
            return ModelSettings("codex", RUNTIME_MODEL)
        if rehearsal:
            return ModelSettings("codex", self.rehearsal_model)
        if self.profile == "preferred":
            if not self.claude_model:
                raise ValueError(
                    "Claude model is not configured; use GPT profile"
                )
            return ModelSettings("claude", self.claude_model)
        return ModelSettings("codex", RUNTIME_MODEL)


def load(path: pathlib.Path | None = None) -> Settings:
    """Load one explicit config file; never load credential files."""
    return Settings(**json.loads(path.read_text())) if path else Settings()


# Explicit additive user authorization; historical LIMITS and ledger unchanged.
DIAGNOSTIC_CASE_SECONDS = {"A": 180, "B": 180, "C": 300}
DIAGNOSTIC_LIMITS = {
    "session_seconds": 1800,
    "invocation_seconds": 660,
    "observable_tokens": 16000,
    "isolated_attempts": 3,
    "full_attempts": 0,
    "research_workers": 1,
    "search_calls": 0,
    "fetch_attempts": 0,
}
