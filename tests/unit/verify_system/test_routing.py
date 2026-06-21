"""Tests for verify_system routing -- select_layers().

Verifies that the QA-context -> layer-kind mapping is correct for all
four QaContext values (AG3-026 §2.1.2, §4 AK4).
"""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import QaContext
from agentkit.backend.verify_system.routing import QALayerKind, select_layers


class TestSelectLayers:
    """Unit tests for select_layers routing function."""

    def test_implementation_initial_returns_all_kinds(self) -> None:
        """IMPLEMENTATION_INITIAL -> all layer kinds in order incl. sonarqube_gate.

        FK-33 §33.8.3: the sonarqube_gate is classificatory Layer 1 but
        sequenced AFTER adversarial and BEFORE policy.
        """
        kinds = select_layers(QaContext.IMPLEMENTATION_INITIAL)
        assert kinds == (
            QALayerKind.STRUCTURAL,
            QALayerKind.LLM_EVALUATOR,
            QALayerKind.ADVERSARIAL,
            QALayerKind.SONARQUBE_GATE,
            QALayerKind.POLICY,
        )

    def test_implementation_remediation_returns_all_kinds(self) -> None:
        """IMPLEMENTATION_REMEDIATION -> same sequence as INITIAL."""
        kinds = select_layers(QaContext.IMPLEMENTATION_REMEDIATION)
        assert kinds == (
            QALayerKind.STRUCTURAL,
            QALayerKind.LLM_EVALUATOR,
            QALayerKind.ADVERSARIAL,
            QALayerKind.SONARQUBE_GATE,
            QALayerKind.POLICY,
        )

    def test_exploration_initial_returns_two_kinds(self) -> None:
        """EXPLORATION_INITIAL -> reduced set: LLM_EVALUATOR + POLICY."""
        kinds = select_layers(QaContext.EXPLORATION_INITIAL)
        assert kinds == (
            QALayerKind.LLM_EVALUATOR,
            QALayerKind.POLICY,
        )

    def test_exploration_remediation_returns_two_kinds(self) -> None:
        """EXPLORATION_REMEDIATION -> same reduced set as INITIAL."""
        kinds = select_layers(QaContext.EXPLORATION_REMEDIATION)
        assert kinds == (
            QALayerKind.LLM_EVALUATOR,
            QALayerKind.POLICY,
        )

    def test_implementation_initial_has_five_layers(self) -> None:
        """Implementation sequence -> 5 kinds (incl. sonarqube_gate, FK-33 §33.8.3)."""
        kinds = select_layers(QaContext.IMPLEMENTATION_INITIAL)
        assert len(kinds) == 5  # noqa: PLR2004

    def test_exploration_initial_has_two_layers(self) -> None:
        """Layer count matches AK4: exploration -> 2 layers."""
        kinds = select_layers(QaContext.EXPLORATION_INITIAL)
        assert len(kinds) == 2  # noqa: PLR2004

    def test_layer_order_structural_before_llm_before_adversarial(self) -> None:
        """Order: structural < llm < adversarial < sonarqube_gate < policy.

        FK-33 §33.8.3: the green gate is the final deterministic
        convergence step, after adversarial and before policy.
        """
        kinds = select_layers(QaContext.IMPLEMENTATION_INITIAL)
        indices = {k: i for i, k in enumerate(kinds)}
        assert indices[QALayerKind.STRUCTURAL] < indices[QALayerKind.LLM_EVALUATOR]
        assert indices[QALayerKind.LLM_EVALUATOR] < indices[QALayerKind.ADVERSARIAL]
        assert indices[QALayerKind.ADVERSARIAL] < indices[QALayerKind.SONARQUBE_GATE]
        assert indices[QALayerKind.SONARQUBE_GATE] < indices[QALayerKind.POLICY]

    def test_exploration_llm_before_policy(self) -> None:
        """Exploration layer order: llm_evaluator < policy."""
        kinds = select_layers(QaContext.EXPLORATION_INITIAL)
        indices = {k: i for i, k in enumerate(kinds)}
        assert indices[QALayerKind.LLM_EVALUATOR] < indices[QALayerKind.POLICY]

    def test_all_four_qa_context_values_covered(self) -> None:
        """All four QaContext members produce a non-empty routing result."""
        for ctx in QaContext:
            kinds = select_layers(ctx)
            assert len(kinds) >= 1, f"select_layers({ctx!r}) returned empty tuple"

    @pytest.mark.parametrize(
        ("qa_context", "expected_count"),
        [
            (QaContext.IMPLEMENTATION_INITIAL, 5),
            (QaContext.IMPLEMENTATION_REMEDIATION, 5),
            (QaContext.EXPLORATION_INITIAL, 2),
            (QaContext.EXPLORATION_REMEDIATION, 2),
        ],
    )
    def test_layer_count_parametrized(
        self,
        qa_context: QaContext,
        expected_count: int,
    ) -> None:
        """Parametrised sanity check for layer counts."""
        kinds = select_layers(qa_context)
        assert len(kinds) == expected_count
