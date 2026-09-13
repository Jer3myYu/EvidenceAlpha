"""One bounded research workflow with portable stage inputs and replay."""

import concurrent.futures
import copy
import dataclasses
import json
import itertools
import math
import pathlib
import re
import shutil
import time
import uuid

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import handoff as evidence_handoff
from evidencealpha import providers
from evidencealpha import reading
from evidencealpha import render
from evidencealpha import presentation
from evidencealpha import retrieval
from evidencealpha import reranking
from evidencealpha import review as review_contract
from evidencealpha import stage_context
from evidencealpha import tools


class ResearchHandoffError(providers.ProviderError):
    """A failed worker with bounded original evidence, not final findings."""

    def __init__(self, message: str, handoff: dict) -> None:
        super().__init__(message)
        self.handoff = handoff


def review_followup_input(review: dict) -> dict:
    """Keep writing originals; compact navigation repeated after review."""
    return {
        **{
            key: value
            for key, value in review.items()
            if key
            not in (
                "notes",
                "plan",
                "gaps",
                "unsynthesized_evidence",
                "supplemental_findings",
                "review_inventory",
            )
        },
        "sources": [
            {k: v for k, v in source.items() if k != "identifying_passage"}
            for source in review.get("sources", [])
        ],
    }


def revision_input(review: dict, findings: dict) -> dict:
    """Keep the draft, requirements and originals; omit upstream repetition."""
    return {
        **review_followup_input(review),
        "findings": {
            k: v for k, v in findings.items() if k in ("content", "issues")
        },
        "instruction": "Correct supported material issues; reject unsupported "
        "objections against originals. Disclose unresolved conclusions.",
    }


