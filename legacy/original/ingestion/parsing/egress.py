"""Egress policy for parser adapters (03 §3.7).

**MVP position: deny all.** Every bound adapter declares
``egress: none``, local adapters are explicitly network-free, and the
conformance suite asserts it rather than leaving it merely
unimplemented.

What exists here now is the decision point, not the transport: the
policy object, the startup validation that refuses any adapter
declaring egress, and the per-``source_class`` keying that a real
policy will need. The endpoint allowlist and remote transport wait for
the first hosted adapter, so admitting one is an addition rather than a
redesign (03 §14 step 1).

Two rules survive whatever replaces :class:`DenyAllEgressPolicy`:

* the default is deny, and only application policy may widen it —
  neither the research agent nor anything inside a document can;
* ``user_upload`` is the dangerous class, being the most likely to be
  confidential and the least likely to have been cleared.
"""

from typing import Protocol

import pydantic

from contracts import document
from ingestion.parsing import capabilities as capabilities_module


class EgressPolicyError(Exception):
    """Raised when an adapter's egress declaration is not permitted.

    Raised at startup by :func:`validate_adapter_egress`, so an adapter
    that would transmit an artifact cannot be bound in the first place.
    """


class EgressDecision(pydantic.BaseModel):
    """Whether one artifact may be transmitted, and why."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: str


class EgressPolicy(Protocol):
    """Decides whether an artifact may leave the process."""

    name: str

    def allows(
        self,
        source_class: document.SourceClass,
        adapter_capabilities: capabilities_module.AdapterCapabilities,
    ) -> EgressDecision:
        """Return whether transmission is permitted.

        Args:
          source_class: The trusted caller context of the artifact.
          adapter_capabilities: What the bound adapter declared.

        Returns:
          The decision, carrying a reason either way.
        """


class DenyAllEgressPolicy:
    """The MVP policy: nothing is ever transmitted (03 §3.7).

    An adapter declaring ``egress: none`` is permitted because it
    transmits nothing. Anything else is denied, and the denial is a
    policy decision rather than a failure (03 §8.1).
    """

    name = "deny_all"

    def allows(
        self,
        source_class: document.SourceClass,
        adapter_capabilities: capabilities_module.AdapterCapabilities,
    ) -> EgressDecision:
        """Return whether transmission is permitted.

        Args:
          source_class: The trusted caller context of the artifact.
          adapter_capabilities: What the bound adapter declared.

        Returns:
          Allowed only when the adapter declares ``egress: none``.
        """
        if adapter_capabilities.egress is capabilities_module.Egress.NONE:
            return EgressDecision(
                allowed=True,
                reason="adapter declares egress=none and transmits nothing",
            )
        return EgressDecision(
            allowed=False,
            reason=(
                "remote parsing is not enabled; "
                f"source_class={source_class.value} may not be transmitted"
            ),
        )


#: The policy in force. Replacing this is an application decision, made
#: once, in application code.
DEFAULT_EGRESS_POLICY: EgressPolicy = DenyAllEgressPolicy()


def validate_adapter_egress(
    adapter_name: str,
    adapter_capabilities: capabilities_module.AdapterCapabilities,
    policy: EgressPolicy | None = None,
) -> None:
    """Reject an adapter the policy would never let transmit.

    Called by the registry at startup for every binding, so a hosted
    adapter cannot be bound while the policy denies egress. Failing at
    boot is the point: the alternative is discovering it per document.

    Args:
      adapter_name: The adapter being bound, named for the message.
      adapter_capabilities: What that adapter declared.
      policy: The policy in force; :data:`DEFAULT_EGRESS_POLICY` when
        omitted.

    Raises:
      EgressPolicyError: If the policy denies the declared egress for
        any source class.
    """
    policy = policy or DEFAULT_EGRESS_POLICY
    for source_class in document.SourceClass:
        decision = policy.allows(source_class, adapter_capabilities)
        if not decision.allowed:
            raise EgressPolicyError(
                f"adapter {adapter_name!r} declares "
                f"egress={adapter_capabilities.egress.value}, which policy "
                f"{policy.name!r} denies: {decision.reason}"
            )
