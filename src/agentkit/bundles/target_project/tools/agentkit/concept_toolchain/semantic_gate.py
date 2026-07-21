"""Mutating semantic-gate CLI (FK-78 section 78.14).

Subcommands: ``units <run-dir>`` (derive source units from
``source-register.tsv`` and write ``source-units.tsv``), ``prepare
<run-dir> --gate w2|w3 [--scope <scope_id>]...`` (write digest-addressed
request packs to ``semantic/requests/``), ``import <run-dir>
<receipt-file>`` (validate a semantic receipt and register it under
``semantic/receipts/``).

Writer discipline: every subcommand requires the caller identity
(``--principal``, ``--session``) and the expected ``--fencing-token``.
Each invocation acquires the mutation mutex ``RUN.mutex`` (``O_EXCL``)
and writes an owner-bearing payload ``{owner_principal, owner_session,
nonce, acquired_at, heartbeat_at, ttl_seconds}``. Liveness is measured
against ``heartbeat_at``, which is refreshed before every write step, so
a legitimate long-running operation is never taken over as crashed.

EVERY mutex change and effect — acquire, takeover, heartbeat refresh,
payload write and release — runs under ONE shared coordination intent
``RUN.mutex.intent`` (``O_CREAT|O_EXCL``): whoever cannot create it loses
and aborts. Because there is exactly one intent (not a separate write and
takeover intent), a takeover can never interleave with another writer's
critical section. The intent carries its own nonce
(``{holder_principal, holder_session, intent_nonce, acquired_at,
ttl_seconds}``) and is released only by nonce match
(compare-before-delete); an expired intent is likewise cleared only when
it still carries the observed nonce, and the following exclusive create
arbitrates between reclaimers. Under the intent the mutex is re-read and
must still carry the identity observed before; only then is it atomically
replaced. Takeover additionally requires the caller's fencing token to
equal ``RUN.lease_fencing_token``. The heartbeat refresh revalidates the
mutex nonce immediately before writing, so a foreign nonce is a hard
abort with exit code 2, never an overwrite. Release deletes the mutex
only when the nonce still matches, so a foreign or newer mutex survives.

Under the mutex the CLI reloads ``LEASE.json`` and ``RUN.json`` and
verifies: the lease belongs to the run, is not released, its TTL is
alive, its owner principal and session equal the caller identity, and
``lease.fencing_token == --fencing-token == RUN.lease_fencing_token``.
Only then does the command mutate (atomic temp+rename writes). A caller
that cannot confirm the lease never writes (stale writers are
additionally stopped by the fencing-token CAS of the RUN write protocol,
FK-78 section 78.4).

The idempotency key is the request digest: identical content is a no-op;
``prepare`` never overwrites — an existing pack for the same gate and
scope with a different request digest is an ERROR.

Exit codes: ``0`` success/no-op, ``1`` validation errors, ``2`` missing
prerequisites (mutex busy, missing/expired/released/foreign lease),
``3`` usage errors. ``--json`` emits the FK-78 envelope instead of
human-readable output.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

try:
    from . import runmodel
    from .docmodel import file_digest_sha256
    from .findings import EXIT_USAGE, CheckResult, error, exit_code, to_envelope
    from .units import derive_units, lf_normalize
except ImportError:  # pragma: no cover - direct script execution path
    import importlib

    _package_parent = str(Path(__file__).resolve().parent.parent)
    if _package_parent not in sys.path:
        sys.path.insert(0, _package_parent)
    _cli = importlib.import_module("concept_toolchain.semantic_gate")
    if __name__ == "__main__":
        raise SystemExit(_cli.main()) from None
    raise

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_UNITS_HEADER = "unit_id\tsource_id\tunit_locator\tunit_digest\tclaim_refs\tempty_reason"

#: Crash-orphaned mutation mutexes older than this are taken over.
MUTEX_TTL_SECONDS = 600


class _UsageErrorParser(argparse.ArgumentParser):
    """Argument parser that exits with the FK-78 usage exit code (3)."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _add_writer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run_dir", help="Incubation run directory.")
    parser.add_argument("--principal", required=True, help="Caller principal id (must equal the lease owner).")
    parser.add_argument("--session", required=True, help="Caller session ref (must equal the lease owner session).")
    parser.add_argument("--fencing-token", required=True, type=int, help="Expected lease/RUN fencing token.")


