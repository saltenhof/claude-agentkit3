"""Real two-process mutex race: exactly one writer may take over (FK-78 78.4)."""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import findings, runmodel_locks, runmodel_registers, semantic_gate
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import TOOLS_DIR
from tests.unit.concept_toolchain.runfixtures import LF, TAB, WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

GATE_SCRIPT = TOOLS_DIR / "concept_toolchain" / "semantic_gate.py"

#: Both processes block on a wall-clock instant, then race for the takeover.
#:
#: Each racer records CONSERVATIVE (inner) hold intervals: the start is stamped
#: AFTER the claim returned and the end BEFORE the release runs, so every
#: recorded interval is a strict subset of the real hold. An overlap between
#: two processes is therefore always a real violation of mutual exclusion and
#: never a measurement artefact — which is what lets the test rule out
#: concurrency inside the critical section instead of only inspecting the
#: final file content.
RACE_DRIVER = """
import json, sys, time
tools, project_root, run_rel, start_at = sys.argv[1:5]
sys.path.insert(0, tools)
from concept_toolchain import semantic_gate

spans = []


def open_span(kind):
    spans.append([kind, time.time(), None])


def close_span(kind):
    for span in reversed(spans):
        if span[0] == kind and span[2] is None:
            span[2] = time.time()
            return


claim_intent = semantic_gate._claim_intent
release_intent = semantic_gate._release_intent
acquire_mutex = semantic_gate._acquire_mutex
guard_release = semantic_gate._MutexGuard.release


def timed_claim_intent(run_dir, principal, session, owed):
    nonce, problem = claim_intent(run_dir, principal, session, owed)
    if nonce is not None:
        open_span("intent")
    return nonce, problem


def timed_release_intent(run_dir, nonce, owed):
    close_span("intent")
    release_intent(run_dir, nonce, owed)


def timed_acquire_mutex(run_dir, principal, session, token, owed):
    nonce, problem = acquire_mutex(run_dir, principal, session, token, owed)
    if nonce is not None:
        open_span("mutex")
    return nonce, problem


def timed_guard_release(self):
    close_span("mutex")
    guard_release(self)


semantic_gate._claim_intent = timed_claim_intent
semantic_gate._release_intent = timed_release_intent
semantic_gate._acquire_mutex = timed_acquire_mutex
semantic_gate._MutexGuard.release = timed_guard_release

while time.time() < float(start_at):
    time.sleep(0.001)
code = semantic_gate.main([
    "--project-root", project_root, "units", run_rel,
    "--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1",
])
print(json.dumps({"code": code, "spans": [span for span in spans if span[2] is not None]}))
"""


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=False)


def write_expired_mutex(fixture: RunFixture) -> None:
    runfixtures.write_json(
        fixture.run_dir / "RUN.mutex",
        {
            "owner_principal": "crashed.writer",
            "owner_session": "sess-crashed",
            "nonce": "crashed-nonce",
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T00:00:00Z",
            "ttl_seconds": 600,
        },
    )


@dataclass(frozen=True)
class Hold:
    """One conservatively measured hold of a coordination primitive."""

    kind: str
    start: float
    end: float

    def __str__(self) -> str:
        return f"{self.kind}[{self.start:.6f} .. {self.end:.6f}]"


@dataclass(frozen=True)
class RaceOutcome:
    """Both racers' exit codes, diagnostics and hold intervals."""

    codes: list[int]
    diagnostics: list[str]
    holds: list[list[Hold]]

    def __str__(self) -> str:
        return "\n".join(
            f"[{code}] {text.strip()} | holds: {', '.join(str(hold) for hold in held)}"
            for code, text, held in zip(self.codes, self.diagnostics, self.holds, strict=True)
        )


def race_two_processes(fixture: RunFixture, tmp_path: Path) -> RaceOutcome:
    """Start two real processes that hit the mutex at the same wall-clock instant."""
    driver = tmp_path / "race_driver.py"
    driver.write_text(RACE_DRIVER, encoding="utf-8")
    start_at = str(time.time() + 1.5)
    arguments = [sys.executable, str(driver), str(TOOLS_DIR), str(fixture.project_root), fixture.run_rel, start_at]

    def launch() -> subprocess.CompletedProcess[str]:
        return subprocess.run(arguments, check=False, capture_output=True, encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(launch), pool.submit(launch)]]
    reported = [json.loads(result.stdout.strip().splitlines()[-1]) for result in results]
    return RaceOutcome(
        codes=[int(item["code"]) for item in reported],
        diagnostics=[str(result.stderr) for result in results],
        holds=[[Hold(str(span[0]), float(span[1]), float(span[2])) for span in item["spans"]] for item in reported],
    )


def assert_holds_never_overlap(outcome: RaceOutcome, kind: str) -> None:
    """No two processes may hold the same primitive at overlapping instants."""
    first, second = ([hold for hold in held if hold.kind == kind] for held in outcome.holds)
    for left in first:
        for right in second:
            disjoint = left.end <= right.start or right.end <= left.start
            assert disjoint, f"two processes held the {kind} concurrently: {left} vs {right}\n{outcome}"


def assert_both_contended(outcome: RaceOutcome) -> None:
    """Guard against a vacuous pass: both racers must have reached the latch."""
    for index, held in enumerate(outcome.holds):
        assert any(hold.kind == "intent" for hold in held), (
            f"racer {index} never held the coordination intent, so the race proves nothing\n{outcome}"
        )


def test_two_processes_racing_a_takeover_never_mutate_concurrently(fixture: RunFixture, tmp_path: Path) -> None:
    """Both may run (serialized), but never hold the mutex at the same time."""
    fixture.units_path.unlink()
    write_expired_mutex(fixture)
    outcome = race_two_processes(fixture, tmp_path)
    codes = outcome.codes
    assert 0 in codes, f"no writer won the race:\n{outcome}"
    assert set(codes) <= {0, 2}, f"a writer neither won nor aborted cleanly:\n{outcome}"
    # Measured mutual exclusion, not just a plausible end state.
    assert_both_contended(outcome)
    assert_holds_never_overlap(outcome, "intent")
    assert_holds_never_overlap(outcome, "mutex")
    # No writer left the mutex or the takeover intent behind.
    assert not (fixture.run_dir / "RUN.mutex").exists()
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()
    # The mutated register is contract-conform, i.e. no interleaved write happened.
    rows, issues = runmodel_registers.load_source_units(fixture.units_path, require_disposition=False)
    assert issues == [], issues
    assert len(rows) == 4


