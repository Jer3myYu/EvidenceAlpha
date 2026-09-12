"""Bounded evidence tools shared by both providers; no agent shell access."""

import decimal
import dataclasses
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.parse
import uuid

import requests
import tavily
import dotenv

from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import providers
from evidencealpha import retrieval
from evidencealpha import reading
from evidencealpha import reranking

TOOL_DEFINITIONS = {
    "search_evidence": {
        "query": "focused question",
        "source_id": "optional source ID",
        "question_id": "task question ID",
    },
    "open_source": {
        "source_id": "string",
        "question_id": "task question ID",
        "page": "optional original page; exclusive with chunk/continuation",
        "continuation": "optional exact version-bound cursor",
        "chunk_id": "optional exact returned ID, e.g. c30, not 30",
        "surrounding": (
            "0: exact chunk; 1..2: complete neighboring paragraph/table "
            "blocks per side in page order, under the configured window limit"
        ),
    },
    "search_web": {"query": "string"},
    "fetch_source": {"url": "public HTTP(S) URL"},
    "calculate": {
        "operation": "add|subtract|multiply|divide",
        "values": "decimal strings",
    },
}


class EvidenceTools:
    """Infrastructure owns source side effects and external-call accounting."""

    def __init__(
        self,
        store: documents.SourceStore,
        settings: config.Settings,
        mode: str,
        ledger: budget.Ledger | None = None,
        scorer: reranking.Scorer | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.mode = mode
        self.ledger = ledger
        self.retriever = retrieval.Retriever(store, settings, scorer)

    def definitions(self) -> dict:
        """Expose only capabilities permitted by this execution mode."""
        return {
            key: value
            for key, value in TOOL_DEFINITIONS.items()
            if self.mode == "live" or key not in ("search_web", "fetch_source")
        }

    def call(
        self, name: str, arguments: dict, deadline: float | None = None
    ) -> object:
        """Dispatch a validated capability."""
        if name not in self.definitions():
            raise ValueError(f"Tool unavailable in {self.mode}: {name}")
        remaining = 30 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Tool deadline expired")
        if deadline is not None and name in ("search_web", "fetch_source"):
            return self._external(name, arguments, deadline)
        if name == "search_evidence":
            query = arguments["query"]
            source_id = arguments.get("source_id")
            # Observed Codex queries used this familiar scope syntax. Honor
            # it explicitly rather than silently treating it as a search term.
            scopes = re.findall(r"\bsource_id:([a-f0-9]{64})\b", query)
            if scopes:
                if len(set(scopes)) != 1 or source_id not in (None, scopes[0]):
                    raise ValueError("Conflicting source scopes")
                source_id = scopes[0]
                query = re.sub(r"\bsource_id:[a-f0-9]{64}\b", "", query).strip()
            result = self.retriever.search(
                query, source_id, arguments.get("question_id"), deadline
            )
            if result["retrieval_status"] == "reranker_cancelled":
                raise providers.ProviderCancelled("Local retrieval cancelled")
            passages = result.pop("passages")
            if result.get("error") is None:
                result.pop("error", None)
            return {**documents.group_passages(passages), **result}
        if name == "open_source":
            source_id = arguments["source_id"]
            chunk_id = arguments.get("chunk_id")
            surrounding = arguments.get("surrounding") or 0
            if (
                chunk_id is not None
                and not surrounding
                and arguments.get("page") is None
                and not arguments.get("continuation")
            ):
                passage = self.store.concise_passage(
                    self.store.open_source(source_id, chunk_id)
                )
                return documents.group_passages([passage])
            if (
                chunk_id is not None
                or arguments.get("page") is not None
                or arguments.get("continuation")
            ):
                block = reading.window(
                    self.store,
                    source_id,
                    chunk_id,
                    surrounding=surrounding,
                    page=arguments.get("page"),
                    continuation=arguments.get("continuation"),
                    characters=self.settings.reading_window_characters,
                )
                return {
                    **documents.group_passages(block["passages"]),
                    "reading_blocks": [block],
                    "question_id": arguments.get("question_id"),
                }
            if surrounding:
                raise ValueError("Surrounding retrieval requires a chunk_id")
            result = self.store.open_source(source_id)
            if len(result["text"]) > self.settings.source_open_characters:
                raise ValueError(
                    "Source exceeds full-text tool limit; use "
                    "search_evidence then open_source with chunk_id. "
                    "No source text has been truncated."
                )
            return documents.group_passages(
                [
                    {
                        **self.store.source_context(source_id),
                        "text": result["text"],
                        "spans": [
                            {
                                "start": 0,
                                "end": len(result["text"]),
                                "page": None,
                            }
                        ],
                    }
                ]
            )
        if name == "calculate":
            values = [decimal.Decimal(str(v)) for v in arguments["values"]]
            if len(values) != 2 or not all(v.is_finite() for v in values):
                raise ValueError("Calculator requires two finite decimals")
            left, right = values
            operation = arguments["operation"]
            if operation == "add":
                result = left + right
            elif operation == "subtract":
                result = left - right
            elif operation == "multiply":
                result = left * right
            elif operation == "divide":
                result = left / right
            else:
                raise ValueError("Unsupported arithmetic operation")
            return {
                "result": str(result),
                "inputs": arguments,
                "limitation": "Arithmetic only; metric selection not validated",
            }
        if self.ledger is None:
            raise ValueError("External tools require an active campaign ledger")
        if name == "search_web":
            self.ledger.acquire("search_calls")
            key = os.environ.get("TAVILY_API_KEY")
            if not key and self.settings.search_env_file:
                key = dotenv.dotenv_values(self.settings.search_env_file).get(
                    "TAVILY_API_KEY"
                )
            result = tavily.TavilyClient(api_key=key).search(
                query=arguments["query"],
                max_results=5,
                timeout=min(30, remaining),
            )
            return {
                "kind": "search_snippets_not_original_snapshots",
                "results": result.get("results", []),
            }
        return self._fetch(arguments["url"], deadline)

    def _external(self, name: str, arguments: dict, deadline: float) -> object:
        """Bound network waits and parsing in a cancellable process group."""
        if self.ledger is None:
            raise ValueError("External tools require an active campaign ledger")
        request = providers.Request(
            name,
            json.dumps(
                {
                    "name": name,
                    "arguments": arguments,
                    "store": str(self.store.root.resolve()),
                    "settings": dataclasses.asdict(self.settings),
                    "ledger": str(self.ledger.path.resolve()),
                }
            ),
            self.settings.model("plan"),
            (self.store.root.parent / "tools" / uuid.uuid4().hex).resolve(),
            max(0, deadline - time.monotonic()),
            deadline,
        )
        events, code = providers.execute(
            [sys.executable, "-m", "evidencealpha.tool_runner"], request
        )
        if code or not events:
            raise RuntimeError("External tool failed; see tool artifacts")
        return events[-1]

    def _fetch(self, url: str, deadline: float | None = None) -> dict:
        for source in self.store.sources():
            if source["url"] == url:
                return {"source": source, "reused": True}
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme not in ("https", "http")
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Source URL must be public HTTP(S), without credentials"
            )
        self.ledger.acquire("fetch_attempts")
        remaining = 30 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Fetch deadline expired")
        # No automatic retries. Requests timeout bounds individual socket waits.
        with requests.get(
            url,
            timeout=(min(10, remaining), min(20, remaining)),
            stream=True,
            allow_redirects=False,
        ) as response:
            if 300 <= response.status_code < 400:
                raise ValueError(
                    "Source redirected; fetch the explicit Location URL: "
                    + response.headers.get("Location", "unknown")
                )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            suffix = ".pdf" if "pdf" in content_type else ".html"
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory) / ("download" + suffix)
                size = 0
                with path.open("wb") as output:
                    for chunk in response.iter_content(65536):
                        if (
                            deadline is not None
                            and time.monotonic() >= deadline
                        ):
                            raise RuntimeError("Fetch deadline expired")
                        size += len(chunk)
                        if size > 25_000_000:
                            raise ValueError(
                                "Source exceeds 25 MB capture limit"
                            )
                        output.write(chunk)
                return {"source": self.store.ingest(path, url), "reused": False}
