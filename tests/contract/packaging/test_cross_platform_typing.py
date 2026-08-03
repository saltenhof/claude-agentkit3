"""Contract: the package type-checks for every TARGET platform, not just this one.

``mypy`` resolves platform-gated stdlib surfaces (``ctypes.WinDLL``,
``ctypes.get_last_error``, ``os.getuid`` …) against the platform it runs on.
A Windows-local run therefore reports clean for code that the Linux CI rejects,
and vice versa — the failure is invisible until the pipeline breaks, and it
breaks in a stage that runs AFTER the developer has already reported "mypy
clean".

This test closes that gap locally by asking ``mypy`` for the other platforms
explicitly. It is the reason a platform-gated surface must narrow on
``sys.platform`` INLINE (narrowing does not travel through a helper call).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The platforms AK3 is type-checked for. ``win32`` is covered by the default
#: project run; the others are what the CI actually executes on.
_TARGET_PLATFORMS = ("linux", "darwin")


@pytest.mark.parametrize("platform", _TARGET_PLATFORMS)
def test_src_type_checks_for_target_platform(platform: str) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "mypy",
            "src",
            "--strict",
            "--no-error-summary",
            "--platform",
            platform,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # `PYTHONWARNINGS=error::EncodingWarning` is set for the suite so AK3's
        # own CLI children fail on an unpinned read. mypy is NOT AK3's code and
        # carries such a read itself: inherited, the escalation aborts it with
        # exit 2 on a defect nobody here can fix. The variable is dropped at
        # this one FOREIGN boundary, named -- not switched off for everyone.
        env={k: v for k, v in os.environ.items() if k != "PYTHONWARNINGS"},
        check=False,
    )
    assert completed.returncode == 0, (
        f"mypy --platform {platform} rejected the package. A platform-gated "
        f"surface most likely lacks an INLINE `sys.platform` guard:\n{completed.stdout}"
    )
