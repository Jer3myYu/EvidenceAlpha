"""Run the industry research workflow on a question, or resume a thread.

Usage::

    set -a; source .env; set +a
    .venv/bin/python scripts/industry_workflow.py "光掩模产业调研"
    .venv/bin/python scripts/industry_workflow.py --resume 3f9c2a1b
    .venv/bin/python scripts/industry_workflow.py --backup backup.db
    .venv/bin/python scripts/industry_workflow.py "q" --limit wall_clock_s=3600
    .venv/bin/python scripts/industry_workflow.py "q" --fixture tmp/.../fixture

Every run is checkpointed to ``data/workflow.db`` under a thread id,
printed first. An interrupted run resumes with ``--resume`` at the
node that did not finish; a Phase 6-9 thread cannot be resumed here
(replay it in Studio). The report is written to
``data/reports/<thread_id>.md``, with a formatted copy alongside it at
``data/reports/<thread_id>.pdf``; the trace shows every node, task, and
the budget as the run goes.
"""

import argparse
import asyncio
import sys
import tempfile

from industry import budget
from industry import graph as graph_module
from industry import pdf as pdf_module
from industry import records
from industry import snapshots
from industry import state as state_module
from industry import tools
from industry import trace
from research import persist
from research import web

_LEVEL_TEXT = {
    "verified": "verified report",
    "partial": "PARTIAL REPORT, NOT FULLY VERIFIED",
    "diagnostic_only": "DIAGNOSTICS ONLY, BODY WITHHELD",
}


