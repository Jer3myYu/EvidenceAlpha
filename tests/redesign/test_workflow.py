"""Observable workflow boundaries, not legacy eligibility machinery."""

import dataclasses
import json
import pathlib

import pytest

from evidencealpha import artifacts
from evidencealpha import cli
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import workflow

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures" / "redesign"


def _run(tmp_path, name="service", outputs=None):
    brief, provider, sources = cli.fixture(FIXTURES / f"{name}.json")
    if outputs:
        provider.outputs.update(outputs)
    root = tmp_path / "run"
    result = workflow.run(brief, config.Settings(), provider, sources, root)
    return result, provider, root


@pytest.mark.parametrize("name", ["manufacturing", "service"])
def test_complete_generic_report(tmp_path, name):
    """Distinct domains preserve body, figures, source links and PDF."""
    result, provider, root = _run(tmp_path, name)
    assert result["status"] == "reviewed_with_limitations"
    assert result["render"]["pdf_status"] == "complete"
    assert result["reviewed_hash"] is None
    assert result["review_status"] == "partial"
    assert (root / "reports/report.pdf").stat().st_size > 1000
    figures = artifacts.read(root / "reports/figures.json")
    assert (root / "reports" / figures[0]["path"]).exists()
    assert "Sources / 来源" in (root / "reports/report.md").read_text()
    assert len([c for c in provider.calls if c.stage == "review"]) == 1
    assert len([c for c in provider.calls if c.stage == "recheck"]) == (
        name == "manufacturing"
    )


def test_review_failure_preserves_draft(tmp_path):
    """Malformed/failed review never deletes or certifies useful writing."""
    result, _, root = _run(tmp_path, outputs={"review": {"content": ""}})
    assert result["status"] == "draft_review_incomplete"
    assert result["reviewed_hash"] is None
    assert (root / "reports/draft.md").read_bytes() == (
        root / "reports/report.md"
    ).read_bytes()
    assert result["error"]["type"] == "ValueError"


def test_optional_polish_and_unresolved_recheck_are_bounded(tmp_path):
    """No third review and optional polish alone does not spend revision."""
    issue = {
        "severity": "optional",
        "location": "title",
        "evidence": "style only",
        "impact": "readability",
        "suggestion": "shorten",
    }
    result, provider, _ = _run(
        tmp_path, outputs={"review": {"content": "polish", "issues": [issue]}}
    )
    assert result["status"] == "reviewed_with_limitations"
    assert not any(c.stage == "revision" for c in provider.calls)
    issue["severity"] = "material"
    issue["original_passages"] = artifacts.read(
        FIXTURES / "manufacturing.json"
    )["outputs"]["review"]["issues"][0]["original_passages"]
    other = tmp_path / "second"
    result, provider, _ = _run(
        other,
        "manufacturing",
        {"recheck": {"content": "unresolved", "issues": [issue]}},
    )
    assert result["status"] == "reviewed_with_limitations"
    assert [c.stage for c in provider.calls].count("recheck") == 1


def test_resume_reuses_outputs_and_changed_draft_invalidates_review(tmp_path):
    """Hash dependencies invalidate review while unrelated research is
    reused.
    """
    first, _, root = _run(tmp_path)
    brief, provider, sources = cli.fixture(FIXTURES / "service.json")
    resumed = workflow.run(
        brief, config.Settings(), provider, sources, root, resume=True
    )
    assert not provider.calls
    assert resumed["report_hash"] == first["report_hash"]
    draft = root / "reports/draft.md"
    draft.write_text(draft.read_text() + "\nAdditional explicit limitation.\n")
    workflow.run(brief, config.Settings(), provider, sources, root, resume=True)
    assert [c.stage for c in provider.calls] == ["review"]


def test_reviewer_has_independent_portable_context(tmp_path):
    """Writer notes and private provider sessions are not reviewer inputs."""
    _, provider, root = _run(tmp_path)
    review = next(c for c in provider.calls if c.stage == "review")
    portable = json.loads(json.loads(review.prompt)["messages"][1]["content"])
    assert "notes" not in portable
    assert "asset_hashes" in portable
    record = next((root / "stages/review").glob("*/input.json"))
    data = artifacts.read(record)
    assert data["settings"]["model"] == config.REVIEW_MODEL
    assert data["settings"]["effort"] == "medium"
    assert data["portable"]["draft"] == (root / "reports/report.md").read_text()


def test_fixture_stage_fork_preserves_original(tmp_path):
    """No-op replay emits identical body into a new attempt/corpus."""
    _, _, root = _run(tmp_path)
    before = artifacts.tree_hash(root)
    source = next((root / "stages/synthesis").glob("*/input.json"))
    _, provider, _ = cli.fixture(FIXTURES / "service.json")

    result = workflow.replay_stage(
        source,
        tmp_path / "fork",
        config.Settings(),
        provider,
        documents.SourceStore(root / "sources"),
    )
    original = artifacts.read(source.parent / "output.json")
    assert result["output"] == original
    assert artifacts.tree_hash(root) == before


def test_changed_settings_do_not_reuse(tmp_path):
    """A changed model/prompt contract cannot inherit prior review silently."""
    _, _, root = _run(tmp_path)
    brief, provider, sources = cli.fixture(FIXTURES / "service.json")
    with pytest.raises(ValueError, match="Settings changed"):
        workflow.run(
            brief,
            dataclasses.replace(config.Settings(), workers=1),
            provider,
            sources,
            root,
            resume=True,
        )


def test_malformed_control_records_fail_at_boundary():
    """Bad model control values fail clearly before orchestration/rendering."""
    for output, role in [
        ({"content": "x", "issues": [1]}, "review"),
        ({"content": "x", "tasks": [1]}, "plan"),
        ({"content": "x", "figures": ["invalid"]}, "synthesis"),
    ]:
        with pytest.raises(ValueError):
            workflow.parse_output(json.dumps(output), role)


def test_revision_preserves_draft_figure_inputs(tmp_path):
    """Revision assets never overwrite the figure version examined first."""
    _, _, root = _run(tmp_path, "manufacturing")
    assert (root / "reports/draft/figures/figure-1.json").is_file()
    assert (root / "reports/revised/figures/figure-1.json").is_file()
    draft = (root / "reports/draft.md").read_text()
    revised = (root / "reports/revised.md").read_text()
    assert "](draft/figures/figure-1.png)" in draft
    assert "](revised/figures/figure-1.png)" in revised
