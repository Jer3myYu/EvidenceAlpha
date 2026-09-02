"""Phase 2 test: the prompt carries every chunk, numbered, plus the question."""

import dataclasses

from rag import models
from research import acquire
from research import agent
from research import answer
from research import plan
from research import web


def test_build_prompt_numbers_chunks_and_includes_question():
    chunks = [
        models.RetrievedChunk("Acme makes arms in Pittsburgh.", "a.txt", 0.1),
        models.RetrievedChunk("Beta sells frozen peas in Ohio.", "b.md", 0.4),
    ]

    prompt = answer.build_prompt("Where is Acme based?", chunks)

    assert "[1] source: a.txt\nAcme makes arms in Pittsburgh." in prompt
    assert "[2] source: b.md\nBeta sells frozen peas in Ohio." in prompt
    assert prompt.index("[1]") < prompt.index("[2]")
    assert prompt.endswith("Question: Where is Acme based?")


def test_format_chunks_numbers_source_distance_and_text_in_order():
    chunks = [
        models.RetrievedChunk("Acme makes arms in Pittsburgh.", "a.txt", 0.1),
        models.RetrievedChunk("Beta sells frozen peas in Ohio.", "b.md", 0.4),
    ]

    text = agent.format_chunks(chunks)

    assert text == (
        "[D1] source: a.txt (distance 0.1000)\n"
        "Acme makes arms in Pittsburgh.\n\n"
        "[D2] source: b.md (distance 0.4000)\n"
        "Beta sells frozen peas in Ohio."
    )


def test_format_results_labels_web_hits_in_order():
    results = [
        web.WebResult("Humanoid Index", "https://h.example/a", "108 firms."),
        web.WebResult("Forbes list", "https://f.example/b", "16 leaders."),
    ]

    text = agent.format_results(results)

    assert text == (
        "[W1] Humanoid Index - https://h.example/a\n108 firms.\n\n"
        "[W2] Forbes list - https://f.example/b\n16 leaders."
    )


def test_parse_plan_reads_candidates_selection_and_reason():
    data = {
        "use_tot": True,
        "candidates": [
            {
                "label": "A",
                "approach": "Value chain",
                "scope": "strong",
                "evidence": "strong",
                "coverage": "medium",
            },
            {
                "label": "B",
                "approach": "Technology stack",
                "scope": "strong",
                "evidence": "medium",
                "coverage": "strong",
            },
            {
                "label": "C",
                "approach": "Vendors vs suppliers",
                "scope": "strong",
                "evidence": "strong",
                "coverage": "strong",
            },
        ],
        "selected": "C",
        "reason": "Covers direct and indirect exposure.",
    }

    result = plan.parse_plan(data)

    assert result.use_tot is True
    assert [c.label for c in result.candidates] == ["A", "B", "C"]
    assert result.candidates[1].evidence == "medium"
    assert result.chosen().approach == "Vendors vs suppliers"
    assert result.reason == "Covers direct and indirect exposure."


def test_candidate_schema_allows_only_candidate_fields():
    # parse_plan builds Candidate(**item), so any key the schema lets the
    # model emit must be a Candidate field, and no other key may pass.
    item = plan.PLAN_SCHEMA["properties"]["candidates"]["items"]
    fields = {field.name for field in dataclasses.fields(plan.Candidate)}

    assert set(item["properties"]) == fields
    assert item["additionalProperties"] is False


def test_is_pdf_uses_content_type_or_url_suffix():
    assert acquire.is_pdf("https://x.example/report", "application/pdf")
    assert acquire.is_pdf("https://x.example/Report.PDF", "text/html")
    assert not acquire.is_pdf("https://x.example/page", "text/html")
