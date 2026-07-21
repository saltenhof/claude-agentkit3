"""Process lifecycle, minimal env, and tree teardown (AG3-164).

Blutgruppe T: platform process control.

* POSIX: new session (process group) + SIGTERM/SIGKILL on the group.
* Windows: Job Object with KILL_ON_JOB_CLOSE. The root is created
  ``CREATE_SUSPENDED``, assigned to the job, then resumed — so children
  cannot escape before job membership.

Process identities use PID + create_time with revalidation immediately
before kill (no PID-reuse TOCTOU). All waits use the remaining deadline
budget only (no forced minimum wait when the budget is exhausted).

Fail-closed: if the process-control plane cannot be established or
terminated, :class:`ProcessControlError` is raised — there is no silent
fallback to a weaker kill strategy.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import psutil  # type: ignore[import-untyped]

from agentkit.backend.installer.mcp_conformance.types import (
    POSIX_BASE_ENV_KEYS,
    WIN_BASE_ENV_KEYS,
    ProcessIdentity,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_TERMINATE_GRACE_SECONDS: Final = 2.0
_GRACEFUL_EXIT_SECONDS: Final = 1.0
_CREATE_SUSPENDED: Final = 0x00000004
_THREAD_SUSPEND_RESUME: Final = 0x0002
_TH32CS_SNAPTHREAD: Final = 0x00000004
_INVALID_HANDLE_VALUE: Final = -1


class ProcessControlError(Exception):
    """Process-tree control plane failed (job/group create, assign, terminate)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def merge_control_details(*parts: str) -> str:
    """Join primary and cleanup control-plane fault details for public diagnosis."""
    return "; ".join(part for part in parts if part)


def remaining_budget(deadline: float) -> float:
    """Non-negative seconds remaining until ``deadline``."""
    return max(0.0, deadline - time.monotonic())


def build_minimal_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    """Minimal child env: platform base keys + explicit entry env only."""
    keys = WIN_BASE_ENV_KEYS if sys.platform == "win32" else POSIX_BASE_ENV_KEYS
    env: dict[str, str] = {}
    for key in keys:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def resolve_command(command: str, *, cwd: str | Path | None) -> str | None:
    """Resolve command against ``cwd`` for relative paths; PATH for bare names."""
    import shutil

    if not command or not command.strip():
        return None

    candidate = Path(command)
    base = Path(cwd) if cwd is not None else Path.cwd()

    if candidate.is_absolute():
        return str(candidate) if candidate.is_file() else None

    has_sep = os.sep in command or (os.altsep is not None and os.altsep in command)
    if has_sep or command.startswith("."):
        resolved = (base / candidate).resolve()
        return str(resolved) if resolved.is_file() else None

    under_cwd = (base / candidate).resolve()
    if under_cwd.is_file():
        return str(under_cwd)

    return shutil.which(command)


def identity_of(pid: int) -> ProcessIdentity | None:
    """Snapshot PID + create_time, or None if the process is gone."""
    try:
        proc = psutil.Process(pid)
        return ProcessIdentity(pid=pid, create_time=float(proc.create_time()))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


