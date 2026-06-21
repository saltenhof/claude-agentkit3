"""Contract test for Governance.register_hooks and Governance.deactivate_locks.

AG3-031 signature pinning per §2.1.4.
Pins:
  - Governance.register_hooks parameter names and type annotations.
  - Governance.deactivate_locks parameter names and type annotations.
  - Governance.__init__ parameter names (hook_repo, lock_repo, project_key).
  - run_hook remains a static method (unchanged by AG3-031).
  - HookDefinition fields: hook_event_name, matcher, command (FK-30 §30.3.1).

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from agentkit.backend.governance.runner import Governance


def _hints(method: object) -> dict[str, object]:
    """Resolve PEP 563 lazy annotations.

    Provides a localns that includes governance types so that TYPE_CHECKING-
    gated imports (like HookDefinition) can be resolved by get_type_hints.
    """
    from agentkit.backend.governance.hook_registration import HookDefinition, RegistrationResult
    from agentkit.backend.governance.locks import DeactivationResult

    localns = {
        "HookDefinition": HookDefinition,
        "RegistrationResult": RegistrationResult,
        "DeactivationResult": DeactivationResult,
    }
    return typing.get_type_hints(method, localns=localns)  # type: ignore[arg-type]


@pytest.mark.contract
class TestGovernanceInitSignature:
    """Governance.__init__ has the expected parameters."""

    def test_init_params_present(self) -> None:
        sig = inspect.signature(Governance.__init__)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "hook_repo" in params
        assert "lock_repo" in params
        assert "project_key" in params

    def test_hook_repo_is_keyword_only(self) -> None:
        sig = inspect.signature(Governance.__init__)
        param = sig.parameters["hook_repo"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY

    def test_lock_repo_is_keyword_only(self) -> None:
        sig = inspect.signature(Governance.__init__)
        param = sig.parameters["lock_repo"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY


@pytest.mark.contract
class TestRegisterHooksSignature:
    """Signature pinning for Governance.register_hooks."""

    def test_method_exists(self) -> None:
        assert hasattr(Governance, "register_hooks")
        assert callable(Governance.register_hooks)

    def test_parameter_names(self) -> None:
        sig = inspect.signature(Governance.register_hooks)
        param_names = list(sig.parameters.keys())
        assert "self" in param_names
        assert "hook_definitions" in param_names

    def test_hook_definitions_annotation(self) -> None:
        hints = _hints(Governance.register_hooks)
        # Should be list[HookDefinition] — check it resolves
        assert "hook_definitions" in hints

    def test_return_annotation_present(self) -> None:
        hints = _hints(Governance.register_hooks)
        assert "return" in hints

    def test_is_not_static(self) -> None:
        # register_hooks is an instance method, not a static method
        assert not isinstance(
            inspect.getattr_static(Governance, "register_hooks"),
            staticmethod,
        )


@pytest.mark.contract
class TestDeactivateLocksSignature:
    """Signature pinning for Governance.deactivate_locks."""

    def test_method_exists(self) -> None:
        assert hasattr(Governance, "deactivate_locks")
        assert callable(Governance.deactivate_locks)

    def test_parameter_names(self) -> None:
        sig = inspect.signature(Governance.deactivate_locks)
        param_names = list(sig.parameters.keys())
        assert "self" in param_names
        assert "story_id" in param_names

    def test_story_id_is_str(self) -> None:
        hints = _hints(Governance.deactivate_locks)
        assert hints.get("story_id") is str

    def test_return_annotation_present(self) -> None:
        hints = _hints(Governance.deactivate_locks)
        assert "return" in hints

    def test_is_not_static(self) -> None:
        assert not isinstance(
            inspect.getattr_static(Governance, "deactivate_locks"),
            staticmethod,
        )


@pytest.mark.contract
class TestRunHookRemainsStatic:
    """run_hook must remain a static method (not touched by AG3-031)."""

    def test_run_hook_is_static(self) -> None:
        assert isinstance(
            inspect.getattr_static(Governance, "run_hook"),
            staticmethod,
        )

    def test_run_hook_parameter_names(self) -> None:
        sig = inspect.signature(Governance.run_hook)
        param_names = list(sig.parameters.keys())
        assert "hook_id" in param_names
        assert "event" in param_names
        assert "phase" in param_names
        assert "project_root" in param_names


@pytest.mark.contract
class TestHookDefinitionFields:
    """HookDefinition has FK-30 §30.3.1 fields: hook_event_name, matcher, command."""

    def test_hook_definition_fields_present(self) -> None:
        from agentkit.backend.governance.hook_registration import HookDefinition, HookEventName

        defn = HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher="Bash",
            command="agentkit-hook-claude pre branch_guard",
        )
        assert defn.hook_event_name == HookEventName.PRE_TOOL_USE
        assert defn.matcher == "Bash"
        assert defn.command == "agentkit-hook-claude pre branch_guard"

    def test_hook_definition_no_harness_field(self) -> None:
        """HookDefinition must NOT have harness field (FK-30 §30.3.1 has 3 fields only)."""
        import pydantic

        from agentkit.backend.governance.hook_registration import HookDefinition, HookEventName

        with pytest.raises(pydantic.ValidationError):
            HookDefinition(  # type: ignore[call-arg]
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="cmd",
                harness="CLAUDE_CODE",
            )

    def test_hook_definition_no_hook_id_field(self) -> None:
        """HookDefinition must NOT have hook_id field (not in FK-30 §30.3.1)."""
        import pydantic

        from agentkit.backend.governance.hook_registration import HookDefinition, HookEventName

        with pytest.raises(pydantic.ValidationError):
            HookDefinition(  # type: ignore[call-arg]
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="cmd",
                hook_id="branch_guard",
            )
