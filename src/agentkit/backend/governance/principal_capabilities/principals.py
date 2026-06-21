"""Canonical principals and harness-context-only principal resolution (FK-55 §55.3/§55.3a).

The :class:`Principal` enum transcribes the nine canonical principal types of
FK-55 §55.3 *exactly* (same wire values as the FK-55 glossary ``principal``
term). :class:`PrincipalResolver` derives the principal **only** from the
harness/event context — never from prompt content (FK-55 §55.3a).

Resolution is fail-closed to the *least-privileged applicable* principal
(FK-55 §55.3a, §55.10.1):

- A privileged principal (``pipeline_deterministic`` / ``admin_service`` /
  ``human_cli``) is assumed only with an explicit structural service
  attestation.
- A spawned sub-agent's specific role (``worker`` / ``qa_reader`` /
  ``adversarial_writer`` / ``llm_evaluator``) is resolved from its structural
  spawn attestation. A sub-agent WITHOUT a more specific attestation does NOT
  inherit ``worker`` write capabilities — it falls fail-closed to the
  least-privileged sub-agent principal (``llm_evaluator``, which has no local
  filesystem capability per the invariant
  ``llm_evaluator_has_no_local_filesystem_capability``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.governance.guard_evaluation import HookEvent


class Principal(StrEnum):
    """The nine canonical AK3 principal types (FK-55 §55.3).

    Wire values are normative and identical to the FK-55 glossary ``principal``
    term. New principals require their own Feinkonzept (FK-55 §55.3 "Normative
    Reduktion") and must not be added ad hoc.
    """

    INTERACTIVE_AGENT = "interactive_agent"
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    QA_READER = "qa_reader"
    ADVERSARIAL_WRITER = "adversarial_writer"
    LLM_EVALUATOR = "llm_evaluator"
    PIPELINE_DETERMINISTIC = "pipeline_deterministic"
    HUMAN_CLI = "human_cli"
    ADMIN_SERVICE = "admin_service"


#: Structural attestation flag the platform/CLI emits to attest a principal.
#: FK-55 §55.3a: the principal is derived only from technically attested context
#: — the token is a structural CLI marker emitted by the platform/CLI, NOT free
#: agent text (FK-55 §55.10.7: official service paths are not bash-spoofable).
#: It carries the spawn role for sub-agents AND the service attestation for the
#: privileged principals.
_ATTEST_FLAG = "--ak3-principal-attest"

#: Privileged principals — assumable only via an explicit service attestation
#: (FK-55 §55.3a source 4 / §55.10.1). Never inferred from context alone.
_PRIVILEGED: frozenset[Principal] = frozenset(
    {
        Principal.PIPELINE_DETERMINISTIC,
        Principal.ADMIN_SERVICE,
        Principal.HUMAN_CLI,
    }
)

#: Sub-agent roles — assumable for a spawned sub-agent via its structural spawn
#: attestation (FK-55 §55.3a source 1/3). ``orchestrator`` / ``interactive_agent``
#: are main-agent contexts, not sub-agent roles.
_SUBAGENT_ROLES: frozenset[Principal] = frozenset(
    {
        Principal.WORKER,
        Principal.QA_READER,
        Principal.ADVERSARIAL_WRITER,
        Principal.LLM_EVALUATOR,
    }
)

#: Least-privileged sub-agent principal. An unattested sub-agent fails closed to
#: this principal (no local filesystem capability — invariant
#: ``llm_evaluator_has_no_local_filesystem_capability``), NOT to ``worker``.
_LEAST_PRIVILEGED_SUBAGENT = Principal.LLM_EVALUATOR


class PrincipalResolver:
    """Resolves the technical :class:`Principal` from harness/event context.

    FK-55 §55.3a — Principal-Attestierung: the principal is derived *only* from
    technically attested context:

    1. Hook context (``principal_kind``: ``main`` vs ``subagent`` — the
       ``is_subagent`` signal of FK-55 §55.3a/§55.10.1).
    2. Active lock/run binding (``session_id`` / ``parent_session_id``).
    3. The structural spawn/service attestation in ``cli_args``.

    Prompt content, agent self-description, or command strings are **never** a
    valid attestation source (FK-55 §55.3a). Missing context resolves
    fail-closed to the most restrictive applicable principal (§55.10.1).
    """

    def resolve(self, event: HookEvent) -> Principal:
        """Return the attested principal for ``event``.

        Args:
            event: Harness-neutral hook event. Only ``principal_kind``,
                ``session_id``, ``parent_session_id`` and ``cli_args`` are
                consulted — never ``operation_args`` payload text (FK-55
                §55.3a).

        Returns:
            The resolved :class:`Principal`. Privileged and specific sub-agent
            principals require a valid structural attestation; otherwise the
            result is the fail-closed least-privileged applicable principal.
        """
        attested = self._attested_principal(event.cli_args)
        if event.principal_kind == "subagent":
            # A sub-agent's role comes ONLY from its structural attestation.
            # Without one it fails closed to the least-privileged sub-agent
            # principal — never to ``worker`` (FK-55 §55.3a / §55.10.1).
            if attested is not None and attested in _SUBAGENT_ROLES:
                return attested
            return _LEAST_PRIVILEGED_SUBAGENT
        # Main agent: only the three privileged principals are attestable.
        if attested is not None and attested in _PRIVILEGED:
            return attested
        if event.session_id:
            # is_subagent == false with an active run binding ⇒ orchestrator
            # (FK-55 §55.10.1: "is_subagent == false → mindestens orchestrator").
            return Principal.ORCHESTRATOR
        return Principal.INTERACTIVE_AGENT

    @staticmethod
    def _attested_principal(cli_args: list[str] | None) -> Principal | None:
        """Extract the attested principal from the structural ``cli_args`` pair.

        The attestation is the platform/CLI structural pair
        ``["--ak3-principal-attest", "<principal_value>"]``. An unknown value or
        a missing/dangling flag yields ``None`` (fail-closed — no attestation).
        Whether the attested value is *honored* depends on the principal_kind
        (sub-agent role vs privileged) and is decided in :meth:`resolve`.
        """
        if not cli_args:
            return None
        for index, token in enumerate(cli_args):
            if token != _ATTEST_FLAG:
                continue
            if index + 1 >= len(cli_args):
                return None
            try:
                return Principal(cli_args[index + 1])
            except ValueError:
                return None
        return None


__all__ = [
    "Principal",
    "PrincipalResolver",
]
