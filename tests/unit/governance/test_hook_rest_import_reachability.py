"""Static import-reachability regression pin for AG3-129 (AC1).

After AG3-129 the guard-counter, worker-health, telemetry AND story-type hook
paths mediate canonical state over REST. This test proves (via AST, ignoring
prose) that:

1. the converted runner functions reference NONE of the direct-DB repositories /
   emitter / DSN / ``psycopg`` (per-function scan); and
2. the WHOLE transitive import closure of the hook-side REST mediation modules
   (``rest_edge`` + the projectedge client + the REST emitter + the REST
   worker-health store) reaches NO ``agentkit.backend.state_backend`` module,
   NO ``psycopg`` import and NO ``AGENTKIT_STATE_DATABASE_URL`` -- i.e. the
   mediation path is transitively database-free (the transitive proof the round-1
   review asked for, catching lazily-imported DB access).

It is deliberately SCOPED to the converted paths / mediation modules (not the
whole runner): other runner paths -- capability enforcement, freeze, CCAG -- are
migrated by separate stories (AG3-131 et al.), so a whole-runner ban would be
wrong here.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import agentkit.backend.governance.runner as runner_mod

_DIRECT_DB_CLASSES = frozenset(
    {
        "StateBackendGuardCounterRepository",
        "StateBackendWorkerHealthRepository",
        "StateBackendStoryRepository",
        "StateBackendEmitter",
    }
)
_DSN_ENV = "AGENTKIT_STATE_DATABASE_URL"
_STATE_BACKEND_PKG = "agentkit.backend.state_backend"

#: The runner functions AG3-129 converted from direct-DB to REST mediation.
_CONVERTED_FUNCTIONS = (
    "_record_guard_invocation",
    "_sweep_stale_guard_counters",
    "_run_health_monitor_pre",
    "_run_health_monitor_post",
    "_run_review_guard",
    "_run_web_call_budget_guard",
    "_run_budget_event_emitter_post",
    "_run_skill_usage_check",
    "_run_prompt_integrity_guard",
    "_resolve_local_story_type",
    "_is_code_producing_story",
    "_authoritative_required_roles",
)

#: The hook-side REST state-mediation modules whose transitive closure must be
#: database-free.
_MEDIATION_SEED_MODULES = (
    "agentkit.backend.governance.rest_edge",
    "agentkit.harness_client.projectedge.governance_client",
    "agentkit.backend.telemetry.rest_emitter",
    "agentkit.backend.implementation.worker_health.rest_repository",
)


def _is_type_checking_test(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


class _StripTypeChecking(ast.NodeTransformer):
    """Drop ``if TYPE_CHECKING:`` bodies so only RUNTIME imports remain.

    Type-only imports never execute, so they are not runtime reachability -- the
    transitive DB-free proof must ignore them (a ``TYPE_CHECKING`` import of a
    state-backend type is a type annotation, not a database call).
    """

    def visit_If(self, node: ast.If) -> object:  # noqa: N802 -- ast visitor name
        if _is_type_checking_test(node.test):
            return [self.visit(child) for child in node.orelse]
        self.generic_visit(node)
        return node


def _runtime_tree(source: str) -> ast.Module:
    return ast.fix_missing_locations(_StripTypeChecking().visit(ast.parse(source)))


def _module_file(module_name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
        return None
    return Path(spec.origin)


def _imported_agentkit_modules(tree: ast.AST) -> set[str]:
    """Return every ``agentkit.*`` module imported anywhere in ``tree``.

    Walks module-level AND function-body (lazy) imports so a psycopg import
    hidden behind a lazy ``import`` inside a helper is still followed.
    """
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("agentkit"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("agentkit"):
                modules.add(module)
                modules.update(f"{module}.{a.name}" for a in node.names)
    return modules


def _direct_db_hits(node: ast.AST) -> set[str]:
    """Return direct-DB identifiers/imports/DSN-strings actually used in ``node``."""
    hits: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                if "psycopg" in alias.name:
                    hits.add("psycopg")
        elif isinstance(child, ast.ImportFrom):
            module = child.module or ""
            if "psycopg" in module:
                hits.add("psycopg")
            if module.startswith(_STATE_BACKEND_PKG):
                hits.add(module)
            for alias in child.names:
                if alias.name in _DIRECT_DB_CLASSES:
                    hits.add(alias.name)
        elif isinstance(child, ast.Name) and (
            child.id in _DIRECT_DB_CLASSES or child.id == "psycopg"
        ):
            hits.add(child.id)
        elif isinstance(child, ast.Attribute) and child.attr in _DIRECT_DB_CLASSES:
            hits.add(child.attr)
        elif (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value == _DSN_ENV
        ):
            hits.add(_DSN_ENV)
    return hits


def _functions_by_name(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _module_import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def test_converted_runner_functions_carry_no_direct_db() -> None:
    source = Path(runner_mod.__file__).read_text(encoding="utf-8")
    functions = _functions_by_name(ast.parse(source))
    for name in _CONVERTED_FUNCTIONS:
        assert name in functions, f"converted function {name} not found in runner"
        hits = _direct_db_hits(functions[name])
        assert not hits, f"{name} still reaches direct-DB {sorted(hits)} after AG3-129"


def test_mediation_closure_is_transitively_db_free() -> None:
    """Transitive proof: the REST mediation modules reach no DB (AC1, round-2)."""
    visited: set[str] = set()
    queue: list[str] = list(_MEDIATION_SEED_MODULES)
    offenders: list[str] = []

    while queue:
        module_name = queue.pop()
        if module_name in visited:
            continue
        visited.add(module_name)
        # A reachable ``state_backend`` module (the direct-DB store) is itself a
        # violation -- the mediation path must never transitively import it.
        if module_name.startswith(_STATE_BACKEND_PKG):
            offenders.append(module_name)
            continue
        file = _module_file(module_name)
        if file is None:
            continue
        # RUNTIME reachability only: ``TYPE_CHECKING`` imports never execute.
        tree = _runtime_tree(file.read_text(encoding="utf-8"))
        if any("psycopg" in name for name in _module_import_names(tree)):
            offenders.append(f"{module_name} imports psycopg")
        hits = _direct_db_hits(tree)
        if hits:
            offenders.append(f"{module_name} references {sorted(hits)}")
        queue.extend(_imported_agentkit_modules(tree) - visited)

    assert not offenders, f"mediation closure is not DB-free: {offenders}"


def test_runner_module_never_imports_psycopg_or_dsn() -> None:
    tree = ast.parse(Path(runner_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "psycopg" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert "psycopg" not in (node.module or "")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != _DSN_ENV
