"""Bounded quantity grammar: lexer, parser, renderer, evidence binding.

Every number in the registry passed through here once. ``admit`` takes
a researcher's ``QuantityDraft`` and the canonical ``Evidence`` it
names, locates the quoted number in the excerpt, parses the complete
quantity expression written there **without reading the proposed
unit**, compares the two structures, and returns an admitted
``Quantity`` with the exact ``EvidenceBinding`` that established it, or
a typed ``Refusal``. ``verify_binding`` re-runs that parse against a
stored binding at correction and load. ``render`` is the one spelling
of a ``UnitExpr`` and ``parse_unit(render(e)) == e`` for every valid
tree; nothing else in the program interprets unit text.

The grammar is closed and small on purpose: scalar quantities, explicit
scales, currencies and count units from a documented lexicon, percent
and percentage points, products, quotients, parentheses and integer
powers 2 and 3. Everything else -- ranges, paired figures, numeric
exponent notation, unresolved continuations, unknown words -- is refused
as a whole, never truncated to the part that would have matched.
"""

import dataclasses
import decimal
import hashlib
import re
import unicodedata

from industry import records

# --------------------------------------------------------------- lexicon

# Decimal exponents by scale word. ``m``/``b``/``k`` are magnitudes only
# in scale position beside a unit or after a currency prefix.
CJK_SCALES = {"万亿": 12, "百万": 6, "亿": 8, "万": 4, "千": 3}
LATIN_SCALES = {
    "trillion": 12,
    "trillions": 12,
    "tn": 12,
    "billion": 9,
    "billions": 9,
    "bn": 9,
    "b": 9,
    "million": 6,
    "millions": 6,
    "mn": 6,
    "m": 6,
    "thousand": 3,
    "thousands": 3,
    "k": 3,
}
_SHORT_SCALES = frozenset(("m", "b", "k"))
# The one spelling ``render`` uses per exponent.
SCALE_WORDS = {
    3: "thousand",
    4: "万",
    6: "million",
    8: "亿",
    9: "billion",
    12: "trillion",
}

# Currency spellings and the atom each establishes. A bare symbol is its
# own atom: ``$`` does not establish ``USD``.
CURRENCIES = {
    "USD": "USD",
    "US$": "USD",
    "美元": "USD",
    "CNY": "CNY",
    "RMB": "CNY",
    "人民币": "CNY",
    "EUR": "EUR",
    "€": "EUR",
    "欧元": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "英镑": "GBP",
    "JPY": "JPY",
    "日元": "JPY",
    "KRW": "KRW",
    "₩": "KRW",
    "韩元": "KRW",
    "HKD": "HKD",
    "HK$": "HKD",
    "港元": "HKD",
    "$": "$",
    "¥": "¥",
    "元": "元",
}
# Count and measure units: spelling -> canonical atom, or a tree for the
# aliases that are powers (``平方米`` is m²).
_UNIT_ATOMS = {
    # Chinese counts and measures
    "人": "人",
    "家": "家",
    "台": "台",
    "片": "片",
    "件": "件",
    "个": "个",
    "套": "套",
    "条": "条",
    "张": "张",
    "颗": "颗",
    "块": "块",
    "辆": "辆",
    "架": "架",
    "部": "部",
    "座": "座",
    "只": "只",
    "股": "股",
    "户": "户",
    "次": "次",
    "亩": "亩",
    "年": "年",
    "月": "月",
    "日": "日",
    "天": "天",
    "小时": "小时",
    "升": "升",
    "吨": "t",
    "克": "g",
    "千克": "kg",
    "公斤": "kg",
    "米": "m",
    "公里": "km",
    "千米": "km",
    # Latin counts and measures
    "people": "people",
    "person": "people",
    "employees": "people",
    "employee": "people",
    "units": "units",
    "unit": "units",
    "pcs": "pcs",
    "pieces": "pcs",
    "piece": "pcs",
    "sets": "sets",
    "set": "sets",
    "shares": "shares",
    "share": "shares",
    "wafers": "wafers",
    "wafer": "wafers",
    "masks": "masks",
    "mask": "masks",
    "t": "t",
    "tonnes": "t",
    "tonne": "t",
    "tons": "t",
    "ton": "t",
    "kg": "kg",
    "g": "g",
    "km": "km",
    "m": "m",
    "cm": "cm",
    "mm": "mm",
    "ha": "ha",
    "day": "day",
    "days": "day",
    "year": "year",
    "years": "year",
    "month": "month",
    "months": "month",
    "hour": "hour",
    "hours": "hour",
    "%": "%",
    "percent": "%",
    "pct": "%",
    "个百分点": "pp",
    "百分点": "pp",
    "pp": "pp",
    "ratio": "ratio",
}
_UNIT_POWERS = {"平方米": ("m", 2), "sqm": ("m", 2), "立方米": ("m", 3)}
# SI symbols are case-sensitive (T is not tonnes); words are not.
_CASE_SENSITIVE = frozenset(("t", "g", "m", "kg", "km", "cm", "mm", "ha", "pp"))


def _unit_spelling(text: str) -> str | None:
    """The lexicon spelling a Latin token names, honouring case rules."""
    if text in CURRENCIES:
        return text
    lowered = text.lower()
    if lowered in _UNIT_ATOMS or lowered in _UNIT_POWERS:
        if lowered in _CASE_SENSITIVE and text != lowered:
            return None
        return lowered
    return None


ATOMS = frozenset(_UNIT_ATOMS.values()) | frozenset(CURRENCIES.values())

# After a complete CJK unit, an adjoining character ends the expression
# only when it begins one of these; any other adjoining run is
# unresolved and refuses (``52元器件`` is not 52 元).
PROSE_CONTINUATION_WORDS = (
    "项目",
    "用于",
    "规模",
    "建设",
    "投资",
    "使用",
    "认缴",
    "认购",
    "左右",
    "增长",
    "增至",
    "增加",
    "以上",
    "以下",
    "以内",
    "大关",
    "上升",
    "下降",
    "同比",
    "环比",
)
PROSE_CONTINUATION_CHARS = frozenset(
    "的和及与或等为占之约是并即而也但则均分其共已将就仅该此从由向对在于时不无中"
)
_RANGE_CJK = ("至", "到")
_DASHES = "-~−–—‐‑－～"
# Only these read as a negative sign; the others are range connectors.
_SIGN_CHARS = "-−－"
_ELLIPSES = ("…", "...")
_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_OPERATORS = {"/": "divide", "*": "multiply", "·": "multiply", "×": "multiply"}


