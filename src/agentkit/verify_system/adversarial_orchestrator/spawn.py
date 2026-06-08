"""AdversarialSpawner — Layer-3 mandatory-target spawn mechanics (FK-27 §27.6, FK-48).

Layer 2 can name concrete negative cases that Layer 3 MUST address (FK-48 §48.2
Mandatory Adversarial Targets). This module derives those targets from the
Layer-2 findings and produces a typed :class:`AdversarialSpawnRequest` — the
``agents_to_spawn`` orders the engine writes into the ``PhaseState`` so the
orchestrator spawns the adversarial worker on phase re-entry (FK-27 §27.6).

Sandbox-scoping (AG3-044 §2.1.6, FK-48 §48.1): every adversarial spawn writes
into ``_temp/adversarial/{story_id}/{epoch}/`` — a Protected-Path (AG3-023,
``governance.guard_system.protected_paths``) so a normal worker cannot tamper
with adversarial evidence. The spawner materialises the sandbox dir and writes a
typed ``ADVERSARIAL_TEST_SANDBOX`` envelope (the durable, ownership-clear record);
fail-closed/real, not a stub.

Adversarial-result processing (test-promotion / quarantine) is a follow-up story
(AG3-044 §2.1.6 out-of-scope) — this module provides only the spawn mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.artifacts import ArtifactEnvelope, ProducerType
from agentkit.artifacts.envelope import ENVELOPE_SCHEMA_VERSION
from agentkit.artifacts.producer import Producer, ProducerId
from agentkit.core_types import (
    ArtifactClass,
    EnvelopeStatus,
    Severity,
    SpawnKind,
    SpawnReason,
    SpawnRequest,
)
from agentkit.governance.guard_system.protected_paths import (
    is_adversarial_sandbox_path,
)
from agentkit.verify_system.register import (
    ADVERSARIAL_SANDBOX_PRODUCER,
    ADVERSARIAL_SANDBOX_STAGE,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.pipeline_engine.phase_executor import PhaseState
    from agentkit.verify_system.contract import VerifyContextBundle
    from agentkit.verify_system.protocols import Finding

#: Sandbox root segment (AG3-044 §2.1.6 / FK-48 §48.1).
ADVERSARIAL_SANDBOX_DIRNAME = "adversarial"


@dataclass(frozen=True)
class AdversarialTarget:
    """A mandatory adversarial target derived from a Layer-2 finding (FK-48 §48.2).

    Attributes:
        finding_id: The originating finding id (``layer.check``).
        source: Where the finding came from (e.g. ``"qa_review"``).
        normative_ref: Normative reference / finding message.
        open_part: The concrete open negative case the worker must test.
        mandatory: Always ``True`` for derived targets (FK-48 §48.2.2).
        test_anchor: POSIX-relative sandbox file the adversarial test goes into
            (AG3-044 AC8: each target carries a test anchor).
    """

    finding_id: str
    source: str
    normative_ref: str
    open_part: str
    mandatory: bool
    test_anchor: str


@dataclass(frozen=True)
class AdversarialSpawnRequest:
    """The typed result of an adversarial spawn order (FK-27 §27.6).

    Attributes:
        story_id: Story display id.
        epoch: Evidence-epoch token scoping the sandbox.
        sandbox_path: Absolute path of the materialised sandbox dir.
        targets: The mandatory adversarial targets to address.
        agents_to_spawn: The typed spawn orders to write into ``PhaseState``.
    """

    story_id: str
    epoch: str
    sandbox_path: Path
    targets: tuple[AdversarialTarget, ...]
    agents_to_spawn: tuple[SpawnRequest, ...]

    def apply_to_state(self, state: PhaseState) -> PhaseState:
        """Return a copy of ``state`` with the adversarial spawn orders set.

        FK-45 §45.3: the spawn orders live in ``PhaseState.agents_to_spawn`` —
        the single typed truth the orchestrator reacts to. This is the
        productive write that makes the spawn non-dead.

        Args:
            state: The phase state to augment.

        Returns:
            A new ``PhaseState`` carrying ``agents_to_spawn``.
        """
        return state.model_copy(
            update={"agents_to_spawn": list(self.agents_to_spawn)},
        )


class AdversarialSpawner:
    """Derives mandatory targets and requests the Layer-3 adversarial spawn."""

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        """Initialise with the producer-bound artifact manager.

        Args:
            artifact_manager: The AG3-023 manager (the only authorised
                envelope write path).
        """
        self._artifact_manager = artifact_manager

    def derive_targets(
        self,
        layer2_findings: list[Finding],
    ) -> list[AdversarialTarget]:
        """Derive >= 1 mandatory target per BLOCKING Layer-2 finding (FK-48 §48.2).

        Each BLOCKING Layer-2 finding names a concrete negative case Layer 3 must
        cover; the derived target carries a deterministic sandbox test anchor
        (AG3-044 AC8). Non-blocking findings are inspiration only (the explorative
        part of Layer 3) and are NOT turned into mandatory targets here.

        Args:
            layer2_findings: The Layer-2 findings of the current round.

        Returns:
            One :class:`AdversarialTarget` per BLOCKING finding, each with a test
            anchor (empty list when there are no blocking findings).
        """
        targets: list[AdversarialTarget] = []
        for index, finding in enumerate(layer2_findings):
            if finding.severity is not Severity.BLOCKING:
                continue
            finding_id = f"{finding.layer}.{finding.check}"
            targets.append(
                AdversarialTarget(
                    finding_id=finding_id,
                    source=finding.layer,
                    normative_ref=finding.message,
                    open_part=finding.suggestion or finding.message,
                    mandatory=True,
                    test_anchor=f"test_{finding.check}_{index}.py",
                )
            )
        return targets

    def request_spawn(
        self,
        ctx: VerifyContextBundle,
        targets: list[AdversarialTarget],
        *,
        story_id: str | None = None,
    ) -> AdversarialSpawnRequest:
        """Materialise the sandbox + build the adversarial spawn order (FK-27 §27.6).

        Creates the protected sandbox dir ``_temp/adversarial/{story_id}/{epoch}/``,
        writes a typed ``ADVERSARIAL_TEST_SANDBOX`` envelope (durable record) and
        returns the spawn orders (one ``SpawnRequest`` per target) to write into
        ``PhaseState.agents_to_spawn``. Fail-closed: a sandbox path that does not
        resolve as a Protected-Path is a hard error (the spawn evidence must be
        tamper-protected, AG3-023).

        Args:
            ctx: The verify-context bundle (story dir, run id, attempt/epoch).
            targets: The mandatory targets the adversarial worker must address.
            story_id: The authoritative story display id (the one
                ``run_qa_subflow`` was invoked with). When ``None`` it falls back
                to the story-dir name (the productive ``story_dir`` IS the story
                dir, so the name is the story id). Passing it explicitly avoids
                relying on the dir name when the caller already holds the id.

        Returns:
            An :class:`AdversarialSpawnRequest` with the materialised sandbox and
            the typed spawn orders.

        Raises:
            ValueError: When the resolved sandbox path is not a Protected-Path.
        """
        resolved_story_id = story_id if story_id is not None else _story_id_from_ctx(ctx)
        epoch = str(ctx.attempt)
        sandbox_path = (
            ctx.story_dir
            / "_temp"
            / ADVERSARIAL_SANDBOX_DIRNAME
            / resolved_story_id
            / epoch
        )
        sandbox_rel = (
            f"_temp/{ADVERSARIAL_SANDBOX_DIRNAME}/{resolved_story_id}/{epoch}"
        )
        # FAIL-CLOSED (AG3-023): the sandbox MUST resolve as a Protected-Path so
        # ordinary workers cannot tamper with adversarial evidence.
        if not is_adversarial_sandbox_path(sandbox_rel):
            raise ValueError(
                f"adversarial sandbox path {sandbox_rel!r} is not a "
                "Protected-Path (AG3-023 / FK-48 §48.1)",
            )
        sandbox_path.mkdir(parents=True, exist_ok=True)

        spawn_orders = tuple(
            SpawnRequest(
                kind=SpawnKind.ADVERSARIAL,
                spawn_reason=SpawnReason.REMEDIATION,
                target_id=target.finding_id,
                sandbox_path=f"{sandbox_rel}/{target.test_anchor}",
            )
            for target in targets
        )
        self._write_sandbox_envelope(ctx, resolved_story_id, sandbox_rel, targets)
        return AdversarialSpawnRequest(
            story_id=resolved_story_id,
            epoch=epoch,
            sandbox_path=sandbox_path,
            targets=tuple(targets),
            agents_to_spawn=spawn_orders,
        )

    def _write_sandbox_envelope(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        sandbox_rel: str,
        targets: list[AdversarialTarget],
    ) -> None:
        """Write the typed ADVERSARIAL_TEST_SANDBOX envelope (durable record)."""
        now = datetime.now(tz=UTC)
        envelope = ArtifactEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            story_id=story_id,
            run_id=ctx.run_id,
            stage=ADVERSARIAL_SANDBOX_STAGE,
            attempt=ctx.attempt,
            producer=Producer(
                type=ProducerType.WORKER,
                name=ADVERSARIAL_SANDBOX_PRODUCER,
                id=ProducerId(f"{ADVERSARIAL_SANDBOX_PRODUCER}-{ctx.run_id}"),
            ),
            started_at=now,
            finished_at=now,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
            payload={
                "sandbox_path": sandbox_rel,
                "targets": [
                    {
                        "finding_id": t.finding_id,
                        "source": t.source,
                        "open_part": t.open_part,
                        "test_anchor": t.test_anchor,
                    }
                    for t in targets
                ],
            },
        )
        self._artifact_manager.write(envelope)


def _story_id_from_ctx(ctx: VerifyContextBundle) -> str:
    """Resolve the story id from the verify-context bundle (fail-closed).

    Args:
        ctx: The verify-context bundle.

    Returns:
        The story id (from the story-dir name).
    """
    return ctx.story_dir.name


__all__ = [
    "ADVERSARIAL_SANDBOX_DIRNAME",
    "AdversarialSpawnRequest",
    "AdversarialSpawner",
    "AdversarialTarget",
]
