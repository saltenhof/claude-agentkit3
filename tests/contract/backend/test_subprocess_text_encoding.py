"""No text-mode subprocess read may depend on the machine it runs on.

``text=True`` without ``encoding`` decodes with the platform's preferred
encoding: UTF-8 on Linux and macOS, cp1252 on a German Windows. The same code
then reads the same bytes correctly on one machine and raises
``UnicodeDecodeError`` on another -- which is how the concept CLI died on a diff
of German prose while every CI run stayed green.

**How the rule is drawn.** An earlier version recognised process calls by the
callee's bare name -- so `template.run(...)` counted and `runners["x"](...)` did
not. That is the very defect this file exists to prevent: a name asserting an
identity the check never verifies. The rule is now in two halves, and the first
one asks nothing about names:

1. **Any call that names an encoding decides one.** A call carrying `encoding=`
   or `errors=` must pin a literal UTF-8 spelling -- whatever it is called and
   however it was reached. This alone catches `subprocess.run(argv,
   encoding="cp1252")`, `errors="replace"`, and every `Path.read_text()` that
   picks a non-UTF-8 codec.
2. **A text-mode process call must pin one too.** `text=`/`universal_newlines=`
   is not exclusive to subprocess -- plenty of domain objects carry a `text`
   field -- so this half additionally requires the call to look like a process
   call: a subprocess-only keyword, or a callee that resolves to a subprocess
   entry point through import, alias, annotation, `getattr`, binder or wrapper.

**Named limit:** half 2 resolves names, not values. A callee that arrives from
another module, from a parameter, or from a container built somewhere else is
not recognised as a process call, so a bare `text=True` behind it goes
unnoticed. Half 1 is unaffected -- it never asks who is being called. Closing
half 2 completely would need type inference rather than a syntax rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_TREES = ("src", "tools", "scripts", "tests")

TEXT_MODE_KEYWORDS = ("text", "universal_newlines")
# `errors=` also enables subprocess text mode, but it is a common domain keyword
# (lists of findings), so it only counts where bytes are actually decoded.
DECODING_CALLEES = frozenset({"read_text", "write_text", "open", "decode"})
# Text file I/O without an encoding takes the platform default -- the same
# defect one layer down from subprocess. `open` is deliberately absent: the name
# also belongs to `os.open` (file descriptors, no codec) and to domain objects
# with an `open()` of their own. Where `open` DOES name a codec, half 1 still
# holds it to UTF-8.
TEXT_FILE_CALLEES = frozenset({"read_text", "write_text"})
SUBPROCESS_ENTRY_POINTS = frozenset(
    {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
)
# Keywords no non-subprocess API carries: their presence identifies a process
# call whatever the callee is named.
SUBPROCESS_ONLY_KEYWORDS = frozenset({"capture_output", "shell", "stdout", "stderr", "stdin"})
UTF8_SPELLINGS = frozenset({"utf-8", "utf8", "u8"})


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.NamedExpr):  # (execute := subprocess.run)(...)
        func = func.value
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _names_a_codec(call: ast.Call) -> bool:
    """Return whether the call decides an encoding -- half 1 of the rule."""
    return any(kw.arg == "encoding" for kw in call.keywords)


def _opens_binary(call: ast.Call) -> bool:
    """Return whether the call opens in binary mode -- nothing is decoded then."""
    mode = next(
        (kw.value for kw in call.keywords if kw.arg == "mode"),
        call.args[0] if call.args else None,
    )
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _names_error_handling(call: ast.Call, bound: set[str]) -> bool:
    """Return whether ``errors=`` here is a codec argument, not a domain field."""
    if not any(kw.arg == "errors" for kw in call.keywords):
        return False
    return _callee_name(call) in DECODING_CALLEES or _is_process_call(call, bound)


def _reads_text(call: ast.Call) -> bool:
    """Return whether the call decodes. Anything but a falsy literal counts."""
    for kw in call.keywords:
        if kw.arg not in TEXT_MODE_KEYWORDS:
            continue
        if isinstance(kw.value, ast.Constant) and not kw.value.value:
            continue
        return True
    return False


def _reaches_subprocess(value: ast.expr | None, known: set[str]) -> bool:
    if isinstance(value, ast.Attribute):
        return value.attr in SUBPROCESS_ENTRY_POINTS
    if isinstance(value, ast.Name):
        return value.id in known
    if isinstance(value, ast.IfExp):
        return _reaches_subprocess(value.body, known) or _reaches_subprocess(value.orelse, known)
    if isinstance(value, ast.Tuple | ast.List | ast.Set):
        return any(_reaches_subprocess(element, known) for element in value.elts)
    if isinstance(value, ast.Dict):
        return any(_reaches_subprocess(element, known) for element in value.values)
    if isinstance(value, ast.NamedExpr):
        return _reaches_subprocess(value.value, known)
    if isinstance(value, ast.Call):
        if _callee_name(value) == "getattr":
            return _reaches_subprocess(value.args[0], known) if value.args else False
        return any(_reaches_subprocess(arg, known) for arg in value.args)
    return False


def _bound_names(tree: ast.AST) -> set[str]:
    """Return every local name through which a subprocess entry point is reached."""
    names: set[str] = {"subprocess", "sp"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in SUBPROCESS_ENTRY_POINTS
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target if isinstance(node, ast.AnnAssign) else node.target]
            )
            if _reaches_subprocess(node.value, names):
                names.update(t.id for t in targets if isinstance(t, ast.Name))
                names.update(t.attr for t in targets if isinstance(t, ast.Attribute))
                for target in targets:
                    if isinstance(target, ast.Tuple):
                        names.update(e.id for e in target.elts if isinstance(e, ast.Name))
        # A wrapper function that forwards into subprocess IS the call site's
        # subprocess -- its callers decide the keywords.
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            isinstance(inner, ast.Call) and _reaches_subprocess(inner.func, names)
            for inner in ast.walk(node)
        ):
            names.add(node.name)
    return names


def _is_process_call(node: ast.Call, bound: set[str]) -> bool:
    keywords = {kw.arg for kw in node.keywords if kw.arg is not None}
    if keywords & SUBPROCESS_ONLY_KEYWORDS:
        return True
    if _callee_name(node) in SUBPROCESS_ENTRY_POINTS | bound:
        return True
    # `runners["x"](...)` where the container was built from subprocess, and
    # `getattr(subprocess, name)(...)` where the callee is computed.
    func = node.func
    if isinstance(func, ast.Subscript) and isinstance(func.value, ast.Name):
        return func.value.id in bound
    if isinstance(func, ast.Call) and _reaches_subprocess(func, bound):
        return True
    return any(_reaches_subprocess(arg, bound) for arg in node.args)


def _is_utf8_literal(value: ast.expr) -> bool:
    # Only a literal UTF-8 spelling counts: a name or a call could be
    # `locale.getpreferredencoding()`, which is the defect itself.
    return (
        isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and value.value.lower().replace("_", "-") in UTF8_SPELLINGS
    )


def _pins_utf8(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "encoding":
            return _is_utf8_literal(kw.value)
    # `bytes.decode("utf-8", ...)` names its codec positionally.
    return bool(call.args) and _is_utf8_literal(call.args[0])


def _offences(tree: ast.AST) -> list[tuple[int, str]]:
    bound = _bound_names(tree)
    offences: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _pins_utf8(node):
            continue
        if _names_a_codec(node) or _names_error_handling(node, bound):
            offences.append((node.lineno, "names a codec that is not literal utf-8"))
        elif _reads_text(node) and _is_process_call(node, bound):
            offences.append((node.lineno, "process text mode without a literal utf-8 encoding"))
        elif _callee_name(node) in TEXT_FILE_CALLEES and not _opens_binary(node):
            offences.append((node.lineno, "text file I/O without a pinned encoding"))
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
    assert offenders == [], "calls decoding without a pinned encoding: " + ", ".join(offenders)


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
        # `encoding=` and `errors=` enable text mode by themselves.
        'subprocess.run(argv, encoding="cp1252")',
        'subprocess.run(argv, errors="replace")',
        'subprocess.run(argv, text=False, encoding="cp1252")',
        # Reached through any indirection at all -- the rule never asks.
        "execute = subprocess.run\nexecute(argv, text=True)",
        "from subprocess import run as execute\nexecute(argv, text=True)",
        "execute: object = subprocess.run\nexecute(argv, text=True)",
        'execute = getattr(subprocess, "run")\nexecute(argv, text=True)',
        "execute, other = subprocess.run, fallback\nexecute(argv, text=True)",
        "self.execute = subprocess.run\nself.execute(argv, text=True)",
        "(execute := subprocess.run)(argv, text=True)",
        'runners = {"x": subprocess.run}\nrunners["x"](argv, text=True)',
        "getattr(subprocess, dynamic)(argv, text=True)",
        "functools.partial(subprocess.run, text=True)",
        "def execute(*a, **kw):\n    return subprocess.run(*a, **kw)\nexecute(argv, text=True)",
        "self._runner(argv, capture_output=True, text=True)",
        # File I/O picks codecs too -- half 1 does not care what is called.
        'path.read_text(encoding="cp1252")',
        "path.write_text(body, encoding=locale.getpreferredencoding())",
    )
    for source in evasions:
        assert _offences(ast.parse(source)) != [], source


def test_the_guard_accepts_what_decodes_nothing_or_pins_utf8() -> None:
    accepted = (
        'subprocess.run(argv, text=True, encoding="utf-8")',
        'subprocess.run(argv, text=True, encoding="UTF-8")',
        'subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")',
        'path.read_text(encoding="utf-8", errors="surrogateescape")',
        "subprocess.run(argv, capture_output=True)",  # bytes: nothing is decoded
        "subprocess.run(argv, capture_output=True, text=False)",
        "real_popen(*args, **kwargs)",  # forwards; decides no keyword itself
        # A domain object with a `text` field is not a process call.
        '_ChangedLine(line=1, text="a normative sentence")',
        'Message(role="user", text=body)',
    )
    for source in accepted:
        assert _offences(ast.parse(source)) == [], source
