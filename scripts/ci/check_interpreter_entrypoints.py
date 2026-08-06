"""Check that AgentKit entrypoints use the single interpreter owner."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

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
# CPython's generic console selector and the Windows ``py`` launcher form one
# grammar, not an inventory: ``py`` or ``python``, an optional numeric version
# (``3``, ``3.14`` or the compact ``314``), then an optional ``.exe`` suffix.
# Implementation-specific executable families such as ``pypy``, ``jython`` and
# ``micropython`` are deliberately outside this rule: they are not names emitted
# by AK3's CPython/Windows-launcher installation contract, and folding arbitrary
# implementation brands into the prefix would also match non-command data. If AK3
# adds a supported alternative runtime, that runtime needs its own named contract
# rather than an ever-growing alias list here.
_PYTHON_PATH_SELECTOR_NAME = r"(?:py|python)(?:\d+(?:\.\d+)*)?"
_PYTHON_PATH_SELECTOR_TOKEN = rf"{_PYTHON_PATH_SELECTOR_NAME}(?:\.exe)?"
PYTHON_PATH_SELECTOR = re.compile(
    rf"^{_PYTHON_PATH_SELECTOR_TOKEN}$",
    re.IGNORECASE,
)
SKILL_BUNDLE_ROOT = Path("src/agentkit/bundles/skill_bundles")
TARGET_PROJECT_ROOT = Path("src/agentkit/bundles/target_project")
MINIMUM_BUNDLE_VERSION_OWNER = Path(
    "src/agentkit/backend/skills/version_policy.py"
)
FLOOR_POLICY_ROOTS = (Path("concept"), Path("guardrails"))
_FENCE_START = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)$"
)
_SEMANTIC_VERSION = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
_SEMANTIC_VERSION_IN_TEXT = re.compile(
    r"`(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))`"
)
_FLOOR_AUTHORITY_LANGUAGE = re.compile(
    r"(?:Mindest-Konformversion|Mindestversion|produktive(?:n|r)?\s+Grenze|"
    r"produktiv\s+bindbar|unter\s+der\s+produktiven)",
    re.IGNORECASE,
)
_SKILL_FLOOR_CONTEXT = re.compile(
    r"(?:skill|bundle|create-userstory|execute-userstory|concept-incubation)",
    re.IGNORECASE,
)
_SELECTOR_BINDING_NAME = re.compile(
    r"(?:COMMAND|EXECUTABLE|INTERPRETER|PROGRAM|SELECTOR|WRAPPER)",
    re.IGNORECASE,
)
_PYTHON_MODULE_TARGET = re.compile(
    r"(?<![\w-])-m\s+(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
)
_BARE_PYTHON_INSTRUCTION = re.compile(
    rf"(?<![\w./\\-])(?P<selector>{_PYTHON_PATH_SELECTOR_TOKEN})\s+"
    r"(?:-m\s+[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*|"
    r"-[A-Za-z0-9][^\s'\"`]*|"
    r"[A-Za-z0-9_-]+(?:[./\\][A-Za-z0-9_-]+)*\.py)"
    r"(?=$|[\s'\"`.,;:!?)])",
    re.IGNORECASE,
)
_SELECTOR_MENTION = re.compile(
    rf"(?<![\w./\\-])(?:{_PYTHON_PATH_SELECTOR_TOKEN}|"
    r"agentkit(?:-[a-z0-9][a-z0-9-]*)*(?:\.exe)?)\b",
    re.IGNORECASE,
)
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


@dataclass(frozen=True, slots=True)
class _CommandParameter:
    """One positional/keyword location that can select an executable."""

    position: int | None
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProcessApi:
    """One stdlib API through which caller text can select a process image."""

    canonical_name: str
    command_parameters: tuple[_CommandParameter, ...]

    @property
    def label(self) -> str:
        """Return the stable family label used in diagnostics."""
        return self.canonical_name.split(".", maxsplit=1)[0]


def _command_parameter(
    position: int | None,
    *keywords: str,
) -> _CommandParameter:
    return _CommandParameter(position, tuple(keywords))


def _process_api(
    canonical_name: str,
    *parameters: _CommandParameter,
) -> tuple[str, _ProcessApi]:
    return canonical_name, _ProcessApi(canonical_name, tuple(parameters))


# Complete public stdlib inventory whose call receives an external executable or
# shell command from the caller. ``subprocess`` helpers and both asyncio creation
# helpers are included, as are every documented os.exec*, os.spawn*, posix_spawn*,
# shell/startfile entry, pty.spawn, and multiprocessing's child-interpreter setter.
# ``AbstractEventLoop.subprocess_exec/subprocess_shell`` are handled separately
# below because ordinary AST provenance cannot prove an arbitrary loop variable.
# fork/forkpty, multiprocessing.Process/Pool, ProcessPoolExecutor, webbrowser and
# venv are intentionally absent: they create a process but expose no caller-supplied
# external command at the starting call. No control- or data-flow inference is used.
_PROCESS_APIS: dict[str, _ProcessApi] = dict(
    [
        *(
            _process_api(
                f"subprocess.{name}",
                _command_parameter(0, "args"),
                _command_parameter(None, "executable"),
            )
            for name in ("Popen", "call", "check_call", "check_output", "run")
        ),
        *(
            _process_api(
                f"subprocess.{name}",
                _command_parameter(0, "cmd"),
            )
            for name in ("getoutput", "getstatusoutput")
        ),
        _process_api(
            "asyncio.create_subprocess_exec",
            _command_parameter(0, "program"),
            _command_parameter(None, "executable"),
        ),
        _process_api(
            "asyncio.create_subprocess_shell",
            _command_parameter(0, "cmd"),
            _command_parameter(None, "executable"),
        ),
        _process_api(
            "asyncio.subprocess.create_subprocess_exec",
            _command_parameter(0, "program"),
            _command_parameter(None, "executable"),
        ),
        _process_api(
            "asyncio.subprocess.create_subprocess_shell",
            _command_parameter(0, "cmd"),
            _command_parameter(None, "executable"),
        ),
        *(
            _process_api(f"os.{name}", _command_parameter(0, "path"))
            for name in (
                "execl",
                "execle",
                "execlp",
                "execlpe",
                "execv",
                "execve",
                "execvp",
                "execvpe",
                "posix_spawn",
                "posix_spawnp",
            )
        ),
        *(
            _process_api(f"os.{name}", _command_parameter(1, "path"))
            for name in (
                "spawnl",
                "spawnle",
                "spawnlp",
                "spawnlpe",
                "spawnv",
                "spawnve",
                "spawnvp",
                "spawnvpe",
            )
        ),
        _process_api("os.system", _command_parameter(0, "command")),
        _process_api("os.popen", _command_parameter(0, "cmd")),
        _process_api("os.startfile", _command_parameter(0, "path")),
        _process_api("pty.spawn", _command_parameter(0, "argv")),
        _process_api(
            "multiprocessing.set_executable",
            _command_parameter(0, "executable"),
        ),
    ]
)
_PROCESS_MODULES = frozenset(
    canonical_name.split(".", maxsplit=1)[0]
    for canonical_name in _PROCESS_APIS
)
_UNBOUND_PROCESS_METHOD_APIS: dict[str, _ProcessApi] = {
    "set_executable": _ProcessApi(
        "multiprocessing.context.BaseContext.set_executable",
        (_command_parameter(0, "executable"),),
    ),
    "subprocess_exec": _ProcessApi(
        "asyncio.AbstractEventLoop.subprocess_exec",
        (
            _command_parameter(1),
            _command_parameter(None, "executable"),
        ),
    ),
    "subprocess_shell": _ProcessApi(
        "asyncio.AbstractEventLoop.subprocess_shell",
        (
            _command_parameter(1),
            _command_parameter(None, "executable"),
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class SkillBundleAudit:
    """Aggregate result for Markdown surfaces in productive skill bundles."""

    findings: tuple[Finding, ...]
    shipped_bundle_versions: int
    shipped_files: int
    bundle_versions: int
    files: int
    fences: int
    prose_lines: int
    python_modules: int


@dataclass(frozen=True, slots=True)
class _CodeFence:
    """One Markdown code fence represented without interpreting its contents."""

    number: int
    opening_line: int
    text: str

    def line_at(self, offset: int) -> int:
        """Return the source line owning a character in the fence body."""
        return self.opening_line + 1 + self.text[:offset].count("\n")


@dataclass(frozen=True, slots=True)
class _QuoteNormalizedText:
    """Textually normalized shell text with offsets mapped back to raw text."""

    raw: str
    text: str
    raw_offsets: tuple[int, ...]

    def raw_offset(self, normalized_offset: int) -> int:
        """Map a normalized character offset to the original source offset."""
        if normalized_offset < len(self.raw_offsets):
            return self.raw_offsets[normalized_offset]
        return len(self.raw)


def _without_shell_quotes(raw: str) -> _QuoteNormalizedText:
    """Remove quotes/backslashes and join continuations without shell evaluation."""
    retained: list[tuple[str, int]] = []
    offset = 0
    while offset < len(raw):
        character = raw[offset]
        if character in {'"', "'"}:
            offset += 1
            continue
        if character == "\\":
            if raw.startswith("\r\n", offset + 1):
                offset += 3
            elif raw.startswith("\n", offset + 1):
                offset += 2
            else:
                offset += 1
            continue
        retained.append((character, offset))
        offset += 1
    return _QuoteNormalizedText(
        raw=raw,
        text="".join(character for character, _offset in retained),
        raw_offsets=tuple(offset for _character, offset in retained),
    )


_SHELL_EVALUATION_MARKERS = ("$(", "`", "$'")


def _undecidable_shell_evaluation(raw: str) -> tuple[int, str] | None:
    """Return the first marker that makes checked shell text undecidable."""
    candidates = (
        (offset, marker)
        for marker in _SHELL_EVALUATION_MARKERS
        if (offset := raw.find(marker)) >= 0
    )
    return min(candidates, key=lambda item: item[0], default=None)


@dataclass(frozen=True, slots=True)
class _SkillFenceException:
    """One visible non-entrypoint selector mention in a productive fence."""

    path: Path
    fence: int
    raw_text: str
    reason: str


_NON_ENTRYPOINT_SKILL_FENCE_MENTIONS: tuple[_SkillFenceException, ...] = ()


@dataclass(frozen=True, slots=True)
class _SelectorLiteralException:
    """One exact call-argument literal that is data, never an executable selector."""

    path: Path
    line: int
    literal: str
    reason: str


_NON_COMMAND_SELECTOR_LITERALS: tuple[_SelectorLiteralException, ...] = (
    *(
        _SelectorLiteralException(
            Path("src/agentkit/backend/governance/default_hook_definitions.py"),
            line,
            literal,
            "logical Claude hook identifier consumed only by the absolute-wrapper materializer",
        )
        for line, literal in (
            (68, "agentkit-hook-claude pre "),
            (73, "agentkit-hook-claude post "),
            (78, "agentkit-hook-claude post "),
            (83, "agentkit-hook-claude post "),
            (88, "agentkit-hook-claude post "),
            (95, "agentkit-hook-claude pre "),
            (102, "agentkit-hook-claude post "),
            (108, "agentkit-hook-claude pre "),
            (115, "agentkit-hook-claude pre "),
        )
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/installer/codex_settings.py"),
        44,
        "agentkit-hook-codex",
        "wrapper identity passed to the central absolute-wrapper renderer",
    ),
    *(
        _SelectorLiteralException(
            Path("src/agentkit/backend/installer/lifecycle/detach.py"),
            148,
            literal,
            "parser vocabulary that recognizes current absolute interpreter-bound "
            "script hooks by basename and older bare hook text; never launches it",
        )
        for literal in ("python", "python3", "python.exe", "python3.exe")
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/installer/runner.py"),
        1431,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/pipeline_engine/phase_executor/models.py"),
        466,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/project_management/http/routes.py"),
        408,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/project_management/http/routes.py"),
        533,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/project_management/lifecycle.py"),
        76,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/project_management/lifecycle.py"),
        105,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/backend/story/service.py"),
        56,
        "python",
        "Pydantic serialization mode",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/claude_code.py"),
        184,
        "agentkit-hook-claude",
        "parser command-name label",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/claude_code.py"),
        275,
        "agentkit-hook-claude",
        "wrapper identity passed to the central absolute-wrapper renderer",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/codex/cli.py"),
        62,
        "agentkit-hook-codex",
        "parser command-name label",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/settings_writer.py"),
        112,
        "agentkit-hook-claude",
        "wrapper identity passed to the harness absolute-wrapper materializer",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/settings_writer.py"),
        443,
        "agentkit-hook-codex",
        "wrapper identity passed to the harness absolute-wrapper materializer",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/settings_writer.py"),
        310,
        r"^agentkit-hook-claude (?P<phase>\S+) (?P<hook_id>\S+)$",
        "logical hook-command validation pattern, never an executable command",
    ),
    _SelectorLiteralException(
        Path("src/agentkit/harness_client/harness_adapters/settings_writer.py"),
        458,
        ": expected exactly 'agentkit-hook-claude {phase} {hook_id}'. Fail-closed: refusing to write an "
        "unrecognised command to the ",
        "validation error text describing the logical hook identifier",
    ),
)


@dataclass(frozen=True, slots=True)
class _RenderedText:
    """Statically composed source text with line ownership per fragment."""

    fragments: tuple[tuple[str, int], ...]
    dynamic_lines: tuple[int, ...] = ()
    dynamic_selectors: tuple[tuple[str, int], ...] = ()
    raw_text: str | None = None

    @property
    def text(self) -> str:
        """Return the runtime text represented by the static fragments."""
        return "".join(fragment for fragment, _line in self.fragments)

    def line_at(self, offset: int) -> int:
        """Return the source line owning the character at ``offset``."""
        consumed = 0
        for fragment, line in self.fragments:
            boundary = consumed + len(fragment)
            if offset < boundary:
                return line + fragment[: offset - consumed].count("\n")
            consumed = boundary
        return self.fragments[-1][1] if self.fragments else 1


@dataclass(frozen=True, slots=True)
class _StaticTextEnvironment:
    """Bounded per-scope constant-string environment for one Python AST."""

    bindings_by_scope: dict[ast.AST, dict[str, _RenderedText]]
    assignments_by_scope: dict[ast.AST, dict[str, ast.AST]]
    discarded_assignments_by_scope: dict[
        ast.AST,
        dict[str, tuple[tuple[ast.stmt, ast.AST], ...]],
    ]
    scope_by_node: dict[ast.AST, ast.AST]

    def bindings_for(self, node: ast.AST) -> dict[str, _RenderedText]:
        """Return the safely resolved constants visible at ``node``."""
        return self.bindings_by_scope.get(self.scope_by_node[node], {})

    def assignment_for(self, node: ast.Name) -> ast.AST | None:
        """Return a unique local assignment expression visible at ``node``."""
        return self.assignments_by_scope.get(self.scope_by_node[node], {}).get(
            node.id
        )

    def module_assignment_for(self, node: ast.Name) -> ast.AST | None:
        """Return the unique direct assignment for ``node`` in this module."""
        module_scope = next(
            (
                scope
                for scope in self.assignments_by_scope
                if isinstance(scope, ast.Module)
            ),
            None,
        )
        if module_scope is None:
            return None
        return self.assignments_by_scope[module_scope].get(node.id)

    def discarded_assignments_for(
        self,
        node: ast.Name,
    ) -> tuple[tuple[ast.stmt, ast.AST], ...]:
        """Return unsafe candidate assignments kept for fail-closed auditing."""
        return self.discarded_assignments_by_scope.get(
            self.scope_by_node[node], {}
        ).get(node.id, ())


class _FunctionBindingCollector(ast.NodeVisitor):
    """Collect names bound in one function without entering nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(
            alias.asname or alias.name.split(".", maxsplit=1)[0]
            for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass


class BundleVersionAssessor(Protocol):
    """Callable contract exported by the agent-skills version-policy owner."""

    def __call__(
        self,
        bundle_id: str,
        bundle_version: str,
    ) -> tuple[str | None, bool, bool]:
        """Return minimum version, comparability, and conformance."""


@dataclass(slots=True)
class _SubprocessScopeBindings:
    """All bindings relevant to process-API provenance in one lexical scope."""

    imports: dict[str, list[tuple[str, ast.AST]]]
    aliases: dict[str, list[tuple[ast.expr, ast.AST]]]
    rebindings: dict[str, list[ast.AST]]


@dataclass(frozen=True, slots=True)
class _ProcessCallResolution:
    """Flow-insensitive provenance and candidate APIs for one call target."""

    provenance: str
    apis: tuple[_ProcessApi, ...]


@dataclass(frozen=True, slots=True)
class _SubprocessBindingInventory:
    """Flow-insensitive stdlib process-API inventory for one Python module."""

    bindings_by_scope: dict[ast.AST, _SubprocessScopeBindings]
    scope_by_node: dict[ast.AST, ast.AST]
    parent_by_scope: dict[ast.AST, ast.AST | None]

    def provenance_for(self, node: ast.expr) -> _ProcessCallResolution:
        """Resolve a call target without interpreting execution order or branches."""
        origins, uncertain = self._origins_for_expression(node, frozenset())
        apis = tuple(
            _PROCESS_APIS[origin]
            for origin in sorted(origins)
            if origin in _PROCESS_APIS
        )
        if apis:
            provenance = "undecidable" if uncertain or len(apis) != 1 else "stdlib"
            return _ProcessCallResolution(provenance, apis)
        if isinstance(node, ast.Attribute) and node.attr in _UNBOUND_PROCESS_METHOD_APIS:
            return _ProcessCallResolution(
                "undecidable",
                (_UNBOUND_PROCESS_METHOD_APIS[node.attr],),
            )
        return _ProcessCallResolution("unrelated", ())

    def _origins_for_expression(
        self,
        node: ast.expr,
        seen: frozenset[tuple[ast.AST, str]],
    ) -> tuple[set[str], bool]:
        if isinstance(node, ast.Name):
            return self._origins_for_name(
                node.id,
                self.scope_by_node[node],
                seen,
            )
        attribute = _attribute_path(node)
        if attribute is None:
            return set(), False
        root_name, suffix = attribute
        root_origins, uncertain = self._origins_for_name(
            root_name,
            self.scope_by_node[node],
            seen,
        )
        return {
            f"{origin}.{suffix}"
            for origin in root_origins
            if origin in _PROCESS_MODULES
            or any(
                canonical_name.startswith(f"{origin}.")
                for canonical_name in _PROCESS_APIS
            )
        }, uncertain

    def _origins_for_name(
        self,
        name: str,
        scope: ast.AST,
        seen: frozenset[tuple[ast.AST, str]],
    ) -> tuple[set[str], bool]:
        key = (scope, name)
        if key in seen:
            return set(), True
        next_seen = seen | {key}
        origins: set[str] = set()
        binding_count = 0
        unknown_binding = False
        current: ast.AST | None = scope
        while current is not None:
            bindings = self.bindings_by_scope[current]
            imported = bindings.imports.get(name, ())
            aliases = bindings.aliases.get(name, ())
            rebound = bindings.rebindings.get(name, ())
            binding_count += len(imported) + len(aliases) + len(rebound)
            origins.update(origin for origin, _node in imported)
            unknown_binding = unknown_binding or bool(rebound)
            for expression, _node in aliases:
                alias_origins, alias_uncertain = self._origins_for_expression(
                    expression,
                    next_seen,
                )
                origins.update(alias_origins)
                unknown_binding = unknown_binding or alias_uncertain or not alias_origins
            current = self.parent_by_scope[current]
        return origins, unknown_binding or binding_count != 1


def _attribute_path(node: ast.expr) -> tuple[str, str] | None:
    """Return ``(bound root, dotted suffix)`` for a plain attribute chain."""
    attributes: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name) or not attributes:
        return None
    return current.id, ".".join(reversed(attributes))


