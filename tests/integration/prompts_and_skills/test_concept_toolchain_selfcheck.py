"""Self-check: the bundled concept toolchain must pass the real AK3 corpus.

Acceptance criterion for project neutrality (FK-78 section 78.14): the
generic engine, configured only through this repository's
``concept/_meta/concept-governance.json``, validates the AK3 concept
corpus green. AK3-specific lints (tag corpus, index completeness,
domain-registry rules) intentionally live outside the engine.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = (
    REPO_ROOT / "src" / "agentkit" / "bundles" / "target_project" / "tools" / "agentkit" / "concept_toolchain" / "check.py"
)


def run_check(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--project-root", str(REPO_ROOT), command],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("command", ["frontmatter", "formal"])
def test_selfcheck_against_repo_corpus(command: str) -> None:
    completed = run_check(command)
    assert completed.returncode == 0, (
        f"check.py {command} against the AK3 corpus failed with exit {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert f"[{command}] OK" in completed.stdout
