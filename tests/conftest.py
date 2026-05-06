from __future__ import annotations

import contextlib
import os
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TOOLS_ROOT = REPO_ROOT / "tools"
PYTEST_TEMP_ROOT = REPO_ROOT / "tmp" / "pytest-temproot"
PROMPT_BUNDLE_STORE_ENV = "AGENTKIT_PROMPT_BUNDLE_STORE_ROOT"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
os.environ.setdefault("AGENTKIT_STATE_BACKEND", "sqlite")
os.environ.setdefault("AGENTKIT_ALLOW_SQLITE", "1")
if os.name == "nt":
    PYTEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(PYTEST_TEMP_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolate_prompt_bundle_store(tmp_path_factory: pytest.TempPathFactory) -> None:
    os.environ.setdefault(
        PROMPT_BUNDLE_STORE_ENV,
        str(tmp_path_factory.mktemp("prompt-bundle-store")),
    )


def _needs_windows_mkdir_compat() -> bool:
    """Detect sandboxed Windows environments where mkdir(mode=0o700) is unreadable."""
    if os.name != "nt":
        return False

    probe_root = REPO_ROOT / "tmp"
    probe_root.mkdir(exist_ok=True)
    probe = probe_root / f".pytest-mode-probe-{uuid.uuid4().hex}"

    try:
        os.mkdir(probe, 0o700)
        try:
            os.listdir(probe)
            return False
        except PermissionError:
            return True
    finally:
        with contextlib.suppress(OSError):
            os.chmod(probe, 0o777)
        with contextlib.suppress(OSError):
            probe.rmdir()


if _needs_windows_mkdir_compat():
    _ORIGINAL_OS_MKDIR = os.mkdir

    def _compat_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        """Avoid unreadable temp dirs from os.mkdir(..., 0o700)."""
        if dir_fd is not None:
            _ORIGINAL_OS_MKDIR(path, mode, dir_fd=dir_fd)
            return

        if mode == 0o777:
            _ORIGINAL_OS_MKDIR(path, mode)
            return

        _ORIGINAL_OS_MKDIR(path)
        with contextlib.suppress(OSError):
            os.chmod(path, mode)

    os.mkdir = _compat_mkdir
