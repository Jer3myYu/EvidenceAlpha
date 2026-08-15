"""Route bindings, startup validation, and dispatch (03 §3.3).

The dispatcher knows *roles*; this registry binds a role to an
*implementation*. Swapping PyMuPDF for another parser is therefore a
one-line binding change plus a new adapter module — and if the
replacement is weaker, **startup fails** instead of the corpus quietly
degrading.

There is deliberately no separate config tree. A binding is one line, it
changes when code changes, and it must be type-checked and validated
anyway; an external file would add a deployment surface without buying
anything. If bindings later need to differ per environment they graduate
to shared application configuration at that point, not in advance.

Validation runs when this module is imported, before the application
serves traffic. A binding is rejected when its adapter is unknown, its
capabilities fall below the route's minimum profile (03 §3.5), or the
egress policy would never permit it (03 §3.7).

**No adapter is bound yet.** Every route below is a planned route: it is
detected and named, and it returns ``UNSUPPORTED_FORMAT`` with the
detected format reported, so the gap is measurable. It never falls
through to a text adapter.
"""

from collections.abc import Iterable, Mapping

import pydantic

from contracts import quality
from ingestion.parsing import capabilities as capabilities_module
from ingestion.parsing import detector
from ingestion.parsing import egress as egress_module
from ingestion.parsing.adapters import base


class RegistryError(Exception):
    """Raised at startup when a binding cannot be honored.

    Failing at boot is the entire point of the capability model: the
    alternative is a corpus regression discovered months later.
    """


