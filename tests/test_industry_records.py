"""Records, allowlist completeness, and the installed package."""

import importlib
import inspect

import pydantic
import pytest

from industry import records


def test_installed_package_imports():
    assert importlib.import_module("industry.records") is records


def test_every_record_class_is_persisted():
    classes = {
        obj
        for _, obj in inspect.getmembers(records, inspect.isclass)
        if issubclass(obj, records.Record) and obj is not records.Record
    }
    assert classes == set(records.PERSISTED)


def test_extra_fields_are_rejected():
    with pytest.raises(pydantic.ValidationError):
        records.Claim(id="C1", statement="x", kind="fact", extra=1)


def test_usage_addition_sums_and_keeps_unknown():
    total = records.Usage(turns=3, tool_calls=2, cost_usd=0.5) + records.Usage(
        turns=4, duration_s=2.0, unknown=True
    )
    assert (total.turns, total.tool_calls, total.duration_s) == (7, 2, 2.0)
    assert total.cost_usd == 0.5 and total.unknown


def test_required_questions_and_central_set():
    assert sorted(records.REQUIRED_QUESTIONS) == list(range(1, 9))
    assert records.CENTRAL_QUESTIONS == (1, 2, 3, 4, 5)
    assert len(records.QUESTION_4_TOPICS) == 5
