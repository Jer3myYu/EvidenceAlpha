"""Bounded material-claim review; references are not factual certification."""

from evidencealpha import artifacts
from evidencealpha import documents


def inventory(
    output: dict,
    draft: str,
    requirements: list[dict],
    aliases: dict | None = None,
) -> dict:
    """Bind the writer's provisional claim list to the exact draft and brief."""
    items = []
    seen = set()
    required_ids = {r["id"] for r in requirements}
    for claim in output.get("review_claims", []):
        claim = dict(claim)
        for source_id, alias in (aliases or {}).items():
            claim["location"] = claim.get("location", "").replace(
                source_id, alias
            )
        if (
            not claim.get("id")
            or claim["id"] in seen
            or not claim.get("claim", "").strip()
            or not claim.get("location", "").strip()
            or claim.get("requirement_id") not in required_ids | {""}
        ):
            raise ValueError(
                "Review claim identity/location/requirement invalid"
            )
        seen.add(claim["id"])
        items.append(
            {
                **claim,
                "kind": "factual",
                "location_verified": claim["location"] in draft,
            }
        )
    mapped = {c["requirement_id"] for c in items}
    gaps = [r for r in requirements if r["id"] not in mapped]
    # Historical writers had no claim inventory. Keep omissions explicit;
    # never reinterpret heading counts as a complete factual audit.
    return {
        "version": 2,
        "items": items,
        "unmapped_requirements": gaps,
        "requirements": requirements,
        "status": "provisional" if items and not gaps else "incomplete",
        "draft_hash": artifacts.digest(draft),
    }


def assess(
    output: dict,
    specification: dict,
    store: documents.SourceStore,
    draft: str = "",
) -> dict:
    """Validate documented checks while keeping interpretation provisional."""
    additions = output.get("review_claims", [])
    if additions:
        specification = inventory(
            {"review_claims": specification["items"] + additions},
            draft,
            specification["requirements"],
        )
    claims = {c["id"]: c for c in specification["items"]}
    checks = {}
    errors = []
    for check in output.get("review_checks", []):
        cid = check.get("id")
        if cid in checks or cid not in claims:
            raise ValueError("Unknown or duplicate review claim ID")
        checks[cid] = check
    items = []
    for cid, claim in claims.items():
        check = checks.get(cid, {})
        status = check.get("status", "unexamined")
        outcome = check.get("outcome", "not_assessed")
        refs = check.get("original_passages", [])
        problem = None
        if not claim.get("location_verified", True):
            problem = "Location is not an exact draft excerpt; check unverified"
        elif status not in (
            "examined",
            "partial",
            "unexamined",
        ) or outcome not in (
            "supported",
            "contradicted",
            "insufficient_evidence",
            "not_assessed",
        ):
            problem = "Invalid examination/outcome combination"
        elif not check.get("explanation", "").strip():
            problem = "Missing explanation of examination or its limits"
        elif status == "examined" and (
            check.get("checked_claim") != claim["claim"]
            or check.get("remaining", "").strip()
            or outcome == "not_assessed"
        ):
            problem = "Complete examination must identify the exact whole claim"
        elif status != "examined" and outcome in ("supported", "contradicted"):
            problem = "Partial examination cannot certify the whole claim"
        elif outcome in ("supported", "contradicted") and not refs:
            problem = "Factual judgment requires supporting originals"
        elif (
            outcome == "insufficient_evidence"
            and not check.get("checks_performed", "").strip()
        ):
            problem = (
                "Record actual checks and their limits; do not prove absence"
            )
        for ref in refs:
            original = store.open_source(ref["source_id"], ref["chunk_id"])
            if not ref.get("quote") or ref["quote"] not in original["text"]:
                problem = "Quote is absent from its original"
        if problem:
            errors.append({"id": cid, "error": problem})
            status, outcome = "unexamined", "not_assessed"
        items.append({**claim, **check, "status": status, "outcome": outcome})
    missing = [x["id"] for x in items if x["status"] != "examined"]
    inventory_complete = specification["status"] != "incomplete"
    complete = (
        bool(items)
        and inventory_complete
        and not missing
        and bool(output.get("inventory_assessment", "").strip())
    )
    factual = complete and all(x["outcome"] == "supported" for x in items)
    return {
        "status": "complete" if complete else "partial",
        "factual_status": "supported" if factual else "unresolved",
        "items": items,
        "errors": errors,
        "unexamined_ids": missing,
        "unmapped_requirements": specification["unmapped_requirements"],
        "editorial_assessment": output.get("editorial_assessment", ""),
        "inventory_assessment": output.get("inventory_assessment", ""),
        "provisional": True,
        "limitation": (
            "Exact references checked; semantic support and inventory "
            "completeness remain model judgments, not certification."
        ),
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
            merged[key]["claim_ids"] = sorted(
                set(
                    merged[key].get("claim_ids", [])
                    + entry.get("claim_ids", [])
                )
            )
    return list(merged.values())


def resolution(assessment: dict, issues: list[dict], recheck: dict) -> dict:
    """Map a focused recheck only to explicitly linked original claims."""
    checked = {
        x["id"] for x in recheck.get("items", []) if x["status"] == "examined"
    }
    affected = {}
    for i, issue in enumerate(issues):
        for cid in issue.get("claim_ids", []):
            affected.setdefault(cid, set()).add(f"finding-{i}")
    resolved = {cid for cid, ids in affected.items() if ids <= checked}
    outstanding = [
        x["id"]
        for x in assessment["items"]
        if x["status"] != "examined"
        or (x["outcome"] != "supported" and x["id"] not in resolved)
    ]
    return {
        "status": (
            "supported"
            if assessment["status"] == "complete" and not outstanding
            else "unresolved"
        ),
        "resolved_claim_ids": sorted(resolved),
        "outstanding_claim_ids": outstanding,
        "limitation": "Focused recheck does not upgrade unexamined scope.",
    }
