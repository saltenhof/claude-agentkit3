"""Unit tests for Layer-2 reviewers with real deterministic logic.

AG3-026 Pass-2 §Befund-B: Three reviewer classes each have:
- PASS path: conditions met, no findings.
- FAIL paths: at least one test per dimension.
- LLMClient slot: NotImplementedError when non-None client is passed.

AG3-026 Pass-3 ERROR-5: All Layer-2 reviewers now require review_input.
- review_input=None raises Layer2InputMissingError (fail-closed).
- review_input=Layer2ReviewInput() (all empty) -> MAJOR layer2_input.missing
  + filesystem fallback checks.
- review_input with populated fields -> text-based checks.

AG3-026 Pass-3 ERROR-6: dangling_concept_ref test added.

No MagicMock. No real LLM calls. Filesystem state is built using
pytest's ``tmp_path`` fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2InputMissingError, Layer2ReviewInput
from agentkit.backend.verify_system.llm_evaluator.reviewer import (
    DocFidelityReviewer,
    QaReviewReviewer,
    SemanticReviewer,
)
from agentkit.backend.verify_system.protocols import QALayer, Severity

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Dummy LLM client for slot test
# ---------------------------------------------------------------------------


class _DummyLLMClient:
    """Marker dataclass to satisfy the llm_client slot test.

    AG3-026 Pass-2 §Befund-B: No real LLM calls, just a marker object.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_ctx() -> StoryContext:
    """Build a minimal StoryContext for reviewer tests."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _empty_ri() -> Layer2ReviewInput:
    """Empty Layer2ReviewInput (all fields empty strings)."""
    return Layer2ReviewInput()


def _write_py(path: Path, content: str) -> None:
    """Write a Python file with the given content.

    Args:
        path: Target file path.
        content: Python source code.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_test_file(dir_: Path, name: str = "test_something.py", n_tests: int = 3) -> Path:
    """Write a test file with ``n_tests`` dummy test functions.

    Args:
        dir_: Directory to write the test file into.
        name: Filename for the test file.
        n_tests: Number of test functions to include.

    Returns:
        Path to the written test file.
    """
    funcs = "\n".join(
        f"def test_case_{i}():\n    assert True\n" for i in range(n_tests)
    )
    content = f'"""Test module."""\n\n{funcs}'
    test_path = dir_ / name
    _write_py(test_path, content)
    return test_path


# ===========================================================================
# QaReviewReviewer
# ===========================================================================


