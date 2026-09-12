"""Check duplicate-window accounting with fake model/tokenizer modules."""

import contextlib
import sys
import types

from evidencealpha import reranking


def test_identical_windows_score_once_per_query(monkeypatch):
    """Duplicate originals retain logits/views but charge only real forwards."""
    calls = []

    class Model:
        """Record forwards without importing a neural framework."""

        def eval(self):
            """Match the local loader interface."""
            return self

        def __call__(self, **encoded):
            calls.append(encoded)
            return types.SimpleNamespace(
                logits=types.SimpleNamespace(reshape=lambda _: [4.25])
            )

    class Tokenizer:
        """Use deterministic character counts."""

        def encode(self, value, **_):
            """Count query characters."""
            return list(value)

        def __call__(self, query, text, **_):
            return {"input_ids": list(query + text)}

    monkeypatch.setitem(
        sys.modules,
        "torch",
        types.SimpleNamespace(
            set_num_threads=lambda _: None,
            float32="float32",
            inference_mode=contextlib.nullcontext,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(
            AutoTokenizer=types.SimpleNamespace(
                from_pretrained=lambda *_, **__: Tokenizer()
            ),
            AutoModelForSequenceClassification=types.SimpleNamespace(
                from_pretrained=lambda *_, **__: Model()
            ),
        ),
    )
    view = {"identity_text": "Original", "passages": [{"text": "support"}]}

    class Connection:
        """Supply one query then close the worker loop."""

        def __init__(self):
            self.sent = []
            self.received = False

        def recv(self):
            """Return duplicate views exactly once."""
            if self.received:
                raise EOFError
            self.received = True
            return "query", [view, view]

        def send(self, item):
            """Keep observable worker output."""
            self.sent.append(item)

        def close(self):
            """No process or socket exists."""

    connection = Connection()
    reranking._worker(  # pylint: disable=protected-access
        connection,
        {
            "reranker_threads": 4,
            "reranker_path": "unused",
            "reranker_query_tokens": 128,
            "reranker_pair_tokens": 1024,
        },
    )
    result = connection.sent[0]["results"]
    assert len(calls) == 1
    assert [r["pairs"] for r in result] == [1, 0]
    assert [r["score"] for r in result] == [4.25, 4.25]
    assert result[0]["scored_views"] == result[1]["scored_views"]
