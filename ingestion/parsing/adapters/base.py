"""The parser adapter contract (03 §3.4).

Every adapter implements the same small interface. It answers "what did
the parser see"; the subsystem — converters, normalizer, gate — answers
"what does the corpus get". That split is what keeps a new vendor
integration at tens of lines rather than a reimplementation of the
normalized contract.

Three things an adapter must never do: dereference a URL derived from
document content, document metadata, or the artifact's own source URL
(03 §1.0); write to ChromaDB; or implement RAG chunking.

No concrete adapter lives in this package yet. Roles are declared in
:mod:`ingestion.parsing.capabilities` and bound in
:mod:`ingestion.parsing.registry`; a role with no binding returns
``UNSUPPORTED_FORMAT`` rather than falling through to a text adapter.
"""

from typing import Protocol, runtime_checkable

import pydantic

from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector
from ingestion.parsing import shapes


class AdapterError(Exception):
    """Raised by an adapter that cannot parse the artifact.

    An adapter exception is a recoverable parser failure: it triggers
    the one approved fallback, exactly as a ``failed`` gate verdict does
    (03 §8.1).
    """


class ParseRequest(pydantic.BaseModel):
    """What an adapter is asked to parse (03 §3.4).

    The artifact plus what detection concluded about it. Nothing else:
    an adapter that needs more context is an adapter doing the
    ingestion service's job.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    artifact: shapes.AcquiredArtifact
    detection: detector.DetectionResult


@runtime_checkable
class ParserAdapter(Protocol):
    """One parser implementation behind one or more roles (03 §3.4)."""

    name: str
    version: str
    capabilities: capabilities_module.AdapterCapabilities

    def supports(self, request: ParseRequest) -> bool:
        """Return whether this adapter can handle the request.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          True when the adapter is willing to attempt the parse.
        """

    def parse(self, request: ParseRequest) -> shapes.RawParseResult:
        """Parse the artifact into one of the three native shapes.

        Args:
          request: The artifact and what detection concluded.

        Returns:
          The adapter's native output plus its own provenance.

        Raises:
          AdapterError: If the artifact cannot be parsed.
        """
