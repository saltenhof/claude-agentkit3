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
``RUN.mutex.intent`` (``O_CREAT|O_EXCL``): whoever cannot create it waits
for it, bounded by ``INTENT_WAIT_SECONDS``, and aborts once that budget is
spent. The intent is only ever held across a handful of file operations,
so waiting it out is the normal case; giving up on first sight would let a
losing competitor evict the rightful mutex owner from its own critical
section. Because there is exactly one intent (not a separate write and
takeover intent), a takeover can never interleave with another writer's
critical section. The intent carries its own nonce
(``{holder_principal, holder_session, intent_nonce, acquired_at,
ttl_seconds}``) and is released only by nonce match
(compare-before-delete).

THE RULE THAT ORDERS EVERYTHING ELSE. Read-then-act is not atomic: the
identity a caller observed is not part of the ``unlink`` or ``os.replace``
that follows it. So EVERY effect that a caller derives from an EARLIER
observation — not only a delete — runs under an OS advisory lock on
``RUN.mutex.intent.lock`` (``fcntl.flock`` / ``msvcrt.locking``), and the
observation is re-established INSIDE that lock immediately before the
effect. Concretely that covers the latch reclaim, the latch release, the
heartbeat refresh, the mutex takeover, the final payload write of a
subcommand, the mutex release and the give-back of an exclusively created
file that could not be filled. Nothing that touches a file on the strength
of something read beforehand is left outside it.

Why the SAME lock orders latch and mutex: every reclaim of a latch needs
the lock, and every mutex takeover needs the latch. While an effect holds
the lock and has re-proven that the latch is still its own, nobody can
reclaim that latch, hence nobody holds it, hence nobody can have taken the
mutex over — so the effect cannot land on top of a successor's work. And
if the latch was already reclaimed before the lock was taken, the effect
sees it and refuses. Preventing the loss is impossible (a frozen process
cannot heartbeat and no timeout tells it apart from a dead one — that is
why the latch has a TTL at all), so the answer is DETECTION, applied to
every effect and not only to the release.

The lock is held across a handful of file operations only, never across a
bounded wait and never across the claim: ``O_CREAT|O_EXCL`` remains the
arbiter of both claims — the latch and a fresh ``RUN.mutex``. The lock
file is a pure serialization device: it is never deleted and never
carries state, and the operating system drops the lock when its holder
dies.

Under the intent the mutex is re-read and must still carry the identity
observed before; only then is it atomically replaced. Takeover
additionally requires the caller's fencing token to equal
``RUN.lease_fencing_token``. The heartbeat refresh revalidates the mutex
nonce immediately before writing, so a foreign nonce is a hard abort with
exit code 2, never an overwrite. Release deletes the mutex only when the
nonce still matches, so a foreign or newer mutex survives.

An owed deletion that does not happen is never reported as success: it
leaves a file behind that blocks every further writer until its TTL
elapses. Such a failure is collected in :class:`_OwedEffects` and emitted
as a blocking ERROR finding naming the file — deliberately as a finding
and not as an INCOMPLETE reason, because the release runs in ``main``'s
``finally`` and the mutation it tears down may well have landed. On the
process boundary it carries its own exit code (``4``), so a caller can
tell "the work is done, the run directory needs a hand" from a wrong
result or a run that never started, without parsing any message.

"The file is gone" and "the file is there but nobody can validate it"
are never the same answer. Both make ``load_mutex_state`` /
``load_intent_state`` return ``None``, so every compare-before-delete
asks :func:`_check_ownership`, which only calls a file gone when it is
provably absent. A file that exists but cannot be verified is never
deleted unverified — that would abandon compare-before-delete — and never
reported as done either: it becomes the same blocking ERROR finding,
carrying the loader's own diagnosis as its reason. For ``RUN.mutex`` that
blockade is PERMANENT and not TTL-bounded, because a payload that does
not validate is rejected by :func:`_take_over_mutex` instead of being
taken over.

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

Exit codes: ``0`` success/no-op, ``1`` blocking validation findings,
``2`` missing prerequisites (mutex busy, missing/expired/released/foreign
lease), ``3`` usage errors, ``4`` the mutation is settled but an owed
cleanup effect did not happen. ``4`` has its own code because "work done,
cleanup failed" is neither of the other two failures, and it has the
WEAKEST rank: a real validation finding (``1``) or a missing prerequisite
(``2``) always wins, because ``4`` tells a consumer the work is done.
``--json`` emits the FK-78 envelope instead of human-readable output; the
owed effect is a blocking ERROR finding there in every case.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import enum
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

try:
    from . import (
        runmodel_digests,
        runmodel_locks,
        runmodel_promotion,
        runmodel_registers,
        runmodel_run,
        runmodel_semantic,
        runmodel_tsv,
    )
    from .docmodel import file_digest_sha256
    from .findings import (
        EXIT_OWED_EFFECT,
        EXIT_USAGE,
        CheckResult,
        error,
        exit_code_with_owed_effect,
        to_envelope,
    )
    from .runmodel_constants import RunModelConstants as Vocab
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

    from .runmodel_validation import Issue

_UNITS_HEADER = "unit_id\tsource_id\tunit_locator\tunit_digest\tclaim_refs\tempty_reason"
RUN_MUTEX_FILE = "RUN.mutex"
RUN_FILE = "RUN.json"

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
    prepare.add_argument("--gate", required=True, choices=sorted(Vocab.SEMANTIC_GATE_KEYS), help="Gate key (w2 or w3).")
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
    owed = _OwedEffects()
    project_root = Path(args.project_root).resolve()
    run_dir = Path(args.run_dir) if Path(args.run_dir).is_absolute() else project_root / args.run_dir
    if not run_dir.is_dir():
        result.complete = False
        result.incomplete_reason = f"run directory does not exist: {run_dir}"
        return _finish(args, command, result, owed)
    principal, session, token = str(args.principal), str(args.session), int(args.fencing_token)
    nonce, mutex_problem = _acquire_mutex(run_dir, principal, session, token, owed)
    if mutex_problem is not None:
        result.complete = False
        result.incomplete_reason = mutex_problem
        return _finish(args, command, result, owed)
    try:
        run = _verify_writer(run_dir, result, principal, session, token)
        if run is not None and result.complete and not result.findings:
            guard = _MutexGuard(run_dir, nonce or "", principal, session, owed)
            try:
                guard.revalidate()
            except (MutexLostError, OSError) as exc:
                result.complete = False
                result.incomplete_reason = _mutation_problem(exc)
            else:
                _dispatch(args, command, result, project_root, run_dir, run, guard)
    finally:
        if nonce is not None:
            _MutexGuard(run_dir, nonce, principal, session, owed).release()
    return _finish(args, command, result, owed)


class MutexLostError(Exception):
    """Raised when mutex ownership is lost inside a critical section."""


@dataclass(frozen=True)
class _Orphan:
    """A file whose owed deletion did not happen, plus why it stayed behind.

    ``permanent`` distinguishes the two blockades a leftover file causes.
    A file that is still a VALID payload is taken over once its TTL
    elapses, so the run directory unwedges itself. A ``RUN.mutex`` that
    does not validate never is: :func:`_take_over_mutex` rejects an
    invalid payload before it ever looks at the TTL, so only a human can
    clear it. Saying "until its TTL elapses" there would be a false
    promise, and a false promise is how a wedged run directory ends up
    waited on instead of repaired.
    """

    path: Path
    detail: str
    permanent: bool = False


