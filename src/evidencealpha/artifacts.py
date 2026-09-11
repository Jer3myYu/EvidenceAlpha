"""Atomic portable artifacts, fingerprints and exact tool trace replay."""

import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any


def now() -> str:
    """Return an aware UTC timestamp."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value: Any) -> str:
    """Hash bytes or a canonical JSON value."""
    data = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    )
    return hashlib.sha256(data).hexdigest()


def write(path: pathlib.Path, value: Any) -> None:
    """Atomically write JSON, UTF-8 text, or bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(value, (str, bytes)):
        value = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    data = value.encode() if isinstance(value, str) else value
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read(path: pathlib.Path) -> Any:
    """Read a JSON artifact."""
    return json.loads(path.read_text(encoding="utf-8"))


def event(path: pathlib.Path, kind: str, **fields: Any) -> None:
    """Append one observable event; callers own distinct event files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"time": now(), "kind": kind, **fields}, ensure_ascii=False
            )
            + "\n"
        )


def contained(root: pathlib.Path, name: str) -> pathlib.Path:
    """Resolve an artifact path, refusing escapes and symlink escapes."""
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes its workspace")
    return result


def tree_hash(root: pathlib.Path) -> dict[str, str]:
    """Fingerprint regular files for stage-level dependency tracking."""
    return {
        str(p.relative_to(root)): digest(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def revision() -> dict:
    """Record actual checkout revision and tracked dirty-diff hash."""

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.DEVNULL
        )

    try:
        return {
            "head": git("rev-parse", "HEAD").decode().strip(),
            "diff_hash": digest(git("diff", "HEAD")),
            "active_code_hash": digest(
                {
                    str(p.relative_to(pathlib.Path(__file__).parent)): digest(
                        p.read_bytes()
                    )
                    for p in pathlib.Path(__file__).parent.rglob("*")
                    if p.suffix in (".py", ".md")
                }
            ),
            "status": git("status", "--porcelain").decode(),
        }
    except (OSError, subprocess.CalledProcessError):
        return {"head": None, "diff_hash": None, "status": "not a checkout"}


class TraceReplay:
    """Return only an exact tool/argument/source-version match."""

    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries

    def call(self, name: str, arguments: dict, sources: dict) -> Any:
        """Raise a replay miss rather than invent a tool result."""
        for entry in self.entries:
            if (entry["name"], entry["arguments"], entry["sources"]) == (
                name,
                arguments,
                sources,
            ):
                return entry["result"]
        raise ValueError(f"Replay miss: {name}")
