"""Architecture conformance: governance modules must not have module-level runtime imports
from agentkit.backend.state_backend.store (the store package or its submodules).

AG3-031 Pass-5 Fix E9: pin that agentkit.backend.governance.{integrity_gate,setup_preflight_gate.phase,runner}
contain no module-level or class-level ``from agentkit.backend.state_backend.store`` imports outside
TYPE_CHECKING blocks.  Lazy imports inside function/method bodies are acceptable (they are
deferred, not side-effects of module loading).  The canonical wiring point is the composition
root (``agentkit.backend.bootstrap.composition_root``).

AG3-031 Pass-6 Fix E9: ``setup_preflight_gate.phase`` is additionally checked for ANY
``from agentkit.backend.state_backend.store`` import anywhere in the module — including inside
function bodies — because all wiring must go through DI/composition-root, not lazy fallbacks.
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
    """Return all module-level ``from agentkit.backend.state_backend.store...`` imports that are
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
                node.module == "agentkit.backend.state_backend.store"
                or node.module.startswith("agentkit.backend.state_backend.store.")
            )
        ):
            violations.append(lines[node.lineno - 1].strip())
    return violations


def _collect_all_state_backend_store_imports(source: str) -> list[str]:
    """Return ALL ``from agentkit.backend.state_backend.store...`` imports anywhere in the module.

    Unlike ``_collect_module_level_state_backend_store_imports``, this also
    catches lazy imports inside function/method bodies.  Only TYPE_CHECKING
    blocks are excluded.

    Used for ``setup_preflight_gate.phase`` where even lazy fallbacks are
    forbidden (AG3-031 Pass-6 Fix E9).
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

    lines = source.splitlines()
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if node.lineno in type_checking_linenos:
            continue
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module == "agentkit.backend.state_backend.store"
                or node.module.startswith("agentkit.backend.state_backend.store.")
            )
        ):
            violations.append(lines[node.lineno - 1].strip())
    return violations


def _collect_imports_matching(source: str, forbidden: tuple[str, ...]) -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == item or alias.name.startswith(f"{item}.")
                    for item in forbidden
                ):
                    violations.append(lines[node.lineno - 1].strip())
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names = {alias.name for alias in node.names}
            if any(
                module == item or module.startswith(f"{item}.") for item in forbidden
            ):
                violations.append(lines[node.lineno - 1].strip())
            if "PostToolOutcome" in imported_names:
                violations.append(lines[node.lineno - 1].strip())
    return violations


class TestGovernanceNoModuleLevelStateBackendImports:
    """Governance modules must not have module-level imports from agentkit.backend.state_backend.store.

    AG3-031 Pass-5 Fix E9: all wiring goes through composition_root.
    TYPE_CHECKING-gated imports and lazy imports inside function bodies are allowed.
    """

    def test_integrity_gate_no_module_level_state_backend_store_import(self) -> None:
        """agentkit.backend.governance.integrity_gate has no module-level state_backend.store import."""
        src = _source_path("agentkit.backend.governance.integrity_gate")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.backend.governance.integrity_gate contains forbidden module-level imports "
            f"from agentkit.backend.state_backend.store: {violations}"
        )

    def test_setup_preflight_gate_phase_no_module_level_state_backend_store_import(
        self,
    ) -> None:
        """agentkit.backend.governance.setup_preflight_gate.phase has no module-level state_backend.store import."""
        src = _source_path("agentkit.backend.governance.setup_preflight_gate.phase")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.backend.governance.setup_preflight_gate.phase contains forbidden module-level imports "
            f"from agentkit.backend.state_backend.store: {violations}"
        )

    def test_setup_preflight_gate_phase_no_lazy_state_backend_store_import(
        self,
    ) -> None:
        """agentkit.backend.governance.setup_preflight_gate.phase has no lazy state_backend.store import anywhere.

        AG3-031 Pass-6 Fix E9: even lazy (function-body) imports from
        agentkit.backend.state_backend.store are forbidden in this module.  All wiring
        must go through DI parameters or the composition root.
        """
        src = _source_path("agentkit.backend.governance.setup_preflight_gate.phase")
        violations = _collect_all_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.backend.governance.setup_preflight_gate.phase contains forbidden imports "
            f"(including lazy) from agentkit.backend.state_backend.store: {violations}"
        )

    def test_runner_no_module_level_state_backend_store_import(self) -> None:
        """agentkit.backend.governance.runner has no module-level state_backend.store import."""
        src = _source_path("agentkit.backend.governance.runner")
        violations = _collect_module_level_state_backend_store_imports(
            src.read_text(encoding="utf-8")
        )
        assert not violations, (
            f"agentkit.backend.governance.runner contains forbidden module-level imports "
            f"from agentkit.backend.state_backend.store: {violations}"
        )

    def test_harness_adapters_do_not_import_worker_health_contract(self) -> None:
        modules = [
            "agentkit.harness_client.harness_adapters.claude_code",
            "agentkit.harness_client.harness_adapters.codex.event_mapping",
            "agentkit.harness_client.harness_adapters.post_tool_outcome",
        ]
        violations: dict[str, list[str]] = {}
        for module in modules:
            src = _source_path(module)
            found = _collect_imports_matching(
                src.read_text(encoding="utf-8"),
                ("agentkit.backend.implementation",),
            )
            if found:
                violations[module] = found
        assert violations == {}
