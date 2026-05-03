"""Deterministic architecture-conformance checks driven by formal specs."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from agentkit.exceptions import AgentKitError

if TYPE_CHECKING:
    from pathlib import Path

    from .compiler import CompiledFormalSpec

ENTITIES_DOC_ID = "formal.architecture-conformance.entities"
INVARIANTS_DOC_ID = "formal.architecture-conformance.invariants"

_VALID_BLOODGROUPS = frozenset({"A", "R", "T"})
_VALID_EXPOSURE = frozenset({"top", "sub_exposed", "internal"})
_VALID_COMPONENT_KINDS = frozenset({"domain", "shared"})

_VALID_EFFECT_SURFACE_NAMES = frozenset(
    {
        "persistence",
        "filesystem",
        "network",
        "subprocess",
        "queue",
        "time_randomness",
        "global_state",
        "async_runtime",
        "serialization_boundary",
        "cache",
        "framework_runtime",
    }
)


class ArchitectureConformanceError(AgentKitError):
    """Raised when architecture-conformance specs or checks fail."""


@dataclass(frozen=True)
class ComponentGroup:
    """Eine benannte Komponenten-Gruppe fuer Abhaengigkeitspruefungen.

    Args:
        group_id: Stabiler eindeutiger Bezeichner.
        name: Lesbarer Name der Komponente.
        bloodgroup: Klassifizierungscode A, R oder T.
        module_prefixes: Python-Modul-Prefixe die zu dieser Gruppe gehoeren.
        parent_group_id: Optionaler Bezeichner der uebergeordneten Gruppe.
        exposure: Sichtbarkeit der Gruppe (top / sub_exposed / internal).
        top_surface_modules: Oeffentliche Schnittstellen-Module der Gruppe.
        component_kind: Fachliche Klassifizierung domain oder shared.
        owner_group_id: Besitzende Gruppe (nur bei component_kind=shared).
        allowed_importers: Erlaubte importierende Gruppen (nur bei shared).
        exported_symbols: Exportierte vollqualifizierte Namen (nur bei shared).
        allowed_imported_symbols: Erlaubte importierte Symbole (nur bei shared).
        intra_bc_layer_order: Geordnete Liste von Sub-Gruppen-IDs fuer
            intra-BC-Schichtreihenfolge-Pruefung.
    """

    group_id: str
    name: str
    bloodgroup: str
    module_prefixes: tuple[str, ...]
    parent_group_id: str | None = None
    exposure: str = "top"
    top_surface_modules: tuple[str, ...] = field(default_factory=tuple)
    component_kind: str = "domain"
    owner_group_id: str | None = None
    allowed_importers: tuple[str, ...] = field(default_factory=tuple)
    exported_symbols: tuple[str, ...] = field(default_factory=tuple)
    allowed_imported_symbols: tuple[str, ...] = field(default_factory=tuple)
    intra_bc_layer_order: tuple[str, ...] = field(default_factory=tuple)

    def is_top(self) -> bool:
        """Gibt True zurueck wenn die Gruppe eine Top-Level-Gruppe ist."""
        return self.parent_group_id is None

    def is_shared(self) -> bool:
        """Gibt True zurueck wenn es sich um eine Shared-Komponente handelt."""
        return self.component_kind == "shared"

    def chain_to_top(
        self,
        lookup: dict[str, ComponentGroup],
    ) -> list[ComponentGroup]:
        """Gibt die Kette von dieser Gruppe bis zur Wurzel zurueck.

        Args:
            lookup: Mapping von group_id zu ComponentGroup.

        Returns:
            Liste beginnend mit dieser Gruppe bis zur obersten Elterngruppe.
        """
        chain: list[ComponentGroup] = [self]
        current = self
        while current.parent_group_id is not None:
            parent = lookup.get(current.parent_group_id)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return chain


@dataclass(frozen=True)
class DependencyRule:
    """Eine verbotene Import-Richtung."""

    rule_id: str
    source_module_prefixes: tuple[str, ...]
    forbidden_module_prefixes: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class AcyclicGroupSet:
    """Eine Gruppen-Teilmenge die azyklisch bleiben muss."""

    set_id: str
    group_ids: tuple[str, ...]


@dataclass(frozen=True)
class MutationSurfaceRule:
    """Eine begrenzte Schreibflaechen-Regel ueber importierte Writer-Symbole."""

    rule_id: str
    writer_symbols: tuple[str, ...]
    allowed_module_prefixes: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ReadSurfaceRule:
    """Eine begrenzte Leseflaechen-Regel ueber importierte Reader-Symbole."""

    rule_id: str
    reader_symbols: tuple[str, ...]
    allowed_module_prefixes: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class BloodtypeDependencyRule:
    """AC005 — Blutgruppen-basierte Abhaengigkeitsregel auf Komponentenebene.

    Args:
        rule_id: Stabiler eindeutiger Bezeichner.
        source_bloodgroup: Blutgruppe der Quellkomponente.
        forbidden_target_bloodgroups: Verbotene Blutgruppen als Ziel.
        allow_through_bloodgroup: Optionale Durchgangs-Blutgruppe (Anti-Laundering).
        message: Fehlermeldung bei Verletzung.
    """

    rule_id: str
    source_bloodgroup: str
    forbidden_target_bloodgroups: tuple[str, ...]
    allow_through_bloodgroup: str | None
    message: str


@dataclass(frozen=True)
class EffectSurface:
    """AC006 — Symbol-basierte Effektflaechen-Regel.

    Args:
        surface_id: Stabiler eindeutiger Bezeichner.
        name: Kategoriename der Effektflaeche.
        forbidden_for_bloodgroups: Blutgruppen fuer die diese Effekte verboten sind.
        symbols: Vollqualifizierte Symbole die diese Effektflaeche ausloesen.
        message: Fehlermeldung bei Verletzung.
    """

    surface_id: str
    name: str
    forbidden_for_bloodgroups: tuple[str, ...]
    symbols: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class TypeTaintRule:
    """AC007 — AST-basierte Typen-Tainting-Regel fuer oeffentliche Signaturen.

    Args:
        rule_id: Stabiler eindeutiger Bezeichner.
        source_bloodgroup: Blutgruppe der zu pruefenden Module.
        forbidden_typed_bloodgroups: Blutgruppen die nicht in Signaturen
            erscheinen duerfen.
        forbid_instantiation_of_bloodgroups: Blutgruppen deren Klassen nicht
            instanziiert werden duerfen.
        message: Fehlermeldung bei Verletzung.
    """

    rule_id: str
    source_bloodgroup: str
    forbidden_typed_bloodgroups: tuple[str, ...]
    forbid_instantiation_of_bloodgroups: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class BoundaryModuleKind:
    """Vokabular-Eintrag fuer Boundary-Module-Kategorien.

    Args:
        code: Eindeutiger Kategorien-Code.
        meaning: Beschreibung der Kategorie.
    """

    code: str
    meaning: str


# Sentinel-Typ fuer importable_by / may_import_component_groups.
# "any" bedeutet: alle Aufrufer erlaubt.
_AnyOrIds = Literal["any"] | tuple[str, ...]


@dataclass(frozen=True)
class BoundaryModule:
    """Ein nicht-fachliches Boundary-Modul (CLI, Config, Adapter, Driver, etc.).

    Args:
        boundary_id: Stabiler eindeutiger Bezeichner.
        name: Lesbarer Name des Boundary-Moduls.
        bloodgroup: Bluttyp-Klassifizierungscode A, R oder T.
        boundary_kind: Kategorie-Code aus boundary_module_kinds.
        module_prefixes: Python-Modul-Prefixe die zu diesem Boundary-Modul gehoeren.
        importable_by: "any" oder Tupel von Gruppen-/Boundary-IDs die
            dieses Modul importieren duerfen. Leeres Tupel = niemand darf importieren.
        may_import_component_groups: "any" oder Tupel von Komponenten-Gruppen-IDs
            die dieses Boundary-Modul importieren darf.
        may_import_boundary_modules: Tupel von Boundary-Modul-IDs die
            dieses Modul importieren darf.
    """

    boundary_id: str
    name: str
    bloodgroup: str
    boundary_kind: str
    module_prefixes: tuple[str, ...]
    importable_by: _AnyOrIds
    may_import_component_groups: _AnyOrIds
    may_import_boundary_modules: tuple[str, ...]


@dataclass(frozen=True)
class ArchitectureConformanceConfig:
    """Normalisierte Architektur-Pruef-Konfiguration.

    Args:
        component_groups: Alle bekannten Komponenten-Gruppen.
        dependency_rules: Verbotene Import-Richtungen (AC001).
        acyclic_group_sets: Azyklizitaets-Regeln (AC002).
        mutation_surface_rules: Schreibflaechen-Regeln (AC003).
        read_surface_rules: Leseflaechen-Regeln (AC004).
        bloodtype_dependency_rules: Blutgruppen-Abhaengigkeitsregeln (AC005).
        effect_surfaces: Effektflaechen-Regeln (AC006).
        type_taint_rules: Typen-Taint-Regeln (AC007).
        module_completeness_check_enabled: Wenn True wird AC008/AC009
            (Modul-Vollstaendigkeitspruefung) durchgefuehrt.
            Standard: False (sicherer Default fuer bestehende Specs).
        boundary_modules: Alle bekannten Boundary-Module (AC009-AC012).
        boundary_module_kinds: Vokabular der Boundary-Modul-Kategorien.
    """

    component_groups: tuple[ComponentGroup, ...]
    dependency_rules: tuple[DependencyRule, ...]
    acyclic_group_sets: tuple[AcyclicGroupSet, ...]
    mutation_surface_rules: tuple[MutationSurfaceRule, ...]
    read_surface_rules: tuple[ReadSurfaceRule, ...]
    bloodtype_dependency_rules: tuple[BloodtypeDependencyRule, ...]
    effect_surfaces: tuple[EffectSurface, ...]
    type_taint_rules: tuple[TypeTaintRule, ...]
    module_completeness_check_enabled: bool = False
    boundary_modules: tuple[BoundaryModule, ...] = field(default_factory=tuple)
    boundary_module_kinds: tuple[BoundaryModuleKind, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ArchitectureViolation:
    """Eine deterministische Architektur-Grenzverletzung im Code."""

    code: str
    path: Path | None
    module: str
    line: int
    column: int
    message: str
    rule_id: str


def load_architecture_conformance_config(
    compiled: CompiledFormalSpec,
) -> ArchitectureConformanceConfig:
    """Laedt die Architektur-Konformanz-Konfiguration aus kompilierten Specs.

    Args:
        compiled: Kompilierte Formalspezifikation.

    Returns:
        Normalisierte Architektur-Konformanz-Konfiguration.

    Raises:
        ArchitectureConformanceError: Wenn die Spezifikation ungueltig ist.
    """
    entities = _require_document(compiled, ENTITIES_DOC_ID)
    invariants = _require_document(compiled, INVARIANTS_DOC_ID)

    raw_groups = _require_mapping_list(entities.spec, "component_groups", entities.path)
    component_groups = tuple(
        _load_component_group(entry, entities.path) for entry in raw_groups
    )
    _validate_component_group_hierarchy(component_groups, entities.path)

    raw_kinds = _optional_mapping_list(
        entities.spec, "boundary_module_kinds", entities.path
    )
    boundary_module_kinds = tuple(
        _load_boundary_module_kind(entry, entities.path) for entry in raw_kinds
    )
    known_kind_codes = frozenset(k.code for k in boundary_module_kinds)

    raw_boundary = _optional_mapping_list(
        entities.spec, "boundary_modules", entities.path
    )
    # Load in two passes: first parse all entries to collect IDs, then validate refs.
    boundary_modules_unvalidated = tuple(
        _load_boundary_module_raw(entry, entities.path, known_kind_codes)
        for entry in raw_boundary
    )
    known_group_ids = frozenset(g.group_id for g in component_groups)
    known_boundary_ids = frozenset(b.boundary_id for b in boundary_modules_unvalidated)
    _validate_boundary_module_refs(
        boundary_modules_unvalidated,
        known_group_ids,
        known_boundary_ids,
        entities.path,
    )
    boundary_modules = boundary_modules_unvalidated

    dependency_rules = tuple(
        DependencyRule(
            rule_id=_require_string(entry, "id", invariants.path),
            source_module_prefixes=_require_string_tuple(
                entry,
                "source_module_prefixes",
                invariants.path,
            ),
            forbidden_module_prefixes=_require_string_tuple(
                entry,
                "forbidden_module_prefixes",
                invariants.path,
            ),
            message=_require_string(entry, "message", invariants.path),
        )
        for entry in _require_mapping_list(
            invariants.spec,
            "dependency_rules",
            invariants.path,
        )
    )

    known_group_ids_set: set[str] = {group.group_id for group in component_groups}
    acyclic_group_sets = tuple(
        _load_acyclic_group_set(entry, invariants.path, known_group_ids_set)
        for entry in _require_mapping_list(
            invariants.spec,
            "acyclic_group_sets",
            invariants.path,
        )
    )
    mutation_surface_rules = tuple(
        MutationSurfaceRule(
            rule_id=_require_string(entry, "id", invariants.path),
            writer_symbols=_require_string_tuple(
                entry,
                "writer_symbols",
                invariants.path,
            ),
            allowed_module_prefixes=_require_string_tuple(
                entry,
                "allowed_module_prefixes",
                invariants.path,
            ),
            message=_require_string(entry, "message", invariants.path),
        )
        for entry in _optional_mapping_list(
            invariants.spec,
            "mutation_surface_rules",
            invariants.path,
        )
    )
    read_surface_rules = tuple(
        ReadSurfaceRule(
            rule_id=_require_string(entry, "id", invariants.path),
            reader_symbols=_require_string_tuple(
                entry,
                "reader_symbols",
                invariants.path,
            ),
            allowed_module_prefixes=_require_string_tuple(
                entry,
                "allowed_module_prefixes",
                invariants.path,
            ),
            message=_require_string(entry, "message", invariants.path),
        )
        for entry in _optional_mapping_list(
            invariants.spec,
            "read_surface_rules",
            invariants.path,
        )
    )

    bloodtype_dependency_rules = tuple(
        _load_bloodtype_dependency_rule(entry, invariants.path)
        for entry in _optional_mapping_list(
            invariants.spec,
            "bloodtype_dependency_rules",
            invariants.path,
        )
    )
    effect_surfaces = tuple(
        _load_effect_surface(entry, invariants.path)
        for entry in _optional_mapping_list(
            invariants.spec,
            "effect_surfaces",
            invariants.path,
        )
    )
    type_taint_rules = tuple(
        _load_type_taint_rule(entry, invariants.path)
        for entry in _optional_mapping_list(
            invariants.spec,
            "type_taint_rules",
            invariants.path,
        )
    )

    # module_completeness_check defaults to False so existing specs are unaffected.
    # Opt-in by setting module_completeness_check: true in the invariants spec.
    module_completeness_check_enabled = bool(
        invariants.spec.get("module_completeness_check", False)
    )

    return ArchitectureConformanceConfig(
        component_groups=component_groups,
        dependency_rules=dependency_rules,
        acyclic_group_sets=acyclic_group_sets,
        mutation_surface_rules=mutation_surface_rules,
        read_surface_rules=read_surface_rules,
        bloodtype_dependency_rules=bloodtype_dependency_rules,
        effect_surfaces=effect_surfaces,
        type_taint_rules=type_taint_rules,
        module_completeness_check_enabled=module_completeness_check_enabled,
        boundary_modules=boundary_modules,
        boundary_module_kinds=boundary_module_kinds,
    )


def audit_architecture_conformance(
    compiled: CompiledFormalSpec,
    code_root: Path,
) -> tuple[ArchitectureViolation, ...]:
    """Scannt Python-Code auf formale Architekturgrenz-Verletzungen.

    Args:
        compiled: Kompilierte Formalspezifikation.
        code_root: Wurzelverzeichnis des Python-Quellcodes.

    Returns:
        Geordnetes Tupel aller gefundenen Verletzungen.
    """
    config = load_architecture_conformance_config(compiled)
    import_graph = _build_import_graph(code_root)

    violations: list[ArchitectureViolation] = []
    violations.extend(_check_dependency_rules(import_graph, config.dependency_rules))
    violations.extend(_check_acyclic_sets(import_graph, config))
    violations.extend(
        _check_mutation_surface_rules(import_graph, config.mutation_surface_rules)
    )
    violations.extend(
        _check_read_surface_rules(import_graph, config.read_surface_rules)
    )
    if config.module_completeness_check_enabled:
        violations.extend(
            _check_module_completeness(
                import_graph, config.component_groups, config.boundary_modules
            )
        )
    violations.extend(_check_target_exposure(import_graph, config.component_groups))
    if config.boundary_modules:
        violations.extend(
            _check_boundary_outbound_imports(
                import_graph, config.component_groups, config.boundary_modules
            )
        )
        violations.extend(
            _check_boundary_inbound_imports(
                import_graph, config.component_groups, config.boundary_modules
            )
        )
        violations.extend(
            _check_boundary_bloodtype_rules(
                import_graph, config.component_groups, config.boundary_modules
            )
        )
    violations.extend(
        _check_intra_bc_layer_order(import_graph, config.component_groups)
    )
    violations.extend(
        _check_bloodtype_dependency_rules(
            import_graph, config.component_groups, config.bloodtype_dependency_rules
        )
    )
    violations.extend(
        _check_effect_surfaces(
            import_graph, config.component_groups, config.effect_surfaces
        )
    )
    violations.extend(
        _check_type_taint_rules(
            import_graph, config.component_groups, config.type_taint_rules
        )
    )

    return tuple(
        sorted(
            violations,
            key=lambda item: (
                "" if item.path is None else str(item.path),
                item.module,
                item.line,
                item.column,
                item.code,
            ),
        )
    )


def raise_on_architecture_violations(
    violations: tuple[ArchitectureViolation, ...],
) -> None:
    """Wirft einen aggregierten Fehler wenn Architektur-Verletzungen vorliegen.

    Args:
        violations: Gefundene Verletzungen.

    Raises:
        ArchitectureConformanceError: Wenn mindestens eine Verletzung vorliegt.
    """
    if not violations:
        return

    formatted = "; ".join(
        (
            f"{violation.code} {violation.module}:{violation.line}:"
            f"{violation.column} {violation.message}"
        )
        for violation in violations
    )
    raise ArchitectureConformanceError(
        f"Architecture-conformance violations detected: {formatted}",
        detail={
            "violations": [
                {
                    "code": violation.code,
                    "path": None if violation.path is None else str(violation.path),
                    "module": violation.module,
                    "line": violation.line,
                    "column": violation.column,
                    "message": violation.message,
                    "rule_id": violation.rule_id,
                }
                for violation in violations
            ]
        },
    )


def render_component_tree(config: ArchitectureConformanceConfig) -> str:
    """Rendert eine textuelle Baumdarstellung der Komponenten-Gruppen.

    Args:
        config: Normalisierte Architektur-Konformanz-Konfiguration.

    Returns:
        Mehrzeiliger String mit der Baumdarstellung.
    """
    children: dict[str | None, list[ComponentGroup]] = {}
    for group in config.component_groups:
        parent_key = group.parent_group_id
        children.setdefault(parent_key, []).append(group)
    for group_list in children.values():
        group_list.sort(key=lambda g: g.name)

    lines: list[str] = []

    def _render(group: ComponentGroup, prefix: str, is_last: bool) -> None:
        connector = "└─" if is_last else "├─"
        lines.append(
            f"{prefix}{connector} {group.name} [{group.bloodgroup}, {group.exposure}]"
        )
        child_list = children.get(group.group_id, [])
        child_prefix = prefix + ("   " if is_last else "│  ")
        for idx, child in enumerate(child_list):
            _render(child, child_prefix, idx == len(child_list) - 1)

    top_groups = sorted(
        [g for g in config.component_groups if g.parent_group_id is None],
        key=lambda g: g.name,
    )
    for idx, top_group in enumerate(top_groups):
        is_last_top = idx == len(top_groups) - 1
        connector = "└─" if is_last_top else "├─"
        lines.append(
            f"{connector} {top_group.name} "
            f"[{top_group.bloodgroup}, {top_group.exposure}]"
        )
        child_list = children.get(top_group.group_id, [])
        child_prefix = "   " if is_last_top else "│  "
        for cidx, child in enumerate(child_list):
            _render(child, child_prefix, cidx == len(child_list) - 1)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal check implementations
# ---------------------------------------------------------------------------


def _check_dependency_rules(
    import_graph: dict[str, _ModuleImports],
    rules: tuple[DependencyRule, ...],
) -> list[ArchitectureViolation]:
    violations: list[ArchitectureViolation] = []
    for module, record in import_graph.items():
        for rule in rules:
            if not _matches_prefix(module, rule.source_module_prefixes):
                continue
            for imported_module, line, column in record.imports:
                if _matches_prefix(imported_module, rule.forbidden_module_prefixes):
                    violations.append(
                        ArchitectureViolation(
                            code="AC001",
                            path=record.path,
                            module=module,
                            line=line,
                            column=column,
                            message=(f"{rule.message}: imports '{imported_module}'"),
                            rule_id=rule.rule_id,
                        )
                    )
    return violations


def _check_mutation_surface_rules(
    import_graph: dict[str, _ModuleImports],
    rules: tuple[MutationSurfaceRule, ...],
) -> list[ArchitectureViolation]:
    violations: list[ArchitectureViolation] = []
    for module, record in import_graph.items():
        for imported_module, line, column in record.imports:
            symbol_name = imported_module.rsplit(".", maxsplit=1)[-1]
            for rule in rules:
                if symbol_name not in rule.writer_symbols:
                    continue
                if _matches_prefix(module, rule.allowed_module_prefixes):
                    continue
                violations.append(
                    ArchitectureViolation(
                        code="AC003",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=f"{rule.message}: imports '{imported_module}'",
                        rule_id=rule.rule_id,
                    )
                )
    return violations


def _check_read_surface_rules(
    import_graph: dict[str, _ModuleImports],
    rules: tuple[ReadSurfaceRule, ...],
) -> list[ArchitectureViolation]:
    violations: list[ArchitectureViolation] = []
    for module, record in import_graph.items():
        for imported_module, line, column in record.imports:
            symbol_name = imported_module.rsplit(".", maxsplit=1)[-1]
            for rule in rules:
                if symbol_name not in rule.reader_symbols:
                    continue
                if _matches_prefix(module, rule.allowed_module_prefixes):
                    continue
                violations.append(
                    ArchitectureViolation(
                        code="AC004",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=f"{rule.message}: imports '{imported_module}'",
                        rule_id=rule.rule_id,
                    )
                )
    return violations


def _check_acyclic_sets(
    import_graph: dict[str, _ModuleImports],
    config: ArchitectureConformanceConfig,
) -> list[ArchitectureViolation]:
    group_lookup = _group_lookup(config.component_groups)
    group_edges = _group_edges(import_graph, config.component_groups)
    violations: list[ArchitectureViolation] = []
    for group_set in config.acyclic_group_sets:
        cycle = _find_group_cycle(group_edges, group_set.group_ids)
        if cycle is None:
            continue
        labels = [group_lookup[group_id].name for group_id in cycle]
        violations.append(
            ArchitectureViolation(
                code="AC002",
                path=None,
                module=cycle[0],
                line=1,
                column=1,
                message=(
                    "component cycle detected across stable groups: "
                    + " -> ".join(labels)
                ),
                rule_id=group_set.set_id,
            )
        )
    return violations


def _check_module_completeness(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    boundary_modules: tuple[BoundaryModule, ...] = (),
) -> list[ArchitectureViolation]:
    """AC008/AC009 — Jedes agentkit.*-Modul muss einer Komponenten-Gruppe
    oder einem Boundary-Modul zugeordnet sein.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        boundary_modules: Bekannte Boundary-Module (optional).

    Returns:
        Liste der Verletzungen fuer nicht zugeordnete Module.
    """
    violations: list[ArchitectureViolation] = []
    for module, record in import_graph.items():
        if not (module == "agentkit" or module.startswith("agentkit.")):
            continue
        matched_group = _group_for_module(module, component_groups)
        if matched_group is not None:
            continue
        matched_boundary = _boundary_for_module(module, boundary_modules)
        if matched_boundary is not None:
            continue
        code = "AC009" if boundary_modules else "AC008"
        violations.append(
            ArchitectureViolation(
                code=code,
                path=record.path,
                module=module,
                line=1,
                column=1,
                message="module is not assigned to any component or boundary-module",
                rule_id="architecture-conformance.check.module_completeness",
            )
        )
    return violations


def _check_boundary_outbound_imports(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    boundary_modules: tuple[BoundaryModule, ...],
) -> list[ArchitectureViolation]:
    """AC010 — Outbound-Imports aus Boundary-Modulen respektieren may_import_*.

    Jeder Import aus einem Modul innerhalb eines Boundary-Moduls darf nur
    auf erlaubte Ziele zeigen:
    - eigene module_prefixes des Boundary-Moduls
    - component_groups laut may_import_component_groups
    - boundary_modules laut may_import_boundary_modules
    - alles, was zu keiner bekannten Komponente oder keinem Boundary-Modul gehoert
      (stdlib / third-party)

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        boundary_modules: Bekannte Boundary-Module.

    Returns:
        Liste der AC010-Verletzungen.
    """
    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_boundary = _boundary_for_module(module, boundary_modules)
        if source_boundary is None:
            continue

        for imported_module, line, column in record.imports:
            # Allow: imports within the same boundary-module's own prefixes.
            if _matches_prefix(imported_module, source_boundary.module_prefixes):
                continue

            target_group = _group_for_module(imported_module, component_groups)
            target_boundary = _boundary_for_module(imported_module, boundary_modules)

            # If imported module is unknown (stdlib / third-party), allow it.
            if target_group is None and target_boundary is None:
                continue

            if target_group is not None:
                # Check may_import_component_groups.
                if source_boundary.may_import_component_groups == "any":
                    continue
                if target_group.group_id in source_boundary.may_import_component_groups:
                    continue
                # Also allow if parent group is explicitly listed.
                if target_group.parent_group_id in source_boundary.may_import_component_groups:
                    continue
                violations.append(
                    ArchitectureViolation(
                        code="AC010",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"boundary-module '{source_boundary.name}' imports"
                            f" component '{target_group.name}'"
                            f" which is not in may_import_component_groups:"
                            f" imports '{imported_module}'"
                        ),
                        rule_id=(
                            f"architecture-conformance.check"
                            f".boundary_outbound.{source_boundary.boundary_id}"
                        ),
                    )
                )
            elif target_boundary is not None:
                if target_boundary.boundary_id in source_boundary.may_import_boundary_modules:
                    continue
                violations.append(
                    ArchitectureViolation(
                        code="AC010",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"boundary-module '{source_boundary.name}' imports"
                            f" boundary-module '{target_boundary.name}'"
                            f" which is not in may_import_boundary_modules:"
                            f" imports '{imported_module}'"
                        ),
                        rule_id=(
                            f"architecture-conformance.check"
                            f".boundary_outbound.{source_boundary.boundary_id}"
                        ),
                    )
                )

    return violations


def _check_boundary_inbound_imports(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    boundary_modules: tuple[BoundaryModule, ...],
) -> list[ArchitectureViolation]:
    """AC011 — Inbound-Imports auf Boundary-Module respektieren importable_by.

    Wenn importable_by == [] darf niemand das Boundary-Modul importieren.
    Wenn importable_by == "any" darf jeder importieren.
    Sonst muss der Aufrufer in der importable_by-Liste stehen (Gruppen-ID
    oder Boundary-Modul-ID).

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        boundary_modules: Bekannte Boundary-Module.

    Returns:
        Liste der AC011-Verletzungen.
    """
    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        source_boundary = _boundary_for_module(module, boundary_modules)

        for imported_module, line, column in record.imports:
            target_boundary = _boundary_for_module(imported_module, boundary_modules)
            if target_boundary is None:
                continue
            # Importing from within the same boundary-module is always allowed.
            if source_boundary is not None and (
                source_boundary.boundary_id == target_boundary.boundary_id
            ):
                continue

            importable_by = target_boundary.importable_by
            if importable_by == "any":
                continue

            if not importable_by:
                # Nobody may import this boundary-module.
                violations.append(
                    ArchitectureViolation(
                        code="AC011",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"boundary-module '{target_boundary.name}'"
                            f" (importable_by=[]) must not be imported"
                            f" by any module, but '{module}' imports"
                            f" '{imported_module}'"
                        ),
                        rule_id=(
                            f"architecture-conformance.check"
                            f".boundary_inbound.{target_boundary.boundary_id}"
                        ),
                    )
                )
                continue

            # importable_by is a non-empty tuple of IDs.
            caller_ids: set[str] = set()
            if source_group is not None:
                caller_ids.add(source_group.group_id)
                if source_group.parent_group_id:
                    caller_ids.add(source_group.parent_group_id)
            if source_boundary is not None:
                caller_ids.add(source_boundary.boundary_id)

            allowed_ids = frozenset(importable_by)
            if not caller_ids.intersection(allowed_ids):
                violations.append(
                    ArchitectureViolation(
                        code="AC011",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"boundary-module '{target_boundary.name}'"
                            f" is not importable by '{module}';"
                            f" allowed importers: {sorted(importable_by)}:"
                            f" imports '{imported_module}'"
                        ),
                        rule_id=(
                            f"architecture-conformance.check"
                            f".boundary_inbound.{target_boundary.boundary_id}"
                        ),
                    )
                )

    return violations


def _check_boundary_bloodtype_rules(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    boundary_modules: tuple[BoundaryModule, ...],
) -> list[ArchitectureViolation]:
    """AC012 — Bluttyp-Import-Regeln fuer Boundary-Module.

    A-Komponenten und A-Boundary-Module duerfen T-Boundary-Module
    nicht direkt importieren. Sie muessen ueber R-Boundary-Module gehen.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        boundary_modules: Bekannte Boundary-Module.

    Returns:
        Liste der AC012-Verletzungen.
    """
    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        source_boundary = _boundary_for_module(module, boundary_modules)

        src_bg: str | None = None
        if source_group is not None:
            src_bg = source_group.bloodgroup
        elif source_boundary is not None:
            src_bg = source_boundary.bloodgroup

        if src_bg != "A":
            continue

        for imported_module, line, column in record.imports:
            target_boundary = _boundary_for_module(imported_module, boundary_modules)
            if target_boundary is None:
                continue
            if target_boundary.bloodgroup != "T":
                continue

            violations.append(
                ArchitectureViolation(
                    code="AC012",
                    path=record.path,
                    module=module,
                    line=line,
                    column=column,
                    message=(
                        f"A-type module '{module}' directly imports"
                        f" T-type boundary-module '{target_boundary.name}';"
                        f" A must go through an R-type boundary-module:"
                        f" imports '{imported_module}'"
                    ),
                    rule_id=(
                        f"architecture-conformance.check"
                        f".boundary_bloodtype.{target_boundary.boundary_id}"
                    ),
                )
            )

    return violations


def _check_target_exposure(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
) -> list[ArchitectureViolation]:
    """AC001-target-not-exposed — Cross-BC-Imports nur auf sub_exposed-Subkomponenten.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.

    Returns:
        Liste der Verletzungen fuer Imports auf nicht-exponierte Subkomponenten.
    """
    lookup = _group_lookup(component_groups)
    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        if source_group is None:
            continue
        source_top = _top_level_group(source_group, lookup)

        for imported_module, line, column in record.imports:
            target_group = _group_for_module(imported_module, component_groups)
            if target_group is None:
                continue
            target_top = _top_level_group(target_group, lookup)

            # Only check cross-BC imports
            if source_top.group_id == target_top.group_id:
                continue

            # Target is a subkomponente (not top-level)
            if target_group.group_id == target_top.group_id:
                continue

            # Subkomponente must be sub_exposed for cross-BC access
            if target_group.exposure != "sub_exposed":
                violations.append(
                    ArchitectureViolation(
                        code="AC001",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"cross-BC import targets non-exposed subcomponent"
                            f" '{target_group.name}'"
                            f" (exposure={target_group.exposure}):"
                            f" imports '{imported_module}'"
                        ),
                        rule_id=("architecture-conformance.check.target_not_exposed"),
                    )
                )
    return violations


def _check_intra_bc_layer_order(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
) -> list[ArchitectureViolation]:
    """AC002-intra-bc-layer — Prueft intra-BC Schichtreihenfolge.

    Pruefung nur wenn intra_bc_layer_order gesetzt ist.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.

    Returns:
        Liste der Verletzungen fuer ungeordnete intra-BC-Schichtimports.
    """
    lookup = _group_lookup(component_groups)
    violations: list[ArchitectureViolation] = []

    for top_group in component_groups:
        if not top_group.intra_bc_layer_order:
            continue

        layer_order = top_group.intra_bc_layer_order
        layer_index: dict[str, int] = {gid: idx for idx, gid in enumerate(layer_order)}

        for module, record in import_graph.items():
            source_group = _group_for_module(module, component_groups)
            if source_group is None:
                continue
            # Only modules belonging to this BC
            source_top = _top_level_group(source_group, lookup)
            if source_top.group_id != top_group.group_id:
                continue
            src_layer_idx = layer_index.get(source_group.group_id)
            if src_layer_idx is None:
                continue

            for imported_module, line, column in record.imports:
                target_group = _group_for_module(imported_module, component_groups)
                if target_group is None:
                    continue
                target_top = _top_level_group(target_group, lookup)
                if target_top.group_id != top_group.group_id:
                    continue
                tgt_layer_idx = layer_index.get(target_group.group_id)
                if tgt_layer_idx is None:
                    continue

                if tgt_layer_idx > src_layer_idx:
                    violations.append(
                        ArchitectureViolation(
                            code="AC002",
                            path=record.path,
                            module=module,
                            line=line,
                            column=column,
                            message=(
                                f"intra-BC layer violation in '{top_group.name}':"
                                f" '{source_group.name}' (layer {src_layer_idx})"
                                f" imports from '{target_group.name}'"
                                f" (layer {tgt_layer_idx}):"
                                f" imports '{imported_module}'"
                            ),
                            rule_id=(
                                f"architecture-conformance.check"
                                f".intra_bc_layer_order.{top_group.group_id}"
                            ),
                        )
                    )
    return violations


def _check_bloodtype_dependency_rules(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    rules: tuple[BloodtypeDependencyRule, ...],
) -> list[ArchitectureViolation]:
    """AC005 — Blutgruppen-basierte Abhaengigkeits-Pruefung.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        rules: Blutgruppen-Abhaengigkeitsregeln.

    Returns:
        Liste der AC005-Verletzungen.
    """
    if not rules:
        return []

    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        if source_group is None:
            continue
        src_bg = source_group.bloodgroup

        for imported_module, line, column in record.imports:
            target_group = _group_for_module(imported_module, component_groups)
            if target_group is None:
                continue
            tgt_bg = target_group.bloodgroup

            for rule in rules:
                if rule.source_bloodgroup != src_bg:
                    continue

                if tgt_bg in rule.forbidden_target_bloodgroups:
                    # Direct forbidden import
                    violations.append(
                        ArchitectureViolation(
                            code="AC005",
                            path=record.path,
                            module=module,
                            line=line,
                            column=column,
                            message=(
                                f"{rule.message}: '{module}' [{src_bg}] imports "
                                f"'{imported_module}' [{tgt_bg}]"
                            ),
                            rule_id=rule.rule_id,
                        )
                    )
                elif (
                    rule.allow_through_bloodgroup is not None
                    and tgt_bg == rule.allow_through_bloodgroup
                    # Anti-laundering: pass-through allowed only if target group does
                    # not re-export a forbidden bloodgroup symbol.
                    and _group_re_exports_forbidden_bloodgroup(
                        target_group,
                        rule.forbidden_target_bloodgroups,
                        component_groups,
                    )
                ):
                    violations.append(
                        ArchitectureViolation(
                            code="AC005",
                            path=record.path,
                            module=module,
                            line=line,
                            column=column,
                            message=(
                                f"{rule.message} (anti-laundering): "
                                f"'{module}' [{src_bg}] imports "
                                f"'{imported_module}' [{tgt_bg}] which "
                                f"re-exports forbidden bloodgroup symbols"
                            ),
                            rule_id=rule.rule_id,
                        )
                    )
    return violations


def _group_re_exports_forbidden_bloodgroup(
    group: ComponentGroup,
    forbidden_bloodgroups: tuple[str, ...],
    component_groups: tuple[ComponentGroup, ...],
) -> bool:
    """Prueft ob eine Gruppe verbotene Blutgruppen-Symbole re-exportiert.

    Args:
        group: Die zu pruefende Gruppe.
        forbidden_bloodgroups: Verbotene Blutgruppen.
        component_groups: Alle bekannten Gruppen.

    Returns:
        True wenn die Gruppe verbotene Blutgruppen-Symbole re-exportiert.
    """
    for sym in group.exported_symbols:
        sym_group = _group_for_module(sym, component_groups)
        if sym_group is not None and sym_group.bloodgroup in forbidden_bloodgroups:
            return True
    for surface_module in group.top_surface_modules:
        surface_group = _group_for_module(surface_module, component_groups)
        if (
            surface_group is not None
            and surface_group.bloodgroup in forbidden_bloodgroups
        ):
            return True
    return False


def _check_effect_surfaces(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    effect_surfaces: tuple[EffectSurface, ...],
) -> list[ArchitectureViolation]:
    """AC006 — Symbol-basierte Effektflaechen-Pruefung.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        effect_surfaces: Effektflaechen-Regeln.

    Returns:
        Liste der AC006-Verletzungen.
    """
    if not effect_surfaces:
        return []

    # Pre-compile flat lookup for performance.
    exact_patterns: dict[str, list[tuple[str, str, frozenset[str]]]] = {}
    wildcard_prefixes: list[tuple[str, str, str, frozenset[str]]] = []

    for surface in effect_surfaces:
        forbidden_set = frozenset(surface.forbidden_for_bloodgroups)
        for sym in surface.symbols:
            if sym.endswith(".*"):
                prefix = sym[:-2]
                wildcard_prefixes.append(
                    (prefix, surface.surface_id, surface.message, forbidden_set)
                )
            else:
                exact_patterns.setdefault(sym, []).append(
                    (surface.surface_id, surface.message, forbidden_set)
                )

    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        if source_group is None:
            continue
        src_bg = source_group.bloodgroup

        for imported_module, line, column in record.imports:
            matched_entries: list[tuple[str, str, frozenset[str]]] = []

            # Check exact matches
            if imported_module in exact_patterns:
                matched_entries.extend(exact_patterns[imported_module])

            # Check wildcard prefix matches
            for prefix, surface_id, msg, forbidden_set in wildcard_prefixes:
                if imported_module == prefix or imported_module.startswith(
                    f"{prefix}."
                ):
                    matched_entries.append((surface_id, msg, forbidden_set))

            for surface_id, msg, forbidden_set in matched_entries:
                if src_bg not in forbidden_set:
                    continue
                violations.append(
                    ArchitectureViolation(
                        code="AC006",
                        path=record.path,
                        module=module,
                        line=line,
                        column=column,
                        message=(
                            f"{msg}: '{module}' [{src_bg}] imports "
                            f"effect-surface symbol '{imported_module}'"
                        ),
                        rule_id=surface_id,
                    )
                )
    return violations


def _check_type_taint_rules(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
    rules: tuple[TypeTaintRule, ...],
) -> list[ArchitectureViolation]:
    """AC007 — AST-basierte Typen-Taint-Pruefung fuer oeffentliche Signaturen.

    Args:
        import_graph: Importgraph des gescannten Codes.
        component_groups: Bekannte Komponenten-Gruppen.
        rules: Typen-Taint-Regeln.

    Returns:
        Liste der AC007-Verletzungen.
    """
    if not rules:
        return []

    violations: list[ArchitectureViolation] = []

    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        if source_group is None:
            continue

        applicable_rules = [
            rule for rule in rules if rule.source_bloodgroup == source_group.bloodgroup
        ]
        if not applicable_rules:
            continue

        try:
            source_text = record.path.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(record.path))
        except (OSError, SyntaxError):
            continue

        alias_map = _build_alias_map(tree)

        for rule in applicable_rules:
            forbidden_tainted = frozenset(rule.forbidden_typed_bloodgroups)
            forbidden_instantiation = frozenset(
                rule.forbid_instantiation_of_bloodgroups
            )

            # Check public function/class signatures
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("_"):
                        continue
                    annotation_nodes = _collect_annotation_nodes(node)
                    for ann_node in annotation_nodes:
                        resolved_names = _resolve_annotation_names(ann_node, alias_map)
                        for name in resolved_names:
                            bg = _bloodgroup_for_qualified_name(
                                name, component_groups, alias_map
                            )
                            if bg in forbidden_tainted:
                                violations.append(
                                    ArchitectureViolation(
                                        code="AC007",
                                        path=record.path,
                                        module=module,
                                        line=node.lineno,
                                        column=node.col_offset + 1,
                                        message=(
                                            f"{rule.message}: public function "
                                            f"'{node.name}' in '{module}' uses "
                                            f"type '{name}' with bloodgroup '{bg}'"
                                        ),
                                        rule_id=f"{rule.rule_id}.type_taint",
                                    )
                                )

                    # Check for forbidden instantiation in function body
                    if forbidden_instantiation:
                        call_violations = _find_forbidden_calls(
                            node,
                            module,
                            record.path,
                            rule,
                            forbidden_instantiation,
                            component_groups,
                            alias_map,
                        )
                        violations.extend(call_violations)

                elif isinstance(node, ast.ClassDef):
                    if node.name.startswith("_"):
                        continue
                    # Check public class body for attribute annotations
                    for item in node.body:
                        if (
                            isinstance(item, ast.AnnAssign)
                            and isinstance(item.target, ast.Name)
                            and not item.target.id.startswith("_")
                        ):
                            resolved = _resolve_annotation_names(
                                item.annotation, alias_map
                            )
                            for name in resolved:
                                bg = _bloodgroup_for_qualified_name(
                                    name, component_groups, alias_map
                                )
                                if bg in forbidden_tainted:
                                    violations.append(
                                        ArchitectureViolation(
                                            code="AC007",
                                            path=record.path,
                                            module=module,
                                            line=item.lineno,
                                            column=item.col_offset + 1,
                                            message=(
                                                f"{rule.message}: public attribute"
                                                f" '{item.target.id}' in class"
                                                f" '{node.name}' of '{module}'"
                                                f" uses type '{name}' [{bg}]"
                                            ),
                                            rule_id=f"{rule.rule_id}.type_taint",
                                        )
                                    )

    return violations


def _build_alias_map(tree: ast.Module) -> dict[str, str]:
    """Erstellt eine Map von lokalen Namen zu vollqualifizierten Namen.

    Args:
        tree: Geparster AST eines Python-Moduls.

    Returns:
        Mapping von lokalem Alias zu vollqualifiziertem Modulnamen.
    """
    alias_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                alias_map[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module_base = node.module or ""
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                fqn = f"{module_base}.{alias.name}" if module_base else alias.name
                alias_map[local_name] = fqn
    return alias_map


def _collect_annotation_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.expr]:
    """Sammelt alle Annotations-Knoten einer Funktion.

    Args:
        node: Funktions-Knoten im AST.

    Returns:
        Liste aller Annotations-Ausdruecke (Parameter + Rueckgabewert).
    """
    annotations: list[ast.expr] = []
    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
        if arg.annotation is not None:
            annotations.append(arg.annotation)
    if node.args.vararg and node.args.vararg.annotation:
        annotations.append(node.args.vararg.annotation)
    if node.args.kwarg and node.args.kwarg.annotation:
        annotations.append(node.args.kwarg.annotation)
    if node.returns is not None:
        annotations.append(node.returns)
    return annotations


def _resolve_annotation_names(
    node: ast.expr,
    alias_map: dict[str, str],
) -> list[str]:
    """Loest Annotations-Ausdruecke zu vollqualifizierten Namen auf.

    Args:
        node: Annotations-Ausdruck im AST.
        alias_map: Mapping von lokalen Aliasen zu vollqualifizierten Namen.

    Returns:
        Liste aufgeloester vollqualifizierter Namen (ggf. unvollstaendig).
    """
    results: list[str] = []
    _collect_names_from_annotation(node, alias_map, results)
    return results


def _collect_names_from_annotation(
    node: ast.expr,
    alias_map: dict[str, str],
    results: list[str],
) -> None:
    """Rekursiv Annotations-Knoten nach Typ-Namen durchsuchen.

    Args:
        node: AST-Knoten.
        alias_map: Lokaler Alias-Map.
        results: Sammelliste fuer aufgeloeste Namen (in-place erweitert).
    """
    if isinstance(node, ast.Name):
        resolved = alias_map.get(node.id, node.id)
        results.append(resolved)
    elif isinstance(node, ast.Attribute):
        full = _ast_attribute_to_str(node)
        if full:
            resolved = alias_map.get(full, full)
            results.append(resolved)
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Forward reference as string
        try:
            inner = ast.parse(node.value, mode="eval")
            if isinstance(inner, ast.Expression):
                _collect_names_from_annotation(inner.body, alias_map, results)
        except SyntaxError:
            pass
    elif isinstance(node, ast.Subscript):
        _collect_names_from_annotation(node.value, alias_map, results)
        if isinstance(node.slice, ast.Tuple):
            for elt in node.slice.elts:
                _collect_names_from_annotation(elt, alias_map, results)
        else:
            _collect_names_from_annotation(node.slice, alias_map, results)
    elif isinstance(node, ast.BinOp):
        # PEP 604 union syntax: X | Y
        _collect_names_from_annotation(node.left, alias_map, results)
        _collect_names_from_annotation(node.right, alias_map, results)
    elif isinstance(node, ast.Tuple):
        for elt in node.elts:
            _collect_names_from_annotation(elt, alias_map, results)


def _ast_attribute_to_str(node: ast.Attribute) -> str:
    """Konvertiert einen AST-Attribute-Knoten in einen Punktnamen.

    Args:
        node: AST-Attribute-Knoten.

    Returns:
        Vollqualifizierter Name oder leerer String wenn nicht auflösbar.
    """
    parts: list[str] = [node.attr]
    current: ast.expr = node.value
    while True:
        if isinstance(current, ast.Name):
            parts.append(current.id)
            break
        elif isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        else:
            return ""
    return ".".join(reversed(parts))


def _bloodgroup_for_qualified_name(
    name: str,
    component_groups: tuple[ComponentGroup, ...],
    alias_map: dict[str, str],
) -> str | None:
    """Gibt die Blutgruppe eines vollqualifizierten Namens zurueck.

    Args:
        name: Vollqualifizierter Typ-Name.
        component_groups: Bekannte Komponenten-Gruppen.
        alias_map: Lokaler Alias-Map (fuer weitere Aufloesung).

    Returns:
        Blutgruppen-Code oder None wenn nicht auflösbar.
    """
    resolved = alias_map.get(name, name)
    group = _group_for_module(resolved, component_groups)
    if group is not None:
        return group.bloodgroup
    return None


def _find_forbidden_calls(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    path: Path,
    rule: TypeTaintRule,
    forbidden_instantiation: frozenset[str],
    component_groups: tuple[ComponentGroup, ...],
    alias_map: dict[str, str],
) -> list[ArchitectureViolation]:
    """Sucht nach verbotenen Klassen-Instanziierungen in einer Funktion.

    Args:
        func_node: Funktions-Knoten im AST.
        module: Modulname.
        path: Pfad zum Quellfile.
        rule: Angewandte Typen-Taint-Regel.
        forbidden_instantiation: Verbotene Blutgruppen fuer Instanziierungen.
        component_groups: Bekannte Komponenten-Gruppen.
        alias_map: Lokaler Alias-Map.

    Returns:
        Liste der Verletzungen fuer verbotene Instanziierungen.
    """
    violations: list[ArchitectureViolation] = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        callee_name: str | None = None
        if isinstance(node.func, ast.Name):
            callee_name = alias_map.get(node.func.id, node.func.id)
        elif isinstance(node.func, ast.Attribute):
            full = _ast_attribute_to_str(node.func)
            if full:
                callee_name = alias_map.get(full, full)
        if callee_name is None:
            continue
        bg = _bloodgroup_for_qualified_name(callee_name, component_groups, alias_map)
        if bg in forbidden_instantiation:
            violations.append(
                ArchitectureViolation(
                    code="AC007",
                    path=path,
                    module=module,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    message=(
                        f"{rule.message}: '{module}' instantiates "
                        f"'{callee_name}' with bloodgroup '{bg}'"
                    ),
                    rule_id=f"{rule.rule_id}.forbidden_instantiation",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ModuleImports:
    path: Path
    imports: tuple[tuple[str, int, int], ...]


def _build_import_graph(code_root: Path) -> dict[str, _ModuleImports]:
    graph: dict[str, _ModuleImports] = {}
    for path in sorted(code_root.rglob("*.py")):
        module = _module_name_for_path(code_root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _ImportVisitor(module=module)
        visitor.visit(tree)
        graph[module] = _ModuleImports(path=path, imports=tuple(visitor.imports))
    return graph


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, *, module: str) -> None:
        self._module = module
        self.imports: list[tuple[str, int, int]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append((alias.name, node.lineno, node.col_offset + 1))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for target in _resolved_from_targets(self._module, node):
            self.imports.append((target, node.lineno, node.col_offset + 1))
        self.generic_visit(node)


def _module_name_for_path(code_root: Path, path: Path) -> str:
    relative = path.relative_to(code_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolved_from_targets(
    current_module: str, node: ast.ImportFrom
) -> tuple[str, ...]:
    base_module = _resolve_import_from_base(current_module, node.module, node.level)
    if not base_module:
        return ()
    targets = {base_module}
    for alias in node.names:
        if alias.name == "*":
            continue
        targets.add(f"{base_module}.{alias.name}")
    return tuple(sorted(targets))


def _resolve_import_from_base(
    current_module: str,
    imported_module: str | None,
    level: int,
) -> str:
    if level == 0:
        return imported_module or ""

    package_parts = current_module.split(".")[:-1]
    if level - 1 > len(package_parts):
        return ""
    anchor_parts = package_parts[: len(package_parts) - (level - 1)]
    if imported_module:
        anchor_parts.extend(imported_module.split("."))
    return ".".join(part for part in anchor_parts if part)


def _group_lookup(
    component_groups: tuple[ComponentGroup, ...],
) -> dict[str, ComponentGroup]:
    return {group.group_id: group for group in component_groups}


def _group_edges(
    import_graph: dict[str, _ModuleImports],
    component_groups: tuple[ComponentGroup, ...],
) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {group.group_id: set() for group in component_groups}
    for module, record in import_graph.items():
        source_group = _group_for_module(module, component_groups)
        if source_group is None:
            continue
        for imported_module, _, _ in record.imports:
            target_group = _group_for_module(imported_module, component_groups)
            if target_group is None or target_group.group_id == source_group.group_id:
                continue
            edges[source_group.group_id].add(target_group.group_id)
    return edges


def _group_for_module(
    module: str,
    component_groups: tuple[ComponentGroup, ...],
) -> ComponentGroup | None:
    matches = [
        group
        for group in component_groups
        if _matches_prefix(module, group.module_prefixes)
    ]
    if not matches:
        return None
    return max(
        matches, key=lambda item: max(len(prefix) for prefix in item.module_prefixes)
    )


def _boundary_for_module(
    module: str,
    boundary_modules: tuple[BoundaryModule, ...],
) -> BoundaryModule | None:
    """Gibt das Boundary-Modul zurueck, zu dem ein Modul-Name gehoert.

    Args:
        module: Vollqualifizierter Modulname.
        boundary_modules: Bekannte Boundary-Module.

    Returns:
        Passendes BoundaryModule oder None wenn nicht gefunden.
    """
    matches = [
        bm
        for bm in boundary_modules
        if _matches_prefix(module, bm.module_prefixes)
    ]
    if not matches:
        return None
    return max(
        matches, key=lambda item: max(len(prefix) for prefix in item.module_prefixes)
    )


def _top_level_group(
    group: ComponentGroup,
    lookup: dict[str, ComponentGroup],
) -> ComponentGroup:
    """Gibt die oberste Elterngruppe einer Gruppe zurueck.

    Args:
        group: Ausgangspunkt.
        lookup: Mapping von group_id zu ComponentGroup.

    Returns:
        Oberste Elterngruppe (oder die Gruppe selbst wenn bereits Top-Level).
    """
    current = group
    while current.parent_group_id is not None:
        parent = lookup.get(current.parent_group_id)
        if parent is None:
            break
        current = parent
    return current


def _find_group_cycle(
    edges: dict[str, set[str]],
    group_ids: tuple[str, ...],
) -> tuple[str, ...] | None:
    allowed = set(group_ids)
    visited: set[str] = set()
    stack: list[str] = []
    visiting: set[str] = set()

    def walk(node: str) -> tuple[str, ...] | None:
        visiting.add(node)
        stack.append(node)
        for successor in sorted(edges.get(node, set())):
            if successor not in allowed:
                continue
            if successor in visiting:
                start = stack.index(successor)
                return tuple(stack[start:] + [successor])
            if successor in visited:
                continue
            cycle = walk(successor)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in group_ids:
        if node in visited:
            continue
        cycle = walk(node)
        if cycle is not None:
            return cycle
    return None


def _matches_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------


def _load_component_group(entry: dict[str, Any], path: Path) -> ComponentGroup:
    """Laedt eine Komponenten-Gruppe aus einem YAML-Eintrag.

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Pfad zur Quelldatei fuer Fehlermeldungen.

    Returns:
        Normalisierte ComponentGroup.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen oder ungueltig sind.
    """
    group_id = _require_string(entry, "id", path)
    name = _require_string(entry, "name", path)
    bloodgroup = _require_string(entry, "bloodgroup", path)
    if bloodgroup not in _VALID_BLOODGROUPS:
        raise ArchitectureConformanceError(
            f"Architecture-conformance bloodgroup '{bloodgroup}' in {path} is invalid; "
            f"must be one of {sorted(_VALID_BLOODGROUPS)}",
            detail={"path": str(path), "group_id": group_id, "bloodgroup": bloodgroup},
        )
    module_prefixes = _require_string_tuple(entry, "module_prefixes", path)

    parent_group_id: str | None = entry.get("parent_group_id") or None

    # Determine default exposure
    default_exposure = "top" if parent_group_id is None else "internal"
    exposure_raw = entry.get("exposure")
    exposure = exposure_raw if exposure_raw is not None else default_exposure
    if exposure not in _VALID_EXPOSURE:
        raise ArchitectureConformanceError(
            f"Architecture-conformance exposure '{exposure}' for group '{group_id}' "
            f"in {path} is invalid; must be one of {sorted(_VALID_EXPOSURE)}",
            detail={"path": str(path), "group_id": group_id, "exposure": exposure},
        )
    if exposure == "sub_exposed" and parent_group_id is None:
        raise ArchitectureConformanceError(
            f"Architecture-conformance group '{group_id}' in {path} has "
            f"exposure='sub_exposed' but no parent_group_id;"
            f" sub_exposed requires a parent",
            detail={"path": str(path), "group_id": group_id},
        )

    top_surface_modules_raw = entry.get("top_surface_modules") or []
    if not isinstance(top_surface_modules_raw, list):
        raise ArchitectureConformanceError(
            f"Architecture-conformance field 'top_surface_modules' for group "
            f"'{group_id}' in {path} must be a list",
            detail={"path": str(path), "group_id": group_id},
        )
    top_surface_modules = tuple(str(s) for s in top_surface_modules_raw)
    for tsm in top_surface_modules:
        if not any(tsm == p or tsm.startswith(f"{p}.") for p in module_prefixes):
            raise ArchitectureConformanceError(
                f"Architecture-conformance top_surface_module '{tsm}' for group "
                f"'{group_id}' in {path} is not a subprefix of any module_prefix",
                detail={"path": str(path), "group_id": group_id, "module": tsm},
            )

    component_kind_raw = entry.get("component_kind")
    component_kind = component_kind_raw if component_kind_raw is not None else "domain"
    if component_kind not in _VALID_COMPONENT_KINDS:
        raise ArchitectureConformanceError(
            f"Architecture-conformance component_kind '{component_kind}' for group "
            f"'{group_id}' in {path} is invalid; must be one of "
            f"{sorted(_VALID_COMPONENT_KINDS)}",
            detail={"path": str(path), "group_id": group_id, "kind": component_kind},
        )

    owner_group_id: str | None = entry.get("owner_group_id") or None
    allowed_importers_raw = entry.get("allowed_importers") or []
    exported_symbols_raw = entry.get("exported_symbols") or []
    allowed_imported_symbols_raw = entry.get("allowed_imported_symbols") or []

    if component_kind == "shared":
        if not owner_group_id:
            raise ArchitectureConformanceError(
                f"Architecture-conformance shared group '{group_id}' in {path} "
                f"is missing required field 'owner_group_id'",
                detail={"path": str(path), "group_id": group_id},
            )
        if not isinstance(allowed_importers_raw, list) or not allowed_importers_raw:
            raise ArchitectureConformanceError(
                f"Architecture-conformance shared group '{group_id}' in {path} "
                f"requires non-empty 'allowed_importers'",
                detail={"path": str(path), "group_id": group_id},
            )
        if not isinstance(exported_symbols_raw, list) or not exported_symbols_raw:
            raise ArchitectureConformanceError(
                f"Architecture-conformance shared group '{group_id}' in {path} "
                f"requires non-empty 'exported_symbols'",
                detail={"path": str(path), "group_id": group_id},
            )
        if (
            not isinstance(allowed_imported_symbols_raw, list)
            or not allowed_imported_symbols_raw
        ):
            raise ArchitectureConformanceError(
                f"Architecture-conformance shared group '{group_id}' in {path} "
                f"requires non-empty 'allowed_imported_symbols'",
                detail={"path": str(path), "group_id": group_id},
            )

    intra_bc_layer_order_raw = entry.get("intra_bc_layer_order") or []
    if not isinstance(intra_bc_layer_order_raw, list):
        raise ArchitectureConformanceError(
            f"Architecture-conformance field 'intra_bc_layer_order' for group "
            f"'{group_id}' in {path} must be a list",
            detail={"path": str(path), "group_id": group_id},
        )

    return ComponentGroup(
        group_id=group_id,
        name=name,
        bloodgroup=bloodgroup,
        module_prefixes=module_prefixes,
        parent_group_id=parent_group_id,
        exposure=exposure,
        top_surface_modules=top_surface_modules,
        component_kind=component_kind,
        owner_group_id=owner_group_id,
        allowed_importers=tuple(str(s) for s in allowed_importers_raw),
        exported_symbols=tuple(str(s) for s in exported_symbols_raw),
        allowed_imported_symbols=tuple(str(s) for s in allowed_imported_symbols_raw),
        intra_bc_layer_order=tuple(str(s) for s in intra_bc_layer_order_raw),
    )


def _validate_component_group_hierarchy(
    component_groups: tuple[ComponentGroup, ...],
    path: Path,
) -> None:
    """Prueft Hierarchie-Invarianten der Komponenten-Gruppen.

    Args:
        component_groups: Alle geladenen Gruppen.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Raises:
        ArchitectureConformanceError: Wenn Hierarchie ungueltig ist.
    """
    lookup = {g.group_id: g for g in component_groups}

    # Validate parent references and shared allowed_importers
    for group in component_groups:
        if group.parent_group_id is not None and group.parent_group_id not in lookup:
            raise ArchitectureConformanceError(
                f"Architecture-conformance group '{group.group_id}' in {path} "
                f"references unknown parent_group_id '{group.parent_group_id}'",
                detail={
                    "path": str(path),
                    "group_id": group.group_id,
                    "parent_group_id": group.parent_group_id,
                },
            )
        if group.component_kind == "shared":
            if group.owner_group_id and group.owner_group_id not in lookup:
                raise ArchitectureConformanceError(
                    f"Architecture-conformance shared group"
                    f" '{group.group_id}' in {path} "
                    f"references unknown owner_group_id"
                    f" '{group.owner_group_id}'",
                    detail={"path": str(path), "group_id": group.group_id},
                )
            # allowed_importers must be top-level group ids
            for importer_id in group.allowed_importers:
                if importer_id not in lookup:
                    raise ArchitectureConformanceError(
                        f"Architecture-conformance shared group"
                        f" '{group.group_id}' in {path} "
                        f"references unknown allowed_importer"
                        f" '{importer_id}'",
                        detail={"path": str(path), "group_id": group.group_id},
                    )
                importer_group = lookup[importer_id]
                if not importer_group.is_top():
                    raise ArchitectureConformanceError(
                        f"Architecture-conformance shared group"
                        f" '{group.group_id}' in {path} has"
                        f" allowed_importer '{importer_id}'"
                        f" which is not a top-level group",
                        detail={"path": str(path), "group_id": group.group_id},
                    )

    # Check for cycles in parent chain
    for group in component_groups:
        visited: set[str] = set()
        current_id: str | None = group.group_id
        while current_id is not None:
            if current_id in visited:
                raise ArchitectureConformanceError(
                    f"Architecture-conformance parent_group_id chain forms a cycle "
                    f"starting at '{group.group_id}' in {path}",
                    detail={"path": str(path), "group_id": group.group_id},
                )
            visited.add(current_id)
            current = lookup.get(current_id)
            if current is None:
                break
            current_id = current.parent_group_id


def _load_bloodtype_dependency_rule(
    entry: dict[str, Any],
    path: Path,
) -> BloodtypeDependencyRule:
    """Laedt eine Blutgruppen-Abhaengigkeitsregel aus einem YAML-Eintrag.

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Returns:
        Normalisierte BloodtypeDependencyRule.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen oder ungueltig sind.
    """
    rule_id = _require_string(entry, "id", path)
    source_bg = _require_string(entry, "source_bloodgroup", path)
    if source_bg not in _VALID_BLOODGROUPS:
        raise ArchitectureConformanceError(
            f"Invalid source_bloodgroup '{source_bg}' in bloodtype_dependency_rule "
            f"'{rule_id}' in {path}",
            detail={"path": str(path), "rule_id": rule_id},
        )
    forbidden_raw = entry.get("forbidden_target_bloodgroups")
    if not isinstance(forbidden_raw, list) or not forbidden_raw:
        raise ArchitectureConformanceError(
            f"bloodtype_dependency_rule '{rule_id}' in {path} requires non-empty "
            f"'forbidden_target_bloodgroups'",
            detail={"path": str(path), "rule_id": rule_id},
        )
    for bg in forbidden_raw:
        if bg not in _VALID_BLOODGROUPS:
            raise ArchitectureConformanceError(
                f"Invalid forbidden_target_bloodgroup '{bg}'"
                f" in rule '{rule_id}' in {path}",
                detail={"path": str(path), "rule_id": rule_id},
            )
    allow_through = entry.get("allow_through_bloodgroup") or None
    if allow_through is not None and allow_through not in _VALID_BLOODGROUPS:
        raise ArchitectureConformanceError(
            f"Invalid allow_through_bloodgroup '{allow_through}'"
            f" in rule '{rule_id}' in {path}",
            detail={"path": str(path), "rule_id": rule_id},
        )
    message = _require_string(entry, "message", path)
    return BloodtypeDependencyRule(
        rule_id=rule_id,
        source_bloodgroup=source_bg,
        forbidden_target_bloodgroups=tuple(str(bg) for bg in forbidden_raw),
        allow_through_bloodgroup=allow_through,
        message=message,
    )


def _load_effect_surface(
    entry: dict[str, Any],
    path: Path,
) -> EffectSurface:
    """Laedt eine Effektflaechen-Regel aus einem YAML-Eintrag.

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Returns:
        Normalisierte EffectSurface.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen oder ungueltig sind.
    """
    surface_id = _require_string(entry, "id", path)
    name = _require_string(entry, "name", path)
    if name not in _VALID_EFFECT_SURFACE_NAMES:
        raise ArchitectureConformanceError(
            f"Invalid effect surface name '{name}' for '{surface_id}' in {path}; "
            f"must be one of {sorted(_VALID_EFFECT_SURFACE_NAMES)}",
            detail={"path": str(path), "surface_id": surface_id, "name": name},
        )
    forbidden_bgs_raw = entry.get("forbidden_for_bloodgroups")
    if not isinstance(forbidden_bgs_raw, list) or not forbidden_bgs_raw:
        raise ArchitectureConformanceError(
            f"effect_surface '{surface_id}' in {path} requires non-empty "
            f"'forbidden_for_bloodgroups'",
            detail={"path": str(path), "surface_id": surface_id},
        )
    symbols_raw = entry.get("symbols")
    if not isinstance(symbols_raw, list) or not symbols_raw:
        raise ArchitectureConformanceError(
            f"effect_surface '{surface_id}' in {path} requires non-empty 'symbols'",
            detail={"path": str(path), "surface_id": surface_id},
        )
    message = _require_string(entry, "message", path)
    return EffectSurface(
        surface_id=surface_id,
        name=name,
        forbidden_for_bloodgroups=tuple(str(bg) for bg in forbidden_bgs_raw),
        symbols=tuple(str(s) for s in symbols_raw),
        message=message,
    )


def _load_type_taint_rule(
    entry: dict[str, Any],
    path: Path,
) -> TypeTaintRule:
    """Laedt eine Typen-Taint-Regel aus einem YAML-Eintrag.

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Returns:
        Normalisierte TypeTaintRule.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen oder ungueltig sind.
    """
    rule_id = _require_string(entry, "id", path)
    source_bg = _require_string(entry, "source_bloodgroup", path)
    if source_bg not in _VALID_BLOODGROUPS:
        raise ArchitectureConformanceError(
            f"Invalid source_bloodgroup '{source_bg}'"
            f" in type_taint_rule '{rule_id}' in {path}",
            detail={"path": str(path), "rule_id": rule_id},
        )
    forbidden_typed_raw = entry.get("forbidden_typed_bloodgroups") or []
    forbid_instantiation_raw = entry.get("forbid_instantiation_of_bloodgroups") or []
    message = _require_string(entry, "message", path)
    return TypeTaintRule(
        rule_id=rule_id,
        source_bloodgroup=source_bg,
        forbidden_typed_bloodgroups=tuple(str(bg) for bg in forbidden_typed_raw),
        forbid_instantiation_of_bloodgroups=tuple(
            str(bg) for bg in forbid_instantiation_raw
        ),
        message=message,
    )


def _load_boundary_module_kind(
    entry: dict[str, Any],
    path: Path,
) -> BoundaryModuleKind:
    """Laedt einen Boundary-Modul-Kategorie-Eintrag aus einem YAML-Mapping.

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Returns:
        Normalisiertes BoundaryModuleKind.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen.
    """
    code = _require_string(entry, "code", path)
    meaning = _require_string(entry, "meaning", path)
    return BoundaryModuleKind(code=code, meaning=meaning)


def _load_boundary_module_raw(
    entry: dict[str, Any],
    path: Path,
    known_kind_codes: frozenset[str],
) -> BoundaryModule:
    """Laedt ein Boundary-Modul aus einem YAML-Mapping (ohne Kreuzreferenz-Pruefung).

    Args:
        entry: YAML-Mapping-Eintrag.
        path: Quelldatei-Pfad fuer Fehlermeldungen.
        known_kind_codes: Bekannte Boundary-Modul-Kategorie-Codes.

    Returns:
        Normalisiertes BoundaryModule.

    Raises:
        ArchitectureConformanceError: Wenn Pflichtfelder fehlen oder ungueltig sind.
    """
    boundary_id = _require_string(entry, "id", path)
    name = _require_string(entry, "name", path)
    bloodgroup = _require_string(entry, "bloodgroup", path)
    if bloodgroup not in _VALID_BLOODGROUPS:
        raise ArchitectureConformanceError(
            f"Architecture-conformance bloodgroup '{bloodgroup}' for boundary-module"
            f" '{boundary_id}' in {path} is invalid;"
            f" must be one of {sorted(_VALID_BLOODGROUPS)}",
            detail={"path": str(path), "boundary_id": boundary_id, "bloodgroup": bloodgroup},
        )
    boundary_kind = _require_string(entry, "boundary_kind", path)
    if known_kind_codes and boundary_kind not in known_kind_codes:
        raise ArchitectureConformanceError(
            f"Architecture-conformance boundary_kind '{boundary_kind}' for"
            f" boundary-module '{boundary_id}' in {path} is not declared in"
            f" boundary_module_kinds; known codes: {sorted(known_kind_codes)}",
            detail={"path": str(path), "boundary_id": boundary_id, "kind": boundary_kind},
        )
    module_prefixes = _require_string_tuple(entry, "module_prefixes", path)

    importable_by = _load_any_or_ids(entry, "importable_by", boundary_id, path)
    may_import_component_groups = _load_any_or_ids(
        entry, "may_import_component_groups", boundary_id, path
    )

    may_import_boundary_raw = entry.get("may_import_boundary_modules") or []
    if not isinstance(may_import_boundary_raw, list):
        raise ArchitectureConformanceError(
            f"Architecture-conformance field 'may_import_boundary_modules' for"
            f" boundary-module '{boundary_id}' in {path} must be a list",
            detail={"path": str(path), "boundary_id": boundary_id},
        )
    may_import_boundary_modules = tuple(str(s) for s in may_import_boundary_raw)

    return BoundaryModule(
        boundary_id=boundary_id,
        name=name,
        bloodgroup=bloodgroup,
        boundary_kind=boundary_kind,
        module_prefixes=module_prefixes,
        importable_by=importable_by,
        may_import_component_groups=may_import_component_groups,
        may_import_boundary_modules=may_import_boundary_modules,
    )


def _load_any_or_ids(
    entry: dict[str, Any],
    key: str,
    context_id: str,
    path: Path,
) -> _AnyOrIds:
    """Laedt einen Sentinel-Tagged-Wert: entweder "any" oder eine ID-Liste.

    Args:
        entry: YAML-Mapping-Eintrag.
        key: Feldname.
        context_id: ID des Eltern-Eintrags fuer Fehlermeldungen.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Returns:
        Literal "any" oder ein Tupel von ID-Strings.

    Raises:
        ArchitectureConformanceError: Wenn der Wert weder "any" noch eine Liste ist.
    """
    raw = entry.get(key)
    if raw == "any":
        return "any"
    if raw is None or raw == []:
        return ()
    if isinstance(raw, list):
        return tuple(str(s) for s in raw)
    raise ArchitectureConformanceError(
        f"Architecture-conformance field '{key}' for '{context_id}' in {path}"
        f" must be 'any' or a list of IDs",
        detail={"path": str(path), "id": context_id, "field": key, "value": raw},
    )


def _validate_boundary_module_refs(
    boundary_modules: tuple[BoundaryModule, ...],
    known_group_ids: frozenset[str],
    known_boundary_ids: frozenset[str],
    path: Path,
) -> None:
    """Prueft Kreuzreferenzen in Boundary-Modul-Eintraegen.

    Validiert, dass alle IDs in importable_by, may_import_component_groups
    und may_import_boundary_modules auf bekannte Eintraege zeigen.

    Args:
        boundary_modules: Alle geladenen Boundary-Module.
        known_group_ids: Bekannte Komponenten-Gruppen-IDs.
        known_boundary_ids: Bekannte Boundary-Modul-IDs.
        path: Quelldatei-Pfad fuer Fehlermeldungen.

    Raises:
        ArchitectureConformanceError: Wenn eine Referenz ungueltig ist.
    """
    all_known = known_group_ids | known_boundary_ids
    for bm in boundary_modules:
        if bm.importable_by != "any":
            for ref_id in bm.importable_by:
                if ref_id not in all_known:
                    raise ArchitectureConformanceError(
                        f"Architecture-conformance boundary-module '{bm.boundary_id}'"
                        f" in {path} has unknown importable_by reference '{ref_id}'",
                        detail={"path": str(path), "boundary_id": bm.boundary_id, "ref": ref_id},
                    )
        if bm.may_import_component_groups != "any":
            for ref_id in bm.may_import_component_groups:
                if ref_id not in known_group_ids:
                    raise ArchitectureConformanceError(
                        f"Architecture-conformance boundary-module '{bm.boundary_id}'"
                        f" in {path} has unknown may_import_component_groups"
                        f" reference '{ref_id}'",
                        detail={"path": str(path), "boundary_id": bm.boundary_id, "ref": ref_id},
                    )
        for ref_id in bm.may_import_boundary_modules:
            if ref_id not in known_boundary_ids:
                raise ArchitectureConformanceError(
                    f"Architecture-conformance boundary-module '{bm.boundary_id}'"
                    f" in {path} has unknown may_import_boundary_modules"
                    f" reference '{ref_id}'",
                    detail={"path": str(path), "boundary_id": bm.boundary_id, "ref": ref_id},
                )


def _require_document(compiled: CompiledFormalSpec, doc_id: str) -> Any:
    document = next((doc for doc in compiled.documents if doc.doc_id == doc_id), None)
    if document is None:
        raise ArchitectureConformanceError(
            f"Missing architecture-conformance formal spec: {doc_id}",
            detail={"object_id": doc_id},
        )
    return document


def _load_acyclic_group_set(
    entry: dict[str, Any],
    path: Path,
    known_group_ids: set[str],
) -> AcyclicGroupSet:
    group_ids = _require_string_tuple(entry, "group_ids", path)
    unknown = sorted(
        group_id for group_id in group_ids if group_id not in known_group_ids
    )
    if unknown:
        raise ArchitectureConformanceError(
            f"Unknown architecture component groups in {path}: {', '.join(unknown)}",
            detail={"path": str(path), "unknown_group_ids": unknown},
        )
    return AcyclicGroupSet(
        set_id=_require_string(entry, "id", path),
        group_ids=group_ids,
    )


def _require_mapping_list(
    spec: dict[str, Any],
    key: str,
    path: Path,
) -> list[dict[str, Any]]:
    value = spec.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArchitectureConformanceError(
            f"Architecture-conformance spec field '{key}' in {path} "
            "must be a list of mappings",
            detail={"path": str(path), "field": key, "value": value},
        )
    return value


def _optional_mapping_list(
    spec: dict[str, Any],
    key: str,
    path: Path,
) -> list[dict[str, Any]]:
    value = spec.get(key, [])
    if value == []:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArchitectureConformanceError(
            f"Architecture-conformance spec field '{key}' in {path} "
            "must be a list of mappings",
            detail={"path": str(path), "field": key, "value": value},
        )
    return value


def _require_string(mapping: dict[str, Any], key: str, path: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise ArchitectureConformanceError(
            f"Architecture-conformance field '{key}' in {path} "
            "must be a non-empty string",
            detail={"path": str(path), "field": key, "value": value},
        )
    return value


def _require_string_tuple(
    mapping: dict[str, Any],
    key: str,
    path: Path,
) -> tuple[str, ...]:
    value = mapping.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item != "" for item in value)
    ):
        raise ArchitectureConformanceError(
            f"Architecture-conformance field '{key}' in {path} "
            "must be a non-empty string list",
            detail={"path": str(path), "field": key, "value": value},
        )
    return tuple(value)