@dataclass
class _OwedEffects:
    """Collects owed deletions that did not happen (FK-78 section 78.4).

    After compare-before-delete has established ownership, the deletion is
    an owed effect and not an attempt. When it finally fails, the file
    blocks every further writer — reporting that on stderr while exiting
    ``0`` would be exactly the silent success FK-78 forbids.

    The release runs in ``main``'s ``finally``, i.e. after the outcome of
    the mutation is already decided. A failure there must therefore not
    overwrite that outcome (the mutation may well have landed) and must
    not escape the teardown as an exception. It is collected here and
    turned by :func:`_finish` into an additional blocking finding plus the
    dedicated exit code ``4``, which says "the work is done, the run
    directory needs a hand" without displacing a worse outcome.
    """

    orphans: list[_Orphan] = field(default_factory=list)

    def record(self, path: Path, detail: str, *, permanent: bool = False) -> None:
        """Note that ``path`` stayed behind, with the reason it did."""
        self.orphans.append(_Orphan(path=path, detail=detail, permanent=permanent))


class _Ownership(enum.Enum):
    """What a compare-before-delete could establish about a file.

    ``UNVERIFIABLE`` is the case the loaders cannot express: they return
    ``None`` for a file that is gone AND for one that is there but
    unreadable, truncated or invalid. Collapsing the two makes an I/O
    error look like a completed deletion.
    """

    OURS = "ours"
    FOREIGN = "foreign"
    GONE = "gone"
    UNVERIFIABLE = "unverifiable"


def _file_is_absent(path: Path) -> bool:
    """Whether ``path`` is PROVABLY absent — a failed stat is not proof.

    ``Path.exists`` answers ``False`` for a permission or I/O error too,
    which is exactly the confusion this function exists to avoid.
    """
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _check_ownership(path: Path, own_identity: str, observed_identity: str | None) -> _Ownership:
    """Classify a compare-before-delete target against the caller's identity.

    The identity is a nonce wherever the file carries one, and the kernel's
    (device, inode) pair for a file that was created exclusively but never
    got a payload (:func:`_open_identity`). The classification is the same
    question either way — "is this still the file I am entitled to act on"
    — so it is answered in one place.

    Args:
        path: The file the caller owes a deletion for.
        own_identity: The identity the caller established when it took the
            file.
        observed_identity: The identity just read back from the file, or
            ``None`` when reading it produced nothing valid at all.

    Returns:
        Which of the four outcomes holds. Only ``OURS`` permits a delete;
        ``UNVERIFIABLE`` obliges the caller to record an owed effect.
    """
    if observed_identity is not None:
        return _Ownership.OURS if observed_identity == own_identity else _Ownership.FOREIGN
    return _Ownership.GONE if _file_is_absent(path) else _Ownership.UNVERIFIABLE


def _issue_detail(issues: Sequence[Issue]) -> str:
    """Render the loader's own diagnosis; it IS the reason, not noise."""
    return "; ".join(f"{issue.locator}: {issue.message}" for issue in issues) or "no diagnosis reported"


def _unverifiable_detail(issues: Sequence[Issue]) -> str:
    """Explain that the file is there but its identity could not be read."""
    return f"the file exists but could not be verified as ours ({_issue_detail(issues)})"


def _mutation_problem(exc: BaseException) -> str:
    """Describe why a mutation stopped — losing the mutex or the file system.

    Both end the same way: nothing was written and the run reports
    INCOMPLETE. An OS error must not escape as a traceback, because every
    exit code of this CLI carries a distinct meaning (``1`` validation
    findings, ``2`` missing prerequisites, ``4`` an owed cleanup effect
    that did not happen) and a crash carries none.
    """
    if isinstance(exc, MutexLostError):
        return str(exc)
    return f"file system error while coordinating the mutex: {exc}; refusing to mutate"


