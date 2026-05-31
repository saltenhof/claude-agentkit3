"""E5 (AG3-015 Review R1): QA prompt-audit goes through the top surface only.

FK-44 §44.4.2: ``verify_system`` must resolve QA/evaluator prompts exclusively
via ``PromptRuntime.materialize_prompt`` and persist audit via
``ArtifactManager`` -- never by importing the prompt-runtime sub-modules
(``compose_named_prompt`` / ``initialize_prompt_run_pin`` /
``write_rendered_prompt_artifact``) or ``state_backend.store`` directly.

This pins the boundary so the previous top-surface bypass cannot regress.
"""

from __future__ import annotations

import ast
from pathlib import Path

import agentkit.verify_system.prompt_audit as prompt_audit_module

_FORBIDDEN_NAMES = frozenset(
    {
        "compose_named_prompt",
        "initialize_prompt_run_pin",
        "write_rendered_prompt_artifact",
        "resolve_runtime_scope",
    },
)


def _imported_names(module_file: Path) -> set[str]:
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                names.add(alias.name)
                if "state_backend.store" in module:
                    names.add("state_backend.store")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_prompt_audit_does_not_import_subsurface_or_state_backend() -> None:
    module_file = Path(prompt_audit_module.__file__)
    imported = _imported_names(module_file)
    assert not (_FORBIDDEN_NAMES & imported), (
        "verify_system.prompt_audit must not import prompt-runtime sub-surface "
        f"helpers or state_backend.store directly; found: "
        f"{_FORBIDDEN_NAMES & imported}"
    )
    assert "state_backend.store" not in imported


def test_prompt_audit_uses_prompt_runtime_top_surface() -> None:
    """The module imports the PromptRuntime top surface (FK-44 §44.4.2)."""
    module_file = Path(prompt_audit_module.__file__)
    imported = _imported_names(module_file)
    assert "PromptRuntime" in imported
