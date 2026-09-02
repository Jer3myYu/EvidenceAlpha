"""The parse manifest and ``parse_id`` (03 §5.1).

The manifest has two halves and **only one of them is hashed**.

The **planned** manifest is a property of the configured pipeline, not
of the parse outcome: route role, **every registered attempt** — the
primary and the approved fallback alike — with each one's adapter
version, library versions, extraction class, determinism, declared
native shape, and the converter version for that shape, plus the
normalizer and quality-policy versions. All of it is known before any
adapter runs, which is what makes ``parse_id`` computable up front and
the reuse check in 03 §6 a direct lookup.

Listing the fallback matters: a route whose fallback changed is a
different pipeline even when the primary is untouched, and re-parsing
should be expressible for it like any other manifest change.

The **observed** manifest records what only exists once the parse has
happened — which attempts ran, whether the fallback produced the
accepted output, metrics, warnings, the vendor-reported version, and a
digest of the raw adapter output. It is persisted for audit and
deliberately excluded from identity.

Excluding the outcome loses nothing: for a fixed artifact and a fixed
planned manifest, whether the primary fails is itself determined.
"""

import hashlib
import json

import pydantic

from contracts import document
from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import shapes
from ingestion.parsing.converters import blocks as blocks_converter
from ingestion.parsing.converters import common
from ingestion.parsing.converters import elements as elements_converter
from ingestion.parsing.converters import markdown as markdown_converter

_MODEL_CONFIG = pydantic.ConfigDict(frozen=True, extra="forbid")

#: Converter version per native shape, for the planned manifest.
CONVERTER_VERSIONS: dict[shapes.NativeShape, str] = {
    shapes.NativeShape.BLOCK_SEQUENCE: blocks_converter.CONVERTER_VERSION,
    shapes.NativeShape.ELEMENT_LIST: elements_converter.CONVERTER_VERSION,
    shapes.NativeShape.MARKDOWN_DOCUMENT: (
        markdown_converter.CONVERTER_VERSION
    ),
}


class PlannedAttempt(pydantic.BaseModel):
    """One registered attempt on a route, described in advance.

    Every adapter the route may run — the primary and the approved
    fallback — is described here before any of them runs, each with the
    converter version for the shape it declared. Which one ends up
    producing the output is an *observed* fact and lives in
    :class:`ObservedManifest`.
    """

    model_config = _MODEL_CONFIG

    adapter_name: str
    adapter_version: str
    is_fallback: bool = False
    library_versions: dict[str, str] = pydantic.Field(default_factory=dict)
    extraction_class: capabilities_module.ExtractionClass
    determinism: capabilities_module.Determinism
    native_shape: shapes.NativeShape
    converter_version: str
    endpoint_host: str | None = None
    pinned_service_version: str | None = None


class PlannedManifest(pydantic.BaseModel):
    """The hashed half of the manifest, known before parsing.

    Every field is a property of the configured pipeline. Changing any
    one of them — a library upgrade, an adapter swap, a new fallback, a
    quality threshold — changes ``parse_id``, which is what makes
    re-parsing and re-indexing expressible rather than a special case.

    ``attempts`` lists **every registered attempt**, not only the
    primary. A route whose fallback changed is a different pipeline even
    when the primary is untouched, and the fallback's converter version
    is as much a part of the configured pipeline as the primary's.
    """

    model_config = _MODEL_CONFIG

    route_role: capabilities_module.RouteRole
    attempts: list[PlannedAttempt]
    normalizer_version: str = common.NORMALIZER_VERSION
    schema_version: str = document.SCHEMA_VERSION
    quality_policy_version: str

    @pydantic.model_validator(mode="after")
    def _check_attempts(self) -> "PlannedManifest":
        """Require exactly one primary, listed first, and no repeats."""
        if not self.attempts:
            raise ValueError("a planned manifest needs at least one attempt")
        if self.attempts[0].is_fallback:
            raise ValueError("the primary attempt must be listed first")
        primaries = [
            attempt for attempt in self.attempts if not attempt.is_fallback
        ]
        if len(primaries) != 1:
            raise ValueError("a route has exactly one primary attempt")
        names = {attempt.adapter_name for attempt in self.attempts}
        if len(names) != len(self.attempts):
            raise ValueError("an adapter may appear once per route")
        return self

    @property
    def primary(self) -> PlannedAttempt:
        """Return the primary attempt."""
        return self.attempts[0]