@dataclasses.dataclass(frozen=True)
class Refusal:
    """Why a text is not a quantity; ``code`` becomes the limitation."""

    code: str
    detail: str = ""


@dataclasses.dataclass(frozen=True)
class Token:
    """One lexical token with its offsets in the original text."""

    kind: str
    text: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class Parsed:
    """A complete quantity expression found in an excerpt."""

    value: float
    unit: records.UnitExpr
    number_start: int
    number_end: int
    expression_start: int
    expression_end: int
    cell: tuple[int, int] | None = None
    header_cell: tuple[int, int] | None = None


# ---------------------------------------------------------- constructors


def atom(name: str) -> records.UnitExpr:
    """The atom ``name`` (a canonical lexicon identifier)."""
    return records.UnitExpr(kind="atom", atom=name)


def scale10(exponent: int, expr: records.UnitExpr) -> records.UnitExpr:
    """``expr`` scaled by ten to ``exponent``."""
    return records.UnitExpr(kind="scale10", exponent=exponent, left=expr)


def multiply(
    left: records.UnitExpr, right: records.UnitExpr
) -> records.UnitExpr:
    """The product ``left * right``."""
    return records.UnitExpr(kind="multiply", left=left, right=right)


def divide(left: records.UnitExpr, right: records.UnitExpr) -> records.UnitExpr:
    """The quotient ``left / right``, operands kept whole."""
    return records.UnitExpr(kind="divide", left=left, right=right)


def power(base: records.UnitExpr, exponent: int) -> records.UnitExpr:
    """``base`` raised to ``exponent`` (2 or 3)."""
    return records.UnitExpr(kind="power", exponent=exponent, left=base)


def _unit_for(spelling: str) -> records.UnitExpr:
    if spelling in _UNIT_POWERS:
        base, exponent = _UNIT_POWERS[spelling]
        return power(atom(base), exponent)
    if spelling in _UNIT_ATOMS:
        return atom(_UNIT_ATOMS[spelling])
    return atom(CURRENCIES[spelling])


# ---------------------------------------------------------------- lexer


def fold(text: str) -> str:
    """Compatibility-normalize per character, keeping every offset.

    Only characters whose NFKC form is again one character are folded
    (full-width digits and punctuation, ``％``, ``（）``); the dash family
    becomes ``-``; superscript digits are kept as they are so a unit
    power never turns into a digit. ``len(fold(s)) == len(s)`` always.
    """
    out: list[str] = []
    for char in text:
        if char in _SUPERSCRIPTS:
            out.append(char)
        elif char in _DASHES:
            out.append("-")
        else:
            folded = unicodedata.normalize("NFKC", char)
            out.append(folded if len(folded) == 1 else char)
    return "".join(out)


def _is_cjk(char: str) -> bool:
    return "一" <= char <= "鿿"


def lex(text: str) -> list[Token]:
    """Lossless tokens over ``fold(text)`` with the original offsets.

    Kinds: ``number`` (digits with optional comma groups and decimal
    part; the grouping is validated by the parser), ``word`` (a Latin
    run, a currency symbol, ``%``), ``cjk`` (one CJK character), ``op``
    (``/ * · × ^``), ``sup`` (a superscript digit), ``paren``, ``dash``,
    ``space``, ``punct``. Nothing is dropped.
    """
    folded = fold(text)
    tokens: list[Token] = []
    i, n = 0, len(folded)
    while i < n:
        char = folded[i]
        if char in "0123456789":
            j = i + 1
            while j < n and (
                folded[j] in "0123456789,"
                or (
                    folded[j] == "."
                    and j + 1 < n
                    and folded[j + 1] in "0123456789"
                )
            ):
                if folded[j] == "," and not (
                    j + 1 < n and folded[j + 1] in "0123456789"
                ):
                    break
                j += 1
            tokens.append(Token("number", folded[i:j], i, j))
            i = j
        elif char.isspace():
            j = i + 1
            while j < n and folded[j].isspace():
                j += 1
            tokens.append(Token("space", folded[i:j], i, j))
            i = j
        elif folded.startswith(("US$", "HK$"), i):
            tokens.append(Token("word", folded[i : i + 3], i, i + 3))
            i += 3
        elif char in "$¥€£₩%":
            tokens.append(Token("word", char, i, i + 1))
            i += 1
        elif char.isascii() and char.isalpha():
            j = i + 1
            while j < n and folded[j].isascii() and folded[j].isalpha():
                j += 1
            tokens.append(Token("word", folded[i:j], i, j))
            i = j
        elif _is_cjk(char):
            tokens.append(Token("cjk", char, i, i + 1))
            i += 1
        elif char in "/*·×^":
            tokens.append(Token("op", char, i, i + 1))
            i += 1
        elif char in _SUPERSCRIPTS:
            tokens.append(Token("sup", char, i, i + 1))
            i += 1
        elif char in "()":
            tokens.append(Token("paren", char, i, i + 1))
            i += 1
        elif char == "-":
            tokens.append(Token("dash", char, i, i + 1))
            i += 1
        else:
            tokens.append(Token("punct", char, i, i + 1))
            i += 1
    return tokens


_NUMBER_FORM = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")


def _grouped(number: str) -> bool:
    """Whether a numeric token is one well-formed number.

    Comma groups are exactly three digits and there is at most one
    decimal point: ``2.2.1`` and ``2023.6.30`` are section numbers or
    dates, not numbers.
    """
    return _NUMBER_FORM.match(number) is not None


# --------------------------------------------------------------- parser


