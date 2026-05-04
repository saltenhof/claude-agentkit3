"""Unit tests for boundary_modules support (AC009-AC012)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from concept_compiler import (
    audit_architecture_conformance,
    compile_formal_specs,
    load_architecture_conformance_config,
)
from concept_compiler.architecture_conformance import ArchitectureConformanceError

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_BASE_ENTITIES_YAML = """\
object: formal.architecture-conformance.entities
schema_version: 2
kind: entity-set
context: architecture-conformance
bloodgroups:
  - id: architecture-conformance.bloodgroup.a_code
    code: A
    meaning: domain component
  - id: architecture-conformance.bloodgroup.r_code
    code: R
    meaning: adapter
  - id: architecture-conformance.bloodgroup.t_code
    code: T
    meaning: driver
boundary_module_kinds:
  - id: architecture-conformance.boundary_kind.entry_boundary
    code: entry_boundary
    meaning: entry boundary
  - id: architecture-conformance.boundary_kind.adapter_boundary
    code: adapter_boundary
    meaning: adapter boundary
  - id: architecture-conformance.boundary_kind.config_foundation
    code: config_foundation
    meaning: config foundation
  - id: architecture-conformance.boundary_kind.shared_foundation
    code: shared_foundation
    meaning: shared foundation
  - id: architecture-conformance.boundary_kind.infrastructure_driver
    code: infrastructure_driver
    meaning: infrastructure driver
  - id: architecture-conformance.boundary_kind.infrastructure_io
    code: infrastructure_io
    meaning: infrastructure io
component_groups:
  - id: architecture-conformance.group.domain_a
    name: DomainA
    bloodgroup: A
    module_prefixes:
      - agentkit.domain_a
  - id: architecture-conformance.group.domain_b
    name: DomainB
    bloodgroup: A
    module_prefixes:
      - agentkit.domain_b
boundary_modules:
  - id: architecture-conformance.boundary.cli
    name: Cli
    bloodgroup: R
    boundary_kind: entry_boundary
    module_prefixes:
      - agentkit.cli
    importable_by: []
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
  - id: architecture-conformance.boundary.config
    name: Config
    bloodgroup: R
    boundary_kind: config_foundation
    module_prefixes:
      - agentkit.config
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules: []
  - id: architecture-conformance.boundary.shared
    name: Shared
    bloodgroup: A
    boundary_kind: shared_foundation
    module_prefixes:
      - agentkit.shared
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules: []
  - id: architecture-conformance.boundary.driver
    name: Driver
    bloodgroup: T
    boundary_kind: infrastructure_driver
    module_prefixes:
      - agentkit.driver
    importable_by:
      - architecture-conformance.boundary.repo
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
  - id: architecture-conformance.boundary.repo
    name: Repo
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.repo
    importable_by: any
    may_import_component_groups:
      - architecture-conformance.group.domain_a
      - architecture-conformance.group.domain_b
    may_import_boundary_modules:
      - architecture-conformance.boundary.driver
      - architecture-conformance.boundary.shared