class ParseAttempt(pydantic.BaseModel):
    """One adapter attempt, primary or fallback (03 §3.3)."""

    model_config = _MODEL_CONFIG

    role: capabilities_module.RouteRole
    adapter_name: str
    adapter_version: str
    is_fallback: bool = False
    verdict: quality.QualityVerdict | None = None
    error: str | None = None


class ObservedManifest(pydantic.BaseModel):
    """The recorded half of the manifest, never hashed (03 §5.1).

    ``raw_output_digest`` exists for ``determinism: opaque_remote``,
    where a vendor can change their model without changing any
    configured version string. The digest makes that drift detectable
    after the fact; it does not make it preventable, and
    reproducibility is not claimed for that class.
    """

    model_config = _MODEL_CONFIG

    attempts: list[ParseAttempt] = pydantic.Field(default_factory=list)
    fallback_used: bool = False
    warnings: list[document.ParseWarning] = pydantic.Field(default_factory=list)
    metrics: document.ParseMetrics = pydantic.Field(
        default_factory=document.ParseMetrics
    )
    rejected_block_count: int = pydantic.Field(default=0, ge=0)
    vendor_reported_version: str | None = None
    raw_output_digest: str | None = None


class ParseManifest(pydantic.BaseModel):
    """Both halves of the manifest, persisted together (03 §9)."""

    model_config = _MODEL_CONFIG

    planned: PlannedManifest
    observed: ObservedManifest = pydantic.Field(
        default_factory=ObservedManifest
    )


def canonical_planned_payload(planned: PlannedManifest) -> str:
    """Serialize a planned manifest to a stable string.

    Key order is normalized so that a semantically identical manifest
    always hashes the same, whatever order the fields were built in.

    Args:
      planned: The planned manifest.

    Returns:
      Canonical JSON with sorted keys and no insignificant whitespace.
    """
    return json.dumps(
        planned.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_parse_id(version_id: str, planned: PlannedManifest) -> str:
    """Derive ``parse_id`` from the content hash and planned manifest.

    Computable before any adapter runs, which is the whole point: the
    reuse check is a direct lookup, and it matches previously failed
    parses too, so a deterministic failure is not retried until the
    planned manifest changes (03 §6).

    Args:
      version_id: The content hash of the source bytes (02 §13).
      planned: The planned manifest.

    Returns:
      A ``sha256:``-prefixed parse identity.
    """
    payload = f"{version_id}|{canonical_planned_payload(planned)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_planned_attempt(
    adapter_name: str,
    adapter_version: str,
    adapter_capabilities: capabilities_module.AdapterCapabilities,
    is_fallback: bool = False,
    library_versions: dict[str, str] | None = None,
    pinned_service_version: str | None = None,
) -> PlannedAttempt:
    """Describe one registered adapter before it runs.

    The converter version comes from the adapter's **declared** native
    shape, which is why the declaration is static (03 §3.5): the planned
    manifest has to name it before any adapter has produced output.

    Args:
      adapter_name: The bound adapter's name.
      adapter_version: The bound adapter's version.
      adapter_capabilities: What that adapter declared.
      is_fallback: Whether this is the route's approved fallback.
      library_versions: Versions of every parsing library the adapter
        can invoke.
      pinned_service_version: The pinned remote service or model
        version, when one is configured.

    Returns:
      The planned description of this attempt.
    """
    shape = adapter_capabilities.native_shape
    return PlannedAttempt(
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        is_fallback=is_fallback,
        library_versions=dict(library_versions or {}),
        extraction_class=adapter_capabilities.extraction_class,
        determinism=adapter_capabilities.determinism,
        native_shape=shape,
        converter_version=CONVERTER_VERSIONS[shape],
        endpoint_host=adapter_capabilities.endpoint_host,
        pinned_service_version=pinned_service_version,
    )


def build_planned_manifest(
    role: capabilities_module.RouteRole,
    attempts: list[PlannedAttempt],
    quality_policy_version: str,
) -> PlannedManifest:
    """Assemble a planned manifest for a whole route.

    Args:
      role: The route role being served.
      attempts: Every registered attempt, primary first.
      quality_policy_version: Version of the quality policy in force.

    Returns:
      The planned manifest for this pipeline.
    """
    return PlannedManifest(
        route_role=role,
        attempts=list(attempts),
        quality_policy_version=quality_policy_version,
    )


def raw_output_digest(raw: shapes.RawParseResult) -> str:
    """Digest an adapter's raw output for drift detection.

    Args:
      raw: The adapter's native result.

    Returns:
      A ``sha256:``-prefixed digest of the serialized raw output.
    """
    payload = raw.model_dump_json()
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
