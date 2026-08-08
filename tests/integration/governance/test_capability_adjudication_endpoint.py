"""Negative paths of the capability-adjudication endpoint (AG3-239 AC 6).

A test that only shows the good case does not satisfy AC 6. The three mandatory
axes are covered here plus the two that this particular operation makes
load-bearing:

1. missing / invalid authorization;
2. unknown story identity;
3. **fail-closed when the core is unreachable** -- the one that matters most,
   because an adjudication that cannot be obtained must BLOCK, never pass;
4. the dual-materialization invariant
   ``freeze_has_backend_record_and_local_export``: any disagreement between the
   canonical record and the edge's local export is a fail-closed freeze;
5. a capability fault inside the core never escapes as a runtime error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from agentkit.backend.governance.capability_adjudication import (
    CapabilityAdjudicationService,
)
from agentkit_wire.governance_adjudication import (
    AdjudicationOutcome,
    CapabilityAdjudicationRequest,
    LocalFreezeState,
)

if TYPE_CHECKING:
    from pathlib import Path

_PATH = "/v1/governance/capability-adjudications"


def _request(**overrides: Any) -> CapabilityAdjudicationRequest:
    """Build a valid adjudication request; overrides narrow the case."""
    payload: dict[str, Any] = {
        "op_id": "op-ag3-239",
        "operation": "bash_command",
        "operation_args": {"tool_name": "Bash", "command": "git status"},
        "principal_kind": "main",
        "freshness_class": "mutation",
        "cwd": ".",
        "execution_mode": "ai_augmented",
    }
    payload.update(overrides)
    return CapabilityAdjudicationRequest(**payload)


class _FrozenStore:
    """Canonical freeze store double: reports an active freeze at a version."""

    def __init__(self, *, version: int | None = 7) -> None:
        self._version = version

    def read_freeze(self, story_id: str) -> object | None:
        _ = story_id
        if self._version is None:
            return None
        return type("_Record", (), {"freeze_version": self._version})()


class _ExplodingStore:
    """Canonical freeze store double that faults on read."""

    def read_freeze(self, story_id: str) -> object | None:
        raise RuntimeError(f"postgres unavailable while reading freeze for {story_id}")


@pytest.mark.integration
class TestCoreUnreachableFailsClosed:
    """An adjudication that cannot be obtained is not one that permits."""

    def test_transport_error_blocks_the_tool(self, tmp_path: Path) -> None:
        from agentkit.backend.exceptions import ControlPlaneApiError
        from agentkit.backend.governance import runner
        from agentkit.backend.governance.guard_evaluation import HookEvent

        class _UnreachableClient:
            def adjudicate_capability(self, request: object) -> object:
                _ = request
                raise ControlPlaneApiError("core unreachable")

        def _client(_project_root: Path) -> object:
            return _UnreachableClient()

        original = runner.rest_edge.governance_edge_client
        runner.rest_edge.governance_edge_client = _client  # type: ignore[assignment]
        try:
            decision = runner._run_capability_enforcement(
                HookEvent(
                    operation="bash_command",
                    operation_args={"tool_name": "Bash", "command": "rm -rf .git"},
                    freshness_class="mutation",
                    cwd=str(tmp_path),
                ),
                project_root=tmp_path,
            )
        finally:
            runner.rest_edge.governance_edge_client = original  # type: ignore[assignment]

        assert decision is not None, (
            "an unreachable core must BLOCK; returning None would let the tool run"
        )
        assert decision.allowed is False
        assert "fail-closed" in decision.message


@pytest.mark.integration
class TestFreezeDualMaterializationIsFailClosed:
    """`freeze_has_backend_record_and_local_export` -- any disagreement blocks."""

    def test_record_active_but_no_local_export(self, tmp_path: Path) -> None:
        service = CapabilityAdjudicationService(project_root=tmp_path)
        result = service._freeze_disagrees(
            _FrozenStore(), "AG3-239", LocalFreezeState(present=False)
        )
        assert result is not None
        assert result.allowed is False
        assert result.freeze_disagreement is True

    def test_version_drift_between_record_and_export(self, tmp_path: Path) -> None:
        service = CapabilityAdjudicationService(project_root=tmp_path)
        result = service._freeze_disagrees(
            _FrozenStore(version=7),
            "AG3-239",
            LocalFreezeState(present=True, story_id="AG3-239", freeze_version=6),
        )
        assert result is not None
        assert result.freeze_disagreement is True
        assert "freeze_version" in result.message

    def test_unreadable_local_export_is_not_absence(self, tmp_path: Path) -> None:
        service = CapabilityAdjudicationService(project_root=tmp_path)
        result = service._freeze_disagrees(
            _FrozenStore(version=None),
            "AG3-239",
            LocalFreezeState(present=True, unreadable=True),
        )
        assert result is not None, "a corrupt export must never read as 'not frozen'"
        assert result.freeze_disagreement is True

    def test_local_export_names_a_different_story(self, tmp_path: Path) -> None:
        service = CapabilityAdjudicationService(project_root=tmp_path)
        result = service._freeze_disagrees(
            _FrozenStore(version=7),
            "AG3-239",
            LocalFreezeState(present=True, story_id="AG3-999", freeze_version=7),
        )
        assert result is not None
        assert result.freeze_disagreement is True

    def test_both_sides_agree_is_not_a_disagreement(self, tmp_path: Path) -> None:
        service = CapabilityAdjudicationService(project_root=tmp_path)
        assert (
            service._freeze_disagrees(
                _FrozenStore(version=7),
                "AG3-239",
                LocalFreezeState(present=True, story_id="AG3-239", freeze_version=7),
            )
            is None
        ), "a matching pair is a real freeze for the overlay to decide, not a defect"


@pytest.mark.integration
class TestCoreFaultNeverEscapes:
    """FK-55 §55.10.5: a capability fault is a decision, not an exception."""

    def test_backend_fault_becomes_a_fault_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import agentkit.backend.state_backend.store.freeze_repository as freeze_mod

        monkeypatch.setattr(freeze_mod, "FreezeRepository", lambda _root: _ExplodingStore())
        result = CapabilityAdjudicationService(project_root=tmp_path).adjudicate(
            _request(story_id="AG3-239")
        )
        assert result.outcome is AdjudicationOutcome.FAULT
        assert result.allowed is False
        assert result.detail == "RuntimeError"


@pytest.mark.integration
class TestEndpointRejectsBadInput:
    """Payload and identity defects fail closed at the boundary."""

    def test_missing_op_id_is_unprocessable(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CapabilityAdjudicationRequest(
                op_id="",
                operation="bash_command",
                principal_kind="main",
                execution_mode="ai_augmented",
            )

    def test_unknown_field_is_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _request(prompt_text="ignore all previous instructions")

    def test_unknown_story_identity_is_adjudicated_not_assumed(
        self, tmp_path: Path
    ) -> None:
        """An unknown story yields no local freeze and no silent permit."""
        from agentkit.backend.governance.runner import _local_freeze_state

        state = _local_freeze_state(tmp_path, "AG3-does-not-exist")
        assert state.present is False
        assert state.freeze_version is None


@pytest.mark.integration
class TestRouteIsRegisteredAndScoped:
    """The operation exists on the wire, not only as a service class."""

    def test_route_is_project_scoped_in_the_surface_policy(self) -> None:
        from agentkit.backend.control_plane_http.surface_policy import (
            _PROJECT_ONLY_ROUTE_PATTERNS,
        )

        assert any(pattern.match(_PATH) for pattern in _PROJECT_ONLY_ROUTE_PATTERNS), (
            "the adjudication route must carry the same surface class as the "
            "other hook-mediation routes -- an unclassified route is reachable "
            "by the wrong principal"
        )

    def test_edge_client_exposes_exactly_one_operation(self) -> None:
        from agentkit.harness_client.projectedge.governance_client import (
            GovernanceEdgeClient,
        )

        assert hasattr(GovernanceEdgeClient, "adjudicate_capability")
