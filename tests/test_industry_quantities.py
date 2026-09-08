"""The bounded quantity grammar: identity, binding, and refusal.

These are the invariant tests of the quantity redesign (plan revision
22 §4.28): I3 lossless expression identity over enumerated and random
trees, I1 one exact binding under mutation, I2 proposal-independent
interpretation, the external-gap policy, and the number-form rules.
End-to-end instances through the merge live in ``test_industry_merge``.
"""

import itertools
import random

import pytest

import quantity_support as support
from industry import quantities
from industry import records

ATOMS = ("USD", "元", "kg", "day")


def trees(depth):
    """Every unit tree to ``depth`` over four atoms, powers and scales."""
    if depth == 0:
        return [quantities.atom(a) for a in ATOMS]
    below = trees(depth - 1)
    out = list(below)
    for tree in below:
        if tree.kind not in ("power", "scale10"):
            out += [quantities.power(tree, n) for n in (2, 3)]
        if tree.kind != "scale10":
            out += [quantities.scale10(e, tree) for e in (4, 6, 8)]
    for left, right in itertools.product(below, repeat=2):
        out.append(quantities.divide(left, right))
        out.append(quantities.multiply(left, right))
    return out


def test_every_enumerated_tree_renders_to_one_spelling_that_parses_back():
    # I3: rendering followed by parsing is the identity, and no two
    # trees share a spelling (grouping, order and exponents survive).
    seen = {}
    distinct = set()
    for tree in trees(2):
        text = quantities.render(tree)
        assert quantities.parse_unit(text) == tree, text
        assert seen.setdefault(text, tree) == tree, text
        assert records.UnitExpr.model_validate(tree.model_dump()) == tree
        distinct.add(tree.model_dump_json())
    assert len(seen) == len(distinct) == 6480


def test_random_deep_trees_round_trip():
    rng = random.Random(7)
    atoms = [quantities.atom(a) for a in ATOMS + ("%", "台")]

    def build(depth):
        if depth == 0 or rng.random() < 0.25:
            return rng.choice(atoms)
        kind = rng.choice(("scale", "power", "div", "mul", "div", "mul"))
        if kind == "scale":
            inner = build(depth - 1)
            if inner.kind == "scale10":
                inner = rng.choice(atoms)
            return quantities.scale10(rng.choice((3, 4, 6, 8, 9, 12)), inner)
        if kind == "power":
            inner = build(depth - 1)
            if inner.kind in ("power", "scale10"):
                inner = rng.choice(atoms)
            return quantities.power(inner, rng.choice((2, 3)))
        left, right = build(depth - 1), build(depth - 1)
        if kind == "div":
            return quantities.divide(left, right)
        return quantities.multiply(left, right)

    for _ in range(3000):
        tree = build(3)
        assert quantities.parse_unit(quantities.render(tree)) == tree


def test_grouping_order_and_exponents_are_distinct_units():
    # C1 round 6, findings 2 and 3, at the grammar.
    assert support.unit("USD/(kg/day)") != support.unit("(USD/kg)/day")
    assert support.unit("(USD/kg)/day") == support.unit("USD/kg/day")
    assert support.unit("USD*(kg/day)") != support.unit("USD*kg/day")
    assert support.unit("USD/m²") != support.unit("USD/m³")
    assert support.unit("kg/USD") != support.unit("USD/kg")
    assert support.unit("USD/kg") != support.unit("USD*kg")
    assert support.unit("USD million") != support.unit("USD")
    # The documented aliases are the only collapses.
    assert support.unit("million USD") == support.unit("USD million")
    assert support.unit("美元") == support.unit("USD")
    assert support.unit("平方米") == quantities.power(quantities.atom("m"), 2)
    assert support.unit("人民币万元") == support.unit("万元人民币")
    assert support.unit("$ million") != support.unit("USD million")
    assert support.unit("个百分点") != support.unit("%")


def test_the_unit_expr_record_refuses_malformed_trees():
    with pytest.raises(ValueError):
        records.UnitExpr(kind="atom", atom="widgets")
    with pytest.raises(ValueError):
        records.UnitExpr(
            kind="scale10", exponent=5, left=quantities.atom("USD")
        )
    with pytest.raises(ValueError):
        records.UnitExpr(kind="power", exponent=4, left=quantities.atom("m"))
    with pytest.raises(ValueError):
        quantities.scale10(4, quantities.scale10(8, quantities.atom("元")))
    with pytest.raises(ValueError):
        records.UnitExpr(kind="divide", left=quantities.atom("USD"))