class _SubprocessBindingCollector(ast.NodeVisitor):
    """Inventory imports and rebindings without interpreting control flow."""

    def __init__(self, tree: ast.Module) -> None:
        self.scope_stack: list[ast.AST] = [tree]
        self.bindings_by_scope: dict[ast.AST, _SubprocessScopeBindings] = {
            tree: _SubprocessScopeBindings({}, {}, {})
        }
        self.scope_by_node: dict[ast.AST, ast.AST] = {}
        self.parent_by_scope: dict[ast.AST, ast.AST | None] = {tree: None}

    @property
    def _scope(self) -> ast.AST:
        return self.scope_stack[-1]

    def visit(self, node: ast.AST) -> None:
        self.scope_by_node[node] = self._scope
        super().visit(node)

    def _record_import(self, name: str, kind: str, node: ast.AST) -> None:
        self.bindings_by_scope[self._scope].imports.setdefault(name, []).append(
            (kind, node)
        )

    def _record_rebinding(self, name: str, node: ast.AST) -> None:
        self.bindings_by_scope[self._scope].rebindings.setdefault(name, []).append(
            node
        )

    def _record_alias(self, name: str, value: ast.expr, node: ast.AST) -> None:
        self.bindings_by_scope[self._scope].aliases.setdefault(name, []).append(
            (value, node)
        )

    def _record_rebinding_in_scope(
        self,
        scope: ast.AST,
        name: str,
        node: ast.AST,
    ) -> None:
        self.bindings_by_scope[scope].rebindings.setdefault(name, []).append(node)

    def _push_scope(self, scope: ast.AST, *, skip_classes: bool) -> None:
        parent = self._scope
        if skip_classes:
            for candidate in reversed(self.scope_stack):
                if not isinstance(candidate, ast.ClassDef):
                    parent = candidate
                    break
        self.parent_by_scope[scope] = parent
        self.bindings_by_scope[scope] = _SubprocessScopeBindings({}, {}, {})
        self.scope_stack.append(scope)

    def _visit_arguments_in_parent(self, arguments: ast.arguments) -> None:
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if arguments.vararg is not None and arguments.vararg.annotation is not None:
            self.visit(arguments.vararg.annotation)
        if arguments.kwarg is not None and arguments.kwarg.annotation is not None:
            self.visit(arguments.kwarg.annotation)
        for default in (*arguments.defaults, *arguments.kw_defaults):
            if default is not None:
                self.visit(default)

    def _record_parameters(self, arguments: ast.arguments) -> None:
        parameters = [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ]
        if arguments.vararg is not None:
            parameters.append(arguments.vararg)
        if arguments.kwarg is not None:
            parameters.append(arguments.kwarg)
        for parameter in parameters:
            self._record_rebinding(parameter.arg, parameter)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            module = alias.name if alias.asname else alias.name.split(".", maxsplit=1)[0]
            if module in _PROCESS_MODULES or any(
                canonical_name.startswith(f"{module}.")
                for canonical_name in _PROCESS_APIS
            ):
                self._record_import(name, module, node)
            else:
                self._record_rebinding(name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            canonical_name = f"{node.module}.{alias.name}"
            if canonical_name in _PROCESS_APIS:
                self._record_import(name, canonical_name, node)
            else:
                self._record_rebinding(name, node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.scope_by_node[target] = self._scope
            if isinstance(target, ast.Name):
                self._record_alias(target.id, node.value, target)
            else:
                self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.scope_by_node[node.target] = self._scope
        if isinstance(node.target, ast.Name) and node.value is not None:
            self._record_alias(node.target.id, node.value, node.target)
        else:
            self.visit(node.target)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._record_rebinding(node.name, node)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arguments_in_parent(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self._push_scope(node, skip_classes=True)
        self._record_parameters(node.args)
        for statement in node.body:
            self.visit(statement)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record_rebinding(node.name, node)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._push_scope(node, skip_classes=False)
        for statement in node.body:
            self.visit(statement)
        self.scope_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arguments_in_parent(node.args)
        self._push_scope(node, skip_classes=True)
        self._record_parameters(node.args)
        self.visit(node.body)
        self.scope_stack.pop()

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
        results: tuple[ast.expr, ...],
    ) -> None:
        first, *remaining = node.generators
        self.visit(first.iter)
        self._push_scope(node, skip_classes=True)
        self.visit(first.target)
        for condition in first.ifs:
            self.visit(condition)
        for generator in remaining:
            self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for result in results:
            self.visit(result)
        self.scope_stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, (node.key, node.value))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record_rebinding(node.id, node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.scope_by_node[node.target] = self._scope
        if isinstance(
            self._scope,
            (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp),
        ):
            parent = self.parent_by_scope[self._scope]
            if parent is not None:
                self.bindings_by_scope[parent].aliases.setdefault(
                    node.target.id, []
                ).append((node.value, node.target))
                return
        self._record_alias(node.target.id, node.value, node.target)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self._record_rebinding(name, node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            self._record_rebinding(name, node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._record_rebinding(node.name, node)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self._record_rebinding(node.name, node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._record_rebinding(node.name, node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self._record_rebinding(node.rest, node)


def _subprocess_binding_inventory(tree: ast.Module) -> _SubprocessBindingInventory:
    """Build the flow-insensitive subprocess binding inventory for ``tree``."""
    collector = _SubprocessBindingCollector(tree)
    collector.visit(tree)
    return _SubprocessBindingInventory(
        collector.bindings_by_scope,
        collector.scope_by_node,
        collector.parent_by_scope,
    )


class _ArgumentLiteralCollector(ast.NodeVisitor):
    """Collect string literals in one argument while leaving nested calls separate."""

    def __init__(self) -> None:
        self.literals: list[ast.Constant] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Let the main source visitor audit a nested call as its own boundary."""

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (str, bytes)):
            self.literals.append(node)


def _string_literals_without_nested_calls(node: ast.expr) -> tuple[ast.Constant, ...]:
    collector = _ArgumentLiteralCollector()
    collector.visit(node)
    return tuple(collector.literals)


class _SourceAudit(ast.NodeVisitor):
    """Collect forbidden selectors and provenance-backed owner calls."""

    def __init__(
        self,
        path: Path,
        *,
        source: str,
        selector_names: frozenset[str],
        text_environment: _StaticTextEnvironment,
        subprocess_bindings: _SubprocessBindingInventory,
    ) -> None:
        self.path = path
        self.source = source
        self.selector_names = selector_names
        self.selector_pattern = _skill_selector_pattern(selector_names)
        self.text_environment = text_environment
        self.subprocess_bindings = subprocess_bindings
        self.function_stack: list[str | None] = []
        self.scope_depth = 0
        self.function_definitions: set[str] = set()
        self.owner_function_aliases: list[dict[str, str]] = [{}]
        self.owner_module_aliases: list[set[str]] = [set()]
        self.bound_names: list[set[str]] = [set()]
        self.owner_calls_by_function: dict[str, set[str]] = {}
        self.sys_module_aliases: set[str] = set()
        self.findings: list[Finding] = []
        self.visible_non_entrypoints: list[Finding] = []
        self.matched_selector_exceptions: set[_SelectorLiteralException] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            self.bound_names[-1].add(bound_name)
            if alias.name == "sys":
                self.sys_module_aliases.add(bound_name)
            elif alias.name == OWNER_MODULE:
                self.owner_module_aliases[-1].add(bound_name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        imported_names = {alias.asname or alias.name for alias in node.names}
        self.bound_names[-1].update(imported_names)
        if node.module == OWNER_MODULE:
            for alias in node.names:
                self.bound_names[-1].add(alias.asname or alias.name)
                if alias.name in OWNER_FUNCTIONS:
                    self.owner_function_aliases[-1][alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.function_stack.append(None)
        try:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self._audit_selector_literals(
                        default,
                        context="callable default",
                        raw_owner=default,
                    )
                    self.visit(default)
            if node.returns is not None:
                self.visit(node.returns)
        finally:
            self.function_stack.pop()
        module_level = self.scope_depth == 0
        self.bound_names[-1].add(node.name)
        if module_level:
            self.function_definitions.add(node.name)
        self.scope_depth += 1
        self.function_stack.append(node.name if module_level else None)
        self.owner_function_aliases.append({})
        self.owner_module_aliases.append(set())
        arguments = (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
        bound = {argument.arg for argument in arguments}
        if node.args.vararg is not None:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            bound.add(node.args.kwarg.arg)
        binding_collector = _FunctionBindingCollector()
        for statement in node.body:
            binding_collector.visit(statement)
        bound.update(binding_collector.names)
        self.bound_names.append(bound)
        for statement in node.body:
            self.visit(statement)
        self.bound_names.pop()
        self.owner_module_aliases.pop()
        self.owner_function_aliases.pop()
        self.function_stack.pop()
        self.scope_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound_names[-1].add(node.name)
        self.scope_depth += 1
        self.owner_function_aliases.append({})
        self.owner_module_aliases.append(set())
        self.bound_names.append(set())
        self.generic_visit(node)
        self.bound_names.pop()
        self.owner_module_aliases.pop()
        self.owner_function_aliases.pop()
        self.scope_depth -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self._audit_selector_literals(
                    default,
                    context="callable default",
                    raw_owner=default,
                )
                self.visit(default)
        self.function_stack.append(None)
        self.owner_function_aliases.append({})
        self.owner_module_aliases.append(set())
        bound = {
            argument.arg
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
        }
        if node.args.vararg is not None:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            bound.add(node.args.kwarg.arg)
        self.bound_names.append(bound)
        self.visit(node.body)
        self.bound_names.pop()
        self.owner_module_aliases.pop()
        self.owner_function_aliases.pop()
        self.function_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.bound_names[-1].add(target.id)
            self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.bound_names[-1].add(node.target.id)
        self.visit(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.visit(node.target)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.bound_names[-1].add(node.id)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, (node.key, node.value))

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
        results: tuple[ast.expr, ...],
    ) -> None:
        """Visit a comprehension in its implicit function-like scope."""
        first, *remaining = node.generators
        self.visit(first.iter)
        bound = {
            candidate.id
            for generator in node.generators
            for candidate in ast.walk(generator.target)
            if isinstance(candidate, ast.Name)
        }
        self.function_stack.append(None)
        self.owner_function_aliases.append({})
        self.owner_module_aliases.append(set())
        self.bound_names.append(bound)
        self.visit(first.target)
        for condition in first.ifs:
            self.visit(condition)
        for generator in remaining:
            self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for result in results:
            self.visit(result)
        self.bound_names.pop()
        self.owner_module_aliases.pop()
        self.owner_function_aliases.pop()
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
            self._audit_selector_literals(
                argument,
                context="call argument",
                raw_owner=node,
            )
        owner_name = self._owner_call_name(node.func)
        if owner_name is not None:
            caller = self.function_stack[-1] if self.function_stack else "<module>"
            if caller is not None:
                self.owner_calls_by_function.setdefault(caller, set()).add(owner_name)
        process_resolution = self.subprocess_bindings.provenance_for(node.func)
        if process_resolution.provenance != "unrelated":
            audited_expressions: set[int] = set()
            for api in process_resolution.apis:
                for parameter in api.command_parameters:
                    argument = _call_parameter_value(node, parameter)
                    if argument is None or id(argument) in audited_expressions:
                        continue
                    audited_expressions.add(id(argument))
                    self._audit_process_command(
                        node,
                        argument,
                        api=api,
                        provenance=process_resolution.provenance,
                    )
        self.generic_visit(node)

    def _audit_selector_literals(
        self,
        node: ast.expr,
        *,
        context: str,
        raw_owner: ast.AST,
    ) -> None:
        """Reject selector words without resolving the receiving callable."""
        if isinstance(node, ast.Name):
            assigned = self.text_environment.module_assignment_for(node)
            if isinstance(assigned, ast.Constant) and isinstance(
                assigned.value, (str, bytes)
            ):
                node = assigned
                raw_owner = assigned
            elif isinstance(assigned, ast.Name) and _SELECTOR_BINDING_NAME.search(
                node.id
            ):
                self.findings.append(
                    Finding(
                        self.path,
                        node.lineno,
                        f"undecidable {context} name {node.id!r} does not resolve "
                        "in one module-constant step; raw text: "
                        f"{_raw_ast_text(self.source, raw_owner)!r}",
                    )
                )
                return
        literal_selector_names = self.selector_names - {"agentkit"}
        for literal in _string_literals_without_nested_calls(node):
            selector = _forbidden_literal_selector(
                literal.value,
                literal_selector_names,
            )
            if selector is None:
                continue
            exception = next(
                (
                    candidate
                    for candidate in _NON_COMMAND_SELECTOR_LITERALS
                    if candidate.path == self.path
                    and candidate.line == literal.lineno
                    and candidate.literal == literal.value
                ),
                None,
            )
            if exception is not None:
                self.matched_selector_exceptions.add(exception)
                self.visible_non_entrypoints.append(
                    Finding(
                        self.path,
                        literal.lineno,
                        f"selector literal {literal.value!r} is non-command data: "
                        f"{exception.reason}",
                    )
                )
                continue
            self.findings.append(
                Finding(
                    self.path,
                    literal.lineno,
                    f"{context} contains forbidden selector literal {selector!r} "
                    "independent of callable provenance; raw text: "
                    f"{_raw_ast_text(self.source, raw_owner)!r}",
                )
            )

    def _audit_process_command(
        self,
        call: ast.Call,
        argument: ast.expr,
        *,
        api: _ProcessApi,
        provenance: str,
    ) -> None:
        """Audit one statically identified executable/shell-command argument."""
        command = _subprocess_command_expression(argument)
        if isinstance(command, ast.Name):
            assigned = self.text_environment.assignment_for(command)
            if assigned is not None:
                command = _subprocess_command_expression(assigned)
            else:
                for assignment, value in (
                    self.text_environment.discarded_assignments_for(command)
                ):
                    raw_assignment = _raw_ast_text(self.source, assignment)
                    match = self.selector_pattern.search(
                        _raw_ast_text(self.source, value)
                    )
                    if match is not None:
                        self.findings.append(
                            Finding(
                                self.path,
                                assignment.lineno,
                                f"undecidable {api.label} command binding contains "
                                f"selector {match.group(0)!r}; raw assignment: "
                                f"{raw_assignment!r}",
                            )
                        )
        rendered = (
            None
            if command is None
            else _render_static_text(
                command,
                self.text_environment.bindings_for(command),
            )
        )
        selector = (
            None
            if rendered is None or rendered.dynamic_lines
            else _forbidden_command_selector(rendered.text, self.selector_names)
        )
        if selector is not None:
            message = (
                f"undecidable {api.label} call provenance may launch bare "
                f"{selector!r} from PATH; raw call: "
                f"{_raw_ast_text(self.source, call)!r}"
                if provenance == "undecidable"
                else f"{api.label} launches bare {selector!r} from PATH"
            )
            self.findings.append(
                Finding(
                    self.path,
                    call.lineno,
                    message,
                )
            )
        elif command is not None and (
            (rendered is not None and rendered.dynamic_lines)
            or (
                rendered is None
                and not isinstance(command, ast.Name)
                and self.selector_pattern.search(
                    _raw_ast_text(self.source, command)
                )
            )
        ):
            mentions = (
                [
                    match.group(0)
                    for match in self.selector_pattern.finditer(
                        _raw_ast_text(self.source, command)
                    )
                ]
                if rendered is None
                else [
                    match.group(0)
                    for fragment, _line in rendered.fragments
                    for match in self.selector_pattern.finditer(fragment)
                ]
            )
            if mentions:
                raw_text = _raw_ast_text(self.source, command)
                self.findings.append(
                    Finding(
                        self.path,
                        command.lineno,
                        f"undecidable {api.label} command expression combines "
                        f"selector {mentions[0]!r} with dynamic content; "
                        f"raw text: {raw_text!r}",
                    )
                )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "executable"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.sys_module_aliases
        ):
            function_name = self.function_stack[-1] if self.function_stack else "<module>"
            if function_name is None:
                function_name = "<nested>"
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
            for aliases, bound in zip(
                reversed(self.owner_function_aliases),
                reversed(self.bound_names),
                strict=True,
            ):
                if node.id in aliases:
                    return aliases[node.id]
                if node.id in bound:
                    return None
            return None
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.attr in OWNER_FUNCTIONS
        ):
            for aliases, bound in zip(
                reversed(self.owner_module_aliases),
                reversed(self.bound_names),
                strict=True,
            ):
                if node.value.id in aliases:
                    return node.attr
                if node.value.id in bound:
                    return None
        return None

def _keyword_value(node: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in node.keywords if item.arg == name), None)


def _call_parameter_value(
    node: ast.Call,
    parameter: _CommandParameter,
) -> ast.expr | None:
    """Return one process selector argument without guessing call semantics."""
    if parameter.position is not None and len(node.args) > parameter.position:
        return node.args[parameter.position]
    for keyword in parameter.keywords:
        value = _keyword_value(node, keyword)
        if value is not None:
            return value
    return None


def _subprocess_command_expression(node: ast.expr | None) -> ast.expr | None:
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        return node.elts[0]
    return node


def _forbidden_command_selector(
    command: str,
    selector_names: frozenset[str],
) -> str | None:
    """Return a forbidden PATH selector when ``command`` starts with one."""
    tokens = command.strip().split(maxsplit=1)
    if not tokens:
        return None
    candidate = tokens[0]
    if PYTHON_PATH_SELECTOR.fullmatch(candidate):
        return candidate
    normalized = candidate.casefold()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    if normalized not in selector_names:
        return None
    return candidate


def _forbidden_literal_selector(
    value: str | bytes,
    selector_names: frozenset[str],
) -> str | None:
    """Return any naked selector word, including Windows suffixes."""
    if isinstance(value, bytes):
        try:
            text = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    else:
        text = value
    named_alternatives = "|".join(
        re.escape(selector)
        for selector in sorted(selector_names, key=lambda item: (-len(item), item))
    )
    alternatives = (
        _PYTHON_PATH_SELECTOR_TOKEN
        if not named_alternatives
        else rf"{_PYTHON_PATH_SELECTOR_TOKEN}|{named_alternatives}(?:\.exe)?"
    )
    pattern = re.compile(
        rf"(?<![\w-])(?P<selector>(?:{alternatives}))(?![\w-])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        if match.start() > 0 and text[match.start() - 1] in "./\\":
            continue
        if match.end() < len(text) and text[match.end()] in "./\\":
            continue
        selector = match.group("selector")
        if PYTHON_PATH_SELECTOR.fullmatch(selector):
            stripped = text.strip()
            if PYTHON_PATH_SELECTOR.fullmatch(stripped):
                return selector
            suffix = text[match.end() :]
            if not re.match(
                r"\s+(?:-[A-Za-z0-9][^\s'\"`]*|[A-Za-z0-9_./\\-]+\.py)",
                suffix,
            ):
                # ``Python runtime version`` and similar prose are data, not a
                # PATH selector. The generic call/default audit still rejects
                # an exact selector and command-shaped ``python -V`` text.
                continue
        return selector
    return None


def _raw_ast_text(source: str, node: ast.AST) -> str:
    """Return stable raw source text for an undecidable expression."""
    return ast.get_source_segment(source, node) or ast.unparse(node)


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
    if not scripts:
        findings.append(
            Finding(
                Path("pyproject.toml"),
                1,
                "project.scripts must declare at least one entrypoint",
            )
        )
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


def _audit_python_version_source(root: Path) -> list[Finding]:
    """Reject tool-specific Python targets that override ``requires-python``."""
    declaration = root / "pyproject.toml"
    try:
        payload = tomllib.loads(declaration.read_text(encoding="utf-8"))
        project = payload["project"]
        if not isinstance(project, dict) or not isinstance(
            project.get("requires-python"), str
        ):
            raise TypeError("project.requires-python must be a string")
        tool = payload.get("tool", {})
        if not isinstance(tool, dict):
            raise TypeError("tool must be a table")
        ruff = tool.get("ruff", {})
        if not isinstance(ruff, dict):
            raise TypeError("tool.ruff must be a table")
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        return [Finding(Path("pyproject.toml"), 1, f"cannot derive Python version source: {exc}")]
    if "target-version" in ruff:
        return [
            Finding(
                Path("pyproject.toml"),
                1,
                "tool.ruff.target-version duplicates and overrides "
                "project.requires-python; Ruff must derive the target",
            )
        ]
    return []


def _bundle_version_policy(
    root: Path,
) -> tuple[dict[str, str], BundleVersionAssessor | None, list[Finding]]:
    """Load floor data and comparison rule from the agent-skills owner."""
    relative = MINIMUM_BUNDLE_VERSION_OWNER
    module_name = "_agentkit_checked_skill_version_policy"
    try:
        spec = importlib.util.spec_from_file_location(module_name, root / relative)
        if spec is None or spec.loader is None:
            raise ImportError("cannot create module specification")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any owner-load failure must fail closed
        return {}, None, [
            Finding(relative, 1, f"cannot load skill bundle version policy: {exc}")
        ]
    finally:
        sys.modules.pop(module_name, None)
    floors = getattr(module, "MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS", None)
    assessor = getattr(module, "assess_bundle_version", None)
    if not isinstance(floors, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in floors.items()
    ):
        return {}, None, [
            Finding(relative, 1, "skill bundle version floors must be str -> str")
        ]
    if not callable(assessor):
        return floors, None, [
            Finding(relative, 1, "skill bundle version comparison rule is missing")
        ]
    return floors, assessor, []


def _validate_bundle_version_floors(
    floors: dict[str, str],
    assessor: BundleVersionAssessor | None,
) -> list[Finding]:
    """Validate that every declared floor satisfies its owner's own rule."""
    findings: list[Finding] = []
    for bundle_id, floor in floors.items():
        try:
            assessed_floor, comparable, conform = (
                assessor(bundle_id, floor)
                if assessor is not None
                else (None, False, False)
            )
        except (TypeError, ValueError) as exc:
            findings.append(
                Finding(
                    MINIMUM_BUNDLE_VERSION_OWNER,
                    1,
                    f"invalid minimum bundle version {bundle_id}@{floor}: {exc}",
                )
            )
            continue
        if assessed_floor != floor or not comparable or not conform:
            findings.append(
                Finding(
                    MINIMUM_BUNDLE_VERSION_OWNER,
                    1,
                    f"invalid minimum bundle version {bundle_id}@{floor}",
                )
            )
    return findings


def _audit_concept_floor_authority(root: Path) -> list[Finding]:
    """Reject numeric floor authority outside the agent-skills code owner."""
    findings: list[Finding] = []
    policy_paths = sorted(
        path
        for relative_root in FLOOR_POLICY_ROOTS
        if (policy_root := root / relative_root).is_dir()
        for path in policy_root.rglob("*.md")
    )
    for path in policy_paths:
        relative = path.relative_to(root)
        lines = path.read_text(encoding="utf-8").splitlines()
        paragraph_start = 1
        paragraph: list[str] = []
        for line_number, line in enumerate((*lines, ""), start=1):
            if line.strip():
                if not paragraph:
                    paragraph_start = line_number
                paragraph.append(line)
                continue
            text = "\n".join(paragraph)
            if (
                _FLOOR_AUTHORITY_LANGUAGE.search(text)
                and _SKILL_FLOOR_CONTEXT.search(text)
                and (
                version_match := _SEMANTIC_VERSION_IN_TEXT.search(text)
                )
            ):
                findings.append(
                    Finding(
                        relative,
                        paragraph_start + text[: version_match.start()].count("\n"),
                        "numeric skill-bundle floor authority is duplicated outside "
                        f"{MINIMUM_BUNDLE_VERSION_OWNER.as_posix()}: "
                        f"{version_match.group('version')!r}",
                    )
                )
            paragraph = []
    return findings


def _productive_skill_bundle_versions(
    root: Path,
) -> tuple[list[Path], list[Finding]]:
    """Return bundle versions the installer may bind under its current floors."""
    floors, assessor, findings = _bundle_version_policy(root)
    bundle_root = root / SKILL_BUNDLE_ROOT
    if not bundle_root.is_dir():
        return [], [*findings, Finding(SKILL_BUNDLE_ROOT, 1, "skill bundle store is missing")]
    findings.extend(_validate_bundle_version_floors(floors, assessor))

    productive: list[Path] = []
    productive_bundle_ids: set[str] = set()
    for bundle_dir in sorted(path for path in bundle_root.iterdir() if path.is_dir()):
        for version_dir in sorted(path for path in bundle_dir.iterdir() if path.is_dir()):
            relative = version_dir.relative_to(root)
            if _SEMANTIC_VERSION.fullmatch(version_dir.name) is None:
                findings.append(Finding(relative, 1, "bundle directory is not a semantic version"))
                continue
            if assessor is None:
                continue
            try:
                floor, comparable, conform = assessor(
                    bundle_dir.name,
                    version_dir.name,
                )
            except (TypeError, ValueError) as exc:
                findings.append(
                    Finding(relative, 1, f"cannot assess productive bundle version: {exc}")
                )
                continue
            if not comparable:
                findings.append(
                    Finding(relative, 1, "bundle version is not comparable to its minimum")
                )
                continue
            # Immutable history stays visible in the shipped counters, while the
            # content audit follows only versions eligible at the productive
            # Skills binding points. This exclusion is safe only while every
            # link-creating API enforces the same owner floor before binding.
            if floor is not None and not conform:
                continue
            manifest_path = version_dir / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise TypeError("manifest root must be an object")
                if manifest.get("bundle_id") != bundle_dir.name:
                    raise ValueError("manifest bundle_id does not match its directory")
                if manifest.get("bundle_version") != version_dir.name:
                    raise ValueError("manifest bundle_version does not match its directory")
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                findings.append(Finding(relative / "manifest.json", 1, f"cannot audit productive bundle: {exc}"))
                continue
            productive.append(version_dir)
            productive_bundle_ids.add(bundle_dir.name)
    for bundle_id, floor in floors.items():
        if bundle_id not in productive_bundle_ids:
            findings.append(
                Finding(
                    SKILL_BUNDLE_ROOT / bundle_id,
                    1,
                    f"no valid productive bundle version satisfies minimum {floor}",
                )
            )
    return productive, findings


def _iter_code_fences(markdown: str) -> list[_CodeFence]:
    """Return Markdown fence bodies without interpreting their contents."""
    fences: list[_CodeFence] = []
    active_marker: str | None = None
    opening_line = 0
    body: list[str] = []
    for line_number, line in enumerate(markdown.splitlines(keepends=True), start=1):
        logical_line = line.rstrip("\r\n")
        if active_marker is None:
            match = _FENCE_START.fullmatch(logical_line)
            if match is None:
                continue
            marker = match.group("fence")
            if marker.startswith("`") and "`" in match.group("info"):
                continue
            active_marker = marker
            opening_line = line_number
            body = []
            continue
        marker_character = re.escape(active_marker[0])
        if re.fullmatch(
            rf"[ \t]{{0,3}}{marker_character}{{{len(active_marker)},}}[ \t]*",
            logical_line,
        ):
            fences.append(
                _CodeFence(
                    number=len(fences) + 1,
                    opening_line=opening_line,
                    text="".join(body),
                )
            )
            active_marker = None
            body = []
            continue
        body.append(line)
    if active_marker is not None:
        fences.append(
            _CodeFence(
                number=len(fences) + 1,
                opening_line=opening_line,
                text="".join(body),
            )
        )
    return fences


def _skill_selector_pattern(wrapper_names: frozenset[str]) -> re.Pattern[str]:
    """Build the forbidden selector inventory for productive fences.

    A selector followed immediately by ``.``, ``/``, or ``\\`` is a module or
    path segment. A preceding separator alone does not exempt the selector, so
    relative executable invocations such as ``./agentkit`` remain findings.
    """
    wrapper_alternatives = "|".join(
        rf"{re.escape(selector)}(?:\.exe)?"
        for selector in sorted(wrapper_names, key=lambda value: (-len(value), value))
    )
    python_selector = (
        rf"(?<![\w./\\-]){_PYTHON_PATH_SELECTOR_TOKEN}(?![\w./\\-])"
    )
    wrapper_selector = (
        rf"(?<![\w-])(?:{wrapper_alternatives})(?![\w./\\-])"
        if wrapper_alternatives
        else ""
    )
    alternatives = "|".join(
        selector for selector in (python_selector, wrapper_selector) if selector
    )
    return re.compile(
        rf"(?:{alternatives})",
        re.IGNORECASE,
    )


def _inline_skill_command_pattern(
    root: Path,
    entrypoints: tuple[EntryPoint, ...],
    wrapper_names: frozenset[str],
) -> re.Pattern[str]:
    """Build the textual command-like selector rule for Markdown prose.

    Windows resolves executable names case-insensitively, so command-shaped
    prose must apply the same spelling rule as fences and Python source.
    """
    entrypoints_by_name = {entrypoint.name: entrypoint for entrypoint in entrypoints}
    alternatives = [
        rf"{_PYTHON_PATH_SELECTOR_TOKEN}(?=[ \t]+(?:--?[A-Za-z0-9][\w-]*|"
        r"[A-Za-z0-9_./\\-]+\.py))"
    ]
    for wrapper_name in sorted(
        wrapper_names,
        key=lambda value: (-len(value), value),
    ):
        if wrapper_name == "agentkit":
            entrypoint = entrypoints_by_name.get(wrapper_name)
            verbs = (
                _declared_agentkit_verbs(root, entrypoint)
                if entrypoint is not None
                else ("export-story-md", "status")
            )
            arguments = ("--help", "--version", *verbs)
            argument_pattern = "|".join(
                re.escape(argument) for argument in sorted(set(arguments))
            )
        elif wrapper_name.startswith("agentkit-hook-"):
            argument_pattern = r"(?:pre|post)\s+[A-Za-z_][\w-]*"
        else:
            argument_pattern = r"(?:--help|--version)"
        alternatives.append(
            rf"{re.escape(wrapper_name)}(?:\.exe)?(?=[ \t]+(?:{argument_pattern})"
            r"(?=$|[\s'\"`.,;:!?)])"
            r")"
        )
    return re.compile(
        rf"(?<![\w./\\-])(?P<selector>(?:{'|'.join(alternatives)}))"
        r"(?![\w./\\-])",
        re.IGNORECASE,
    )


def _iter_markdown_prose_lines(markdown: str) -> list[tuple[int, str]]:
    """Return non-fence Markdown lines with their original locators."""
    fenced_lines: set[int] = set()
    for fence in _iter_code_fences(markdown):
        body_lines = len(fence.text.splitlines())
        end_line = fence.opening_line + body_lines + 1
        fenced_lines.update(range(fence.opening_line, end_line + 1))
    return [
        (line_number, line)
        for line_number, line in enumerate(markdown.splitlines(), start=1)
        if line_number not in fenced_lines
    ]


def _exception_spans(
    relative: Path,
    fence: _CodeFence,
) -> tuple[tuple[int, int], ...]:
    """Resolve exact visible exceptions applicable to one fence."""
    spans: list[tuple[int, int]] = []
    for exception in _NON_ENTRYPOINT_SKILL_FENCE_MENTIONS:
        if exception.path != relative or exception.fence != fence.number:
            continue
        starts = [
            match.start()
            for match in re.finditer(re.escape(exception.raw_text), fence.text)
        ]
        spans.extend(
            (start, start + len(exception.raw_text))
            for start in starts
        )
    return tuple(spans)


def _module_exists(root: Path, module: str) -> bool:
    if not module or any(not part.isidentifier() for part in module.split(".")):
        return False
    base = root / "src" / Path(*module.split("."))
    return base.with_suffix(".py").is_file() or (base / "__main__.py").is_file()


def _skill_shell_evaluation_findings(
    relative: Path,
    raw: str,
    *,
    context: str,
    line_at: Callable[[int], int],
) -> list[Finding]:
    """Render fail-closed shell-evaluation findings with original locators."""
    evaluation = _undecidable_shell_evaluation(raw)
    if evaluation is None:
        return []
    raw_offset, marker = evaluation
    raw_line = raw.splitlines()[raw[:raw_offset].count("\n")]
    return [
        Finding(
            relative,
            line_at(raw_offset),
            f"{context} is undecidable: shell evaluation marker {marker!r}; "
            f"raw text: {raw_line!r}",
        )
    ]


def _audit_skill_bundle_fences(
    root: Path,
    entrypoints: tuple[EntryPoint, ...],
) -> SkillBundleAudit:
    """Audit selector instructions in productive bundle fences and prose."""
    versions, findings = _productive_skill_bundle_versions(root)
    bundle_store = root / SKILL_BUNDLE_ROOT
    shipped_versions = (
        [
            version_dir
            for bundle_dir in sorted(
                path for path in bundle_store.iterdir() if path.is_dir()
            )
            for version_dir in sorted(
                path for path in bundle_dir.iterdir() if path.is_dir()
            )
            if _SEMANTIC_VERSION.fullmatch(version_dir.name) is not None
        ]
        if bundle_store.is_dir()
        else []
    )
    shipped_files = sum(
        1
        for version_dir in shipped_versions
        for _markdown_path in version_dir.rglob("*.md")
    )
    files = 0
    fences = 0
    prose_lines = 0
    python_modules = 0
    wrapper_names = frozenset(
        {"agentkit", *(entrypoint.name.lower() for entrypoint in entrypoints)}
    )
    selector_pattern = _skill_selector_pattern(wrapper_names)
    inline_command_pattern = _inline_skill_command_pattern(
        root,
        entrypoints,
        wrapper_names,
    )
    for version_dir in versions:
        for markdown_path in sorted(version_dir.rglob("*.md")):
            files += 1
            relative = markdown_path.relative_to(root)
            try:
                markdown = markdown_path.read_text(encoding="utf-8")
                code_fences = _iter_code_fences(markdown)
            except (OSError, UnicodeError) as exc:
                findings.append(
                    Finding(relative, 1, f"cannot audit skill code fences: {exc}")
                )
                continue
            fences += len(code_fences)
            prose = _iter_markdown_prose_lines(markdown)
            prose_lines += len(prose)
            fences_by_number = {fence.number: fence for fence in code_fences}
            for exception in _NON_ENTRYPOINT_SKILL_FENCE_MENTIONS:
                if exception.path != relative:
                    continue
                declared_fence = fences_by_number.get(exception.fence)
                if (
                    declared_fence is None
                    or exception.raw_text not in declared_fence.text
                    or selector_pattern.search(
                        _without_shell_quotes(exception.raw_text).text
                    )
                    is None
                    or not exception.reason.strip()
                ):
                    findings.append(
                        Finding(
                            relative,
                            1,
                            "invalid or stale skill-fence exception for fence "
                            f"{exception.fence} and raw text {exception.raw_text!r}",
                        )
                    )
            for fence in code_fences:
                exception_spans = _exception_spans(relative, fence)
                findings.extend(
                    _skill_shell_evaluation_findings(
                        relative,
                        fence.text,
                        context=f"skill code fence {fence.number}",
                        line_at=fence.line_at,
                    )
                )
                normalized_fence = _without_shell_quotes(fence.text)
                for match in selector_pattern.finditer(normalized_fence.text):
                    raw_start = normalized_fence.raw_offset(match.start())
                    if any(start <= raw_start < end for start, end in exception_spans):
                        continue
                    findings.append(
                        Finding(
                            relative,
                            fence.line_at(raw_start),
                            f"skill code fence {fence.number} contains forbidden "
                            f"selector word {match.group(0)!r}; raw text: "
                            f"{fence.text.splitlines()[fence.text[:raw_start].count(chr(10))]!r}",
                        )
                    )
                for match in _PYTHON_MODULE_TARGET.finditer(fence.text):
                    python_modules += 1
                    module = match.group("module")
                    if not _module_exists(root, module):
                        findings.append(
                            Finding(
                                relative,
                                fence.line_at(match.start("module")),
                                f"productive python -m target {module!r} has no "
                                "module file or package __main__.py",
                            )
                        )
            for line_number, line in prose:
                normalized_line = _without_shell_quotes(line)
                for match in inline_command_pattern.finditer(normalized_line.text):
                    findings.append(
                        Finding(
                            relative,
                            line_number,
                            "skill inline prose contains command-like forbidden "
                            f"selector {match.group('selector')!r}; raw text: {line!r}",
                        )
                    )
    return SkillBundleAudit(
        findings=tuple(findings),
        shipped_bundle_versions=len(shipped_versions),
        shipped_files=shipped_files,
        bundle_versions=len(versions),
        files=files,
        fences=fences,
        prose_lines=prose_lines,
        python_modules=python_modules,
    )


def _audit_python(
    root: Path,
) -> tuple[list[Finding], list[Finding], tuple[EntryPoint, ...]]:
    findings: list[Finding] = []
    visible_non_entrypoints: list[Finding] = []
    matched_selector_exceptions: set[_SelectorLiteralException] = set()
    audits_by_path: dict[Path, _SourceAudit] = {}
    entrypoints, declaration_findings = _declared_entrypoints(root)
    findings.extend(declaration_findings)
    selector_names = frozenset(
        {
            "agentkit",
            *(entrypoint.name.casefold() for entrypoint in entrypoints),
        }
    )
    source_root = root / SOURCE_ROOT
    for source_path in sorted(source_root.rglob("*.py")):
        relative = source_path.relative_to(root)
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(Finding(relative, 1, f"cannot audit Python source: {exc}"))
            continue
        audit = _SourceAudit(
            relative,
            source=source,
            selector_names=selector_names,
            text_environment=_constant_text_environment(tree),
            subprocess_bindings=_subprocess_binding_inventory(tree),
        )
        audit.visit(tree)
        audit.findings = list(dict.fromkeys(audit.findings))
        audit.visible_non_entrypoints = list(
            dict.fromkeys(audit.visible_non_entrypoints)
        )
        findings.extend(audit.findings)
        visible_non_entrypoints.extend(audit.visible_non_entrypoints)
        matched_selector_exceptions.update(audit.matched_selector_exceptions)
        audits_by_path[relative] = audit

    if root == REPO_ROOT.resolve():
        for exception in _NON_COMMAND_SELECTOR_LITERALS:
            if exception not in matched_selector_exceptions:
                findings.append(
                    Finding(
                        exception.path,
                        exception.line,
                        "invalid or stale non-command selector-literal exception for "
                        f"{exception.literal!r}: {exception.reason}",
                    )
                )

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
    return findings, visible_non_entrypoints, tuple(entrypoints)


def _is_productive_cli_surface(
    relative: Path,
    tree: ast.Module,
    entrypoint_paths: frozenset[Path],
) -> bool:
    """Return whether source text can publish an executable CLI instruction."""
    if (
        relative.is_relative_to(TARGET_PROJECT_ROOT)
        or relative in entrypoint_paths
        or relative.name == "__main__.py"
    ):
        return True
    argparse_modules = {"argparse"}
    parser_names = {"ArgumentParser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            argparse_modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "argparse"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "argparse":
            parser_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "ArgumentParser"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "ArgumentParser"
                and isinstance(function.value, ast.Name)
                and function.value.id in argparse_modules
            ) or (
                isinstance(function, ast.Name)
                and function.id in parser_names
            ):
                return True
        if not isinstance(node, ast.If):
            continue
        names = {
            candidate.id
            for candidate in ast.walk(node.test)
            if isinstance(candidate, ast.Name)
        }
        constants = {
            candidate.value
            for candidate in ast.walk(node.test)
            if isinstance(candidate, ast.Constant)
            and isinstance(candidate.value, str)
        }
        if "__name__" in names and "__main__" in constants:
            return True
    return False


def _render_joined_text(
    node: ast.JoinedStr,
    bindings: dict[str, _RenderedText] | None = None,
) -> _RenderedText | None:
    """Represent an f-string without evaluating any formatted expression."""
    active_bindings = bindings or {}
    fragments: list[tuple[str, int]] = []
    dynamic_lines: list[int] = []
    dynamic_selectors: list[tuple[str, int]] = []
    for value in node.values:
        if isinstance(value, ast.FormattedValue):
            resolved = _render_static_text(value.value, active_bindings)
            if resolved is not None:
                fragments.extend(resolved.fragments)
                dynamic_lines.extend(resolved.dynamic_lines)
                dynamic_selectors.extend(resolved.dynamic_selectors)
                continue
            fragments.append(("__AK3_DYNAMIC__", value.lineno))
            dynamic_lines.append(value.lineno)
            for candidate in ast.walk(value.value):
                if not (
                    isinstance(candidate, ast.Constant)
                    and isinstance(candidate.value, str)
                ):
                    continue
                dynamic_selectors.extend(
                    (match.group(0), candidate.lineno)
                    for match in _SELECTOR_MENTION.finditer(candidate.value)
                )
            continue
        rendered = _render_static_text(value, active_bindings)
        if rendered is None:
            return None
        fragments.extend(rendered.fragments)
        dynamic_lines.extend(rendered.dynamic_lines)
        dynamic_selectors.extend(rendered.dynamic_selectors)
    return _RenderedText(
        tuple(fragments),
        tuple(dynamic_lines),
        tuple(dynamic_selectors),
    )


def _literal_selector_mentions(node: ast.AST) -> tuple[tuple[str, int], ...]:
    """Inventory selector literals without evaluating their containing expression."""
    return tuple(
        (match.group(0), candidate.lineno)
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
        for match in _SELECTOR_MENTION.finditer(candidate.value)
    )


def _render_static_text(
    node: ast.AST,
    bindings: dict[str, _RenderedText] | None = None,
) -> _RenderedText | None:
    """Render supported literal string compositions without executing code."""
    active_bindings = bindings or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _RenderedText(((node.value, node.lineno),))
    if isinstance(node, ast.Name):
        return active_bindings.get(node.id)
    if isinstance(node, ast.JoinedStr):
        return _render_joined_text(node, active_bindings)
    if isinstance(node, ast.BinOp):
        left = _render_static_text(node.left, active_bindings)
        right = _render_static_text(node.right, active_bindings)
        if isinstance(node.op, ast.Add) and left is not None and right is not None:
            return _RenderedText(
                (*left.fragments, *right.fragments),
                (*left.dynamic_lines, *right.dynamic_lines),
                (*left.dynamic_selectors, *right.dynamic_selectors),
            )
        if left is not None:
            right_selectors = _literal_selector_mentions(node.right)
            return _RenderedText(
                (*left.fragments, ("__AK3_DYNAMIC__", node.right.lineno)),
                (*left.dynamic_lines, node.right.lineno),
                (*left.dynamic_selectors, *right_selectors),
            )
        if right is not None:
            return _RenderedText(
                (("__AK3_DYNAMIC__", node.left.lineno), *right.fragments),
                (node.left.lineno, *right.dynamic_lines),
                right.dynamic_selectors,
            )
        return None
    if isinstance(node, ast.Call):
        return _render_static_call_text(node, active_bindings)
    return None


def _render_static_call_text(
    node: ast.Call,
    bindings: dict[str, _RenderedText],
) -> _RenderedText | None:
    """Render the bounded ``format`` and literal ``join`` call forms."""
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and (node.args or node.keywords)
    ):
        template = _render_static_text(node.func.value, bindings)
        if template is None:
            return None
        argument_selectors = tuple(
            selector
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
            for selector in _literal_selector_mentions(argument)
        )
        return _RenderedText(
            (*template.fragments, ("__AK3_DYNAMIC__", node.lineno)),
            (*template.dynamic_lines, node.lineno),
            (*template.dynamic_selectors, *argument_selectors),
        )
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        return None
    separator = _render_static_text(node.func.value, bindings)
    if separator is None:
        return None
    values: list[_RenderedText] = []
    for item in node.args[0].elts:
        value = _render_static_text(item, bindings)
        if value is None:
            return None
        values.append(value)
    fragments = []
    dynamic_lines = []
    dynamic_selectors = []
    for index, value in enumerate(values):
        if index:
            fragments.extend(separator.fragments)
        fragments.extend(value.fragments)
        dynamic_lines.extend(value.dynamic_lines)
        dynamic_selectors.extend(value.dynamic_selectors)
    return _RenderedText(
        tuple(fragments),
        tuple(dynamic_lines),
        tuple(dynamic_selectors),
    )


def _scope_body(scope: ast.AST) -> list[ast.stmt]:
    """Return the direct statement body of a supported lexical scope."""
    body = getattr(scope, "body", None)
    return body if isinstance(body, list) else []


_LEXICAL_SCOPE_TYPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
)


def _lexical_parent(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.AST | None:
    """Return the nearest lexical scope containing ``node``."""
    parent = parents.get(node)
    while parent is not None and not isinstance(parent, _LEXICAL_SCOPE_TYPES):
        parent = parents.get(parent)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        while isinstance(parent, ast.ClassDef):
            parent = _lexical_parent(parent, parents)
    return parent


class _ScopeAssignmentCollector(ast.NodeVisitor):
    """Collect assignments in one lexical scope, including conditional bodies."""

    def __init__(self) -> None:
        self.candidates: dict[str, list[tuple[ast.stmt, ast.AST]]] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.candidates.setdefault(target.id, []).append((node, node.value))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self.candidates.setdefault(node.target.id, []).append((node, node.value))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass


def _direct_constant_assignments(
    scope: ast.AST,
) -> tuple[
    dict[str, ast.AST],
    dict[str, tuple[tuple[ast.stmt, ast.AST], ...]],
]:
    """Keep unique direct assignments and retain every discarded candidate."""
    collector = _ScopeAssignmentCollector()
    for statement in _scope_body(scope):
        collector.visit(statement)
    direct_statement_ids = {id(statement) for statement in _scope_body(scope)}
    assignments: dict[str, ast.AST] = {}
    discarded: dict[str, tuple[tuple[ast.stmt, ast.AST], ...]] = {}
    for name, candidates in collector.candidates.items():
        if len(candidates) == 1 and id(candidates[0][0]) in direct_statement_ids:
            assignments[name] = candidates[0][1]
        else:
            discarded[name] = tuple(candidates)
    return assignments, discarded


def _local_scope_bindings(scope: ast.AST) -> set[str]:
    """Return names that prevent a function or lambda from reading outer bindings."""
    if isinstance(scope, ast.Lambda):
        arguments = scope.args
        names: set[str] = set()
    elif isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = scope.args
        collector = _FunctionBindingCollector()
        for statement in scope.body:
            collector.visit(statement)
        names = collector.names
    else:
        return set()
    names.update(
        argument.arg
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        )
    )
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _resolve_constant_assignments(
    assignments: dict[str, ast.AST],
    visible: dict[str, _RenderedText],
) -> dict[str, _RenderedText]:
    """Resolve a bounded fixed point of literal local assignments."""
    unresolved = dict(assignments)
    local: dict[str, _RenderedText] = {}
    changed = True
    while changed:
        changed = False
        for name, value in tuple(unresolved.items()):
            rendered = _render_static_text(value, {**visible, **local})
            if rendered is None:
                continue
            local[name] = rendered
            del unresolved[name]
            changed = True
    return local


def _constant_text_environment(tree: ast.Module) -> _StaticTextEnvironment:
    """Resolve only single-assignment constants in their lexical scope.

    This intentionally is not general data-flow analysis: conditional,
    destructuring, augmented, and multiply assigned names stay unresolved.
    """
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    scope_by_node: dict[ast.AST, ast.AST] = {}
    scopes: list[ast.AST] = []
    for node in ast.walk(tree):
        parent = node
        while not isinstance(parent, _LEXICAL_SCOPE_TYPES):
            parent = parents[parent]
        scope_by_node[node] = parent
        if node is parent:
            scopes.append(node)

    bindings_by_scope: dict[ast.AST, dict[str, _RenderedText]] = {}
    assignments_by_scope: dict[ast.AST, dict[str, ast.AST]] = {}
    discarded_assignments_by_scope: dict[
        ast.AST,
        dict[str, tuple[tuple[ast.stmt, ast.AST], ...]],
    ] = {}
    pending_scopes = set(scopes)
    while pending_scopes:
        progressed = False
        for scope in tuple(pending_scopes):
            parent = _lexical_parent(scope, parents)
            if parent is not None and parent not in bindings_by_scope:
                continue
            locally_bound = _local_scope_bindings(scope)
            visible = {
                name: value
                for name, value in bindings_by_scope.get(parent, {}).items()
                if name not in locally_bound
            }
            visible_assignments = {
                name: value
                for name, value in assignments_by_scope.get(parent, {}).items()
                if name not in locally_bound
            }
            visible_discarded = {
                name: value
                for name, value in discarded_assignments_by_scope.get(
                    parent, {}
                ).items()
                if name not in locally_bound
            }
            direct_assignments, discarded_assignments = (
                _direct_constant_assignments(scope)
            )
            local = _resolve_constant_assignments(
                direct_assignments,
                visible,
            )
            bindings_by_scope[scope] = {**visible, **local}
            assignments_by_scope[scope] = {
                **visible_assignments,
                **direct_assignments,
            }
            discarded_assignments_by_scope[scope] = {
                **visible_discarded,
                **discarded_assignments,
            }
            pending_scopes.remove(scope)
            progressed = True
        if not progressed:  # pragma: no cover - AST parents are acyclic
            break
    return _StaticTextEnvironment(
        bindings_by_scope,
        assignments_by_scope,
        discarded_assignments_by_scope,
        scope_by_node,
    )


def _static_cli_texts(
    tree: ast.Module,
    environment: _StaticTextEnvironment,
) -> list[_RenderedText]:
    """Return maximal statically composed strings from a Python AST."""
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    rendered_nodes: list[_RenderedText] = []
    for node in ast.walk(tree):
        bindings = environment.bindings_for(node)
        rendered = _render_static_text(node, bindings)
        if rendered is None:
            continue
        ancestor = parents.get(node)
        while ancestor is not None:
            if _render_static_text(
                ancestor,
                environment.bindings_for(ancestor),
            ) is not None:
                break
            ancestor = parents.get(ancestor)
        if ancestor is None:
            rendered_nodes.append(
                _RenderedText(
                    rendered.fragments,
                    rendered.dynamic_lines,
                    rendered.dynamic_selectors,
                    ast.unparse(node),
                )
            )
    return rendered_nodes


def _declared_agentkit_verbs(root: Path, entrypoint: EntryPoint) -> tuple[str, ...]:
    """Read the general CLI's dispatched verbs from its authoritative source."""
    try:
        tree = ast.parse((root / entrypoint.path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return ()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "_dispatch_command":
            continue
        verbs: set[str] = set()
        for candidate in ast.walk(node):
            if not isinstance(candidate, ast.Dict):
                if not isinstance(candidate, ast.Compare):
                    continue
                if not (
                    isinstance(candidate.left, ast.Attribute)
                    and candidate.left.attr == "command"
                ):
                    continue
                verbs.update(
                    comparator.value
                    for comparator in candidate.comparators
                    if isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                )
                continue
            verbs.update(
                key.value
                for key in candidate.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        return tuple(verbs)
    return ()


def _declared_wrapper_instruction(
    root: Path,
    entrypoints: tuple[EntryPoint, ...],
) -> re.Pattern[str]:
    """Build the productive wrapper selector from ``project.scripts``."""
    alternatives: list[str] = []
    for entrypoint in sorted(entrypoints, key=lambda item: (-len(item.name), item.name)):
        name = re.escape(entrypoint.name)
        if entrypoint.name == "agentkit":
            verbs = "|".join(
                re.escape(verb)
                for verb in sorted(_declared_agentkit_verbs(root, entrypoint))
            )
            argument = rf"(?:--help|--version|{verbs})"
        elif entrypoint.name.startswith("agentkit-hook-"):
            argument = r"(?:pre|post)\s+[A-Za-z_][\w-]*"
        else:
            argument = r"(?:--help|--version)"
        alternatives.append(rf"{name}(?:\.exe)?\s+{argument}")
    if not alternatives:
        return re.compile(r"(?!)")
    return re.compile(
        rf"(?<![\w./\\-])(?:{'|'.join(alternatives)})"
        r"(?=$|[\s'\"`.,;:!?)])",
        re.IGNORECASE,
    )


def _audit_productive_cli_text(
    root: Path,
    entrypoints: tuple[EntryPoint, ...],
) -> tuple[list[Finding], int]:
    """Reject PATH entrypoint instructions published by executable CLI sources."""
    findings: list[Finding] = []
    audited = 0
    wrapper_instruction = _declared_wrapper_instruction(root, entrypoints)
    dynamic_wrapper_selector = re.compile(
        r"(?<![\w./\\-])(?P<selector>agentkit)"
        r"(?:-[a-z0-9][a-z0-9-]*)*(?:\.exe)?"
        r"(?=\s+[^\r\n]*__AK3_DYNAMIC__)",
        re.IGNORECASE,
    )
    dynamic_python_selector = re.compile(
        rf"(?<![\w./\\-])(?P<selector>{_PYTHON_PATH_SELECTOR_TOKEN})"
        r"(?=\s+(?:\{\}|%s)?__AK3_DYNAMIC__)",
        re.IGNORECASE,
    )
    entrypoint_paths = frozenset(entrypoint.path for entrypoint in entrypoints)
    for source_path in sorted((root / SOURCE_ROOT).rglob("*.py")):
        relative = source_path.relative_to(root)
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, SyntaxError, UnicodeError):
            # The primary source audit reports the actionable parse/read finding.
            continue
        if not _is_productive_cli_surface(relative, tree, entrypoint_paths):
            continue
        audited += 1
        environment = _constant_text_environment(tree)
        for rendered in _static_cli_texts(tree, environment):
            normalized_text = _without_shell_quotes(rendered.text)
            if rendered.dynamic_lines:
                expression_line = min(
                    *(line for _fragment, line in rendered.fragments),
                    *rendered.dynamic_lines,
                )
                selector_locations = list(rendered.dynamic_selectors)
                selector_locations.extend(
                    (
                        match.groupdict().get("selector") or match.group(0),
                        rendered.line_at(normalized_text.raw_offset(match.start())),
                    )
                    for pattern in (
                        _BARE_PYTHON_INSTRUCTION,
                        dynamic_python_selector,
                        dynamic_wrapper_selector,
                    )
                    for match in pattern.finditer(normalized_text.text)
                )
                for selector, _line in dict.fromkeys(selector_locations):
                    findings.append(
                        Finding(
                            relative,
                            expression_line,
                            "undecidable productive CLI string expression: dynamic "
                            f"content is combined with selector {selector!r}; "
                            f"raw text: {rendered.raw_text!r}",
                        )
                    )
                continue
            matches = sorted(
                (
                    *_BARE_PYTHON_INSTRUCTION.finditer(normalized_text.text),
                    *wrapper_instruction.finditer(normalized_text.text),
                ),
                key=lambda item: item.start(),
            )
            for match in matches:
                findings.append(
                    Finding(
                        relative,
                        rendered.line_at(normalized_text.raw_offset(match.start())),
                        "productive CLI text publishes bare "
                        f"{match.group(0)!r} from PATH; raw text: {rendered.text!r}",
                    )
                )
    return findings, audited


def _audit_bundled_hook(
    root: Path,
    entrypoints: tuple[EntryPoint, ...],
) -> list[Finding]:
    """Inventory every command published by the bundled Claude hook settings."""
    relative = Path("src/agentkit/bundles/target_project/.claude/settings.json")
    path = root / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        hooks_by_event = payload["hooks"]
        if not isinstance(hooks_by_event, dict) or not hooks_by_event:
            raise TypeError("hooks must be a non-empty object")
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        return [Finding(relative, 1, f"cannot audit bundled hook command: {exc}")]

    findings: list[Finding] = []
    commands: list[tuple[str, str]] = []
    for event, groups in sorted(hooks_by_event.items()):
        if not isinstance(event, str) or not isinstance(groups, list):
            findings.append(
                Finding(relative, 1, "bundled hook events must map to lists")
            )
            continue
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                findings.append(
                    Finding(
                        relative,
                        1,
                        f"bundled hook group {event}[{group_index}] must contain a hooks list",
                    )
                )
                continue
            for hook_index, hook in enumerate(group["hooks"]):
                if not isinstance(hook, dict):
                    findings.append(
                        Finding(
                            relative,
                            1,
                            f"bundled hook {event}[{group_index}].hooks[{hook_index}] must be an object",
                        )
                    )
                    continue
                hook_type = hook.get("type")
                if hook_type != "command":
                    findings.append(
                        Finding(
                            relative,
                            1,
                            f"cannot audit bundled hook {event}[{group_index}]."
                            f"hooks[{hook_index}] of unknown type {hook_type!r}",
                        )
                    )
                    continue
                command = hook.get("command")
                if not isinstance(command, str) or not command.strip():
                    findings.append(
                        Finding(
                            relative,
                            1,
                            f"bundled command hook {event}[{group_index}].hooks[{hook_index}] has no command",
                        )
                    )
                    continue
                commands.append((event, command))

    expected = "__AK3_INTERPRETER__ .agentkit/hooks/pre_tool_use.py"
    if ("PreToolUse", expected) not in commands:
        findings.append(
            Finding(
                relative,
                1,
                f"bundled PreToolUse hooks must publish {expected!r}",
            )
        )

    wrapper_names = frozenset(
        {"agentkit", *(entrypoint.name.casefold() for entrypoint in entrypoints)}
    )
    selector_pattern = _skill_selector_pattern(wrapper_names)
    for event, command in commands:
        findings.extend(
            _audit_one_bundled_hook_command(
                relative,
                event,
                command,
                selector_pattern,
            )
        )
    if not commands:
        findings.append(Finding(relative, 1, "bundled hooks publish no commands"))
    return findings


def _audit_one_bundled_hook_command(
    relative: Path,
    event: str,
    command: str,
    selector_pattern: re.Pattern[str],
) -> list[Finding]:
    """Audit one known command hook without widening the settings traversal."""
    evaluation = _undecidable_shell_evaluation(command)
    findings = (
        [
            Finding(
                relative,
                1,
                f"bundled {event} hook command is undecidable: shell evaluation "
                f"marker {evaluation[1]!r}; raw text: {command!r}",
            )
        ]
        if evaluation is not None
        else []
    )
    normalized = _without_shell_quotes(command)
    findings.extend(
        Finding(
            relative,
            1,
            f"bundled {event} hook command contains forbidden selector "
            f"{match.group(0)!r}; raw text: {command!r}",
        )
        for match in selector_pattern.finditer(normalized.text)
    )
    return findings


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
    findings, visible_non_entrypoints, entrypoints = _audit_python(root)
    cli_text_findings, cli_surface_count = _audit_productive_cli_text(
        root,
        entrypoints,
    )
    findings.extend(cli_text_findings)
    findings.extend(_audit_bundled_hook(root, entrypoints))
    findings.extend(_audit_python_version_source(root))
    findings.extend(_audit_concept_floor_authority(root))
    skill_bundle_audit = _audit_skill_bundle_fences(root, entrypoints)
    findings.extend(skill_bundle_audit.findings)
    for finding in visible_non_entrypoints:
        print(f"[interpreter-entrypoints] INFO: {finding.render()} (visible exception)")
    if findings:
        for finding in sorted(findings, key=lambda item: (str(item.path), item.line)):
            print(f"[interpreter-entrypoints] ERROR: {finding.render()}", file=sys.stderr)
        print(
            f"[interpreter-entrypoints] FAILED: {len(findings)} violation(s)",
            file=sys.stderr,
        )
        return 1
    if _NON_ENTRYPOINT_SKILL_FENCE_MENTIONS:
        for exception in _NON_ENTRYPOINT_SKILL_FENCE_MENTIONS:
            print(
                "[interpreter-entrypoints] INFO: skill-fence exception: "
                f"{exception.path.as_posix()} fence {exception.fence}; "
                f"raw_text={exception.raw_text!r}; reason={exception.reason}"
            )
    else:
        print("[interpreter-entrypoints] INFO: skill-fence exceptions: none")
    print(
        "[interpreter-entrypoints] OK: "
        f"{len(entrypoints)} declared entrypoint(s) and the installed-package "
        "boundary use the central interpreter owner; "
        f"{skill_bundle_audit.shipped_files} skill Markdown file(s) in "
        f"{skill_bundle_audit.shipped_bundle_versions} shipped immutable bundle version(s), "
        "of which "
        f"{skill_bundle_audit.files} skill Markdown file(s) in "
        f"{skill_bundle_audit.bundle_versions} productive skill bundle version(s), "
        f"{skill_bundle_audit.fences} code fence(s), "
        f"{skill_bundle_audit.prose_lines} non-fence prose line(s), "
        f"{skill_bundle_audit.python_modules} python -m target(s), and "
        f"{cli_surface_count} productive CLI source file(s) audited"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
