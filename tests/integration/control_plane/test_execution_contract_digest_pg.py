"""Integration: AG3-143 execution-contract-digest end-to-end against REAL Postgres.

Drives the PUBLIC :class:`ControlPlaneRuntimeService` API (``start_phase``)
against the real Postgres backend -- true phase boundaries, real digest
gathering (project registration, story specification, run-prompt-pin), never
fabricated:

* AC1/AC2 -- a real setup start atomically persists the run's
  ``execution_contract_digest`` together with the claim-CAS finalize; a
  component that cannot be resolved (no project registration, no resolvable
  prompt binding) deterministically REJECTS the fresh setup start -- no
  engine dispatch runs, no run ever enters the execution regime without a
  digest.
* AC5 -- the digest is queryable read-only after insert (no update path
  anywhere in this module's API surface).
* AC4 -- the "pinned-for-new-runs" two-run scenario: a project-config change
  AFTER a run starts leaves that run's persisted digest unchanged; a NEW run
  started afterwards gets a DIFFERENT digest.
* AC9 -- Postgres-only fail-closed (K5): the standalone insert/load facade
  functions raise ``ConfigError`` on a non-Postgres backend; no SQLite mirror.

``tests/integration/control_plane/`` is NOT in the conftest Postgres
auto-attach allow-list (mirrors the sibling AG3-142 ownership-fencing suite),
so this module requests the isolation fixture explicitly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from agentkit.backend.control_plane.models import PhaseDispatchResult, PhaseMutationRequest
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.installer.paths import PROMPT_BUNDLE_STORE_ENV, prompt_bundle_store_dir
from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.backend.prompt_runtime.execution_contract import ExecutionContractDigestRecord
from agentkit.backend.state_backend.store import (
    boot_backend_instance_identity_global,
    insert_execution_contract_digest_global,
    load_active_run_ownership_record_global,
    load_execution_contract_digest_global,
    save_story_context_global,
)
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import StorySpecification
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-digest"


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    """Bind the per-test isolated Postgres control-plane schema (K5 Postgres-only)."""
    del postgres_isolated_schema


class _AdmittedDispatcher:
    """A dispatcher that always reports the phase as completed (real engine untested)."""

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


def _real_digest_service(*, now: datetime, instance_id: str) -> ControlPlaneRuntimeService:
    """A service with the REAL Postgres store but a faked engine dispatch.

    AG3-143's constructor DI-defaults the digest reader to a trivial fake
    whenever ``phase_dispatcher`` is injected (protecting the wider existing
    test corpus that fakes the dispatcher). These digest tests explicitly
    override that default back to the REAL gathering
    (``_build_execution_contract_digest``) so the assertions below prove
    genuine project-registration/story-specification/run-prompt-pin
    resolution, not the DI placeholder.
    """
    identity = boot_backend_instance_identity_global(instance_id, now)
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: now,
        instance_identity=identity,
    )
    service._execution_contract_digest_reader = (  # noqa: SLF001 -- force REAL gathering
        lambda request, run_id: service._build_execution_contract_digest(  # noqa: SLF001
            request=request, run_id=run_id,
        )
    )
    return service


def _request(*, story_id: str, op_id: str, session_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=[f"T:/worktrees/{story_id}"],
    )


def _seed_story(tmp_path: Path, story_id: str) -> Path:
    """Seed a resolvable StoryContext AND its StorySpecification (SAME UUID)."""
    project_root = tmp_path / _PROJECT
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    story_uuid = uuid4()
    save_story_context_global(
        None,
        StoryContext(
            story_uuid=story_uuid,
            project_key=_PROJECT,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        ),
    )
    StateBackendStoryRepository().save_specification(
        story_uuid,
        StorySpecification(
            need="Need text", solution="Solution text", acceptance=["AC1"],
        ),
    )
    return project_root


def _seed_project_registration(
    project_root: Path, *, config_digest: str, config_version: str = "1",
) -> None:
    StateBackendProjectRegistrationRepository().save(
        ProjectRegistration(
            project_key=_PROJECT,
            project_root=project_root,
            github_owner="acme",
            github_repo=_PROJECT,
            runtime_profile=RuntimeProfile.CORE,
            config_version=config_version,
            config_digest=config_digest,
            registered_at=_T0,
        ),
    )


def _seed_prompt_binding(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Materialize a resolvable ``prompt-bundle.lock.json`` + central manifest."""
    bundle_store_root = project_root / "prompt-bundle-store"
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(bundle_store_root))
    bundle_root = prompt_bundle_store_dir("core", "1")
    bundle_root.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps({"bundle_id": "core", "bundle_version": "1"})
    (bundle_root / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / ".agentkit" / "config"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "prompt-bundle.lock.json").write_text(
        json.dumps(
            {
                "bundle_id": "core",
                "bundle_version": "1",
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": hashlib.sha256(
                    manifest_text.encode("utf-8"),
                ).hexdigest(),
                "templates": {},
            },
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# AC1/AC2/AC5: real setup persists the digest atomically, read-only after insert
# ---------------------------------------------------------------------------


def test_real_setup_start_persists_digest_atomically_with_ownership_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    story_id = "AG3-700"
    run_id = "run-700"
    project_root = _seed_story(tmp_path, story_id)
    _seed_project_registration(project_root, config_digest="c" * 64)
    _seed_prompt_binding(project_root, monkeypatch)
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac1")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-1", session_id="sess-1"),
    )

    assert result.status == "committed"
    ownership = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert ownership is not None and ownership.run_id == run_id

    digest_record = load_execution_contract_digest_global(_PROJECT, story_id, run_id)
    assert digest_record is not None
    assert len(digest_record.execution_contract_digest) == 64
    assert digest_record.run_id == run_id


