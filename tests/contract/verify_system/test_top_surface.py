"""Contract test for VerifySystem.run_qa_subflow -- AG3-026 signature pinning.

Pins:
  - VerifySystem.run_qa_subflow parameter names and type annotations
  - Return-type annotation is exactly QaSubflowOutcome (AG3-026 Pass-2 Befund A)
  - VerifyContextBundle is exported from agentkit.backend.verify_system
  - VerifySystem is exported from agentkit.backend.verify_system
  - PolicyVerdictResult is NOT in __init__.__all__ (AK11)
  - VerifyTarget, VerifyTargetType, QaSubflowExecutionResult NOT exported (AK11)
"""

from __future__ import annotations

import inspect

import pytest

import agentkit.backend.verify_system as _vs_module
from agentkit.backend.core_types import QaContext
from agentkit.backend.verify_system import (
    QaSubflowOutcome,
    VerifyContextBundle,
    VerifySystem,
)
from agentkit.backend.verify_system.system import VerifySystem as _VerifySystemDirect


def _resolved_hints() -> dict[str, object]:
    """Resolve type annotations on run_qa_subflow, handling PEP 563 string forms.

    ``from __future__ import annotations`` makes annotations lazy strings.
    ``typing.get_type_hints`` resolves them back to the actual types.
    """
    import typing

    return typing.get_type_hints(VerifySystem.run_qa_subflow)


@pytest.mark.contract
class TestRunQaSubflowSignature:
    """Signature pinning for VerifySystem.run_qa_subflow."""

    def test_method_exists_on_verify_system(self) -> None:
        assert hasattr(VerifySystem, "run_qa_subflow")
        assert callable(VerifySystem.run_qa_subflow)

    def test_parameter_names(self) -> None:
        sig = inspect.signature(VerifySystem.run_qa_subflow)
        param_names = list(sig.parameters.keys())
        # 'self' is the first parameter of an unbound method.
        # 'review_input' is the optional Layer2ReviewInput kwarg (AG3-026 Pass-3).
        # 'previous_findings' carries the prior round's findings for the
        # FindingResolutionAssessor (FK-34 / AG3-041 §2.1.5, default ()).
        assert param_names == [
            "self", "ctx", "story_id", "qa_context", "target",
            "review_input", "previous_findings",
        ]

    def test_ctx_annotation_is_verify_context_bundle(self) -> None:
        hints = _resolved_hints()
        assert hints["ctx"] is VerifyContextBundle

    def test_story_id_annotation_is_str(self) -> None:
        hints = _resolved_hints()
        assert hints["story_id"] is str

    def test_qa_context_annotation_is_qa_context(self) -> None:
        hints = _resolved_hints()
        assert hints["qa_context"] is QaContext

    def test_target_annotation_is_artifact_reference(self) -> None:
        from agentkit.backend.artifacts import ArtifactReference

        hints = _resolved_hints()
        assert hints["target"] is ArtifactReference

    def test_return_annotation_is_qa_subflow_outcome(self) -> None:
        """AG3-026 Pass-2 Befund A: return type changed from PolicyVerdict to QaSubflowOutcome."""
        hints = _resolved_hints()
        assert hints["return"] is QaSubflowOutcome


@pytest.mark.contract
class TestVerifySystemPublicExports:
    """VerifySystem and required types are exported from agentkit.backend.verify_system."""

    def test_verify_system_in_all(self) -> None:
        assert "VerifySystem" in _vs_module.__all__

    def test_verify_context_bundle_in_all(self) -> None:
        assert "VerifyContextBundle" in _vs_module.__all__

    def test_verify_system_error_in_all(self) -> None:
        assert "VerifySystemError" in _vs_module.__all__

    def test_verify_target_unknown_error_in_all(self) -> None:
        assert "VerifyTargetUnknownError" in _vs_module.__all__

    def test_layer_execution_error_in_all(self) -> None:
        assert "LayerExecutionError" in _vs_module.__all__


@pytest.mark.contract
class TestForbiddenExports:
    """Internal types must NOT be exported from agentkit.backend.verify_system (AK11)."""

    def test_policy_verdict_result_not_in_all(self) -> None:
        assert "PolicyVerdictResult" not in _vs_module.__all__

    def test_verify_target_not_in_all(self) -> None:
        assert "VerifyTarget" not in _vs_module.__all__

    def test_verify_target_type_not_in_all(self) -> None:
        assert "VerifyTargetType" not in _vs_module.__all__

    def test_qa_subflow_execution_result_not_in_all(self) -> None:
        assert "QaSubflowExecutionResult" not in _vs_module.__all__

    def test_private_qa_subflow_execution_result_not_in_all(self) -> None:
        assert "_QaSubflowExecutionResult" not in _vs_module.__all__

    def test_policy_verdict_result_not_importable_from_init(self) -> None:
        """PolicyVerdictResult must not be accessible as an attribute of the module."""
        assert not hasattr(_vs_module, "PolicyVerdictResult")

    def test_verify_target_not_importable_from_init(self) -> None:
        assert not hasattr(_vs_module, "VerifyTarget")

    def test_verify_target_type_not_importable_from_init(self) -> None:
        assert not hasattr(_vs_module, "VerifyTargetType")


@pytest.mark.contract
class TestVerifySystemIsDirectlyImportable:
    """VerifySystem can be imported via 'from agentkit.backend.verify_system import VerifySystem'."""

    def test_import_verify_system(self) -> None:
        from agentkit.backend.verify_system import VerifySystem as ImportedVerifySystem

        assert ImportedVerifySystem is _VerifySystemDirect

    def test_import_verify_context_bundle(self) -> None:
        from agentkit.backend.verify_system import (
            VerifyContextBundle as ImportedVerifyContextBundle,
        )

        assert ImportedVerifyContextBundle is VerifyContextBundle
