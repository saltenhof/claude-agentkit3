"""Durable recovery journal for uncertain VectorDB completion commits."""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from agentkit.backend.installer.file_ops import atomic_write_text
from agentkit.integration_clients.vectordb.errors import VectorDbWriteError

_RUN_ID = re.compile(r"^[0-9a-f]{64}$")
_JOURNAL_ENTRY_SUFFIX = ".json"
_ATOMIC_WRITE_TEMP_SUFFIX = ".tmp"
_RECOVERY_RELATIVE_PATH = Path(
    ".agentkit",
    "receipts",
    "vectordb",
    "pending-commits",
)


class CommitRecoveryState(StrEnum):
    """The only durable outcomes that can remain after a commit attempt."""

    OUTCOME_UNKNOWN = "outcome_unknown"
    NOT_COMMITTED = "not_committed"


class CompletionCommitJournalEntry(BaseModel):
    """Exact position-bound attempt and its durable recovery classification."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    state: CommitRecoveryState
    project_id: StrictStr
    run_id: StrictStr
    record_uuid: StrictStr
    properties: dict[StrictStr, StrictStr]


class FileCommitRecoveryJournal:
    """One strict, atomic state-machine record per deterministic run."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def stage_unknown(self, entry: CompletionCommitJournalEntry) -> None:
        """Persist an exact attempt as outcome-unknown before conditional create."""
        if entry.state is not CommitRecoveryState.OUTCOME_UNKNOWN:
            raise VectorDbWriteError(
                "only an outcome_unknown commit entry can be staged"
            )
        self._write(entry)

    def finish_committed(self, run_id: str) -> None:
        """Finish COMMITTED by durably removing its recovery-capable entry."""
        path = self._path(run_id)
        if path.is_symlink():
            raise VectorDbWriteError(
                f"completion recovery journal entry became a symlink: {path}"
            )
        if path.exists():
            path.unlink()
        if self.root.exists():
            with suppress(OSError):
                self.root.rmdir()

    def finish_not_committed(
        self,
        entry: CompletionCommitJournalEntry,
    ) -> None:
        """Finish definitively NOT COMMITTED; this entry is never recoverable."""
        if entry.state is not CommitRecoveryState.OUTCOME_UNKNOWN:
            raise VectorDbWriteError(
                "only an outcome_unknown commit can finish as not_committed"
            )
        current = self._load_path(self._path(entry.run_id))
        if current != entry:
            raise VectorDbWriteError(
                "completion recovery transition does not match the staged attempt"
            )
        terminal = entry.model_copy(
            update={"state": CommitRecoveryState.NOT_COMMITTED}
        )
        self._write(terminal)

    def list_pending(
        self,
        project_id: str,
    ) -> tuple[CompletionCommitJournalEntry, ...]:
        """Load only genuine outcome-unknown entries for recovery."""
        entries = self._load_all()
        return tuple(
            entry
            for entry in entries
            if entry.project_id == project_id
            and entry.state is CommitRecoveryState.OUTCOME_UNKNOWN
        )

    def _write(self, entry: CompletionCommitJournalEntry) -> None:
        path = self._path(entry.run_id)
        if self.root.exists() and (
            self.root.is_symlink() or not self.root.is_dir()
        ):
            raise VectorDbWriteError("completion recovery journal root is invalid")
        created_directories = _create_directory_tree(path.parent)
        if self.root.is_symlink() or not self.root.is_dir() or path.is_symlink():
            raise VectorDbWriteError("completion recovery journal path is invalid")
        for directory in created_directories:
            _sync_directory(directory.parent)
        rendered = json.dumps(
            entry.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        atomic_write_text(path, rendered + "\n", newline="")
        _sync_directory(self.root)

    def _load_all(self) -> tuple[CompletionCommitJournalEntry, ...]:
        if not self.root.exists():
            return ()
        if self.root.is_symlink() or not self.root.is_dir():
            raise VectorDbWriteError("completion recovery journal root is invalid")
        entries: list[CompletionCommitJournalEntry] = []
        for path in sorted(self.root.iterdir()):
            if _is_journal_atomic_write_temp(path):
                if path.is_symlink() or (path.exists() and not path.is_file()):
                    raise VectorDbWriteError(
                        f"completion recovery journal entry is invalid: {path}"
                    )
                continue
            if (
                path.suffix != _JOURNAL_ENTRY_SUFFIX
                or path.is_symlink()
                or not path.is_file()
            ):
                raise VectorDbWriteError(
                    f"completion recovery journal entry is invalid: {path}"
                )
            entries.append(self._load_path(path))
        return tuple(entries)

    @staticmethod
    def _load_path(path: Path) -> CompletionCommitJournalEntry:
        try:
            return CompletionCommitJournalEntry.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise VectorDbWriteError(
                f"invalid completion recovery journal entry {path}: {exc}"
            ) from exc

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise VectorDbWriteError("completion run_id is not a lowercase SHA-256")
        return self.root / f"{run_id}{_JOURNAL_ENTRY_SUFFIX}"


def _is_journal_atomic_write_temp(path: Path) -> bool:
    """Recognize only this journal's transient ``atomic_write_text`` artifact."""
    if path.suffix != _ATOMIC_WRITE_TEMP_SUFFIX:
        return False
    target = path.with_suffix("")
    return (
        target.suffix == _JOURNAL_ENTRY_SUFFIX
        and _RUN_ID.fullmatch(target.stem) is not None
        and path == target.with_suffix(target.suffix + _ATOMIC_WRITE_TEMP_SUFFIX)
    )


def _create_directory_tree(path: Path) -> tuple[Path, ...]:
    """Create a directory tree and return new directories from parent to leaf."""
    missing: list[Path] = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        parent = candidate.parent
        if parent == candidate:
            raise OSError(
                f"completion recovery filesystem anchor is unavailable: {candidate}"
            )
        candidate = parent
    path.mkdir(parents=True, exist_ok=True)
    return tuple(reversed(missing))


def _sync_directory(path: Path) -> None:
    """Make the journal rename durable before a remote commit may begin."""
    if os.name == "nt":
        _sync_windows_directory(path)
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_windows_directory(path: Path) -> None:
    """Flush a Windows directory handle opened for metadata writes."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = [wintypes.HANDLE]
    flush_file_buffers.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_write = 0x40000000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    backup_semantics = 0x02000000
    handle = create_file(
        str(path),
        generic_write,
        share_all,
        None,
        open_existing,
        backup_semantics,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot open journal directory for flush: {path}")
    flushed = bool(flush_file_buffers(handle))
    flush_error = ctypes.get_last_error()
    closed = bool(close_handle(handle))
    close_error = ctypes.get_last_error()
    if not flushed:
        raise OSError(flush_error, f"cannot flush journal directory: {path}")
    if not closed:
        raise OSError(close_error, f"cannot close journal directory handle: {path}")


def project_commit_recovery_journal(project_root: Path) -> FileCommitRecoveryJournal:
    """Bind the durable commit owner to one existing project root."""
    try:
        resolved = project_root.resolve(strict=True)
    except OSError as exc:
        raise VectorDbWriteError(
            f"completion recovery project root is unavailable: {project_root}"
        ) from exc
    if not resolved.is_dir():
        raise VectorDbWriteError(
            f"completion recovery project root is not a directory: {resolved}"
        )
    return FileCommitRecoveryJournal(resolved / _RECOVERY_RELATIVE_PATH)


__all__ = [
    "CommitRecoveryState",
    "CompletionCommitJournalEntry",
    "FileCommitRecoveryJournal",
    "project_commit_recovery_journal",
]