class _Parser:
    """Recursive descent over the tokens; one instance per text."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        # A currency prefix before the number completes a bare scale
        # (``$52 million``); once used, the tail is the whole unit.
        self.prefix: records.UnitExpr | None = None
        self.prefix_used = False

    @property
    def bare_scale_ok(self) -> bool:
        return self.prefix is not None and not self.prefix_used

    def complete_scale(self, exponent: int) -> records.UnitExpr:
        self.prefix_used = True
        return scale10(exponent, self.prefix)

    # -- helpers ------------------------------------------------------

    def tok(self, i: int) -> Token | None:
        return self.tokens[i] if 0 <= i < len(self.tokens) else None

    def skip_space(self, i: int) -> int:
        """Past one ordinary space (never a newline or a run of them)."""
        t = self.tok(i)
        if t and t.kind == "space" and t.text == " ":
            return i + 1
        return i

    def cjk_text(self, i: int, length: int) -> str | None:
        """The text of ``length`` consecutive CJK tokens from ``i``."""
        chars = []
        for k in range(i, i + length):
            t = self.tok(k)
            if t is None or t.kind != "cjk":
                return None
            chars.append(t.text)
        return "".join(chars)

    def cjk_match(self, i: int, table) -> tuple[str, int] | None:
        """Longest table entry spelled by the CJK tokens from ``i``."""
        longest = ""
        for spelling in table:
            if not _is_cjk(spelling[0]):
                continue
            if len(spelling) > len(longest) and (
                self.cjk_text(i, len(spelling)) == spelling
            ):
                longest = spelling
        if not longest:
            return None
        return longest, i + len(longest)

    def prose_continues(self, i: int) -> bool:
        """Whether the CJK run at ``i`` begins a documented continuation."""
        t = self.tok(i)
        if t is None or t.kind != "cjk":
            return True
        if t.text in PROSE_CONTINUATION_CHARS:
            return True
        return any(
            self.cjk_text(i, len(w)) == w for w in PROSE_CONTINUATION_WORDS
        )

    # -- grammar ------------------------------------------------------

    def unit_tail(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        """``ws? expr`` from ``i``: (unit, end index, refusal)."""
        j = self.skip_space(i)
        unit, end, refusal = self.expr(j)
        if refusal is not None:
            return None, i, refusal
        if unit is None:
            return None, i, None
        return unit, end, None

    def expr(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        left, end, refusal = self.term(i)
        if refusal is not None or left is None:
            return left, end, refusal
        while True:
            j = self.skip_space(end)
            t = self.tok(j)
            is_op = t is not None and (
                (t.kind == "op" and t.text in _OPERATORS)
                or (t.kind == "word" and t.text.lower() == "per")
            )
            if not is_op:
                return left, end, None
            spaced = j != end
            kind = "divide" if t.kind == "word" else _OPERATORS[t.text]
            k = self.skip_space(j + 1)
            nxt = self.tok(k)
            if nxt is not None and nxt.kind == "number":
                return (
                    None,
                    i,
                    Refusal(
                        "unsupported_number_form",
                        "operator followed by a number",
                    ),
                )
            opens_group = (
                nxt is not None and nxt.kind == "paren" and nxt.text == "("
            )
            if not opens_group and (
                nxt is None or nxt.kind in ("punct", "paren", "space")
            ):
                if spaced:
                    return left, end, None
                return (
                    None,
                    i,
                    Refusal(
                        "ambiguous_continuation",
                        f"operator {t.text} without operand",
                    ),
                )
            right, after, refusal = self.term(k)
            if refusal is not None:
                return None, i, refusal
            if right is None:
                return (
                    None,
                    i,
                    Refusal(
                        "ambiguous_continuation",
                        f"operator {t.text} then {nxt.text!r}",
                    ),
                )
            left = (
                divide(left, right)
                if kind == "divide"
                else multiply(left, right)
            )
            end = after

    def term(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        t = self.tok(i)
        if t is None:
            return None, i, None
        if t.kind == "paren" and t.text == "(":
            return self.group(i)
        if t.kind == "word":
            lowered = t.text.lower()
            if lowered in LATIN_SCALES:
                return self.latin_scaled(i)
            return self.latin_unit(i)
        if t.kind == "cjk":
            scale = self.cjk_match(i, CJK_SCALES)
            if scale is not None:
                return self.cjk_scaled(i, scale)
            return self.cjk_unit(i, None)
        return None, i, None

    def group(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        inner, end, refusal = self.expr(i + 1)
        if refusal is not None:
            return None, i, refusal
        if inner is None:
            return None, i, None
        j = self.skip_space(end)
        close = self.tok(j)
        if close is None or close.text != ")":
            return (
                None,
                i,
                Refusal("ambiguous_continuation", "unbalanced group"),
            )
        return self.powered(inner, j + 1)

    def powered(
        self, base: records.UnitExpr, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        t = self.tok(i)
        if t is not None and t.kind == "sup":
            if t.text not in "²³":
                return None, i, Refusal("unsupported_unit_power", t.text)
            return power(base, 2 if t.text == "²" else 3), i + 1, None
        if t is not None and t.kind == "op" and t.text == "^":
            n = self.tok(i + 1)
            if n is not None and n.kind == "number" and n.text in ("2", "3"):
                return power(base, int(n.text)), i + 2, None
            return None, i, Refusal("unsupported_unit_power", "^")
        return base, i, None

    def latin_scaled(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        """A Latin scale word, then a unit, a group, or (with a currency
        prefix) nothing."""
        t = self.tok(i)
        exponent = LATIN_SCALES[t.text.lower()]
        j = self.skip_space(i + 1)
        nxt = self.tok(j)
        if nxt is not None and nxt.kind == "paren" and nxt.text == "(":
            inner, end, refusal = self.group(j)
            if refusal is not None or inner is None:
                return None, i, refusal
            return scale10(exponent, inner), end, None
        if t.text.lower() in _SHORT_SCALES and not self.bare_scale_ok:
            # ``52 m`` is metres unless a unit follows (``52m USD``).
            unit, end, refusal = self.unit_after_scale(j)
            if refusal is not None:
                return None, i, refusal
            if unit is None:
                return self.latin_unit(i)
            return scale10(exponent, unit), end, None
        unit, end, refusal = self.unit_after_scale(j)
        if refusal is not None:
            return None, i, refusal
        if unit is None:
            if self.bare_scale_ok:
                return self.complete_scale(exponent), i + 1, None
            return None, i, Refusal("no_unit", f"scale {t.text} without a unit")
        return scale10(exponent, unit), end, None

    def unit_after_scale(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        t = self.tok(i)
        if t is None:
            return None, i, None
        if t.kind == "word" and t.text.lower() not in LATIN_SCALES:
            return self.latin_unit(i)
        if t.kind == "cjk":
            if self.cjk_match(i, CJK_SCALES) is not None:
                return None, i, Refusal("ambiguous_continuation", "two scales")
            return self.cjk_unit(i, None)
        return None, i, None

    def latin_unit(
        self, i: int
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        t = self.tok(i)
        spelling = _unit_spelling(t.text)
        if spelling is None:
            return None, i, None
        base, end, refusal = self.powered(_unit_for(spelling), i + 1)
        if refusal is not None:
            return None, i, refusal
        glued = self.tok(end)
        if glued is not None and glued.kind == "word":
            return None, i, Refusal("attached_continuation", glued.text)
        # postfix scale: ``USD million``
        j = self.skip_space(end)
        nxt = self.tok(j)
        if (
            nxt is not None
            and nxt.kind == "word"
            and nxt.text.lower() in LATIN_SCALES
            and nxt.text.lower() not in _SHORT_SCALES
        ):
            return scale10(LATIN_SCALES[nxt.text.lower()], base), j + 1, None
        return base, end, None

    def cjk_scaled(
        self, i: int, scale: tuple[str, int]
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        spelling, j = scale
        exponent = CJK_SCALES[spelling]
        nxt = self.tok(j)
        if nxt is not None and nxt.kind == "cjk":
            unit, end, refusal = self.cjk_unit(j, exponent)
            if refusal is not None:
                return None, i, refusal
            if unit is not None:
                return unit, end, None
            if self.bare_scale_ok and self.prose_continues(j):
                return self.complete_scale(exponent), j, None
            return (
                None,
                i,
                Refusal("no_unit", f"scale {spelling} then {nxt.text!r}"),
            )
        k = self.skip_space(j)
        after = self.tok(k)
        if after is not None and after.kind == "cjk" and k != j:
            # ``万 元``: one space inside the unit from HTML joining.
            if self.cjk_match(k, CJK_SCALES) is None:
                unit, end, refusal = self.cjk_unit(k, exponent)
                if refusal is not None:
                    return None, i, refusal
                if unit is not None:
                    return unit, end, None
        if after is not None and after.kind == "word":
            unit, end, refusal = self.latin_unit(k)
            if refusal is not None:
                return None, i, refusal
            if unit is not None and unit.kind != "scale10":
                return scale10(exponent, unit), end, None
        if after is not None and after.kind == "paren" and after.text == "(":
            inner, end, refusal = self.group(k)
            if refusal is not None or inner is None:
                return None, i, refusal
            return scale10(exponent, inner), end, None
        if self.bare_scale_ok:
            return self.complete_scale(exponent), j, None
        return None, i, Refusal("no_unit", f"bare scale {spelling}")

    def cjk_unit(
        self, i: int, exponent: int | None
    ) -> tuple[records.UnitExpr | None, int, Refusal | None]:
        """A CJK unit word at ``i`` (currency, count, measure), scaled by
        ``exponent`` when given, followed by a boundary or a documented
        prose continuation."""
        match = self.cjk_match(i, CURRENCIES) or self.cjk_match(
            i, {**_UNIT_ATOMS, **_UNIT_POWERS}
        )
        if match is None:
            return None, i, None
        spelling, end = match
        base = _unit_for(spelling)
        # ``52亿元人民币``: the enumerated CNY form.
        suffix = self.cjk_match(end, {"人民币": "CNY"})
        if suffix is not None:
            if base.atom == "元":
                base = atom("CNY")
                end = suffix[1]
            else:
                return (
                    None,
                    i,
                    Refusal("prefix_tail_conflict", "two currencies"),
                )
        base, end, refusal = self.powered(base, end)
        if refusal is not None:
            return None, i, refusal
        nxt = self.tok(end)
        if (
            nxt is not None
            and nxt.kind == "cjk"
            and not self.prose_continues(end)
        ):
            return (
                None,
                i,
                Refusal("ambiguous_continuation", spelling + nxt.text),
            )
        if nxt is not None and nxt.kind == "word":
            lowered = nxt.text.lower()
            if lowered in LATIN_SCALES and lowered not in _SHORT_SCALES:
                if exponent is not None:
                    return (
                        None,
                        i,
                        Refusal("ambiguous_continuation", "two scales"),
                    )
                return scale10(LATIN_SCALES[lowered], base), end + 1, None
            return None, i, Refusal("attached_continuation", nxt.text)
        unit = scale10(exponent, base) if exponent is not None else base
        # postfix Latin scale after a space: ``元 million``
        j = self.skip_space(end)
        after = self.tok(j)
        if (
            exponent is None
            and after is not None
            and after.kind == "word"
            and after.text.lower() in LATIN_SCALES
            and after.text.lower() not in _SHORT_SCALES
        ):
            return scale10(LATIN_SCALES[after.text.lower()], base), j + 1, None
        return unit, end, None


def parse_unit(text: str) -> records.UnitExpr | Refusal:
    """Parse a proposed unit text; the whole text must be consumed.

    The spellings are the evidence spellings: ``亿元``, ``USD million``,
    ``%``, ``USD/kg``, ``万元/年``, and the explicit CNY forms
    ``人民币万元`` / ``万元人民币`` (a currency prefix before a ``元``
    denomination establishes CNY exactly as it does in evidence).
    """
    stripped = text.strip()
    if not stripped:
        return Refusal("no_unit", "empty")
    plain = _parse_whole(stripped, None)
    if not isinstance(plain, Refusal):
        return plain
    tokens = lex(stripped)
    parser = _Parser(tokens)
    if tokens and tokens[0].kind == "word" and tokens[0].text in CURRENCIES:
        prefixed = _parse_whole(
            stripped, atom(CURRENCIES[tokens[0].text]), parser.skip_space(1)
        )
    elif parser.cjk_text(0, 3) == "人民币":
        prefixed = _parse_whole(stripped, atom("CNY"), parser.skip_space(3))
    else:
        return plain
    return prefixed if not isinstance(prefixed, Refusal) else plain


def _parse_whole(
    text: str, prefix: records.UnitExpr | None, start: int = 0
) -> records.UnitExpr | Refusal:
    parser = _Parser(lex(text))
    parser.prefix = prefix
    tokens = parser.tokens
    unit, end, refusal = parser.expr(start)
    if refusal is not None:
        return refusal
    if unit is None and prefix is not None and start == len(tokens):
        return prefix
    if unit is None:
        return Refusal("no_unit", text)
    if end != len(tokens):
        return Refusal("ambiguous_continuation", text[tokens[end].start :])
    if prefix is None or parser.prefix_used:
        return unit
    merged = _merge_prefix(prefix, unit)
    if merged is None:
        return Refusal("prefix_tail_conflict", text)
    return merged


def _merge_prefix(prefix: records.UnitExpr, tail) -> records.UnitExpr | None:
    """The unit a currency prefix and a tail establish together."""
    if tail is None:
        return prefix
    if tail == prefix:
        return tail
    if prefix.atom == "CNY" and tail.kind == "atom" and tail.atom == "元":
        return atom("CNY")
    if (
        prefix.atom == "CNY"
        and tail.kind == "scale10"
        and tail.left is not None
        and tail.left == atom("元")
    ):
        return scale10(tail.exponent, atom("CNY"))
    return None


def _number_value(token: Token, sign: str) -> float:
    return float(decimal.Decimal(sign + token.text.replace(",", "")))


def _is_ellipsis(text: str, token: Token) -> bool:
    """Whether a punctuation token is (part of) an ellipsis."""
    if token.text == "…":
        return True
    window = text[max(0, token.start - 2) : token.end + 2]
    return token.text == "." and window.count(".") >= 3


def _plain(number: Token, max_digits: int) -> bool:
    return number.text.isdigit() and 1 <= len(number.text) <= max_digits


def _spaced_grouping(tokens: list[Token], idx: int) -> bool:
    """Whether the number at ``idx`` is part of a ``1 234`` grouping."""

    def percent_follows(k: int) -> bool:
        j = k + 1
        if j < len(tokens) and tokens[j].kind == "space":
            j += 1
        return (
            j < len(tokens)
            and tokens[j].kind == "word"
            and tokens[j].text == "%"
        )

    def pair(left: int, right: int) -> bool:
        return (
            tokens[left].kind == "number"
            and tokens[right].kind == "number"
            and tokens[left + 1].kind == "space"
            and tokens[left + 1].text == " "
            and _plain(tokens[left], 3)
            and _plain(tokens[right], 3)
            and len(tokens[right].text) == 3
            and not percent_follows(right)
        )

    if idx >= 2 and pair(idx - 2, idx):
        return True
    return idx + 2 < len(tokens) and pair(idx, idx + 2)


def _completes_previous_figure(parser: _Parser, i: int) -> bool:
    """Whether the currency at ``i`` belongs to the figure before it.

    ``100 million USD 52``: the ``USD`` completes ``100 million`` and
    cannot also prefix ``52``. A figure end (a number, a scale, a unit
    or a percent) at most one plain space before the currency claims
    it; punctuation, a newline or an ordinary word leaves it free.
    """
    j = i - 1
    t = parser.tok(j)
    if t is not None and t.kind == "space" and t.text == " ":
        j -= 1
    return _figure_end(parser, j)


def _figure_end(parser: _Parser, i: int) -> bool:
    """Whether the token at ``i`` ends a figure (number, unit, ``%``)."""
    t = parser.tok(i)
    if t is None:
        return False
    if t.kind == "number":
        return True
    if t.kind == "word":
        return (
            t.text.lower() in LATIN_SCALES or _unit_spelling(t.text) is not None
        )
    if t.kind == "cjk":
        # <number> <scale>? <unit> ending exactly here.
        for length in (3, 2, 1):
            spelling = parser.cjk_text(i - length + 1, length)
            if spelling is None or not (
                spelling in CURRENCIES
                or spelling in _UNIT_ATOMS
                or spelling in _UNIT_POWERS
            ):
                continue
            k = i - length
            for scale_length in (2, 1, 0):
                if (
                    scale_length
                    and parser.cjk_text(k - scale_length + 1, scale_length)
                    not in CJK_SCALES
                ):
                    continue
                j = k - scale_length
                if parser.tok(j) is not None and parser.tok(j).kind == "space":
                    j -= 1
                before = parser.tok(j)
                if before is not None and before.kind == "number":
                    return True
    return False


_PATTERN_WORDS = frozenset(("to", "per"))
_CUT_ALWAYS = "。;；!！?？:：、"
_CUT_CONDITIONAL = ",.，．"
_GROUP_OPEN = "(（[【"
_GROUP_CLOSE = ")）]】"


def certified_cuts(text: str) -> list[int]:
    """Offsets after which prose may be cut without harming any quantity.

    Shared by the chunker (``snapshots.chunk_blocks`` packs exact spans
    between these offsets) and by admission (an occurrence is isolated
    from an unknown gap only by one of them). A certified delimiter
    stops every rule of the grammar: sentence punctuation always; a
    comma or full stop only when neither neighbour is a digit and the
    stop is not part of a dot run; never inside a bracketed group. The
    delimiter stays with the text before the cut.
    """
    cuts: list[int] = []
    depth = 0
    n = len(text)
    for i, char in enumerate(text):
        if char in _GROUP_OPEN:
            depth += 1
            continue
        if char in _GROUP_CLOSE:
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        if char in _CUT_ALWAYS:
            cuts.append(i + 1)
        elif char in _CUT_CONDITIONAL:
            before = text[i - 1] if i > 0 else ""
            after = text[i + 1] if i + 1 < n else ""
            if before.isdigit() or after.isdigit():
                continue
            if char in ".．" and (
                (before and before in ".．") or (after and after in ".．")
            ):
                continue
            cuts.append(i + 1)
    return cuts


def pack_spans(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Exact source slices ``[start, end)`` covering ``text`` in order.

    The chunker's contract (plan revision 22 §4.28): each chunk ends at
    the rightmost certified cut within ``size`` of its start, else at
    the first certified cut beyond it, else at the end of the text --
    never at an arbitrary character, so no chunk ever holds part of a
    quantity expression without the rest. A chunk always adds at least
    one span beyond the previous chunk's end. The next chunk starts at
    the certified cut nearest ``end - overlap`` that leaves its first
    new span within ``size`` when any does (ties toward more preceding
    context), else at ``end`` with no overlap. Slices are never trimmed
    or re-normalized, so every offset is an offset in ``text``.
    """
    n = len(text)
    if n == 0:
        return []
    cuts = certified_cuts(text)
    chunks: list[tuple[int, int]] = []
    start = 0
    previous_end = 0
    while True:
        if n - start <= size:
            end = n
        else:
            later = [c for c in cuts if c > start and c > previous_end]
            within = [c for c in later if c - start <= size]
            if within:
                end = within[-1]
            elif later:
                end = later[0]
            else:
                end = n
        chunks.append((start, end))
        previous_end = end
        if end >= n:
            return chunks
        beyond = [c for c in cuts if c > end]
        next_span_end = beyond[0] if beyond else n
        candidates = [c for c in cuts if start < c <= end]
        target = end - overlap
        fitting = [c for c in candidates if next_span_end - c <= size]
        pool = fitting or candidates
        nxt = min(pool, key=lambda c: (abs(c - target), c)) if pool else end
        start = nxt if nxt > start else end