def test_proposal_spellings_parse_or_refuse_whole():
    good = {
        "亿元": "亿元",
        "USD million": "USD million",
        "US$ m": "USD million",
        "$ million": "$ million",
        "RMB 万元": "万CNY",
        "USD/kg": "USD/kg",
        "万元/年": "万元/年",
        "million (USD/kg)": "million (USD/kg)",
        "(USD/kg)²": "(USD/kg)²",
        "%": "%",
        "percent": "%",
        "百分点": "pp",
    }
    for text, spelling in good.items():
        assert quantities.render(support.unit(text)) == spelling, text
    for text, code in (
        ("52亿元", "no_unit"),
        ("亿", "no_unit"),
        ("元件", "ambiguous_continuation"),
        ("USD*", "ambiguous_continuation"),
        ("", "no_unit"),
        ("m^4", "unsupported_unit_power"),
    ):
        parsed = quantities.parse_unit(text)
        assert isinstance(parsed, quantities.Refusal) and parsed.code == code


def parse(text, quote, occurrence=1, **kw):
    """Parse the expression a quote selects; return the outcome."""
    at = quantities.find_quote(text, quote, occurrence)
    if isinstance(at, quantities.Refusal):
        return at.code
    parsed = quantities.parse_expression(text, at, **kw)
    if isinstance(parsed, quantities.Refusal):
        return parsed.code
    return quantities.render(parsed.unit), parsed.value


def test_the_expression_is_read_from_the_evidence_alone():
    # I2: every case below is decided by the excerpt, never by what a
    # researcher proposed; the proposal is compared afterwards.
    assert parse("收入为52亿元，同比增长12%。", "52亿元") == ("亿元", 52.0)
    assert parse("收入为52亿元，同比增长12%。", "12%") == ("%", 12.0)
    assert parse("投资人民币52万元。", "人民币52万元") == ("万CNY", 52.0)
    assert parse("总投资52亿元人民币。", "52亿元人民币") == ("亿CNY", 52.0)
    assert parse("about $52 million per set.", "$52 million") == (
        "$ million/sets",
        52.0,
    )
    assert parse("costs US$52m per employee", "US$52m") == (
        "USD million/people",
        52.0,
    )
    assert parse("Price was 52 USD per kg.", "52 USD") == ("USD/kg", 52.0)
    assert parse("cost 52 (USD/kg) today", "52") == ("USD/kg", 52.0)
    assert parse("单价13,188.99 元/片、", "13,188.99 元/片") == (
        "元/片",
        13188.99,
    )
    assert parse("52万吨/年", "52万吨") == ("万t/年", 52.0)
    assert parse("面积52 平方米", "52 平方米") == ("m²", 52.0)
    assert parse("同比-5.2%，", "-5.2%") == ("%", -5.2)
    assert parse("率 -16.34% -15.02% 1.57%", "-15.02%") == ("%", -15.02)
    assert parse("Acme sold 100 million USD and employed 52 people.", "52") == (
        "people",
        52.0,
    )


def test_ranges_paired_figures_and_unresolved_text_refuse_whole():
    for text, quote, code in (
        ("份额约为13.19%-26.39%，", "13.19%", "range"),
        ("份额约为13.19%-26.39%，", "26.39%", "range"),
        ("收入52 - 60亿元。", "60亿元", "range"),
        ("成本10至20万元。", "20万元", "range"),
        ("成本10至20万元。", "10", "range"),
        ("roughly $10 million to $20 million", "$20 million", "range"),
        ("收入10.96/13.70 亿元", "13.70 亿元", "unsupported_number_form"),
        ("（负债总额÷资产总额）×100%；", "100%", "unsupported_number_form"),
        ("report 53 / 312 个百分点", "312 个百分点", "unsupported_number_form"),
        ("uses 52 kg per 100 km", "52 kg", "unsupported_number_form"),
        ("revenue 52 × 10⁶ USD", "52", "unsupported_number_form"),
        ("cost .52 USD", "52 USD", "unsupported_number_form"),
        ("金额1 234 万元。", "234 万元", "unsupported_number_form"),
        ("见2.2.1节", "2.2.1", "unsupported_number_form"),
        ("本批包括52元件。", "52元件", "ambiguous_continuation"),
        ("本批包括52元器件。", "52元", "ambiguous_continuation"),
        ("完成6.2 亿元股权融资", "6.2 亿元", "ambiguous_continuation"),
        ("price 52 USD kg today", "52 USD", "ambiguous_continuation"),
        ("price 52 USD / widget", "52 USD", "ambiguous_continuation"),
        ("EPS to $0.54from $0.15", "$0.54", "attached_continuation"),
        ("Model X-52 units sold", "52 units", "range"),
        ("人民币1个月", "人民币1", "ambiguous_continuation"),
        ("人民币 2025年", "人民币 2025", "prefix_tail_conflict"),
        ("about $52 million USD", "$52 million", "prefix_tail_conflict"),
        ("The cable length was 52 M long", "52 M", "no_unit"),
        ("revenue was 52 million", "52 million", "no_unit"),
        ("总计152亿元。", "52亿元", "not_in_excerpt"),
    ):
        assert parse(text, quote) == code, (text, quote)
    # Documented prose continuations are boundaries; whitespace inside a
    # CJK unit is tolerated once; a percent takes no denomination.
    assert parse("投资2,000 万 元左右", "2,000 万 元") == ("万元", 2000.0)
    assert parse("总投资60,464.56万元项目", "60,464.56万元") == (
        "万元",
        60464.56,
    )
    assert parse("from 36.3% year-to-date", "36.3%") == ("%", 36.3)
    assert parse("清溢光电 - 52.43% 58.03%", "52.43%") == ("%", 52.43)


