"""One bounded research workflow with portable stage inputs and replay."""

import concurrent.futures
import dataclasses
import json
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
from evidencealpha import providers
from evidencealpha import render
from evidencealpha import tools


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
    ) -> dict:
        """Record a new attempt."""
        folder = root / "stages" / stage / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True)
        prompt_path = pathlib.Path(__file__).parent / "prompts"
        instructions = (
            (prompt_path / "common.md").read_text()
            + "\n"
            + (prompt_path / f"{role}.md").read_text()
        )
        settings = self.settings.model(role, rehearsal)
        if self.ledger and artifacts.read(self.ledger.path)["claude_disabled"]:
            settings = config.ModelSettings("codex", config.RUNTIME_MODEL)
        record = {
            "stage": stage,
            "role": role,
            "portable": portable,
            "instructions": instructions,
            "tools": self.tools.definitions(),
            "settings": dataclasses.asdict(settings),
            "prompt_version": config.PROMPT_VERSION,
            "mode": self.tools.mode,
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
        messages = [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(portable, ensure_ascii=False),
            },
        ]
        deadline = min(
            deadline if deadline is not None else float("inf"),
            time.monotonic() + record["seconds"],
        )
        event_path = folder / "events.jsonl"
        status = "failed"
        try:
            for turn in range(self.settings.tool_rounds):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise providers.ProviderError("Stage deadline expired")
                call_dir = folder / f"call-{turn}"
                final_turn = turn == self.settings.tool_rounds - 1
                available_tools = {} if final_turn else record["tools"]
                prompt = json.dumps(
                    {
                        "messages": messages,
                        "tools": available_tools,
                        "remaining_calls": self.settings.tool_rounds - turn,
                        "turn_instruction": (
                            "Final call: return your completed stage output "
                            "from gathered evidence, with explicit gaps. "
                            "Do not request tools."
                            if final_turn
                            else "Gather evidence efficiently; reserve the "
                            "last call for completed stage output."
                        ),
                    },
                    ensure_ascii=False,
                )
                reservation = None
                if self.ledger:
                    reservation = self.ledger.reserve(
                        self.campaign_attempt, settings.provider, remaining
                    )
                    remaining = reservation["reserved_seconds"]
                request = providers.Request(
                    stage,
                    prompt,
                    settings,
                    call_dir.resolve(),
                    remaining,
                    deadline,
                    tuple(available_tools),
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
                    result = provider.run(request)
                    usage = result.usage
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
                messages.append({"role": "assistant", "content": result.text})
                if not output.get("tool_calls"):
                    status = "complete"
                    artifacts.write(folder / "output.json", output)
                    artifacts.write(folder / "output.md", output["content"])
                    return {
                        "path": str(folder.relative_to(root)),
                        "input_hash": artifacts.digest(portable),
                        "output_hash": artifacts.digest(output),
                        "output": output,
                    }
                for call in output["tool_calls"]:
                    if time.monotonic() >= deadline:
                        raise providers.ProviderError("Stage deadline expired")
                    source_versions = {
                        s["id"]: s["hash"] for s in self.tools.store.sources()
                    }
                    tool_started = time.monotonic()
                    try:
                        value = self.tools.call(
                            call["name"], call["arguments"], deadline=deadline
                        )
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
                    messages.append(
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"tool": call["name"], "result": value},
                                ensure_ascii=False,
                            ),
                        }
                    )
            raise providers.ProviderError(
                "Tool-round limit reached; no final output"
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            artifacts.event(
                event_path,
                "error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise
        finally:
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
    return value


def _source_inputs(store: documents.SourceStore, ids: list[str]) -> list[dict]:
    result = []
    for source_id in ids:
        item = store.open_source(source_id)
        source = item["source"]
        result.append(
            {
                "source_id": source_id,
                "hash": source["hash"],
                "text_hash": source["text_hash"],
                "url": source["url"],
                "chunk_count": len(source["chunks"]),
                "identifying_passage": (
                    store.open_source(source_id, source["chunks"][0]["id"])
                    if source["chunks"]
                    else None
                ),
                "warnings": source["warnings"],
            }
        )
    return result


def _prepare_report(
    output: dict, reports: pathlib.Path, store: documents.SourceStore, name: str
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
    for index, figure in enumerate(manifest, 1):
        caption = (
            f'\n图 {index}：{figure["caption"]} '
            f'({figure["period"]}; {figure["unit"]})。'
            f'{figure["caveats"]}\n'
        )
        caption += "来源：" + ", ".join(figure["source_ids"]) + "\n"
        pattern = r"(!\[[^\]]*\]\(" + re.escape(figure["path"]) + r"\))"
        body, count = re.subn(
            pattern,
            lambda match, caption=caption: match[0] + "\n" + caption,
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
) -> dict:
    """Run one plan/research/write/review/revise/recheck path."""
    if mode not in ("fixture", "fixed-corpus", "live"):
        raise ValueError("Unknown run mode")
    if not isinstance(provider, providers.FixtureProvider) and not ledger:
        raise ValueError("Model runs require an admitted campaign attempt")
    root.mkdir(parents=True, exist_ok=resume)
    manifest_path = root / "manifest.json"
    store = documents.SourceStore(root / "sources", settings.chunk_characters)
    if resume:
        manifest = artifacts.read(manifest_path)
        brief = manifest["brief"]
        if manifest["settings"] != json.loads(
            json.dumps(dataclasses.asdict(settings))
        ):
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
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    runner = StageRunner(
        settings,
        provider,
        tools.EvidenceTools(store, settings, mode, ledger),
        ledger,
        campaign_attempt,
    )
    original_sources = _source_inputs(store, manifest["initial_sources"])
    base = {"brief": brief, "sources": original_sources}

    def stage(
        name: str,
        role: str,
        portable: dict,
        seconds: float,
        deadline: float | None = None,
    ) -> dict:
        if deadline is not None and time.monotonic() >= deadline:
            raise providers.ProviderError("Research phase deadline expired")
        old = manifest["stages"].get(name)
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
        value = runner.run(
            name, role, portable, root, seconds=seconds, deadline=deadline
        )
        return value

    def save(name: str, value: dict) -> None:
        manifest["stages"][name] = value
        artifacts.write(manifest_path, manifest)

    current = None
    review_status = "draft_review_incomplete"
    try:
        plan = stage("plan", "plan", base, settings.stage_allocations[0])
        save("plan", plan)
        tasks = plan["output"].get("tasks", [])
        if not isinstance(tasks, list) or len(tasks) > 12:
            raise ValueError("Plan tasks must be a short list")
        jobs = []
        for index, task in enumerate(tasks):
            if task.get("role") not in ("industry", "company") or not task.get(
                "question"
            ):
                raise ValueError(
                    "Only scoped industry/company research tasks are allowed"
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
        research_deadline = time.monotonic() + max(0, research_seconds)
        manifest["research_phase"] = {"seconds": max(0, research_seconds)}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.workers
        ) as pool:
            futures = {
                pool.submit(
                    stage,
                    name,
                    task["role"],
                    {**base, "task": task, "plan": plan["output"]["content"]},
                    settings.stage_allocations[1],
                    research_deadline,
                ): name
                for name, task in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    save(name, future.result())
                except (OSError, ValueError, RuntimeError, KeyError) as exc:
                    manifest.setdefault("research_gaps", {})[name] = str(exc)
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
        synthesis_input = {
            "brief": brief,
            "sources": sources,
            "plan": plan["output"]["content"],
            "notes": {
                name: manifest["stages"][name]["output"]["content"]
                for name, _ in jobs
                if name in manifest["stages"]
            },
            "gaps": manifest.get("research_gaps", {}),
        }
        previous_synthesis = manifest["stages"].get("synthesis", {}).get("path")
        synthesis = stage(
            "synthesis",
            "synthesis",
            synthesis_input,
            settings.stage_allocations[2],
        )
        save("synthesis", synthesis)
        draft = reports / "draft.md"
        if not (
            resume
            and draft.exists()
            and previous_synthesis == synthesis["path"]
        ):
            draft = _prepare_report(
                synthesis["output"], reports, store, "draft.md"
            )
        current = draft

        # Independent reviewer sees brief, exact draft/figures and
        # originals only.
        def review_input(path: pathlib.Path) -> dict:
            return {
                "brief": brief,
                "draft": path.read_text(),
                "sources": sources,
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
        material = [
            i for i in review["output"]["issues"] if i["severity"] == "material"
        ]
        if material:
            revision_input = {
                **synthesis_input,
                **review_input(current),
                "findings": review["output"],
                "instruction": (
                    "Correct material issues or contest with evidence; "
                    "disclose unresolved conclusions."
                ),
            }
            revision = stage(
                "revision",
                "revision",
                revision_input,
                settings.stage_allocations[4],
            )
            save("revision", revision)
            current = _prepare_report(
                revision["output"], reports, store, "revised.md"
            )
            recheck = stage(
                "recheck",
                "recheck",
                {**review_input(current), "prior_issues": material},
                settings.stage_allocations[5],
            )
            save("recheck", recheck)
            material = [
                i
                for i in recheck["output"]["issues"]
                if i["severity"] == "material"
            ]
        review_status = "reviewed_with_limitations" if material else "reviewed"
        manifest["unresolved_issues"] = material
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if current is None and (reports / "draft.md").exists():
            current = reports / "draft.md"
    finally:
        manifest["status"] = review_status
        manifest["completed"] = artifacts.now()
        if current:
            final = reports / "report.md"
            artifacts.write(final, current.read_bytes())
            manifest["reviewed_hash"] = (
                artifacts.digest(current.read_bytes())
                if review_status != "draft_review_incomplete"
                else None
            )
            manifest["report_hash"] = artifacts.digest(final.read_bytes())
            try:
                manifest["render"] = render.export(final)
            except (OSError, ValueError, RuntimeError) as exc:
                manifest["render"] = {
                    "pdf_status": "pending",
                    "error": str(exc),
                    "markdown": str(final),
                }
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