class StageRunner:
    """Own tool rounds."""

    def __init__(
        self,
        settings: config.Settings,
        provider: providers.Provider,
        evidence_tools: tools.EvidenceTools,
        ledger: budget.Ledger | None = None,
        campaign_attempt: dict | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.tools = evidence_tools
        self.ledger = ledger
        self.campaign_attempt = campaign_attempt

    def run(
        self,
        stage: str,
        role: str,
        portable: dict,
        root: pathlib.Path,
        rehearsal: bool = False,
        seconds: float | None = None,
        deadline: float | None = None,
        final_notes_only: bool = False,
    ) -> dict:
        """Record a new attempt."""
        stage_tools = copy.copy(self.tools)
        if stage_tools.mode == "verification":
            stage_tools.mode = (
                "live"
                if self.settings.web_verification
                and (
                    role in ("review", "recheck") or stage == "review-followup"
                )
                else "fixed-corpus"
            )
        scorer = self.tools.retriever.scorer
        stage_tools.retriever = retrieval.Retriever(
            self.tools.store,
            self.settings,
            None if isinstance(scorer, reranking.LocalReranker) else scorer,
        )
        # Scores are reusable only for identical query/views/version/settings.
        # Each uncached search still launches and reloads its own scorer.
        stage_tools.retriever.cache = self.tools.retriever.cache
        folder = root / "stages" / stage / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True)
        prompt_path = pathlib.Path(__file__).parent / "prompts"
        instructions = (
            (prompt_path / "common.md").read_text()
            + "\n"
            + (prompt_path / f"{role}.md").read_text()
        )
        settings = self.settings.model(role, rehearsal)
        if (
            self.ledger
            and settings.provider == "claude"
            and artifacts.read(self.ledger.path)["claude_disabled"]
        ):
            settings = config.ModelSettings("codex", config.RUNTIME_MODEL)
        record = {
            "stage": stage,
            "role": role,
            "final_notes_only": final_notes_only,
            "portable": portable,
            "instructions": instructions,
            "tools": stage_tools.definitions(),
            "settings": dataclasses.asdict(settings),
            "prompt_version": config.PROMPT_VERSION,
            "mode": stage_tools.mode,
            "native_tool_enforcement": (
                "no provider calls"
                if isinstance(self.provider, providers.FixtureProvider)
                else "configured controls; integration validation pending"
            ),
            "replay_mode": "fresh_portable_session",
            "upstream_hash": artifacts.digest(portable),
            "seconds": (
                seconds if seconds is not None else self.settings.stage_seconds
            ),
        }
        artifacts.write(folder / "input.json", record)
        stage_tools.retriever.trace_dir = folder / "retrieval"
        context = stage_context.StageContext(
            folder / "context-state.json",
            {k: v for k, v in portable.items() if k != "settled_evidence"},
        )
        checkpoint = portable.get("continuation_checkpoint")
        if checkpoint:
            prior_path = artifacts.contained(root, checkpoint["state"])
            if (
                artifacts.digest(prior_path.read_bytes())
                != checkpoint["state_hash"]
            ):
                raise ValueError("Research checkpoint changed")
            prior = artifacts.read(prior_path)
            if prior["task"].get("task") != portable.get("task"):
                raise ValueError("Research checkpoint task changed")
            current_task = context.data["task"]
            context.data = copy.deepcopy(prior)
            context.data["task"] = current_task
            stage_tools.retriever.pairs = checkpoint["pairs"]
            stage_tools.retriever.seconds = checkpoint["retrieval_seconds"]
        context.settle(portable.get("settled_evidence", {}))
        started_stage = time.monotonic()
        deadline, stage_limit = min(
            (started_stage + record["seconds"], "worker_elapsed"),
            (
                deadline if deadline is not None else float("inf"),
                "enclosing_deadline",
            ),
            key=lambda item: item[0],
        )
        live_execution = isinstance(self.ledger, budget.ExecutionLedger)
        if live_execution:
            deadline = started_stage + max(
                0, self.campaign_attempt["deadline"] - time.time()
            )
            stage_limit = "campaign_elapsed"
        duration = max(0, deadline - started_stage)
        reserve = min(self.settings.final_writing_reserve_seconds, duration)
        evidence_end = (
            deadline - reserve
            if role in ("company", "industry", "revision")
            else deadline
        )
        if final_notes_only:
            evidence_end = started_stage
        if live_execution and not final_notes_only:
            evidence_end = deadline
        final_end = deadline
        artifacts.write(
            folder / "timing.json",
            {
                "stage_deadline_monotonic": deadline,
                "stage_limiting_resource": stage_limit,
                "evidence_deadline_monotonic": evidence_end,
                "final_deadline_monotonic": final_end,
                "final_writing_reserve_seconds": reserve,
                "invocation_seconds": self.settings.invocation_seconds,
                "final_notes_only": final_notes_only,
            },
        )
        tool_count = checkpoint["tool_count"] if checkpoint else 0
        requested_writing = False
        phase = "evidence"
        longest_call = 0.0
        phase_outcomes = []
        event_path = folder / "events.jsonl"
        status = "failed"
        try:
            if checkpoint and checkpoint.get("pending_output"):
                pending_path = artifacts.contained(
                    root, checkpoint["pending_output"]
                )
                if (
                    artifacts.digest(pending_path.read_bytes())
                    != checkpoint["pending_hash"]
                ):
                    raise ValueError("Pending response changed")
                pending = parse_output(pending_path.read_text(), role)
                context.update_coverage(
                    pending.get("coverage_updates", []),
                    pending.get("stop_reason"),
                )
                for call in pending.get("tool_calls", []):
                    if (
                        not live_execution
                        and tool_count >= self.settings.stage_tool_limit
                    ) or time.monotonic() >= evidence_end:
                        raise providers.ProviderError(
                            "Checkpoint tool budget exhausted"
                        )
                    tool_count += 1
                    tool_started = time.monotonic()
                    value = stage_tools.call(
                        call["name"], call["arguments"], deadline=evidence_end
                    )
                    context.settle(value, call["arguments"].get("question_id"))
                    context.outcome(call["name"], call["arguments"], value)
                    artifacts.event(
                        event_path,
                        "tool",
                        name=call["name"],
                        arguments=call["arguments"],
                        result=value,
                        seconds=time.monotonic() - tool_started,
                        checkpoint_continuation=True,
                    )
                artifacts.write(context.path, context.data)
            rounds = (
                self.settings.command_calls
                if live_execution
                else self.settings.tool_rounds
            )
            for turn in (
                range(rounds) if rounds is not None else itertools.count()
            ):
                evidence_remaining = evidence_end - time.monotonic()
                should_write = (
                    final_notes_only
                    or (
                        isinstance(self.ledger, budget.ExecutionLedger)
                        and self.ledger.writing_due()
                    )
                    or requested_writing
                    or (
                        not live_execution
                        and tool_count >= self.settings.stage_tool_limit
                    )
                    or (rounds is not None and turn == rounds - 1)
                    or evidence_remaining <= longest_call
                    or (not live_execution and role == "revision" and turn >= 2)
                )
                if phase == "evidence" and should_write:
                    context.data["stop_reason"] = context.data[
                        "stop_reason"
                    ] or (
                        "tool_limit"
                        if tool_count >= self.settings.stage_tool_limit
                        else (
                            "turn_limit"
                            if turn == self.settings.tool_rounds - 1
                            else (
                                "writing_requested"
                                if requested_writing or final_notes_only
                                else "protected_writing_deadline"
                            )
                        )
                    )
                    phase = "final_notes"
                    if not phase_outcomes:
                        phase_outcomes.append(
                            {
                                "phase": "evidence",
                                "outcome": "writing_requested",
                            }
                        )
                    artifacts.write(
                        folder / "phase-outcomes.json", phase_outcomes
                    )
                    artifacts.event(
                        event_path,
                        "phase_transition",
                        phase=phase,
                        evidence_remaining=evidence_remaining,
                        prior_call_seconds=longest_call,
                    )
                final_turn = phase == "final_notes"
                call_deadline = final_end if final_turn else evidence_end
                limit = (
                    stage_limit
                    if final_turn
                    else (
                        "protected_final_writing"
                        if evidence_end < final_end
                        else stage_limit
                    )
                )
                remaining = call_deadline - time.monotonic()
                if remaining <= 0:
                    raise providers.ProviderError("Stage deadline expired")
                call_dir = folder / f"call-{turn}"
                available_tools = {} if final_turn else record["tools"]
                if (
                    stage_tools.mode != "fixture"
                    and not isinstance(self.provider, providers.FixtureProvider)
                    and not self.settings.writer_context_tokens
                ):
                    raise ValueError(
                        "Writer capacity unconfirmed; live admission blocked"
                    )
                input_tokens = self.settings.writer_input_tokens
                if self.settings.writer_context_tokens:
                    input_tokens = (
                        self.settings.writer_context_tokens
                        - self.settings.writer_output_tokens
                        - self.settings.writer_transport_tokens
                    )
                if role in ("review", "recheck") and live_execution:
                    if not self.settings.reviewer_context_tokens:
                        raise ValueError("GPT-6 review capacity is unconfirmed")
                    input_tokens = (
                        self.settings.reviewer_context_tokens
                        - self.settings.reviewer_output_tokens
                        - self.settings.writer_transport_tokens
                    )
                if live_execution:
                    used = artifacts.read(self.ledger.path)["invocations"]
                    context.data["task"]["scheduling_guidance"] = {
                        "stage_call_target": self.ledger.stage_calls,
                        "stage_calls_used": sum(
                            x.get("stage") == stage for x in used
                        ),
                        "overall_calls_remaining": (
                            self.settings.command_calls - len(used)
                            if self.settings.command_calls is not None
                            else None
                        ),
                        "stage_seconds_target": record["seconds"],
                        "stage_seconds_used": time.monotonic() - started_stage,
                        "instruction": (
                            "Targets are guidance. Finish useful "
                            "context opens and concise final notes; leave "
                            "capacity for other researchers, synthesis, review "
                            "and revision. Do not certify absence from "
                            "an unsuccessful search or a narrow excerpt."
                        ),
                    }
                prompt, current_context = context.request(
                    instructions,
                    available_tools,
                    phase,
                    rounds - turn if rounds is not None else None,
                    (
                        self.settings.request_memory_bytes
                        if live_execution
                        else self.settings.stage_context_bytes
                    ),
                    input_tokens,
                )
                artifacts.write(call_dir / "context.json", current_context)
                if final_turn:
                    artifacts.write(
                        folder / "writing-context.json", current_context
                    )
                admission_started = time.monotonic()
                call_deadline, limit = min(
                    (call_deadline, limit),
                    (
                        admission_started + self.settings.invocation_seconds,
                        "configured_invocation",
                    ),
                    key=lambda item: item[0],
                )
                remaining = call_deadline - admission_started
                reservation = None
                if self.ledger:
                    if isinstance(self.ledger, budget.ExecutionLedger):
                        self.ledger.final_writing = final_turn
                    reservation = self.ledger.reserve(
                        self.campaign_attempt, settings.provider, remaining
                    )
                    if reservation["reserved_seconds"] < remaining:
                        call_deadline = (
                            admission_started + reservation["reserved_seconds"]
                        )
                        limit = reservation.get(
                            "limiting_resource", "ledger_budget"
                        )
                request = providers.Request(
                    stage,
                    prompt,
                    settings,
                    call_dir.resolve(),
                    max(0, call_deadline - time.monotonic()),
                    call_deadline,
                    tuple(available_tools),
                    limit,
                )
                artifacts.write(
                    call_dir / "limits.json",
                    {
                        "phase": phase,
                        "deadline": call_deadline,
                        "limiting_resource": limit,
                        "configured_invocation_seconds": (
                            self.settings.invocation_seconds
                        ),
                        "worker_deadline": final_end,
                    },
                )
                artifacts.write(call_dir / "request.txt", prompt)
                artifacts.write(
                    call_dir / "settings.json", dataclasses.asdict(settings)
                )
                started = time.monotonic()
                result, call_status = None, "failed"
                usage = {}
                try:
                    provider = self.provider
                    if isinstance(
                        provider,
                        (providers.CodexProvider, providers.ClaudeProvider),
                    ):
                        provider = (
                            providers.CodexProvider()
                            if settings.provider == "codex"
                            else providers.ClaudeProvider()
                        )
                    artifacts.write(
                        call_dir / "model-identity.json",
                        {
                            "requested_model": settings.model,
                            "actual_model": None,
                            "status": "awaiting_provider_result",
                        },
                    )
                    result = provider.run(request)
                    usage = result.usage
                    artifacts.write(
                        call_dir / "model-identity.json",
                        {
                            "requested_model": settings.model,
                            "actual_model": result.effective_model,
                            "status": (
                                "provider_reported"
                                if result.effective_model
                                else "not_reported_by_provider"
                            ),
                        },
                    )
                    if (
                        result.effective_model
                        and result.effective_model
                        not in (settings.model, "fixture")
                    ):
                        raise providers.ProviderError(
                            "Provider model mismatch", usage
                        )
                    call_status = "complete"
                except providers.QuotaExhausted as exc:
                    usage = exc.usage
                    if settings.provider != "claude" or not self.ledger:
                        raise
                    self.ledger.disable_claude(str(exc))
                    artifacts.event(
                        event_path,
                        "provider_fallback",
                        reason=str(exc),
                        previous=dataclasses.asdict(settings),
                    )
                    settings = config.ModelSettings(
                        "codex", config.RUNTIME_MODEL
                    )
                    # Fresh portable session; keep public
                    # tool results, never private context.
                    continue
                except providers.ProviderTimeout as exc:
                    usage = exc.usage
                    failure = {
                        "error": str(exc),
                        "phase": phase,
                        "deadline": exc.deadline,
                        "ended_by": exc.limit,
                        "call": call_dir.name,
                        "status": "failed",
                    }
                    artifacts.write(call_dir / "failure.json", failure)
                    artifacts.event(event_path, "provider_timeout", **failure)
                    raise
                except providers.ProviderError as exc:
                    usage = exc.usage
                    raise
                finally:
                    if reservation:
                        self.ledger.settle(
                            reservation,
                            time.monotonic() - started,
                            call_status,
                            usage,
                        )
                longest_call = max(longest_call, time.monotonic() - started)
                artifacts.write(
                    call_dir / "normalized.json", dataclasses.asdict(result)
                )
                artifacts.event(
                    event_path,
                    "provider_result",
                    usage=usage,
                    session_id=result.session_id,
                    requested=dataclasses.asdict(settings),
                    effective_model=result.effective_model,
                    effective_effort=result.effective_effort,
                    seconds=time.monotonic() - started,
                    prompt_bytes=len(prompt.encode()),
                )
                if time.monotonic() >= deadline:
                    raise providers.ProviderError("Stage deadline expired")
                output = parse_output(result.text, role)
                try:
                    context.update_coverage(
                        output.get("coverage_updates", []),
                        output.get("stop_reason"),
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    context.outcome(
                        "coverage_update", {}, {"error": str(exc)}, "error"
                    )
                if output.get("content") and output.get("tool_calls"):
                    context.outcome(
                        "research_note", {}, output["content"], "unverified"
                    )
                if not output.get("tool_calls"):
                    if not final_turn and role in (
                        "company",
                        "industry",
                        "revision",
                    ):
                        requested_writing = True
                        context.outcome(
                            "research_note",
                            {},
                            output.get("content", ""),
                            "unverified",
                        )
                        continue
                    if role in ("review", "recheck"):
                        for issue in output["issues"]:
                            for ref in issue.get("original_passages", []):
                                original = stage_tools.store.open_source(
                                    ref["source_id"], ref["chunk_id"]
                                )
                                if ref["quote"] not in original["text"]:
                                    raise ValueError(
                                        "Review quote is absent from original"
                                    )
                    if role in ("review", "recheck"):
                        artifacts.write(
                            call_dir / "review-assessment.json",
                            review_contract.assess(output, stage_tools.store),
                        )
                    phase_outcomes.append(
                        {"phase": "final_notes", "outcome": "complete"}
                    )
                    artifacts.write(
                        folder / "phase-outcomes.json", phase_outcomes
                    )
                    status = "complete"
                    artifacts.write(folder / "output.json", output)
                    artifacts.write(folder / "output.md", output["content"])
                    return {
                        "path": str(folder.relative_to(root)),
                        "input_hash": artifacts.digest(portable),
                        "output_hash": artifacts.digest(output),
                        "output": output,
                    }
                if final_turn:
                    raise providers.ProviderError(
                        "Final response requested tools"
                    )
                for index, call in enumerate(output["tool_calls"]):
                    if (
                        time.monotonic() >= evidence_end
                        or (
                            not live_execution
                            and tool_count >= self.settings.stage_tool_limit
                        )
                        or index >= self.settings.turn_tool_limit
                    ):
                        for pending in output["tool_calls"][index:]:
                            context.outcome(
                                pending["name"],
                                pending["arguments"],
                                {"reason": "Phase ended; tool not run"},
                                "not_executed",
                            )
                        break
                    source_versions = {
                        s["id"]: s["hash"] for s in stage_tools.store.sources()
                    }
                    tool_count += 1
                    tool_started = time.monotonic()
                    try:
                        qid = call["arguments"].get("question_id")
                        if qid and qid not in context.data["questions"]:
                            raise ValueError("Unknown tool question ID")
                        value = stage_tools.call(
                            call["name"],
                            call["arguments"],
                            deadline=evidence_end,
                        )
                    except (
                        providers.ProviderCancelled,
                        providers.QuotaExhausted,
                    ):
                        raise
                    except (OSError, ValueError, RuntimeError) as exc:
                        value = {"error": str(exc), "type": type(exc).__name__}
                    artifacts.event(
                        event_path,
                        "tool",
                        name=call["name"],
                        arguments=call["arguments"],
                        sources=source_versions,
                        result=value,
                        seconds=time.monotonic() - tool_started,
                    )
                    if isinstance(value, dict):
                        context.settle(
                            value, call["arguments"].get("question_id")
                        )
                    context.outcome(call["name"], call["arguments"], value)
            raise providers.ProviderError(
                "Tool-round limit reached; no final output"
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            artifacts.event(
                event_path,
                "error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            phase_outcomes.append(
                {
                    "phase": phase,
                    "outcome": "terminal_failure",
                    "type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            artifacts.write(folder / "phase-outcomes.json", phase_outcomes)
            context.outcome(
                "stage", {"phase": phase}, {"error": str(exc)}, "failed"
            )
            if role in ("company", "industry"):
                try:
                    _, handoff = context.request(
                        instructions,
                        {},
                        "final_notes",
                        0,
                        (
                            self.settings.request_memory_bytes
                            if live_execution
                            else self.settings.stage_context_bytes
                        ),
                    )
                except ValueError as context_error:
                    # The full task/evidence remain durable even when the task
                    # itself cannot fit. Never mask the original failure.
                    handoff = {
                        "context_record": str(context.path),
                        "context_error": str(context_error),
                    }
                handoff.update(status="unsynthesized_evidence", error=str(exc))
                artifacts.write(folder / "handoff.json", handoff)
                if isinstance(exc, providers.ProviderCancelled):
                    raise
                raise ResearchHandoffError(str(exc), handoff) from exc
            raise
        finally:
            stage_tools.retriever.close()
            artifacts.write(
                folder / "work-usage.json",
                {
                    "tool_executions": tool_count,
                    "reranker_pairs": stage_tools.retriever.pairs,
                    "retrieval_seconds": stage_tools.retriever.seconds,
                    "stop_reason": context.data["stop_reason"],
                },
            )
            artifacts.write(
                folder / "status.json",
                {"status": status, "completed": artifacts.now()},
            )


def parse_output(text: str, role: str) -> dict:
    """Validate the small control envelope."""
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Provider output must be a JSON object")
    calls = value.get("tool_calls", [])
    if not isinstance(calls, list):
        raise ValueError("tool_calls must be a list")
    for call in calls:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("name"), str)
            or not isinstance(call.get("arguments"), dict)
        ):
            raise ValueError("Malformed tool call")
    if calls:
        return value
    if (
        not isinstance(value.get("content"), str)
        or not value["content"].strip()
    ):
        raise ValueError("Empty provider content")
    figures = value.get("figures", [])
    if not isinstance(figures, list) or any(
        not isinstance(f, dict) for f in figures
    ):
        raise ValueError("Figures must be a list of records")
    for figure in figures:
        if figure.get("kind") not in ("bar", "diagram"):
            raise ValueError("Unsupported figure kind")
        if figure["kind"] == "bar":
            numbers = figure.get("values", [])
            if not isinstance(numbers, list) or any(
                n is not None
                and (not isinstance(n, (int, float)) or not math.isfinite(n))
                for n in numbers
            ):
                raise ValueError("Figure values must be finite numbers or null")
    if role == "plan":
        tasks = value.get("tasks", [])
        if not isinstance(tasks, list) or any(
            not isinstance(t, dict) for t in tasks
        ):
            raise ValueError("Plan tasks must be records")
    if role in ("review", "recheck"):
        if not isinstance(value.get("issues"), list):
            raise ValueError("Review must explicitly supply issues")
        for issue in value["issues"]:
            if not isinstance(issue, dict):
                raise ValueError("Review findings must be records")
            if issue.get("severity") not in ("material", "optional") or any(
                not isinstance(issue.get(key), str) or not issue[key].strip()
                for key in ("location", "evidence", "impact", "suggestion")
            ):
                raise ValueError("Malformed review finding")
            if issue.get("kind", "factual") not in review_contract.ISSUE_KINDS:
                raise ValueError("Unknown material issue kind")
            refs = issue.get("original_passages", [])
            if (
                issue["severity"] == "material"
                and issue.get("kind", "factual") == "factual"
                and not refs
            ):
                raise ValueError(
                    "Material objections require original passages"
                )
            if not isinstance(refs, list) or any(
                not isinstance(ref, dict)
                or any(
                    not isinstance(ref.get(key), str) or not ref[key].strip()
                    for key in ("source_id", "chunk_id", "quote")
                )
                for ref in refs
            ):
                raise ValueError("Malformed original passage reference")
    return value


def _source_inputs(store: documents.SourceStore, ids: list[str]) -> list[dict]:
    result = []
    for source_id in ids:
        item = store.open_source(source_id)
        source = item["source"]
        result.append(
            {
                **store.source_context(source_id),
                "hash": source["hash"],
                "text_hash": source["text_hash"],
                "url": source["url"],
                "chunk_count": len(source["chunks"]),
                "identifying_passage": (
                    store.concise_passage(
                        store.open_source(source_id, source["chunks"][0]["id"])
                    )
                    if source["chunks"]
                    else None
                ),
                "warnings": source["warnings"],
            }
        )
    return result


def _prepare_report(
    output: dict,
    reports: pathlib.Path,
    store: documents.SourceStore,
    name: str,
    information_cutoff: str | None = None,
) -> pathlib.Path:
    artifacts.write(reports / name, output["content"])
    specs = output.get("figures", [])
    version = pathlib.Path(name).stem
    manifest = render.figures(
        specs, reports / version, {s["id"] for s in store.sources()}
    )
    for figure in manifest:
        for key in ("path", "input", "code"):
            figure[key] = f"{version}/{figure[key]}"
    artifacts.write(reports / "figures.json", manifest)
    body = output["content"].replace("](" + "figures/", f"]({version}/figures/")
    # A revision may retain the prior draft directory. Bind known figure
    # filenames to the new manifest before deciding a figure is missing.
    for figure in manifest:
        filename = pathlib.Path(figure["path"]).name
        pattern = r"(!\[[^\]]*\]\()([^\s)]+)(\))"
        body = re.sub(
            pattern,
            lambda match, figure=figure, filename=filename: (
                match[1] + figure["path"] + match[3]
                if pathlib.Path(match[2]).name == filename
                else match[0]
            ),
            body,
        )
    for index, figure in enumerate(manifest, 1):
        caption = (
            f'\n图 {index}：{figure["caption"]} '
            f'({figure["period"]}; {figure["unit"]})。'
            f'{figure["caveats"]}\n'
        )
        caption += "来源：" + ", ".join(figure["source_ids"]) + "\n"
        pattern = r"(!\[[^\]]*\]\(" + re.escape(figure["path"]) + r"\))"
        existing = re.search(pattern + r"\s*\n\s*图\s*\d+", body)
        body, count = re.subn(
            pattern,
            lambda match, caption=caption, existing=existing: match[0]
            + ("" if existing else "\n" + caption),
            body,
            count=1,
        )
        if not count:
            body += f'\n\n![{figure["title"]}]({figure["path"]})\n' + caption
    missing_sources = [s for s in store.sources() if s["url"] not in body]
    if missing_sources:
        body += "\n\n## Sources / 来源\n\n"
        for source in missing_sources:
            label = source["id"]
            body += f'- [{label}]({source["url"]})\n'
    mapping_path = reports / "source-map.json"
    mapping = {
        value["source_id"]: alias
        for alias, value in (
            artifacts.read(mapping_path).items()
            if mapping_path.exists()
            else []
        )
    }
    for source in store.sources():
        if source["id"] not in mapping:
            mapping[source["id"]] = f"S{len(mapping) + 1}"
    for source_id, alias in mapping.items():
        body = body.replace(source_id, alias)
    artifacts.write(
        reports / "source-map.json",
        {
            alias: {**store.source_context(sid), "source_id": sid}
            for sid, alias in mapping.items()
        },
    )
    for sid, alias in mapping.items():
        context = store.source_context(sid)
        label = presentation.source_label(alias, context)
        url = context["url"]
        body = body.replace(f"[{alias}]({url})", f"[{label}]({url})")
        body = re.sub(
            r"(?m)^(来源：[^\n]*)\b" + re.escape(alias) + r"\b",
            lambda match, label=label, url=url: (
                match[1] + f"[{label}]({url})"
            ),
            body,
        )
    body = re.sub(r"(?m)^((?:- )?\*\*[^*\n]+)([：:。])(\*\*)", r"\1\3\2", body)
    body, locations = presentation.citation_pages(
        body, {alias: sid for sid, alias in mapping.items()}, store
    )
    artifacts.write(reports / "citation-pages.json", locations)
    body = presentation.table_notes(body)
    lines = body.splitlines()
    lines[:8] = [
        line
        for line in lines[:8]
        if not (line.startswith("报告日期：") and " · 信息截止：" in line)
    ]
    body = "\n".join(lines)
    report_date = artifacts.now()[:10]
    cutoff = information_cutoff or "未指定"
    code_version = artifacts.revision()["head"][:7]
    metadata = (
        f"报告日期：{report_date} · 信息截止："
        f"{cutoff} · 版本："
        f"{code_version}"
    )
    first, separator, rest = body.partition("\n")
    body = first + separator + "\n" + metadata + "\n\n" + rest
    path = reports / name
    artifacts.write(path, body)
    return path


def run(
    brief: dict,
    settings: config.Settings,
    provider: providers.Provider,
    source_paths: list[pathlib.Path],
    root: pathlib.Path,
    mode: str = "fixture",
    ledger: budget.Ledger | None = None,
    campaign_attempt: dict | None = None,
    resume: bool = False,
    source_corpus: pathlib.Path | None = None,
    execution: dict | None = None,
    replay_runner: object | None = None,
) -> dict:
    """Run one plan/research/write/review/revise/recheck path."""
    if mode not in ("fixture", "fixed-corpus", "live", "verification"):
        raise ValueError("Unknown run mode")
    if not isinstance(provider, providers.FixtureProvider) and not ledger:
        raise ValueError("Model runs require an admitted campaign attempt")
    if mode == "fixed-corpus" and settings.web_verification:
        raise ValueError("Fixed-corpus mode cannot enable web verification")
    execution = execution or {}
    root.mkdir(parents=True, exist_ok=resume or bool(execution))
    manifest_path = root / execution.get("manifest_file", "manifest.json")
    store = documents.SourceStore(root / "sources", settings.chunk_characters)
    if resume:
        manifest = artifacts.read(manifest_path)
        brief = manifest["brief"]
        if not execution.get("continuation") and manifest[
            "settings"
        ] != json.loads(json.dumps(dataclasses.asdict(settings))):
            raise ValueError(
                "Settings changed; fork a run rather than reuse stale stages"
            )
    else:
        if source_corpus:
            shutil.copytree(source_corpus, store.root, dirs_exist_ok=True)
        for path in source_paths:
            store.ingest(path)
        sources = store.sources()
        manifest = {
            "id": root.name,
            "brief": brief,
            "mode": mode,
            "settings": dataclasses.asdict(settings),
            "revision": artifacts.revision(),
            "started": artifacts.now(),
            "stages": {},
            "initial_sources": [s["id"] for s in sources],
            "status": "running",
            "validation": (
                "fixture plumbing only" if mode == "fixture" else "pending"
            ),
        }
    if execution.get("recovery") and not resume:
        manifest["stages"] = evidence_handoff.recover_stages(
            execution["recovery"], root, brief, store
        )
        manifest["validation"] = "Recovery from saved stages; new calls only"
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    runner = StageRunner(
        settings,
        provider,
        tools.EvidenceTools(store, settings, mode, ledger),
        ledger,
        campaign_attempt,
    )
    if replay_runner is not None:
        runner = replay_runner
        manifest["validation"] = (
            "Saved-output plumbing replay; no autonomous research "
            "or model validation"
        )
    manifest.update(
        execution_status="running",
        coverage_status="unassessed",
        review_status="not_started",
        export_status="not_started",
    )
    original_sources = _source_inputs(store, manifest["initial_sources"])
    base = {"brief": brief, "sources": original_sources}

    def stage(
        name: str,
        role: str,
        portable: dict,
        seconds: float,
        deadline: float | None = None,
        final_notes_only: bool = False,
    ) -> dict:
        if campaign_attempt:
            outer = (
                time.monotonic() + campaign_attempt["deadline"] - time.time()
            )
            deadline = min(
                deadline if deadline is not None else outer,
                outer,
            )
        if deadline is not None and time.monotonic() >= deadline:
            raise providers.ProviderError("Research phase deadline expired")
        checkpoint = (
            execution.get("continuation", {}).get("stages", {}).get(name)
        )
        if checkpoint:
            portable = {**portable, "continuation_checkpoint": checkpoint}
            final_notes_only = final_notes_only or checkpoint.get(
                "final_notes_only", False
            )
        old = manifest["stages"].get(name)
        if old and old.get("recovery_origin"):
            prior = artifacts.read(root / old["path"] / "input.json")[
                "portable"
            ]
            if name.startswith("research-") and any(
                prior.get(k) != portable.get(k)
                for k in ("brief", "task", "required_scope")
            ):
                raise ValueError("Recovered research scope changed")
            if name == "review" and prior.get(
                "review_inventory"
            ) != portable.get("review_inventory"):
                raise ValueError("Recovered review contract changed")
            return old
        if (
            old
            and resume
            and execution.get("continuation")
            and name.startswith("research-")
        ):
            saved = artifacts.read(root / old["path"] / "output.json")
            prior_input = artifacts.read(root / old["path"] / "input.json")[
                "portable"
            ]
            same_task = all(
                prior_input.get(key) == portable.get(key)
                for key in ("brief", "sources", "task", "required_scope")
            )
            if not same_task or artifacts.digest(saved) != old["output_hash"]:
                raise ValueError("Completed current-run research changed")
            return old
        completed_output = (
            execution.get("continuation", {})
            .get("completed_stage_hashes", {})
            .get(name)
        )
        if old and completed_output:
            saved = artifacts.read(root / old["path"] / "output.json")
            if artifacts.digest(saved) != completed_output or old[
                "input_hash"
            ] != artifacts.digest(portable):
                raise ValueError("Completed stage checkpoint changed")
            return old
        completed_review = execution.get("continuation", {}).get(
            "review_output_hash"
        )
        if name == "review" and old and completed_review:
            prior = artifacts.read(root / old["path"] / "input.json")[
                "portable"
            ]
            saved = artifacts.read(root / old["path"] / "output.json")
            if completed_review != artifacts.digest(saved) or any(
                prior.get(k) != portable.get(k)
                for k in (
                    "brief",
                    "draft",
                    "required_scope",
                    "review_inventory",
                    "settled_evidence",
                )
            ):
                raise ValueError("Completed review checkpoint changed")
            return old
        if old and old["input_hash"] == artifacts.digest(portable):
            saved = artifacts.read(root / old["path"] / "output.json")
            stored_input = artifacts.read(root / old["path"] / "input.json")
            prompts = pathlib.Path(__file__).parent / "prompts"
            instructions = (
                (prompts / "common.md").read_text()
                + "\n"
                + (prompts / f"{role}.md").read_text()
            )
            if (
                artifacts.digest(saved) == old["output_hash"]
                and stored_input["instructions"] == instructions
            ):
                return old
        stage_settings = settings
        if execution:
            rounds = (
                settings.review_rounds
                if role in ("review", "recheck")
                else (1 if final_notes_only else settings.tool_rounds)
            )
            if role == "plan" and execution.get("required_research_roles"):
                rounds = 1
            if name in ("followup", "review-followup"):
                rounds = min(rounds, 3)
            stage_settings = dataclasses.replace(settings, tool_rounds=rounds)
            if isinstance(runner, StageRunner):
                runner.settings = stage_settings
                runner.tools.settings = stage_settings
        if isinstance(ledger, budget.ExecutionLedger):
            ledger.stage = name
            ledger.research = role in ("company", "industry", "plan", "review")
            ledger.stage_calls = (
                settings.tool_rounds
                if checkpoint
                else stage_settings.tool_rounds
            )
            ledger.stage_seconds = (
                settings.company_provider_seconds
                if ledger.research
                else settings.command_provider_seconds
            )
            ledger.stage_tokens = (
                settings.company_observable_tokens
                if ledger.research
                else settings.command_observable_tokens
            )
        value = runner.run(
            name,
            role,
            portable,
            root,
            seconds=seconds,
            deadline=deadline,
            final_notes_only=final_notes_only,
        )
        return value

    def save(name: str, value: dict) -> None:
        manifest["stages"][name] = value
        artifacts.write(manifest_path, manifest)

    current = None
    review_status = "draft_review_incomplete"
    try:
        if resume and execution.get("continuation"):
            plan = manifest["stages"]["plan"]
            saved_plan = artifacts.read(root / plan["path"] / "output.json")
            if artifacts.digest(saved_plan) != plan["output_hash"]:
                raise ValueError("Completed planning checkpoint changed")
        elif execution.get("tasks"):
            plan = {
                "output": {
                    "content": "Explicit scoped tasks reused",
                    "tasks": execution["tasks"],
                },
                "status": "scoped_task_reuse",
                "input_hash": artifacts.digest(execution["tasks"]),
            }
        else:
            plan = stage(
                "plan",
                "plan",
                {
                    **base,
                    "planning_constraints": execution.get(
                        "planning_constraints", {}
                    ),
                    "reused_industry_scope": bool(
                        execution.get("industry_import")
                    ),
                    "instruction": (
                        "Plan scoped company work; do not duplicate "
                        "imported industry research."
                        if execution.get("industry_import")
                        else "Plan focused tasks from the brief."
                    ),
                },
                settings.stage_allocations[0],
            )
        save("plan", plan)
        tasks = plan["output"].get("tasks", [])
        if not isinstance(tasks, list) or len(tasks) > 12:
            raise ValueError("Plan tasks must be a short list")
        required_roles = execution.get("required_research_roles")
        if required_roles and sorted(
            t.get("role", "") for t in tasks
        ) != sorted(required_roles):
            raise ValueError("Plan exceeds admitted research role allocation")
        jobs = []
        for index, task in enumerate(tasks):
            if task.get("role") not in ("industry", "company") or not task.get(
                "question"
            ):
                raise ValueError(
                    "Only scoped industry/company research tasks are allowed"
                )
            if execution.get("industry_import") and task["role"] == "industry":
                raise ValueError(
                    "Plan duplicated explicitly imported industry scope"
                )
            jobs.append((f"research-{index}", task))
        research_seconds = settings.stage_allocations[1]
        if campaign_attempt:
            # Reserve writing, review/revision and export before research.
            research_seconds = min(
                research_seconds,
                campaign_attempt["deadline"]
                - time.time()
                - sum(settings.stage_allocations[2:])
                - settings.export_seconds,
            )
        research_deadline = min(
            time.monotonic() + max(0, research_seconds),
            execution.get("continuation", {}).get(
                "research_deadline", float("inf")
            ),
        )
        if isinstance(ledger, budget.ExecutionLedger):
            research_deadline = (
                time.monotonic() + campaign_attempt["deadline"] - time.time()
            )
        manifest["research_phase"] = {"seconds": max(0, research_seconds)}
        required_scope = execution.get("required_scope", [])
        imported = None
        if execution.get("industry_import"):
            imported = evidence_handoff.import_bundle(
                pathlib.Path(execution["industry_import"]), store
            )
            manifest["industry_import"] = imported["provenance"]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.workers
        ) as pool:
            futures = {
                pool.submit(
                    stage,
                    name,
                    task["role"],
                    {
                        **base,
                        "task": task,
                        "plan": plan["output"]["content"],
                        "required_scope": [
                            r
                            for r in required_scope
                            if (
                                r.get("role") == task["role"]
                                if "role" in r
                                else r.get("task", name) == name
                            )
                        ],
                    },
                    settings.stage_allocations[1],
                    research_deadline,
                ): name
                for name, task in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    save(name, future.result())
                except (
                    OSError,
                    ValueError,
                    RuntimeError,
                    KeyError,
                    TypeError,
                ) as exc:
                    if isinstance(exc, providers.ProviderCancelled):
                        raise
                    manifest.setdefault("research_gaps", {})[name] = str(exc)
                    if isinstance(exc, ResearchHandoffError):
                        manifest.setdefault("unsynthesized_evidence", {})[
                            name
                        ] = exc.handoff
        if settings.contextualize:
            for index, source in enumerate(
                store.sources()[: settings.context_documents]
            ):
                if (store.root / source["id"] / "context.json").exists():
                    continue
                text = store.open_source(source["id"])["text"][
                    : settings.context_characters
                ]
                context = stage(
                    f"context-{index}",
                    "context",
                    {"source": source, "text": text},
                    settings.stage_seconds,
                )
                save(f"context-{index}", context)
                store.add_context(
                    source["id"],
                    context["output"]["content"],
                    [
                        b["id"]
                        for b in source["blocks"]
                        if b["end"] <= len(text)
                    ],
                    dataclasses.asdict(settings.model("context")),
                    config.PROMPT_VERSION,
                )
        sources = _source_inputs(store, [s["id"] for s in store.sources()])
        research_records = {
            name: manifest["stages"][name]
            for name, _ in jobs
            if name in manifest["stages"]
        }
        assembled = evidence_handoff.collect(root, research_records, store)
        scope_output = {
            "scope": [
                item
                for record in research_records.values()
                for item in record["output"].get("scope", [])
            ]
        }
        initial_scope = evidence_handoff.scope(
            scope_output, required_scope, store
        )
        manifest["initial_coverage"] = initial_scope
        coverage = initial_scope
        recovered_draft = (
            manifest["stages"].get("synthesis", {}).get("recovery_origin")
        )
        if recovered_draft:
            manifest["pre_review_followup"] = (
                "Reused draft: preserve initial gaps for targeted review; "
                "do not restart completed research."
            )
        if (
            required_scope
            and initial_scope["status"] != "complete"
            and not recovered_draft
        ):
            gaps = [
                x for x in initial_scope["items"] if x["status"] != "supported"
            ]
            followup_input = {
                **base,
                **assembled,
                "task": {
                    "role": "company",
                    "question": (
                        "Resolve essential gaps using your own focused "
                        "searches and context opens. Preserve uncertainty "
                        "and prior useful findings."
                    ),
                },
                "required_scope": [
                    {"id": x["id"], "question": x["question"]} for x in gaps
                ],
                "initial_notes": {
                    name: r["output"]["content"]
                    for name, r in research_records.items()
                },
                "initial_gaps": gaps,
                "supplemental_findings": execution.get(
                    "supplemental_findings", []
                ),
                "supplemental_provenance": (
                    "Explicit prior source checks, not autonomous discoveries"
                ),
            }
            artifacts.write(
                root
                / execution.get(
                    "initial_coverage_file", "initial-coverage.json"
                ),
                initial_scope,
            )
            try:
                # Follow-up cannot consume protected downstream time.
                follow_deadline = None
                if campaign_attempt:
                    follow_deadline = (
                        time.monotonic()
                        + campaign_attempt["deadline"]
                        - time.time()
                        - sum(settings.stage_allocations[2:])
                        - settings.export_seconds
                    )
                if isinstance(ledger, budget.ExecutionLedger):
                    follow_deadline = None
                followup = stage(
                    "followup",
                    "company",
                    followup_input,
                    settings.followup_seconds,
                    follow_deadline,
                )
                save("followup", followup)
                previous_failure = manifest.get("research_gaps", {}).pop(
                    "followup", None
                )
                if previous_failure:
                    manifest.setdefault(
                        "recovered_execution_failures", []
                    ).append({"stage": "followup", "error": previous_failure})
                research_records["followup"] = followup
                follow_scope = evidence_handoff.scope(
                    followup["output"], followup_input["required_scope"], store
                )
                manifest["followup_coverage"] = follow_scope
                coverage = evidence_handoff.merge_scope(
                    initial_scope, follow_scope
                )
            except (
                OSError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
            ) as exc:
                if isinstance(exc, providers.ProviderCancelled):
                    raise
                manifest.setdefault("research_gaps", {})["followup"] = str(exc)
                if isinstance(exc, ResearchHandoffError):
                    manifest.setdefault("unsynthesized_evidence", {})[
                        "followup"
                    ] = exc.handoff
            assembled = evidence_handoff.collect(root, research_records, store)
        for failed in manifest.get("unsynthesized_evidence", {}).values():
            assembled["settled_evidence"] = evidence_handoff.merge(
                assembled["settled_evidence"],
                failed.get("settled_evidence", {}),
            )
        notes = {
            name: record["output"]["content"]
            for name, record in research_records.items()
        }
        if imported:
            notes["imported-industry"] = imported["notes"]
            assembled["settled_evidence"] = evidence_handoff.merge(
                assembled["settled_evidence"], imported["evidence"]
            )
            assembled["required_original_refs"] = sorted(
                set(
                    assembled["required_original_refs"]
                    + [
                        reading.reference(p)
                        for p in documents.ungroup_passages(
                            imported["evidence"]
                        )
                    ]
                )
            )
            assembled["imported_citation_map"] = imported["citation_map"]
        manifest["coverage"] = coverage
        manifest["coverage_status"] = coverage["status"]
        manifest["execution_status"] = (
            "partial" if manifest.get("research_gaps") else "running"
        )
        artifacts.write(
            root / execution.get("handoff_file", "research-handoff.json"),
            assembled,
        )
        synthesis_input = {
            "brief": brief,
            "sources": sources,
            "plan": plan["output"]["content"],
            "notes": notes,
            **assembled,
            "coverage": coverage,
            "gaps": manifest.get("research_gaps", {}),
            "review_requirements": required_scope if execution else [],
            "instruction": (
                "Write from originals, retaining explanations, units "
                "and technical qualifiers. Disclose unresolved essential "
                "coverage and payload omissions; notes alone are not evidence."
            ),
        }
        previous_synthesis = manifest["stages"].get("synthesis", {}).get("path")
        synthesis = stage(
            "synthesis",
            "synthesis",
            synthesis_input,
            settings.stage_allocations[2],
            final_notes_only=bool(execution),
        )
        save("synthesis", synthesis)
        synthesis_handoff = evidence_handoff.collect(
            root, {"synthesis": synthesis}, store
        )
        assembled["upstream_omissions"].update(
            synthesis_handoff["upstream_omissions"]
        )
        draft = reports / "draft.md"
        if not (
            resume
            and draft.exists()
            and previous_synthesis == synthesis["path"]
        ):
            draft = _prepare_report(
                synthesis["output"],
                reports,
                store,
                "draft.md",
                settings.information_cutoff,
            )
        current = draft

        # Independent reviewer sees brief, exact draft/figures and
        # originals only.
        def review_input(path: pathlib.Path) -> dict:
            return {
                "brief": brief,
                "draft": path.read_text(),
                "review_mode": True,
                "information_cutoff": settings.information_cutoff,
                "web_verification_enabled": settings.web_verification,
                "questions": required_scope
                or [
                    {"id": key, "question": key}
                    for key in review_contract.CRITERIA
                ],
                "recovered_followup_notes": notes.get("followup"),
                "review_followup_notes": notes.get("review-followup"),
                "review_followup_coverage": (
                    manifest.get("review_followup_coverage")
                    if "review-followup" in notes
                    else None
                ),
                "coverage": {
                    **coverage,
                    "items": [
                        {k: v for k, v in x.items() if k != "original_passages"}
                        for x in coverage["items"]
                        if x["status"] != "supported"
                    ],
                    "scope_note": (
                        "Open gaps only; originals for all claims "
                        "remain supplied"
                    ),
                },
                "supplemental_findings": execution.get(
                    "supplemental_findings", []
                ),
                "settled_evidence": assembled["settled_evidence"],
                "upstream_omissions": assembled["upstream_omissions"],
                "required_original_refs": assembled["required_original_refs"],
                "required_scope": [],
                "sources": _source_inputs(
                    store, [s["id"] for s in store.sources()]
                ),
                "source_map": artifacts.read(reports / "source-map.json"),
                "figures": artifacts.read(reports / "figures.json"),
                "visual_review_capability": (
                    "Text, figure specifications and hashes only; no native "
                    "pixels supplied. Layout/readability require rendered "
                    "visual inspection outside this reviewer."
                ),
                "asset_hashes": {
                    figure[key]: artifacts.digest(
                        artifacts.contained(reports, figure[key]).read_bytes()
                    )
                    for figure in artifacts.read(reports / "figures.json")
                    for key in ("path", "input", "code")
                },
            }

        review = stage(
            "review",
            "review",
            review_input(current),
            settings.stage_allocations[3],
        )
        save("review", review)
        examined = review_contract.assess(review["output"], store)
        manifest["review_scope"] = examined
        manifest["review_status"] = examined["status"]
        manifest["readiness"] = examined["decision"]
        manifest["factual_status"] = "targeted_checks_only"
        supplemental = execution.get("supplemental_findings", [])
        if supplemental:
            parse_output(
                json.dumps(
                    {
                        "content": "Supplemental source check",
                        "issues": supplemental,
                    }
                ),
                "review",
            )
        support = evidence_handoff.validate_quotes(
            review["output"]["issues"]
            + supplemental
            + review["output"].get("scope", []),
            store,
        )
        reviewed_originals = evidence_handoff.collect(
            root, {"review": review}, store
        )
        evidence_handoff.require_support(assembled, support)
        evidence_handoff.require_support(
            assembled,
            reviewed_originals["settled_evidence"],
            [],
        )
        material = [
            i
            for i in review_contract.findings(
                review["output"]["issues"], supplemental
            )
            if i["severity"] == "material"
        ]
        if (
            not material
            and examined["status"] == "complete"
            and examined["decision"] == "needs revision"
        ):
            # A substantive negative rubric still drives one revision when
            # the reviewer omitted its actionable issue list. No new verdict.
            material = [
                {
                    "severity": "material",
                    "kind": "explanation",
                    "location": "Report against the user brief",
                    "evidence": json.dumps(
                        examined["rubric"], ensure_ascii=False
                    ),
                    "impact": "Reviewer judged the report not ready "
                    "for its user.",
                    "suggestion": "Address the stated rubric deficiencies; "
                    "preserve evidence and disclose unresolved gaps.",
                    "original_passages": [],
                    "origins": ["rubric_routing"],
                }
            ]
        material = review_contract.route(material)
        if material:
            manifest["readiness"] = "needs revision"
        manifest["initial_review_issues"] = material
        manifest["unresolved_issues"] = material
        manifest["supplemental_findings"] = supplemental
        research_issues = [x for x in material if x["action"] == "research"]
        if research_issues:
            # One shared post-review investigation, never a research restart.
            gap_input = {
                **base,
                **assembled,
                "sources": _source_inputs(
                    store, [s["id"] for s in store.sources()]
                ),
                "information_cutoff": settings.information_cutoff,
                "task": {
                    "role": "company",
                    "question": "Investigate only these essential review gaps. "
                    "Use the authorized corpus; preserve original support "
                    "and scope unresolved results accurately.",
                },
                "questions": [
                    {"id": x["id"], "question": x["suggestion"]}
                    for x in research_issues
                ],
                "required_scope": [
                    {"id": x["id"], "question": x["suggestion"]}
                    for x in research_issues
                ],
                "review_gaps": research_issues,
                "draft": current.read_text(),
            }
            try:
                recovery = stage(
                    "review-followup",
                    "company",
                    gap_input,
                    settings.followup_seconds,
                )
                save("review-followup", recovery)
                recovered = evidence_handoff.collect(
                    root, {"review-followup": recovery}, store
                )
                evidence_handoff.require_support(
                    assembled,
                    recovered["settled_evidence"],
                    recovered["required_original_refs"],
                )
                assembled["upstream_omissions"].update(
                    recovered["upstream_omissions"]
                )
                notes["review-followup"] = recovery["output"]["content"]
                manifest["review_followup_coverage"] = evidence_handoff.scope(
                    recovery["output"], gap_input["required_scope"], store
                )
            except (
                OSError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
            ) as exc:
                if isinstance(exc, providers.ProviderCancelled):
                    raise
                manifest["review_followup_error"] = str(exc)
                notes["review-followup"] = "Focused research failed: " + str(
                    exc
                )
                if isinstance(exc, ResearchHandoffError):
                    evidence_handoff.require_support(
                        assembled, exc.handoff.get("settled_evidence", {})
                    )
        if material:
            revision_portable = revision_input(
                review_input(current), {**review["output"], "issues": material}
            )
            revision = stage(
                "revision",
                "revision",
                revision_portable,
                settings.stage_allocations[4],
                final_notes_only=bool(execution),
            )
            save("revision", revision)
            current = _prepare_report(
                revision["output"],
                reports,
                store,
                "revised.md",
                settings.information_cutoff,
            )
            recheck = stage(
                "recheck",
                "recheck",
                {
                    **review_followup_input(review_input(current)),
                    "prior_issues": material,
                    "initial_review_assessment": examined,
                    "required_scope": [],
                },
                settings.stage_allocations[5],
            )
            save("recheck", recheck)
            rechecked = review_contract.assess(recheck["output"], store)
            manifest["recheck_scope"] = rechecked
            material = review_contract.unresolved(material, recheck["output"])
            manifest["revision_resolution"] = (
                "complete"
                if not material and rechecked["status"] == "complete"
                else "unverified_or_unresolved"
            )
            manifest["readiness"] = (
                "needs revision" if material else rechecked["decision"]
            )
        review_status = (
            "reviewed"
            if manifest["readiness"] == "ready"
            else "reviewed_with_limitations"
        )
        if manifest["execution_status"] == "running":
            manifest["execution_status"] = "complete"
        manifest["unresolved_issues"] = material
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        manifest["execution_status"] = "failed"
        manifest["readiness"] = "needs revision"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if current is None and (reports / "draft.md").exists():
            current = reports / "draft.md"
    finally:
        manifest["status"] = review_status
        manifest["completed"] = artifacts.now()
        if current:
            final = reports / "report.md"
            artifacts.write(final, current.read_bytes())
            manifest["reviewed_subset_hash"] = (
                artifacts.digest(current.read_bytes())
                if manifest.get("review_scope")
                else None
            )
            manifest["reviewed_hash"] = (
                artifacts.digest(current.read_bytes())
                if review_status == "reviewed"
                else None
            )
            manifest["report_hash"] = artifacts.digest(final.read_bytes())
            try:
                if manifest.get("error", {}).get(
                    "type"
                ) == "ProviderCancelled" or (
                    campaign_attempt
                    and time.time() >= campaign_attempt["deadline"]
                ):
                    raise providers.ProviderCancelled(
                        "Export cancelled by enclosing deadline"
                    )
                manifest["render"] = render.export(final)
            except (OSError, ValueError, RuntimeError) as exc:
                manifest["render"] = {
                    "pdf_status": "pending",
                    "error": str(exc),
                    "markdown": str(final),
                }
        manifest["export_status"] = manifest.get("render", {}).get(
            "pdf_status", "not_started"
        )
        providers.cancel_all()
        artifacts.write(manifest_path, manifest)
    return manifest


def replay_stage(
    input_path: pathlib.Path,
    output_root: pathlib.Path,
    settings: config.Settings,
    provider: providers.Provider,
    store: documents.SourceStore,
    mode: str = "fixture",
    ledger: budget.Ledger | None = None,
    attempt: dict | None = None,
) -> dict:
    """Fork a recorded stage into a new directory."""
    record = artifacts.read(input_path)
    output_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(store.root, output_root / "sources")
    frozen = documents.SourceStore(
        output_root / "sources", settings.chunk_characters
    )
    runner = StageRunner(
        settings,
        provider,
        tools.EvidenceTools(frozen, settings, mode, ledger),
        ledger,
        attempt,
    )
    result = runner.run(
        record["stage"],
        record["role"],
        record["portable"],
        output_root,
        rehearsal=mode != "fixture",
    )
    artifacts.write(
        output_root / "replay.json",
        {"parent": str(input_path), "mode": mode, "result": result},
    )
    return result
