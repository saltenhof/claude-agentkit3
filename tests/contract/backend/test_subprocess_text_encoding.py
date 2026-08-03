"""Every text-mode subprocess read must pin UTF-8, not the platform.

``text=True`` without ``encoding`` decodes with the platform's preferred
encoding: UTF-8 on Linux and macOS, cp1252 on a German Windows. The same code
then reads the same repository content correctly on one machine and raises
``UnicodeDecodeError`` on another -- which is how the concept CLI died on a diff
of German prose while every CI run stayed green.

The guard covers every productive tree, and it treats what it cannot READ as an
offence: a call that hides its arguments behind ``**kwargs`` or a partial cannot
be shown to pin anything, so it fails here rather than on someone's machine.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTIVE_TREES = ("src", "tools", "scripts")

SUBPROCESS_ENTRY_POINTS = frozenset(
    {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
)
TEXT_MODE_KEYWORDS = ("text", "universal_newlines")


def _local_aliases(tree: ast.AST) -> set[str]:
    """Return names bound to a subprocess entry point in this module.

    ``execute = subprocess.run`` renames the call without changing what it does.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        if node.value.attr not in SUBPROCESS_ENTRY_POINTS:
            continue
        aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return aliases


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _subprocess_calls(tree: ast.AST, aliases: set[str]) -> list[ast.Call]:
    """Return every call that reaches a subprocess entry point.

    ``functools.partial(subprocess.run, ...)`` is judged at the partial itself:
    that is where the keywords are written.
    """
    names = SUBPROCESS_ENTRY_POINTS | aliases
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node) in names:
            calls.append(node)
            continue
        if _callee_name(node) == "partial" and any(
            isinstance(arg, ast.Attribute) and arg.attr in SUBPROCESS_ENTRY_POINTS
            for arg in node.args
        ):
            calls.append(node)
    return calls


def _pins_utf8(call: ast.Call) -> bool:
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}
    encoding = keywords.get("encoding")
    # `encoding=None` is the platform default spelled out -- not a pin.
    return encoding is not None and not (
        isinstance(encoding, ast.Constant) and encoding.value is None
    )


def _reads_text(call: ast.Call) -> bool:
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}
    return any(
        isinstance(keywords.get(name), ast.Constant) and keywords[name].value is True
        for name in TEXT_MODE_KEYWORDS
    )


def _hides_its_arguments(call: ast.Call) -> bool:
    """Return whether the call splats keywords the guard cannot inspect."""
    return any(kw.arg is None for kw in call.keywords)


def _offences(tree: ast.AST) -> list[tuple[int, str]]:
    aliases = _local_aliases(tree)
    offences: list[tuple[int, str]] = []
    for call in _subprocess_calls(tree, aliases):
        if _pins_utf8(call):
            continue
        if _reads_text(call):
            offences.append((call.lineno, "text mode without a pinned encoding"))
        elif _hides_its_arguments(call):
            offences.append((call.lineno, "keywords hidden behind ** -- cannot be shown to pin"))
    return offences


def test_no_subprocess_read_relies_on_the_platform_encoding() -> None:
    offenders: list[str] = []
    for tree_name in PRODUCTIVE_TREES:
        for path in sorted((REPO_ROOT / tree_name).rglob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: {reason}"
                for line, reason in _offences(module)
            )
    assert offenders == [], "subprocess calls without a pinned encoding: " + ", ".join(offenders)


def test_the_guard_catches_every_evasion_it_claims_to_catch() -> None:
    """The guard is only worth its claim if it survives being worked around."""
    evasions = (
        "subprocess.run(argv, text=True)",
        "subprocess.run(argv, text=True, encoding=None)",
        "subprocess.run(argv, universal_newlines=True)",
        "subprocess.run(argv, **options)",
        "execute = subprocess.run\nexecute(argv, text=True)",
        "functools.partial(subprocess.run, text=True)",
    )
    for source in evasions:
        assert _offences(ast.parse(source)) != [], source


def test_the_guard_accepts_a_pinned_call() -> None:
    accepted = (
        'subprocess.run(argv, text=True, encoding="utf-8")',
        'subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")',
        "subprocess.run(argv, capture_output=True)",  # bytes: nothing is decoded
        'functools.partial(subprocess.run, text=True, encoding="utf-8")',
    )
    for source in accepted:
        assert _offences(ast.parse(source)) == [], source
