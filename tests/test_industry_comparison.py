"""The normalized comparison projection: what may be compared, and what may not."""

from industry import comparison
from industry import quantities
from industry import records


def unit(text: str) -> records.UnitExpr:
    parsed = quantities.parse_declaration(text)
    assert not isinstance(parsed, quantities.Refusal), parsed
    return parsed


def evidence(eid: str, version: str = "v1") -> records.Evidence:
    return records.Evidence(
        id=eid,
        source_id="S1",
        source_version_id=version,
        excerpt="x",
        locator="page 1",
        kind="passage",
        extraction="pdf_text",
        task_id="T1",
        retrieved_at="2026-09-10T00:00:00+00:00",
    )


def claim(
    cid: str,
    entity: str,
    dimension: str,
    value: float | None = None,
    unit_text: str = "元",
    period: str | None = None,
    scope: str | None = None,
    review: records.Review = "supported",
    reason: str | None = None,
) -> records.Claim:
    quantity = None
    if value is not None:
        quantity = records.Quantity(
            value=value,
            unit=unit(unit_text),
            period=period,
            scope=scope,
            binding=records.EvidenceBinding(
                evidence_id="E1",
                excerpt_sha256="0" * 64,
                number_start=0,
                number_end=1,
                expression_start=0,
                expression_end=1,
                as_written="1",
            ),
        )
    return records.Claim(
        id=cid,
        statement=f"{entity} {dimension}",
        kind="fact",
        evidence_ids=["E1"],
        review=review,
        review_reason=reason,
        # The verifier confirmed the claim bears on the comparison; a
        # tag it did not confirm has never earned coverage (U1-03).
        topics=["comparison"],
        reviewed_topics=["comparison"],
        entity=entity,
        dimension=dimension,
        period=period,
        quantity=quantity,
    )


def state(*claims: records.Claim) -> dict:
    return {
        "claims": {c.id: c for c in claims},
        "evidence": {"E1": evidence("E1")},
    }


def test_scale_is_folded_so_one_unit_is_not_two_bases():
    """52亿元 and 5.2e9元 are the same number written twice."""
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024")
    b = claim("C2", "龙图", "revenue", 5.2e9, "元", "2024")
    projection = comparison.project(state(a, b))
    assert len(projection.rows) == 1
    groups = projection.rows[0].comparable()
    assert len(groups) == 1
    assert {c.entity for c in groups[0]} == {"清溢", "龙图"}
    assert {round(c.value) for c in groups[0]} == {5_200_000_000}
    assert projection.any_comparable()


def test_a10_a_different_period_is_a_different_basis():
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024")
    b = claim("C2", "龙图", "revenue", 40.0, "亿元", "2023")
    projection = comparison.project(state(a, b))
    assert projection.rows[0].comparable() == []
    assert not projection.any_comparable()
    assert projection.notes and "not directly comparable" in projection.notes[0]
    assert "2023" in projection.notes[0] and "2024" in projection.notes[0]


def test_a10_a_different_scope_is_a_different_basis():
    """Consolidated revenue is not semiconductor segment revenue."""
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024", scope="合并")
    b = claim("C2", "龙图", "revenue", 40.0, "亿元", "2024", scope="半导体分部")
    projection = comparison.project(state(a, b))
    assert projection.rows[0].comparable() == []
    assert "合并" in projection.notes[0] and "半导体分部" in projection.notes[0]


def test_a10_distinct_metrics_never_substitute_for_one_another():
    """Attributable profit is not profit before tax; the GPT report's error."""
    a = claim("C1", "龙图", "attributable net profit", 3.0, "亿元", "2024")
    b = claim("C2", "龙图", "profit before tax", 4.5, "亿元", "2024")
    projection = comparison.project(state(a, b))
    assert [row.metric for row in projection.rows] == [
        "attributable net profit",
        "profit before tax",
    ]
    assert not projection.any_comparable()


def test_a_currency_is_never_converted_without_a_rate():
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024")
    b = claim("C2", "Photronics", "revenue", 800.0, "百万美元", "2024")
    projection = comparison.project(state(a, b))
    assert projection.rows[0].comparable() == []
    assert projection.notes


def test_a_metric_label_differing_only_in_case_is_one_metric():
    a = claim("C1", "清溢", "2024 revenue", 52.0, "亿元", "2024")
    b = claim("C2", "龙图", "2024 Revenue", 40.0, "亿元", "2024")
    projection = comparison.project(state(a, b))
    assert len(projection.rows) == 1
    assert projection.rows[0].metric == "2024 revenue"
    assert projection.any_comparable()


def test_null_is_unknown_and_never_zero():
    a = claim("C1", "清溢", "capacity", None)
    projection = comparison.project(state(a))
    cell = projection.rows[0].cells[0]
    assert cell.value is None
    assert "unknown" in comparison.render(projection)
    assert "0" not in comparison.render(projection).split("unknown")[0][-6:]


def test_a_qualification_travels_into_the_table():
    a = claim(
        "C1",
        "清溢",
        "revenue",
        52.0,
        "亿元",
        "2024",
        review="qualified",
        reason="the figure rests on a search snippet only",
    )
    projection = comparison.project(state(a))
    assert projection.rows[0].cells[0].caveat.startswith("the figure rests")
    assert "search snippet only" in comparison.render(projection)


def test_only_reviewed_claims_enter_the_projection():
    a = claim(
        "C1", "清溢", "revenue", 52.0, "亿元", "2024", review="unreviewed"
    )
    b = claim("C2", "龙图", "revenue", 40.0, "亿元", "2024")
    projection = comparison.project(state(a, b))
    assert [c.claim_id for row in projection.rows for c in row.cells] == ["C2"]


def test_the_projection_is_deterministic():
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024")
    b = claim("C2", "龙图", "revenue", 40.0, "亿元", "2024")
    assert comparison.render(
        comparison.project(state(a, b))
    ) == comparison.render(comparison.project(state(b, a)))


def test_u1_03_an_unconfirmed_comparison_tag_earns_nothing():
    """Only topics the verifier confirmed take part, as everywhere else."""
    a = claim("C1", "清溢", "revenue", 52.0, "亿元", "2024")
    b = claim("C2", "龙图", "revenue", 40.0, "亿元", "2024")
    b = b.model_copy(update={"reviewed_topics": []})
    projection = comparison.project(state(a, b))
    assert [c.claim_id for row in projection.rows for c in row.cells] == ["C1"]
    assert not projection.any_comparable()


def test_u1_03_numbers_with_no_established_unit_or_period_are_not_a_basis():
    """The same unknown written twice is not agreement."""
    a = claim("C1", "清溢", "capacity", 100.0, "元", None)
    b = claim("C2", "龙图", "capacity", 80.0, "元", None)
    projection = comparison.project(state(a, b))
    assert projection.rows[0].comparable() == []
    # Qualitative cells, which carry no value, still compare.
    c = claim("C3", "清溢", "positioning")
    e = claim("C4", "龙图", "positioning")
    qualitative = comparison.project(state(c, e))
    assert qualitative.rows[0].comparable()


def test_u1_04_a_scale_below_a_divide_is_reached():
    """`万元/片` parses as divide(scale10(4, 元), 片)."""
    a = claim("C1", "清溢", "unit price", 1.0, "万元/片", "2024")
    b = claim("C2", "龙图", "unit price", 10000.0, "元/片", "2024")
    projection = comparison.project(state(a, b))
    assert projection.any_comparable()
    values = {round(c.value) for c in projection.rows[0].cells}
    assert values == {10000}