"""


def _write_boundary_spec(
    tmp_path: Path,
    *,
    extra_groups: str = "",
    extra_boundary_modules: str = "",
    files: dict[str, str] | None = None,
    module_completeness_check: bool = False,
) -> Path:
    """Write a minimal formal-spec fixture with boundary_modules support.

    Args:
        tmp_path: Base temporary directory.
        extra_groups: Extra component_groups YAML lines (no extra indentation needed).
        extra_boundary_modules: Extra boundary_modules YAML lines appended at end.
        files: Dict mapping module-dotpath -> source code.
        module_completeness_check: Whether to enable the completeness check.

    Returns:
        Root path of the written fixture.
    """
    root = tmp_path / "repo"
    formal_root = root / "concept" / "formal-spec" / "architecture-conformance"
    source_root = root / "src"
    formal_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    completeness_flag = "true" if module_completeness_check else "false"

    entities_yaml = _BASE_ENTITIES_YAML
    if extra_groups:
        entities_yaml = entities_yaml.replace(
            "boundary_modules:",
            extra_groups.rstrip("\n") + "\nboundary_modules:",
        )
    if extra_boundary_modules:
        entities_yaml = entities_yaml.rstrip("\n") + "\n" + extra_boundary_modules

    entities_md = (
        "---\n"
        "id: formal.architecture-conformance.entities\n"
        "title: Architecture Conformance Entities\n"
        "status: active\n"
        "doc_kind: spec\n"
        "context: architecture-conformance\n"
        "spec_kind: entity-set\n"
        "version: 16\n"
        "prose_refs: []\n"
        "---\n"
        "\n"
        "# Test Entities\n"
        "\n"
        "<!-- FORMAL-SPEC:BEGIN -->\n"
        "```yaml\n"
        + entities_yaml
        + "```\n"
        "<!-- FORMAL-SPEC:END -->\n"
    )
    (formal_root / "entities.md").write_text(entities_md, encoding="utf-8")

    invariants_md = (
        "---\n"
        "id: formal.architecture-conformance.invariants\n"
        "title: Architecture Conformance Invariants\n"
        "status: active\n"
        "doc_kind: spec\n"
        "context: architecture-conformance\n"
        "spec_kind: invariant-set\n"
        "version: 1\n"
        "prose_refs: []\n"
        "---\n"
        "\n"
        "# Test Invariants\n"
        "\n"
        "<!-- FORMAL-SPEC:BEGIN -->\n"
        "```yaml\n"
        "object: formal.architecture-conformance.invariants\n"
        "schema_version: 1\n"
        "kind: invariant-set\n"
        "context: architecture-conformance\n"
        "dependency_rules: []\n"
        "acyclic_group_sets: []\n"
        f"module_completeness_check: {completeness_flag}\n"
        "```\n"
        "<!-- FORMAL-SPEC:END -->\n"
    )
    (formal_root / "invariants.md").write_text(invariants_md, encoding="utf-8")

    for item_name, item_source in (files or {}).items():
        module_path = source_root.joinpath(*item_name.split("."))
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.with_suffix(".py").write_text(
            dedent(item_source).strip() + "\n",
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_loader_boundary_modules_loaded(tmp_path: Path) -> None:
    """Boundary-Module werden vollstaendig geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    assert len(config.boundary_modules) == 5
    names = {bm.name for bm in config.boundary_modules}
    assert "Cli" in names
    assert "Config" in names
    assert "Driver" in names


def test_loader_boundary_module_kinds_loaded(tmp_path: Path) -> None:
    """Boundary-Modul-Kategorien werden geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    assert len(config.boundary_module_kinds) == 6
    codes = {k.code for k in config.boundary_module_kinds}
    assert "entry_boundary" in codes
    assert "infrastructure_driver" in codes


def test_loader_boundary_importable_by_any(tmp_path: Path) -> None:
    """importable_by: any wird als Sentinel-Literal geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    config_bm = next(bm for bm in config.boundary_modules if bm.name == "Config")
    assert config_bm.importable_by == "any"


def test_loader_boundary_importable_by_empty(tmp_path: Path) -> None:
    """importable_by: [] wird als leeres Tupel geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    cli_bm = next(bm for bm in config.boundary_modules if bm.name == "Cli")
    assert cli_bm.importable_by == ()


def test_loader_boundary_may_import_component_groups_any(tmp_path: Path) -> None:
    """may_import_component_groups: any wird als Sentinel geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    cli_bm = next(bm for bm in config.boundary_modules if bm.name == "Cli")
    assert cli_bm.may_import_component_groups == "any"


def test_loader_boundary_may_import_component_groups_list(tmp_path: Path) -> None:
    """may_import_component_groups als ID-Liste wird als Tupel geladen."""
    root = _write_boundary_spec(tmp_path)
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    config = load_architecture_conformance_config(compiled)

    repo_bm = next(bm for bm in config.boundary_modules if bm.name == "Repo")
    assert isinstance(repo_bm.may_import_component_groups, tuple)
    assert "architecture-conformance.group.domain_a" in repo_bm.may_import_component_groups