def parse_args() -> argparse.Namespace:
    """A question, ``--resume``, or ``--backup``; optional limit overrides."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", maxsplit=1)[0]
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("question", nargs="?", help="start a new thread")
    target.add_argument("--resume", metavar="THREAD_ID", help="resume a thread")
    target.add_argument(
        "--backup", metavar="PATH", help="copy the checkpoint database"
    )
    parser.add_argument(
        "--fixture",
        metavar="DIR",
        help="fixed evidence: search and fetch only the pages recorded in "
        "DIR/sources.json (a temporary index; no network)",
    )
    parser.add_argument(
        "--route",
        choices=("C", "S"),
        default="C",
        help="workflow route: C the corrected existing one (default), "
        "S the simplified candidate (plan D-U16). Routing only; both "
        "share the registry, budget, review and delivery gate",
    )
    parser.add_argument(
        "--limit",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override one limit, e.g. wall_clock_s=3600 (repeatable)",
    )
    return parser.parse_args()


def limits_from(overrides: list[str]) -> records.Limits:
    """Apply ``NAME=VALUE`` overrides to the default limits."""
    values = {}
    defaults = records.Limits()
    for item in overrides:
        name, _, raw = item.partition("=")
        if not hasattr(defaults, name):
            sys.exit(f"Unknown limit {name!r}.")
        kind = type(getattr(defaults, name))
        try:
            values[name] = kind(raw)
        except ValueError:
            sys.exit(f"Limit {name} needs a {kind.__name__}, not {raw!r}.")
    try:
        return records.Limits(**values)
    except ValueError as error:
        sys.exit(f"Invalid limits: {error}")


def require_live_key() -> None:
    """Stop before any run that would need the live web API without a key."""
    try:
        web.api_key()
    except RuntimeError as error:
        sys.exit(str(error))


def check_fixture(
    meta: records.RunMeta, backend: tools.FixtureBackend
) -> str | None:
    """The reason a resumed fixture run may not continue, or ``None``.

    The thread recorded the fixture's digest (every served page and its
    bytes); a resume must rebuild exactly that evidence.
    """
    if meta.fixture_digest and meta.fixture_digest != backend.digest:
        return (
            f"Fixture {meta.fixture} has changed since this thread was "
            f"recorded (digest {backend.digest[:12]} != "
            f"{meta.fixture_digest[:12]}); a resume keeps its evidence."
        )
    return None


def fixture_backend(directory: str) -> tools.FixtureBackend:
    """The fixed-evidence backend over a temporary index and store."""
    scratch = tempfile.mkdtemp(prefix="fixture-run-")
    backend = tools.FixtureBackend(
        directory,
        snapshots.vector_store(f"{scratch}/chroma"),
        f"{scratch}/sources",
    )
    print(f"FIXTURE: {len(backend.pages)} pages from {directory}")
    return backend


def show(title: str, body: str) -> None:
    """Print one stage with a rule under its title."""
    rule = "-" * len(title)
    print(f"\n{title}\n{rule}\n{body}")


async def stream(graph, payload, config, runtime) -> state_module.IndustryState:
    """Stream the graph, print trace lines, return the final state."""
    state: state_module.IndustryState = {}
    thread_id = config["configurable"]["thread_id"]
    try:
        async for mode, chunk in graph.astream(
            payload,
            config,
            stream_mode=["updates", "values"],
            durability="sync",
        ):
            if mode == "values":
                state = chunk
                continue
            for node, update in chunk.items():
                for line in trace.render_update(node, update or {}, state):
                    print(line)
                if node in ("merge", "deliver"):
                    print(
                        trace.budget_line(
                            {**state, **(update or {})}, runtime.limits
                        )
                    )
    except asyncio.CancelledError:
        print(
            "\nInterrupted. The last completed node is saved; continue with:"
            f"\n  scripts/industry_workflow.py --resume {thread_id}"
        )
        raise
    return state


async def main() -> None:
    """Start, resume, or back up."""
    args = parse_args()
    if args.backup:
        persist.backup(persist.DB_PATH, args.backup)
        print(f"Backed up {persist.DB_PATH} to {args.backup}")
        return
    if args.resume is None and not args.fixture:
        require_live_key()
    runtime = budget.Runtime(limits_from(args.limit), route=args.route)
    backend = fixture_backend(args.fixture) if args.fixture else None
    async with persist.open_checkpointer() as checkpointer:
        graph = graph_module.build_graph(
            runtime, backend=backend, checkpointer=checkpointer
        )
        if args.resume is None:
            thread_id = persist.new_thread_id()
            show(
                "THREAD", f"{thread_id}  (--resume {thread_id} if interrupted)"
            )
            show("QUESTION", args.question)
            config = persist.thread_config(thread_id)
            payload = graph_module.initial_state(
                args.question,
                runtime.limits,
                fixture=args.fixture,
                fixture_digest=backend.digest if backend else None,
                route=args.route,
            )
        else:
            if args.limit:
                sys.exit(
                    "--limit applies to new runs; a resume keeps the "
                    "limits recorded in the thread."
                )
            thread_id = args.resume
            try:
                snapshot = await persist.load_industry_state(
                    graph, thread_id, state_module.WORKFLOW_VERSION
                )
            except LookupError as error:
                sys.exit(str(error))
            meta = snapshot.values["meta"]
            if args.fixture and args.fixture != meta.fixture:
                sys.exit(
                    f"This thread was recorded with fixture {meta.fixture!r}; "
                    "a resume keeps it."
                )
            # A resume keeps the route it was recorded with.
            runtime = budget.Runtime(meta.limits, route=meta.route)
            if meta.fixture:
                backend = fixture_backend(meta.fixture)
                problem = check_fixture(meta, backend)
                if problem:
                    sys.exit(problem)
            else:
                backend = None
                require_live_key()
            graph = graph_module.build_graph(
                runtime, backend=backend, checkpointer=checkpointer
            )
            show("THREAD", thread_id)
            show("QUESTION", snapshot.values["question"])
            if not snapshot.next:
                meta = snapshot.values["meta"]
                show(
                    "STATUS",
                    f"completed earlier: {meta.report_status}; report "
                    f"{meta.report_path}",
                )
                return
            pending = snapshot.next[0]
            config = persist.resume_config(thread_id, snapshot)
            if pending in state_module.SINGLE_CALL_NODES:
                updates = graph_module.resume_updates(
                    snapshot.values, pending, runtime.limits
                )
                await graph.aupdate_state(
                    config, updates, as_node=f"reserve_{pending}"
                )
                for line in updates["route_log"]:
                    print(f"RESUME: {line}")
            else:
                print(f"RESUMING AT: {pending}")
            payload = None
        runtime.begin(thread_id)
        show("TRACE", "")
        state = await stream(graph, payload, config, runtime)
    meta = state["meta"]
    delivery = state.get("delivery")
    if delivery is not None:
        # The classification and its reason stand before the path: the
        # status word alone cannot tell a useful partial report from a
        # withheld one -- both are `incomplete`.
        lines = [f"{_LEVEL_TEXT[delivery.level]} ({delivery.status})"]
        lines.append(delivery.reason + ".")
        if delivery.removed:
            lines.append("not included: " + ", ".join(delivery.removed))
        if delivery.floor:
            lines.append(delivery.floor + ".")
        lines.append(str(meta.report_path))
        rendered = pdf_module.pdf_beside(meta.report_path)
        if rendered:
            lines.append(rendered)
        show("REPORT", "\n".join(lines))
    else:
        show("REPORT", f"{meta.report_status}: {meta.report_path}")
    show(
        "COVERAGE",
        "\n".join(
            f"Q{c.question}: {c.status}  {c.note}" for c in state["coverage"]
        ),
    )
    open_issues = [i for i in state["issues"].values() if i.status == "open"]
    show(
        "OPEN ISSUES",
        "\n".join(
            f"[{i.id}] {i.severity} {i.category} on {i.target}: {i.description}"
            for i in open_issues
        )
        or "none",
    )
    show("BUDGET", trace.budget_line(state, runtime.limits))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