def test_two_processes_racing_a_live_mutex_both_abort(fixture: RunFixture, tmp_path: Path) -> None:
    """A live foreign mutex blocks every competing writer — exactly one owner."""
    fixture.units_path.unlink()
    runfixtures.write_json(
        fixture.run_dir / "RUN.mutex",
        {
            "owner_principal": "busy.writer",
            "owner_session": "sess-busy",
            "nonce": "busy-nonce",
            "acquired_at": runfixtures.now_utc(),
            "heartbeat_at": runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )
    outcome = race_two_processes(fixture, tmp_path)
    assert outcome.codes == [2, 2], outcome
    assert not fixture.units_path.exists()
    # Both aborted, but both DID pass through the latch — serialized, never together.
    assert_both_contended(outcome)
    assert_holds_never_overlap(outcome, "intent")
    assert all(hold.kind != "mutex" for held in outcome.holds for hold in held), (
        f"nobody may own a mutex that is held by a live foreign writer\n{outcome}"
    )
    state = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
    assert state["nonce"] == "busy-nonce", "a live foreign mutex must survive untouched"


def write_intent(fixture: RunFixture, *, nonce: str = "foreign-intent", acquired_at: str | None = None) -> None:
    runfixtures.write_json(
        fixture.run_dir / semantic_gate.INTENT_NAME,
        {
            "holder_principal": "other.writer",
            "holder_session": "sess-other",
            "intent_nonce": nonce,
            "acquired_at": acquired_at or runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )


def write_latch(intent: Path, *, nonce: str = "held-latch", acquired_at: str | None = None) -> bytes:
    """Write a foreign coordination latch and return its exact bytes."""
    runfixtures.write_json(
        intent,
        {
            "holder_principal": "other.writer",
            "holder_session": "sess-other",
            "intent_nonce": nonce,
            "acquired_at": acquired_at or runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )
    return intent.read_bytes()


def claim_latch(run_dir: Path, owed: semantic_gate._OwedEffects | None = None) -> tuple[str | None, str | None]:
    """Claim the latch as the unit under test, with an owed-effects sink."""
    sink = owed if owed is not None else semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    return semantic_gate._claim_intent(run_dir, "orch.alice", "sess-orch", sink)  # noqa: SLF001 - unit under test


def test_a_live_latch_is_waited_out_instead_of_lost(tmp_path: Path) -> None:
    """AG3-179: the latch is short-held, so a competitor waits for it."""
    intent = tmp_path / semantic_gate.INTENT_NAME
    write_latch(intent)
    releasing = threading.Timer(0.3, semantic_gate._remove_owned_file, args=(intent,))  # noqa: SLF001 - same delete path
    releasing.start()
    try:
        nonce, problem = claim_latch(tmp_path)
    finally:
        releasing.join()
    assert nonce is not None, f"the waiting writer must get the latch once its holder releases it: {problem}"
    state, issues = runmodel_locks.load_intent_state(intent)
    assert issues == [], issues
    assert state is not None
    assert (state.holder_principal, state.intent_nonce) == ("orch.alice", nonce)


def test_the_wait_budget_ends_in_a_fail_closed_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting is bounded ON BOTH SIDES: not shorter, and not longer either.

    The lower bound alone would be satisfied by a writer that waits
    forever, i.e. by the very defect the bound is supposed to exclude. The
    rescue timer exists so an unbounded implementation TERMINATES instead
    of hanging the suite: it frees the latch long after the budget, which
    makes an unbounded writer succeed late — and both the ``nonce is None``
    assertion and the upper bound then fail loudly.
    """
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)  # the budget, not the behaviour, is shortened
    intent = tmp_path / semantic_gate.INTENT_NAME
    held = write_latch(intent)
    rescue = threading.Timer(10.0, lambda: intent.unlink(missing_ok=True))
    rescue.start()
    started = time.monotonic()
    try:
        nonce, problem = claim_latch(tmp_path)
    finally:
        rescue.cancel()
        rescue.join()
    elapsed = time.monotonic() - started
    assert nonce is None, "a writer must not get a latch that its holder never released"
    assert problem is not None and "coordination intent" in problem, problem
    assert elapsed >= 0.2, "a writer must not give up before its wait budget is spent"
    assert elapsed < 5.0, f"the wait must END with its budget; it took {elapsed:.2f}s for a 0.2s budget"
    assert intent.read_bytes() == held, "a live foreign latch must survive untouched"


def test_an_expired_latch_is_still_reclaimed_without_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting must not delay the takeover of a crash-orphaned latch."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 30.0)  # dwarfs the measurement below
    intent = tmp_path / semantic_gate.INTENT_NAME
    write_latch(intent, acquired_at="2020-01-01T00:00:00Z")
    started = time.monotonic()
    nonce, problem = claim_latch(tmp_path)
    assert nonce is not None, problem
    assert time.monotonic() - started < 1.0, "an expired latch is reclaimed, not waited out"


def test_a_latch_without_a_payload_yet_is_waited_out_not_stolen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exclusive create and the payload write are two steps; the gap is a hold."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)
    intent = tmp_path / semantic_gate.INTENT_NAME
    intent.touch()
    nonce, _ = claim_latch(tmp_path)
    assert nonce is None
    assert intent.exists(), "a fresh latch that is not readable yet must not be reclaimed"


def test_a_refused_create_aborts_cleanly_instead_of_crashing(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A create the platform refuses is a lost claim, never a traceback.

    Only ``FileExistsError`` used to be handled, so any other OS error on
    the latch left the CLI with an uncaught exception and exit code 1 —
    a code this CLI's contract gives a precise meaning (blocking
    validation findings; a failed owed effect has its own code 4), never a
    crash. The real
    trigger (a Windows sharing violation) cannot be provoked on demand, so
    the refusal itself is injected; the behaviour under test is the exit,
    not the errno.
    """
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)
    real_open = os.open

    def refuse_the_latch(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if str(path).endswith(semantic_gate.INTENT_NAME):
            raise PermissionError(13, "sharing violation")
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(semantic_gate.os, "open", refuse_the_latch)
    write_expired_mutex(fixture)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2, "a refused latch must be a clean INCOMPLETE, not a crash"
    assert "cannot create the RUN.mutex coordination intent" in capsys.readouterr().err


def test_a_refused_commit_aborts_cleanly_instead_of_crashing(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A commit the file system refuses is INCOMPLETE, not an uncaught error.

    The staged write is committed with a bounded retry; when that budget
    is spent the error is real and must reach the caller as an exit code
    with a reason, not as a traceback.
    """
    fixture.units_path.unlink()
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    real_replace = os.replace

    def refuse_the_units(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if str(dst).endswith("source-units.tsv"):
            raise PermissionError(13, "sharing violation")
        real_replace(src, dst, *args, **kwargs)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(semantic_gate.os, "replace", refuse_the_units)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2, "a refused commit must be a clean INCOMPLETE, not a crash"
    assert "file system error while coordinating the mutex" in capsys.readouterr().err
    assert not fixture.units_path.exists(), "nothing may be left behind by a refused commit"
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()


def test_a_reader_holding_the_latch_open_cannot_orphan_it(tmp_path: Path) -> None:
    """The release must wait out a reader, not give the deletion up.

    On Windows a reader that has the file open blocks ``unlink`` with a
    sharing violation (WinError 32). Swallowing that error left the latch
    behind for its full TTL, and every later writer then waited it out and
    aborted — with a waiting competitor polling the payload, exactly that
    happened under load (AG3-179). On platforms without mandatory sharing
    the deletion succeeds at once and this stays a regression guard.
    """
    intent = tmp_path / semantic_gate.INTENT_NAME
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    nonce, problem = claim_latch(tmp_path, owed)
    assert nonce is not None, problem
    opened = threading.Event()

    def hold_open() -> None:
        with intent.open("rb"):
            opened.set()
            time.sleep(0.3)

    reader = threading.Thread(target=hold_open, name="latch-reader")
    reader.start()
    try:
        assert opened.wait(timeout=10), "the reader never got the latch open"
        semantic_gate._release_intent(tmp_path, nonce, owed)  # noqa: SLF001 - unit under test
    finally:
        reader.join(timeout=10)
    assert not intent.exists(), "a released latch must not survive its holder"
    assert owed.orphans == [], "a release that succeeded must not report an orphan"


def test_a_flickering_competitor_cannot_evict_the_mutex_owner(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG3-179 regression: the loser's latch holds must not abort the owner.

    The rightful owner claims the latch four times (acquire, revalidate,
    write, release). A competitor that takes the latch between two of them
    used to end the owner's run with exit 2 — so under contention nobody
    got through at all.

    Both directions of contention are FORCED, not hoped for — a counter
    that merely observes whichever way the scheduler happened to go proves
    nothing on a good day and flakes on a bad one:

    * The competitor holds its first latch until the owner has demonstrably
      waited for it, so the owner's very first claim contends.
    * While the owner holds the latch, a competing exclusive create is
      attempted from inside its own critical section. The arbiter must
      refuse it. That is the same collision the flickering thread used to
      hit by luck, only now it cannot be missed.
    """
    fixture.units_path.unlink()
    intent = fixture.run_dir / semantic_gate.INTENT_NAME
    stop = threading.Event()
    competitor_holds_it = threading.Event()
    owner_waited = threading.Event()
    collisions = {"count": 0, "stolen": 0}
    waits = {"count": 0}

    original_wait = semantic_gate._wait_out_the_latch  # noqa: SLF001 - contention counter
    original_release = semantic_gate._release_intent  # noqa: SLF001 - probe point

    def counting_wait(run_dir: Path, deadline: float, probe_at: float | None) -> tuple[bool, float | None]:
        waits["count"] += 1
        owner_waited.set()
        return original_wait(run_dir, deadline, probe_at)  # type: ignore[no-any-return]  # passthrough

    def probed_release(run_dir: Path, nonce: str, owed: semantic_gate._OwedEffects) -> None:
        # Runs while the owner STILL holds the latch: an exclusive create by
        # anyone else must fail here, every single time.
        try:
            os.close(os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            collisions["count"] += 1
        else:
            collisions["stolen"] += 1
        original_release(run_dir, nonce, owed)

    monkeypatch.setattr(semantic_gate, "_wait_out_the_latch", counting_wait)
    monkeypatch.setattr(semantic_gate, "_release_intent", probed_release)

    def flicker() -> None:
        first_hold = True
        while not stop.is_set():
            try:
                descriptor = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                time.sleep(0.005)  # the owner holds it; a competitor never steals
                continue
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(semantic_gate._intent_payload("other.writer", "sess-other", "flicker"))  # noqa: SLF001 - competitor payload
            competitor_holds_it.set()
            if first_hold:
                first_hold = False
                owner_waited.wait(timeout=10)  # hold until the owner really had to wait
            else:
                time.sleep(0.04)
            with contextlib.suppress(OSError):
                intent.unlink()  # only ever the latch this thread created exclusively
            time.sleep(0.04)

    competitor = threading.Thread(target=flicker, name="latch-flicker")
    competitor.start()
    try:
        assert competitor_holds_it.wait(timeout=10), "the competitor never got the latch"
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        stop.set()
        owner_waited.set()  # never leave the competitor hanging on a failed run
        competitor.join(timeout=10)
    assert code == 0, "a competitor holding the latch briefly must not abort the mutex owner"
    assert waits["count"] > 0, "the owner never had to wait for the competitor — no contention was exercised"
    assert collisions["stolen"] == 0, "someone claimed the latch while the owner was holding it"
    assert collisions["count"] > 0, "the owner's own hold was never probed — no contention was exercised"
    rows, issues = runmodel_registers.load_source_units(fixture.units_path, require_disposition=False)
    assert issues == [], issues
    assert len(rows) == 4


def test_held_coordination_intent_blocks_a_second_writer(
    fixture: RunFixture, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live coordination intent makes every competing writer abort."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)  # the latch is waited out; only shorten the budget
    write_expired_mutex(fixture)
    write_intent(fixture)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2
    assert "coordination intent" in capsys.readouterr().err
    surviving = json.loads((fixture.run_dir / semantic_gate.INTENT_NAME).read_text(encoding="utf-8"))
    assert surviving["intent_nonce"] == "foreign-intent", "a live foreign intent must survive untouched"


def test_stale_intent_is_only_cleared_when_identity_still_matches(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compare-before-delete: a reclaimer that observes a changed intent loses."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)  # the fresh latch is live, so only the budget ends it
    write_expired_mutex(fixture)
    write_intent(fixture, acquired_at="2020-01-01T00:00:00Z")
    original_load = semantic_gate.runmodel_locks.load_intent_state
    calls = {"count": 0}

    def load_then_swap(path: Path) -> object:
        state = original_load(path)
        calls["count"] += 1
        if calls["count"] == 1:  # after the first observation another holder appears
            write_intent(fixture, nonce="fresh-intent")
        return state

    semantic_gate.runmodel_locks.load_intent_state = load_then_swap  # type: ignore[assignment]  # noqa: SLF001 - race injection
    try:
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        semantic_gate.runmodel_locks.load_intent_state = original_load  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert code == 2
    surviving = json.loads((fixture.run_dir / semantic_gate.INTENT_NAME).read_text(encoding="utf-8"))
    assert surviving["intent_nonce"] == "fresh-intent", "the newly claimed intent must not be removed"


def test_mutex_replaced_under_intent_aborts_the_loser(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """The identity CAS rejects a taker whose observed mutex was replaced."""
    write_expired_mutex(fixture)
    original_claim = semantic_gate._claim_intent  # noqa: SLF001 - race injection point

    def claim_then_replace(
        run_dir: Path, principal: str, session: str, owed: semantic_gate._OwedEffects
    ) -> tuple[str | None, str | None]:
        claimed, problem = original_claim(run_dir, principal, session, owed)
        if claimed is not None:
            runfixtures.write_json(
                fixture.run_dir / "RUN.mutex",
                {
                    "owner_principal": "other.writer",
                    "owner_session": "sess-other",
                    "nonce": "winner-nonce",
                    "acquired_at": runfixtures.now_utc(),
                    "heartbeat_at": runfixtures.now_utc(),
                    "ttl_seconds": 600,
                },
            )
        return claimed, problem

    semantic_gate._claim_intent = claim_then_replace  # type: ignore[assignment]  # noqa: SLF001 - race injection
    try:
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        semantic_gate._claim_intent = original_claim  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert code == 2
    assert "refusing to mutate" in capsys.readouterr().err
    state = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
    assert state["nonce"] == "winner-nonce"


def test_foreign_nonce_during_operation_aborts(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """Losing the mutex mid-operation is a hard abort, never a silent write."""
    fixture.units_path.unlink()
    original_write = semantic_gate._atomic_write_bytes  # noqa: SLF001 - injection point

    def steal_then_write(path: Path, data: bytes) -> None:
        if path.name == "RUN.mutex":
            original_write(path, data)
            runfixtures.write_json(
                path,
                {
                    "owner_principal": "thief",
                    "owner_session": "sess-thief",
                    "nonce": "stolen-nonce",
                    "acquired_at": runfixtures.now_utc(),
                    "heartbeat_at": runfixtures.now_utc(),
                    "ttl_seconds": 600,
                },
            )
            return
        original_write(path, data)

    semantic_gate._atomic_write_bytes = steal_then_write  # type: ignore[assignment]  # noqa: SLF001 - injection
    try:
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        semantic_gate._atomic_write_bytes = original_write  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert code == 2
    assert "taken over by 'thief'" in capsys.readouterr().err
    assert not fixture.units_path.exists(), "aborted run must not have written the register"


#: Writer that stalls WHILE STAGING its write, i.e. right after the guard check.
STALL_DRIVER = """
import sys, time
from pathlib import Path
tools, project_root, run_rel, barrier = sys.argv[1:5]
sys.path.insert(0, tools)
from concept_toolchain import semantic_gate

original = semantic_gate._stage_temp
state = {"stalled": False}


def stalling(path, data):
    temp = original(path, data)
    if not state["stalled"] and path.name == "source-units.tsv":
        state["stalled"] = True
        Path(barrier + ".entered").write_text("in", encoding="utf-8")
        while not Path(barrier).exists():
            time.sleep(0.02)
    return temp


semantic_gate._stage_temp = stalling
code = semantic_gate.main([
    "--project-root", project_root, "units", run_rel,
    "--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1",
])
print(code)
"""


def test_stalled_writer_lands_neither_write_nor_release(fixture: RunFixture, tmp_path: Path) -> None:
    """R9-1: a writer stalled past the TTL must not write and must not release."""
    fixture.units_path.unlink()
    driver = tmp_path / "stall_driver.py"
    driver.write_text(STALL_DRIVER, encoding="utf-8")
    barrier = tmp_path / "release-barrier"
    stalled = subprocess.Popen(
        [sys.executable, str(driver), str(TOOLS_DIR), str(fixture.project_root), fixture.run_rel, str(barrier)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    try:
        entered = tmp_path / "release-barrier.entered"
        deadline = time.time() + 30
        while not entered.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert entered.exists(), "stalled writer never reached its staged write"
        assert not fixture.units_path.exists(), "nothing may be committed while staging"

        # The stalled writer is paused past its TTL: expire mutex and intents.
        state = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
        stalled_nonce = state["nonce"]
        state["heartbeat_at"] = "2020-01-01T00:00:00Z"
        state["acquired_at"] = "2020-01-01T00:00:00Z"
        runfixtures.write_json(fixture.run_dir / "RUN.mutex", state)
        intent_path = fixture.run_dir / semantic_gate.INTENT_NAME
        held_intent = json.loads(intent_path.read_text(encoding="utf-8"))
        held_intent_nonce = held_intent["intent_nonce"]
        held_intent["acquired_at"] = "2020-01-01T00:00:00Z"
        runfixtures.write_json(intent_path, held_intent)

        # Process 2 takes the mutex over and completes a full write.
        takeover = semantic_gate.main(
            ["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS]
        )
        assert takeover == 0, "the live writer must be able to take over the expired mutex"
        after_takeover = fixture.units_path.read_bytes()
        foreign_mutex = {
            "owner_principal": "other.writer",
            "owner_session": "sess-other",
            "nonce": "owner-after-takeover",
            "acquired_at": runfixtures.now_utc(),
            "heartbeat_at": runfixtures.now_utc(),
            "ttl_seconds": 600,
        }
        runfixtures.write_json(fixture.run_dir / "RUN.mutex", foreign_mutex)

        barrier.write_text("go", encoding="utf-8")
        stdout, stderr = stalled.communicate(timeout=60)
    finally:
        if stalled.poll() is None:  # pragma: no cover - defensive cleanup
            stalled.kill()
            stalled.communicate()

    reported = int(stdout.strip().splitlines()[-1])
    assert reported == 2, "stalled writer must abort after losing the mutex: " + stdout + stderr
    assert "taken over by" in stderr
    assert held_intent_nonce != "", "the stalled writer must have held a coordination intent"
    assert fixture.units_path.read_bytes() == after_takeover, "the stalled writer's write landed after the takeover"
    # Its release must not remove the new owner's mutex (compare-before-delete).
    surviving = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
    assert surviving["nonce"] == "owner-after-takeover" != stalled_nonce
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()


# --------------------------------------------------------------------------
# An owed deletion that does not happen is never a success
# --------------------------------------------------------------------------


def refuse_unlink_of(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the deletion of exactly one file fail like a sharing violation.

    A reader that blocks ``unlink`` for the WHOLE retry budget cannot be
    provoked on demand — it is a timing artefact of the platform. The
    refusal is therefore injected; what is under test is the outcome of a
    definitively failed owed deletion, not the errno that caused it.
    """
    real_unlink = pathlib.Path.unlink

    def refusing(self: pathlib.Path, *args: object, **kwargs: object) -> None:
        if self.name == name:
            raise PermissionError(32, "the process cannot access the file because it is being used")
        real_unlink(self, *args, **kwargs)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(pathlib.Path, "unlink", refusing)


def test_a_failed_owed_deletion_is_never_reported_as_success(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AG3-179 / FK-78 78.4: an orphaned mutex ends the run, not with ``OK``.

    The release runs in ``main``'s ``finally``. When its owed deletion
    fails for good, the mutex stays behind and blocks EVERY further writer
    until its TTL elapses — reporting that on stderr while exiting 0 made
    the CLI claim a clean run over a wedged run directory.
    """
    fixture.units_path.unlink()
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    refuse_unlink_of(monkeypatch, "RUN.mutex")
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    captured = capsys.readouterr()
    assert code != 0, f"a run that orphaned its mutex must not exit 0:\n{captured.out}{captured.err}"
    assert "[units] OK" not in captured.out, "an orphaned mutex must never be reported as success"
    assert (fixture.run_dir / "RUN.mutex").exists(), "the injection must really leave the file behind"
    # The mutation is NOT retroactively denied: it landed, and the report says so.
    assert fixture.units_path.exists(), "the write landed and must not be reported away"
    assert "MAY ALREADY HAVE LANDED" in captured.out, captured.out
    assert "RUN.mutex" in captured.out, captured.out
    assert "blocks every further writer" in captured.out, captured.out


def test_a_failed_owed_deletion_is_a_structured_finding_in_the_envelope(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The outcome travels in the FK-78 envelope, not as a print to stderr."""
    fixture.units_path.unlink()
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    refuse_unlink_of(monkeypatch, "RUN.mutex")
    code = semantic_gate.main(
        ["--project-root", str(fixture.project_root), "--json", "units", fixture.run_rel, *WRITER_ARGS]
    )
    envelope = json.loads(capsys.readouterr().out)
    assert code == findings.EXIT_OWED_EFFECT, envelope
    orphan_findings = [
        finding
        for finding in envelope["findings"]
        if finding["severity"] == "ERROR" and finding["path"] == "RUN.mutex" and finding["locator"] == "owed-deletion"
    ]
    assert orphan_findings, envelope
    assert envelope["complete"] is True, "the check ran to completion; only its teardown failed"


def test_a_failed_owed_deletion_has_its_own_exit_code(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PO decision 2026-08-02: "work done, cleanup failed" is its own code.

    A consumer must be able to tell three different situations apart
    WITHOUT parsing the message: the content is wrong (1), nothing ran
    (2), or the work is settled and only the run directory needs a hand
    (4). Folding the third into 1 made every caller either treat a wedged
    directory as a content defect or ignore both.
    """
    fixture.units_path.unlink()
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    refuse_unlink_of(monkeypatch, "RUN.mutex")
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    captured = capsys.readouterr()
    assert code == findings.EXIT_OWED_EFFECT == 4, f"{captured.out}{captured.err}"
    assert code not in {findings.EXIT_PASS, findings.EXIT_FINDINGS, findings.EXIT_INCOMPLETE, findings.EXIT_USAGE}
    assert "CLEANUP FAILED" in captured.out, captured.out
    assert "[units] OK" not in captured.out
    assert fixture.units_path.exists(), "the code says the work is settled, so it must be"


def test_a_real_finding_outranks_a_failed_cleanup(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rank 2 of the contract: a wrong result is worse than a wedged directory.

    Exit 4 asserts that the work is done. A run that also produced a
    blocking validation finding must therefore NOT report 4 — that would
    tell the caller its content was accepted.
    """
    fixture.units_path.unlink()
    register = fixture.run_dir / "baseline" / "source-register.tsv"
    lines = register.read_text(encoding="utf-8").splitlines()
    columns = lines[0].split(TAB)
    row = lines[1].split(TAB)
    row[columns.index("sha256")] = "0" * 64  # digest drift: a real validation finding
    register.write_text(LF.join([lines[0], TAB.join(row), *lines[2:]]) + LF, encoding="utf-8", newline=LF)
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    refuse_unlink_of(monkeypatch, "RUN.mutex")
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    captured = capsys.readouterr()
    assert code == findings.EXIT_FINDINGS, f"{captured.out}{captured.err}"
    assert "owed-deletion" in captured.out, "the orphan is still reported, it just does not decide the code"
    assert not fixture.units_path.exists(), "a run with findings must not have written the register"


def test_a_missing_prerequisite_outranks_a_failed_cleanup(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rank 1 of the contract: a run that never ran cannot report work done."""
    fixture.units_path.unlink()
    (fixture.run_dir / "LEASE.json").unlink()
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    refuse_unlink_of(monkeypatch, "RUN.mutex")
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    captured = capsys.readouterr()
    assert code == findings.EXIT_INCOMPLETE, f"{captured.out}{captured.err}"
    assert "INCOMPLETE" in captured.err
    assert "owed-deletion" in captured.out, "the orphan is still reported, it just does not decide the code"
    assert not fixture.units_path.exists()


def test_a_release_that_cannot_get_the_cleanup_lock_reports_the_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting for the cleanup lock is bounded, and giving up is not silent."""
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    intent = tmp_path / semantic_gate.INTENT_NAME
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    nonce, problem = claim_latch(tmp_path, owed)
    assert nonce is not None, problem
    descriptor = os.open(tmp_path / semantic_gate.INTENT_LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    started = time.monotonic()
    try:
        assert semantic_gate._try_advisory_lock(descriptor), "a second descriptor must be able to take the lock"  # noqa: SLF001 - unit under test
        semantic_gate._release_intent(tmp_path, nonce, owed)  # noqa: SLF001 - unit under test
    finally:
        semantic_gate._drop_advisory_lock(descriptor)  # noqa: SLF001 - unit under test
        os.close(descriptor)
    assert time.monotonic() - started < 3.0, "the wait for the cleanup lock must be bounded"
    assert intent.exists(), "the release could not run, so the latch is still there"
    assert [orphan for orphan in owed.orphans if orphan.path.name == semantic_gate.INTENT_NAME], owed.orphans


# --------------------------------------------------------------------------
# "Gone" and "there but unverifiable" are never the same answer
# --------------------------------------------------------------------------


def corrupt_the_mutex_before_the_release(monkeypatch: pytest.MonkeyPatch, mutex: Path) -> None:
    """Make the release's final re-read of ``RUN.mutex`` find no valid payload.

    The reviewed scenario is a read error or a corrupt file at exactly the
    instant the release re-reads the mutex to compare nonces — the instant
    is what makes it dangerous, because the mutation has already landed by
    then. A broken payload is one of the ways ``load_mutex_state`` answers
    ``None``; the injection places it at that seam, the real
    ``_compare_before_delete_mutex`` then runs untouched — behind the
    cleanup lock and the latch re-proof, which both still happen for real.
    """
    original = semantic_gate._MutexGuard._compare_before_delete_mutex  # noqa: SLF001 - seam, the real method still runs

    def corrupt_then_delete(self: semantic_gate._MutexGuard) -> None:
        mutex.write_bytes(b"{ this is not a mutex payload\n")
        original(self)

    monkeypatch.setattr(  # noqa: SLF001 - injection
        semantic_gate._MutexGuard, "_compare_before_delete_mutex", corrupt_then_delete
    )


def test_an_unverifiable_mutex_is_never_deleted_and_never_reported_as_success(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AG3-179 / FK-78 78.4: a mutex that cannot be read is not a mutex that is gone.

    ``load_mutex_state`` returns ``None`` for a missing file AND for one
    that is there but unreadable. Treating the second as the first made the
    release return without deleting anything and without owing anything —
    exit 0 and ``[units] OK`` over a run directory that is wedged for good,
    because an invalid payload is rejected by the takeover instead of being
    taken over after its TTL.
    """
    fixture.units_path.unlink()
    mutex = fixture.run_dir / "RUN.mutex"
    corrupt_the_mutex_before_the_release(monkeypatch, mutex)
    code = semantic_gate.main(
        ["--project-root", str(fixture.project_root), "--json", "units", fixture.run_rel, *WRITER_ARGS]
    )
    envelope = json.loads(capsys.readouterr().out)
    assert code == findings.EXIT_OWED_EFFECT, envelope
    orphan_findings = [
        finding
        for finding in envelope["findings"]
        if finding["path"] == "RUN.mutex" and finding["locator"] == "owed-deletion"
    ]
    assert orphan_findings, envelope
    message = str(orphan_findings[0]["message"])
    assert "could not be verified as ours" in message, message
    assert "file: not readable as JSON" in message, "the loader's own diagnosis is the reason and must survive"
    assert "PERMANENTLY" in message, "an unreadable RUN.mutex is never taken over after its TTL"
    assert mutex.exists(), "a file whose identity cannot be read must never be deleted unverified"
    assert fixture.units_path.exists(), "the mutation landed and must not be reported away"


def test_an_unverifiable_latch_is_never_deleted_and_never_silently_released(tmp_path: Path) -> None:
    """The same confusion on the intent: a latch that does not validate stays.

    Unlike the mutex the latch IS cleared by the mtime fallback once its
    TTL elapsed, so the blockade it causes is bounded — the finding says
    so, and does not promise a takeover that will not come.
    """
    intent = tmp_path / semantic_gate.INTENT_NAME
    intent.write_bytes(b'{"holder_principal": "orch.alice"}\n')  # valid JSON, no valid latch identity
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    semantic_gate._release_intent(tmp_path, "our-nonce", owed)  # noqa: SLF001 - unit under test
    assert intent.exists(), "a latch whose identity cannot be read must not be deleted unverified"
    orphans = [orphan for orphan in owed.orphans if orphan.path.name == semantic_gate.INTENT_NAME]
    assert orphans, owed.orphans
    assert "could not be verified as ours" in orphans[0].detail, orphans[0].detail
    assert "missing required field" in orphans[0].detail, "the loader's diagnosis is the reason"
    assert orphans[0].permanent is False, "the mtime fallback releases an unreadable latch after its TTL"


def test_a_release_that_cannot_claim_the_intent_reports_an_unverifiable_mutex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blocked release must not read "unreadable" as "already gone" either."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)
    write_latch(tmp_path / semantic_gate.INTENT_NAME)  # a live foreign latch blocks the claim
    mutex = tmp_path / "RUN.mutex"
    mutex.write_bytes(b"{ this is not a mutex payload\n")
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    semantic_gate._MutexGuard(tmp_path, "our-nonce", "orch.alice", "sess-orch", owed).release()  # noqa: SLF001 - unit under test
    orphans = [orphan for orphan in owed.orphans if orphan.path.name == "RUN.mutex"]
    assert orphans, owed.orphans
    assert "the coordination intent could not be claimed" in orphans[0].detail, orphans[0].detail
    assert "could not be verified as ours" in orphans[0].detail, orphans[0].detail
    assert orphans[0].permanent is True, "an invalid RUN.mutex payload is never taken over"
    assert mutex.exists()


def test_a_blocked_intent_release_reports_an_unverifiable_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup lock busy AND latch unreadable is two reasons, not zero."""
    monkeypatch.setattr(semantic_gate, "FILE_EFFECT_RETRY_SECONDS", 0.05)
    intent = tmp_path / semantic_gate.INTENT_NAME
    intent.write_bytes(b"{ this is not a latch payload\n")
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    descriptor = os.open(tmp_path / semantic_gate.INTENT_LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert semantic_gate._try_advisory_lock(descriptor), "a second descriptor must be able to take the lock"  # noqa: SLF001 - unit under test
        semantic_gate._release_intent(tmp_path, "our-nonce", owed)  # noqa: SLF001 - unit under test
    finally:
        semantic_gate._drop_advisory_lock(descriptor)  # noqa: SLF001 - unit under test
        os.close(descriptor)
    orphans = [orphan for orphan in owed.orphans if orphan.path.name == semantic_gate.INTENT_NAME]
    assert orphans, owed.orphans
    assert "cleanup lock stayed busy" in orphans[0].detail, orphans[0].detail
    assert "could not be verified as ours" in orphans[0].detail, orphans[0].detail
    assert intent.exists()


def test_only_a_file_not_found_error_proves_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence must be PROVEN — and ``Path.exists`` proves nothing.

    ``Path.exists`` answers ``False`` for a permission or I/O error exactly
    as it does for a missing file, which is the very confusion this whole
    distinction exists to remove, one level further down. Only
    ``FileNotFoundError`` is proof; on any other ``OSError`` we could not
    tell, and fail-closed then has to say "not gone" — which turns a
    compare-before-delete into a reported orphan instead of a silent
    success. The failing ``stat`` is injected because a directory we may
    not traverse cannot be produced on demand in a temp dir.
    """
    missing = tmp_path / "never-existed"
    assert semantic_gate._file_is_absent(missing) is True, "a real FileNotFoundError IS proof"  # noqa: SLF001 - the rule under test
    real_stat = pathlib.Path.stat

    def refuse_stat(self: pathlib.Path, *args: object, **kwargs: object) -> object:
        if self.name == "never-existed":
            raise PermissionError(13, "cannot stat the file")
        return real_stat(self, *args, **kwargs)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(pathlib.Path, "stat", refuse_stat)
    assert semantic_gate._file_is_absent(missing) is False, (  # noqa: SLF001 - the rule under test
        "a stat we could not perform must never be read as proof of absence"
    )
    assert semantic_gate._check_ownership(missing, "our-nonce", None) is semantic_gate._Ownership.UNVERIFIABLE, (  # noqa: SLF001 - the rule under test
        "and the caller must therefore owe a finding rather than assume the deletion happened"
    )


def test_a_provably_absent_file_is_never_an_orphan(tmp_path: Path) -> None:
    """The other half of the distinction: gone IS success, and stays silent.

    Without this the fix could degenerate into "report everything", which
    would turn every ordinary clean run into a blocking finding.
    """
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    semantic_gate._release_intent(tmp_path, "our-nonce", owed)  # noqa: SLF001 - unit under test
    assert owed.orphans == [], "a latch that was never there is not an orphan"
    semantic_gate._MutexGuard(tmp_path, "our-nonce", "orch.alice", "sess-orch", owed).release()  # noqa: SLF001 - unit under test
    assert owed.orphans == [], "a mutex that was never there is not an orphan"
    assert not (tmp_path / semantic_gate.INTENT_NAME).exists(), "the release cleaned up its own latch"


# --------------------------------------------------------------------------
# A failed payload write gives the latch back
# --------------------------------------------------------------------------


def test_a_failed_latch_payload_write_gives_the_latch_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AG3-179: the exclusive create makes the latch OURS — including its cleanup.

    ``O_CREAT|O_EXCL`` succeeds, then the payload write fails (a full disk,
    an I/O error). The empty file left behind used to look like a freshly
    held latch to every later run, which then waited it out and aborted —
    for a full TTL, because only the mtime fallback releases a latch
    without a readable payload. A full disk cannot be provoked on demand,
    so the failure is injected; the behaviour under test is the cleanup.
    """
    intent = tmp_path / semantic_gate.INTENT_NAME
    real_write = semantic_gate._write_new_payload  # noqa: SLF001 - failure injection point
    calls = {"count": 0}

    def flaky_write(descriptor: int, payload: bytes) -> OSError | None:
        calls["count"] += 1
        if calls["count"] == 1:
            os.close(descriptor)  # the real write path would have closed it too
            return OSError(28, "no space left on device")
        return real_write(descriptor, payload)  # type: ignore[no-any-return]  # passthrough

    monkeypatch.setattr(semantic_gate, "_write_new_payload", flaky_write)
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    nonce, problem = claim_latch(tmp_path, owed)
    assert nonce is None, "a latch without its payload is not a claim"
    assert problem is not None and "payload" in problem, problem
    assert not intent.exists(), "an empty latch must not stay behind"
    assert owed.orphans == [], "the cleanup succeeded, so nothing was orphaned"
    # And the run directory is not wedged: the next claim goes through at once.
    started = time.monotonic()
    second, second_problem = claim_latch(tmp_path)
    assert second is not None, second_problem
    assert time.monotonic() - started < 1.0, "the abandoned latch must not delay the next writer"


# --------------------------------------------------------------------------
# The read-then-unlink window is closed by an OS advisory lock
# --------------------------------------------------------------------------


def test_the_latch_cleanup_section_is_mutually_exclusive(tmp_path: Path) -> None:
    """AG3-179 / FK-78 78.4: compare-before-delete alone is not atomic.

    Cleaner A reads the expired nonce N1 and stalls before its ``unlink``.
    B removes N1, exclusively creates N2 and enters its critical section —
    and A then deletes N2, because the expected nonce is not part of the
    delete operation. A third writer could claim the latch in parallel.

    The advisory lock closes exactly that window, so what has to be proven
    is that no second cleaner can be inside the section while the first one
    sits between its identity check and its unlink.
    """
    intent = tmp_path / semantic_gate.INTENT_NAME
    held = write_latch(intent, nonce="expired-one", acquired_at="2020-01-01T00:00:00Z")
    inside = threading.Event()
    resume = threading.Event()
    real_remove = semantic_gate._remove_owned_file  # noqa: SLF001 - stall injection point
    outcome: dict[str, bool] = {}

    def stalling_remove(path: pathlib.Path) -> str | None:
        inside.set()
        assert resume.wait(timeout=30), "the stalled cleaner was never resumed"
        return real_remove(path)  # type: ignore[no-any-return]  # passthrough

    def first_cleaner() -> None:
        outcome["reclaimed"] = semantic_gate._reclaim_expired_intent(tmp_path)  # noqa: SLF001 - unit under test

    semantic_gate._remove_owned_file = stalling_remove  # type: ignore[assignment]  # noqa: SLF001 - stall injection
    cleaner = threading.Thread(target=first_cleaner, name="latch-cleaner")
    cleaner.start()
    try:
        assert inside.wait(timeout=30), "the first cleaner never reached its unlink"
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - only the FIRST cleaner stalls
        assert semantic_gate._reclaim_expired_intent(tmp_path) is False, (  # noqa: SLF001 - unit under test
            "a second cleaner entered the section while the first one was inside it"
        )
        assert intent.read_bytes() == held, "the second cleaner must not have touched the latch"
    finally:
        resume.set()
        cleaner.join(timeout=30)
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert outcome["reclaimed"] is True, "the cleaner that owned the section must finish its reclaim"
    assert not intent.exists()


def test_the_release_section_is_mutually_exclusive(tmp_path: Path) -> None:
    """AG3-179 / FK-78 78.4: the OWED delete path holds the lock too.

    Same window as the reclaim, on the path that matters more: the release
    reads its own nonce and then unlinks. A holder that stalls between
    those two steps must not be able to remove a latch that someone else
    legitimately created in the meantime, so no second cleaner may be
    inside the section while it sits there.

    This is deliberately a stopped interleaving and not a sequential
    check. Taking the advisory lock and dropping it again BEFORE the read
    reopens the read-then-unlink window completely, and every other
    release test stays green under exactly that mutation: they only prove
    that a busy lock file aborts, that the lock file gets created, and
    that a foreign nonce survives a sequential release.
    """
    intent = tmp_path / semantic_gate.INTENT_NAME
    held = write_latch(intent, nonce="held-by-us", acquired_at="2020-01-01T00:00:00Z")
    inside = threading.Event()
    resume = threading.Event()
    real_remove = semantic_gate._remove_owned_file  # noqa: SLF001 - stall injection point
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test

    def stalling_remove(path: pathlib.Path) -> str | None:
        inside.set()
        assert resume.wait(timeout=30), "the stalled releaser was never resumed"
        return real_remove(path)  # type: ignore[no-any-return]  # passthrough

    def releaser() -> None:
        semantic_gate._release_intent(tmp_path, "held-by-us", owed)  # noqa: SLF001 - unit under test

    semantic_gate._remove_owned_file = stalling_remove  # type: ignore[assignment]  # noqa: SLF001 - stall injection
    thread = threading.Thread(target=releaser, name="latch-releaser")
    thread.start()
    try:
        assert inside.wait(timeout=30), "the release never reached its unlink"
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - only the RELEASE stalls
        # The latch is expired, so a cleaner WOULD collect it — unless the
        # release still owns the section. That is the whole assertion.
        assert semantic_gate._reclaim_expired_intent(tmp_path) is False, (  # noqa: SLF001 - second entrant
            "a cleaner entered the cleanup section while the release was inside it"
        )
        assert intent.read_bytes() == held, "the cleaner must not have touched the latch"
    finally:
        resume.set()
        thread.join(timeout=30)
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert not intent.exists(), "the release that owned the section must finish its owed deletion"
    assert owed.orphans == [], owed.orphans


# --------------------------------------------------------------------------
# O_CREAT|O_EXCL arbitrates the FRESH mutex too, not just the latch
# --------------------------------------------------------------------------


def write_live_foreign_mutex(fixture: RunFixture, *, nonce: str = "busy-nonce") -> bytes:
    """Write a mutex held by someone else RIGHT NOW and return its bytes."""
    runfixtures.write_json(
        fixture.run_dir / "RUN.mutex",
        {
            "owner_principal": "busy.writer",
            "owner_session": "sess-busy",
            "nonce": nonce,
            "acquired_at": runfixtures.now_utc(),
            "heartbeat_at": runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )
    return (fixture.run_dir / "RUN.mutex").read_bytes()


def test_a_failing_stat_never_makes_a_live_mutex_look_absent(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AG3-179 R1: the fresh mutex is CREATED exclusively, never written after a look.

    ``Path.exists`` answers ``False`` for a permission or I/O error just as
    it does for a missing file — the very confusion ``_file_is_absent``
    exists to name. A read-then-create acquire therefore overwrote a LIVE
    foreign mutex with its own nonce the moment one ``stat`` failed, and
    two writers then both believed they owned the run. That is a SAFETY
    defect, not a liveness one, so the arbiter has to be the kernel:
    ``O_CREAT|O_EXCL`` cannot be fooled by a failing ``stat``.

    The failing stat is injected exactly as the operating system reports
    it, i.e. as ``exists() is False`` on a file that is very much there.
    """
    fixture.units_path.unlink()
    held = write_live_foreign_mutex(fixture)
    real_exists = pathlib.Path.exists

    def blind_exists(self: pathlib.Path, **kwargs: object) -> bool:
        if self.name == "RUN.mutex":
            return False  # what a failed stat looks like from here
        return bool(real_exists(self, **kwargs))  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(pathlib.Path, "exists", blind_exists)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2, "a live foreign mutex is a hard abort, whatever stat says"
    assert "is held by" in capsys.readouterr().err
    assert (fixture.run_dir / "RUN.mutex").read_bytes() == held, "a live foreign mutex was overwritten with our nonce"
    assert not fixture.units_path.exists(), "nothing may be mutated without the mutex"


def test_the_fresh_mutex_claim_wins_the_name_before_it_has_a_payload(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exclusive create happens BEFORE the payload exists — that is the point.

    Stopped interleaving at the only seam both a read-then-create and an
    exclusive create share: building the payload. A read-then-create has
    already decided "absent" by then and has NOT taken the name, so a
    competitor can still slip a live mutex in and get it overwritten. An
    exclusive create holds the name at that instant, so the competitor's
    own exclusive create must fail — every time, not usually.
    """
    fixture.units_path.unlink()
    mutex = fixture.run_dir / "RUN.mutex"
    real_payload = semantic_gate._mutex_payload  # noqa: SLF001 - interleaving point
    competitor: dict[str, bool] = {}

    def competing_payload(principal: str, session: str, nonce: str, acquired_at: str) -> bytes:
        if "created" not in competitor:
            try:
                descriptor = os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                competitor["created"] = False
            else:
                os.close(descriptor)
                competitor["created"] = True
        return real_payload(principal, session, nonce, acquired_at)  # type: ignore[no-any-return]  # passthrough

    monkeypatch.setattr(semantic_gate, "_mutex_payload", competing_payload)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert competitor, "the interleaving point was never reached — the test proves nothing"
    assert competitor["created"] is False, "the mutex name was still free while its payload was being built"
    assert code == 0, "the exclusive creator owns the run and must complete it"
    assert not mutex.exists(), "the owner released its own mutex"


def test_a_refused_mutex_create_aborts_cleanly_instead_of_crashing(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not "it exists" but "the platform refused it": a lost claim, never a traceback.

    Every exit code of this CLI carries its own meaning; a crash carries
    none. Only ``FileExistsError`` may route into the takeover — any other
    ``OSError`` is fail-closed with a regular exit.
    """
    fixture.units_path.unlink()
    real_open = os.open

    def refusing_open(path: object, flags: int, *rest: int) -> int:
        if str(path).endswith("RUN.mutex") and flags & os.O_EXCL:
            raise PermissionError(13, "permission denied")
        return real_open(path, flags, *rest)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(semantic_gate.os, "open", refusing_open)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2, "a refused create is a missing prerequisite, not a validation finding"
    assert "cannot create RUN.mutex exclusively" in capsys.readouterr().err
    assert not (fixture.run_dir / "RUN.mutex").exists()
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists(), "the latch must not be orphaned either"
    assert not fixture.units_path.exists()


def test_a_failed_mutex_payload_write_gives_the_claim_back(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty RUN.mutex would wedge the run FOREVER, so the claim is handed back.

    Same two-step gap as the latch, with a harsher leftover: an invalid
    mutex payload is rejected by the takeover before its TTL is even looked
    at, so nothing ever collects it. The next run must therefore find the
    directory usable.
    """
    fixture.units_path.unlink()
    mutex = fixture.run_dir / "RUN.mutex"
    real_write = semantic_gate._write_new_payload  # noqa: SLF001 - failure injection point
    failed: dict[str, bool] = {}

    def flaky_write(descriptor: int, payload: bytes) -> OSError | None:
        if b"owner_principal" in payload and "once" not in failed:
            failed["once"] = True
            os.close(descriptor)  # the real write path would have closed it too
            return OSError(28, "no space left on device")
        return real_write(descriptor, payload)  # type: ignore[no-any-return]  # passthrough

    monkeypatch.setattr(semantic_gate, "_write_new_payload", flaky_write)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert failed, "the mutex payload write was never exercised"
    assert code == 2, "a claim without its payload is not a claim"
    assert "cannot write the RUN.mutex payload" in capsys.readouterr().err
    assert not mutex.exists(), "an empty RUN.mutex must not stay behind — nothing would ever collect it"
    monkeypatch.undo()
    second = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert second == 0, "the run directory must not be wedged by the abandoned claim"


# --------------------------------------------------------------------------
# A releaser that lost its latch must not delete its successor's mutex
# --------------------------------------------------------------------------


def write_own_expired_mutex(run_dir: Path, nonce: str) -> bytes:
    """Write a mutex owned by orch.alice whose heartbeat has long expired."""
    runfixtures.write_json(
        run_dir / "RUN.mutex",
        {
            "owner_principal": "orch.alice",
            "owner_session": "sess-orch",
            "nonce": nonce,
            "acquired_at": "2020-01-01T00:00:00Z",
            "heartbeat_at": "2020-01-01T00:00:00Z",
            "ttl_seconds": 600,
        },
    )
    return (run_dir / "RUN.mutex").read_bytes()


def alice_guard(run_dir: Path, nonce: str, owed: semantic_gate._OwedEffects) -> semantic_gate._MutexGuard:
    """The guard of the writer that is about to release its own mutex."""
    return semantic_gate._MutexGuard(run_dir, nonce, "orch.alice", "sess-orch", owed)  # noqa: SLF001 - unit under test


def test_a_stalled_release_cannot_lose_its_latch_and_delete_the_successor(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG3-179 R2: the OWED mutex delete is atomic against a latch reclaim.

    The interleaving that used to destroy a living owner's mutex: A holds
    latch I1 and reads its own mutex M1, then stalls past the latch TTL. B
    reclaims I1, claims I2, takes over the (also expired) M1 and writes M2 —
    and A, resuming, unlinks by PATH and removes M2, the mutex of a writer
    that is inside its critical section.

    Holding the advisory cleanup lock across "the latch is still ours" and
    the compare-before-delete orders the two events: while A is inside, B
    cannot reclaim the latch, so B cannot hold it, so B cannot take the
    mutex over. B loses its claim — fail-closed — instead of losing a mutex
    it legitimately owned.
    """
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.3)  # the budget, not the behaviour
    run_dir = fixture.run_dir
    intent = run_dir / semantic_gate.INTENT_NAME
    mutex = run_dir / "RUN.mutex"
    write_latch(intent, nonce="alice-latch", acquired_at="2020-01-01T00:00:00Z")  # A stalled past the TTL
    alice_mutex = write_own_expired_mutex(run_dir, "alice-mutex")
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    inside = threading.Event()
    resume = threading.Event()
    real_remove = semantic_gate._remove_owned_file  # noqa: SLF001 - stall injection point
    seen: dict[str, object] = {}

    def stalling_remove(path: pathlib.Path) -> str | None:
        if path.name == "RUN.mutex":
            inside.set()
            assert resume.wait(timeout=30), "the stalled releaser was never resumed"
        return real_remove(path)  # type: ignore[no-any-return]  # passthrough

    def releaser() -> None:
        # The owed delete itself, entered with the latch A claimed long ago.
        # Going through ``release()`` would claim a FRESH latch here, and a
        # fresh latch is by definition not yet reclaimable — the stall that
        # matters is the one that outlived the latch A already had.
        alice_guard(run_dir, "alice-mutex", owed)._delete_own_mutex("alice-latch")  # noqa: SLF001 - unit under test

    semantic_gate._remove_owned_file = stalling_remove  # type: ignore[assignment]  # noqa: SLF001 - stall injection
    thread = threading.Thread(target=releaser, name="mutex-releaser")
    thread.start()
    try:
        assert inside.wait(timeout=30), "the release never reached its unlink"
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - only A stalls
        bob_owed = semantic_gate._OwedEffects()  # noqa: SLF001 - the competitor's own sink
        seen["nonce"], seen["problem"] = semantic_gate._acquire_mutex(  # noqa: SLF001 - the real competitor
            run_dir, "orch.bob", "sess-bob", 1, bob_owed
        )
        seen["mutex"] = mutex.read_bytes() if mutex.exists() else None
    finally:
        resume.set()
        thread.join(timeout=30)
        semantic_gate._remove_owned_file = real_remove  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert seen["nonce"] is None, f"a competitor took the mutex over while the release owned the section: {seen}"
    assert "coordination intent" in str(seen["problem"]), seen["problem"]
    assert seen["mutex"] == alice_mutex, "the mutex changed hands inside someone else's cleanup section"
    assert not mutex.exists(), "the releaser that owned the section must finish its owed deletion"
    assert owed.orphans == [], owed.orphans


def test_a_releaser_whose_latch_was_reclaimed_refuses_to_delete(fixture: RunFixture) -> None:
    """The other half of R2: if the latch IS gone, the release must notice.

    Prevention is impossible — a frozen process cannot heartbeat and no
    timeout tells it apart from a dead one — so the resuming holder has to
    DETECT the loss. Two outcomes, both fail-closed and neither destructive:
    a successor's mutex is left alone silently, and a mutex that is still
    ours is left alone with a blocking finding, because we could no longer
    prove we were allowed to remove it.
    """
    run_dir = fixture.run_dir
    intent = run_dir / semantic_gate.INTENT_NAME
    mutex = run_dir / "RUN.mutex"

    # (a) A successor already established itself: nothing to report, nothing to touch.
    write_latch(intent, nonce="bob-latch")
    successor = write_live_foreign_mutex(fixture, nonce="bob-mutex")
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    alice_guard(run_dir, "alice-mutex", owed)._delete_own_mutex("alice-latch")  # noqa: SLF001 - unit under test
    assert mutex.read_bytes() == successor, "the successor's mutex must survive the resuming releaser"
    assert owed.orphans == [], "a mutex that is not ours is not an orphan of ours"

    # (b) Our own mutex is still there, but we can no longer prove the claim.
    still_ours = write_own_expired_mutex(run_dir, "alice-mutex")
    owed = semantic_gate._OwedEffects()  # noqa: SLF001 - unit under test
    alice_guard(run_dir, "alice-mutex", owed)._delete_own_mutex("alice-latch")  # noqa: SLF001 - unit under test
    assert mutex.read_bytes() == still_ours, "an unproven claim may not delete, however familiar the nonce looks"
    assert len(owed.orphans) == 1, owed.orphans
    assert "reclaimed while we held it" in owed.orphans[0].detail, owed.orphans[0].detail


def test_the_cleanup_lock_is_a_pure_serialization_device(fixture: RunFixture) -> None:
    """The lock file is never deleted and never carries state.

    A lock file that could itself be removed would have the very
    read-then-unlink problem it exists to solve, so it outlives every run.
    """
    fixture.units_path.unlink()
    lock = fixture.run_dir / semantic_gate.INTENT_LOCK_NAME
    first = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert first == 0
    assert lock.is_file(), "the cleanup lock must survive the run that created it"
    assert lock.stat().st_size == 0, "the cleanup lock carries no state"
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()
    assert not (fixture.run_dir / "RUN.mutex").exists()
    second = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert second == 0, "an existing lock file must not block the next run"
    assert lock.is_file()