class TestQaReviewReviewer:
    """QaReviewReviewer tests: pass path, fail paths, llm_client slot."""

    # --- name / protocol ---

    def test_name_is_qa_review(self) -> None:
        """Reviewer name is 'qa_review'."""
        assert QaReviewReviewer().name == "qa_review"

    def test_implements_qa_layer_protocol(self) -> None:
        """QaReviewReviewer satisfies QALayer protocol."""
        assert isinstance(QaReviewReviewer(), QALayer)

    # --- LLM slot ---

    def test_llm_client_slot_raises_not_implemented(self) -> None:
        """Non-None llm_client raises NotImplementedError (AG3-043 slot)."""
        with pytest.raises(NotImplementedError, match="AG3-043"):
            QaReviewReviewer(llm_client=_DummyLLMClient())

    # --- review_input=None raises (fail-closed) ---

    def test_review_input_none_raises_layer2_input_missing_error(
        self, tmp_path: Path
    ) -> None:
        """review_input=None must raise Layer2InputMissingError (fail-closed)."""
        with pytest.raises(Layer2InputMissingError):
            QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=None)

    # --- PASS path (text-based, populated review_input) ---

    def test_pass_with_populated_review_input(self, tmp_path: Path) -> None:
        """PASS: review_input with test references, coverage %, 3+ test names."""
        ri = Layer2ReviewInput(
            story_spec="Implement feature X",
            diff_summary="tests/unit/test_feature.py added; src/feature.py modified",
            concept_excerpt="FK-27 §27.5",
            handover=(
                "Produced: tests/unit/test_a.py, tests/unit/test_b.py, "
                "tests/unit/test_c.py. coverage: 91%"
            ),
        )
        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        assert result.passed is True
        assert result.layer == "qa_review"

    # --- PASS path (filesystem fallback, empty review_input) ---

    def test_pass_when_tests_present_and_sufficient_empty_ri(self, tmp_path: Path) -> None:
        """PASS (fallback): story_dir with >= 3 test functions, coverage file present.

        Pass-4 ERROR-5: pin empty-Layer2ReviewInput emits MAJOR ``layer2_input.missing``
        (no silent PASS) while overall result stays passed=True (no BLOCKING).
        """
        from agentkit.backend.verify_system.protocols import Severity

        _write_test_file(tmp_path, "test_feature.py", n_tests=3)
        (tmp_path / ".coverage").write_text("", encoding="utf-8")

        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        # layer2_input.missing MAJOR is emitted, but no BLOCKING -> passed=True
        assert result.passed is True
        assert result.layer == "qa_review"
        # Hard pin: MAJOR ``layer2_input.missing`` MUST be in findings.
        missing = [f for f in result.findings if f.check == "layer2_input.missing"]
        assert len(missing) == 1
        assert missing[0].severity is Severity.MAJOR

    # --- FAIL paths (text-based, populated review_input) ---

    def test_no_tests_in_diff_produces_blocking_finding(self, tmp_path: Path) -> None:
        """FAIL: diff_summary + handover have no test file references -> BLOCKING."""
        ri = Layer2ReviewInput(
            diff_summary="src/foo.py modified",
            handover="coverage: 88%",
        )
        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        assert result.passed is False
        codes = {f.check for f in result.findings}
        assert "qa_review.no_tests" in codes

    def test_no_coverage_in_handover_produces_major_finding(self, tmp_path: Path) -> None:
        """FAIL: handover mentions tests but no coverage % -> MAJOR."""
        ri = Layer2ReviewInput(
            diff_summary="tests/unit/test_something.py added",
            handover="Produced: test_a, test_b, test_c. No coverage data yet.",
        )
        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        codes = {f.check for f in result.findings}
        assert "qa_review.coverage_unknown" in codes

    # --- FAIL paths (filesystem fallback, empty review_input) ---

    def test_no_tests_produces_blocking_finding_via_filesystem(self, tmp_path: Path) -> None:
        """FAIL (fallback): no test files in story_dir -> BLOCKING qa_review.no_tests."""
        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        blocking = [f for f in result.findings if f.severity == Severity.BLOCKING]
        assert any(f.check == "qa_review.no_tests" for f in blocking)

    def test_thin_tests_produces_major_finding_via_filesystem(self, tmp_path: Path) -> None:
        """FAIL (fallback): only 1 test function -> MAJOR qa_review.edge_cases_thin."""
        _write_test_file(tmp_path, "test_minimal.py", n_tests=1)
        (tmp_path / ".coverage").write_text("", encoding="utf-8")

        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "qa_review.edge_cases_thin" in checks

    def test_missing_coverage_report_produces_major_finding_via_filesystem(
        self, tmp_path: Path
    ) -> None:
        """FAIL (fallback): no coverage report -> MAJOR qa_review.coverage_unknown."""
        _write_test_file(tmp_path, "test_covered.py", n_tests=5)

        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "qa_review.coverage_unknown" in checks

    def test_prompt_audit_in_metadata(self, tmp_path: Path) -> None:
        """evaluate() always includes 'prompt_audit' in metadata."""
        result = QaReviewReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert "prompt_audit" in result.metadata


# ===========================================================================
# SemanticReviewer
# ===========================================================================


