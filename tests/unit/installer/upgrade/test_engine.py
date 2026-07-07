"""Unit tests for the engine-driven upgrade flow (AG3-089 FIX 1 / FIX 3).

FIX 1: upgrade runs THROUGH the AG3-088 ``CheckpointEngine`` (an engine-driven
flow), not a standalone helper. These tests assert the upgrade flow is a real
``FlowDefinition`` walked by the SAME engine and that ``run_upgrade`` drives it.

FIX 3: the upgrade flow actually invokes ``migrate_hooks`` ->
``Governance.register_hooks`` (the §51.6 hook migration is genuinely wired).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.installer.upgrade.conftest import (
    InMemoryRegistrationRepo,
    register_project,
    write_valid_project_yaml,
)

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    RegistrationResult,
)
from agentkit.backend.installer.checkpoint_engine.engine import CheckpointEngine
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.upgrade._digest import config_file_digest
from agentkit.backend.installer.upgrade.engine import (
    UP_01_DETECT_FOOTPRINT,
    UP_04_MIGRATE_HOOKS,
    UpgradeRequest,
    UpgradeRunContext,
    build_upgrade_branch_predicate_registry,
    build_upgrade_flow,
    build_upgrade_handler_registry,
)
from agentkit.backend.installer.upgrade.upgrade_flow import run_upgrade
from agentkit.backend.process.language.model import FlowLevel, NodeKind

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGovernance:
    """Records the ``register_hooks`` call (FIX 3 — proves the wiring)."""

    def __init__(self) -> None:
        self.calls: list[list[HookDefinition]] = []

    def register_hooks(
        self, hook_definitions: list[HookDefinition]
    ) -> RegistrationResult:
        self.calls.append(hook_definitions)
        return RegistrationResult(
            registered=[d.matcher for d in hook_definitions], skipped=[]
        )


def _hook(matcher: str) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.POST_TOOL_USE,
        matcher=matcher,
        command=f"agentkit-hook-claude post {matcher.lower()}",
    )


def test_upgrade_flow_is_a_component_flow_walked_by_the_engine() -> None:
    """FIX 1: the upgrade flow is a real ``level=COMPONENT`` FlowDefinition.

    Every ``step`` node has a registered handler and the engine accepts the
    registries (the same engine the installer flow uses) — so the upgrade run is
    engine-driven, not a hand-rolled second walker.
    """
    flow = build_upgrade_flow()
    handlers = build_upgrade_handler_registry()

    assert flow.level is FlowLevel.COMPONENT
    step_nodes = [n.node_id for n in flow.nodes if n.kind is NodeKind.STEP]
    assert step_nodes  # non-empty spine
    for node_id in step_nodes:
        assert node_id in handlers  # every step is a real handler (ZERO DEBT)

    # The SHARED engine validates the registry at construction (a missing handler
    # would fail closed here) — proving the upgrade flow runs on the same walker.
    engine: CheckpointEngine[UpgradeRunContext] = CheckpointEngine(
        flow=flow,
        handlers=handlers,
        branch_predicates=build_upgrade_branch_predicate_registry(),
    )
    assert engine.flow.flow_id == flow.flow_id


def test_run_upgrade_traverses_engine_and_populates_run_state(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """FIX 1: running the flow on the engine populates the run-state per handler.

    The detect handler records the footprint + decision on the run-state; a
    direct engine run proves the handlers (not an imperative helper) produce the
    result the flow contract orders.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    request = UpgradeRequest(
        project_root=project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
    )
    context = UpgradeRunContext(mode=ExecutionMode.VERIFY, request=request)
    engine: CheckpointEngine[UpgradeRunContext] = CheckpointEngine(
        flow=build_upgrade_flow(),
        handlers=build_upgrade_handler_registry(),
        branch_predicates=build_upgrade_branch_predicate_registry(),
    )

    results = engine.run(context)

    # The engine ran the whole linear spine and each handler emitted one result.
    checkpoints = [r.checkpoint for r in results]
    assert checkpoints[0] == UP_01_DETECT_FOOTPRINT
    assert UP_04_MIGRATE_HOOKS in checkpoints
    # The detect handler populated the run-state (engine-driven, not a helper).
    assert context.run_state.footprint is not None
    assert context.run_state.decision is not None


def test_run_upgrade_register_calls_register_hooks(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """FIX 3 / AC4: the register-mode upgrade flow calls ``register_hooks``.

    ``run_upgrade`` drives the engine; the ``up_04_migrate_hooks`` handler invokes
    ``migrate_hooks`` -> ``Governance.register_hooks`` (no longer a built-but-
    unwired helper). The recording governance double proves the call is made.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    governance = _RecordingGovernance()

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
        governance=governance,  # type: ignore[arg-type]
        desired_hook_definitions=[_hook("Bash"), _hook("Write")],
    )

    # FIX 3: register_hooks was actually called through the upgrade flow.
    assert len(governance.calls) == 1
    assert {d.matcher for d in governance.calls[0]} == {"Bash", "Write"}
    assert result.hook_outcome is not None
    assert set(result.hook_outcome.registered) == {"Bash", "Write"}


def test_run_upgrade_register_migrates_legacy_claude_settings(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """The engine-wired hook checkpoint rewrites persisted flat Claude settings."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "command": "agentkit-hook-claude pre branch_guard",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    governance = _RecordingGovernance()

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.REGISTER,
        governance=governance,  # type: ignore[arg-type]
        desired_hook_definitions=[],
    )

    assert result.claude_hook_settings_migrated is True
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    group = data["hooks"]["PreToolUse"][0]
    assert "command" not in group
    assert group["hooks"] == [
        {"command": "agentkit-hook-claude pre branch_guard", "type": "command"}
    ]


def test_run_upgrade_verify_does_not_call_register_hooks(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """Read-only verify plans the hook migration WITHOUT registering (FK-50 §50.2)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )
    governance = _RecordingGovernance()

    result = run_upgrade(
        project_root,
        project_key=project_root.stem,
        target_config_version="3.0",
        registration_repo=registration_repo,  # type: ignore[arg-type]
        mode=ExecutionMode.VERIFY,
        governance=governance,  # type: ignore[arg-type]
        desired_hook_definitions=[_hook("Bash")],
    )

    assert governance.calls == []  # no mutation in read-only mode
    assert result.hook_outcome is None
    assert result.mutated is False
