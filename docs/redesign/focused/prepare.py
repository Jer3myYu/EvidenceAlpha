"""Freeze the authorized saved-stage diagnostic without invoking a model."""

import dataclasses
import importlib.metadata
import json
import pathlib
import shutil
import subprocess
import sys

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import documents

ROOT = pathlib.Path(__file__).resolve().parents[3]
DESTINATION = ROOT / "data/redesign/focused-diagnostic/frozen"
RUN = ROOT / "data/redesign/runs/57bd6a8282dd494db15e13394ba3c4fc"
CASES = {
    "A": ("company", "research-1/b8d6a606cbfd"),
    "B": ("review", "review/7f3fb0629188"),
    "C": ("revision", "revision/1161e229dee3"),
}
# Identity annotations quote document headers, not each passage's subject.
IDENTITIES = {
    "134a14ccbea168ac6f9bc869c15926134dd42da74dbcab0aeb7e50679f4f7e08": (
        "c28",
        "深圳清溢光电股份有限公司投资者关系活动记录表",
        "c28",
        "深圳清溢光电股份有限公司",
    ),
    "25ae4a74a2feddac299bfb1fd84c1872b309c51fe0519c755498a3e6a960596b": (
        "c0",
        "深圳市龙图光罩股份有限公司2025 年年度报告摘要",
        "c0",
        "深圳市龙图光罩股份有限公司",
    ),
    "8e233a86876dd1b01b6611dc56bc9d91f14106f40fdc57f61aa5e0196a515ffd": (
        "c1",
        "Photronics Reports Full Year and Fourth Quarter Fiscal 2025 Results",
        "c2",
        "Photronics, Inc.",
    ),
    "b81b85f11d30d9cebd91041d76ffe71f7bdd3dcf4290b98213152aa28b272bf7": (
        "c0",
        "深圳清溢光电股份有限公司2025 年年度报告",
        "c0",
        "深圳清溢光电股份有限公司",
    ),
    "fbbfaa667b9e5166472aa329bf48aa53890d3d43c9b1d54958fe8fe9faf6f394": (
        "c1",
        "2025年度“提质增效重回报”行动方案评估报告",
        "c0",
        "深圳市路维光电股份有限公司",
    ),
}


def main() -> None:
    """Copy and hash code, prompts, corpus, exact draft/assets and inputs."""
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise RuntimeError("Commit candidate before freezing")
    DESTINATION.mkdir(parents=True, exist_ok=False)
    shutil.copytree(
        ROOT / "src",
        DESTINATION / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    shutil.copytree(
        ROOT / "data/redesign/stage2-real-corpus", DESTINATION / "corpus"
    )
    shutil.copytree(
        ROOT / "docs/redesign/focused",
        DESTINATION / "diagnostic",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(RUN / "reports", DESTINATION / "preserved-reports")
    shutil.copy2(ROOT / "pyproject.toml", DESTINATION / "pyproject.toml")
    store = documents.SourceStore(DESTINATION / "corpus")
    sources = []
    for source_id, (
        title_chunk,
        title,
        issuer_chunk,
        issuer,
    ) in IDENTITIES.items():
        artifacts.write(
            store.root / source_id / "identity.json",
            {
                "title": {"value": title, "chunk_id": title_chunk},
                "issuer": {"value": issuer, "chunk_id": issuer_chunk},
            },
        )
        sources.append(store.source_context(source_id))
    for case, (role, stage) in CASES.items():
        original = artifacts.read(RUN / "stages" / stage / "input.json")
        portable = original["portable"]
        portable["sources"] = sources
        portable["brief"]["execution_guidance"] = (
            "Isolated diagnostic using only the frozen saved originals; no "
            "external acquisition. Preserve the user's research requirements. "
            "Use exact source_id filters and source locators. Return compact "
            "complete stage output; target <=2500 tokens for company/review "
            "and <=7000 for revision. Unknowns remain unknown."
        )
        removed = []
        if role == "revision":
            for key in ("plan", "notes", "gaps", "unsynthesized_evidence"):
                if key in portable:
                    removed.append(key)
                    del portable[key]
        artifacts.write(
            DESTINATION / "cases" / f"{case}.json",
            {
                "stage": role,
                "role": role,
                "portable": portable,
                "seconds": config.DIAGNOSTIC_CASE_SECONDS[case],
                "parent_input": str(RUN / "stages" / stage / "input.json"),
                "parent_hash": artifacts.digest(
                    (RUN / "stages" / stage / "input.json").read_bytes()
                ),
                "removed_fields": removed,
            },
        )
    settings = dataclasses.asdict(
        config.Settings(workers=1, rehearsal_model=config.RUNTIME_MODEL)
    )
    settings.update(
        ledger="external additive ledger only", search_env_file=None
    )
    artifacts.write(DESTINATION / "settings.json", settings)
    artifacts.write(
        DESTINATION / "environment.json",
        {
            "code_commit": artifacts.revision(),
            "python": sys.version,
            "codex_version": subprocess.check_output(
                ["codex", "--version"], text=True
            ).strip(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "pymupdf",
                    "requests",
                    "claude-agent-sdk",
                    "pytest",
                    "black",
                    "pylint",
                )
            },
            "runtime_limit": "Remote model routing is not frozen",
        },
    )
    hashes = {
        str(p.relative_to(DESTINATION)): artifacts.digest(p.read_bytes())
        for p in sorted(DESTINATION.rglob("*"))
        if p.is_file()
    }
    artifacts.write(DESTINATION / "manifest.json", hashes)
    for path in DESTINATION.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
        elif path.is_dir():
            path.chmod(0o555)
    DESTINATION.chmod(0o555)
    artifacts.write(
        DESTINATION.parent / "freeze.json",
        {
            "snapshot": str(DESTINATION),
            "files": len(hashes),
            "manifest_hash": artifacts.digest(
                (DESTINATION / "manifest.json").read_bytes()
            ),
            "code_commit": artifacts.revision(),
            "prepared": artifacts.now(),
        },
    )
    print(json.dumps({"frozen": str(DESTINATION), "files": len(hashes)}))


if __name__ == "__main__":
    main()
