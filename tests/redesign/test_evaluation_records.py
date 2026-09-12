"""Evaluation helpers cannot rewrite closed historical records."""

import importlib.util
import pathlib

import pytest

from evidencealpha import artifacts


@pytest.mark.parametrize("status", ["closed", "active"])
@pytest.mark.parametrize("script", ["evaluate_hybrid_rag", "judge_hybrid_rag"])
def test_closed_evaluation_is_read_only(script, status, tmp_path):
    """Refuse before configuration reads, writes or provider admission."""
    path = (
        pathlib.Path(__file__).resolve().parents[2] / "scripts" / f"{script}.py"
    )
    spec = importlib.util.spec_from_file_location(script, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifacts.write(tmp_path / "ledger.json", {"status": status})
    sentinel = (
        "retrieval-freeze.json"
        if script.startswith("evaluate")
        else "judge-label-key.json"
    )
    artifacts.write(tmp_path / sentinel, {"preserved": True})
    before = artifacts.tree_hash(tmp_path)
    args = (
        (tmp_path, tmp_path / "corpus")
        if script.startswith("evaluate")
        else (tmp_path,)
    )
    with pytest.raises(ValueError, match="Preserve existing"):
        module.run(*args)
    assert artifacts.tree_hash(tmp_path) == before