def test_execution_contract_digest_has_no_update_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: a second INSERT for the SAME run identity is rejected (no silent
    overwrite) -- the persistence layer enforces read-only-after-insert.
    """
    story_id = "AG3-701"
    run_id = "run-701"
    project_root = _seed_story(tmp_path, story_id)
    _seed_project_registration(project_root, config_digest="c" * 64)
    _seed_prompt_binding(project_root, monkeypatch)
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac5")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-2", session_id="sess-1"),
    )
    assert result.status == "committed"

    with pytest.raises(Exception, match="(?i)duplicate|unique"):
        insert_execution_contract_digest_global(
            ExecutionContractDigestRecord(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                execution_contract_digest="0" * 64,
                digest_format_version=1,
                formed_at=_T0,
            ),
        )


def test_setup_rejected_when_project_not_registered(tmp_path: Path) -> None:
    """AC2: a digest component (project/QA/gate config) that cannot be
    resolved deterministically rejects the fresh setup start -- no run ever
    enters the execution regime without a persisted digest.
    """
    story_id = "AG3-702"
    run_id = "run-702"
    _seed_story(tmp_path, story_id)
    # Deliberately no project registration, no prompt binding.
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac2a")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-3", session_id="sess-1"),
    )

    assert result.status == "rejected"
    assert load_active_run_ownership_record_global(_PROJECT, story_id) is None
    assert load_execution_contract_digest_global(_PROJECT, story_id, run_id) is None


def test_setup_rejected_when_prompt_binding_unresolvable(
    tmp_path: Path,
) -> None:
    """AC2: project IS registered but the run-prompt-pin component cannot be
    resolved (no ``prompt-bundle.lock.json``) -- still a clean rejection.
    """
    story_id = "AG3-703"
    run_id = "run-703"
    project_root = _seed_story(tmp_path, story_id)
    _seed_project_registration(project_root, config_digest="c" * 64)
    # Deliberately no prompt-bundle.lock.json.
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac2b")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-4", session_id="sess-1"),
    )

    assert result.status == "rejected"
    assert load_active_run_ownership_record_global(_PROJECT, story_id) is None
    assert load_execution_contract_digest_global(_PROJECT, story_id, run_id) is None


def test_setup_rejected_when_project_config_digest_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 (Codex r1 CRITICAL fix): a registered project whose ``config_digest``
    is NOT a valid 64-char lowercase SHA-256 hex string is an unresolvable
    'project/QA/gate configuration' component -- reject fail-closed instead
    of hashing a malformed component into the digest.
    """
    story_id = "AG3-707"
    run_id = "run-707"
    project_root = _seed_story(tmp_path, story_id)
    _seed_project_registration(project_root, config_digest="deadbeef")
    _seed_prompt_binding(project_root, monkeypatch)
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac2c")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-7", session_id="sess-1"),
    )

    assert result.status == "rejected"
    assert load_active_run_ownership_record_global(_PROJECT, story_id) is None
    assert load_execution_contract_digest_global(_PROJECT, story_id, run_id) is None


