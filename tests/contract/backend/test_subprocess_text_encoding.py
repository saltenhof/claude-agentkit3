"""No text-mode subprocess read may depend on the machine it runs on.

``text=True`` without ``encoding`` decodes with the platform's preferred
encoding: UTF-8 on Linux and macOS, cp1252 on a German Windows. The same code
then reads the same bytes correctly on one machine and raises
``UnicodeDecodeError`` on another -- which is how the concept CLI died on a diff
of German prose while every CI run stayed green.

Two rules, and the second one is why this file is longer than it looks:

1. A text-mode read must pin ``encoding`` to a UTF-8 spelling. Any other
   encoding, and any expression the guard cannot evaluate, counts as unpinned:
   a name or a call could be ``locale.getpreferredencoding()``, which is the
   defect spelled out.
2. What the guard cannot READ, it rejects. A call that hides its keywords
   behind ``**`` cannot be shown to pin anything. Recognition therefore does not
   rest on the callee's name alone -- an aliased or re-imported ``run`` is still
   a subprocess call, and a call carrying subprocess-only keywords is judged as
   one whatever it is named.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_TREES = ("src", "tools", "scripts", "tests")

SUBPROCESS_ENTRY_POINTS = frozenset(
    {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
)
# Keywords no non-subprocess API carries. A call with one of these is a process
# call no matter what name it was reached through.
SUBPROCESS_ONLY_KEYWORDS = frozenset({"capture_output", "shell", "stdout", "stderr", "stdin"})
TEXT_MODE_KEYWORDS = ("text", "universal_newlines")
UTF8_SPELLINGS = frozenset({"utf-8", "utf8", "u8"})


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _reaches_subprocess(value: ast.expr | None, known: set[str]) -> bool:
    if isinstance(value, ast.Attribute):
        return value.attr in SUBPROCESS_ENTRY_POINTS
    if isinstance(value, ast.Name):
        return value.id in known
    if isinstance(value, ast.IfExp):
        return _reaches_subprocess(value.body, known) or _reaches_subprocess(value.orelse, known)
    if isinstance(value, ast.Call):
        if _callee_name(value) == "getattr":
            return any(
                isinstance(arg, ast.Constant) and arg.value in SUBPROCESS_ENTRY_POINTS
                for arg in value.args
            )
        return any(_reaches_subprocess(arg, known) for arg in value.args)
    return False


def _bound_names(tree: ast.AST) -> set[str]:
    """Return every local name that can reach a subprocess entry point.

    Covers ``from subprocess import run as execute``, ``execute =
    subprocess.run`` (annotated or not), ``getattr(subprocess, "run")`` and
    ``partial(run, ...)``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in SUBPROCESS_ENTRY_POINTS
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if _reaches_subprocess(node.value, names):
                names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _is_process_call(node: ast.Call, bound: set[str]) -> bool:
    keywords = {kw.arg for kw in node.keywords if kw.arg is not None}
    if keywords & SUBPROCESS_ONLY_KEYWORDS:
        return True
    if _callee_name(node) in SUBPROCESS_ENTRY_POINTS | bound:
        return True
    # Any binder -- `partial(run, ...)`, `bind(run, ...)` -- that carries a
    # subprocess entry point as an argument decides that call's keywords here.
    return any(_reaches_subprocess(arg, bound) for arg in node.args)


def _forwards_everything(node: ast.Call) -> bool:
    """Return whether the call only passes its caller's arguments through.

    ``real_popen(*args, **kwargs)`` decides nothing; demanding an encoding there
    would move the decision to the wrong place. A call with an argument of its
    own is a call that decides.
    """
    if not node.args and not node.keywords:
        return False
    return all(isinstance(arg, ast.Starred) for arg in node.args) and all(
        kw.arg is None for kw in node.keywords
    )


def _reads_text(call: ast.Call) -> bool:
    """Return whether the call decodes. Anything but a falsy literal counts.

    ``text=1`` and ``text=SOME_NAME`` decode just as much as ``text=True``.
    """
    for kw in call.keywords:
        if kw.arg not in TEXT_MODE_KEYWORDS:
            continue
        if isinstance(kw.value, ast.Constant) and not kw.value.value:
            continue
        return True
    return False


def _pins_utf8(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg != "encoding":
            continue
        value = kw.value
        return (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.lower().replace("_", "-") in UTF8_SPELLINGS
        )
    return False


def _offences(tree: ast.AST) -> list[tuple[int, str]]:
    bound = _bound_names(tree)
    offences: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_process_call(node, bound):
            continue
        if _pins_utf8(node):
            continue
        if _reads_text(node):
            offences.append((node.lineno, "text mode without a literal utf-8 encoding"))
        elif any(kw.arg is None for kw in node.keywords) and not _forwards_everything(node):
            offences.append((node.lineno, "keywords hidden behind ** -- cannot be shown to pin"))
    return offences


def test_no_subprocess_read_relies_on_the_platform_encoding() -> None:
    offenders: list[str] = []
    for tree_name in SCANNED_TREES:
        for path in sorted((REPO_ROOT / tree_name).rglob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: {reason}"
                for line, reason in _offences(module)
            )
    assert offenders == [], "subprocess calls without a pinned encoding: " + ", ".join(offenders)


def test_the_guard_catches_every_evasion_it_claims_to_catch() -> None:
    """A guard is worth exactly what it survives being worked around."""
    evasions = (
        "subprocess.run(argv, text=True)",
        "subprocess.run(argv, text=True, encoding=None)",
        'subprocess.run(argv, text=True, encoding="cp1252")',
        "subprocess.run(argv, text=True, encoding=locale.getpreferredencoding(False))",
        "ENCODING = None\nsubprocess.run(argv, text=True, encoding=ENCODING)",
        "subprocess.run(argv, universal_newlines=True)",
        "subprocess.run(argv, text=1)",
        "TEXT = True\nsubprocess.run(argv, text=TEXT)",
        "subprocess.run(argv, **options)",
        "execute = subprocess.run\nexecute(argv, text=True)",
        "from subprocess import run as execute\nexecute(argv, text=True)",
        "execute: object = subprocess.run\nexecute(argv, text=True)",
        'execute = getattr(subprocess, "run")\nexecute(argv, text=True)',
        "from subprocess import run\nbind(run, text=True)",
        "functools.partial(subprocess.run, text=True)",
        # Reached through no recognizable name at all -- judged by its keywords.
        "self._runner(argv, capture_output=True, text=True)",
        "runners[key](argv, shell=False, text=True)",
    )
    for source in evasions:
        assert _offences(ast.parse(source)) != [], source


def test_the_guard_accepts_a_pinned_call() -> None:
    accepted = (
        'subprocess.run(argv, text=True, encoding="utf-8")',
        'subprocess.run(argv, text=True, encoding="UTF-8")',
        'subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")',
        "subprocess.run(argv, capture_output=True)",  # bytes: nothing is decoded
        "subprocess.run(argv, capture_output=True, text=False)",
        'functools.partial(subprocess.run, text=True, encoding="utf-8")',
        # A pure forwarder decides nothing -- the caller already did.
        "real_popen(*args, **kwargs)",
    )
    for source in accepted:
        assert _offences(ast.parse(source)) == [], source
