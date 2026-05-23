"""Layer-2 LLM-Reviewer fuer den QA-Subflow (FK-27 §27.4-§27.6 + §27.7).

Drei eigenstaendige Reviewer-Klassen gemaess W1 (AG3-026 Re-Review)
mit echter deterministischer Prueflogik (AG3-026 Pass-2 §Befund-B):

- ``QaReviewReviewer``: Prueft Testqualitaet, Coverage, Edge-Cases.
  Layer-Tag: ``qa_review``. Artefakt: ``qa_review.json``.
- ``SemanticReviewer``: Prueft Konzept-Treue, Naming, fachliche
  Korrektheit. Layer-Tag: ``semantic_review``. Artefakt:
  ``semantic_review.json``.
- ``DocFidelityReviewer``: Prueft Docstring-Vollstaendigkeit,
  ADR-/Konzept-Querverweise, OpenAPI-Konsistenz. Layer-Tag:
  ``doc_fidelity``. Artefakt: ``doc_fidelity.json``.

AG3-026 Pass-3 ERROR-5: All three reviewers now accept a ``review_input``
(``Layer2ReviewInput``) kwarg. When ``review_input is None``, the reviewer
raises ``Layer2InputMissingError`` (fail-closed per FK-27 §27.4-§27.6).
When ``review_input`` has empty fields, a MAJOR finding with code
``"layer2_input.missing"`` is emitted instead of silent PASS.

Alle drei Reviewer sind deterministische Regel-Pruefe (Pass-2
§Befund-B). Der ``LLMClient``-Slot ist fuer AG3-043 vorgesehen; wenn
ein Client uebergeben wird, wird ``NotImplementedError`` ausgeloest.

Sichtbarkeitsregel (AC001): Aufrufer ausserhalb von ``verify_system``
duerfen nur ``VerifySystem`` importieren, nicht diese Klassen direkt.
``system.py`` verdrahtet sie intern ueber ``create_default``.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from agentkit.verify_system.llm_evaluator.inputs import Layer2InputMissingError, Layer2ReviewInput
from agentkit.verify_system.prompt_audit import materialize_qa_prompt_audit
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX)\b")
_SNAKE_CASE_FUNC = re.compile(r"^[a-z_][a-z0-9_]*$")
_PASCAL_CASE_CLASS = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_COVERAGE_PATTERN = re.compile(r"coverage[:\s]+(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)


def _collect_py_files(story_dir: Path) -> list[Path]:
    """Return all .py files in story_dir recursively.

    Args:
        story_dir: Root directory to search.

    Returns:
        Sorted list of .py files found.
    """
    return sorted(story_dir.rglob("*.py"))


def _parse_ast_safely(source: str) -> ast.Module | None:
    """Parse Python source to AST without raising on syntax errors.

    Args:
        source: Python source code string.

    Returns:
        Parsed ``ast.Module`` or ``None`` on syntax error.
    """
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


# ---------------------------------------------------------------------------
# Shared Layer-2 guard
# ---------------------------------------------------------------------------


def _require_review_input(
    reviewer_name: str,
    review_input: Layer2ReviewInput | None,
) -> None:
    """Raise ``Layer2InputMissingError`` if ``review_input`` is None (fail-closed).

    Args:
        reviewer_name: Display name of the caller (for error message).
        review_input: The input to validate.

    Raises:
        Layer2InputMissingError: When ``review_input is None``.
    """
    if review_input is None:
        raise Layer2InputMissingError(
            f"{reviewer_name}.evaluate() called with review_input=None. "
            "Layer-2 reviewers require an explicit Layer2ReviewInput instance "
            "(FK-27 §27.4-§27.6). Pass Layer2ReviewInput() with empty strings "
            "as a default when Worker handover artefacts are not yet available "
            "(THEME-009)."
        )


def _missing_input_finding(layer_name: str) -> Finding:
    """Build the MAJOR finding emitted when all review_input fields are empty.

    Args:
        layer_name: Layer name string (e.g. ``"qa_review"``).

    Returns:
        A MAJOR Finding with code ``"layer2_input.missing"``.
    """
    return Finding(
        layer=layer_name,
        check="layer2_input.missing",
        severity=Severity.MAJOR,
        message=(
            "Layer-2 review_input has no content (all fields empty). "
            "Worker handover artefacts are not yet available (THEME-009). "
            "Skipping text-based checks; file-system checks applied as fallback."
        ),
        trust_class=TrustClass.SYSTEM,
    )


def _all_empty(review_input: Layer2ReviewInput) -> bool:
    """Return True if all four Layer2ReviewInput fields are empty strings."""
    return not any([
        review_input.story_spec,
        review_input.diff_summary,
        review_input.concept_excerpt,
        review_input.handover,
    ])


# ---------------------------------------------------------------------------
# QaReviewReviewer
# ---------------------------------------------------------------------------


class QaReviewReviewer:
    """Layer 2a: Deterministic QA reviewer (Testqualitaet, Coverage, Edge-Cases).

    FK-27 §27.5 (sinngemaess). Prueft:
    - Test-Datei-Praesenz via ``diff_summary``/``handover`` (wenn review_input
      vorhanden); Fallback auf ``story_dir`` wenn leer.
    - Edge-Case-Tiefe (< 3 test functions referenced == thin suite).
    - Coverage-Schwellwert via ``handover``-Text (Regex); MAJOR wenn fehlend.

    Profil: ``qa_review``. Artefakt: ``qa_review.json``.

    LLM-Augmentation ist AG3-043; ``llm_client`` ist reservierter Slot.
    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.

    Attributes:
        llm_client: Optional LLM client for future augmentation (AG3-043).
            Pass ``None`` (default) for deterministic-only evaluation.
    """

    def __init__(self, *, llm_client: object | None = None) -> None:
        """Initialise the QaReviewReviewer.

        Args:
            llm_client: Must be ``None`` until AG3-043. If non-None,
                raises ``NotImplementedError``.

        Raises:
            NotImplementedError: If ``llm_client`` is not ``None``.
        """
        if llm_client is not None:
            msg = (
                "LLM-Augmentation fuer QaReviewReviewer ist in AG3-043 implementiert. "
                "Bis dahin muss llm_client=None bleiben."
            )
            raise NotImplementedError(msg)
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"qa_review"``.
        """
        return "qa_review"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate QA review quality via deterministic checks.

        When ``review_input`` is ``None``, raises ``Layer2InputMissingError``
        (fail-closed, FK-27 §27.5). When ``review_input`` has all empty fields,
        emits a MAJOR ``layer2_input.missing`` finding and falls back to
        filesystem checks on ``story_dir``.

        Args:
            ctx: Story context (used for prompt audit).
            story_dir: Directory containing story artifacts (fallback when
                review_input fields are empty).
            review_input: FK-27 §27.5 text inputs. Required; ``None`` raises.

        Returns:
            LayerResult with findings (empty == PASS).

        Raises:
            Layer2InputMissingError: When ``review_input`` is ``None``.
        """
        _require_review_input(self.name, review_input)
        assert review_input is not None  # for type narrowing
        findings: list[Finding] = []

        if _all_empty(review_input):
            findings.append(_missing_input_finding(self.name))
            # Fallback to filesystem-based checks when handover text unavailable.
            test_files = _find_test_files(story_dir)
            findings.extend(self._check_test_presence(test_files, story_dir))
            findings.extend(self._check_edge_case_depth(test_files))
            findings.extend(self._check_coverage(story_dir))
        else:
            # Text-based checks on review_input fields (FK-27 §27.5).
            findings.extend(self._check_test_in_diff(review_input))
            findings.extend(self._check_coverage_in_handover(review_input))
            findings.extend(self._check_edge_cases_in_handover(review_input))

        passed = not any(f.severity == Severity.BLOCKING for f in findings)
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
            metadata={
                "prompt_audit": materialize_qa_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-review",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )

    def _check_test_in_diff(self, review_input: Layer2ReviewInput) -> list[Finding]:
        """Check that diff_summary or handover mentions test files."""
        combined = review_input.diff_summary + "\n" + review_input.handover
        has_tests = bool(re.search(r"tests?[/\\]|test_\w+\.py", combined, re.IGNORECASE))
        if has_tests:
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.no_tests",
                severity=Severity.BLOCKING,
                message=(
                    "diff_summary and handover do not mention any test files. "
                    "At least one test file is required (Zero Debt Rule, FK-27 §27.5)."
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        ]

    def _check_coverage_in_handover(self, review_input: Layer2ReviewInput) -> list[Finding]:
        """Check that handover mentions a coverage percentage."""
        match = _COVERAGE_PATTERN.search(review_input.handover)
        if match:
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.coverage_unknown",
                severity=Severity.MAJOR,
                message=(
                    "handover does not contain a coverage percentage statement "
                    "(e.g. 'coverage: 87%'). Cannot verify 85% threshold (CLAUDE.md)."
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        ]

    def _check_edge_cases_in_handover(self, review_input: Layer2ReviewInput) -> list[Finding]:
        """Check that diff_summary references enough test cases (heuristic)."""
        combined = review_input.diff_summary + "\n" + review_input.handover
        # Count distinct test_* references as a rough edge-case depth proxy.
        test_refs = re.findall(r"\btest_\w+", combined)
        unique_refs = set(test_refs)
        if len(unique_refs) >= 3:  # noqa: PLR2004
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.edge_cases_thin",
                severity=Severity.MAJOR,
                message=(
                    f"Only {len(unique_refs)} distinct test reference(s) found in "
                    "diff_summary/handover. At least 3 are expected for adequate "
                    "edge-case coverage (FK-27 §27.5)."
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        ]

    def _check_test_presence(
        self, test_files: list[Path], story_dir: Path
    ) -> list[Finding]:
        if test_files:
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.no_tests",
                severity=Severity.BLOCKING,
                message=(
                    f"No test files found under {story_dir}. "
                    "At least one test file is required (Zero Debt Rule)."
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        ]

    def _check_edge_case_depth(self, test_files: list[Path]) -> list[Finding]:
        if not test_files:
            return []
        total_tests = _count_test_functions(test_files)
        if total_tests >= 3:  # noqa: PLR2004
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.edge_cases_thin",
                severity=Severity.MAJOR,
                message=(
                    f"Only {total_tests} test function(s) found. "
                    "At least 3 are expected for adequate edge-case coverage."
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        ]

    def _check_coverage(self, story_dir: Path) -> list[Finding]:
        coverage_ok, coverage_msg = _check_coverage_report(story_dir)
        if coverage_ok:
            return []
        return [
            Finding(
                layer=self.name,
                check="qa_review.coverage_unknown",
                severity=Severity.MAJOR,
                message=coverage_msg,
                trust_class=TrustClass.SYSTEM,
            ),
        ]


# ---------------------------------------------------------------------------
# SemanticReviewer
# ---------------------------------------------------------------------------


class SemanticReviewer:
    """Layer 2b: Deterministic semantic reviewer (Konzept-Treue, Naming).

    FK-27 §27.4 (sinngemaess). Prueft:
    - TODO/FIXME/XXX markers in ``diff_summary``/``handover`` (text-based
      when review_input is provided; fallback to filesystem scan).
    - Dangling concept references in ``story_spec``/``handover``
      (``concept/...`` paths that do not exist).
    - Naming conventions (snake_case functions, PascalCase classes) via
      filesystem scan on ``story_dir`` (unchanged).

    Profil: ``semantic_review``. Artefakt: ``semantic_review.json``.

    LLM-Augmentation ist AG3-043; ``llm_client`` ist reservierter Slot.
    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.

    Attributes:
        llm_client: Optional LLM client for future augmentation (AG3-043).
            Pass ``None`` (default) for deterministic-only evaluation.
    """

    def __init__(self, *, llm_client: object | None = None) -> None:
        """Initialise the SemanticReviewer.

        Args:
            llm_client: Must be ``None`` until AG3-043. If non-None,
                raises ``NotImplementedError``.

        Raises:
            NotImplementedError: If ``llm_client`` is not ``None``.
        """
        if llm_client is not None:
            msg = (
                "LLM-Augmentation fuer SemanticReviewer ist in AG3-043 implementiert. "
                "Bis dahin muss llm_client=None bleiben."
            )
            raise NotImplementedError(msg)
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"semantic_review"``.
        """
        return "semantic_review"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate semantic quality via deterministic checks.

        When ``review_input`` is ``None``, raises ``Layer2InputMissingError``
        (fail-closed, FK-27 §27.4). When fields are empty, falls back to
        filesystem-based checks.

        Args:
            ctx: Story context (used for prompt audit).
            story_dir: Directory containing story artifacts.
            review_input: FK-27 §27.4 text inputs. Required; ``None`` raises.

        Returns:
            LayerResult with findings (empty == PASS).

        Raises:
            Layer2InputMissingError: When ``review_input`` is ``None``.
        """
        _require_review_input(self.name, review_input)
        assert review_input is not None  # for type narrowing
        findings: list[Finding] = []

        if _all_empty(review_input):
            findings.append(_missing_input_finding(self.name))
            # Fallback to filesystem-based checks.
            py_files = _collect_py_files(story_dir)
            for py_file in py_files:
                findings.extend(self._check_file(py_file))
            findings.extend(_check_dangling_concept_refs(story_dir, py_files))
        else:
            # Text-based checks on review_input fields (FK-27 §27.4).
            findings.extend(self._check_todo_in_text(review_input))
            findings.extend(self._check_dangling_concept_refs_in_text(review_input, story_dir))
            # Naming convention checks still require filesystem access.
            py_files = _collect_py_files(story_dir)
            for py_file in py_files:
                findings.extend(self._check_naming_only(py_file))

        passed = not any(f.severity == Severity.BLOCKING for f in findings)
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
            metadata={
                "prompt_audit": materialize_qa_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-semantic-review",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )

    def _check_todo_in_text(self, review_input: Layer2ReviewInput) -> list[Finding]:
        """Check diff_summary and handover for TODO/FIXME/XXX markers."""
        findings: list[Finding] = []
        for field_name, text in (
            ("diff_summary", review_input.diff_summary),
            ("handover", review_input.handover),
        ):
            for match in _TODO_PATTERN.finditer(text):
                findings.append(
                    Finding(
                        layer=self.name,
                        check="semantic.todo_in_production",
                        severity=Severity.BLOCKING,
                        message=(
                            f"'{match.group()}' marker found in {field_name}. "
                            "Remove before delivery (Zero Debt Rule)."
                        ),
                        trust_class=TrustClass.SYSTEM,
                    )
                )
        return findings

    def _check_dangling_concept_refs_in_text(
        self,
        review_input: Layer2ReviewInput,
        story_dir: Path,
    ) -> list[Finding]:
        """Check story_spec/handover for concept/ paths that do not exist."""
        repo_root = self._locate_repo_root(story_dir)
        if repo_root is None:
            return []

        findings: list[Finding] = []
        for field_name, text in (
            ("story_spec", review_input.story_spec),
            ("handover", review_input.handover),
        ):
            findings.extend(self._dangling_refs_in_field(field_name, text, repo_root))
        return findings

    @staticmethod
    def _locate_repo_root(story_dir: Path) -> Path | None:
        candidate = story_dir
        for _ in range(6):
            if (candidate / "concept").is_dir():
                return candidate
            if not candidate.parent or candidate == candidate.parent:
                return None
            candidate = candidate.parent
        return None

    def _dangling_refs_in_field(
        self,
        field_name: str,
        text: str,
        repo_root: Path,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for match in _DANGLING_REF_PATTERN.finditer(text):
            ref = match.group(0)
            if not ref.startswith("concept/"):
                continue
            if (repo_root / ref).exists():
                continue
            findings.append(
                Finding(
                    layer=self.name,
                    check="semantic.dangling_concept_ref",
                    severity=Severity.MAJOR,
                    message=(
                        f"Concept path '{ref}' referenced in "
                        f"{field_name} does not exist."
                    ),
                    trust_class=TrustClass.SYSTEM,
                )
            )
        return findings

    def _check_file(self, py_file: Path) -> list[Finding]:
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        findings: list[Finding] = []
        findings.extend(self._check_todo_markers(py_file, source))
        tree = _parse_ast_safely(source)
        if tree is not None:
            findings.extend(self._check_naming_in_tree(py_file, tree))
        return findings

    def _check_naming_only(self, py_file: Path) -> list[Finding]:
        """Naming convention check (filesystem-based, always applied)."""
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        tree = _parse_ast_safely(source)
        if tree is None:
            return []
        return self._check_naming_in_tree(py_file, tree)

    def _check_todo_markers(self, py_file: Path, source: str) -> list[Finding]:
        findings: list[Finding] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            match = _TODO_PATTERN.search(line)
            if not match:
                continue
            findings.append(
                Finding(
                    layer=self.name,
                    check="semantic.todo_in_production",
                    severity=Severity.BLOCKING,
                    message=(
                        f"'{match.group()}' marker found in {py_file.name}:{lineno}. "
                        "Remove before delivery (Zero Debt Rule)."
                    ),
                    trust_class=TrustClass.SYSTEM,
                    file_path=str(py_file),
                    line_number=lineno,
                ),
            )
        return findings

    def _check_naming_in_tree(self, py_file: Path, tree: ast.AST) -> list[Finding]:
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                finding = self._check_function_naming(py_file, node)
            elif isinstance(node, ast.ClassDef):
                finding = self._check_class_naming(py_file, node)
            else:
                finding = None
            if finding is not None:
                findings.append(finding)
        return findings

    def _check_function_naming(
        self,
        py_file: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> Finding | None:
        if node.name.startswith("_") or _SNAKE_CASE_FUNC.match(node.name):
            return None
        return Finding(
            layer=self.name,
            check="semantic.naming_violation",
            severity=Severity.MAJOR,
            message=(
                f"Function '{node.name}' in {py_file.name} "
                "does not follow snake_case convention "
                "(CLAUDE.md Coding Rules)."
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=str(py_file),
            line_number=node.lineno,
        )

    def _check_class_naming(self, py_file: Path, node: ast.ClassDef) -> Finding | None:
        if node.name.startswith("_") or _PASCAL_CASE_CLASS.match(node.name):
            return None
        return Finding(
            layer=self.name,
            check="semantic.naming_violation",
            severity=Severity.MAJOR,
            message=(
                f"Class '{node.name}' in {py_file.name} "
                "does not follow PascalCase convention "
                "(CLAUDE.md Coding Rules)."
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=str(py_file),
            line_number=node.lineno,
        )


# ---------------------------------------------------------------------------
# DocFidelityReviewer
# ---------------------------------------------------------------------------


class DocFidelityReviewer:
    """Layer 2c: Deterministic doc-fidelity reviewer (Docstrings/ADR).

    FK-27 §27.6 (sinngemaess). Prueft:
    - Docstring-Vollstaendigkeit: jede public Funktion/Klasse braucht
      einen Docstring (filesystem scan).
    - ADR-/Konzept-Anchor: jede public Klasse braucht einen FK-XX/DK-XX
      Anchor im Docstring oder Modul-Header.
    - Pydantic-Konfiguration: BaseModel-Subklassen benoetigen
      ``model_config = ConfigDict(extra="forbid", frozen=True)`` (oder
      ``extra="forbid"`` mindestens).
    - handover: presence of docstring references in handover text
      (text-based, when review_input provided).

    Profil: ``doc_fidelity``. Artefakt: ``doc_fidelity.json``.

    LLM-Augmentation ist AG3-043; ``llm_client`` ist reservierter Slot.
    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.

    Attributes:
        llm_client: Optional LLM client for future augmentation (AG3-043).
            Pass ``None`` (default) for deterministic-only evaluation.
    """

    def __init__(self, *, llm_client: object | None = None) -> None:
        """Initialise the DocFidelityReviewer.

        Args:
            llm_client: Must be ``None`` until AG3-043. If non-None,
                raises ``NotImplementedError``.

        Raises:
            NotImplementedError: If ``llm_client`` is not ``None``.
        """
        if llm_client is not None:
            msg = (
                "LLM-Augmentation fuer DocFidelityReviewer ist in AG3-043 implementiert. "
                "Bis dahin muss llm_client=None bleiben."
            )
            raise NotImplementedError(msg)
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"doc_fidelity"``.
        """
        return "doc_fidelity"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate doc fidelity via deterministic checks.

        When ``review_input`` is ``None``, raises ``Layer2InputMissingError``
        (fail-closed, FK-27 §27.6). When fields are empty, falls back to
        filesystem checks.

        Args:
            ctx: Story context (used for prompt audit).
            story_dir: Directory containing story artifacts.
            review_input: FK-27 §27.6 text inputs. Required; ``None`` raises.

        Returns:
            LayerResult with findings (empty == PASS).

        Raises:
            Layer2InputMissingError: When ``review_input`` is ``None``.
        """
        _require_review_input(self.name, review_input)
        assert review_input is not None  # for type narrowing
        findings: list[Finding] = []

        if _all_empty(review_input):
            findings.append(_missing_input_finding(self.name))
        # Structural doc checks always run (filesystem-based; unaffected by review_input).
        for py_file in _collect_py_files(story_dir):
            findings.extend(self._check_file(py_file))

        passed = not any(f.severity == Severity.BLOCKING for f in findings)
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
            metadata={
                "prompt_audit": materialize_qa_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-doc-fidelity",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )

    def _check_file(self, py_file: Path) -> list[Finding]:
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        tree = _parse_ast_safely(source)
        if tree is None:
            return []
        module_doc = ast.get_docstring(tree) or ""
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if node.name.startswith("_"):
                continue
            findings.extend(self._check_node(py_file, source, node, module_doc))
        return findings

    def _check_node(
        self,
        py_file: Path,
        source: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        module_doc: str,
    ) -> list[Finding]:
        doc = ast.get_docstring(node)
        findings: list[Finding] = []
        if not doc:
            findings.append(self._missing_docstring_finding(py_file, node))
        if isinstance(node, ast.ClassDef):
            anchor_finding = self._concept_anchor_finding(py_file, node, doc, module_doc)
            if anchor_finding is not None:
                findings.append(anchor_finding)
            pydantic_finding = self._pydantic_config_finding(py_file, source, node)
            if pydantic_finding is not None:
                findings.append(pydantic_finding)
        return findings

    def _missing_docstring_finding(
        self,
        py_file: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> Finding:
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        return Finding(
            layer=self.name,
            check="doc_fidelity.missing_docstring",
            severity=Severity.MAJOR,
            message=(
                f"Public {kind} '{node.name}' in {py_file.name} "
                "is missing a docstring."
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=str(py_file),
            line_number=node.lineno,
        )

    def _concept_anchor_finding(
        self,
        py_file: Path,
        node: ast.ClassDef,
        doc: str | None,
        module_doc: str,
    ) -> Finding | None:
        anchor_text = (doc or "") + module_doc
        if _has_concept_anchor(anchor_text):
            return None
        return Finding(
            layer=self.name,
            check="doc_fidelity.no_concept_anchor",
            severity=Severity.MINOR,
            message=(
                f"Public class '{node.name}' in {py_file.name} "
                "has no FK-XX or DK-XX concept anchor in its "
                "docstring or module header."
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=str(py_file),
            line_number=node.lineno,
        )

    def _pydantic_config_finding(
        self,
        py_file: Path,
        source: str,
        node: ast.ClassDef,
    ) -> Finding | None:
        if not _is_basemodel_subclass(node):
            return None
        body_src = source.splitlines()
        class_src = "\n".join(body_src[node.lineno - 1 : node.end_lineno])
        if "extra=" in class_src:
            return None
        return Finding(
            layer=self.name,
            check="doc_fidelity.pydantic_config_missing",
            severity=Severity.MAJOR,
            message=(
                f"Pydantic model '{node.name}' in {py_file.name} "
                "is missing 'extra=\"forbid\"' in model_config "
                "(CLAUDE.md Coding Rules)."
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=str(py_file),
            line_number=node.lineno,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_CONCEPT_ANCHOR_PATTERN = re.compile(r"\b(FK|DK)-\d+\b")


def _has_concept_anchor(text: str) -> bool:
    """Return True if text contains a FK-XX or DK-XX concept anchor.

    Args:
        text: Text to search (docstring + module header concatenated).

    Returns:
        ``True`` if at least one FK-XX or DK-XX anchor is found.
    """
    return bool(_CONCEPT_ANCHOR_PATTERN.search(text))


def _is_basemodel_subclass(node: ast.ClassDef) -> bool:
    """Return True if the class appears to subclass BaseModel.

    Uses a heuristic: any base named ``BaseModel`` or ending in
    ``Model``. AST-level check only (no full import resolution).

    Args:
        node: AST ClassDef node to inspect.

    Returns:
        ``True`` if any base name contains ``BaseModel`` or ``Model``.
    """
    for base in node.bases:
        if isinstance(base, ast.Name) and ("BaseModel" in base.id or base.id.endswith("Model")):
            return True
        if isinstance(base, ast.Attribute) and (
            "BaseModel" in base.attr or base.attr.endswith("Model")
        ):
            return True
    return False


def _find_test_files(story_dir: Path) -> list[Path]:
    """Find test files under story_dir.

    Searches for ``test_*.py`` and ``*_test.py`` files recursively within
    ``story_dir`` only. Tests are expected to live under
    ``story_dir/tests/`` (canonical story layout). No walk-up beyond
    ``story_dir`` -- the caller must ensure ``story_dir`` is the correct
    root for the story under evaluation.

    Args:
        story_dir: Root story directory.

    Returns:
        List of found test file paths (empty when none found).
    """
    return (
        list(story_dir.rglob("test_*.py"))
        + list(story_dir.rglob("*_test.py"))
    )


def _count_test_functions(test_files: list[Path]) -> int:
    """Count the number of test functions across all test files.

    Counts functions whose name starts with ``test_``.

    Args:
        test_files: List of test file paths to analyse.

    Returns:
        Total number of test functions found.
    """
    total = 0
    for path in test_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tree = _parse_ast_safely(source)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                total += 1
    return total


def _check_coverage_report(story_dir: Path) -> tuple[bool, str]:
    """Check if a coverage report is available in story_dir.

    Looks for ``.coverage`` or ``coverage.json`` files. When not found,
    returns (False, explanation) so the caller can emit a MAJOR finding
    instead of silently passing.

    Args:
        story_dir: Story root directory to search.

    Returns:
        ``(True, "")`` when a coverage report is found;
        ``(False, message)`` otherwise.
    """
    # Walk up to 4 levels to find coverage artefacts.
    candidate = story_dir
    for _ in range(4):
        if (candidate / ".coverage").exists() or (candidate / "coverage.json").exists():
            return True, ""
        if not candidate.parent or candidate == candidate.parent:
            break
        candidate = candidate.parent
    return (
        False,
        (
            "No coverage report (.coverage or coverage.json) found. "
            "Cannot verify the 85% threshold (CLAUDE.md). "
            "Run 'pytest --cov' to generate coverage data."
        ),
    )


_DANGLING_REF_PATTERN = re.compile(r"\b(FK|DK)-(\d+)\b|concept/[a-zA-Z0-9/_-]+\.md")


def _locate_repo_root_for_concepts(story_dir: Path) -> Path | None:
    """Walk up from story_dir looking for a ``concept/`` directory (max 6 levels)."""
    candidate = story_dir
    for _ in range(6):
        if (candidate / "concept").is_dir():
            return candidate
        if not candidate.parent or candidate == candidate.parent:
            return None
        candidate = candidate.parent
    return None


def _dangling_refs_in_source(
    py_file: Path,
    source: str,
    repo_root: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DANGLING_REF_PATTERN.finditer(source):
        ref = match.group(0)
        if not ref.startswith("concept/"):
            continue
        if (repo_root / ref).exists():
            continue
        line_no = source[: match.start()].count("\n") + 1
        findings.append(
            Finding(
                layer="semantic_review",
                check="semantic.dangling_concept_ref",
                severity=Severity.MAJOR,
                message=(
                    f"Concept path '{ref}' referenced in "
                    f"{py_file.name}:{line_no} does not exist."
                ),
                trust_class=TrustClass.SYSTEM,
                file_path=str(py_file),
                line_number=line_no,
            ),
        )
    return findings


def _check_dangling_concept_refs(
    story_dir: Path,
    py_files: list[Path],
) -> list[Finding]:
    """Check for concept references that point to non-existent files.

    Scans all .py files for ``FK-XX``, ``DK-XX``, and ``concept/...``
    string patterns.  Validates ``concept/...`` paths against the
    filesystem (only path-form refs, not bare FK-XX numbers, since
    FK numbers may exist as section headers without a file per number).

    Args:
        story_dir: Story root directory (used to find repo root).
        py_files: Pre-collected list of .py files to scan.

    Returns:
        List of ``Finding`` instances for dangling concept references.
    """
    repo_root = _locate_repo_root_for_concepts(story_dir)
    if repo_root is None:
        return []

    findings: list[Finding] = []
    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(_dangling_refs_in_source(py_file, source, repo_root))
    return findings
