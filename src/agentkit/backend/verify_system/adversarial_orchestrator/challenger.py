"""Adversarial QA layer -- Layer-3 destructive testing + multi-LLM sparring (FK-48 §48.1).

AG3-079: the real Schicht-3 runtime. The adversarial agent itself is a
Harness-Sub-Agent (FK-48 §48.1.1) started via the existing :class:`AdversarialSpawner`
(``spawn.py``); a deterministic Zone-2 runtime
(:mod:`agentkit.backend.verify_system.adversarial_orchestrator.runtime`) orchestrates the
FK-48 §48.1.3 phases AFTER the sub-agent ran: it reads the sandbox result, forces
the mandatory sparring call over the AG3-065 transport, emits the five adversarial
telemetry events, promotes / quarantines the sandbox tests, materialises
``adversarial.json`` and feeds unmet mandatory targets back to Layer 2.

NO PASS without real evidence (FK-48 §48.1.8): a run with no executed test, a
failed sparring call, a proven finding or an unfulfilled mandatory target FAILs.
When the runtime dependencies (transport / telemetry) are not wired, the layer
fails closed (a BLOCKING result, never a silent passthrough PASS).

AG3-044 (FK-27 §27.6 / FK-48 §48.2): the mandatory-target derivation is owned by
:class:`AdversarialSpawner` (now FK-48 §48.2.2-conform via
``extract_mandatory_targets``); the spawn itself (sandbox + ``agents_to_spawn``)
stays in that module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.prompt_audit_support import PromptAuditMixin
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.verify_system.adversarial_orchestrator.spawn import (
        AdversarialSpawner,
        AdversarialTarget,
    )
    from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.backend.verify_system.llm_evaluator.llm_client import (
        LlmClient,
        RolePoolResolver,
    )
    from agentkit.backend.verify_system.protocols import StoryContextQueryPort

#: Sandbox root segment under the story dir (``_temp/adversarial/...``).
_SANDBOX_DIRNAME = "adversarial"

#: Project ``tests/`` root segment (promotion target, FK-48 §48.1.5).
_TESTS_DIRNAME = "tests"


class AdversarialChallenger(PromptAuditMixin):
    """Layer 3: Adversarial destructive testing (FK-48 §48.1).

    Drives the deterministic Layer-3 runtime over the Harness-Sub-Agent's sandbox
    evidence (the sub-agent itself is the only allowed mock boundary). Returns a
    DERIVED :class:`LayerResult` — no passthrough PASS.

    Satisfies the :class:`~agentkit.backend.verify_system.protocols.QALayer` protocol.

    Args:
        artifact_manager: Producer-bound ArtifactManager (prompt-audit + the only
            authorised ``_temp/qa/`` write path for ``adversarial.json``).
        story_context_port: Run-correlation port (forwarded to the mixin; also
            used to resolve the run scope / sandbox epoch at evaluate time).
        spawner: The :class:`AdversarialSpawner` used to derive mandatory targets
            (FK-48 §48.2). ``None`` keeps target derivation unwired.
        sparring_client: The AG3-065 verify-LLM-transport for the mandatory
            sparring call (consumed, not rebuilt). ``None`` => the runtime is
            unwired and the layer fails closed at evaluate time.
        telemetry_emitter: The emitter for the five adversarial telemetry events.
            ``None`` => unwired -> fail-closed.
        sparring_resolver: Optional role->pool resolver (records the concrete
            sparring pool label in the telemetry / artefact).
    """

    def __init__(
        self,
        *,
        artifact_manager: ArtifactManager | None = None,
        story_context_port: StoryContextQueryPort | None = None,
        spawner: AdversarialSpawner | None = None,
        sparring_client: LlmClient | None = None,
        telemetry_emitter: EventEmitter | None = None,
        sparring_resolver: RolePoolResolver | None = None,
    ) -> None:
        super().__init__(
            artifact_manager=artifact_manager,
            story_context_port=story_context_port,
        )
        self._spawner = spawner
        self._artifact_manager = artifact_manager
        self._sparring_client = sparring_client
        self._telemetry_emitter = telemetry_emitter
        self._sparring_resolver = sparring_resolver

    def derive_adversarial_targets(
        self,
        layer2_findings: list[Finding],
        remediation_round: int = 1,
    ) -> list[AdversarialTarget]:
        """Derive mandatory adversarial targets from Layer-2 findings (FK-48 §48.2.2).

        Delegates to the wired :class:`AdversarialSpawner`. Returns an empty list
        when no spawner is wired or no ``assertion_weakness`` finding qualifies.

        Args:
            layer2_findings: The Layer-2 findings of the current round.
            remediation_round: The current remediation round (1-based).

        Returns:
            The mandatory adversarial targets (FK-48 §48.2.2).
        """
        if self._spawner is None:
            return []
        return self._spawner.extract_mandatory_targets(
            layer2_findings, remediation_round
        )

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"adversarial"``.
        """
        return "adversarial"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Run the real Layer-3 adversarial runtime (FK-48 §48.1, no passthrough).

        ``review_input`` is accepted but ignored by Layer 3 (Adversarial); it is
        only used by Layer-2 reviewers.

        Drives the deterministic runtime over the Harness-Sub-Agent's sandbox
        evidence: reads the sandbox result, forces the mandatory sparring call,
        emits the five adversarial telemetry events, promotes / quarantines the
        sandbox tests, materialises ``adversarial.json`` and derives the verdict.
        Fails closed (BLOCKING) when the runtime is unwired or the sandbox holds
        no evidence — NEVER a silent PASS.

        Args:
            ctx: Story context (story id / project root / run correlation).
            story_dir: Directory containing story artifacts (sandbox parent).
            review_input: Ignored by Layer 3. Accepted for protocol compatibility.

        Returns:
            The DERIVED :class:`LayerResult` (FK-48 §48.1.8).
        """
        del review_input  # Layer 3 does not use review_input.
        prompt_audit = self._materialize_prompt_audit(
            layer_name=self.name,
            template_name="qa-adversarial-review",
            ctx=ctx,
            story_dir=story_dir,
        )
        if (
            self._sparring_client is None
            or self._telemetry_emitter is None
            or self._artifact_manager is None
        ):
            return self._fail_closed(
                "adversarial runtime is not wired (no sparring transport / "
                "telemetry emitter / artifact manager) — FAIL-CLOSED, no "
                "passthrough PASS (FK-48 §48.1).",
                prompt_audit,
            )

        run_id, attempt = self._resolve_run_scope(story_dir)
        sandbox_dir = self._sandbox_dir(story_dir, ctx.story_id, attempt)
        tests_root = self._tests_root(ctx)

        from agentkit.backend.verify_system.adversarial_orchestrator.runtime.artifact import (
            AdversarialResultReadError,
        )
        from agentkit.backend.verify_system.adversarial_orchestrator.runtime.runner import (
            run_adversarial_runtime,
        )

        try:
            runtime_result = run_adversarial_runtime(
                artifact_manager=self._artifact_manager,
                emitter=self._telemetry_emitter,
                sparring_client=self._sparring_client,
                sandbox_dir=sandbox_dir,
                tests_root=tests_root,
                story_id=ctx.story_id,
                run_id=run_id,
                attempt=attempt,
                resolver=self._sparring_resolver,
            )
        except AdversarialResultReadError as exc:
            return self._fail_closed(str(exc), prompt_audit)

        result = runtime_result.layer_result
        return LayerResult(
            layer=result.layer,
            passed=result.passed,
            findings=result.findings,
            metadata={
                **result.metadata,
                "prompt_audit": prompt_audit,
                # FK-48 §48.1.7 / FIX-THE-MODEL: the runtime already materialised
                # the canonical ``adversarial.json`` (schema 3.1) via the
                # ArtifactManager. Signal the subflow to NOT overwrite it with the
                # generic LayerResult projection (single source of truth, no second
                # adversarial-artefact write).
                "artifact_materialized": True,
                "resolution_feedback": {
                    f"{layer}:{check}": status.value
                    for (layer, check), status in (
                        runtime_result.resolution_feedback.items()
                    )
                },
            },
        )

    def _fail_closed(
        self,
        reason: str,
        prompt_audit: dict[str, object],
    ) -> LayerResult:
        """Return a BLOCKING Layer-3 result (fail-closed; no PASS without evidence)."""
        return LayerResult(
            layer=self.name,
            passed=False,
            findings=(
                Finding(
                    layer=self.name,
                    check="adversarial_runtime",
                    severity=Severity.BLOCKING,
                    message=reason,
                    trust_class=TrustClass.SYSTEM,
                ),
            ),
            metadata={"prompt_audit": prompt_audit},
        )

    def _resolve_run_scope(self, story_dir: Path) -> tuple[str, int]:
        """Resolve ``(run_id, attempt)`` via the story-context port (fail-soft).

        Returns ``("adversarial-run", 1)`` when no run scope is resolvable (e.g. a
        unit fixture without a persisted run) so the sandbox epoch is still a
        deterministic value matching the spawn default (``epoch = attempt``).
        """
        port = self._prompt_story_context_port
        if port is None:
            return ("adversarial-run", 1)
        scope = port.resolve_run_scope(story_dir)
        if scope is None:
            return ("adversarial-run", 1)
        return (scope.run_id, scope.attempt)

    def _sandbox_dir(self, story_dir: Path, story_id: str, attempt: int) -> Path:
        """Resolve the protected sandbox dir for this story/epoch (FK-48 §48.1).

        Mirrors :meth:`AdversarialSpawner.request_spawn`: the sandbox lives at
        ``{story_dir}/_temp/adversarial/{story_id}/{epoch}/`` with
        ``epoch == attempt``.
        """
        return story_dir / "_temp" / _SANDBOX_DIRNAME / story_id / str(attempt)

    def _tests_root(self, ctx: StoryContext) -> Path:
        """Resolve the project ``tests/`` root (promotion target, FK-48 §48.1.5)."""
        if ctx.project_root is not None:
            return ctx.project_root / _TESTS_DIRNAME
        # No project root (unit fixture): use the story dir's sibling tests root.
        return ctx.project_root or _missing_tests_root()


def _missing_tests_root() -> Path:
    """Return a non-existent tests root (promotion then promotes nothing)."""
    from pathlib import Path

    return Path("/__agentkit_no_tests_root__")


__all__ = ["AdversarialChallenger"]
