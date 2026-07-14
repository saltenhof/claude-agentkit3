"""Real REST/Postgres proof for lazy CCAG permission-request escalation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.integration.governance_hooks.ccag_rest_support import (
    PROJECT,
    RUN,
    STORY,
    hook_event,
    publish_story_binding,
)
from tests.integration.governance_hooks.conftest import write_control_plane_config
from tests.phase_state_factory import make_phase_state

from agentkit.backend.governance.ccag.permission_commands import OpenPermissionRequestCommand
from agentkit.backend.governance.ccag.permission_service import PermissionService
from agentkit.backend.governance.runner import run_hook
from agentkit.backend.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseName,
    PhaseStatus,
)
from agentkit.backend.state_backend.store.permission_lease_repository import (
    StateBackendPermissionLeaseRepository,
)
from agentkit.backend.state_backend.store.permission_request_repository import (
    StateBackendPermissionRequestRepository,
)
from agentkit.backend.state_backend.store.phase_envelope_repository import (
    StateBackendPhaseEnvelopeRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.guard_evaluation import HookEvent
    from agentkit.backend.pipeline_engine.phase_executor.models import PhaseState


@pytest.fixture(autouse=True)
def _allow_read_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run CCAG from a project root with a real matching allow rule."""
    rules_dir = tmp_path / ".agentkit" / "ccag" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "global.yaml").write_text(
        "rules:\n"
        "  - id: allow-read-rest-integration\n"
        "    tool: Read\n"
        "    allow_pattern: '.*'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)


def _prepare_run(project_root: Path, base_url: str, status: PhaseStatus) -> HookEvent:
    worktree = str(project_root / "worktree")
    (project_root / "worktree").mkdir()
    publish_story_binding(project_root, worktree)
    write_control_plane_config(project_root, base_url)
    StateBackendPhaseEnvelopeRepository(project_root / "stories" / STORY).save_state(
        make_phase_state(story_id=STORY, run_id=RUN, status=status)
    )
    return hook_event(worktree, operation="file_read")


def _open_request(request_id: str, *, expired: bool) -> None:
    clock = (lambda: datetime(2020, 1, 1, tzinfo=UTC)) if expired else None
    PermissionService(
        StateBackendPermissionRequestRepository(),
        StateBackendPermissionLeaseRepository(),
        clock=clock,
    ).open(
        OpenPermissionRequestCommand(
            request_id=request_id,
            project_key=PROJECT,
            story_id=STORY,
            run_id=RUN,
            principal_type="worker",
            tool_name="Read",
            operation_class="read",
            path_classes=("content_plane",),
            request_fingerprint=f"fingerprint-{request_id}",
            ttl_seconds=1 if expired else 1800,
        )
    )


def _state(project_root: Path) -> PhaseState | None:
    return StateBackendPhaseEnvelopeRepository(
        project_root / "stories" / STORY
    ).load_state(STORY, PhaseName.IMPLEMENTATION)


def test_expired_request_escalates_run_through_real_rest_dispatch(
    tmp_path: Path, control_plane_base_url: str, postgres_isolated_schema: str
) -> None:
    """A real REST read lazily expires the request and escalates run state."""
    del postgres_isolated_schema
    event = _prepare_run(tmp_path, control_plane_base_url, PhaseStatus.IN_PROGRESS)
    _open_request("request-expired-rest", expired=True)

    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)

    assert verdict.allowed is True, verdict
    state = _state(tmp_path)
    assert state is not None
    assert state.status is PhaseStatus.ESCALATED
    assert state.escalation_reason is EscalationReason.PERMISSION_REQUEST_EXPIRED


def test_fresh_request_does_not_escalate_through_real_rest_dispatch(
    tmp_path: Path, control_plane_base_url: str, postgres_isolated_schema: str
) -> None:
    """A fresh central request leaves the productive run state unchanged."""
    del postgres_isolated_schema
    event = _prepare_run(tmp_path, control_plane_base_url, PhaseStatus.IN_PROGRESS)
    _open_request("request-fresh-rest", expired=False)

    run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)

    state = _state(tmp_path)
    assert state is not None
    assert state.status is PhaseStatus.IN_PROGRESS


def test_already_escalated_run_is_idempotent_through_real_rest_dispatch(
    tmp_path: Path, control_plane_base_url: str, postgres_isolated_schema: str
) -> None:
    """Lazy expiry never overwrites an existing escalation reason."""
    del postgres_isolated_schema
    event = _prepare_run(tmp_path, control_plane_base_url, PhaseStatus.IN_PROGRESS)
    repository = StateBackendPhaseEnvelopeRepository(tmp_path / "stories" / STORY)
    repository.save_state(
        make_phase_state(
            story_id=STORY,
            run_id=RUN,
            status=PhaseStatus.ESCALATED,
            escalation_reason=EscalationReason.GOVERNANCE_VIOLATION,
        )
    )
    _open_request("request-expired-idempotent-rest", expired=True)

    run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)

    state = _state(tmp_path)
    assert state is not None
    assert state.escalation_reason is EscalationReason.GOVERNANCE_VIOLATION


def test_missing_project_token_logs_named_escalation_degradation_and_continues(
    tmp_path: Path,
    control_plane_base_url: str,
    postgres_isolated_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing REST auth is observable while lazy escalation remains best-effort."""
    del postgres_isolated_schema
    event = _prepare_run(tmp_path, control_plane_base_url, PhaseStatus.IN_PROGRESS)
    _open_request("request-expired-no-token", expired=True)
    monkeypatch.delenv("AGENTKIT_PROJECT_API_TOKEN")

    with caplog.at_level(logging.WARNING, logger="agentkit.backend.governance.runner"):
        verdict = run_hook(
            "ccag_gatekeeper", event, phase="pre", project_root=tmp_path
        )

    assert verdict.allowed is True
    assert "permission_request_ttl_escalation_degraded" in caplog.text
    state = _state(tmp_path)
    assert state is not None
    assert state.status is PhaseStatus.IN_PROGRESS
