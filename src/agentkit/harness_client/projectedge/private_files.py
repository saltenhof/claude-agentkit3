"""Effective owner-only permissions for ProjectEdge credential files."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import local
from typing import TYPE_CHECKING, BinaryIO, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterator


class PrivateFileSecurityError(RuntimeError):
    """Effective owner-only file protection could not be established."""


class PrivateFileLockBusyError(RuntimeError):
    """Another process owns the credential lifecycle lock."""


_POSIX_PRIVATE_MODE = 0o600
_WINDOWS_FULL_CONTROL = 2_032_127
_THREAD_LOCK_STATE = local()


class PrivateFileSecurity(BaseModel):
    """Measured effective protection of one secret-bearing file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: Literal["posix", "windows"]
    owner_only: bool
    mode: int | None = None
    owner_sid: str | None = None
    access_entry_count: int | None = None


def atomic_write_private_text(path: Path, content: str) -> PrivateFileSecurity:
    """Publish UTF-8 text only after measuring owner-only protection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        _POSIX_PRIVATE_MODE,
    )
    os.close(descriptor)
    try:
        apply_private_file_security(temporary)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        measured = inspect_private_file_security(temporary)
        if not measured.owner_only:
            raise PrivateFileSecurityError(
                f"Secret file is not restricted to its owner: {temporary}",
            )
        os.replace(temporary, path)
        return measured
    finally:
        temporary.unlink(missing_ok=True)


def apply_private_file_security(path: Path) -> None:
    """Apply effective owner-only protection for the current platform."""
    if sys.platform == "win32":
        _apply_windows_private_acl(path)
        return
    path.chmod(_POSIX_PRIVATE_MODE)


def inspect_private_file_security(path: Path) -> PrivateFileSecurity:
    """Measure effective owner-only protection for the current platform."""
    if sys.platform == "win32":
        return _inspect_windows_private_acl(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    return PrivateFileSecurity(
        platform="posix",
        owner_only=mode == _POSIX_PRIVATE_MODE,
        mode=mode,
    )


@contextmanager
def exclusive_private_file_lock(path: Path) -> Iterator[None]:
    """Acquire a non-blocking cross-process lock for one credential lifecycle.

    A concurrent operator command fails visibly instead of waiting and then
    interpreting the successor state as a request for another token rotation.
    The operating system releases the lock automatically when a process exits.
    """
    lock_key = str(path.resolve())
    depths = _thread_lock_depths()
    if depths.get(lock_key, 0) > 0:
        depths[lock_key] += 1
        try:
            yield
        finally:
            depths[lock_key] -= 1
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+b") as handle:
        try:
            _lock_file_nonblocking(handle)
        except OSError as exc:
            raise PrivateFileLockBusyError(
                f"Credential operation is already in progress: {path}",
            ) from exc
        depths[lock_key] = 1
        try:
            yield
        finally:
            depths.pop(lock_key, None)
            _unlock_file(handle)


def _thread_lock_depths() -> dict[str, int]:
    depths = getattr(_THREAD_LOCK_STATE, "credential_lock_depths", None)
    if depths is None:
        depths = {}
        _THREAD_LOCK_STATE.credential_lock_depths = depths
    return depths


def _lock_file_nonblocking(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _apply_windows_private_acl(path: Path) -> None:
    script = """
$ErrorActionPreference = 'Stop'
$target = $env:AGENTKIT_PRIVATE_FILE_TARGET
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.FileSecurity
$acl.SetOwner($identity)
$acl.SetAccessRuleProtection($true, $false)
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    $identity,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    [System.Security.AccessControl.AccessControlType]::Allow
)
$acl.AddAccessRule($rule)
[System.IO.File]::SetAccessControl($target, $acl)
"""
    _run_windows_security_script(script, path)


def _inspect_windows_private_acl(path: Path) -> PrivateFileSecurity:
    script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$target = $env:AGENTKIT_PRIVATE_FILE_TARGET
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$acl = [System.IO.File]::GetAccessControl($target)
$entries = @($acl.Access | ForEach-Object {
    [PSCustomObject]@{
        sid = $_.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        rights = [int]$_.FileSystemRights
        access_type = $_.AccessControlType.ToString()
        inherited = [bool]$_.IsInherited
    }
})
[PSCustomObject]@{
    current_sid = $currentSid
    entries = $entries
} | ConvertTo-Json -Compress -Depth 4
"""
    raw = _run_windows_security_script(script, path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PrivateFileSecurityError(
            f"Windows ACL measurement returned invalid JSON for {path}",
        ) from exc
    if not isinstance(payload, dict):
        raise PrivateFileSecurityError(
            f"Windows ACL measurement returned an invalid object for {path}",
        )
    current_sid = payload.get("current_sid")
    entries = payload.get("entries")
    if not isinstance(current_sid, str) or not isinstance(entries, list):
        raise PrivateFileSecurityError(
            f"Windows ACL measurement omitted required fields for {path}",
        )
    return PrivateFileSecurity(
        platform="windows",
        owner_only=_windows_acl_is_owner_only(current_sid, entries),
        owner_sid=current_sid,
        access_entry_count=len(entries),
    )


def _windows_acl_is_owner_only(current_sid: str, entries: list[object]) -> bool:
    if len(entries) != 1 or not isinstance(entries[0], dict):
        return False
    entry = entries[0]
    rights = entry.get("rights")
    return (
        entry.get("sid") == current_sid
        and entry.get("access_type") == "Allow"
        and entry.get("inherited") is False
        and isinstance(rights, int)
        and rights & _WINDOWS_FULL_CONTROL == _WINDOWS_FULL_CONTROL
    )


def _run_windows_security_script(script: str, path: Path) -> str:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise PrivateFileSecurityError("SystemRoot is unavailable for Windows ACL enforcement")
    executable = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    process_environment = os.environ.copy()
    process_environment["AGENTKIT_PRIVATE_FILE_TARGET"] = str(path.resolve())
    try:
        completed = subprocess.run(
            [
                str(executable),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=process_environment,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
        raise PrivateFileSecurityError(
            f"Windows ACL operation failed for {path}: {detail}",
        ) from exc
    except OSError as exc:
        raise PrivateFileSecurityError(
            f"Windows ACL tooling is unavailable for {path}",
        ) from exc
    return completed.stdout.strip()


__all__ = [
    "PrivateFileSecurity",
    "PrivateFileSecurityError",
    "PrivateFileLockBusyError",
    "apply_private_file_security",
    "atomic_write_private_text",
    "exclusive_private_file_lock",
    "inspect_private_file_security",
]
