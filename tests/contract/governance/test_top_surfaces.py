"""Contract test for the two governance top surfaces.

AG3-031 signature pinning per §2.1.4, retargeted by AG3-239 to the owner of each
operation:

  - ``Governance.deactivate_locks`` (core) parameter names and annotations;
  - ``Governance.__init__`` takes ONLY ``lock_repo``;
  - ``InstallerHookGovernance.register_hooks`` (edge) parameter names and
    annotations -- the operation materialises harness settings files on the
    developer machine and therefore cannot sit in the core;
  - hook dispatch is NOT reachable from the administration surface;
  - HookDefinition fields: hook_event_name, matcher, command (FK-30 §30.3.1).

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24; surfaces re-cut by AG3-239.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from agentkit.backend.governance.administration import Governance
from agentkit.backend.installer.writer_client import InstallerHookGovernance


def _hints(method: object) -> dict[str, object]:
    """Resolve PEP 563 lazy annotations.

    Provides a localns that includes governance types so that TYPE_CHECKING-
    gated imports (like HookDefinition) can be resolved by get_type_hints.
    """
    from agentkit.backend.governance.hook_registration import RegistrationResult
    from agentkit.backend.governance.locks import DeactivationResult
    from agentkit_wire.governance_registration import HookDefinition

    localns = {
        "HookDefinition": HookDefinition,
        "RegistrationResult": RegistrationResult,
        "DeactivationResult": DeactivationResult,
    }
    return typing.get_type_hints(method, localns=localns)  # type: ignore[arg-type]


@pytest.mark.contract
class TestGovernanceInitSignature:
    """Governance.__init__ takes the lock repository and nothing else."""

    def test_init_params_present(self) -> None:
        sig = inspect.signature(Governance.__init__)
        params = list(sig.parameters.keys())
        assert params == ["self", "lock_repo"]

    def test_no_hook_repository_dependency(self) -> None:
        """AG3-239: every call site used to fake the half it did not need.

        The core surface must not demand a ``HookRegistrationRepository`` for an
        operation it does not perform -- that dummy was a direct-DB binding in
        three edge-classified composition-root sites.
        """
        sig = inspect.signature(Governance.__init__)
        assert "hook_repo" not in sig.parameters
        assert "project_key" not in sig.parameters
        assert "project_root" not in sig.parameters

    def test_lock_repo_is_keyword_only(self) -> None:
        sig = inspect.signature(Governance.__init__)
        param = sig.parameters["lock_repo"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY


@pytest.mark.contract
class TestRegisterHooksSignature:
    """Signature pinning for the edge-side ``register_hooks``.

    AG3-239: the operation persists through the injected repository and then
    writes ``.claude/settings.json`` / ``.codex/hooks.json`` on the developer
    machine. The core cannot do the second half, so the composed operation is
    edge orchestration.
    """

    def test_operation_is_not_on_the_core_surface(self) -> None:
        assert not hasattr(Governance, "register_hooks")

    def test_method_exists(self) -> None:
        assert hasattr(InstallerHookGovernance, "register_hooks")
        assert callable(InstallerHookGovernance.register_hooks)

    def test_parameter_names(self) -> None:
        sig = inspect.signature(InstallerHookGovernance.register_hooks)
        param_names = list(sig.parameters.keys())
        assert "self" in param_names
        assert "hook_definitions" in param_names

    def test_hook_definitions_annotation(self) -> None:
        hints = _hints(InstallerHookGovernance.register_hooks)
        # Should be list[HookDefinition] — check it resolves
        assert "hook_definitions" in hints

    def test_return_annotation_present(self) -> None:
        hints = _hints(InstallerHookGovernance.register_hooks)
        assert "return" in hints

    def test_is_not_static(self) -> None:
        # register_hooks is an instance method, not a static method
        assert not isinstance(
            inspect.getattr_static(InstallerHookGovernance, "register_hooks"),
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
class TestHookDispatchIsNotOnTheAdministrationSurface:
    """Hook dispatch is a module function of the edge dispatcher, not a facade.

    AG3-239: ``Governance.run_hook`` was a one-line delegation to
    ``governance.runner.run_hook``. It made the core administration surface a
    second import path for the edge hook dispatch, so it is removed rather than
    deprecated (CLAUDE.md, KEINE KOMPATIBILITAETSSCHICHTEN).
    """

    def test_administration_surface_has_no_dispatch_facade(self) -> None:
        assert not hasattr(Governance, "run_hook")

    def test_run_hook_parameter_names(self) -> None:
        from agentkit.backend.governance.runner import run_hook

        sig = inspect.signature(run_hook)
        param_names = list(sig.parameters.keys())
        assert "hook_id" in param_names
        assert "event" in param_names
        assert "phase" in param_names
        assert "project_root" in param_names


@pytest.mark.contract
class TestHookDefinitionFields:
    """HookDefinition has FK-30 §30.3.1 fields: hook_event_name, matcher, command."""

    def test_hook_definition_fields_present(self) -> None:
        from agentkit_wire.governance_registration import HookDefinition, HookEventName

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

        from agentkit_wire.governance_registration import HookDefinition, HookEventName

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

        from agentkit_wire.governance_registration import HookDefinition, HookEventName

        with pytest.raises(pydantic.ValidationError):
            HookDefinition(  # type: ignore[call-arg]
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="cmd",
                hook_id="branch_guard",
            )