def test_an_unknown_gap_is_resolved_only_by_a_certified_delimiter():
    # The residual external-gap policy: PDF page edges, snippet edges
    # and ellipses are unknown gaps; a certified delimiter between the
    # gap and the expression isolates it, nothing else does.
    assert parse("至 97%。 文文", "97%", gap_start=True) == "cut_edge"
    assert parse("民币52亿元。", "52亿元", gap_start=True) == "cut_edge"
    assert parse(",234元。文", "234元", gap_start=True) == "cut_edge"
    assert parse("xyz 52 USD.", "52 USD", gap_start=True) == "cut_edge"
    assert parse("xyz, 52 USD.", "52 USD", gap_start=True) == ("USD", 52.0)
    assert parse("x 52 USD pe", "52 USD", gap_end=True) == "cut_edge"
    assert parse("x 52 USD in 2024", "52 USD", gap_end=True) == "cut_edge"
    assert parse("x 52 USD.", "52 USD", gap_end=True) == ("USD", 52.0)
    assert parse("收入52亿元、", "52亿元", gap_end=True) == ("亿元", 52.0)
    assert parse("revenue was ... 52 million USD in", "52 million USD") == (
        "cut_edge"
    )
    assert parse("revenue was ...; 52 million USD in.", "52 million USD") == (
        "USD million",
        52.0,
    )
    assert parse("USD 52 ... per kg", "USD 52") == "cut_edge"
    # Internal chunk boundaries are certified by construction.
    assert quantities.certified_cuts(
        "收入52亿元，同比增长12%。合计1,234.5元;"
    ) == [
        7,
        15,
        26,
    ]
    assert quantities.certified_cuts("a (b; c) d. e") == [11]


def test_the_quote_selects_one_whole_token():
    text = "总计152亿元，其中52亿元为海外，另52亿元为国内。"
    assert quantities.find_quote(text, "52亿元", 1) == text.index("其中52") + 2
    assert quantities.find_quote(text, "52亿元", 2) == text.index("另52") + 1
    assert quantities.find_quote(text, "52亿元", 3).code == (
        "occurrence_out_of_range"
    )
    assert quantities.find_quote("总计152亿元", "52亿元", 1).code == (
        "not_in_excerpt"
    )
    assert quantities.find_quote("收入为52 亿元。", "52亿元", 1) == 3
    assert quantities.find_quote("x", "", 1).code == "quote_not_a_token"


def test_a_binding_is_verified_field_by_field():
    # I1: every single-field change to a stored binding, or to the
    # evidence it names, is refused; the true binding passes.
    holder = support.evidence(
        "E1", "Acme revenue reached 52亿元 in 2024. Peer sold 52亿元 too."
    )
    quantity = support.admitted(52, "亿元", "52亿元", holder)
    assert quantities.verify_binding(quantity, holder) is None
    second = support.admitted(52, "亿元", "52亿元", holder, occurrence=2)
    assert quantities.verify_binding(second, holder) is None
    assert second.binding.number_start != quantity.binding.number_start
    binding = quantity.binding
    mutations = {
        "evidence_id": "E2",
        "excerpt_sha256": "0" * 64,
        "number_start": binding.number_start + 1,
        "number_end": binding.number_end - 1,
        "expression_start": binding.expression_start - 1,
        "expression_end": binding.expression_end + 1,
        "as_written": "52亿",
        "cell_row": 0,
        "header_row": 0,
    }
    for field, value in mutations.items():
        mutated = quantity.model_copy(
            update={"binding": binding.model_copy(update={field: value})}
        )
        assert quantities.verify_binding(mutated, holder) is not None, field
    for field, value in (
        ("value", 53.0),
        ("unit", support.unit("万元")),
    ):
        mutated = quantity.model_copy(update={field: value})
        assert quantities.verify_binding(mutated, holder) is not None, field
    changed = holder.model_copy(update={"excerpt": holder.excerpt + "!"})
    assert quantities.verify_binding(quantity, changed) is not None
    assert quantities.verify_binding(quantity, None) is not None
    unbound = quantity.model_copy(update={"binding": None})
    assert quantities.verify_binding(unbound, holder) is not None


