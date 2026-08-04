"""Tests for the VerifySystem Capability-A-Top-Komponente.

The facade is the sole entry point for cross-BC callers
(``concept/_meta/bc-cut-decisions.md`` §"BC 2: verify-system",
FK-07 §7.4.2, FK-27). These tests cover construction and pure-delegation
behaviour for the operations consumed by ``agentkit.backend.implementation``.

Wertebereich seit AG3-021: ``Severity`` ist BLOCKING/MAJOR/MINOR und
``PolicyVerdict`` ist PASS/FAIL.
"""

from __future__ import annotations

from inspect import Parameter, signature

import pytest

from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system import VerifySystem
from agentkit.backend.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    QALayer,
    Severity,
    TrustClass,
)


class TestVerifySystemFacade:
    """Construction and delegation behaviour of VerifySystem."""

    def test_create_default_returns_configured_facade(self) -> None:
        verify_system = make_test_verify_system()
        assert isinstance(verify_system, VerifySystem)
        assert isinstance(verify_system.policy_engine, PolicyEngine)
        assert isinstance(
            verify_system.layer_3, AdversarialChallenger
        )

    def test_create_default_uses_canonical_story_type_threshold(self) -> None:
        verify_system = make_test_verify_system()

        assert verify_system.policy_engine.threshold_for(StoryType.IMPLEMENTATION) == 3

    def test_create_default_has_no_keyword_override_channel(self) -> None:
        parameters = signature(VerifySystem.create_default).parameters.values()
        assert all(parameter.kind is not Parameter.VAR_KEYWORD for parameter in parameters)

        with pytest.raises(TypeError, match="unexpected keyword argument"):
            VerifySystem.create_default(
                artifact_manager=_RecordingArtifactManagerForTests(),
                max_major_findings=1,
            )

    def test_facade_is_frozen_dataclass(self) -> None:
        """The facade must be immutable (FrozenInstanceError on assignment)."""
        verify_system = make_test_verify_system()
        try:
            verify_system.policy_engine = PolicyEngine()  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 -- dataclasses.FrozenInstanceError
            assert "frozen" in str(exc).lower() or exc.__class__.__name__ == (
                "FrozenInstanceError"
            )
        else:
            msg = "VerifySystem must be a frozen dataclass"
            raise AssertionError(msg)

    def test_policy_engine_decide_pass_without_findings(self) -> None:
        verify_system = make_test_verify_system()
        decision = verify_system.policy_engine.decide(
            [LayerResult(layer="structural", passed=True, findings=())],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({4}),
        )
        assert decision.passed is True
        assert decision.status == "PASS"
        assert decision.blocking_findings == ()

    def test_policy_engine_decide_fail_on_system_blocking(self) -> None:
        verify_system = make_test_verify_system()
        result = LayerResult(
            layer="structural",
            passed=False,
            findings=(
                Finding(
                    layer="structural",
                    check="missing",
                    severity=Severity.BLOCKING,
                    message="blocking finding",
                    trust_class=TrustClass.SYSTEM,
                ),
            ),
        )
        decision = verify_system.policy_engine.decide(
            [result],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({4}),
        )
        assert decision.passed is False
        assert decision.status == "FAIL"
        assert len(decision.blocking_findings) == 1

    def test_layer_3_is_the_adversarial_qa_layer(self) -> None:
        """``layer_3`` is the ONE name for the adversarial layer.

        The ``adversarial_challenger`` / ``adversarial_layer()`` compat surface
        that mirrored it is removed (2026-08-02): three spellings for one field
        is exactly what the no-compat-layers rule forbids.
        """
        verify_system = make_test_verify_system()
        layer = verify_system.layer_3
        assert isinstance(layer, QALayer)
        assert layer.name == "adversarial"
        assert not hasattr(verify_system, "adversarial_challenger")
        assert not hasattr(verify_system, "adversarial_layer")
        assert not hasattr(verify_system, "policy_decision")


# ---------------------------------------------------------------------------
# Local test helpers (AG3-026 Re-Review: VerifySystem.create_default braucht
# einen ArtifactManager als Pflicht-Argument; Recording-Test-Double inline
# ohne Cross-Module-Helper, um pytest/mypy-Pfad-Konflikte zu vermeiden).
# ---------------------------------------------------------------------------

from agentkit.backend.artifacts import ArtifactEnvelope as _AGAEnvelope  # noqa: E402
from agentkit.backend.artifacts import ArtifactManager as _AGAManager  # noqa: E402
from agentkit.backend.artifacts import ArtifactReference as _AGARef  # noqa: E402


class _RecordingArtifactManagerForTests(_AGAManager):
    """In-memory ArtifactManager for unit tests (no MagicMock)."""

    def __init__(self) -> None:
        self.written_envelopes: list[_AGAEnvelope] = []

    def write(self, envelope: _AGAEnvelope) -> _AGARef:
        self.written_envelopes.append(envelope)
        return _AGARef(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"rec/{envelope.stage}/{envelope.attempt}",
        )


def make_test_verify_system() -> VerifySystem:
    """Build a VerifySystem wired with a recording ArtifactManager."""
    return VerifySystem.create_default(
        artifact_manager=_RecordingArtifactManagerForTests(),
    )