class ProcessSupervisor:
    """Owns one MCP probe process and its platform tree scope."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        self.root_identity: ProcessIdentity | None = None
        self._tracked: set[ProcessIdentity] = set()
        self._job: int | None = None
        self._pgid: int | None = None
        # Optional test hooks (boundary fakes for non-forcible Win32 faults).
        self._job_factory: Any = None
        self._assign_hook: Any = None
        self._resume_hook: Any = None
        self._terminate_hook: Any = None
        self._close_hook: Any = None

    def start(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        cwd: str | None,
        deadline: float | None = None,
    ) -> None:
        """Launch the process under the platform tree scope.

        Fail-closed: any inability to establish the job/group control plane
        raises :class:`ProcessControlError` after cleaning partial state.

        ``deadline`` bounds controlled waits after the OS ``Popen`` returns
        (e.g. assign/resume failure cleanup). The synchronous ``Popen`` itself
        remains outside this budget on platforms that do not interrupt it.
        """
        # Capture requested cleanup span before any OS launch work so a slow
        # Popen cannot burn the post-Popen assign/resume failure budget.
        effective_deadline = (
            deadline if deadline is not None else time.monotonic() + 30.0
        )
        cleanup_budget_s = remaining_budget(effective_deadline)
        if sys.platform == "win32":
            self._start_windows(
                argv,
                env=env,
                cwd=cwd,
                cleanup_budget_s=cleanup_budget_s,
            )
        else:
            self._start_posix(argv, env=env, cwd=cwd)
        self.refresh_tree()

    def _start_posix(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        cwd: str | None,
    ) -> None:
        try:
            self.proc = subprocess.Popen(  # noqa: S603
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                env=env,
                cwd=cwd,
                bufsize=0,
                start_new_session=True,
            )
        except OSError:
            self._reset_control_state()
            raise
        self.root_identity = identity_of(self.proc.pid)
        if self.root_identity is not None:
            self._tracked.add(self.root_identity)
        self._pgid = self.proc.pid

    def _start_windows(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        cwd: str | None,
        cleanup_budget_s: float,
    ) -> None:
        factory = self._job_factory or _create_windows_job
        try:
            self._job = factory()
        except ProcessControlError:
            self._reset_control_state()
            raise
        if self._job is None:
            self._reset_control_state()
            raise ProcessControlError("Windows Job Object creation returned no handle.")

        try:
            self.proc = subprocess.Popen(  # noqa: S603
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                env=env,
                cwd=cwd,
                bufsize=0,
                creationflags=_CREATE_SUSPENDED,
            )
        except OSError as popen_err:
            # Best-effort close; CloseHandle failure is ProcessControlError so a
            # leaked job handle is never silent (AC 6 / review-5 P1-3).
            try:
                self._close_job_handle()
            except ProcessControlError as close_err:
                self._reset_control_state()
                raise ProcessControlError(
                    merge_control_details(
                        f"Job close failed after Popen error: {close_err.detail}",
                        f"Popen error: {popen_err}",
                    )
                ) from popen_err
            self._reset_control_state()
            raise popen_err

        # FK-50 / review-6 P1-2: re-arm cleanup budget after Popen returns so a
        # slow OS launch cannot exhaust kill/wait for assign/resume failures.
        cleanup_deadline = time.monotonic() + max(0.0, cleanup_budget_s)

        try:
            assign = self._assign_hook or _assign_windows_job
            assign(self._job, self.proc)
            resume = self._resume_hook or _resume_suspended_process
            resume(self.proc.pid)
        except ProcessControlError as primary:
            with contextlib.suppress(OSError):
                self.proc.kill()
            wait = remaining_budget(cleanup_deadline)
            if wait > 0:
                with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                    self.proc.wait(timeout=wait)
            self._close_pipes()
            close_error: ProcessControlError | None = None
            try:
                self._close_job_handle()
            except ProcessControlError as ce:
                close_error = ce
            self.proc = None
            self._reset_control_state()
            # Public detail must carry primary AND cleanup faults (review-6 P1-1).
            if close_error is not None:
                raise ProcessControlError(
                    merge_control_details(primary.detail, close_error.detail)
                ) from close_error
            raise primary

        self.root_identity = identity_of(self.proc.pid)
        if self.root_identity is not None:
            self._tracked.add(self.root_identity)

    def refresh_tree(self) -> None:
        """Record live descendants of the root (identity capture for secondary kill)."""
        if self.root_identity is None:
            return
        try:
            root = psutil.Process(self.root_identity.pid)
            if float(root.create_time()) != self.root_identity.create_time:
                return
            for child in root.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    self._tracked.add(
                        ProcessIdentity(
                            pid=child.pid, create_time=float(child.create_time())
                        )
                    )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    def shutdown(self, *, deadline: float, graceful: bool) -> None:
        """Terminate the whole tree within the remaining deadline budget.

        Always closes platform control handles, even when ``proc`` is None
        (P1-1: launch failures must not leak job handles). Primary control-plane
        faults are retained and re-raised after best-effort secondary kill and
        handle close so resources are not abandoned.
        """
        control_error: ProcessControlError | None = None
        try:
            if self.proc is not None:
                self.refresh_tree()

                if graceful and self.proc.poll() is None and self.proc.stdin is not None:
                    with contextlib.suppress(OSError, ValueError):
                        self.proc.stdin.close()
                    grace = min(_GRACEFUL_EXIT_SECONDS, remaining_budget(deadline))
                    if grace > 0:
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            self.proc.wait(timeout=grace)
                        self.refresh_tree()

                # Platform-primary kill — record control-plane failure, continue
                # cleanup, re-raise after secondary kill + handle close.
                try:
                    if sys.platform == "win32":
                        if self._job is not None:
                            terminate = self._terminate_hook or _terminate_windows_job
                            terminate(self._job, deadline=deadline)
                    elif self._pgid is not None:
                        _kill_posix_group(self._pgid, deadline=deadline)
                except ProcessControlError as exc:
                    control_error = exc

                # Secondary: revalidated identity kill.
                _kill_tracked(self._tracked, deadline=deadline)

                wait_budget = min(_TERMINATE_GRACE_SECONDS, remaining_budget(deadline))
                if wait_budget > 0:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        self.proc.wait(timeout=wait_budget)
                if self.proc.poll() is None:
                    with contextlib.suppress(OSError):
                        self.proc.kill()
                    tail = remaining_budget(deadline)
                    if tail > 0:
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            self.proc.wait(timeout=tail)

                self._close_pipes()
        finally:
            try:
                self._close_job_handle()
            except ProcessControlError as close_exc:
                if control_error is None:
                    control_error = close_exc
                else:
                    # Both terminate/group and job-close faults must appear in
                    # the public detail (review-7 P1-1).
                    control_error = ProcessControlError(
                        merge_control_details(
                            control_error.detail, close_exc.detail
                        )
                    )
            self._pgid = None

        if control_error is not None:
            raise control_error

    def _close_pipes(self) -> None:
        if self.proc is None:
            return
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is None:
                continue
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    def _close_job_handle(self) -> None:
        """Close the Windows job handle; surface CloseHandle failures.

        Does not swallow :class:`ProcessControlError` — callers decide how to
        prioritize against an earlier primary fault.
        """
        if self._job is None:
            return
        job = self._job
        self._job = None
        closer = self._close_hook or _close_windows_job
        closer(job)

    def _reset_control_state(self) -> None:
        self._job = None
        self._pgid = None
        self.root_identity = None
        self._tracked.clear()


def _open_if_identity_matches(identity: ProcessIdentity) -> psutil.Process | None:
    """Return a live Process only if create_time still matches ``identity``."""
    try:
        process = psutil.Process(identity.pid)
        if float(process.create_time()) != identity.create_time:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _kill_tracked(tracked: set[ProcessIdentity], *, deadline: float) -> None:
    """Kill tracked identities with create_time revalidated on the same object."""
    for identity in list(tracked):
        process = _open_if_identity_matches(identity)
        if process is None:
            continue
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process.terminate()

    wait = remaining_budget(deadline)
    if wait <= 0:
        for identity in list(tracked):
            process = _open_if_identity_matches(identity)
            if process is not None:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    process.kill()
        return

    live = [
        p
        for identity in list(tracked)
        if (p := _open_if_identity_matches(identity)) is not None
    ]
    if not live:
        return
    _gone, alive = psutil.wait_procs(live, timeout=wait)
    for process in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            # create_time access revalidates the object is still the same process.
            _ = process.create_time()
            process.kill()
    wait2 = remaining_budget(deadline)
    if alive and wait2 > 0:
        psutil.wait_procs(alive, timeout=wait2)


def _kill_posix_group(pgid: int, *, deadline: float) -> None:
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    sigterm = getattr(signal, "SIGTERM", None)
    sigkill = getattr(signal, "SIGKILL", None)
    if killpg is None or sigterm is None:
        raise ProcessControlError("POSIX killpg/SIGTERM unavailable on this platform.")
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        killpg(pgid, sigterm)
    wait = remaining_budget(deadline)
    if wait > 0:
        time.sleep(min(0.05, wait))
    still = False
    if getpgid is not None:
        with contextlib.suppress(psutil.Error):
            for proc in psutil.process_iter(["pid"]):
                try:
                    if proc.pid != 0 and getpgid(proc.pid) == pgid:
                        still = True
                        break
                except (ProcessLookupError, PermissionError, OSError, psutil.Error):
                    continue
    if still:
        if sigkill is None:
            raise ProcessControlError("POSIX SIGKILL unavailable; process group still live.")
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            killpg(pgid, sigkill)


# --- Windows Job Object (typed ctypes) -------------------------------------- #


def _kernel32() -> Any:
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit signatures so 64-bit HANDLEs are not truncated.
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    k32.SetInformationJobObject.restype = ctypes.c_bool
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.AssignProcessToJobObject.restype = ctypes.c_bool
    k32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k32.TerminateJobObject.restype = ctypes.c_bool
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = ctypes.c_bool
    k32.OpenThread.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    k32.OpenThread.restype = ctypes.c_void_p
    k32.ResumeThread.argtypes = [ctypes.c_void_p]
    k32.ResumeThread.restype = ctypes.c_uint
    k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint, ctypes.c_uint]
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    return k32


def _create_windows_job() -> int:
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()
    job_object_extended_limit_information = 9
    job_object_limit_kill_on_job_close = 0x2000

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    handle = k32.CreateJobObjectW(None, None)
    if not handle:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"CreateJobObjectW failed (winerr={err}).")

    info = _JobObjectExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    ok = k32.SetInformationJobObject(
        handle,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        err = ctypes.get_last_error()
        try:
            _close_win32_handle(k32, int(handle), label="job-after-setinfo-fail")
        except ProcessControlError as close_exc:
            raise ProcessControlError(
                f"SetInformationJobObject failed (winerr={err}); {close_exc.detail}"
            ) from close_exc
        raise ProcessControlError(f"SetInformationJobObject failed (winerr={err}).")
    return int(handle)


def _assign_windows_job(job: int, proc: subprocess.Popen[bytes]) -> None:
    import ctypes

    k32 = _kernel32()
    handle = getattr(proc, "_handle", None)
    if handle is None:
        raise ProcessControlError("Windows Popen process handle is unavailable.")
    ok = k32.AssignProcessToJobObject(job, int(handle))
    if not ok:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"AssignProcessToJobObject failed (winerr={err}).")


def _close_win32_handle(k32: Any, handle: int, *, label: str) -> None:
    """Close a Win32 HANDLE and raise on failure (no silent drop)."""
    import ctypes

    if not handle or handle == _INVALID_HANDLE_VALUE:
        return
    ok = k32.CloseHandle(handle)
    if not ok:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"CloseHandle({label}) failed (winerr={err}).")


def _resume_suspended_process(pid: int) -> None:
    """Resume all threads of a CREATE_SUSPENDED process (primary thread)."""
    import ctypes
    from ctypes import wintypes

    k32 = _kernel32()

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    k32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    k32.Thread32First.restype = ctypes.c_bool
    k32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    k32.Thread32Next.restype = ctypes.c_bool

    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap or snap == _INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"CreateToolhelp32Snapshot failed (winerr={err}).")

    resumed = 0
    close_errors: list[str] = []
    resume_errors: list[str] = []
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(_ThreadEntry32)
        more = k32.Thread32First(snap, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thr = k32.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thr:
                    # Resume until suspend count is 0 (CREATE_SUSPENDED uses 1).
                    while True:
                        prev = k32.ResumeThread(thr)
                        if prev == 0xFFFFFFFF:
                            err = ctypes.get_last_error()
                            resume_errors.append(
                                f"ResumeThread failed for tid={entry.th32ThreadID} "
                                f"(winerr={err})"
                            )
                            break
                        if prev <= 1:
                            resumed += 1
                            break
                    try:
                        _close_win32_handle(
                            k32, int(thr), label=f"thread:{entry.th32ThreadID}"
                        )
                    except ProcessControlError as ce:
                        close_errors.append(ce.detail)
            more = k32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        try:
            _close_win32_handle(k32, int(snap), label="thread-snapshot")
        except ProcessControlError as ce:
            close_errors.append(ce.detail)

    if resumed == 0 and not resume_errors:
        resume_errors.append(
            f"Failed to resume any thread of suspended process pid={pid}."
        )
    # Aggregate resume + close faults into one public detail (review-6 P1-1).
    if resume_errors or close_errors:
        raise ProcessControlError(
            merge_control_details(*resume_errors, *close_errors)
        )


def _terminate_windows_job(job: int, *, deadline: float) -> None:
    import ctypes

    k32 = _kernel32()
    ok = k32.TerminateJobObject(job, 1)
    if not ok:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"TerminateJobObject failed (winerr={err}).")
    wait = min(0.2, remaining_budget(deadline))
    if wait > 0:
        time.sleep(wait)


def _close_windows_job(job: int) -> None:
    import ctypes

    k32 = _kernel32()
    ok = k32.CloseHandle(job)
    if not ok:
        err = ctypes.get_last_error()
        raise ProcessControlError(f"CloseHandle(job) failed (winerr={err}).")


__all__ = [
    "ProcessControlError",
    "ProcessSupervisor",
    "build_minimal_env",
    "identity_of",
    "merge_control_details",
    "remaining_budget",
    "resolve_command",
]
