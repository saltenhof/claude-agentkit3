"""Architecture conformance: governance modules must not have module-level runtime imports
from agentkit.state_backend.store (the store package or its submodules).

AG3-031 Pass-5 Fix E9: pin that agentkit.governance.{integrity_gate,setup_preflight_gate.phase,runner}
contain no module-level or class-level ``from agentkit.state_backend.store`` imports outside
TYPE_CHECKING blocks.  Lazy imports inside function/method bodies are acceptable (they are
deferred, not side-effects of module loading).  The canonical wiring point is the composition
root (``agentkit.bootstrap.composition_root``).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def _source_path(module_name: str) -> Path:
    """Resolve the source file for a module."""
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Module {module_name!r} not found"
    assert spec.origin is not None, f"Module {module_name!r} has no origin"
    return Path(spec.origin)


def _collect_module_level_state_backend_store_imports(source: str) -> list[str]:
    """Return all module-level ``from agentkit.state_backend.store...`` imports that are
    NOT inside ``if TYPE_CHECKING`` blocks and NOT inside function/method bodies.

    Only checks:
    - Top-level import statements
    - Imports inside class bodies (but NOT inside methods)

    Returns list of import statement lines that violate the constraint.
    """
    tree = ast.parse(source)

    # Collect linenos that are inside TYPE_CHECKING blocks.
    type_checking_linenos: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_type_checking = (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "typing"
                and test.attr == "TYPE_CHECKING"
            )
        )
        if is_type_checking:
            for child in ast.walk(node):
                if hasattr(child, "lineno"):
                    type_checking_linenos.add(child.lineno)

    # Collect linenos that are inside function/method bodies.
    function_body_linenos: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if hasattr(child, "lineno"):
                function_body_linenos.add(child.lineno)

    lines = source.splitlines()
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if node.lineno in type_checking_linenos:
            continue
        if node.lineno in function_body_linenos:
            # Lazy import inside a function body — acceptable.
            continue
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module == "agentkit.state_backend.store"
                or node.module.startswith("agentkit.state_backend.store.")
            )
        ):
            violations.append(lines[node.lineno - 1].strip())
    return violations


class TestGovernanceNoModuleLevelStateBackendImports:
    """Governance modules must not have module-level imports from agentkit.state_backend.store.

    AG3-031 Pass-5 Fix E9: all wiring goes through composition_root.
    TYPE_CHECKING-gated imports and lazy imports inside function bodies are allowed.
    """

    def test_integrity_gate_no_module_level_state_backend_store_import(self) -> None:
        """agentkit.governance.integrity_gate has no module-level state_backend.store import."""
        src = _source_path("agentkit.governance.integrity_gate")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.governance.integrity_gate contains forbidden module-level imports "
            f"from agentkit.state_backend.store: {violations}"
        )

    def test_setup_preflight_gate_phase_no_module_level_state_backend_store_import(
        self,
    ) -> None:
        """agentkit.governance.setup_preflight_gate.phase has no module-level state_backend.store import."""
        src = _source_path("agentkit.governance.setup_preflight_gate.phase")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.governance.setup_preflight_gate.phase contains forbidden module-level imports "
            f"from agentkit.state_backend.store: {violations}"
        )

    def test_runner_no_module_level_state_backend_store_import(self) -> None:
        """agentkit.governance.runner has no module-level state_backend.store import."""
        src = _source_path("agentkit.governance.runner")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.governance.runner contains forbidden module-level imports "
            f"from agentkit.state_backend.store: {violations}"
        )
