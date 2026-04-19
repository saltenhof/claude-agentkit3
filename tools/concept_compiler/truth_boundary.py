"""Concept-to-code truth-boundary contract checks."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentkit.exceptions import AgentKitError

if TYPE_CHECKING:
    from pathlib import Path

    from concept_compiler.compiler import CompiledFormalSpec

TRUTH_BOUNDARY_DOC_ID = "formal.truth-boundary-checker.invariants"
PATH_METHODS = frozenset({"open", "read_text", "read_bytes", "exists"})
JSON_LOAD_METHODS = frozenset({"load", "loads"})


class TruthBoundaryError(AgentKitError):
    """Raised when the truth-boundary contract is malformed or violated."""


@dataclass(frozen=True)
class TruthBoundaryConfig:
    """Normalized truth-boundary contract configuration."""

    protected_module_prefixes: tuple[str, ...]
    allowed_module_prefixes: tuple[str, ...]
    forbidden_loader_symbols: frozenset[str]
    forbidden_import_modules: tuple[str, ...]
    forbidden_json_truth_filenames: tuple[str, ...]
    forbidden_json_truth_globs: tuple[str, ...]


@dataclass(frozen=True)
class ContractViolation:
    """One static truth-boundary violation in source code."""

    code: str
    path: Path
    module: str
    line: int
    column: int
    message: str


def load_truth_boundary_config(
    compiled: CompiledFormalSpec,
    *,
    object_id: str = TRUTH_BOUNDARY_DOC_ID,
) -> TruthBoundaryConfig:
    """Load the truth-boundary checker policy from compiled formal specs."""
    document = next(
        (doc for doc in compiled.documents if doc.doc_id == object_id),
        None,
    )
    if document is None:
        raise TruthBoundaryError(
            f"Missing truth-boundary formal spec: {object_id}",
            detail={"object_id": object_id},
        )

    spec = document.spec
    return TruthBoundaryConfig(
        protected_module_prefixes=_require_string_tuple(
            spec,
            "protected_module_prefixes",
            document.path,
        ),
        allowed_module_prefixes=_require_string_tuple(
            spec,
            "allowed_module_prefixes",
            document.path,
        ),
        forbidden_loader_symbols=frozenset(
            _require_string_tuple(spec, "forbidden_loader_symbols", document.path),
        ),
        forbidden_import_modules=_require_string_tuple(
            spec,
            "forbidden_import_modules",
            document.path,
        ),
        forbidden_json_truth_filenames=_require_string_tuple(
            spec,
            "forbidden_json_truth_filenames",
            document.path,
        ),
        forbidden_json_truth_globs=_require_string_tuple(
            spec,
            "forbidden_json_truth_globs",
            document.path,
        ),
    )


def audit_truth_boundary(
    compiled: CompiledFormalSpec,
    code_root: Path,
) -> tuple[ContractViolation, ...]:
    """Scan protected modules for JSON-as-truth regressions."""
    config = load_truth_boundary_config(compiled)
    violations: list[ContractViolation] = []

    for path in sorted(code_root.rglob("*.py")):
        module = _module_name_for_path(code_root, path)
        if not _is_protected_module(module, config):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        checker = _TruthBoundaryVisitor(path=path, module=module, config=config)
        checker.visit(tree)
        violations.extend(checker.violations)

    return tuple(
        sorted(
            violations,
            key=lambda item: (str(item.path), item.line, item.column, item.code),
        )
    )


def raise_on_truth_boundary_violations(
    violations: tuple[ContractViolation, ...],
) -> None:
    """Raise a single aggregated error when violations are present."""
    if not violations:
        return

    formatted = "; ".join(
        (
            f"{violation.code} {violation.module}:{violation.line}:"
            f"{violation.column} {violation.message}"
        )
        for violation in violations
    )
    raise TruthBoundaryError(
        f"Truth-boundary contract violations detected: {formatted}",
        detail={
            "violations": [
                {
                    "code": violation.code,
                    "path": str(violation.path),
                    "module": violation.module,
                    "line": violation.line,
                    "column": violation.column,
                    "message": violation.message,
                }
                for violation in violations
            ]
        },
    )


class _TruthBoundaryVisitor(ast.NodeVisitor):
    def __init__(self, *, path: Path, module: str, config: TruthBoundaryConfig) -> None:
        self.path = path
        self.module = module
        self.config = config
        self.violations: list[ContractViolation] = []
        self.bound_string_candidates: dict[str, tuple[str, ...]] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        candidates = _candidate_strings(node.value, self.bound_string_candidates)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.bound_string_candidates[target.id] = candidates
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            imported = alias.name
            if _matches_prefix(imported, self.config.forbidden_import_modules):
                self._add_violation(
                    "TB002",
                    node,
                    f"protected module imports forbidden export module '{imported}'",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        imported_module = node.module or ""
        if _matches_prefix(imported_module, self.config.forbidden_import_modules):
            self._add_violation(
                "TB002",
                node,
                f"protected module imports forbidden export module '{imported_module}'",
            )

        for alias in node.names:
            if alias.name in self.config.forbidden_loader_symbols:
                self._add_violation(
                    "TB003",
                    node,
                    f"protected module imports forbidden export loader '{alias.name}'",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_json_load_call(node):
            self._add_violation(
                "TB001",
                node,
                "protected module uses json.load/json.loads in a decision path",
            )

        called_name = _called_name(node.func)
        if called_name in self.config.forbidden_loader_symbols:
            self._add_violation(
                "TB003",
                node,
                f"protected module calls forbidden export loader '{called_name}'",
            )

        if _is_path_method_call(node):
            for candidate in _path_read_candidates(node, self.bound_string_candidates):
                if _matches_forbidden_json_name(candidate, self.config):
                    self._add_violation(
                        "TB004",
                        node,
                        f"protected module reads forbidden story export '{candidate}'",
                    )
        if _is_builtin_open_call(node):
            for candidate in _argument_candidates(node, self.bound_string_candidates):
                if _matches_forbidden_json_name(candidate, self.config):
                    self._add_violation(
                        "TB004",
                        node,
                        f"protected module reads forbidden story export '{candidate}'",
                    )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _matches_forbidden_json_name(
            node.value, self.config
        ):
            self._add_violation(
                "TB005",
                node,
                (
                    "protected module references forbidden story export "
                    f"literal '{node.value}'"
                ),
            )
        self.generic_visit(node)

    def _add_violation(self, code: str, node: ast.AST, message: str) -> None:
        self.violations.append(
            ContractViolation(
                code=code,
                path=self.path,
                module=self.module,
                line=getattr(node, "lineno", 1),
                column=getattr(node, "col_offset", 0) + 1,
                message=message,
            ),
        )


def _module_name_for_path(code_root: Path, path: Path) -> str:
    relative = path.relative_to(code_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_protected_module(module: str, config: TruthBoundaryConfig) -> bool:
    if _matches_prefix(module, config.allowed_module_prefixes):
        return False
    return _matches_prefix(module, config.protected_module_prefixes)


def _matches_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)


def _require_string_tuple(
    spec: dict[str, Any], key: str, path: Path
) -> tuple[str, ...]:
    value = spec.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item != "" for item in value)
    ):
        raise TruthBoundaryError(
            (
                f"Truth-boundary spec field '{key}' in {path} must be a "
                "non-empty string list"
            ),
            detail={"path": str(path), "field": key, "value": value},
        )
    return tuple(value)


def _is_json_load_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "json"
        and func.attr in JSON_LOAD_METHODS
    )


def _is_path_method_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in PATH_METHODS


def _is_builtin_open_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "open"


def _called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _matches_forbidden_json_name(candidate: str, config: TruthBoundaryConfig) -> bool:
    if candidate in config.forbidden_json_truth_filenames:
        return True
    return any(
        fnmatch.fnmatch(candidate, pattern)
        for pattern in config.forbidden_json_truth_globs
    )


def _candidate_strings(
    node: ast.AST,
    bindings: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return bindings.get(node.id, ())
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("*")
        return ("".join(parts),)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _candidate_strings(node.right, bindings)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
    ):
        candidates: list[str] = []
        for argument in node.args:
            candidates.extend(_candidate_strings(argument, bindings))
        return tuple(candidates)
    return ()


def _path_read_candidates(
    node: ast.Call,
    bindings: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    candidates: list[str] = []
    if isinstance(node.func, ast.Attribute):
        candidates.extend(_candidate_strings(node.func.value, bindings))
    candidates.extend(_argument_candidates(node, bindings))
    return tuple(candidates)


def _argument_candidates(
    node: ast.Call,
    bindings: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    candidates: list[str] = []
    for argument in node.args:
        candidates.extend(_candidate_strings(argument, bindings))
    return tuple(candidates)
