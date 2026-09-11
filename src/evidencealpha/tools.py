"""Bounded evidence tools shared by both providers; no agent shell access."""

import decimal
import pathlib
import tempfile
import urllib.parse

import requests
import tavily

from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents

TOOL_DEFINITIONS = {
    "search_evidence": {"query": "string"},
    "open_source": {"source_id": "string", "chunk_id": "optional string"},
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
    ) -> None:
        self.store = store
        self.settings = settings
        self.mode = mode
        self.ledger = ledger

    def definitions(self) -> dict:
        """Expose only capabilities permitted by this execution mode."""
        return {
            key: value
            for key, value in TOOL_DEFINITIONS.items()
            if self.mode == "live" or key not in ("search_web", "fetch_source")
        }

    def call(self, name: str, arguments: dict) -> object:
        """Dispatch a validated capability."""
        if name not in self.definitions():
            raise ValueError(f"Tool unavailable in {self.mode}: {name}")
        if name == "search_evidence":
            return self.store.search_evidence(
                arguments["query"],
                self.settings.retrieval_limit,
                self.settings.embedding_model,
            )
        if name == "open_source":
            return self.store.open_source(**arguments)
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
            result = tavily.TavilyClient().search(
                query=arguments["query"], max_results=5, timeout=30
            )
            return {
                "kind": "search_snippets_not_original_snapshots",
                "results": result.get("results", []),
            }
        return self._fetch(arguments["url"])

    def _fetch(self, url: str) -> dict:
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
        # No automatic retries. Requests timeout bounds individual socket waits.
        with requests.get(
            url, timeout=(10, 20), stream=True, allow_redirects=False
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
                        size += len(chunk)
                        if size > 25_000_000:
                            raise ValueError(
                                "Source exceeds 25 MB capture limit"
                            )
                        output.write(chunk)
                return {"source": self.store.ingest(path, url), "reused": False}