class _MutexGuard:
    """Serializes every effectful step under the single coordination intent.

    ``exclusive_write`` is the ONLY path that may touch run state. It holds
    ``RUN.mutex.intent`` — the same intent that acquire, takeover, heartbeat
    and release use — across revalidation, heartbeat refresh and the effect
    itself. Because there is exactly ONE intent for all mutex changes, a
    takeover can no longer slip between the ownership check and the
    heartbeat refresh. The intent is released by nonce match only, under
    the advisory cleanup lock.

    Every single effect inside that section — the heartbeat refresh and the
    final ``os.replace`` of the payload alike — additionally runs inside
    :meth:`_proven_ownership`, because holding the intent is not the same as
    still holding it (see :func:`_latched_effect`).

    Owed deletions that the guard could not carry out are recorded in
    ``owed`` rather than dropped: the release runs in ``main``'s
    ``finally`` and must neither crash the teardown nor rewrite the
    already decided outcome of the mutation.
    """

    def __init__(self, run_dir: Path, nonce: str, principal: str, session: str, owed: _OwedEffects) -> None:
        self.run_dir = run_dir
        self.nonce = nonce
        self.principal = principal
        self.session = session
        self.owed = owed

    @contextlib.contextmanager
    def _proven_ownership(self, intent_nonce: str) -> Iterator[None]:
        """Enter a section in which latch AND mutex are re-proven to be ours.

        The two proofs belong together and both belong INSIDE the lock. The
        latch proof orders us against a takeover (see :func:`_latched_effect`);
        the mutex proof is the compare part of compare-before-write, and
        reading it outside the lock would put the very gap back that the
        lock exists to close.

        Args:
            intent_nonce: The latch identity claimed by the enclosing
                :func:`_coordination_intent`.

        Yields:
            Nothing; the caller's effect runs inside the proven section.

        Raises:
            MutexLostError: If the latch or the mutex is no longer ours, or
                could not be proven to be. Callers translate this into an
                INCOMPLETE result — an unproven claim never acts.
        """
        with _latched_effect(self.run_dir, intent_nonce) as blocked:
            if blocked is not None:
                raise MutexLostError(blocked)
            problem = _mutex_still_ours(self.run_dir, self.nonce, self.principal, self.session)
            if problem is not None:
                raise MutexLostError(problem)
            yield

    @contextlib.contextmanager
    def exclusive_write(self) -> Iterator[str]:
        """Hold the coordination intent over revalidation + heartbeat + effect.

        Yields:
            The nonce of the claimed latch. An enclosed effect has to be able
            to re-prove the claim under the cleanup lock before it acts, so
            the identity is handed out rather than kept private.

        Raises:
            MutexLostError: If the intent cannot be claimed or ownership was
                lost; callers translate this into an INCOMPLETE result.
        """
        with _coordination_intent(self.run_dir, self.principal, self.session, self.owed) as intent_nonce:
            self._refresh_under_the_latch(intent_nonce)
            yield intent_nonce

    def _refresh_under_the_latch(self, intent_nonce: str) -> None:
        """Refresh the heartbeat as ONE section (:func:`_latched_effect`).

        The refresh is a read-then-replace like every other effect: it reads
        the mutex, finds our own nonce and replaces the file. A holder that
        freezes between those two steps for longer than the latch TTL loses
        the latch, a successor takes the (by then expired) mutex over and
        writes its own payload — and the resuming holder puts its stale
        payload back on top, handing the run to a writer that no longer
        owns it.
        """
        with self._proven_ownership(intent_nonce):
            _refresh_heartbeat(self.run_dir, self.nonce, self.principal, self.session)

    def write_bytes(self, result: CheckResult, path: Path, data: bytes) -> bool:
        """Stage and commit one write under the exclusive section.

        Two-phase on purpose: the payload is staged into a temp file
        first, ownership is re-proven *immediately* before the atomic
        rename and inside the same cleanup-lock section as the rename, and
        only then does the effect happen. A writer that stalls while
        staging therefore cannot land its write after another process took
        the mutex over — not even when the stall outlived the latch TTL,
        which is exactly the case a check outside the lock would miss.
        """
        try:
            with self.exclusive_write() as intent_nonce:
                temp = _stage_temp(path, data)
                try:
                    self._commit_under_the_latch(intent_nonce, temp, path)
                except BaseException:
                    with contextlib.suppress(OSError):
                        temp.unlink()
                    raise
        except (MutexLostError, OSError) as exc:
            result.complete = False
            result.incomplete_reason = _mutation_problem(exc)
            return False
        return True

    def _commit_under_the_latch(self, intent_nonce: str, temp: Path, path: Path) -> None:
        """Swap the staged payload in as ONE section (:func:`_latched_effect`).

        This is the effect the whole mutex exists for, so it is the one that
        must not land late. Staging can take arbitrarily long; a writer that
        stalls there past the latch TTL would otherwise resume and overwrite
        the run state that a legitimate successor has meanwhile produced.
        """
        with self._proven_ownership(intent_nonce):
            _replace_owned_file(temp, path)

    def revalidate(self) -> None:
        """Confirm ownership and refresh the heartbeat before dispatch."""
        with self.exclusive_write():
            return

    def release(self) -> None:
        """Compare-before-delete the mutex under the coordination intent.

        Never raises: the teardown of a finished run must not turn into a
        crash. A release that could not do its owed work is recorded in
        :class:`_OwedEffects` instead of being dropped.
        """
        try:
            with _coordination_intent(self.run_dir, self.principal, self.session, self.owed) as intent_nonce:
                self._delete_own_mutex(intent_nonce)
        except MutexLostError as exc:
            self._blocked_release(f"the coordination intent could not be claimed for the release: {exc}")
        except OSError as exc:
            self._blocked_release(f"file system error during the release: {exc}")

    def _delete_own_mutex(self, intent_nonce: str) -> None:
        """Delete the mutex while it still carries our nonce, under the cleanup lock.

        This is the release end of the rule :func:`_latched_effect` states in
        full: a releaser that read its own nonce M1 and then stalls past the
        latch TTL loses the latch to a reclaimer, that reclaimer takes over
        the (equally expired) mutex and writes M2 — and the resuming
        releaser would unlink M2, the mutex of a LIVING owner.

        A mutex that cannot be validated is NOT deleted — the identity it
        would have to be compared against is precisely what is missing —
        and it is not treated as gone either: it stays as a blocking
        finding, because an unreadable ``RUN.mutex`` wedges the run
        directory for good (see :class:`_Orphan`).
        """
        with _latched_effect(self.run_dir, intent_nonce) as blocked:
            if blocked is not None:
                self._blocked_release(blocked)
                return
            self._compare_before_delete_mutex()

    def _compare_before_delete_mutex(self) -> None:
        """Unlink the mutex only while it still carries our nonce.

        Caller MUST hold both the coordination latch and the advisory
        cleanup lock, and MUST have re-proven the latch under that lock —
        that is what makes read-then-unlink safe here.
        """
        mutex = self.run_dir / RUN_MUTEX_FILE
        state, issues = runmodel_locks.load_mutex_state(mutex)
        ownership = _check_ownership(mutex, self.nonce, state.nonce if state is not None else None)
        if ownership is _Ownership.UNVERIFIABLE:
            self.owed.record(mutex, _unverifiable_detail(issues), permanent=True)
            return
        if ownership is not _Ownership.OURS:
            return
        detail = _remove_owned_file(mutex)
        if detail is not None:
            self.owed.record(mutex, detail)

    def _blocked_release(self, reason: str) -> None:
        """Record a release that never got to run — but only if it was still owed.

        A mutex that no longer carries our nonce was taken over; leaving it
        alone is the correct outcome, not an orphan. A mutex that cannot be
        read gives no such assurance, so it is reported rather than
        assumed away.
        """
        mutex = self.run_dir / RUN_MUTEX_FILE
        state, issues = runmodel_locks.load_mutex_state(mutex)
        ownership = _check_ownership(mutex, self.nonce, state.nonce if state is not None else None)
        if ownership is _Ownership.UNVERIFIABLE:
            self.owed.record(mutex, f"{reason}; {_unverifiable_detail(issues)}", permanent=True)
        elif ownership is _Ownership.OURS:
            self.owed.record(mutex, reason)


def _dispatch(
    args: argparse.Namespace,
    command: str,
    result: CheckResult,
    project_root: Path,
    run_dir: Path,
    run: runmodel_run.RunState,
    guard: _MutexGuard,
) -> None:
    if command == "units":
        _cmd_units(result, project_root, run_dir, run, guard)
    elif command == "prepare":
        _cmd_prepare(result, project_root, run_dir, str(args.gate), list(args.scope), guard)
    else:
        _cmd_import(result, project_root, run_dir, str(args.receipt_file), guard)


def _blockade_message(orphan: _Orphan) -> str:
    """Say how long the leftover file blocks the next writer — truthfully."""
    if orphan.permanent:
        return (
            "The file stays behind and blocks every further writer PERMANENTLY, not just for its TTL: "
            "a RUN.mutex whose payload does not validate is rejected as invalid instead of being taken over"
        )
    return f"The file stays behind and blocks every further writer until its TTL ({MUTEX_TTL_SECONDS}s) elapses"


def _orphan_message(orphan: _Orphan) -> str:
    """Spell out what an undone owed deletion means for the next writer."""
    return (
        f"owed deletion of {orphan.path} did not happen: {orphan.detail}. "
        f"{_blockade_message(orphan)}; remove it manually to unblock the run. "
        f"This is a teardown failure — the mutation itself MAY ALREADY HAVE LANDED."
    )


def _finish(args: argparse.Namespace, command: str, result: CheckResult, owed: _OwedEffects) -> int:
    """Emit the outcome and return its exit code.

    The code is decided BEFORE the owed-effect findings are appended, so
    that a teardown failure cannot be mistaken for a validation finding: it
    has its own code and the weakest rank (see
    :func:`~findings.exit_code_with_owed_effect`).
    """
    code = exit_code_with_owed_effect([result], owed_effect_failed=bool(owed.orphans))
    for orphan in owed.orphans:
        result.findings.append(error(command, orphan.path.name, "owed-deletion", _orphan_message(orphan)))
    if args.json:
        print(json.dumps(to_envelope(command, [command], [result]), indent=2, sort_keys=True))
    else:
        _print_outcome(command, result, code, len(owed.orphans))
    return code


