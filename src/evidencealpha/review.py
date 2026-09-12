"""User-focused rubric review and bounded material-issue routing."""

from evidencealpha import artifacts
from evidencealpha import documents

CRITERIA = (
    "answers_brief",
    "builds_understanding",
    "useful_analysis",
    "responsible_evidence",
    "clear_communication",
)
RATINGS = ("Meets", "Partly meets", "Does not meet")
DECISIONS = ("ready", "ready with disclosed limitations", "needs revision")
ISSUE_KINDS = (
    "missing_evidence",
    "conflict",
    "factual",
    "explanation",
    "source_limitation",
)


def assess(output: dict, store: documents.SourceStore) -> dict:
    """Validate rubric completeness and references, not every report claim."""
    entries = output.get("rubric", [])
    ids = [x.get("criterion") for x in entries]
    complete = len(ids) == len(CRITERIA) and set(ids) == set(CRITERIA)
    complete = complete and all(
        x.get("rating") in RATINGS and x.get("explanation", "").strip()
        for x in entries
    )
    decision = output.get("decision", "")
    complete = bool(
        complete
        and decision in DECISIONS
        and output.get("review_scope", "").strip()
    )
    for issue in output.get("issues", []):
        for ref in issue.get("original_passages", []):
            original = store.open_source(ref["source_id"], ref["chunk_id"])
            if not ref.get("quote") or ref["quote"] not in original["text"]:
                raise ValueError("Review quote is absent from original")
    material = [
        x for x in output.get("issues", []) if x["severity"] == "material"
    ]
    if (
        not complete
        or material
        or any(x.get("rating") == "Does not meet" for x in entries)
    ):
        decision = "needs revision"
    elif decision == "ready" and any(
        x["rating"] == "Partly meets" for x in entries
    ):
        decision = "ready with disclosed limitations"
    return {
        "status": "complete" if complete else "partial",
        "decision": decision,
        "rubric": entries,
        "examined_scope": output.get("review_scope", ""),
        "limitations": output.get("review_limitations", ""),
        "basis": "Rubric-reviewed with targeted source checks; "
        "not exhaustively fact-verified.",
    }


def findings(autonomous: list[dict], supplemental: list[dict]) -> list[dict]:
    """Deduplicate identical findings without losing their declared origins."""
    merged = {}
    for origin, entries in (
        ("reviewer", autonomous),
        ("supplemental", supplemental),
    ):
        for entry in entries:
            key = artifacts.digest(
                {
                    k: v
                    for k, v in entry.items()
                    if k not in ("origins", "claim_ids")
                }
            )
            if key not in merged:
                merged[key] = {**entry, "origins": []}
            merged[key]["origins"] = sorted(
                set(merged[key]["origins"] + entry.get("origins", [origin]))
            )
    return list(merged.values())


def route(issues: list[dict]) -> list[dict]:
    """Assign stable IDs and deterministic actions without another model."""
    return [
        {
            **issue,
            "id": f"finding-{i}",
            "action": (
                "research"
                if issue.get("kind") in ("missing_evidence", "conflict")
                else (
                    "qualify"
                    if issue.get("kind") == "source_limitation"
                    else "revise"
                )
            ),
        }
        for i, issue in enumerate(findings(issues, []))
        if issue["severity"] == "material"
    ]


def unresolved(issues: list[dict], output: dict) -> list[dict]:
    """Keep every issue unless its focused recheck explicitly resolves it."""
    records = output.get("resolutions", [])
    ids = [x.get("id") for x in records]
    known = {x["id"] for x in issues}
    if len(ids) != len(set(ids)) or set(ids) - known:
        raise ValueError("Unknown or duplicate recheck finding ID")
    resolved = {
        x["id"]
        for x in records
        if x.get("status") == "resolved" and x.get("explanation", "").strip()
    }
    remaining = [x for x in issues if x["id"] not in resolved]
    return findings(
        remaining
        + [x for x in output.get("issues", []) if x["severity"] == "material"],
        [],
    )
