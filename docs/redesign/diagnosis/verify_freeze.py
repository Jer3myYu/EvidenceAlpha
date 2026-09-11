"""Verify the saved evaluation snapshot without starting model work."""

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]


def main() -> None:
    """Check archive, manifest, input hashes and read-only snapshot files."""
    descriptor = json.loads(
        (ROOT / "docs/redesign/diagnosis/FROZEN_EVALUATION.json").read_text()
    )
    snapshot = ROOT / descriptor["snapshot"]
    manifest_path = snapshot / "MANIFEST.json"
    for path, expected in (
        (ROOT / descriptor["archive"], descriptor["archive_sha256"]),
        (manifest_path, descriptor["manifest_sha256"]),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen artifact changed: {path}")
    manifest = json.loads(manifest_path.read_text())
    for relative, expected in manifest["files"].items():
        path = snapshot / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen input changed: {relative}")
        if path.stat().st_mode & 0o222:
            raise ValueError(f"Frozen input is writable: {relative}")
    count = len(manifest["files"])
    print(f"Verified {count} frozen files; no model work.")


if __name__ == "__main__":
    main()