def _print_outcome(command: str, result: CheckResult, code: int, orphans: int) -> None:
    """Render the human-readable outcome; the closing line matches the code."""
    for finding in result.findings:
        print(f"[ERROR] {finding.path}:{finding.locator} - {finding.message}")
    for report in result.reports:
        print(report)
    if not result.complete:
        print(f"[{command}] INCOMPLETE: {result.incomplete_reason}", file=sys.stderr)
    elif code == EXIT_OWED_EFFECT:
        print(f"[{command}] CLEANUP FAILED: the mutation is settled, but {orphans} owed effect(s) did not happen")
    elif result.findings:
        print(f"[{command}] FAILED: {len(result.findings)} error(s)")
    else:
        suffix = f": {result.summary}" if result.summary else ""
        print(f"[{command}] OK{suffix}")


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

#: Advisory-lock file that serializes every delete-by-observed-identity of
#: the latch. It is a pure serialization device: never deleted, never
#: carrying state — a lock file that could itself be removed would have the
#: very read-then-unlink problem it exists to solve.
INTENT_LOCK_NAME = "RUN.mutex.intent.lock"

#: How long a writer waits for a live foreign coordination intent before it
#: fails closed. The intent is a short-held latch (a handful of file
#: operations), not the ownership right — that is the mutex with its nonce,
#: TTL and fencing token. A writer that gave up on first sight would abort
#: the rightful mutex owner in its next critical section, so under real
#: contention no writer got through at all (AG3-179).
INTENT_WAIT_SECONDS = 5.0

#: Poll interval while waiting for the latch to be released.
INTENT_POLL_SECONDS = 0.02

#: How often a waiting writer re-reads the latch payload. The exclusive
#: create is the cheap probe; reading the payload is only needed to judge
#: the TTL, which is measured in minutes. Reading it on every poll would
#: keep the file open often enough to block its holder's own delete.
INTENT_PROBE_SECONDS = 1.0

#: How long a file effect is retried while another process has the file
#: open. On Windows an open reader blocks both ``unlink`` and ``replace``
#: with a sharing violation. Abandoning the effect there is not
#: fail-closed: compare-before-delete has already established ownership,
#: so a release that quietly does nothing orphans the latch until its TTL
#: elapses and blocks every writer in the meantime (AG3-179). The same
#: budget bounds the wait for the advisory cleanup lock, because that wait
#: is part of carrying out the very same owed deletion. Once it is spent
#: the failure becomes a blocking finding, never a silent success.
FILE_EFFECT_RETRY_SECONDS = 5.0