class TestSemanticReviewer:
    """SemanticReviewer tests: pass path, fail paths, llm_client slot."""

    # --- name / protocol ---

    def test_name_is_semantic_review(self) -> None:
        """Reviewer name is 'semantic_review'."""
        assert SemanticReviewer().name == "semantic_review"

    def test_implements_qa_layer_protocol(self) -> None:
        """SemanticReviewer satisfies QALayer protocol."""
        assert isinstance(SemanticReviewer(), QALayer)

    # --- LLM slot ---

    def test_llm_client_slot_raises_not_implemented(self) -> None:
        """Non-None llm_client raises NotImplementedError (AG3-043 slot)."""
        with pytest.raises(NotImplementedError, match="AG3-043"):
            SemanticReviewer(llm_client=_DummyLLMClient())

    # --- review_input=None raises (fail-closed) ---

    def test_review_input_none_raises_layer2_input_missing_error(
        self, tmp_path: Path
    ) -> None:
        """review_input=None must raise Layer2InputMissingError (fail-closed)."""
        with pytest.raises(Layer2InputMissingError):
            SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=None)

    # --- PASS path (text-based) ---

    def test_pass_with_clean_review_input(self, tmp_path: Path) -> None:
        """PASS: review_input with no TODO markers, valid concept refs."""
        ri = Layer2ReviewInput(
            story_spec="Implement FK-27 feature.",
            diff_summary="src/feature.py added",
            concept_excerpt="FK-27 §27.4",
            handover="Produced: feature.py. All clean.",
        )
        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        # No text-based findings; naming checks on empty dir also pass.
        assert result.passed is True
        assert result.findings == ()

    def test_pass_on_empty_dir_with_empty_ri(self, tmp_path: Path) -> None:
        """PASS (fallback): empty story_dir (no .py files) produces no BLOCKING.

        Pass-4 ERROR-5: pin empty Layer2ReviewInput emits MAJOR ``layer2_input.missing``.
        """
        from agentkit.backend.verify_system.protocols import Severity

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        # layer2_input.missing emitted but no BLOCKING.
        assert result.passed is True
        missing = [f for f in result.findings if f.check == "layer2_input.missing"]
        assert len(missing) == 1
        assert missing[0].severity is Severity.MAJOR

    # --- FAIL paths (text-based) ---

    def test_todo_marker_in_diff_produces_blocking_finding(self, tmp_path: Path) -> None:
        """FAIL: TODO in diff_summary -> BLOCKING semantic.todo_in_production."""
        ri = Layer2ReviewInput(
            diff_summary="src/bad.py modified # TODO: fix this later",
            handover="All clean.",
        )
        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        assert result.passed is False
        checks = {f.check for f in result.findings}
        assert "semantic.todo_in_production" in checks

    def test_fixme_in_handover_produces_blocking_finding(self, tmp_path: Path) -> None:
        """FAIL: FIXME in handover -> BLOCKING semantic.todo_in_production."""
        ri = Layer2ReviewInput(
            diff_summary="src/foo.py added",
            handover="Produced foo.py # FIXME: broken",
        )
        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        assert result.passed is False
        checks = {f.check for f in result.findings}
        assert "semantic.todo_in_production" in checks

    # --- FAIL paths (filesystem fallback, empty review_input) ---

    def test_todo_marker_in_py_file_produces_blocking_finding(self, tmp_path: Path) -> None:
        """FAIL (fallback): TODO in .py file -> BLOCKING semantic.todo_in_production."""
        _write_py(
            tmp_path / "bad_module.py",
            '"""Module with debt."""\n\n# TODO: fix this\ndef my_func():\n    pass\n',
        )

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        assert result.passed is False
        checks = {f.check for f in result.findings}
        assert "semantic.todo_in_production" in checks

    def test_camel_case_function_produces_major_finding(self, tmp_path: Path) -> None:
        """FAIL: camelCase function -> MAJOR semantic.naming_violation."""
        _write_py(
            tmp_path / "camel_mod.py",
            '"""Module."""\n\ndef myBadFunction():\n    """Bad name."""\n    pass\n',
        )

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "semantic.naming_violation" in checks
        naming = [f for f in result.findings if f.check == "semantic.naming_violation"]
        assert naming[0].severity == Severity.MAJOR

    def test_lowercase_class_produces_major_finding(self, tmp_path: Path) -> None:
        """FAIL: lowercase class name -> MAJOR semantic.naming_violation."""
        _write_py(
            tmp_path / "lc_class.py",
            '"""Module."""\n\nclass myBadClass:\n    """Bad name."""\n    pass\n',
        )

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "semantic.naming_violation" in checks

    def test_private_functions_skipped_for_naming(self, tmp_path: Path) -> None:
        """Private functions (starting with _) are not checked for naming."""
        _write_py(
            tmp_path / "private_mod.py",
            '"""Module."""\n\ndef _InternalHelper():\n    pass\n',
        )

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        naming = [f for f in result.findings if f.check == "semantic.naming_violation"]
        assert len(naming) == 0

    def test_prompt_audit_in_metadata(self, tmp_path: Path) -> None:
        """evaluate() always includes 'prompt_audit' in metadata."""
        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert "prompt_audit" in result.metadata

    def test_dangling_concept_ref_produces_major_finding(self, tmp_path: Path) -> None:
        """FAIL (text-based): story_spec with concept/ path that does not exist.

        ERROR-6: this code path was implemented but had no test.
        A reference to concept/nonexistent/does_not_exist.md in story_spec triggers
        the check when the repo root (containing concept/) is found in story_dir ancestors.
        """
        # Create a fake concept/ dir so the repo root is found.
        concept_dir = tmp_path / "concept"
        concept_dir.mkdir()

        ri = Layer2ReviewInput(
            story_spec="See concept/nonexistent/does_not_exist.md for details.",
            diff_summary="src/foo.py added",
            concept_excerpt="",
            handover="Produced: foo.py",
        )

        result = SemanticReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        dangling = [f for f in result.findings if f.check == "semantic.dangling_concept_ref"]
        assert len(dangling) >= 1, (
            f"Expected at least one semantic.dangling_concept_ref finding; "
            f"got findings: {[f.check for f in result.findings]}"
        )
        assert dangling[0].severity == Severity.MAJOR


