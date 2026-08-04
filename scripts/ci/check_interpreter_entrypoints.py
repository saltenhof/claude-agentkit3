"""Check that AgentKit entrypoints use the single interpreter owner."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path("src/agentkit")
INTERPRETER_OWNER = Path("src/agentkit/backend/installer/interpreter.py")
PACKAGE_BOUNDARY = Path("src/agentkit/__init__.py")
OWNER_MODULE = "agentkit.backend.installer.interpreter"
OWNER_FUNCTIONS = frozenset(
    {
        "ak3_interpreter_command",
        "ak3_python_command",
        "ak3_wrapper_command",
        "render_ak3_interpreter_command",
        "render_ak3_python_command",
        "render_ak3_wrapper_command",
        "resolve_ak3_interpreter",
        "resolve_ak3_wrapper",
    }
)
SUBPROCESS_FUNCTIONS = frozenset(
    {"call", "check_call", "check_output", "Popen", "run"}
)
BARE_PYTHON = re.compile(r"^python(?:3)?(?:\.exe)?$", re.IGNORECASE)

# ProjectEdge runs a user-requested pytest process inside its own edge runtime;
# it does not select an AK3 package entrypoint. The locator remains visible in
# every successful gate run so the exception cannot become an invisible bucket.
_NON_ENTRYPOINT_SYS_EXECUTABLE = {
    (
        Path("src/agentkit/harness_client/projectedge/verify_evidence.py"),
        "_run_test",
    )
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One deterministic interpreter-entrypoint finding."""

    path: Path
    line: int
    message: str

    def render(self) -> str:
        """Render a stable repository-relative locator."""
        return f"{self.path.as_posix()}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """One console entrypoint derived from the package declaration."""

    name: str
    path: Path
    function: str


class _SourceAudit(ast.NodeVisitor):
    """Collect forbidden selectors and provenance-backed owner calls."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.function_stack: list[str] = []
        self.command_bindings: list[dict[str, str]] = [{}]
        self.function_definitions: set[str] = set()
        self.owner_function_aliases: dict[str, str] = {}
        self.owner_module_aliases: set[str] = set()
        self.owner_calls_by_function: dict[str, set[str]] = {}
        self.subprocess_module_aliases: set[str] = set()
        self.subprocess_function_aliases: set[str] = set()
        self.sys_module_aliases: set[str] = set()
        self.findings: list[Finding] = []
        self.visible_non_entrypoints: list[Finding] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            if alias.name == "subprocess":
                self.subprocess_module_aliases.add(bound_name)
            elif alias.name == "sys":
                self.sys_module_aliases.add(bound_name)
            elif alias.name == OWNER_MODULE:
                self.owner_module_aliases.add(bound_name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "subprocess":
            for alias in node.names:
                if alias.name in SUBPROCESS_FUNCTIONS:
                    self.subprocess_function_aliases.add(alias.asname or alias.name)
        elif node.module == OWNER_MODULE:
            for alias in node.names:
                if alias.name in OWNER_FUNCTIONS:
                    self.owner_function_aliases[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_definitions.add(node.name)
        self.function_stack.append(node.name)
        self.command_bindings.append({})
        self.generic_visit(node)
        self.command_bindings.pop()
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_definitions.add(node.name)
        self.function_stack.append(node.name)
        self.command_bindings.append({})
        self.generic_visit(node)
        self.command_bindings.pop()
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        bare_name = _bare_python_command(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if bare_name is None:
                    self.command_bindings[-1].pop(target.id, None)
                else:
                    self.command_bindings[-1][target.id] = bare_name
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            bare_name = _bare_python_command(node.value)
            if bare_name is None:
                self.command_bindings[-1].pop(node.target.id, None)
            else:
                self.command_bindings[-1][node.target.id] = bare_name
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        owner_name = self._owner_call_name(node.func)
        if owner_name is not None:
            caller = self.function_stack[-1] if self.function_stack else "<module>"
            self.owner_calls_by_function.setdefault(caller, set()).add(owner_name)
        if self._is_subprocess_call(node.func):
            argument = node.args[0] if node.args else _keyword_value(node, "args")
            bare_name = self._resolved_bare_python_command(argument)
            if bare_name is not None:
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        f"subprocess launches bare {bare_name!r} from PATH",
                    )
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "executable"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.sys_module_aliases
        ):
            function_name = self.function_stack[-1] if self.function_stack else "<module>"
            key = (self.path, function_name)
            finding = Finding(
                self.path,
                node.lineno,
                f"direct sys.executable read in {function_name}()",
            )
            if self.path == INTERPRETER_OWNER:
                pass
            elif key in _NON_ENTRYPOINT_SYS_EXECUTABLE:
                self.visible_non_entrypoints.append(finding)
            else:
                self.findings.append(finding)
        self.generic_visit(node)

    def _owner_call_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self.owner_function_aliases.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.owner_module_aliases
            and node.attr in OWNER_FUNCTIONS
        ):
            return node.attr
        return None

    def _is_subprocess_call(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.subprocess_function_aliases
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.subprocess_module_aliases
            and node.attr in SUBPROCESS_FUNCTIONS
        )

    def _resolved_bare_python_command(self, node: ast.expr | None) -> str | None:
        direct = _bare_python_command(node)
        if direct is not None:
            return direct
        if isinstance(node, ast.Name):
            for scope in reversed(self.command_bindings):
                if node.id in scope:
                    return scope[node.id]
        return None


