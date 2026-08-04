"""Effective owner-only permissions for secret-bearing files."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PrivateFileSecurityError(RuntimeError):
    """Effective owner-only file protection could not be established."""


_POSIX_PRIVATE_MODE = 0o600
_WINDOWS_FULL_CONTROL = 2_032_127


class PrivateFileSecurity(BaseModel):
    """Measured effective protection of one secret-bearing file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: Literal["posix", "windows"]
    owner_only: bool
    mode: int | None = None
    owner_sid: str | None = None
    access_entry_count: int | None = None


def atomic_write_private_text(path: Path, content: str) -> PrivateFileSecurity:
    """Atomically replace ``path`` with UTF-8 text protected for its owner.

    The temporary file receives effective owner-only protection before secret
    bytes are written. Publication is one atomic rename, so readers observe
    either the previous complete file or the new complete file.

    Args:
        path: Destination file.
        content: UTF-8 text to persist.

    Returns:
        The effective protection measured after publication.

    Raises:
        PrivateFileSecurityError: If owner-only protection cannot be applied or
            measured.
    """
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
    owner_only = _windows_acl_is_owner_only(current_sid, entries)
    return PrivateFileSecurity(
        platform="windows",
        owner_only=owner_only,
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
    "apply_private_file_security",
    "atomic_write_private_text",
    "inspect_private_file_security",
]