def _isolated(text: str, lo: int, hi: int) -> bool:
    """Whether a certified delimiter ends inside ``(lo, hi]`` of the text.

    Computed over the whole text: a delimiter's neighbours decide
    whether it certifies, so the text must not be truncated first.
    """
    return any(lo < cut <= hi for cut in certified_cuts(text))


def parse_expression(
    text: str,
    number_start: int,
    layout: records.TableLayout | None = None,
    gap_start: bool = False,
    gap_end: bool = False,
) -> Parsed | Refusal:
    """The complete quantity expression whose number starts at an offset.

    Independent of any proposal: the expression is the number, an
    optional currency prefix immediately before it, and the unit text
    the grammar can attach after it, ended by a boundary. A range, a
    paired figure, a glued word, an unresolved continuation or a number
    inside a larger numeric expression refuses the whole thing.

    With a table ``layout``, the number must lie in one cell; a bare
    cell may inherit one header declaration (see ``_table_unit``).
    ``gap_start``/``gap_end`` say that the excerpt's edges are unknown
    gaps (a PDF page edge, a search-snippet edge): an occurrence not
    separated from such an edge, or from an ellipsis, by a certified
    delimiter is refused. Internal chunk boundaries are certified by
    construction (``certified_cuts``) and carry no gap.
    """
    parser = _Parser(lex(text))
    tokens = parser.tokens
    idx = next(
        (
            k
            for k, t in enumerate(tokens)
            if t.kind == "number" and t.start == number_start
        ),
        None,
    )
    if idx is None and text[number_start : number_start + 1] in tuple(
        _SIGN_CHARS
    ):
        # A stored binding anchors a signed figure at its sign.
        idx = next(
            (
                k
                for k, t in enumerate(tokens)
                if t.kind == "number" and t.start == number_start + 1
            ),
            None,
        )
    if idx is None:
        return Refusal("quote_not_a_token", str(number_start))
    number = tokens[idx]
    if not _grouped(number.text):
        return Refusal("unsupported_number_form", number.text)
    # A number glued to a preceding decimal point is not complete
    # (``.52`` is 0.52 or a sentence end without a space).
    if number.start > 0 and text[number.start - 1] in ".．":
        return Refusal("unsupported_number_form", "number after a point")
    # ``1 234``: a plain 1-3 digit number, one space, and a three-digit
    # group may be a space-separated thousands grouping (French style);
    # neither number is complete then. A percent takes no grouping, so
    # ``224 282 %`` in a table row stays two figures.
    if _spaced_grouping(tokens, idx):
        return Refusal("unsupported_number_form", "space-separated groups")
    # -- left side: sign, currency prefix, range and paired figures.
    sign = ""
    start = number.start
    k = idx - 1
    before = parser.tok(k)
    if before is not None and before.kind == "dash":
        left_of_dash = parser.tok(k - 1)
        if left_of_dash is not None and _figure_end(parser, k - 1):
            return Refusal("range", "dash between two figures")
        signable = text[before.start] in _SIGN_CHARS and (
            left_of_dash is None
            or left_of_dash.kind in ("space", "paren", "punct", "cjk")
        )
        if not signable:
            return Refusal("range", "a dash that is not a sign")
        sign, start, k = "-", before.start, k - 1
    number_span_start = start
    kk = k
    # A prefix sits at most one plain space before the figure.
    if (
        parser.tok(kk) is not None
        and parser.tok(kk).kind == "space"
        and parser.tok(kk).text == " "
    ):
        kk -= 1
    b = parser.tok(kk)
    prefix: records.UnitExpr | None = None
    if b is not None:
        prev_i = kk - 1
        if (
            parser.tok(prev_i) is not None
            and parser.tok(prev_i).kind == "space"
        ):
            prev_i -= 1
        prev = parser.tok(prev_i)
        if b.kind == "dash":
            attached_left = kk - 1 >= 0 and tokens[kk - 1].kind != "space"
            if attached_left and _figure_end(parser, kk - 1) and not sign:
                return Refusal("range", "dash attached to the previous figure")
            if (
                not attached_left
                and kk < k
                and prev is not None
                and _figure_end(parser, prev_i)
            ):
                return Refusal("range", "dash between two figures")
        elif b.kind == "cjk" and b.text in _RANGE_CJK:
            if prev is not None and (
                prev.kind == "number" or _figure_end(parser, prev_i)
            ):
                return Refusal("range", "至/到 between figures")
        elif b.kind == "word" and b.text == "to":
            if prev is not None and (
                prev.kind == "number" or _figure_end(parser, prev_i)
            ):
                return Refusal("range", "to between figures")
        elif b.kind == "op" and b.text in "/×*":
            if kk == k or (prev is not None and prev.kind == "number"):
                return Refusal("unsupported_number_form", "paired figures")
        if (
            b.kind == "word"
            and b.text in CURRENCIES
            and kk >= k - 1
            and not _completes_previous_figure(parser, kk)
        ):
            prefix = atom(CURRENCIES[b.text])
            start = b.start
            if prev is not None and prev.kind == "word" and prev.text == "to":
                t3 = parser.tok(prev_i - 1)
                if t3 is not None and t3.kind == "space":
                    t3 = parser.tok(prev_i - 2)
                if t3 is not None and _figure_end(parser, tokens.index(t3)):
                    return Refusal("range", "to between figures")
        elif b.kind == "cjk" and kk >= k - 1:
            cny = parser.cjk_text(kk - 2, 3)
            if cny == "人民币" and not _completes_previous_figure(
                parser, kk - 2
            ):
                prefix = atom("CNY")
                start = tokens[kk - 2].start
    # -- right side: the unit expression.
    parser.prefix = prefix
    tail, end, refusal = parser.unit_tail(idx + 1)
    if refusal is not None:
        return refusal
    unit: records.UnitExpr | None
    if tail is None:
        end = idx + 1
    if prefix is None or parser.prefix_used:
        unit = tail
    else:
        unit = _merge_prefix(prefix, tail)
        if unit is None:
            return Refusal(
                "prefix_tail_conflict", f"{render(prefix)} vs {render(tail)}"
            )
    # -- boundary after the expression.
    j = end
    nxt = parser.tok(j)
    if nxt is not None and nxt.kind == "space" and nxt.text == " ":
        j += 1
        nxt = parser.tok(j)
    if nxt is not None:
        if nxt.kind == "word" and j == end:
            return Refusal("attached_continuation", nxt.text)
        # A unit word the grammar could not attach is unresolved
        # (``52 USD kg``), unless the unit is a percent, which takes no
        # denomination (``36.3% year-to-date`` ends at the percent).
        extendable = unit is not None and unit not in (atom("%"), atom("pp"))
        if (
            nxt.kind == "word"
            and j > end
            and extendable
            and (
                _unit_spelling(nxt.text) is not None
                or nxt.text.lower() in LATIN_SCALES
                or nxt.text.lower() in _PATTERN_WORDS
            )
        ):
            return Refusal("ambiguous_continuation", nxt.text)
        if nxt.kind == "sup":
            return Refusal("unsupported_number_form", nxt.text)
        if (
            nxt.kind == "op"
            and nxt.text in "×*/"
            and (j == end or tail is None)
        ):
            after = parser.tok(parser.skip_space(j + 1))
            if after is not None and after.kind == "number":
                return Refusal(
                    "unsupported_number_form", f"{nxt.text} then a number"
                )
        connector = (
            nxt.kind == "dash"
            or (nxt.kind == "cjk" and nxt.text in _RANGE_CJK)
            or (nxt.kind == "word" and nxt.text == "to")
        )
        if connector:
            m = parser.skip_space(j + 1)
            after = parser.tok(m)
            if (
                after is not None
                and after.kind == "word"
                and after.text in CURRENCIES
            ):
                after = parser.tok(parser.skip_space(m + 1))
            detached = nxt.kind == "dash" and j > end
            spaced_both = detached and m > j + 1
            if (
                after is not None
                and after.kind == "number"
                and (not detached or spaced_both)
            ):
                return Refusal("range", "figure after a connector")
    expression_end = tokens[end - 1].end if end > idx else number.end
    # One external-gap policy: an unknown edge or an ellipsis on either
    # side must be separated from the expression by a certified
    # delimiter, else the missing text could complete or contradict it.
    gap_before = 0 if gap_start else None
    for t in tokens:
        if t.kind == "punct" and t.end <= start and _is_ellipsis(text, t):
            gap_before = max(gap_before or 0, t.end)
    gap_after = len(text) if gap_end else None
    for t in tokens:
        if (
            t.kind == "punct"
            and t.start >= expression_end
            and _is_ellipsis(text, t)
        ):
            gap_after = min(
                gap_after if gap_after is not None else len(text), t.start
            )
    if gap_before is not None and not _isolated(text, gap_before, start):
        return Refusal("cut_edge", "an unknown gap before the figure")
    if gap_after is not None and not _isolated(text, expression_end, gap_after):
        return Refusal("cut_edge", "an unknown gap after the expression")
    spans = (number_span_start, number.end, start, expression_end)
    value = _number_value(number, sign)
    if layout is not None:
        return _table_unit(text, layout, value, unit, spans)
    if unit is None:
        return Refusal("no_unit", "")
    return Parsed(value, unit, *spans)