def build_parser() -> argparse.ArgumentParser:
    """Build the mutating semantic-gate argument parser."""
    parser = _UsageErrorParser(
        prog="python tools/agentkit/concept_toolchain/semantic_gate.py",
        description="Mutating semantic-gate mechanics (FK-78): unit derivation, request packs, receipt import.",
    )
    parser.add_argument("--project-root", default=".", help="Target-project root (default: current directory).")
    parser.add_argument("--json", action="store_true", help="Emit the FK-78 JSON envelope instead of human-readable output.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    units = subparsers.add_parser("units", help="Derive source units and write source-units.tsv.")
    _add_writer_arguments(units)
    prepare = subparsers.add_parser("prepare", help="Write semantic request packs.")
    _add_writer_arguments(prepare)
    prepare.add_argument("--gate", required=True, choices=sorted(runmodel.SEMANTIC_GATE_KEYS), help="Gate key (w2 or w3).")
    prepare.add_argument("--scope", action="append", default=[], help="Scope id (default: all promotion-manifest scopes).")
    importer = subparsers.add_parser("import", help="Validate and register a semantic receipt.")
    _add_writer_arguments(importer)
    importer.add_argument("receipt_file", help="Receipt JSON file (absolute or project-root-relative).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested mutation and return the FK-78 exit code."""
    args = build_parser().parse_args(argv)
    command = str(args.command)
    result = CheckResult(check_id=command)
    project_root = Path(args.project_root).resolve()
    run_dir = Path(args.run_dir) if Path(args.run_dir).is_absolute() else project_root / args.run_dir
    if not run_dir.is_dir():
        result.complete = False
        result.incomplete_reason = f"run directory does not exist: {run_dir}"
        return _finish(args, command, result)
    principal, session, token = str(args.principal), str(args.session), int(args.fencing_token)
    nonce, mutex_problem = _acquire_mutex(run_dir, principal, session, token)
    if mutex_problem is not None:
        result.complete = False
        result.incomplete_reason = mutex_problem
        return _finish(args, command, result)
    try:
        run = _verify_writer(run_dir, result, principal, session, token)
        if run is not None and result.complete and not result.findings:
            guard = _MutexGuard(run_dir, nonce or "", principal, session)
            try:
                with guard.exclusive_write():
                    pass
            except MutexLostError as exc:
                result.complete = False
                result.incomplete_reason = str(exc)
            else:
                _dispatch(args, command, result, project_root, run_dir, run, guard)
    finally:
        if nonce is not None:
            _MutexGuard(run_dir, nonce, principal, session).release()
    return _finish(args, command, result)


class MutexLostError(Exception):
    """Raised when mutex ownership is lost inside a critical section."""


class _MutexGuard:
    """Serializes every effectful step under the single coordination intent.

    ``exclusive_write`` is the ONLY path that may touch run state. It holds
    ``RUN.mutex.intent`` — the same intent that acquire, takeover, heartbeat
    and release use — across revalidation, heartbeat refresh and the effect
    itself. Because there is exactly ONE intent for all mutex changes, a
    takeover can no longer slip between the ownership check and the
    heartbeat refresh. The intent is released by nonce match only.
    """

    def __init__(self, run_dir: Path, nonce: str, principal: str, session: str) -> None:
        self.run_dir = run_dir
        self.nonce = nonce
        self.principal = principal
        self.session = session

    @contextlib.contextmanager
    def exclusive_write(self) -> Iterator[None]:
        """Hold the coordination intent over revalidation + heartbeat + effect.

        Raises:
            MutexLostError: If the intent cannot be claimed or ownership was
                lost; callers translate this into an INCOMPLETE result.
        """
        with _coordination_intent(self.run_dir, self.principal, self.session):
            problem = _mutex_still_ours(self.run_dir, self.nonce, self.principal, self.session)
            if problem is not None:
                raise MutexLostError(problem)
            _refresh_heartbeat(self.run_dir, self.nonce, self.principal, self.session)
            yield

    def write_bytes(self, result: CheckResult, path: Path, data: bytes) -> bool:
        """Stage and commit one write under the exclusive section.

        Two-phase on purpose: the payload is staged into a temp file
        first, ownership is re-verified *immediately* before the atomic
        rename, and only then does the effect happen. A writer that
        stalls while staging therefore still cannot land its write after
        another process took the mutex over — the residual window is the
        single ``os.replace`` call.
        """
        try:
            with self.exclusive_write():
                temp = _stage_temp(path, data)
                try:
                    problem = _mutex_still_ours(self.run_dir, self.nonce, self.principal, self.session)
                    if problem is not None:
                        raise MutexLostError(problem)
                    os.replace(temp, path)
                except BaseException:
                    with contextlib.suppress(OSError):
                        temp.unlink()
                    raise
        except MutexLostError as exc:
            result.complete = False
            result.incomplete_reason = str(exc)
            return False
        return True

    def release(self) -> None:
        """Compare-before-delete the mutex under the coordination intent."""
        try:
            with _coordination_intent(self.run_dir, self.principal, self.session):
                state, _ = runmodel.load_mutex_state(self.run_dir / "RUN.mutex")
                if state is not None and state.nonce == self.nonce:
                    with contextlib.suppress(OSError):
                        (self.run_dir / "RUN.mutex").unlink()
        except MutexLostError:
            return  # someone else coordinates the mutex now; never force a release


def _dispatch(
    args: argparse.Namespace,
    command: str,
    result: CheckResult,
    project_root: Path,
    run_dir: Path,
    run: runmodel.RunState,
    guard: _MutexGuard,
) -> None:
    if command == "units":
        _cmd_units(result, project_root, run_dir, run, guard)
    elif command == "prepare":
        _cmd_prepare(result, project_root, run_dir, str(args.gate), list(args.scope), guard)
    else:
        _cmd_import(result, project_root, run_dir, str(args.receipt_file), guard)


def _finish(args: argparse.Namespace, command: str, result: CheckResult) -> int:
    if args.json:
        print(json.dumps(to_envelope(command, [command], [result]), indent=2, sort_keys=True))
    else:
        for finding in result.findings:
            print(f"[ERROR] {finding.path}:{finding.locator} - {finding.message}")
        for report in result.reports:
            print(report)
        if not result.complete:
            print(f"[{command}] INCOMPLETE: {result.incomplete_reason}", file=sys.stderr)
        elif result.findings:
            print(f"[{command}] FAILED: {len(result.findings)} error(s)")
        else:
            suffix = f": {result.summary}" if result.summary else ""
            print(f"[{command}] OK{suffix}")
    return exit_code([result])


# --------------------------------------------------------------------------
# Mutation mutex and writer verification
# --------------------------------------------------------------------------


def _now_utc() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mutex_payload(principal: str, session: str, nonce: str, acquired_at: str) -> bytes:
    payload = {
        "owner_principal": principal,
        "owner_session": session,
        "nonce": nonce,
        "acquired_at": acquired_at,
        "heartbeat_at": _now_utc(),
        "ttl_seconds": MUTEX_TTL_SECONDS,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


INTENT_NAME = "RUN.mutex.intent"


def _intent_payload(principal: str, session: str, intent_nonce: str) -> bytes:
    payload = {
        "holder_principal": principal,
        "holder_session": session,
        "intent_nonce": intent_nonce,
        "acquired_at": _now_utc(),
        "ttl_seconds": MUTEX_TTL_SECONDS,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _claim_intent(run_dir: Path, principal: str, session: str) -> str | None:
    """Claim the single coordination intent; returns its nonce or ``None``.

    ``O_CREAT|O_EXCL`` is the arbiter. An existing intent is only cleared
    when its own TTL elapsed AND it still carries the exact identity that
    was observed (compare-before-delete); the subsequent exclusive create
    decides the race between two reclaimers.
    """
    intent = run_dir / INTENT_NAME
    nonce = uuid.uuid4().hex
    for _attempt in range(2):
        try:
            descriptor = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            observed, _ = runmodel.load_intent_state(intent)
            if observed is not None and not runmodel.timestamp_expired(observed.acquired_at, observed.ttl_seconds):
                return None
            if not _clear_stale_intent(intent, observed):
                return None
            continue
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_intent_payload(principal, session, nonce))
        return nonce
    return None


def _clear_stale_intent(intent: Path, observed: runmodel.IntentState | None) -> bool:
    """Delete an expired/unreadable intent only if it is still the observed one."""
    if observed is None:
        # Unreadable payload: fall back to mtime age so a crashed writer
        # cannot wedge the run forever.
        try:
            if time.time() - intent.stat().st_mtime <= MUTEX_TTL_SECONDS:
                return False
        except OSError:
            return True
        with contextlib.suppress(OSError):
            intent.unlink()
        return True
    current, _ = runmodel.load_intent_state(intent)
    if current is None or current.intent_nonce != observed.intent_nonce:
        return False
    with contextlib.suppress(OSError):
        intent.unlink()
    return True


def _release_intent(run_dir: Path, intent_nonce: str) -> None:
    """Release the coordination intent by nonce match (compare-before-delete)."""
    intent = run_dir / INTENT_NAME
    state, _ = runmodel.load_intent_state(intent)
    if state is None or state.intent_nonce != intent_nonce:
        return
    with contextlib.suppress(OSError):
        intent.unlink()


@contextlib.contextmanager
def _coordination_intent(run_dir: Path, principal: str, session: str) -> Iterator[None]:
    """Hold the single coordination intent for the enclosed mutex effect."""
    intent_nonce = _claim_intent(run_dir, principal, session)
    if intent_nonce is None:
        raise MutexLostError("another writer holds the RUN.mutex coordination intent; refusing to mutate")
    try:
        yield
    finally:
        _release_intent(run_dir, intent_nonce)


def _acquire_mutex(run_dir: Path, principal: str, session: str, fencing_token: int) -> tuple[str | None, str | None]:
    """Acquire ``RUN.mutex`` under the coordination intent.

    Creating a fresh mutex and taking over an expired one both happen
    inside the SAME intent that guards heartbeat, write and release, so a
    takeover can never interleave with another writer's critical section.
    """
    mutex = run_dir / "RUN.mutex"
    nonce = uuid.uuid4().hex
    try:
        with _coordination_intent(run_dir, principal, session):
            if not mutex.exists():
                _atomic_write_bytes(mutex, _mutex_payload(principal, session, nonce, _now_utc()))
                return nonce, None
            return _take_over_mutex(run_dir, mutex, nonce, principal, session, fencing_token)
    except MutexLostError as exc:
        return None, str(exc)


def _take_over_mutex(
    run_dir: Path, mutex: Path, nonce: str, principal: str, session: str, fencing_token: int
) -> tuple[str | None, str | None]:
    """Take over an expired mutex; caller MUST hold the coordination intent."""
    observed, issues = runmodel.load_mutex_state(mutex)
    if observed is None:
        details = "; ".join(f"{issue.locator}: {issue.message}" for issue in issues)
        return None, f"RUN.mutex exists but is not a valid mutex payload ({details}); refusing to mutate"
    if not runmodel.timestamp_expired(observed.heartbeat_at, observed.ttl_seconds):
        return None, (
            f"RUN.mutex is held by {observed.owner_principal!r} (heartbeat {observed.heartbeat_at}); refusing to mutate"
        )
    run, _ = runmodel.load_run_state(run_dir / "RUN.json")
    if run is None or run.lease_fencing_token != fencing_token:
        return None, "expired RUN.mutex takeover requires a caller fencing token equal to RUN.lease_fencing_token"
    current, _ = runmodel.load_mutex_state(mutex)
    if current is None or (current.nonce, current.heartbeat_at) != (observed.nonce, observed.heartbeat_at):
        return None, "RUN.mutex changed during takeover (another writer won the race); refusing to mutate"
    _atomic_write_bytes(mutex, _mutex_payload(principal, session, nonce, _now_utc()))
    return nonce, None


def _mutex_still_ours(run_dir: Path, nonce: str, principal: str, session: str) -> str | None:
    """Revalidate mutex ownership; returns a problem description on loss."""
    state, _ = runmodel.load_mutex_state(run_dir / "RUN.mutex")
    if state is None:
        return "RUN.mutex vanished or became unreadable during the operation; aborting"
    if state.nonce != nonce:
        return f"RUN.mutex was taken over by {state.owner_principal!r} during the operation; aborting"
    if (state.owner_principal, state.owner_session) != (principal, session):
        return "RUN.mutex owner identity changed during the operation; aborting"
    if runmodel.timestamp_expired(state.heartbeat_at, state.ttl_seconds):
        return "own RUN.mutex heartbeat expired during the operation; aborting"
    return None


def _refresh_heartbeat(run_dir: Path, nonce: str, principal: str, session: str) -> None:
    """Refresh the heartbeat under the coordination intent.

    Revalidates the mutex nonce immediately before writing: a foreign
    nonce is a hard abort, never an overwrite with our own identity.

    Raises:
        MutexLostError: If the mutex is gone or owned by someone else.
    """
    state, _ = runmodel.load_mutex_state(run_dir / "RUN.mutex")
    if state is None:
        raise MutexLostError("RUN.mutex vanished before the heartbeat refresh; aborting")
    if state.nonce != nonce or (state.owner_principal, state.owner_session) != (principal, session):
        raise MutexLostError(f"RUN.mutex was taken over by {state.owner_principal!r} during the operation; aborting")
    _atomic_write_bytes(run_dir / "RUN.mutex", _mutex_payload(principal, session, nonce, state.acquired_at))


def _verify_writer(
    run_dir: Path, result: CheckResult, principal: str, session: str, fencing_token: int
) -> runmodel.RunState | None:
    """Reload LEASE and RUN under the mutex and verify the caller's authority."""
    lease_path = run_dir / "LEASE.json"
    if not lease_path.is_file():
        result.complete = False
        result.incomplete_reason = "LEASE.json not found; mutations require a live writer lease"
        return None
    lease, lease_issues = runmodel.load_lease(lease_path)
    for issue in lease_issues:
        result.findings.append(error(result.check_id, "LEASE.json", issue.locator, issue.message))
    run_path = run_dir / "RUN.json"
    if not run_path.is_file():
        result.complete = False
        result.incomplete_reason = "RUN.json not found; mutations require the authoritative run state"
        return None
    run, run_issues = runmodel.load_run_state(run_path)
    for issue in run_issues:
        result.findings.append(error(result.check_id, "RUN.json", issue.locator, issue.message))
    if lease is None or run is None:
        return None
    problems = _writer_problems(lease, run, principal, session, fencing_token)
    if problems:
        result.complete = False
        result.incomplete_reason = "; ".join(problems)
        return None
    return run


def _writer_problems(
    lease: runmodel.Lease, run: runmodel.RunState, principal: str, session: str, fencing_token: int
) -> list[str]:
    problems: list[str] = []
    if lease.run_id != run.run_id:
        problems.append(f"lease run_id {lease.run_id!r} does not match RUN.json {run.run_id!r}")
    if lease.released:
        problems.append("lease is released; acquire a new lease before mutating")
    elif runmodel.timestamp_expired(lease.acquired_at, lease.ttl_seconds):
        problems.append("lease TTL expired; renew or take over the lease before mutating")
    if lease.owner.principal_id != principal:
        problems.append(f"lease owner principal {lease.owner.principal_id!r} does not match --principal {principal!r}")
    if lease.owner.session_ref != session:
        problems.append(f"lease owner session {lease.owner.session_ref!r} does not match --session {session!r}")
    if lease.fencing_token != fencing_token or run.lease_fencing_token != fencing_token:
        problems.append(
            f"fencing token mismatch: lease {lease.fencing_token}, RUN {run.lease_fencing_token}, "
            f"--fencing-token {fencing_token}"
        )
    return problems


def _stage_temp(path: Path, data: bytes) -> Path:
    """Stage a payload next to its destination and return the temp path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(data)
    return temp


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    os.replace(_stage_temp(path, data), path)


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def _cmd_units(
    result: CheckResult, project_root: Path, run_dir: Path, run: runmodel.RunState, guard: _MutexGuard
) -> None:
    register_path = run_dir / "baseline" / "source-register.tsv"
    if not register_path.is_file():
        result.complete = False
        result.incomplete_reason = "baseline/source-register.tsv not found"
        return
    rows, issues = runmodel.load_source_register(register_path)
    for issue in issues:
        result.findings.append(error(result.check_id, "baseline/source-register.tsv", issue.locator, issue.message))
    units_path = run_dir / "baseline" / "source-units.tsv"
    existing: tuple[runmodel.TsvRow, ...] = ()
    if units_path.is_file():
        existing, unit_issues = runmodel.load_source_units(units_path, require_disposition=False)
        for issue in unit_issues:
            result.findings.append(error(result.check_id, "baseline/source-units.tsv", issue.locator, issue.message))
    if result.findings:
        return
    derived, problems = _derive_register_units(project_root, rows)
    problems.extend(_existing_row_problems(existing, derived, {row["source_id"] for row in rows}))
    if problems:
        result.findings.extend(error(result.check_id, "baseline/source-units.tsv", "file", problem) for problem in problems)
        return
    output_rows = _merge_unit_rows(run.run_uuid8, existing, derived)
    columns = _UNITS_HEADER.split("\t")
    content = "\n".join([_UNITS_HEADER, *("\t".join(row[column] for column in columns) for row in output_rows)]) + "\n"
    if units_path.is_file() and units_path.read_bytes().decode("utf-8") == content:
        result.summary = f"no-op ({len(output_rows)} unit(s) already registered)"
        return
    if not guard.write_bytes(result, units_path, content.encode("utf-8")):
        return
    result.reports.append(f"[units] wrote {len(output_rows)} unit(s) to baseline/source-units.tsv")
    result.summary = f"{len(output_rows)} unit(s) registered"


def _derive_register_units(
    project_root: Path, rows: tuple[runmodel.TsvRow, ...]
) -> tuple[dict[tuple[str, str], str], list[str]]:
    derived: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    for row in rows:
        source_path = project_root / row["path"]
        if not source_path.is_file():
            problems.append(f"source file does not exist: {row['path']}")
            continue
        if file_digest_sha256(source_path) != row["sha256"]:
            problems.append(f"source digest drifted from the register, refusing derivation: {row['path']}")
            continue
        for unit in derive_units(row["path"], source_path.read_text(encoding="utf-8")):
            derived[(row["source_id"], unit.locator)] = unit.digest
    return derived, problems


def _existing_row_problems(
    existing: tuple[runmodel.TsvRow, ...], derived: dict[tuple[str, str], str], source_ids: set[str]
) -> list[str]:
    problems: list[str] = []
    for row in existing:
        key = (row["source_id"], row["unit_locator"])
        if row["source_id"] not in source_ids:
            problems.append(f"existing unit {row['unit_id']} references unknown source {row['source_id']}")
        elif key not in derived:
            problems.append(f"existing unit {row['unit_id']} no longer derives from its source: {row['unit_locator']}")
        elif derived[key] != row["unit_digest"]:
            problems.append(f"unit digest drift for {row['unit_id']} ({row['unit_locator']}); refusing overwrite")
    return problems


def _merge_unit_rows(
    run_uuid8: str, existing: tuple[runmodel.TsvRow, ...], derived: dict[tuple[str, str], str]
) -> list[runmodel.TsvRow]:
    by_key = {(row["source_id"], row["unit_locator"]): row for row in existing}
    counter = max((int(row["unit_id"].rsplit("-", 1)[1]) for row in existing), default=0)
    output = [dict(row) for row in existing]
    for (source_id, locator), digest in sorted(derived.items()):
        if (source_id, locator) in by_key:
            continue
        counter += 1
        output.append(
            {
                "unit_id": f"SU-{run_uuid8}-{counter:04d}",
                "source_id": source_id,
                "unit_locator": locator,
                "unit_digest": digest,
                "claim_refs": "",
                "empty_reason": "",
            }
        )
    output.sort(key=lambda row: row["unit_id"])
    return output


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


def _cmd_prepare(
    result: CheckResult, project_root: Path, run_dir: Path, gate_key: str, scopes: list[str], guard: _MutexGuard
) -> None:
    manifest_path = run_dir / "promotion" / "promotion-manifest.json"
    if not manifest_path.is_file():
        result.complete = False
        result.incomplete_reason = "promotion/promotion-manifest.json not found"
        return
    manifest, issues = runmodel.load_promotion_manifest(manifest_path)
    for issue in issues:
        result.findings.append(error(result.check_id, "promotion/promotion-manifest.json", issue.locator, issue.message))
    if manifest is None:
        return
    target_scopes = scopes or [scope.scope_id for scope in manifest.scopes]
    if not target_scopes:
        result.complete = False
        result.incomplete_reason = "no scopes to prepare (manifest has none and --scope not given)"
        return
    template_path = Path(__file__).resolve().parent / "semantic_templates" / f"{gate_key}.md"
    if not template_path.is_file():
        result.complete = False
        result.incomplete_reason = f"prompt template missing: {template_path}"
        return
    chunks, problems = _build_chunks(project_root, manifest)
    if problems:
        result.findings.extend(
            error(result.check_id, "promotion/promotion-manifest.json", "manifest.targets", problem) for problem in problems
        )
        return
    template_digest = hashlib.sha256(template_path.read_bytes()).hexdigest()
    for scope_id in target_scopes:
        _write_pack(result, run_dir, manifest, gate_key, scope_id, template_digest, chunks, guard)
    if not result.findings:
        result.summary = f"{len(target_scopes)} scope pack(s) settled for gate {gate_key}"


def _build_chunks(project_root: Path, manifest: runmodel.PromotionManifest) -> tuple[list[dict[str, str]], list[str]]:
    chunks: list[dict[str, str]] = []
    problems: list[str] = []
    for target in sorted(manifest.targets, key=lambda item: item.path):
        target_path = project_root / target.path
        if not target_path.is_file():
            problems.append(f"target file does not exist: {target.path}")
            continue
        line_count = max(len(lf_normalize(target_path.read_text(encoding="utf-8")).splitlines()), 1)
        chunks.append(
            {
                "path": target.path,
                "locator": f"{target.path}#L1-L{line_count}",
                "digest": file_digest_sha256(target_path),
            }
        )
    return chunks, problems


def _existing_scope_pack(run_dir: Path, gate: str, scope_id: str) -> runmodel.SemanticRequestPack | None:
    requests_dir = run_dir / "semantic" / "requests"
    if not requests_dir.is_dir():
        return None
    for entry in sorted(requests_dir.glob("*.json")):
        pack, _ = runmodel.load_semantic_request_pack(entry)
        if pack is not None and pack.gate == gate and pack.scope_id == scope_id:
            return pack
    return None


def _write_pack(
    result: CheckResult,
    run_dir: Path,
    manifest: runmodel.PromotionManifest,
    gate_key: str,
    scope_id: str,
    template_digest: str,
    chunks: list[dict[str, str]],
    guard: _MutexGuard,
) -> None:
    gate = runmodel.SEMANTIC_GATE_KEYS[gate_key]
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "gate": gate,
        "scope_id": scope_id,
        "base_revision": {"kind": manifest.base_revision.kind, "value": manifest.base_revision.value},
        "template_id": gate_key,
        "template_digest": template_digest,
        "chunks": chunks,
    }
    request_digest = runmodel.canonical_request_digest(payload)
    payload["request_digest"] = request_digest
    existing = _existing_scope_pack(run_dir, gate, scope_id)
    if existing is not None:
        if existing.request_digest == request_digest:
            result.reports.append(f"[prepare] no-op for scope {scope_id} (request_digest {request_digest})")
            return
        result.findings.append(
            error(
                result.check_id,
                "semantic/requests",
                scope_id,
                f"existing pack for gate {gate!r} and scope {scope_id!r} has request_digest "
                f"{existing.request_digest}; refusing to overwrite with {request_digest}",
            )
        )
        return
    name = f"{gate_key}-{runmodel.normalize_scope_id(scope_id)}-{request_digest[:16]}.json"
    destination = run_dir / "semantic" / "requests" / name
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(destination, content)
    result.reports.append(f"[prepare] wrote pack for scope {scope_id} (request_digest {request_digest})")


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------


def _cmd_import(
    result: CheckResult, project_root: Path, run_dir: Path, receipt_file: str, guard: _MutexGuard
) -> None:
    receipt_path = Path(receipt_file) if Path(receipt_file).is_absolute() else project_root / receipt_file
    if not receipt_path.is_file():
        result.complete = False
        result.incomplete_reason = f"receipt file does not exist: {receipt_path}"
        return
    receipt, issues = runmodel.load_semantic_receipt(receipt_path)
    for issue in issues:
        result.findings.append(error(result.check_id, receipt_path.name, issue.locator, issue.message))
    if receipt is None:
        return
    pack = _find_pack(run_dir, receipt.request_digest)
    if pack is None:
        result.findings.append(
            error(
                result.check_id,
                receipt_path.name,
                "receipt.request_digest",
                f"no request pack matches request_digest {receipt.request_digest}",
            )
        )
        return
    if receipt.gate != pack.gate:
        result.findings.append(
            error(
                result.check_id,
                receipt_path.name,
                "receipt.gate",
                f"receipt gate {receipt.gate!r} does not match the pack gate {pack.gate!r}",
            )
        )
        return
    if receipt.chunk_digests != tuple(chunk.digest for chunk in pack.chunks):
        result.findings.append(
            error(
                result.check_id,
                receipt_path.name,
                "receipt.chunk_digests",
                "receipt chunk_digests do not match the request pack",
            )
        )
        return
    destination = run_dir / "semantic" / "receipts" / f"{receipt.request_digest}.json"
    data = receipt_path.read_bytes()
    if destination.is_file():
        if destination.read_bytes() == data:
            result.summary = f"no-op (receipt for {receipt.request_digest} already registered)"
            return
        result.findings.append(
            error(
                result.check_id,
                receipt_path.name,
                "receipt.request_digest",
                f"conflicting receipt content already registered for request_digest {receipt.request_digest}",
            )
        )
        return
    if not guard.write_bytes(result, destination, data):
        return
    result.reports.append(f"[import] registered receipt for request_digest {receipt.request_digest}")
    result.summary = "receipt registered"


def _find_pack(run_dir: Path, request_digest: str) -> runmodel.SemanticRequestPack | None:
    requests_dir = run_dir / "semantic" / "requests"
    if not requests_dir.is_dir():
        return None
    for entry in sorted(requests_dir.glob("*.json")):
        pack, _ = runmodel.load_semantic_request_pack(entry)
        if pack is not None and pack.request_digest == request_digest:
            return pack
    return None


if __name__ == "__main__":
    raise SystemExit(main())
