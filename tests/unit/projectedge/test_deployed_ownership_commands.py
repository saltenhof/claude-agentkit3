from __future__ import annotations

import inspect

import pytest

from agentkit.bundles.target_project.tools.agentkit import projectedge


def test_deployed_projectedge_has_no_takeover_confirm_command() -> None:
    with pytest.raises(SystemExit) as exc_info:
        projectedge.main(["takeover-confirm"])

    assert exc_info.value.code == 2


def test_deployed_projectedge_delegates_ownership_commands_to_shared_transport() -> None:
    source = inspect.getsource(projectedge._run_agent_ownership)

    assert "client.takeover_request(" in source
    assert "client.admin_abort_operation(" in source
    assert "client.recover(" in source
    assert "urllib" not in source
    assert "ControlPlaneRuntimeService" not in source