# ---------------------------------------------------------------- tables


def parse_declaration(text: str) -> records.UnitExpr | Refusal:
    """The one unit a header cell declares, or a refusal.

    The whole cell is a unit (``万元``), or it holds exactly one
    parenthesised group (``Revenue (USD million)``) or one ``单位：`` /
    ``Unit:`` clause whose content is a unit. Anything else declares
    nothing.
    """
    stripped = fold(text).strip()
    direct = parse_unit(stripped)
    if not isinstance(direct, Refusal):
        return direct
    groups = [
        stripped[i + 1 : stripped.index(")", i)]
        for i, char in enumerate(stripped)
        if char == "(" and ")" in stripped[i:]
    ]
    for marker in ("单位:", "单位：", "Unit:", "unit:"):
        if marker in stripped:
            groups.append(stripped.split(marker, 1)[1].strip(" ）)"))
    units = [
        g for g in (parse_unit(g) for g in groups) if not isinstance(g, Refusal)
    ]
    if len(units) == 1:
        return units[0]
    return Refusal("table_unit_unresolved", stripped[:40])


def _cell_at(
    layout: records.TableLayout, offset: int
) -> records.TableCell | None:
    for cell in layout.cells:
        if cell.start <= offset < cell.end:
            return cell
    return None


def _table_unit(
    text: str,
    layout: records.TableLayout,
    value: float,
    unit: records.UnitExpr | None,
    spans: tuple[int, int, int, int],
) -> Parsed | Refusal:
    """Bind a parsed number to its own cell; a bare cell may inherit.

    The cell is resolved first. A complete inline expression binds to
    its cell (and must not contradict a single leading header's
    declaration); a bare cell -- the number and nothing else -- may
    inherit the one declaration of its column's header when the layout
    is rectangular, unflagged and has exactly one leading header row.
    A malformed inline expression is never rescued by a header.
    """
    number_start, number_end, expression_start, expression_end = spans
    cell = _cell_at(layout, number_start)
    if cell is None:
        return Refusal("table_cell_unresolved", str(number_start))
    if expression_end > cell.end or expression_start < cell.start:
        return Refusal("table_cell_unresolved", "expression crosses a cell")
    header = None
    if layout.header_rows == 1 and not layout.limitations:
        header = next(
            (
                c
                for c in layout.cells
                if c.row == 0 and c.col == cell.col and c.header
            ),
            None,
        )
    declared = parse_declaration(header.text) if header is not None else None
    if unit is not None:
        if (
            declared is not None
            and not isinstance(declared, Refusal)
            and declared != unit
        ):
            return Refusal("conflicts_with_header", render(declared))
        return Parsed(value, unit, *spans, cell=(cell.row, cell.col))
    bare = fold(cell.text).strip() == fold(text)[number_start:number_end]
    if not bare:
        return Refusal("no_unit", "")
    if header is None or declared is None or isinstance(declared, Refusal):
        return Refusal("table_unit_unresolved", cell.text[:40])
    return Parsed(
        value,
        declared,
        *spans,
        cell=(cell.row, cell.col),
        header_cell=(header.row, header.col),
    )


