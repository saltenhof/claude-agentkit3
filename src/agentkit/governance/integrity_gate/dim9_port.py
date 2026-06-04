"""Productive Dimension-9 Sonar port (FK-35 §35.2.4a, consumes AG3-052).

The IntegrityGate Dim 9 only **verifies** a commit-bound ``sonarqube_gate``
attestation (FK-35 §35.2.4a "verifiziert nur — vermisst nicht neu").  This
module wires the productive :class:`SonarDimensionPort` the composition root
hands to the gate for live Closure runs by **consuming the AG3-052 capability**
end-to-end — there is NO hand-rolled attestation loader and NO second gate
mechanic (AG3-034 Remediation R2-C/A2):

* applicability is resolved by :func:`build_sonar_gate_port_for_run` (which calls
  ``resolve_applicability`` internally) from the project ``sonarqube.available``
  flag and the story's decoupled ``mode`` axis (FK-24 §24.3.3) + story type;
* the commit-bound attestation, ledger, current issues and the post-apply
  re-read are resolved by the capability port's ``resolve_inputs``;
* the green/stale/ledger/config verdict is produced by
  :func:`evaluate_sonarqube_gate` — the SAME canonical evaluator the QA-subflow
  gate point uses (AG3-052 AC8 "consumers").

Attestation binding to the integrated merge candidate (FK-29 §29.1a) is produced
by the Closure pre-merge scan, which is OUT OF SCOPE for AG3-034.  When that scan
artefact is absent for an APPLICABLE run, :func:`build_sonar_gate_port_for_run`
returns a fail-closed APPLICABLE port whose inputs carry ``attestation = None``;
:func:`evaluate_sonarqube_gate` then yields a ``failed`` outcome
(``attestation_unreadable``) which Dim 9 maps to a fail-closed ``SONAR_NOT_GREEN``
(configured-but-unreachable, never a silent skip; FK-33 §33.6.5 "absent ≠
broken" applies only to ``available == false``, the not-applicable branch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.config.models import SonarQubeConfig
    from agentkit.governance.integrity_gate import IntegrityGateContext
    from agentkit.story_context_manager.models import StoryContext


class ProductiveSonarDimensionPort:
    """Productive Dim-9 capability seam wired by the composition root (R2-C/A2).

    Consumes the AG3-052 ``sonarqube_gate`` capability end-to-end:
    :func:`build_sonar_gate_port_for_run` resolves applicability + the
    commit-bound inputs, and :func:`evaluate_sonarqube_gate` produces the
    canonical :class:`SonarGateOutcome`.  No attestation is loaded or evaluated
    locally (no second Sonar truth).

    Args:
        sonar_config_loader: Resolves the project ``SonarQubeConfig`` (or
            ``None`` when the project omits the stanza) for the gate context.
            Injected so ``governance`` stays free of project-config /
            state-backend reads (truth boundary; the composition root owns it).
        story_context_loader: Resolves the run's :class:`StoryContext` for the
            gate context (story type + mode + worktree/project root).  ``None``
            when the context is unreadable.
    """

    def __init__(
        self,
        sonar_config_loader: Callable[
            [IntegrityGateContext], SonarQubeConfig | None
        ],
        story_context_loader: Callable[
            [IntegrityGateContext], StoryContext | None
        ],
    ) -> None:
        self._sonar_config_loader = sonar_config_loader
        self._story_context_loader = story_context_loader

    def resolve_dim9_outcome(self, gate_ctx: object) -> Dim9Resolution:
        """Resolve the per-run Dim-9 capability outcome (AG3-052 consumer path).

        Builds the AG3-052 port for the run, resolves its inputs and runs
        :func:`evaluate_sonarqube_gate`.  A not-applicable resolution
        (``available == false`` / fast / non-code) yields a not-applicable
        :class:`Dim9Resolution` (Dim 9 dropped upstream); an APPLICABLE run with
        no resolvable attestation yields a ``failed`` outcome (fail-closed).
        """
        from agentkit.governance.integrity_gate import IntegrityGateContext
        from agentkit.verify_system.sonarqube_gate import (
            SonarApplicability,
            build_sonar_gate_port_for_run,
            evaluate_sonarqube_gate,
        )

        if not isinstance(gate_ctx, IntegrityGateContext):  # pragma: no cover
            msg = f"gate_ctx must be an IntegrityGateContext; got {gate_ctx!r}"
            raise TypeError(msg)

        story_context = self._story_context_loader(gate_ctx)
        if story_context is None:
            # No resolvable context for a code story -> cannot prove a deliberate
            # skip -> APPLICABLE + no outcome -> Dim 9 fails closed downstream.
            return Dim9Resolution(
                applicability=SonarApplicability.APPLICABLE, outcome=None
            )

        config = self._sonar_config_loader(gate_ctx)
        port = build_sonar_gate_port_for_run(
            config, story_context, gate_ctx.story_dir
        )
        if port is None:
            # build_sonar_gate_port_for_run returns None for a DELIBERATE absence
            # (no stanza / available==false / non-code-producing) -> Dim 9 skips
            # (no fail-closed; FK-33 §33.6.5 absent != broken).
            return Dim9Resolution(
                applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE,
                outcome=None,
            )

        inputs = port.resolve_inputs(story_context.story_id, gate_ctx.story_dir)
        if inputs.applicability is not SonarApplicability.APPLICABLE:
            # fast / unavailable resolution surfaced by the port -> Dim 9 dropped.
            return Dim9Resolution(applicability=inputs.applicability, outcome=None)

        outcome = evaluate_sonarqube_gate(
            applicability=inputs.applicability,
            attestation=inputs.attestation,
            main_head_revision=inputs.main_head_revision,
            ledger_entries=inputs.ledger_entries,
            current_issues=inputs.current_issues,
            issue_applier=inputs.issue_applier,
            post_apply_reader=inputs.post_apply_reader,
        )
        return Dim9Resolution(applicability=inputs.applicability, outcome=outcome)


__all__ = ["ProductiveSonarDimensionPort"]
