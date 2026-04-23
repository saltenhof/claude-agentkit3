"""Deterministic architecture-conformance checks driven by formal specs."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.exceptions import AgentKitError

if TYPE_CHECKING:
    from concept_compiler.compiler import CompiledFormalSpec

ENTITIES_DOC_ID = "formal.architecture-conformance.entities"
INVARIANTS_DOC_ID = "formal.architecture-conformance.invariants"


class ArchitectureConformanceError(AgentKitError):
    """Raised when architecture-conformance specs or checks fail."""


@dataclass(frozen=True)
class ComponentGroup:
    """One named component group used for dependency checks."""

    group_id: str
    name: str
    bloodgroup: str
    module_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class DependencyRule:
    """One forbidden import direction."""

    rule_id: str
    source_module_prefixes: tuple[str, ...]
    forbidden_module_prefixes: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class AcyclicGroupSet:
    """One group subset that must remain acyclic."""

    set_id: str
    group_ids: tuple[str, ...]


@dataclass(frozen=True)
class MutationSurfaceRule:
    """One bounded write-surface rule over imported writer symbols."""

    rule_id: str
    writer_symbols: tuple[str, ...]
    allowed_module_prefixes: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ArchitectureConformanceConfig:
    """Normalized architecture checker policy."""

    component_groups: tuple[ComponentGroup, ...]
    dependency_rules: tuple[DependencyRule, ...]
    acyclic_group_sets: tuple[AcyclicGroupSet, ...]
    mutation_surface_rules: tuple[MutationSurfaceRule, ...]


@dataclass(frozen=True)
class ArchitectureViolation:
    """One deterministic architecture violation in code."""

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
    """Load architecture-conformance policy from compiled formal specs."""
    entities = _require_document(compiled, ENTITIES_DOC_ID)
    invariants = _require_document(compiled, INVARIANTS_DOC_ID)

    component_groups = tuple(
        ComponentGroup(
            group_id=_require_string(entry, "id", entities.path),
            name=_require_string(entry, "name", entities.path),
            bloodgroup=_require_string(entry, "bloodgroup", entities.path),
            module_prefixes=_require_string_tuple(entry, "module_prefixes", entities.path),
        )
        for entry in _require_mapping_list(entities.spec, "component_groups", entities.path)
    )

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

    known_group_ids = {group.group_id for group in component_groups}
    acyclic_group_sets = tuple(
        _load_acyclic_group_set(entry, invariants.path, known_group_ids)
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
    return ArchitectureConformanceConfig(
        component_groups=component_groups,
        dependency_rules=dependency_rules,
        acyclic_group_sets=acyclic_group_sets,
        mutation_surface_rules=mutation_surface_rules,
    )


def audit_architecture_conformance(
    compiled: CompiledFormalSpec,
    code_root: Path,
) -> tuple[ArchitectureViolation, ...]:
    """Scan Python code for formal architecture-boundary violations."""
    config = load_architecture_conformance_config(compiled)
    import_graph = _build_import_graph(code_root)
    violations = _check_dependency_rules(import_graph, config.dependency_rules)
    cycle_violations = _check_acyclic_sets(import_graph, config)
    mutation_surface_violations = _check_mutation_surface_rules(
        import_graph,
        config.mutation_surface_rules,
    )
    return tuple(
        sorted(
            violations + cycle_violations + mutation_surface_violations,
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
    """Raise one aggregated error if architecture violations exist."""
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
                            message=(
                                f"{rule.message}: imports '{imported_module}'"
                            ),
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


def _resolved_from_targets(current_module: str, node: ast.ImportFrom) -> tuple[str, ...]:
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
    return max(matches, key=lambda item: max(len(prefix) for prefix in item.module_prefixes))


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


def _require_document(compiled: CompiledFormalSpec, doc_id: str):
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
    unknown = sorted(group_id for group_id in group_ids if group_id not in known_group_ids)
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
            f"Architecture-conformance spec field '{key}' in {path} must be a list of mappings",
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
            f"Architecture-conformance spec field '{key}' in {path} must be a list of mappings",
            detail={"path": str(path), "field": key, "value": value},
        )
    return value


def _require_string(mapping: dict[str, Any], key: str, path: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise ArchitectureConformanceError(
            f"Architecture-conformance field '{key}' in {path} must be a non-empty string",
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
            f"Architecture-conformance field '{key}' in {path} must be a non-empty string list",
            detail={"path": str(path), "field": key, "value": value},
        )
    return tuple(value)
