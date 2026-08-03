"""No text I/O may take the encoding of the machine it runs on.

``text=True`` or ``read_text()`` without ``encoding`` decodes with the
platform's preferred encoding: UTF-8 on Linux and macOS, cp1252 on a German
Windows. The same code then reads the same bytes correctly on one machine and
raises ``UnicodeDecodeError`` on another -- which is how the concept CLI died on
a diff of German prose while every CI run stayed green.

**Why there is no static check here any more.** Three versions of an AST guard
were written and each one was defeated twice over: an evasion it could not see,
and a false positive it invented. It classified `template.run(text=True)` and
`document_api.read_text(format="markdown")` as text I/O because their *names*
matched -- the exact fault this rule exists to prevent, now committed by the
rule itself. A false positive in a blocking test is not cosmetic: it stops every
commit in the repository, which is the same harm as the defect. A check that
asserts something it cannot know is worse than no check, so it is gone.

What remains is the mechanism Python provides for precisely this defect, and it
is semantic rather than syntactic:

* ``PYTHONWARNDEFAULTENCODING=1`` makes the interpreter emit ``EncodingWarning``
  at every call site that decodes without an encoding -- whatever the callee is
  named, however it was reached, including through wrappers and injected
  runners that no syntax rule resolves.
* ``pyproject.toml`` turns that warning into a failure for THIS interpreter.
* ``PYTHONWARNINGS=error::EncodingWarning`` does the same across the process
  boundary, where a pytest filter has no reach. The tests below spawn a real
  child both ways and prove it, rather than assuming the variable works.

**Two named limits, both measured, neither talked away:**

1. *Only code that runs is seen.* Coverage is the bound -- an unexecuted branch
   stays unchecked. That is the honest trade against a syntactic rule that
   mislabels working code.
2. *The escalation is not set globally in CI.* ``PYTHONWARNINGS`` reaches every
   child, including third-party tools AK3 does not own and cannot fix: with it
   set, ``mypy`` aborts on its own unpinned read (exit 2, reproduced here).
   Scoping the filter to the ``agentkit`` package is not possible either -- a
   filter's module field is compiled to an EXACT match, so a package prefix
   never applies. CI therefore sets ``PYTHONWARNDEFAULTENCODING=1`` (the
   warnings appear) and escalates in-process; AK3 CLIs spawned by a test are
   covered where that test opts in, as here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WARNING_ENV = {"PYTHONWARNDEFAULTENCODING": "1", "PYTHONWARNINGS": "error::EncodingWarning"}


def test_the_interpreter_reports_unpinned_reads_in_process() -> None:
    """Prove the net is armed here, rather than assuming the flag does anything."""
    if not sys.flags.warn_default_encoding:
        pytest.skip("PYTHONWARNDEFAULTENCODING=1 not set -- see Jenkinsfile / CONTRIBUTING")

    probe = REPO_ROOT / "pyproject.toml"
    with warnings.catch_warnings():
        warnings.simplefilter("error", EncodingWarning)
        with pytest.raises(EncodingWarning), probe.open() as handle:  # noqa: PLW1514
            handle.read()  # the defect, on purpose, one line deep


@pytest.mark.requires_git
def test_a_child_process_fails_on_an_unpinned_read(tmp_path: Path) -> None:
    """The rule must survive the process boundary.

    A pytest ``filterwarnings`` entry configures the PARENT interpreter only. A
    CLI spawned by an integration test would write its warning to stderr and
    still exit 0 -- green suite, blind decoding. ``PYTHONWARNINGS`` is inherited
    through the environment, so the child fails where the parent would.
    """
    script = tmp_path / "reads_blind.py"
    script.write_text(
        textwrap.dedent(
            """
            import pathlib, sys
            target = pathlib.Path(sys.argv[1])
            with target.open() as handle:   # no encoding: the defect
                handle.read()
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "data.txt").write_text("content\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "data.txt")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **WARNING_ENV},
        check=False,
        timeout=60,
    )

    assert completed.returncode != 0, "a child decoded without an encoding and still passed"
    assert "EncodingWarning" in completed.stderr


@pytest.mark.requires_git
def test_a_child_process_passes_when_the_encoding_is_pinned(tmp_path: Path) -> None:
    """The counterpart: the rule must not fail correct code."""
    script = tmp_path / "reads_pinned.py"
    script.write_text(
        textwrap.dedent(
            """
            import pathlib, sys
            pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "data.txt").write_text("content\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "data.txt")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **WARNING_ENV},
        check=False,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