def test_loader_invalid_boundary_kind_rejected(tmp_path: Path) -> None:
    """Ungueltige boundary_kind wird abgelehnt."""
    root = _write_boundary_spec(
        tmp_path,
        extra_boundary_modules=(
            "  - id: architecture-conformance.boundary.bad\n"
            "    name: BadKind\n"
            "    bloodgroup: R\n"
            "    boundary_kind: nonexistent_kind\n"
            "    module_prefixes:\n"
            "      - agentkit.bad\n"
            "    importable_by: any\n"
            "    may_import_component_groups: []\n"
            "    may_import_boundary_modules: []\n"
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="boundary_kind"):
        load_architecture_conformance_config(compiled)


def test_loader_invalid_bloodgroup_rejected(tmp_path: Path) -> None:
    """Ungueltige bloodgroup in boundary_modules wird abgelehnt."""
    root = _write_boundary_spec(
        tmp_path,
        extra_boundary_modules=(
            "  - id: architecture-conformance.boundary.badblood\n"
            "    name: BadBlood\n"
            "    bloodgroup: X\n"
            "    boundary_kind: config_foundation\n"
            "    module_prefixes:\n"
            "      - agentkit.badblood\n"
            "    importable_by: any\n"
            "    may_import_component_groups: []\n"
            "    may_import_boundary_modules: []\n"
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="bloodgroup"):
        load_architecture_conformance_config(compiled)


def test_loader_unknown_importable_by_ref_rejected(tmp_path: Path) -> None:
    """Unbekannte ID in importable_by wird abgelehnt."""
    root = _write_boundary_spec(
        tmp_path,
        extra_boundary_modules=(
            "  - id: architecture-conformance.boundary.badref\n"
            "    name: BadRef\n"
            "    bloodgroup: R\n"
            "    boundary_kind: adapter_boundary\n"
            "    module_prefixes:\n"
            "      - agentkit.badref\n"
            "    importable_by:\n"
            "      - architecture-conformance.group.nonexistent\n"
            "    may_import_component_groups: []\n"
            "    may_import_boundary_modules: []\n"
        ),
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    with pytest.raises(ArchitectureConformanceError, match="importable_by"):
        load_architecture_conformance_config(compiled)


# ---------------------------------------------------------------------------
# AC009 — module_completeness with boundary_modules
# ---------------------------------------------------------------------------


def test_ac009_unassigned_module_reports_violation(tmp_path: Path) -> None:
    """AC009: Ein Modul das weder Komponente noch Boundary-Modul ist wird gemeldet."""
    root = _write_boundary_spec(
        tmp_path,
        files={"agentkit.orphan.service": "def noop(): pass"},
        module_completeness_check=True,
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac009 = [v for v in violations if v.code == "AC009"]
    assert any("agentkit.orphan" in v.module for v in ac009)


def test_ac009_boundary_module_assigned_no_violation(tmp_path: Path) -> None:
    """AC009: Ein Modul das einem Boundary-Modul entspricht erzeugt keine Verletzung."""
    root = _write_boundary_spec(
        tmp_path,
        files={"agentkit.config.loader": "def load(): pass"},
        module_completeness_check=True,
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac009 = [v for v in violations if v.code == "AC009"]
    assert not any("agentkit.config" in v.module for v in ac009)


def test_ac009_component_module_assigned_no_violation(tmp_path: Path) -> None:
    """AC009: Ein Modul das einer Komponenten-Gruppe entspricht erzeugt keine Verletzung."""
    root = _write_boundary_spec(
        tmp_path,
        files={"agentkit.domain_a.service": "def work(): pass"},
        module_completeness_check=True,
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac009 = [v for v in violations if v.code == "AC009"]
    assert not any("agentkit.domain_a" in v.module for v in ac009)


# ---------------------------------------------------------------------------
# AC010 — boundary outbound imports
# ---------------------------------------------------------------------------


def test_ac010_boundary_imports_forbidden_component(tmp_path: Path) -> None:
    """AC010: config-Boundary darf keine fachliche Komponente importieren."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.config.loader": dedent("""
                from agentkit.domain_a import service
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac010 = [v for v in violations if v.code == "AC010"]
    assert ac010, "Expected AC010 violation"
    assert any("domain_a" in v.message for v in ac010)


def test_ac010_boundary_may_import_any_component_allowed(tmp_path: Path) -> None:
    """AC010: cli-Boundary mit may_import_component_groups=any darf beliebige Komponenten importieren."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.cli.main": dedent("""
                from agentkit.domain_a import service
                from agentkit.domain_b import service
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac010 = [v for v in violations if v.code == "AC010" and "agentkit.cli" in v.module]
    assert not ac010, f"Unexpected AC010 violations: {ac010}"


def test_ac010_boundary_imports_forbidden_boundary(tmp_path: Path) -> None:
    """AC010: config-Boundary darf kein Repo-Boundary importieren."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.config.loader": dedent("""
                from agentkit.repo import store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac010 = [v for v in violations if v.code == "AC010"]
    assert ac010, "Expected AC010 violation"
    assert any("repo" in v.message.lower() for v in ac010)


def test_ac010_boundary_allowed_boundary_import_no_violation(tmp_path: Path) -> None:
    """AC010: cli-Boundary darf config-Boundary importieren (laut may_import_boundary_modules)."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.cli.main": dedent("""
                from agentkit.config import loader
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac010 = [
        v
        for v in violations
        if v.code == "AC010" and "agentkit.cli" in v.module
    ]
    assert not ac010, f"Unexpected AC010 violations: {ac010}"


# ---------------------------------------------------------------------------
# AC011 — boundary inbound imports
# ---------------------------------------------------------------------------


def test_ac011_entry_boundary_must_not_be_imported(tmp_path: Path) -> None:
    """AC011: Kein Modul darf ein entry_boundary (importable_by=[]) importieren."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.domain_a.service": dedent("""
                from agentkit.cli import main
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac011 = [v for v in violations if v.code == "AC011"]
    assert ac011, "Expected AC011 violation for import of entry_boundary"
    assert any("agentkit.cli" in v.message for v in ac011)


def test_ac011_any_importable_boundary_no_violation(tmp_path: Path) -> None:
    """AC011: Jeder darf config importieren (importable_by=any)."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.domain_a.service": dedent("""
                from agentkit.config import loader
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac011 = [
        v
        for v in violations
        if v.code == "AC011" and "agentkit.config" in v.message
    ]
    assert not ac011, f"Unexpected AC011 violations: {ac011}"


def test_ac011_restricted_boundary_wrong_importer(tmp_path: Path) -> None:
    """AC011: driver darf nur von repo importiert werden; domain_a darf nicht."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.domain_a.service": dedent("""
                from agentkit.driver import sqlite_store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac011 = [v for v in violations if v.code == "AC011"]
    assert ac011, "Expected AC011 violation"
    assert any("agentkit.driver" in v.message for v in ac011)


def test_ac011_restricted_boundary_correct_importer_no_violation(tmp_path: Path) -> None:
    """AC011: repo darf driver importieren (in importable_by)."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.repo.store": dedent("""
                from agentkit.driver import sqlite_store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac011 = [
        v
        for v in violations
        if v.code == "AC011" and "agentkit.driver" in v.message
    ]
    assert not ac011, f"Unexpected AC011 violations: {ac011}"


# ---------------------------------------------------------------------------
# AC012 — boundary bloodtype check
# ---------------------------------------------------------------------------


def test_ac012_a_component_imports_t_boundary_warning(tmp_path: Path) -> None:
    """AC012: A-Komponente importiert T-Boundary direkt -> Warning (Auffaelligkeit).

    Kein Verbot: AT-Mischung kann an Mediation-Schichten konstitutiv sein
    (siehe concept/methodology/software-blutgruppen.md Abschnitt 4.2).
    Der Linter macht aufmerksam, entscheidet aber nicht.
    """
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.domain_a.service": dedent("""
                from agentkit.driver import sqlite_store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac012 = [v for v in violations if v.code == "AC012"]
    assert ac012, "Expected AC012 finding for A importing T directly"
    assert any("domain_a" in v.module for v in ac012)
    assert all(v.severity == "warning" for v in ac012), (
        "AC012 must be a warning, not an error"
    )


def test_ac012_r_boundary_imports_t_boundary_no_finding(tmp_path: Path) -> None:
    """AC012: R-Boundary-Modul importiert T-Boundary -> kein Befund."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.repo.store": dedent("""
                from agentkit.driver import sqlite_store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac012 = [v for v in violations if v.code == "AC012"]
    assert not ac012, f"Unexpected AC012 findings: {ac012}"


def test_ac012_a_boundary_imports_t_boundary_warning(tmp_path: Path) -> None:
    """AC012: A-Boundary-Modul (shared) importiert T-Boundary direkt -> Warning."""
    root = _write_boundary_spec(
        tmp_path,
        files={
            "agentkit.shared.util": dedent("""
                from agentkit.driver import sqlite_store
            """),
        },
    )
    compiled = compile_formal_specs(root / "concept" / "formal-spec")
    violations = audit_architecture_conformance(compiled, root / "src")

    ac012 = [v for v in violations if v.code == "AC012"]
    assert ac012, "Expected AC012 finding for A-boundary importing T directly"
    assert all(v.severity == "warning" for v in ac012)


# ---------------------------------------------------------------------------
# Real-repo smoke test: boundary_modules aus entities.md laden
# ---------------------------------------------------------------------------


def test_real_entities_md_loads_boundary_modules() -> None:
    """boundary_modules aus dem echten entities.md werden vollstaendig geladen."""
    compiled = compile_formal_specs(Path("concept/formal-spec"))
    config = load_architecture_conformance_config(compiled)

    assert len(config.boundary_modules) == 15, (
        f"Expected 15 boundary_modules, got {len(config.boundary_modules)}: "
        f"{[bm.boundary_id for bm in config.boundary_modules]}"
    )
    assert len(config.boundary_module_kinds) == 6, (
        f"Expected 6 boundary_module_kinds, got {len(config.boundary_module_kinds)}"
    )


def test_real_repo_audit_does_not_crash() -> None:
    """audit_architecture_conformance laeuft ohne Absturz auf dem echten src/."""
    compiled = compile_formal_specs(Path("concept/formal-spec"))
    # Must not raise — violations are expected, but the tool must count them.
    violations = audit_architecture_conformance(compiled, Path("src"))
    assert isinstance(violations, tuple)
