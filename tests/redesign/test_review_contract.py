"""Rubric acceptance and bounded action routing, with injected judgments."""

import json

from evidencealpha import artifacts
from evidencealpha import config
from evidencealpha import providers
from evidencealpha import documents
from evidencealpha import review
from evidencealpha import workflow


def assessment():
    """Return a complete rubric, not an exhaustive factual certification."""
    return {
        "content": "A useful report with targeted checks.",
        "rubric": [
            {"criterion": key, "rating": "Meets", "explanation": "Checked."}
            for key in review.CRITERIA
        ],
        "decision": "ready",
        "review_scope": "Revenue and commercial status checked; no pixels.",
        "review_limitations": "Targeted checks only.",
        "issues": [],
    }


def issue(kind="explanation"):
    """Return actionable feedback without manufacturing an absence quote."""
    return {
        "severity": "material",
        "kind": kind,
        "location": "Value chain",
        "evidence": "The brief requests a relationship explanation.",
        "impact": "A newcomer cannot understand the business model.",
        "suggestion": "Explain the relationship using authorized sources.",
        "original_passages": [],
    }


def test_rubric_readiness_and_material_routes(tmp_path):
    store = documents.SourceStore(tmp_path / "corpus")
    output = assessment()
    assert review.assess(output, store)["decision"] == "ready"
    output["rubric"][0]["rating"] = "Partly meets"
    assert review.assess(output, store)["decision"] == (
        "ready with disclosed limitations"
    )
    output["issues"] = [issue(), issue("missing_evidence")]
    workflow.parse_output(json.dumps(output), "review")
    assert review.assess(output, store)["decision"] == "needs revision"
    routed = review.route(output["issues"] + [issue()])
    assert [x["action"] for x in routed] == ["revise", "research"]
    # An empty issue list cannot erase an omitted resolution record.
    remaining = review.unresolved(
        routed,
        {
            "issues": [],
            "resolutions": [
                {
                    "id": routed[0]["id"],
                    "status": "resolved",
                    "explanation": "Explained in revision.",
                }
            ],
        },
    )
    assert [x["id"] for x in remaining] == [routed[1]["id"]]
    output["issues"] = []
    output["rubric"] = []
    assert review.assess(output, store)["decision"] == "needs revision"


def test_factual_objection_still_requires_original(tmp_path):
    store = documents.SourceStore(tmp_path / "corpus")
    output = assessment()
    output["issues"] = [issue("factual")]
    try:
        workflow.parse_output(json.dumps(output), "review")
    except ValueError as exc:
        assert "original passages" in str(exc)
    else:
        raise AssertionError("Unsupported factual objection accepted")
    source = tmp_path / "source.txt"
    source.write_text("Pilot supply only.")
    sid = store.ingest(source)["id"]
    output["issues"][0]["original_passages"] = [
        {"source_id": sid, "chunk_id": "c0", "quote": "Mass production."}
    ]
    try:
        review.assess(output, store)
    except ValueError as exc:
        assert "absent" in str(exc)
    else:
        raise AssertionError("Invented quotation accepted")


def test_normal_post_review_recovery_and_failed_recovery(tmp_path, monkeypatch):
    """Exercise normal routing and real source opens with injected outputs."""
    monkeypatch.setattr(
        workflow.render,
        "export",
        lambda _: {
            "pdf_status": "not_tested",
            "reason": "Routing test, no renderer",
        },
    )
    source = tmp_path / "original.txt"
    source.write_text(
        "Pilot supply only. Customer: Water Lab. Revenue: 10 EUR."
    )
    store = documents.SourceStore(tmp_path / "corpus")
    sid = store.ingest(source)["id"]
    for failed in (False, True):
        initial = assessment()
        gap = issue("missing_evidence")
        if not failed:
            gap["suggestion"] = (
                "Explain industry supplier-to-customer relationships "
                "for an investor unfamiliar with this industry."
            )
        initial["issues"] = [gap]
        final = assessment()
        final["resolutions"] = (
            []
            if failed
            else [
                {
                    "id": "finding-0",
                    "status": "resolved",
                    "explanation": "Customer and pilot qualifier incorporated.",
                }
            ]
        )
        outputs = {
            "plan": {
                "content": "Plan",
                "tasks": [
                    {"role": "company", "question": "Explain the business."}
                ],
            },
            "research-0": {"content": "Useful notes; relationship unchecked."},
            "synthesis": {"content": "# Water\nRelationship unverified."},
            "review": initial,
            "review-followup": (
                {"fixture_error": "quota"}
                if failed
                else [
                    {
                        "tool_calls": [
                            {
                                "name": "open_source",
                                "arguments": {
                                    "source_id": sid,
                                    "chunk_id": "c0",
                                },
                            }
                        ]
                    },
                    {"content": "Customer Water Lab, pilot supply only."},
                    {"content": "Customer Water Lab, pilot supply only."},
                ]
            ),
            "revision": {"content": "# Water\nPilot supply only."},
            "recheck": final,
        }
        provider = providers.FixtureProvider(outputs)
        root = tmp_path / ("failure" if failed else "recovered")
        result = workflow.run(
            {"text": "Explain Water for a new investor."},
            config.Settings(),
            provider,
            [],
            root,
            mode="fixed-corpus",
            source_corpus=store.root,
        )
        assert result["execution_status"] == "complete", result.get("error")
        assert list(result["stages"]) == [
            "plan",
            "research-0",
            "synthesis",
            "review",
            *([] if failed else ["review-followup"]),
            "revision",
            "recheck",
        ]
        assert bool(result["unresolved_issues"]) == failed
        assert result["readiness"] == ("needs revision" if failed else "ready")
        for stage in ("revision", "recheck"):
            folder = root / result["stages"][stage]["path"]
            context = artifacts.read(
                sorted(folder.glob("call-*/context.json"))[-1]
            )
            if failed:
                assert "failed" in context["review_followup_notes"]
            else:
                assert "Customer Water Lab" in context["review_followup_notes"]
                assert any(
                    "Customer: Water Lab" in p["text"]
                    for p in documents.ungroup_passages(
                        context["settled_evidence"]
                    )
                )
        assert result["initial_review_issues"]
        if not failed:
            follow_request = next(
                c for c in provider.calls if c.stage == "review-followup"
            )
            assert gap["suggestion"] in follow_request.prompt
            assert "without imposing a company/financial checklist" in (
                follow_request.prompt
            )
