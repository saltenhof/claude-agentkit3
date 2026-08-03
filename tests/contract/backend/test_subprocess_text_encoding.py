"""No text I/O may take the encoding of the machine it runs on.

``text=True`` or ``read_text()`` without ``encoding`` decodes with the
platform's preferred encoding: UTF-8 on Linux and macOS, cp1252 on a German
Windows. The same code then reads the same bytes correctly on one machine and
raises ``UnicodeDecodeError`` on another -- which is how the concept CLI died on
a diff of German prose while every CI run stayed green.

**Why this check is narrow on purpose.** Earlier versions tried to recognise a
process call through aliases, wrappers, containers and `getattr`, and to tell a
codec keyword from a domain keyword. Every widening bought one more evasion and
two more false positives -- `template.run(text=True)`, `Message(body,
encoding="base64")` -- and a false positive here is not cosmetic: this is a
blocking test, so it would stop every commit in the repository. That is the very
harm this whole change set exists to remove.

So the rule asks one question with a syntactic answer: **does this call site
name a text I/O entry point directly?** Only then is an encoding demanded.

- `subprocess.<entry>(...)` -- reached through the module, or through a name
  imported from it.
- `<anything>.read_text(...)` / `.write_text(...)` -- the `pathlib` text API.

What that deliberately does NOT catch is a call reached through an indirection
the syntax cannot resolve: a wrapper function, an injected runner, a callee from
a container. That gap is covered from the other side, semantically, by
``EncodingWarning``: the suite turns it into an error (see ``pyproject.toml``),
so any code path that actually runs and decodes without an encoding fails --
regardless of how its callee was spelled. Static narrowness plus runtime
breadth; neither alone is enough, and neither invents a defect.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_TREES = ("src", "tools", "scripts", "tests")

SUBPROCESS_ENTRY_POINTS = frozenset(
    {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
)
PATHLIB_TEXT_API = frozenset({"read_text", "write_text"})
UTF8_SPELLINGS = frozenset({"utf-8", "utf8", "u8"})


def _subprocess_module_aliases(tree: ast.AST) -> set[str]:
    """Return the names under which the `subprocess` MODULE is reachable."""
    aliases = {"subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "subprocess"
            )
    return aliases


def _subprocess_function_names(tree: ast.AST) -> set[str]:
    """Return names bound by `from subprocess import run [as x]`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in SUBPROCESS_ENTRY_POINTS
            )
    return names


def _is_text_io_call(node: ast.Call, modules: set[str], functions: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in PATHLIB_TEXT_API:
            return True
        return (
            func.attr in SUBPROCESS_ENTRY_POINTS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        )
    return isinstance(func, ast.Name) and func.id in functions


def _decodes(node: ast.Call) -> bool:
    """Return whether this text I/O call actually decodes on this call path."""
    if isinstance(node.func, ast.Attribute) and node.func.attr in PATHLIB_TEXT_API:
        return True  # the pathlib text API always decodes
    for kw in node.keywords:
        if kw.arg in {"text", "universal_newlines", "encoding", "errors"} and not (
            isinstance(kw.value, ast.Constant) and not kw.value.value
        ):
            return True
    return False


def _pins_utf8(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "encoding":
            # Only a literal UTF-8 spelling counts: a name or a call could be
            # `locale.getpreferredencoding()`, which is the defect itself.
            return (
                isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
                and kw.value.value.lower().replace("_", "-") in UTF8_SPELLINGS
            )
    return False


def _offences(tree: ast.AST) -> list[tuple[int, str]]:
    modules = _subprocess_module_aliases(tree)
    functions = _subprocess_function_names(tree)
    return [
        (node.lineno, "text I/O without a literal utf-8 encoding")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _is_text_io_call(node, modules, functions)
        and _decodes(node)
        and not _pins_utf8(node)
    ]


def test_no_text_io_relies_on_the_platform_encoding() -> None:
    offenders: list[str] = []
    for tree_name in SCANNED_TREES:
        for path in sorted((REPO_ROOT / tree_name).rglob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: {reason}"
                for line, reason in _offences(module)
            )
    assert offenders == [], "text I/O without a pinned encoding: " + ", ".join(offenders)


def test_the_rule_catches_what_it_claims_to_catch() -> None:
    caught = (
        "import subprocess\nsubprocess.run(argv, text=True)",
        "import subprocess\nsubprocess.run(argv, text=True, encoding=None)",
        'import subprocess\nsubprocess.run(argv, text=True, encoding="cp1252")',
        "import subprocess\nsubprocess.run(argv, text=True, encoding=locale.getpreferredencoding())",
        "import subprocess\nsubprocess.run(argv, universal_newlines=True)",
        "import subprocess\nsubprocess.run(argv, text=1)",
        'import subprocess\nsubprocess.run(argv, encoding="cp1252")',
        'import subprocess\nsubprocess.run(argv, errors="replace")',
        "import subprocess as sp\nsp.run(argv, text=True)",
        "from subprocess import run\nrun(argv, text=True)",
        "from subprocess import run as execute\nexecute(argv, text=True)",
        "path.read_text()",
        'path.write_text("Groesse bei github.com")',
        'path.read_text(encoding="cp1252")',
    )
    for source in caught:
        assert _offences(ast.parse(source)) != [], source


def test_the_rule_invents_no_defect() -> None:
    """A false positive here blocks every commit -- it must stay impossible."""
    accepted = (
        'import subprocess\nsubprocess.run(argv, text=True, encoding="utf-8")',
        'import subprocess\nsubprocess.run(argv, text=True, encoding="UTF-8")',
        "import subprocess\nsubprocess.run(argv, capture_output=True)",  # bytes
        "import subprocess\nsubprocess.run(argv, capture_output=True, text=False)",
        'path.read_text(encoding="utf-8")',
        'path.write_text(body, encoding="utf-8", errors="surrogateescape")',
        # Domain calls that merely share a keyword or a method name.
        "template.run(text=True)",
        "client.call(payload, text=True)",
        'Message(body, encoding="base64")',
        '_ChangedLine(line=1, text="a normative sentence")',
        "self._runner(argv, capture_output=True, text=True)",
        "real_popen(*args, **kwargs)",
        "os.open(path, os.O_CREAT | os.O_EXCL)",
    )
    for source in accepted:
        assert _offences(ast.parse(source)) == [], source


def test_the_runtime_half_is_armed_when_the_flag_is_set() -> None:
    """Prove the semantic net exists rather than assuming it.

    The static rule above is deliberately narrow; the runtime half is what
    covers what it cannot see. A net nobody verified is not a net: this asserts
    that with ``PYTHONWARNDEFAULTENCODING=1`` an unpinned read really does raise
    here, and says plainly when the flag is off (CI sets it -- see Jenkinsfile).
    """
    import sys
    import warnings

    if not sys.flags.warn_default_encoding:
        pytest.skip("PYTHONWARNDEFAULTENCODING=1 not set -- the runtime half is off")

    probe = REPO_ROOT / "pyproject.toml"
    with warnings.catch_warnings():
        warnings.simplefilter("error", EncodingWarning)
        with pytest.raises(EncodingWarning), probe.open() as handle:  # noqa: PLW1514
            handle.read()  # the defect, committed on purpose, one line deep
