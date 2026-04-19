"""Unit tests for the truth-boundary contract checker."""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from concept_compiler import (
    audit_truth_boundary,
    compile_formal_specs,
    load_truth_boundary_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_truth_boundary_loads_formal_policy(tmp_path: Path) -> None:
    root = _write_fixture(tmp_path, protected_module="agentkit.governance.guard")

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_truth_boundary_config(compiled)

    assert "agentkit.governance" in config.protected_module_prefixes
    assert "context.json" in config.forbidden_json_truth_filenames
    assert "load_verify_decision_artifact" in config.forbidden_loader_symbols


def test_truth_boundary_rejects_json_load_in_protected_module(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.governance.guard",
        source="""
            import json

            def evaluate(story_dir):
                with (story_dir / "context.json").open("r", encoding="utf-8") as handle:
                    return json.load(handle)
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert {violation.code for violation in violations} >= {"TB001", "TB004", "TB005"}


def test_truth_boundary_rejects_forbidden_loader_import(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.pipeline.verify_gate",
        source="""
            from agentkit.qa.artifacts import load_verify_decision_artifact

            def evaluate(story_dir):
                return load_verify_decision_artifact(story_dir)
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert any(violation.code == "TB002" for violation in violations)
    assert any(violation.code == "TB003" for violation in violations)


def test_truth_boundary_rejects_globbed_phase_state_reads(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.pipeline.runner",
        source="""
            def evaluate(story_dir, phase):
                snapshot_path = story_dir / f"phase-state-{phase}.json"
                return snapshot_path.exists()
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert any("phase-state-*.json" in violation.message for violation in violations)


def test_truth_boundary_rejects_builtin_open_on_forbidden_export(
    tmp_path: Path,
) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.governance.guard",
        source="""
            def evaluate(story_dir):
                with open(story_dir / "decision.json", "r", encoding="utf-8") as handle:
                    return handle.read()
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert any(violation.code == "TB004" for violation in violations)


def test_truth_boundary_allows_cli_export_modules(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.cli.export_artifacts",
        source="""
            import json

            def export_context(story_dir):
                return json.loads(
                    (story_dir / "context.json").read_text(encoding="utf-8")
                )
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert violations == ()


def test_truth_boundary_accepts_clean_protected_module(tmp_path: Path) -> None:
    root = _write_fixture(
        tmp_path,
        protected_module="agentkit.governance.guard",
        source="""
            def evaluate(state_reader, story_id):
                return state_reader.get_story_context(story_id)
        """,
    )

    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_truth_boundary(compiled, root / "src")

    assert violations == ()


def _write_fixture(
    tmp_path: Path,
    *,
    protected_module: str,
    source: str | None = None,
) -> Path:
    root = tmp_path / "repo"
    formal_root = root / "concept" / "formal-spec" / "truth-boundary-checker"
    source_root = root / "src"
    formal_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    (formal_root / "invariants.md").write_text(
        dedent(
            """
            ---
            id: formal.truth-boundary-checker.invariants
            title: Truth Boundary Checker Invariants
            status: active
            doc_kind: spec
            context: truth-boundary-checker
            spec_kind: invariant-set
            version: 1
            prose_refs: []
            ---

            # Test Invariants

            <!-- FORMAL-SPEC:BEGIN -->
            ```yaml
            object: formal.truth-boundary-checker.invariants
            schema_version: 1
            kind: invariant-set
            context: truth-boundary-checker
            protected_module_prefixes:
              - agentkit.governance
              - agentkit.pipeline
              - agentkit.qa.structural
            allowed_module_prefixes:
              - agentkit.cli
              - tests
            forbidden_loader_symbols:
              - load_json_object
              - load_json_safe
              - load_verify_decision_artifact
              - load_phase_state
              - load_story_context
            forbidden_import_modules:
              - agentkit.pipeline.state
              - agentkit.qa.artifacts
            forbidden_json_truth_filenames:
              - context.json
              - decision.json
              - verify-decision.json
              - structural.json
              - qa_review.json
              - semantic_review.json
              - semantic-review.json
              - adversarial.json
              - phase-state.json
              - closure.json
            forbidden_json_truth_globs:
              - phase-state-*.json
            invariants:
              - id: truth-boundary-checker.invariant.fs_exports_never_truth
                scope: architecture
                rule: story export files may never become canonical truth
            ```
            <!-- FORMAL-SPEC:END -->
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    module_path = source_root.joinpath(*protected_module.split("."))
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.with_suffix(".py").write_text(
        dedent(source or "def noop():\n    return None\n"),
        encoding="utf-8",
    )
    return root
