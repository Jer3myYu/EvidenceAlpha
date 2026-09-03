"""Phase 8 verification tests: the pure checks and the verifier's shape.

No model calls: the citation checker and the formatters are pure; the
graph-level behaviour is in ``tests/test_workflow.py``.
"""

from typing import Any

import pydantic
import pytest

from research import agent
from research import sources
from research import verify

SOURCES = {
    "S1": sources.SourceRecord("S1", "a.txt", None, "a.txt", ("documents",)),
    "S2": sources.SourceRecord(
        "S2", "Site", "https://x.example/p", None, ("web",)
    ),
}


def test_valid_citation_forms_pass():
    answer = "Acme is in Pittsburgh [S1]. It sells arms [S1, S2] and [S1][S2]."

    assert verify.cited_labels(answer) == ["S1", "S1", "S2", "S1", "S2"]
    assert not verify.check_citations(answer, SOURCES)


def test_round_local_and_unknown_labels_are_reported_once_in_order():
    answer = "A [D2]. B [W1]. C [S9]. D [D2] again. E [S2, S9]."

    assert verify.check_citations(answer, SOURCES) == [
        "[D2] is a round-local label, not a source.",
        "[W1] is a round-local label, not a source.",
        "[S9] is not a known source.",
    ]


def test_ordinary_brackets_and_the_gap_sentence_are_not_citations():
    prose = "In [2024] the board [see note] met; labels [S1 and S2] differ."

    assert not verify.cited_labels(prose)
    assert not verify.check_citations(prose, SOURCES)
    assert not verify.check_citations(agent.EVIDENCE_GAP, {})


def check(verdict: str, claim: str = "Acme employs 520 people.") -> Any:
    return verify.ClaimCheck(
        claim=claim,
        cited_sources=["S1"],
        verdict=verdict,
        reason="Observation 1 states about 400.",
    )


def verification(claims=(), conflicts=(), ratings=()) -> verify.Verification:
    return verify.Verification(
        claims=list(claims),
        conflicts=list(conflicts),
        source_ratings=list(ratings),
    )


def test_supported_claims_and_ratings_alone_raise_no_issue():
    weak = verify.SourceRating(source_id="S2", quality="weak", reason="Blog.")
    result = verification([check("supported")], ratings=[weak])

    assert not verify.list_issues([], result)


def test_unsupported_and_contradicted_claims_are_issues_with_their_reason():
    result = verification(
        [check("supported"), check("unsupported"), check("contradicted")]
    )

    assert verify.list_issues([], result) == [
        'Unsupported claim: "Acme employs 520 people." '
        "Observation 1 states about 400.",
        'Contradicted claim: "Acme employs 520 people." '
        "Observation 1 states about 400.",
    ]


def test_only_undisclosed_conflicts_are_issues_and_citations_come_first():
    hidden = verify.Conflict(
        sources=["S1", "S2"],
        description="The founding year is 2011 in one and 2013 in the other.",
        disclosed_in_answer=False,
    )
    shown = verify.Conflict(
        sources=["S1", "S2"],
        description="Headcount differs.",
        disclosed_in_answer=True,
    )
    result = verification([check("supported")], conflicts=[hidden, shown])

    assert verify.list_issues(["[D1] is a round-local label."], result) == [
        "[D1] is a round-local label.",
        "Conflicting evidence not disclosed ([S1], [S2]): The founding "
        "year is 2011 in one and 2013 in the other.",
    ]


def test_conflicts_under_an_answer_with_no_claims_are_not_issues():
    hidden = verify.Conflict(
        sources=["S1", "S2"],
        description="Founding years differ.",
        disclosed_in_answer=False,
    )

    assert not verify.list_issues([], verification(conflicts=[hidden]))
    assert verify.list_issues(
        [], verification([check("supported")], conflicts=[hidden])
    ) == [
        "Conflicting evidence not disclosed ([S1], [S2]): Founding years "
        "differ."
    ]


def test_verification_schema_is_small_closed_and_enumerated():
    schema = verify.Verification.model_json_schema()

    assert set(schema["properties"]) == {
        "claims",
        "conflicts",
        "source_ratings",
    }
    assert schema["additionalProperties"] is False
    defs = schema["$defs"]
    assert set(defs) == {"ClaimCheck", "Conflict", "SourceRating"}
    assert set(defs["ClaimCheck"]["properties"]) == {
        "claim",
        "cited_sources",
        "verdict",
        "reason",
    }
    assert defs["ClaimCheck"]["properties"]["verdict"]["enum"] == [
        "supported",
        "unsupported",
        "contradicted",
    ]
    assert defs["SourceRating"]["properties"]["quality"]["enum"] == [
        "primary",
        "secondary",
        "weak",
    ]
    assert all(defs[name]["additionalProperties"] is False for name in defs)
    with pytest.raises(pydantic.ValidationError):
        verify.ClaimCheck(
            claim="x", cited_sources=[], verdict="maybe", reason="r"
        )