def test_folding_keeps_offsets_and_token_kinds():
    text = "增长５２．６％（２０２４）；−52 m² ... 文"
    folded = quantities.fold(text)
    assert len(folded) == len(text)
    kinds = [t.kind for t in quantities.lex(text)]
    assert "sup" in kinds and "number" in kinds and "dash" in kinds
    assert quantities.fold("52²")[-1] == "²"


def test_a_signed_quantity_verifies_and_survives_correction():
    # C1 round 7, finding 1: the binding anchored at the minus sign and
    # verification re-parsed at a digit offset, so an admitted negative
    # figure failed verification, was dropped by a statement-only
    # correction, and made its checkpoint unresumable.
    for excerpt, quote, unit_text, value in (
        ("同比-5.2%，", "-5.2%", "%", -5.2),
        ("USD -52.", "USD -52", "USD", -52.0),
        ("率 -16.34% -15.02% 1.57%", "-15.02%", "%", -15.02),
        ("growth of −3.5%.", "−3.5%", "%", -3.5),
    ):
        holder = support.evidence("E1", excerpt)
        quantity = support.admitted(value, unit_text, quote, holder)
        assert quantity.value == value
        assert quantities.verify_binding(quantity, holder) is None, excerpt
        binding = quantity.binding
        assert (
            excerpt[binding.number_start : binding.number_end]
            .lstrip("-−")
            .replace(".", "")
            .isdigit()
        )
        assert (
            excerpt[binding.expression_start : binding.expression_end]
            == binding.as_written
        )
        # The currency prefix stays outside the numeric span.
        assert "USD" not in excerpt[binding.number_start : binding.number_end]


def test_the_binding_records_are_immutable_and_never_shared():
    # C1 round 7, finding 2: a calculation's "preserved" input and a
    # derived claim's projection shared the parent's Quantity and the
    # producer's UnitExpr objects, so an in-place change rewrote the
    # comparison record too.
    holder = support.evidence("E1", "收入52亿元。")
    quantity = support.admitted(52, "亿元", "52亿元", holder)
    with pytest.raises(ValueError):
        quantity.value = 53
    with pytest.raises(ValueError):
        quantity.unit.atom = "USD"
    with pytest.raises(ValueError):
        quantity.binding.number_end = 0


def test_a_currency_prefix_is_adjacent_and_not_the_previous_figures():
    # C1 round 7, finding 3: the prefix rule skipped newlines and runs
    # of spaces, and never asked whether the currency had already
    # completed the previous figure.
    assert parse("Revenue: 100 million USD\n52", "52") == "no_unit"
    assert parse("Revenue: 100 million USD  52", "52") == "no_unit"
    assert parse("Revenue: 100 million USD 52", "52") == "no_unit"
    assert parse("Revenue: 100 USD 52", "52") == "no_unit"
    assert parse("Revenue: USD 52", "52") == ("USD", 52.0)
    assert parse("Revenue was 52 USD. USD 60 next", "60") == ("USD", 60.0)
    # ``人民币`` one space after a figure end is that figure's suffix.
    assert parse("人民币52亿元 人民币 60", "60") == "no_unit"
    assert parse("总额52亿元。人民币 60", "60") == ("CNY", 60.0)
    assert parse("总额52亿元人民币 60", "60") == "no_unit"


def test_late_occurrence_selection_is_linear():
    # C1 round 7, finding 4: every match rescanned every number.
    import time  # pylint: disable=import-outside-toplevel

    text = "52 EUR; " * 4000
    started = time.perf_counter()
    at = quantities.find_quote(text, "52 EUR", 4000)
    missing = quantities.find_quote(text, "52 EUR", 4001)
    assert time.perf_counter() - started < 0.3
    assert at == text.rindex("52 EUR")
    assert missing.code == "occurrence_out_of_range"


def test_orphan_cell_coordinates_are_refused():
    # C1 round 7, finding 5.
    holder = support.evidence("E1", "收入52亿元。")
    quantity = support.admitted(52, "亿元", "52亿元", holder)
    for field in ("cell_col", "header_col", "cell_row", "header_row"):
        mutated = quantity.model_copy(
            update={"binding": quantity.binding.model_copy(update={field: 99})}
        )
        assert quantities.verify_binding(mutated, holder) is not None, field