def test_setup_rejected_when_project_config_version_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 (Codex r1 CRITICAL fix): a registered project whose ``config_version``
    is blank is likewise an unresolvable component -- reject fail-closed.
    """
    story_id = "AG3-708"
    run_id = "run-708"
    project_root = _seed_story(tmp_path, story_id)
    _seed_project_registration(
        project_root, config_digest="c" * 64, config_version="   ",
    )
    _seed_prompt_binding(project_root, monkeypatch)
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac2d")

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-digest-8", session_id="sess-1"),
    )

    assert result.status == "rejected"
    assert load_active_run_ownership_record_global(_PROJECT, story_id) is None
    assert load_execution_contract_digest_global(_PROJECT, story_id, run_id) is None


# ---------------------------------------------------------------------------
# AC4: "pinned-for-new-runs" (default effect class) over two real runs
# ---------------------------------------------------------------------------


def test_config_change_after_run_start_pins_the_running_run_new_run_diverges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    story_a = "AG3-704"
    story_b = "AG3-705"
    project_root = _seed_story(tmp_path, story_a)
    _seed_prompt_binding(project_root, monkeypatch)
    _seed_project_registration(project_root, config_digest="1" * 64)
    service = _real_digest_service(now=_T0, instance_id="inst-digest-ac4")

    first = service.start_phase(
        run_id="run-704",
        phase="setup",
        request=_request(story_id=story_a, op_id="op-digest-5", session_id="sess-1"),
    )
    assert first.status == "committed"
    first_digest = load_execution_contract_digest_global(_PROJECT, story_a, "run-704")
    assert first_digest is not None

    # An administrative config change lands AFTER the run started.
    StateBackendProjectRegistrationRepository().update_upgraded(
        _PROJECT, upgraded_at=_T0, new_digest="2" * 64,
    )

    # The RUNNING run's persisted digest is unchanged (pinned-for-new-runs).
    unchanged_digest = load_execution_contract_digest_global(_PROJECT, story_a, "run-704")
    assert unchanged_digest is not None
    assert unchanged_digest.execution_contract_digest == (
        first_digest.execution_contract_digest
    )

    # A NEW run (different story sharing the same project) started AFTER the
    # config change gets a DIFFERENT digest.
    (project_root / "stories" / story_b).mkdir(parents=True, exist_ok=True)
    _seed_story(tmp_path, story_b)
    second = service.start_phase(
        run_id="run-705",
        phase="setup",
        request=_request(story_id=story_b, op_id="op-digest-6", session_id="sess-2"),
    )
    assert second.status == "committed"
    second_digest = load_execution_contract_digest_global(_PROJECT, story_b, "run-705")
    assert second_digest is not None
    assert (
        second_digest.execution_contract_digest
        != first_digest.execution_contract_digest
    )


# ---------------------------------------------------------------------------
# AC9: Postgres-only fail-closed (K5)
# ---------------------------------------------------------------------------


def test_insert_and_load_fail_closed_on_non_postgres_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.state_backend.store import facade as store_facade

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    store_facade.reset_backend_cache_for_tests()
    try:
        with pytest.raises(ConfigError, match="(?i)postgres"):
            insert_execution_contract_digest_global(
                ExecutionContractDigestRecord(
                    project_key=_PROJECT,
                    story_id="AG3-706",
                    run_id="run-706",
                    execution_contract_digest="d" * 64,
                    digest_format_version=1,
                    formed_at=_T0,
                ),
            )
        with pytest.raises(ConfigError, match="(?i)postgres"):
            load_execution_contract_digest_global(_PROJECT, "AG3-706", "run-706")
    finally:
        monkeypatch.delenv("AGENTKIT_STATE_BACKEND", raising=False)
        monkeypatch.delenv("AGENTKIT_ALLOW_SQLITE", raising=False)
        store_facade.reset_backend_cache_for_tests()