def _intent_payload(principal: str, session: str, intent_nonce: str) -> bytes:
    payload = {
        "holder_principal": principal,
        "holder_session": session,
        "intent_nonce": intent_nonce,
        "acquired_at": _now_utc(),
        "ttl_seconds": MUTEX_TTL_SECONDS,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _claim_intent(run_dir: Path, principal: str, session: str, owed: _OwedEffects) -> tuple[str | None, str | None]:
    """Claim the coordination intent; returns its nonce or why it was lost.

    ``O_CREAT|O_EXCL`` is the arbiter — never a read-then-create. A live
    foreign latch is waited out for at most ``INTENT_WAIT_SECONDS``,
    because the latch is held only across a handful of file operations;
    afterwards the claim fails closed. Its payload is re-read at most
    every ``INTENT_PROBE_SECONDS``, because a waiter that keeps the file
    open blocks its holder's own release. An existing intent is cleared
    only when its own TTL elapsed AND it still carries the exact identity
    that was observed, and that whole sequence runs under the advisory
    cleanup lock (see :func:`_cleanup_lock`).
    """
    intent = run_dir / INTENT_NAME
    nonce = uuid.uuid4().hex
    deadline = time.monotonic() + INTENT_WAIT_SECONDS
    probe_at: float | None = None
    while True:
        try:
            descriptor = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            keep_trying, probe_at = _wait_out_the_latch(run_dir, deadline, probe_at)
            if not keep_trying:
                return None, _held_intent_problem()
            continue
        except OSError as exc:
            # Not "it exists" but "the platform refused the create right
            # now" — a sharing artefact of a competitor holding the latch
            # open. Losing the claim is correct; crashing is not, because
            # this CLI's exit codes carry no meaning for a traceback.
            if not _sleep_until_spent(deadline):
                return None, f"cannot create the RUN.mutex coordination intent: {exc}; refusing to mutate"
            continue
        return _settle_fresh_latch(intent, descriptor, _intent_payload(principal, session, nonce), nonce, owed)


def _settle_fresh_latch(
    intent: Path, descriptor: int, payload: bytes, nonce: str, owed: _OwedEffects
) -> tuple[str | None, str | None]:
    """Give the exclusively created latch its payload, or give the latch back.

    The exclusive create and the payload write are two steps. Once the
    create succeeded the latch is OURS — so a failed write must not leave
    an empty file behind: every later run would read it as a freshly held
    latch and wait it out until the mtime fallback releases it a full TTL
    later. Handing the claim back is the fail-closed outcome.
    """
    created = _open_identity(descriptor)
    failure = _write_new_payload(descriptor, payload)
    if failure is None:
        return nonce, None
    _give_back_exclusive_create(intent, created, failure, owed, permanent=False)
    return None, f"cannot write the RUN.mutex coordination intent payload: {failure}; refusing to mutate"


def _open_identity(descriptor: int) -> str | None:
    """The kernel's identity of an OPEN file: its device and inode.

    A file that was created exclusively but never filled carries no nonce,
    so the payload cannot say who it belongs to. The kernel can: the
    (device, inode) pair it reports for our own descriptor names THIS file
    and no other one that may later wear the same path.

    Returns:
        The identity, or ``None`` when the platform would not report it. An
        identity we do not have is never guessed at — its only use is to
        authorize a delete.
    """
    try:
        info = os.fstat(descriptor)
    except OSError:
        return None
    return f"{info.st_dev}:{info.st_ino}"


def _path_identity(path: Path) -> str | None:
    """The identity of whatever currently wears ``path``; ``None`` if unreadable."""
    try:
        info = path.stat()
    except OSError:
        return None
    return f"{info.st_dev}:{info.st_ino}"


def _give_back_exclusive_create(
    path: Path, created: str | None, failure: OSError, owed: _OwedEffects, *, permanent: bool
) -> None:
    """Remove a file we created exclusively but could not fill, under the cleanup lock.

    THE CLAIM THIS USED TO MAKE WAS FALSE. "No competitor may touch it
    before its own TTL" is true only BEFORE that TTL — and the case that
    matters is the one after it. A caller that created the empty latch I1,
    failed its payload write and then froze loses I1 to
    :func:`_reclaim_expired_intent` once the mtime fallback fires; a
    competitor creates I2 under the same name, and the resuming caller
    deletes I2 by PATH. Same interleaving as every other read-then-act
    here, so it takes the same protection (:func:`_latched_effect` states
    the rule in full).

    The identity compared is not a nonce — the file never got one — but the
    (device, inode) pair the kernel gave our own descriptor. That is an
    exact answer to "is this still the very file I created", which is the
    whole question. The latch does NOT additionally have to be re-proven
    here: for the latch this file IS the latch, and for ``RUN.mutex`` no
    successor can exist while an empty mutex sits on the name, because
    :func:`_take_over_mutex` rejects an invalid payload before it ever
    looks at a TTL.

    ``permanent`` follows :class:`_Orphan`: an empty ``RUN.mutex`` is never
    taken over, so a leftover there wedges the run for good, whereas the
    latch has the mtime fallback.
    """
    with _cleanup_lock(path.parent, FILE_EFFECT_RETRY_SECONDS) as locked:
        if not locked:
            busy = f"the cleanup lock stayed busy for {FILE_EFFECT_RETRY_SECONDS:g}s"
            owed.record(path, _give_back_detail(busy, failure), permanent=permanent)
            return
        _delete_the_file_we_created(path, created, failure, owed, permanent=permanent)


def _delete_the_file_we_created(
    path: Path, created: str | None, failure: OSError, owed: _OwedEffects, *, permanent: bool
) -> None:
    """Compare the file identity and unlink; caller MUST hold the cleanup lock."""
    if created is None:
        unknown = "the file we created exclusively could not be identified, so it may not be deleted by path"
        owed.record(path, _give_back_detail(unknown, failure), permanent=permanent)
        return
    ownership = _check_ownership(path, created, _path_identity(path))
    if ownership is _Ownership.UNVERIFIABLE:
        unreadable = "the file exists but could not be verified as ours (its identity could not be read)"
        owed.record(path, _give_back_detail(unreadable, failure), permanent=permanent)
        return
    if ownership is not _Ownership.OURS:
        return  # reclaimed after its TTL and replaced: deleting it now would hit a competitor's file
    detail = _remove_owned_file(path)
    if detail is not None:
        owed.record(path, _give_back_detail(detail, failure), permanent=permanent)


def _give_back_detail(reason: str, failure: OSError) -> str:
    """Name why the give-back stayed undone, and what made it necessary."""
    return f"{reason} (after the payload write failed: {failure})"


def _write_new_payload(descriptor: int, payload: bytes) -> OSError | None:
    """Write ``payload`` through ``descriptor`` and close it; report the failure.

    Shared by the latch and by ``RUN.mutex``: both are claimed with
    ``O_CREAT|O_EXCL`` and then filled, so both have the same two-step gap.

    The two failure modes are kept apart on purpose: when ``fdopen``
    itself fails it never took ownership of the descriptor, so the
    descriptor must be closed here — whereas after a successful ``fdopen``
    the ``with`` block owns it and closing it again would hit an unrelated
    file.
    """
    try:
        handle = os.fdopen(descriptor, "wb")
    except OSError as exc:  # pragma: no cover - fdopen only fails on a bad descriptor
        with contextlib.suppress(OSError):
            os.close(descriptor)
        return exc
    try:
        with handle:
            handle.write(payload)
    except OSError as exc:
        return exc
    return None


def _wait_out_the_latch(run_dir: Path, deadline: float, probe_at: float | None) -> tuple[bool, float | None]:
    """Take one wait step against a latch that already exists.

    Args:
        run_dir: The incubation run directory holding latch and lock.
        deadline: Monotonic instant at which the wait budget is spent.
        probe_at: Monotonic instant of the next payload read, or ``None``
            before the first one.

    Returns:
        Whether another exclusive create is worth attempting, and the next
        probe instant. A reclaimed latch skips the sleep — the create can
        be retried immediately.
    """
    now = time.monotonic()
    if probe_at is None or now >= probe_at:
        probe_at = now + INTENT_PROBE_SECONDS
        if _reclaim_expired_intent(run_dir):
            return True, probe_at
    return _sleep_until_spent(deadline), probe_at


def _sleep_until_spent(deadline: float) -> bool:
    """Sleep one poll interval; ``False`` once the wait budget is spent."""
    if time.monotonic() >= deadline:
        return False
    time.sleep(INTENT_POLL_SECONDS)
    return True


def _held_intent_problem() -> str:
    """Describe the fail-closed exit after the wait budget is spent."""
    return f"another writer still holds the RUN.mutex coordination intent after {INTENT_WAIT_SECONDS:g}s; refusing to mutate"


def _try_advisory_lock(descriptor: int) -> bool:
    """Take the exclusive OS advisory lock in ONE non-blocking attempt.

    The ``sys.platform`` comparison must stay INLINE. ``mypy`` resolves
    ``msvcrt`` and ``fcntl`` against the platform it RUNS on, so only an
    inline narrowing makes the other branch unreachable for the checker —
    narrowing does not travel through a helper call (same pattern and same
    reason as ``installer/mcp_conformance/process.py``).
    """
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _drop_advisory_lock(descriptor: int) -> None:
    """Release the advisory lock; closing the descriptor would do it too."""
    if sys.platform == "win32":
        import msvcrt

        with contextlib.suppress(OSError):
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextlib.contextmanager
def _cleanup_lock(run_dir: Path, budget_seconds: float) -> Iterator[bool]:
    """Serialize every delete-by-observed-identity of the latch.

    Compare-before-delete is read-then-unlink and therefore not atomic on
    its own: a cleaner that read nonce N1 and stalls can delete the latch
    N2 that a competitor legitimately created in the meantime, and a third
    writer could then claim the latch in parallel. An OS advisory lock
    closes that window because the kernel — not a file we would have to
    delete ourselves — arbitrates it, and because it is released when its
    holder dies.

    It is deliberately NOT extended over the claim: ``O_CREAT|O_EXCL``
    stays the arbiter of the claim, and holding a lock across a bounded
    wait would only move the contention. It is held across a handful of
    file operations, so the wait for it is short by construction.

    Yields:
        Whether the lock is held. A caller that did not get it must not
        delete anything.
    """
    path = run_dir / INTENT_LOCK_NAME
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        yield False  # cannot even open the arbiter: never guess, never delete
        return
    acquired = _wait_for_advisory_lock(descriptor, budget_seconds)
    try:
        yield acquired
    finally:
        if acquired:
            _drop_advisory_lock(descriptor)
        os.close(descriptor)


def _wait_for_advisory_lock(descriptor: int, budget_seconds: float) -> bool:
    """Poll for the advisory lock until ``budget_seconds`` is spent."""
    deadline = time.monotonic() + budget_seconds
    while True:
        if _try_advisory_lock(descriptor):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(INTENT_POLL_SECONDS)


def _reclaim_expired_intent(run_dir: Path) -> bool:
    """Reclaim a latch whose own TTL elapsed; ``True`` if it is gone now.

    A live latch is left alone — it belongs to a writer that is inside its
    critical section. An unreadable payload counts as expired only through
    the mtime fallback of ``_clear_stale_intent``, so the gap between the
    exclusive create and the payload write is waited out, not stolen.

    Read, expiry check, identity re-check and unlink run as ONE section
    under the advisory cleanup lock. The lock is only ever attempted once
    here: if another process holds it, that process is doing this exact
    cleanup right now, so waiting for it would only duplicate its work.
    """
    intent = run_dir / INTENT_NAME
    with _cleanup_lock(run_dir, 0.0) as locked:
        if not locked:
            return False
        observed, _ = runmodel_locks.load_intent_state(intent)
        if observed is not None and not runmodel_digests.timestamp_expired(observed.acquired_at, observed.ttl_seconds):
            return False
        return _clear_stale_intent(intent, observed)


def _clear_stale_intent(intent: Path, observed: runmodel_locks.IntentState | None) -> bool:
    """Delete an expired/unreadable intent; caller MUST hold the cleanup lock."""
    if observed is None:
        # Unreadable payload: fall back to mtime age so a crashed writer
        # cannot wedge the run forever.
        try:
            if time.time() - intent.stat().st_mtime <= MUTEX_TTL_SECONDS:
                return False
        except OSError:
            return True
        return _remove_owned_file(intent) is None
    current, _ = runmodel_locks.load_intent_state(intent)
    if current is None or current.intent_nonce != observed.intent_nonce:
        return False
    return _remove_owned_file(intent) is None


def _remove_owned_file(path: Path) -> str | None:
    """Delete a file whose ownership the caller already established.

    Retries the transient Windows sharing violation: a competitor that
    merely reads the file blocks its deletion, and giving up there is not
    a stricter behaviour but an orphaned latch that blocks every writer
    until its TTL elapses.

    Returns:
        ``None`` once the file is gone, otherwise why it stayed behind.
        Every caller has to act on that — reporting it on stderr while
        exiting ``0`` is the silent success FK-78 section 78.4 forbids.
    """
    deadline = time.monotonic() + FILE_EFFECT_RETRY_SECONDS
    while True:
        try:
            path.unlink()
        except FileNotFoundError:
            return None  # someone reclaimed it after its TTL; it is gone either way
        except OSError as exc:
            if time.monotonic() >= deadline:
                return str(exc)
            time.sleep(INTENT_POLL_SECONDS)
        else:
            return None


def _release_intent(run_dir: Path, intent_nonce: str, owed: _OwedEffects) -> None:
    """Release the coordination intent by nonce match (compare-before-delete).

    Runs under the advisory cleanup lock for the same reason the reclaim
    does: read and unlink are two steps, and between them a stalled holder
    could otherwise delete a latch that is no longer its own. Here the
    lock IS waited for, bounded by ``FILE_EFFECT_RETRY_SECONDS``, because
    this deletion is owed — unlike the opportunistic reclaim.

    A latch that exists but does not validate is left alone and reported:
    deleting it would be a delete without the identity comparison, and
    passing over it silently would report a release that never happened.
    """
    intent = run_dir / INTENT_NAME
    with _cleanup_lock(run_dir, FILE_EFFECT_RETRY_SECONDS) as locked:
        if not locked:
            _record_blocked_intent_release(intent, intent_nonce, owed)
            return
        state, issues = runmodel_locks.load_intent_state(intent)
        ownership = _check_ownership(intent, intent_nonce, state.intent_nonce if state is not None else None)
        if ownership is _Ownership.UNVERIFIABLE:
            owed.record(intent, _unverifiable_detail(issues))
            return
        if ownership is not _Ownership.OURS:
            return
        detail = _remove_owned_file(intent)
        if detail is not None:
            owed.record(intent, detail)


def _record_blocked_intent_release(intent: Path, intent_nonce: str, owed: _OwedEffects) -> None:
    """Note a release that never ran — but only while it was still owed.

    A latch that no longer carries our nonce was reclaimed by someone
    else; leaving it alone is the correct outcome, not an orphan. A latch
    that cannot be read is neither gone nor provably foreign, so it is
    reported. Reading it without the lock is safe here because nothing is
    deleted on that basis — it only decides whether a finding is
    warranted.
    """
    blocked = f"the cleanup lock stayed busy for {FILE_EFFECT_RETRY_SECONDS:g}s"
    state, issues = runmodel_locks.load_intent_state(intent)
    ownership = _check_ownership(intent, intent_nonce, state.intent_nonce if state is not None else None)
    if ownership is _Ownership.UNVERIFIABLE:
        owed.record(intent, f"{blocked}; {_unverifiable_detail(issues)}")
    elif ownership is _Ownership.OURS:
        owed.record(intent, blocked)


@contextlib.contextmanager
def _coordination_intent(run_dir: Path, principal: str, session: str, owed: _OwedEffects) -> Iterator[str]:
    """Hold the single coordination intent for the enclosed mutex effect.

    Yields:
        The nonce of the claimed latch. A section that DELETES a file on the
        strength of holding this latch has to be able to re-prove that it
        still holds it (see :meth:`_MutexGuard._delete_own_mutex`), so the
        identity is handed out rather than kept private.
    """
    intent_nonce, problem = _claim_intent(run_dir, principal, session, owed)
    if intent_nonce is None:
        raise MutexLostError(problem or _held_intent_problem())
    try:
        yield intent_nonce
    finally:
        _release_intent(run_dir, intent_nonce, owed)


def _latch_lost_reason(run_dir: Path, intent_nonce: str) -> str | None:
    """Whether the latch we claimed is STILL ours; caller MUST hold the cleanup lock.

    A holder that stalls longer than the latch TTL loses it to
    :func:`_reclaim_expired_intent` while still believing it is inside its
    critical section. There is no way to prevent that by waiting harder: a
    frozen process is indistinguishable from a dead one by any timeout, and
    a heartbeat cannot be sent by a process that is not running. The sound
    answer is therefore not prevention but DETECTION — the resuming holder
    re-proves its claim before it acts.

    Returns:
        ``None`` while the latch still carries ``intent_nonce``, otherwise
        why it no longer does. A latch that cannot be verified counts as
        lost: we may not act on a claim we cannot prove.
    """
    intent = run_dir / INTENT_NAME
    state, issues = runmodel_locks.load_intent_state(intent)
    ownership = _check_ownership(intent, intent_nonce, state.intent_nonce if state is not None else None)
    if ownership is _Ownership.OURS:
        return None
    if ownership is _Ownership.UNVERIFIABLE:
        return f"the coordination intent could not be re-proven as ours ({_unverifiable_detail(issues)})"
    return f"the coordination intent was reclaimed while we held it (now: {ownership.value})"


@contextlib.contextmanager
def _latched_effect(run_dir: Path, intent_nonce: str) -> Iterator[str | None]:
    """Serialize ONE effect that follows from an earlier observation.

    THE ONE PLACE THE RULE LIVES. Read-then-act is two steps: the identity
    a caller observed is not part of the ``unlink`` or ``os.replace`` that
    follows it. A caller that observed something, then stalls past the
    latch TTL, loses the latch to a reclaimer; that reclaimer takes the
    mutex over and starts working — and the resuming caller then lands its
    effect on top of a LIVING successor. That is a safety violation, and it
    is the same violation whether the effect deletes the mutex, refreshes
    the heartbeat, replaces the mutex in a takeover or commits the
    subcommand's own payload. So all of them go through here, not just the
    one a review happened to name.

    Preventing the latch loss is impossible: a frozen process cannot
    heartbeat and no timeout tells it apart from a dead one — which is why
    the latch has a TTL in the first place. The answer is therefore
    DETECTION. Every reclaim of an expired latch needs the advisory cleanup
    lock, and every mutex takeover needs the latch; holding that lock
    across "the latch is still ours" AND the effect therefore orders the
    two events. While we are inside, nobody can reclaim our latch, hence
    nobody holds it, hence nobody can have taken the mutex over. And if the
    latch was already reclaimed before we got the lock, we see it and refuse.

    The section stays SHORT by construction — a re-read and one file
    operation, never a bounded wait and never the claim itself, which
    remains arbitrated by ``O_CREAT|O_EXCL``. It is also never nested: each
    caller enters it after the enclosing latch claim has already released
    the lock again, because the same-process advisory lock would otherwise
    block against itself.

    Args:
        run_dir: The incubation run directory holding latch and lock.
        intent_nonce: The latch identity the caller claimed earlier.

    Yields:
        ``None`` while the effect may run, otherwise the reason it may not.
        A caller that receives a reason must not perform its effect; what it
        does instead (abort, or record an owed effect) depends on whether
        the effect was owed.
    """
    with _cleanup_lock(run_dir, FILE_EFFECT_RETRY_SECONDS) as locked:
        if not locked:
            yield f"the cleanup lock stayed busy for {FILE_EFFECT_RETRY_SECONDS:g}s"
            return
        yield _latch_lost_reason(run_dir, intent_nonce)


def _acquire_mutex(
    run_dir: Path, principal: str, session: str, fencing_token: int, owed: _OwedEffects
) -> tuple[str | None, str | None]:
    """Acquire ``RUN.mutex`` under the coordination intent.

    Creating a fresh mutex and taking over an expired one both happen
    inside the SAME intent that guards heartbeat, write and release, so a
    takeover can never interleave with another writer's critical section.
    """
    nonce = uuid.uuid4().hex
    try:
        with _coordination_intent(run_dir, principal, session, owed) as intent_nonce:
            return _create_or_take_over_mutex(run_dir, nonce, principal, session, fencing_token, owed, intent_nonce)
    except (MutexLostError, OSError) as exc:
        return None, _mutation_problem(exc)


def _create_or_take_over_mutex(
    run_dir: Path, nonce: str, principal: str, session: str, fencing_token: int, owed: _OwedEffects, intent_nonce: str
) -> tuple[str | None, str | None]:
    """Create ``RUN.mutex`` exclusively, or take over the one that is there.

    ``O_CREAT|O_EXCL`` is the arbiter of a FRESH mutex, exactly as it is for
    the latch, and exactly as FK-78 section 78.4 says it is. A
    read-then-create cannot fill that role: ``Path.exists`` answers
    ``False`` for a permission or I/O error too (that is what
    :func:`_file_is_absent` exists to say), so one transient failing
    ``stat`` on a LIVE foreign mutex was enough to overwrite it with our own
    nonce. That is a SAFETY defect and not a liveness one — two writers
    would both hold what each believes is exclusive ownership of the run.
    Only the kernel can decide that a name did not exist, and
    ``FileExistsError`` is the only proof that it did.

    Every other ``OSError`` is fail-closed: "the platform refused the create
    right now" is a lost claim with a regular exit code, never a guess that
    the file is absent (Rand 2.4 of the decision record).

    The exclusive create itself needs no cleanup lock: it derives nothing
    from an earlier observation — the kernel decides, at the instant of the
    call, whether the name was free.
    """
    mutex = run_dir / RUN_MUTEX_FILE
    try:
        descriptor = os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return _take_over_mutex(run_dir, nonce, principal, session, fencing_token, intent_nonce)
    except OSError as exc:
        return None, f"cannot create RUN.mutex exclusively: {exc}; refusing to mutate"
    return _settle_fresh_mutex(mutex, descriptor, _mutex_payload(principal, session, nonce, _now_utc()), nonce, owed)


def _settle_fresh_mutex(
    mutex: Path, descriptor: int, payload: bytes, nonce: str, owed: _OwedEffects
) -> tuple[str | None, str | None]:
    """Give the exclusively created mutex its payload, or give the claim back.

    The same two-step gap as the latch (:func:`_settle_fresh_latch`), with a
    harsher leftover: an empty ``RUN.mutex`` is not a valid payload, and an
    invalid payload is rejected by :func:`_take_over_mutex` BEFORE its TTL is
    considered. Leaving one behind would wedge the run directory
    permanently, so the failed claim is handed back.
    """
    created = _open_identity(descriptor)
    failure = _write_new_payload(descriptor, payload)
    if failure is None:
        return nonce, None
    _give_back_exclusive_create(mutex, created, failure, owed, permanent=True)
    return None, f"cannot write the RUN.mutex payload: {failure}; refusing to mutate"


def _take_over_mutex(
    run_dir: Path, nonce: str, principal: str, session: str, fencing_token: int, intent_nonce: str
) -> tuple[str | None, str | None]:
    """Take over an expired mutex; caller MUST hold the coordination intent."""
    mutex = run_dir / RUN_MUTEX_FILE
    observed, issues = runmodel_locks.load_mutex_state(mutex)
    if observed is None:
        return None, _unreadable_mutex_problem(mutex, issues)
    if not runmodel_digests.timestamp_expired(observed.heartbeat_at, observed.ttl_seconds):
        return None, (
            f"RUN.mutex is held by {observed.owner_principal!r} (heartbeat {observed.heartbeat_at}); refusing to mutate"
        )
    run, _ = runmodel_run.load_run_state(run_dir / RUN_FILE)
    if run is None or run.lease_fencing_token != fencing_token:
        return None, "expired RUN.mutex takeover requires a caller fencing token equal to RUN.lease_fencing_token"
    return _commit_takeover(run_dir, nonce, principal, session, observed, intent_nonce)


def _commit_takeover(
    run_dir: Path,
    nonce: str,
    principal: str,
    session: str,
    observed: runmodel_locks.MutexState,
    intent_nonce: str,
) -> tuple[str | None, str | None]:
    """Re-read and replace the expired mutex as ONE section (:func:`_latched_effect`).

    The takeover is a read-then-replace like every other effect here, and it
    is the one with the worst outcome: a taker-over that observed the
    expired mutex M1 and then stalls past the latch TTL loses the latch, a
    successor legitimately takes M1 over and writes its live M2 — and the
    resuming taker-over replaces M2 with its own payload. Two writers would
    then both believe they hold the run. The re-read therefore happens under
    the cleanup lock, with the latch re-proven inside it, so no successor
    can exist by the time the replace runs.
    """
    mutex = run_dir / RUN_MUTEX_FILE
    with _latched_effect(run_dir, intent_nonce) as blocked:
        if blocked is not None:
            return None, f"the RUN.mutex takeover could not run safely: {blocked}; refusing to mutate"
        current, _ = runmodel_locks.load_mutex_state(mutex)
        if current is None or (current.nonce, current.heartbeat_at) != (observed.nonce, observed.heartbeat_at):
            return None, "RUN.mutex changed during takeover (another writer won the race); refusing to mutate"
        _atomic_write_bytes(mutex, _mutex_payload(principal, session, nonce, _now_utc()))
        return nonce, None


def _unreadable_mutex_problem(mutex: Path, issues: Sequence[Issue]) -> str:
    """Say why the mutex we could not create exclusively cannot be taken over.

    Reached only after ``FileExistsError``, so the file WAS there a moment
    ago. Two very different reasons can make the loader return ``None``, and
    collapsing them is the same mistake ``_Ownership`` exists to prevent:
    a payload that does not validate is refused a TTL takeover (which is
    what makes that blockade permanent), while a file that is PROVABLY gone
    means somebody deleted the mutex without holding the intent we hold —
    a protocol violation we refuse rather than race against.
    """
    if _file_is_absent(mutex):
        return "RUN.mutex vanished between the exclusive create and the takeover check; refusing to mutate"
    # No TTL takeover for an invalid payload: this refusal is the very
    # reason an unverifiable RUN.mutex wedges the run permanently.
    return f"RUN.mutex exists but is not a valid mutex payload ({_issue_detail(issues)}); refusing to mutate"


def _mutex_still_ours(run_dir: Path, nonce: str, principal: str, session: str) -> str | None:
    """Revalidate mutex ownership; returns a problem description on loss."""
    state, _ = runmodel_locks.load_mutex_state(run_dir / RUN_MUTEX_FILE)
    if state is None:
        return "RUN.mutex vanished or became unreadable during the operation; aborting"
    if state.nonce != nonce:
        return f"RUN.mutex was taken over by {state.owner_principal!r} during the operation; aborting"
    if (state.owner_principal, state.owner_session) != (principal, session):
        return "RUN.mutex owner identity changed during the operation; aborting"
    if runmodel_digests.timestamp_expired(state.heartbeat_at, state.ttl_seconds):
        return "own RUN.mutex heartbeat expired during the operation; aborting"
    return None


def _refresh_heartbeat(run_dir: Path, nonce: str, principal: str, session: str) -> None:
    """Refresh the heartbeat under the coordination intent.

    Revalidates the mutex nonce immediately before writing: a foreign
    nonce is a hard abort, never an overwrite with our own identity.

    Raises:
        MutexLostError: If the mutex is gone or owned by someone else.
    """
    state, _ = runmodel_locks.load_mutex_state(run_dir / RUN_MUTEX_FILE)
    if state is None:
        raise MutexLostError("RUN.mutex vanished before the heartbeat refresh; aborting")
    if state.nonce != nonce or (state.owner_principal, state.owner_session) != (principal, session):
        raise MutexLostError(f"RUN.mutex was taken over by {state.owner_principal!r} during the operation; aborting")
    _atomic_write_bytes(run_dir / RUN_MUTEX_FILE, _mutex_payload(principal, session, nonce, state.acquired_at))


def _verify_writer(
    run_dir: Path, result: CheckResult, principal: str, session: str, fencing_token: int
) -> runmodel_run.RunState | None:
    """Reload LEASE and RUN under the mutex and verify the caller's authority."""
    lease_path = run_dir / "LEASE.json"
    if not lease_path.is_file():
        result.complete = False
        result.incomplete_reason = "LEASE.json not found; mutations require a live writer lease"
        return None
    lease, lease_issues = runmodel_run.load_lease(lease_path)
    for issue in lease_issues:
        result.findings.append(error(result.check_id, "LEASE.json", issue.locator, issue.message))
    run_path = run_dir / RUN_FILE
    if not run_path.is_file():
        result.complete = False
        result.incomplete_reason = "RUN.json not found; mutations require the authoritative run state"
        return None
    run, run_issues = runmodel_run.load_run_state(run_path)
    for issue in run_issues:
        result.findings.append(error(result.check_id, RUN_FILE, issue.locator, issue.message))
    if lease is None or run is None:
        return None
    problems = _writer_problems(lease, run, principal, session, fencing_token)
    if problems:
        result.complete = False
        result.incomplete_reason = "; ".join(problems)
        return None
    return run


def _writer_problems(
    lease: runmodel_run.Lease, run: runmodel_run.RunState, principal: str, session: str, fencing_token: int
) -> list[str]:
    problems: list[str] = []
    if lease.run_id != run.run_id:
        problems.append(f"lease run_id {lease.run_id!r} does not match RUN.json {run.run_id!r}")
    if lease.released:
        problems.append("lease is released; acquire a new lease before mutating")
    elif runmodel_digests.timestamp_expired(lease.acquired_at, lease.ttl_seconds):
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


def _replace_owned_file(temp: Path, path: Path) -> None:
    """Commit a staged payload, retrying the transient sharing violation.

    Same reason as ``_remove_owned_file``: on Windows a competitor that
    reads the destination blocks the swap. Unlike a deletion this one must
    not be reported and dropped — a write that did not land is a hard
    error, so the last failure is raised.
    """
    deadline = time.monotonic() + FILE_EFFECT_RETRY_SECONDS
    while True:
        try:
            os.replace(temp, path)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(INTENT_POLL_SECONDS)
        else:
            return


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    _replace_owned_file(_stage_temp(path, data), path)


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def _cmd_units(
    result: CheckResult, project_root: Path, run_dir: Path, run: runmodel_run.RunState, guard: _MutexGuard
) -> None:
    register_path = run_dir / "baseline" / "source-register.tsv"
    if not register_path.is_file():
        result.complete = False
        result.incomplete_reason = "baseline/source-register.tsv not found"
        return
    rows, issues = runmodel_registers.load_source_register(register_path)
    for issue in issues:
        result.findings.append(error(result.check_id, "baseline/source-register.tsv", issue.locator, issue.message))
    units_path = run_dir / "baseline" / "source-units.tsv"
    existing: tuple[runmodel_tsv.TsvRow, ...] = ()
    if units_path.is_file():
        existing, unit_issues = runmodel_registers.load_source_units(units_path, require_disposition=False)
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
    project_root: Path, rows: tuple[runmodel_tsv.TsvRow, ...]
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
    existing: tuple[runmodel_tsv.TsvRow, ...], derived: dict[tuple[str, str], str], source_ids: set[str]
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
    run_uuid8: str, existing: tuple[runmodel_tsv.TsvRow, ...], derived: dict[tuple[str, str], str]
) -> list[runmodel_tsv.TsvRow]:
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
    manifest, issues = runmodel_promotion.load_promotion_manifest(manifest_path)
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