# -------------------------------------------------------------- renderer


def _simple(expr: records.UnitExpr) -> bool:
    return expr.kind == "atom" or (
        expr.kind == "power" and expr.left.kind == "atom"
    )


def render(expr: records.UnitExpr) -> str:
    """The one canonical spelling of a unit tree (``parse_unit`` inverts it)."""
    if expr.kind == "atom":
        return expr.atom
    if expr.kind == "power":
        base = render(expr.left)
        if expr.left.kind != "atom":
            base = f"({base})"
        return base + ("²" if expr.exponent == 2 else "³")
    if expr.kind == "scale10":
        word = SCALE_WORDS[expr.exponent]
        inner = render(expr.left)
        if not _simple(expr.left):
            return f"{word} ({inner})"
        if expr.exponent in (4, 8):
            return f"{word}{inner}"
        return f"{inner} {word}"
    left = render(expr.left)
    right = render(expr.right)
    compound_right = not _simple(expr.right) and not (
        expr.right.kind == "scale10" and _simple(expr.right.left)
    )
    if expr.kind == "divide":
        if expr.left.kind == "multiply":
            left = f"({left})"
        if compound_right:
            right = f"({right})"
        return f"{left}/{right}"
    compound_left = not _simple(expr.left) and not (
        expr.left.kind in ("scale10", "multiply")
        and (expr.left.kind == "multiply" or _simple(expr.left.left))
    )
    if compound_left:
        left = f"({left})"
    if compound_right:
        right = f"({right})"
    return f"{left}*{right}"


