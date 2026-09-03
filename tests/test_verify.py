"""Phase 8 verification tests: the pure checks and the verifier's shape.

No model calls: the citation checker and the formatters are pure; the
graph-level behaviour is in ``tests/test_workflow.py``.
"""

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
