"""Validated application settings and campaign ceilings from package 07."""

import dataclasses
import json
import pathlib

RUNTIME_MODEL = "gpt-5.6-sol"
REVIEW_MODEL = "gpt-6-astra"
REHEARSAL_MODEL = "gpt-5.5"
PROMPT_VERSION = "rubric-review-web-1"
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

    runtime_model: str = RUNTIME_MODEL
    runtime_effort: str = "medium"
    reviewer_model: str = REVIEW_MODEL
    reviewer_effort: str = "medium"
    reviewer_context_tokens: int | None = None
    reviewer_output_tokens: int = 12000
    web_verification: bool = False
    information_cutoff: str | None = None
    profile: str = "low_claude_quota"
    claude_model: str | None = None
    rehearsal_model: str = REHEARSAL_MODEL
    runs_dir: str = "data/redesign/runs"
    ledger: str = "docs/redesign/RUN_BUDGET.json"
    chunk_characters: int = 1600
    retrieval_limit: int = 6  # Legacy settings reader; now reading-block limit.
    candidate_limit: int = 64
    reading_window_characters: int = 8000
    retrieval_mode: str = "rerank"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_revision: str = "953dc6f"
    reranker_path: str | None = None
    reranker_pair_tokens: int = 1024
    reranker_query_tokens: int = 128
    reranker_search_seconds: int = 30
    reranker_stage_seconds: int = 120
    reranker_stage_pairs: int = 2048
    reranker_memory_bytes: int = 8 * 1024**3
    reranker_threads: int = 4
    stage_tool_limit: int = 32
    turn_tool_limit: int = 8
    writer_input_tokens: int = 64000
    writer_context_tokens: int | None = None
    writer_output_tokens: int = 12000
    writer_transport_tokens: int = 4096
    source_open_characters: int = 24000
    embedding_model: str | None = None
    search_env_file: str | None = None
    tool_rounds: int = 8
    workers: int = 2
    contextualize: bool = False
    context_documents: int = 2
    context_characters: int = 12000
    request_memory_bytes: int = 16 * 1024**2
    stage_context_bytes: int = 100000
    stage_seconds: int = 600
    stage_allocations: tuple[int, ...] = (120, 600, 420, 240, 300, 120)
    # Provisional allowances, not measured completion guarantees.
    final_writing_reserve_seconds: int = 180
    invocation_seconds: int = 900
    export_seconds: int = 120
    followup_seconds: int = 900
    review_rounds: int = 4
    company_provider_seconds: int = 600
    company_observable_tokens: int = 12000
    command_seconds: int = 10800
    command_calls: int | None = 16
    command_provider_seconds: int = 3600
    command_observable_tokens: int = 40000
    writing_provider_reserve: int = 900
    writing_calls_reserve: int = 4
    # One optional review completion turn; leave revision/recheck capacity.
    # Accepted only for saved configuration compatibility; no completion loop.
    review_completion_calls: int = 1
    writing_tokens_reserve: int = 16000

    def __post_init__(self) -> None:
        if (
            self.runtime_model != RUNTIME_MODEL
            or self.runtime_effort != "medium"
        ):
            raise ValueError(
                "This execution retains the authorized model/effort"
            )
        if self.reviewer_model != REVIEW_MODEL:
            raise ValueError("Reviewer must use the requested GPT-6 model")
        if self.web_verification and not self.information_cutoff:
            raise ValueError("Web verification needs an information cutoff")
        if self.writer_context_tokens is not None and (
            self.writer_context_tokens
            <= self.writer_output_tokens + self.writer_transport_tokens
        ):
            raise ValueError(
                "Provider capacity cannot contain output/transport"
            )
        if self.command_calls is not None and self.command_calls <= 0:
            raise ValueError("Call ceiling must be positive or null")
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
        if self.retrieval_mode not in ("rerank", "degraded_lexical"):
            raise ValueError("Unknown retrieval mode")
        if self.embedding_model:
            raise ValueError("Embedding fusion is retired; use retrieval_mode")
        if self.review_completion_calls not in (0, 1):
            raise ValueError(
                "Review permits at most one completion opportunity"
            )
        for value in (
            self.request_memory_bytes,
            self.followup_seconds,
            self.review_rounds,
            self.company_provider_seconds,
            self.company_observable_tokens,
            self.command_seconds,
            self.command_provider_seconds,
            self.command_observable_tokens,
            self.writing_provider_reserve,
            self.writing_calls_reserve,
            self.writing_tokens_reserve,
            self.candidate_limit,
            self.reading_window_characters,
            self.reranker_pair_tokens,
            self.reranker_query_tokens,
            self.reranker_search_seconds,
            self.reranker_stage_seconds,
            self.reranker_stage_pairs,
            self.reranker_memory_bytes,
            self.reranker_threads,
            self.stage_tool_limit,
            self.turn_tool_limit,
            self.writer_input_tokens,
            self.writer_output_tokens,
            self.writer_transport_tokens,
            self.chunk_characters,
            self.retrieval_limit,
            self.source_open_characters,
            self.tool_rounds,
            self.stage_seconds,
            self.stage_context_bytes,
            self.export_seconds,
            self.final_writing_reserve_seconds,
            self.invocation_seconds,
        ):
            if value <= 0:
                raise ValueError("Limits must be positive")

    def model(self, role: str, rehearsal: bool = False) -> ModelSettings:
        """Select a model without silently upgrading or changing providers."""
        if role in ("review", "recheck"):
            return ModelSettings(
                "codex", self.reviewer_model, self.reviewer_effort
            )
        if rehearsal:
            return ModelSettings("codex", self.rehearsal_model)
        if self.profile == "preferred":
            if not self.claude_model:
                raise ValueError(
                    "Claude model is not configured; use GPT profile"
                )
            return ModelSettings("claude", self.claude_model)
        return ModelSettings("codex", self.runtime_model, self.runtime_effort)


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


# Prospective fixed-corpus enforcement. Legacy LIMITS retain historical policy.
# All other stage/cumulative allocations are scheduling guidance and telemetry.
EXECUTION_HARD_LIMITS = {
    "command_seconds": "Single elapsed deadline, including tools and waiting",
    "command_calls": "Optional call ceiling; null uses the wall deadline",
    "invocation_seconds": "Provider watchdog within overall deadline",
    "writer_context_tokens": "Supplied verified provider context capacity",
    "writer_output_tokens": "Output headroom reserved within provider context",
    "writer_transport_tokens": "Headroom for provider-added framing",
    "request_memory_bytes": "Request memory protection",
    "workers": "One provider invocation and reranker worker at a time",
    "reranker_memory_bytes": "Sampled worker RSS protection",
    "reranker_threads": "CPU concurrency protection",
    "reranker_search_seconds": "Per-search preparation/scoring watchdog",
    "source_open_characters": "Reject oversized opens; expose continuation",
    "turn_tool_limit": "Bound one response's tool batch; not campaign quota",
    "export_seconds": "Renderer watchdog, enclosed by command deadline",
}
