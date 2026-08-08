"""The input port of capability adjudication (AG3-239).

Adjudication is core work (FK-01 §1.1a): the capability matrix, the principal
attestation and the canonical conflict-freeze record are core state. Until
AG3-239 the core read its input by importing ``HookEvent`` from
``governance.guard_evaluation`` -- an EDGE module that runs in the hook process
on the developer machine. Three core modules did that, and each import was a
core-to-edge boundary violation.

The fix is a **structural port**, not a moved type. The core names the fields it
reads; anything carrying them satisfies the port without an import:

* the edge ``HookEvent``, when adjudication runs in-process (tests, and the
  guard chain that already holds an event);
* ``agentkit_wire.governance_adjudication.CapabilityAdjudicationRequest``, when
  it arrives over ``/v1``.

Neither side has to know about the other. This mirrors
``story_context_manager.operating_mode_resolver.CarriesOperatingMode``, which
solves the same problem for the operating mode.

``HookEvent`` itself does NOT migrate to the contract package: its hull does not
close (``Path.cwd()`` in its validators), and the frozen classification defers it
with an ``ag3_209_precondition``. A port needs no migration.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AdjudicationInput(Protocol):
    """Everything capability adjudication reads about an operation.

    The field set is deliberately closed and small. It is the FK-55 §55.3a
    attestation surface plus the operation itself -- never prompt content.
    """

    @property
    def operation(self) -> str:
        """Harness-neutral operation identifier (e.g. ``"bash_command"``)."""

    @property
    def operation_args(self) -> dict[str, object]:
        """Harness-neutral operation arguments (tool name, target, command)."""

    @property
    def principal_kind(self) -> str:
        """Attested principal kind (``"main"``, ``"subagent"``, ...)."""

    @property
    def cwd(self) -> str:
        """Working directory the operation runs in."""

    @property
    def session_id(self) -> str | None:
        """Harness session id, when the harness supplies one."""

    @property
    def parent_session_id(self) -> str | None:
        """Parent session id for a spawned sub-agent, else ``None``."""

    @property
    def cli_args(self) -> list[str] | None:
        """Attested CLI arguments, or ``None`` when the harness supplies none."""


__all__ = ["AdjudicationInput"]