# ------------------------------------------------------------- admission


def _gap(evidence: records.Evidence, side: str) -> bool:
    """Whether the excerpt's edge on ``side`` is an unknown gap.

    A search snippet is cut on both sides by a third party; a PDF page
    block carries ``page_cut_start``/``page_cut_end`` from extraction.
    Internal chunk boundaries of extraction v3 are certified and carry
    no flag; a v2 excerpt is not made safe by lacking one.
    """
    if evidence.kind == "snippet":
        return True
    return f"page_cut_{side}" in evidence.limitations


def excerpt_hash(excerpt: str) -> str:
    """The exact hash a binding pins its excerpt with."""
    return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()


def _quote_pattern(quote: str) -> "re.Pattern[str] | None":
    """A pattern for the quote that tolerates whitespace differences."""
    parts = [re.escape(char) for char in fold(quote) if not char.isspace()]
    if not parts:
        return None
    return re.compile(r"\s*".join(parts))


def find_quote(excerpt: str, quote: str, occurrence: int) -> int | Refusal:
    """The start of the one numeric token the chosen quote covers whole.

    Occurrences are counted over matches that cover exactly one complete
    numeric token (a match inside ``152`` does not count), so the
    researcher's ``occurrence`` means what a reader means by it. The
    match tolerates whitespace differences; everything else is exact.
    """
    pattern = _quote_pattern(quote)
    if pattern is None or occurrence < 1:
        return Refusal("quote_not_a_token", quote)
    folded = fold(excerpt)
    numbers = [t for t in lex(excerpt) if t.kind == "number"]
    found = 0
    cursor = 0
    for match in pattern.finditer(folded):
        # Numbers and matches are both in text order: advance a cursor
        # instead of rescanning every number for every match.
        while cursor < len(numbers) and numbers[cursor].end <= match.start():
            cursor += 1
        inside = []
        probe = cursor
        while probe < len(numbers) and numbers[probe].start < match.end():
            inside.append(numbers[probe])
            probe += 1
        if len(inside) != 1:
            continue
        number = inside[0]
        if number.start < match.start() or number.end > match.end():
            continue
        found += 1
        if found == occurrence:
            return number.start
    if found == 0:
        return Refusal("not_in_excerpt", quote)
    return Refusal("occurrence_out_of_range", f"{quote} x{occurrence}")