# ===========================================================================
# DocFidelityReviewer
# ===========================================================================


class TestDocFidelityReviewer:
    """DocFidelityReviewer tests: pass path, fail paths, llm_client slot."""

    # --- name / protocol ---

    def test_name_is_doc_fidelity(self) -> None:
        """Reviewer name is 'doc_fidelity'."""
        assert DocFidelityReviewer().name == "doc_fidelity"

    def test_implements_qa_layer_protocol(self) -> None:
        """DocFidelityReviewer satisfies QALayer protocol."""
        assert isinstance(DocFidelityReviewer(), QALayer)

    # --- LLM slot ---

    def test_llm_client_slot_raises_not_implemented(self) -> None:
        """Non-None llm_client raises NotImplementedError (AG3-043 slot)."""
        with pytest.raises(NotImplementedError, match="AG3-043"):
            DocFidelityReviewer(llm_client=_DummyLLMClient())

    # --- review_input=None raises (fail-closed) ---

    def test_review_input_none_raises_layer2_input_missing_error(
        self, tmp_path: Path
    ) -> None:
        """review_input=None must raise Layer2InputMissingError (fail-closed)."""
        with pytest.raises(Layer2InputMissingError):
            DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=None)

    # --- PASS path ---

    def test_pass_on_empty_dir(self, tmp_path: Path) -> None:
        """PASS: empty story_dir (no .py files) produces no BLOCKING findings.

        Pass-4 ERROR-5: pin empty Layer2ReviewInput emits MAJOR ``layer2_input.missing``.
        """
        from agentkit.backend.verify_system.protocols import Severity

        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        # layer2_input.missing is MAJOR, not BLOCKING -> passed=True
        assert result.passed is True
        missing = [f for f in result.findings if f.check == "layer2_input.missing"]
        assert len(missing) == 1
        assert missing[0].severity is Severity.MAJOR

    def test_pass_on_fully_documented_module(self, tmp_path: Path) -> None:
        """PASS: all public items have docstrings and FK anchor."""
        _write_py(
            tmp_path / "well_documented.py",
            '"""Well documented module. FK-27 anchor here.\n\nSome details.\n"""\n\n'
            "from pydantic import BaseModel, ConfigDict\n\n"
            "class MyModel(BaseModel):\n"
            '    """FK-27: MyModel does things."""\n\n'
            "    model_config = ConfigDict(extra=\"forbid\", frozen=True)\n\n"
            "    name: str\n",
        )

        ri = Layer2ReviewInput(handover="All documented.")
        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=ri)

        # Should have no MAJOR findings (MINOR concept anchor finding allowed
        # if the class docstring doesn't have the anchor, but we put it in).
        major_or_blocking = [
            f for f in result.findings
            if f.severity in (Severity.BLOCKING, Severity.MAJOR)
        ]
        assert major_or_blocking == []

    # --- FAIL paths ---

    def test_missing_docstring_produces_major_finding(self, tmp_path: Path) -> None:
        """FAIL: public function without docstring -> MAJOR."""
        _write_py(
            tmp_path / "undocumented.py",
            '"""Module docstring. FK-27."""\n\ndef public_function():\n    pass\n',
        )

        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "doc_fidelity.missing_docstring" in checks
        missing = [
            f for f in result.findings
            if f.check == "doc_fidelity.missing_docstring"
        ]
        assert missing[0].severity == Severity.MAJOR

    def test_no_concept_anchor_in_class_produces_minor_finding(self, tmp_path: Path) -> None:
        """FAIL: class without FK/DK anchor -> MINOR."""
        _write_py(
            tmp_path / "no_anchor.py",
            '"""Module without concept anchor."""\n\n'
            "class MyWidget:\n"
            '    """A widget. No FK anchor here.\n\n    Details.\n    """\n\n'
            "    pass\n",
        )

        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "doc_fidelity.no_concept_anchor" in checks
        anchor = [f for f in result.findings if f.check == "doc_fidelity.no_concept_anchor"]
        assert anchor[0].severity == Severity.MINOR

    def test_pydantic_model_missing_extra_produces_major_finding(
        self, tmp_path: Path
    ) -> None:
        """FAIL: BaseModel subclass without extra='forbid' -> MAJOR."""
        _write_py(
            tmp_path / "bad_model.py",
            '"""Module. FK-99."""\n\n'
            "from pydantic import BaseModel\n\n"
            "class BadModel(BaseModel):\n"
            '    """FK-99: Bad model without config.\n\n    No extra forbid.\n    """\n\n'
            "    name: str\n",
        )

        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        checks = {f.check for f in result.findings}
        assert "doc_fidelity.pydantic_config_missing" in checks
        pyd = [
            f for f in result.findings
            if f.check == "doc_fidelity.pydantic_config_missing"
        ]
        assert pyd[0].severity == Severity.MAJOR

    def test_private_class_skipped_for_docstring(self, tmp_path: Path) -> None:
        """Private classes (starting with _) are not checked for docstrings."""
        _write_py(
            tmp_path / "private_class.py",
            '"""Module."""\n\nclass _InternalThing:\n    pass\n',
        )

        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())

        missing = [
            f for f in result.findings if f.check == "doc_fidelity.missing_docstring"
        ]
        assert len(missing) == 0

    def test_prompt_audit_in_metadata(self, tmp_path: Path) -> None:
        """evaluate() always includes 'prompt_audit' in metadata."""
        result = DocFidelityReviewer().evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert "prompt_audit" in result.metadata