def _keyword_value(node: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in node.keywords if item.arg == name), None)


def _bare_python_command(node: ast.expr | None) -> str | None:
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        node = node.elts[0]
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    tokens = node.value.strip().split(maxsplit=1)
    if not tokens:
        return None
    candidate = tokens[0]
    return candidate if BARE_PYTHON.fullmatch(candidate) else None


def _declared_entrypoints(root: Path) -> tuple[list[EntryPoint], list[Finding]]:
    declaration = root / "pyproject.toml"
    try:
        payload = tomllib.loads(declaration.read_text(encoding="utf-8"))
        scripts = payload["project"]["scripts"]
        if not isinstance(scripts, dict):
            raise TypeError("project.scripts must be a table")
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        return [], [Finding(Path("pyproject.toml"), 1, f"cannot derive entrypoints: {exc}")]

    entrypoints: list[EntryPoint] = []
    findings: list[Finding] = []
    for name, raw_target in sorted(scripts.items()):
        if not isinstance(name, str) or not isinstance(raw_target, str):
            findings.append(
                Finding(Path("pyproject.toml"), 1, "entrypoint names and targets must be strings")
            )
            continue
        module, separator, function = raw_target.partition(":")
        if not separator or not module or not function:
            findings.append(
                Finding(
                    Path("pyproject.toml"),
                    1,
                    f"entrypoint {name!r} has invalid target {raw_target!r}",
                )
            )
            continue
        path = Path("src") / Path(*module.split("."))
        module_path = path.with_suffix(".py")
        package_path = path / "__init__.py"
        if (root / module_path).is_file():
            resolved_path = module_path
        elif (root / package_path).is_file():
            resolved_path = package_path
        else:
            resolved_path = module_path
        entrypoints.append(EntryPoint(name=name, path=resolved_path, function=function))
    return entrypoints, findings


def _audit_python(root: Path) -> tuple[list[Finding], list[Finding], int]:
    findings: list[Finding] = []
    visible_non_entrypoints: list[Finding] = []
    audits_by_path: dict[Path, _SourceAudit] = {}
    source_root = root / SOURCE_ROOT
    for source_path in sorted(source_root.rglob("*.py")):
        relative = source_path.relative_to(root)
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(relative))
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(Finding(relative, 1, f"cannot audit Python source: {exc}"))
            continue
        audit = _SourceAudit(relative)
        audit.visit(tree)
        findings.extend(audit.findings)
        visible_non_entrypoints.extend(audit.visible_non_entrypoints)
        audits_by_path[relative] = audit

    entrypoints, declaration_findings = _declared_entrypoints(root)
    findings.extend(declaration_findings)
    required_boundaries = [
        EntryPoint(name="installed-package", path=PACKAGE_BOUNDARY, function="_enforce_installed_runtime_isolation"),
        *entrypoints,
    ]
    for entrypoint in required_boundaries:
        audit = audits_by_path.get(entrypoint.path)
        if audit is None:
            findings.append(
                Finding(entrypoint.path, 1, f"declared entrypoint {entrypoint.name!r} is missing")
            )
            continue
        if entrypoint.function not in audit.function_definitions:
            findings.append(
                Finding(
                    entrypoint.path,
                    1,
                    f"declared entrypoint {entrypoint.name!r} has no function {entrypoint.function}()",
                )
            )
        if not audit.owner_calls_by_function.get(entrypoint.function):
            findings.append(
                Finding(
                    entrypoint.path,
                    1,
                    f"entrypoint {entrypoint.name!r} function "
                    f"{entrypoint.function}() does not call an API imported from "
                    f"{OWNER_MODULE}",
                )
            )
    return findings, visible_non_entrypoints, len(entrypoints)


def _audit_bundled_hook(root: Path) -> list[Finding]:
    relative = Path("src/agentkit/bundles/target_project/.claude/settings.json")
    path = root / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        command = payload["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    except (KeyError, IndexError, OSError, TypeError, json.JSONDecodeError) as exc:
        return [Finding(relative, 1, f"cannot audit bundled hook command: {exc}")]
    expected = "__AK3_INTERPRETER__ .agentkit/hooks/pre_tool_use.py"
    if command != expected:
        return [
            Finding(
                relative,
                1,
                f"bundled hook command must be {expected!r}, got {command!r}",
            )
        ]
    return []


def main() -> int:
    """Audit interpreter entrypoints and return zero only for a clean contract."""
    parser = argparse.ArgumentParser(
        description="Check that AK3 entrypoints use the central interpreter owner."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to audit (used by deterministic contract tests).",
    )
    root = parser.parse_args().root.resolve()
    findings, visible_non_entrypoints, entrypoint_count = _audit_python(root)
    findings.extend(_audit_bundled_hook(root))
    for finding in visible_non_entrypoints:
        print(f"[interpreter-entrypoints] INFO: {finding.render()} (not an AK3 entrypoint)")
    if findings:
        for finding in sorted(findings, key=lambda item: (str(item.path), item.line)):
            print(f"[interpreter-entrypoints] ERROR: {finding.render()}", file=sys.stderr)
        print(
            f"[interpreter-entrypoints] FAILED: {len(findings)} violation(s)",
            file=sys.stderr,
        )
        return 1
    print(
        "[interpreter-entrypoints] OK: "
        f"{entrypoint_count} declared entrypoint(s) and the installed-package "
        "boundary use the central interpreter owner"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
