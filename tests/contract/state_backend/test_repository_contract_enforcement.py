"""CLI-level enforcement of the repository/read-surface contract (AG3-128).

FK-07 §7.6/§7.7.5/§7.9 close the gap where public global read-model loaders of
the ``state_backend.store`` facade were not machine-enforced. These tests drive
the real ``scripts/ci/check_architecture_conformance.py`` entry point (not just
the in-process audit function) so the fail-closed CLI exit contract is proven:

* the conformant CURRENT tree exits 0 with an explicit zero-violation message
  (a warning-only exit 0 must not slip through), and
* a synthetic A-code direct-facade-access import of each pinned global read
  loader (story-context, execution-event rows, project telemetry) outside the
  allowed surface exits non-zero with an AC004 error.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_architecture_conformance.py"

# One representative pinned loader per read surface extended by AG3-128:
# a project telemetry loader, its driver-row twin, a story-context loader and a
# story execution-event driver-row loader. Each must fail closed off-surface.
_PINNED_GLOBAL_READ_LOADERS = (
    "load_execution_events_for_project_global",
    "load_execution_event_rows_for_project_global",
    "load_story_context_by_uuid_global",
    "load_execution_event_rows_global",
)


def _run_check(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the architecture-conformance CLI from the repo root."""
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_conformant_current_tree_reports_zero_violations() -> None:
    """The conformant CURRENT tree passes fail-closed with zero violations.

    Asserting the explicit zero-violation banner (not merely exit 0) guards
    against a warning-only ``OK with N warning(s)`` run slipping through.
    """
    result = _run_check()

    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "no architecture contract violations" in result.stdout, (
        f"expected explicit zero-violation banner\nstdout={result.stdout}"
    )


@pytest.mark.parametrize("loader_symbol", _PINNED_GLOBAL_READ_LOADERS)
def test_global_read_loader_direct_facade_access_fails_closed(
    tmp_path: Path, loader_symbol: str
) -> None:
    """A-code importing a pinned global read loader off-surface exits non-zero."""
    leak_root = tmp_path / "leaksrc"
    leak_module = leak_root / "agentkit" / "backend" / "kpi_analytics"
    leak_module.mkdir(parents=True)
    (leak_module / "read_model_leak.py").write_text(
        "from __future__ import annotations\n"
        "from agentkit.backend.state_backend.store.facade import (\n"
        f"    {loader_symbol},\n"
        ")\n\n\n"
        "def leak() -> object:\n"
        f"    return {loader_symbol}\n",
        encoding="utf-8",
    )

    result = _run_check("--code-root", str(leak_root))

    assert result.returncode != 0, (
        f"expected non-zero exit, got 0\nstdout={result.stdout}"
    )
    combined = result.stdout + result.stderr
    assert "AC004" in combined, combined
    assert loader_symbol in combined, combined