def admit(
    draft: records.QuantityDraft, evidence: records.Evidence, evidence_id: str
) -> records.Quantity | Refusal:
    """Admit a draft against the canonical evidence it names.

    Args:
      draft: The researcher's quantity.
      evidence: The canonical registry record the draft's label mapped
        to (its excerpt and table layout are what is parsed).
      evidence_id: Its canonical id, written into the binding.

    Returns:
      An admitted ``Quantity`` with its binding, or a ``Refusal`` whose
      code is the limitation to record.
    """
    number_start = find_quote(evidence.excerpt, draft.quote, draft.occurrence)
    if isinstance(number_start, Refusal):
        return number_start
    parsed = parse_expression(
        evidence.excerpt,
        number_start,
        evidence.table,
        gap_start=_gap(evidence, "start"),
        gap_end=_gap(evidence, "end"),
    )
    if isinstance(parsed, Refusal):
        return parsed
    proposed = parse_unit(draft.unit_text)
    if isinstance(proposed, Refusal):
        return Refusal("unit_text_unparsed", draft.unit_text)
    if proposed != parsed.unit:
        return Refusal(
            "unit_mismatch",
            f"{render(proposed)} proposed, {render(parsed.unit)} written",
        )
    if parsed.value != draft.value:
        return Refusal("value_mismatch", f"{draft.value} vs {parsed.value}")
    binding = records.EvidenceBinding(
        evidence_id=evidence_id,
        excerpt_sha256=excerpt_hash(evidence.excerpt),
        number_start=parsed.number_start,
        number_end=parsed.number_end,
        expression_start=parsed.expression_start,
        expression_end=parsed.expression_end,
        as_written=evidence.excerpt[
            parsed.expression_start : parsed.expression_end
        ],
        cell_row=parsed.cell[0] if parsed.cell else None,
        cell_col=parsed.cell[1] if parsed.cell else None,
        header_row=parsed.header_cell[0] if parsed.header_cell else None,
        header_col=parsed.header_cell[1] if parsed.header_cell else None,
    )
    return records.Quantity(
        value=parsed.value,
        unit=parsed.unit,
        period=draft.period,
        scope=draft.scope,
        binding=binding,
    )


def verify_binding(
    quantity: records.Quantity, evidence: records.Evidence | None
) -> Refusal | None:
    """Re-check a stored binding against the evidence as stored.

    Everything the binding asserts is recomputed: the excerpt hash, the
    four span endpoints, ``as_written``, the value, the unit structure
    and the cell/header association. Nothing is searched for.
    """
    binding = quantity.binding
    if binding is None:
        return Refusal("unbound", "an observed quantity carries a binding")
    if evidence is None or evidence.id != binding.evidence_id:
        return Refusal("unbound", f"evidence {binding.evidence_id} missing")
    if excerpt_hash(evidence.excerpt) != binding.excerpt_sha256:
        return Refusal("unbound", "excerpt changed")
    excerpt = evidence.excerpt
    if (
        not 0
        <= binding.expression_start
        <= binding.number_start
        < binding.number_end
        <= binding.expression_end
        <= len(excerpt)
    ):
        return Refusal("unbound", "spans out of order")
    if (
        excerpt[binding.expression_start : binding.expression_end]
        != binding.as_written
    ):
        return Refusal("unbound", "as_written differs from the excerpt")
    parsed = parse_expression(
        excerpt,
        binding.number_start,
        evidence.table,
        gap_start=_gap(evidence, "start"),
        gap_end=_gap(evidence, "end"),
    )
    if isinstance(parsed, Refusal):
        return Refusal("unbound", parsed.code)
    if parsed.value != quantity.value or parsed.unit != quantity.unit:
        return Refusal("unbound", "value or unit differs from the evidence")
    spans = (
        parsed.number_start,
        parsed.number_end,
        parsed.expression_start,
        parsed.expression_end,
    )
    stored = (
        binding.number_start,
        binding.number_end,
        binding.expression_start,
        binding.expression_end,
    )
    if spans != stored:
        return Refusal("unbound", "spans differ from the evidence")
    # Every coordinate is compared: a pair is present or absent together,
    # so a stray column or row on a prose binding is a difference.
    cell = parsed.cell or (None, None)
    if (binding.cell_row, binding.cell_col) != cell:
        return Refusal("unbound", "cell association differs")
    header = parsed.header_cell or (None, None)
    if (binding.header_row, binding.header_col) != header:
        return Refusal("unbound", "header association differs")
    return None