class Binding(pydantic.BaseModel):
    """One route's implementation choice (03 §3.3, §6).

    ``severe_partial_warnings`` is the route's escalation set: warning
    codes whose presence in a ``partial`` result is worth spending the
    one permitted fallback on. Without it, a filing whose income
    statement collapsed to plain text would enter retrieval carrying
    ``TABLE_STRUCTURE_LOST`` while an approved fallback that would have
    preserved the grid was never tried.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    primary: str
    fallback: str | None = None
    severe_partial_warnings: frozenset[quality.WarningCode] = frozenset()


#: Detected format to route role (03 §3.3). Source-aware HTML splitting
#: already happened during detection, so this maps format to role
#: directly.
ROUTE_TABLE: dict[detector.DetectedFormat, capabilities_module.RouteRole] = {
    detector.DetectedFormat.SEC_INLINE_XBRL_HTML: (
        capabilities_module.RouteRole.SEC_HTML_PARSER
    ),
    detector.DetectedFormat.SEC_HTML: (
        capabilities_module.RouteRole.SEC_HTML_PARSER
    ),
    detector.DetectedFormat.NEWS_HTML: (
        capabilities_module.RouteRole.NEWS_HTML_PARSER
    ),
    detector.DetectedFormat.GENERIC_HTML: (
        capabilities_module.RouteRole.GENERIC_HTML_PARSER
    ),
    detector.DetectedFormat.PDF: (
        capabilities_module.RouteRole.PDF_LAYOUT_PARSER
    ),
    detector.DetectedFormat.DOCX: (capabilities_module.RouteRole.WORD_PARSER),
    detector.DetectedFormat.PPTX: (
        capabilities_module.RouteRole.PRESENTATION_PARSER
    ),
    detector.DetectedFormat.XLSX: (
        capabilities_module.RouteRole.SPREADSHEET_PARSER
    ),
    detector.DetectedFormat.XLS_LEGACY: (
        capabilities_module.RouteRole.SPREADSHEET_PARSER
    ),
    detector.DetectedFormat.CSV: (
        capabilities_module.RouteRole.DELIMITED_TABLE_PARSER
    ),
    detector.DetectedFormat.TSV: (
        capabilities_module.RouteRole.DELIMITED_TABLE_PARSER
    ),
    detector.DetectedFormat.XBRL_XML: (
        capabilities_module.RouteRole.XBRL_PARSER
    ),
    detector.DetectedFormat.GENERIC_XML: (
        capabilities_module.RouteRole.XML_PARSER
    ),
    detector.DetectedFormat.MARKDOWN: (
        capabilities_module.RouteRole.MARKDOWN_PARSER
    ),
    detector.DetectedFormat.JSON: (capabilities_module.RouteRole.JSON_PARSER),
    detector.DetectedFormat.PLAIN_TEXT: (
        capabilities_module.RouteRole.PLAIN_TEXT_PARSER
    ),
    detector.DetectedFormat.PNG_IMAGE: (
        capabilities_module.RouteRole.IMAGE_OCR_PARSER
    ),
    detector.DetectedFormat.JPEG_IMAGE: (
        capabilities_module.RouteRole.IMAGE_OCR_PARSER
    ),
    detector.DetectedFormat.TIFF_IMAGE: (
        capabilities_module.RouteRole.IMAGE_OCR_PARSER
    ),
}

#: Role to implementation. Empty until an adapter exists: 03 §14 builds
#: the SEC HTML route at step 5 and digital PDF at step 7, each behind
#: its own spike. A role absent here is an unregistered route.
ROUTE_BINDINGS: dict[capabilities_module.RouteRole, Binding] = {}


class AdapterRegistry:
    """Holds adapters and bindings, and validates them on construction.

    Constructing a registry is the startup check. Nothing here defers a
    capability question to parse time.
    """

    def __init__(
        self,
        adapters: Iterable[base.ParserAdapter] = (),
        bindings: Mapping[capabilities_module.RouteRole, Binding] | None = None,
        profiles: (
            Mapping[
                capabilities_module.RouteRole, capabilities_module.RouteProfile
            ]
            | None
        ) = None,
        egress_policy: egress_module.EgressPolicy | None = None,
    ) -> None:
        """Build and validate a registry.

        Args:
          adapters: Every adapter implementation available to bind.
          bindings: Role to implementation; :data:`ROUTE_BINDINGS` when
            omitted.
          profiles: Route minimum profiles;
            :data:`ingestion.parsing.capabilities.ROUTE_PROFILES` when
            omitted.
          egress_policy: The egress policy in force;
            :data:`ingestion.parsing.egress.DEFAULT_EGRESS_POLICY` when
            omitted.

        Raises:
          RegistryError: If any binding names an unknown adapter, binds
            an adapter below its route's minimum capability profile, or
            binds one the egress policy would never permit.
        """
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._bindings = dict(
            bindings if bindings is not None else ROUTE_BINDINGS
        )
        self._profiles = dict(
            profiles
            if profiles is not None
            else capabilities_module.ROUTE_PROFILES
        )
        self._egress_policy = (
            egress_policy or egress_module.DEFAULT_EGRESS_POLICY
        )
        self._validate()

    def _validate(self) -> None:
        """Check every binding against its route's minimum profile."""
        for role, binding in self._bindings.items():
            names = [binding.primary]
            if binding.fallback is not None:
                names.append(binding.fallback)
            for name in names:
                self._validate_adapter(role, name)

    def _validate_adapter(
        self, role: capabilities_module.RouteRole, name: str
    ) -> None:
        """Check one bound adapter against one route."""
        adapter = self._adapters.get(name)
        if adapter is None:
            raise RegistryError(
                f"route {role.value!r} binds unknown adapter {name!r}"
            )
        try:
            egress_module.validate_adapter_egress(
                name, adapter.capabilities, self._egress_policy
            )
        except egress_module.EgressPolicyError as error:
            raise RegistryError(str(error)) from error
        profile = self._profiles.get(role)
        if profile is None:
            return
        violations = capabilities_module.check_capabilities(
            adapter.capabilities, profile
        )
        if violations:
            raise RegistryError(
                f"adapter {name!r} cannot serve route {role.value!r}: "
                + "; ".join(violations)
            )

    def resolve(
        self, detected_format: detector.DetectedFormat
    ) -> capabilities_module.RouteRole | None:
        """Return the role that serves a detected format.

        Args:
          detected_format: What detection concluded.

        Returns:
          The route role, or None when the format has no route at all.
        """
        return ROUTE_TABLE.get(detected_format)

    def binding_for(
        self, role: capabilities_module.RouteRole
    ) -> Binding | None:
        """Return the binding for a role, or None if unregistered.

        Args:
          role: The route role.

        Returns:
          The binding, or None when no adapter is bound to the role.
        """
        return self._bindings.get(role)

    def profile_for(
        self, role: capabilities_module.RouteRole
    ) -> capabilities_module.RouteProfile:
        """Return a role's minimum capability profile.

        Args:
          role: The route role.

        Returns:
          The declared profile, or a permissive default for roles
          outside the MVP that have not declared one yet.
        """
        return self._profiles.get(
            role, capabilities_module.RouteProfile(role=role)
        )

    def adapter(self, name: str) -> base.ParserAdapter:
        """Return a registered adapter by name.

        Args:
          name: The adapter's name.

        Returns:
          The adapter implementation.

        Raises:
          RegistryError: If no adapter of that name is registered.
        """
        adapter = self._adapters.get(name)
        if adapter is None:
            raise RegistryError(f"no adapter named {name!r} is registered")
        return adapter

    @property
    def egress_policy(self) -> egress_module.EgressPolicy:
        """Return the egress policy this registry validated against."""
        return self._egress_policy


#: Validated at import time, before the application serves traffic.
DEFAULT_REGISTRY = AdapterRegistry()
