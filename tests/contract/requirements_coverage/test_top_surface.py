"""Contract tests for RequirementsCoverage top-surface (AG3-030).

Pins:
- All four dock-point method signatures and the is_enabled property.
- Architecture conformance: agentkit.backend.requirements_coverage must NOT
  import from agentkit.integration_clients.are.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# Signature pinning
# ---------------------------------------------------------------------------
from agentkit.backend.requirements_coverage.top import RequirementsCoverage


class TestRequirementsCoverageSignatures:
    """All public methods and properties have stable, pinned signatures."""

    def test_is_enabled_is_property(self) -> None:
        assert isinstance(
            inspect.getattr_static(RequirementsCoverage, "is_enabled"),
            property,
        )

    def test_link_requirements_signature(self) -> None:
        sig = inspect.signature(RequirementsCoverage.link_requirements)
        params = list(sig.parameters)
        assert params == ["self", "story_id", "project_key"]

    def test_load_context_signature(self) -> None:
        sig = inspect.signature(RequirementsCoverage.load_context)
        params = list(sig.parameters)
        assert params == ["self", "story_id", "run_id"]

    def test_submit_evidence_signature(self) -> None:
        sig = inspect.signature(RequirementsCoverage.submit_evidence)
        params = list(sig.parameters)
        assert params == ["self", "story_id", "evidence"]

    def test_check_gate_signature(self) -> None:
        sig = inspect.signature(RequirementsCoverage.check_gate)
        params = list(sig.parameters)
        assert params == ["self", "story_id", "project_key"]

    def test_init_signature(self) -> None:
        sig = inspect.signature(RequirementsCoverage.__init__)
        params = list(sig.parameters)
        assert params == [
            "self",
            "are_client",
            "pipeline_config",
            "link_repository",
            "story_context_provider",
            "artifact_manager",
            "scope_mapping",
            "audit_root",
        ]
        assert sig.parameters["link_repository"].kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# Architecture conformance
# ---------------------------------------------------------------------------

_RC_SRC = (
    Path(__file__).parent.parent.parent.parent
    / "src"
    / "agentkit"
    / "requirements_coverage"
)

_FORBIDDEN_IMPORT = "agentkit.integration_clients.are"
_FORBIDDEN_FROM = ("agentkit", "integrations", "are")


def _collect_python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _file_imports_forbidden_module(path: Path) -> bool:
    """Return True if the file contains an import from agentkit.integration_clients.are."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_FORBIDDEN_IMPORT):
                    return True
        elif isinstance(node, ast.ImportFrom):
            # Reconstruct module path
            module = node.module or ""
            if module.startswith(_FORBIDDEN_IMPORT):
                return True
            # Handle relative imports within requirements_coverage
            # (these should never reach integrations.are anyway)
    return False


class TestArchitectureConformance:
    """requirements_coverage must not import from integrations.are (FK-40 §40.4)."""

    def test_no_import_from_integrations_are(self) -> None:
        violations: list[str] = []
        for py_file in _collect_python_files(_RC_SRC):
            if _file_imports_forbidden_module(py_file):
                violations.append(str(py_file))

        assert not violations, (
            "The following files in agentkit.backend.requirements_coverage import from "
            "agentkit.integration_clients.are, which is forbidden (FK-40 §40.4 — "
            "AreClient is BC-internal, not an integrations adapter):\n"
            + "\n".join(violations)
        )

    def test_are_client_module_is_in_requirements_coverage(self) -> None:
        """AreClient must live in requirements_coverage, not integrations."""
        mod = importlib.import_module("agentkit.backend.requirements_coverage.are_client")
        assert hasattr(mod, "AreClient")

    def test_integrations_are_is_empty(self) -> None:
        """agentkit.integration_clients.are.__init__ must not re-export AreClient."""
        mod = importlib.import_module("agentkit.integration_clients.are")
        # The module must not expose AreClient
        assert not hasattr(mod, "AreClient"), (
            "agentkit.integration_clients.are must not re-export AreClient — "
            "AreClient is BC-internal to requirements_coverage (FK-40 §40.4)"
        )