def _build_chunks(project_root: Path, manifest: runmodel_promotion.PromotionManifest) -> tuple[list[dict[str, str]], list[str]]:
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


def _existing_scope_pack(run_dir: Path, gate: str, scope_id: str) -> runmodel_semantic.SemanticRequestPack | None:
    requests_dir = run_dir / "semantic" / "requests"
    if not requests_dir.is_dir():
        return None
    for entry in sorted(requests_dir.glob("*.json")):
        pack, _ = runmodel_semantic.load_semantic_request_pack(entry)
        if pack is not None and pack.gate == gate and pack.scope_id == scope_id:
            return pack
    return None


def _write_pack(
    result: CheckResult,
    run_dir: Path,
    manifest: runmodel_promotion.PromotionManifest,
    gate_key: str,
    scope_id: str,
    template_digest: str,
    chunks: list[dict[str, str]],
    guard: _MutexGuard,
) -> None:
    gate = Vocab.SEMANTIC_GATE_KEYS[gate_key]
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "gate": gate,
        "scope_id": scope_id,
        "base_revision": {"kind": manifest.base_revision.kind, "value": manifest.base_revision.value},
        "template_id": gate_key,
        "template_digest": template_digest,
        "chunks": chunks,
    }
    request_digest = runmodel_digests.canonical_request_digest(payload)
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
    name = f"{gate_key}-{runmodel_digests.normalize_scope_id(scope_id)}-{request_digest[:16]}.json"
    destination = run_dir / "semantic" / "requests" / name
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if guard.write_bytes(result, destination, content):
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
    receipt, issues = runmodel_semantic.load_semantic_receipt(receipt_path)
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


def _find_pack(run_dir: Path, request_digest: str) -> runmodel_semantic.SemanticRequestPack | None:
    requests_dir = run_dir / "semantic" / "requests"
    if not requests_dir.is_dir():
        return None
    for entry in sorted(requests_dir.glob("*.json")):
        pack, _ = runmodel_semantic.load_semantic_request_pack(entry)
        if pack is not None and pack.request_digest == request_digest:
            return pack
    return None


if __name__ == "__main__":
    raise SystemExit(main())
