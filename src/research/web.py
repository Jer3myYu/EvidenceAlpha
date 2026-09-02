"""Web search through Tavily, reduced to a small result model.

Everything Tavily-specific stays in this module. The key is read from the
``TAVILY_API_KEY`` environment variable; ``.env.example`` shows the setup.
"""

import dataclasses
import os

import tavily

KEY_VARIABLE = "TAVILY_API_KEY"


@dataclasses.dataclass(frozen=True)
class WebResult:
    """One web search hit.

    Attributes:
      title: The page title.
      url: The page address.
      snippet: A short extract of the page relevant to the query.
    """

    title: str
    url: str
    snippet: str


def api_key() -> str:
    """Return the Tavily key from the environment.

    Raises:
      RuntimeError: If the variable is missing, naming what to set.
    """
    key = os.environ.get(KEY_VARIABLE)
    if not key:
        raise RuntimeError(
            f"Web search needs the {KEY_VARIABLE} environment variable. "
            "See .env.example for setup."
        )
    return key


def search_web(query: str, max_results: int = 5) -> list[WebResult]:
    """Search the web and return the top results.

    Args:
      query: The search query.
      max_results: How many results to return.

    Returns:
      Results in Tavily's relevance order.

    Raises:
      RuntimeError: If the API key is not set.
    """
    response = tavily.TavilyClient(api_key=api_key()).search(
        query, max_results=max_results
    )
    return [
        WebResult(title=hit["title"], url=hit["url"], snippet=hit["content"])
        for hit in response["results"]
    ]
