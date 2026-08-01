"""Real two-process mutex race: exactly one writer may take over (FK-78 78.4)."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel_locks, runmodel_registers, semantic_gate
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import TOOLS_DIR
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

GATE_SCRIPT = TOOLS_DIR / "concept_toolchain" / "semantic_gate.py"

#: Both processes block on this barrier file, then race for the takeover.
RACE_DRIVER = """
import json, subprocess, sys, time
script, project_root, run_rel, start_at = sys.argv[1:5]
while time.time() < float(start_at):
    time.sleep(0.001)
completed = subprocess.run(
    [sys.executable, script, "--project-root", project_root, "units", run_rel,
     "--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1"],
    check=False, capture_output=True, encoding="utf-8",
)
print(json.dumps({"code": completed.returncode, "stderr": completed.stderr}))
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
class RaceOutcome:
    """Both racers' exit codes plus their diagnostics, so a red race is readable."""

    codes: list[int]
    diagnostics: list[str]

    def __str__(self) -> str:
        return "\n".join(f"[{code}] {text.strip()}" for code, text in zip(self.codes, self.diagnostics, strict=True))


def race_two_processes(fixture: RunFixture, tmp_path: Path) -> RaceOutcome:
    """Start two real processes that hit the mutex at the same wall-clock instant."""
    driver = tmp_path / "race_driver.py"
    driver.write_text(RACE_DRIVER, encoding="utf-8")
    start_at = str(time.time() + 1.5)
    arguments = [sys.executable, str(driver), str(GATE_SCRIPT), str(fixture.project_root), fixture.run_rel, start_at]

    def launch() -> subprocess.CompletedProcess[str]:
        return subprocess.run(arguments, check=False, capture_output=True, encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(launch), pool.submit(launch)]]
    reported = [json.loads(result.stdout.strip().splitlines()[-1]) for result in results]
    return RaceOutcome([int(item["code"]) for item in reported], [str(item["stderr"]) for item in reported])


def test_two_processes_racing_a_takeover_never_mutate_concurrently(fixture: RunFixture, tmp_path: Path) -> None:
    """Both may run (serialized), but never hold the mutex at the same time."""
    fixture.units_path.unlink()
    write_expired_mutex(fixture)
    outcome = race_two_processes(fixture, tmp_path)
    codes = outcome.codes
    assert 0 in codes, f"no writer won the race:\n{outcome}"
    assert set(codes) <= {0, 2}, f"a writer neither won nor aborted cleanly:\n{outcome}"
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


def test_a_live_latch_is_waited_out_instead_of_lost(tmp_path: Path) -> None:
    """AG3-179: the latch is short-held, so a competitor waits for it."""
    intent = tmp_path / semantic_gate.INTENT_NAME
    write_latch(intent)
    releasing = threading.Timer(0.3, semantic_gate._remove_owned_file, args=(intent,))  # noqa: SLF001 - same delete path
    releasing.start()
    try:
        nonce, problem = semantic_gate._claim_intent(tmp_path, "orch.alice", "sess-orch")  # noqa: SLF001 - unit under test
    finally:
        releasing.join()
    assert nonce is not None, f"the waiting writer must get the latch once its holder releases it: {problem}"
    state, issues = runmodel_locks.load_intent_state(intent)
    assert issues == [], issues
    assert state is not None
    assert (state.holder_principal, state.intent_nonce) == ("orch.alice", nonce)


def test_the_wait_budget_ends_in_a_fail_closed_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting is bounded: a latch that never frees up is still a hard abort."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)  # the budget, not the behaviour, is shortened
    intent = tmp_path / semantic_gate.INTENT_NAME
    held = write_latch(intent)
    started = time.monotonic()
    nonce, problem = semantic_gate._claim_intent(tmp_path, "orch.alice", "sess-orch")  # noqa: SLF001 - unit under test
    assert nonce is None
    assert problem is not None and "coordination intent" in problem, problem
    assert time.monotonic() - started >= 0.2, "a writer must not give up before its wait budget is spent"
    assert intent.read_bytes() == held, "a live foreign latch must survive untouched"


def test_an_expired_latch_is_still_reclaimed_without_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting must not delay the takeover of a crash-orphaned latch."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 30.0)  # dwarfs the measurement below
    intent = tmp_path / semantic_gate.INTENT_NAME
    write_latch(intent, acquired_at="2020-01-01T00:00:00Z")
    started = time.monotonic()
    nonce, problem = semantic_gate._claim_intent(tmp_path, "orch.alice", "sess-orch")  # noqa: SLF001 - unit under test
    assert nonce is not None, problem
    assert time.monotonic() - started < 1.0, "an expired latch is reclaimed, not waited out"


def test_a_latch_without_a_payload_yet_is_waited_out_not_stolen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exclusive create and the payload write are two steps; the gap is a hold."""
    monkeypatch.setattr(semantic_gate, "INTENT_WAIT_SECONDS", 0.2)
    intent = tmp_path / semantic_gate.INTENT_NAME
    intent.touch()
    nonce, _ = semantic_gate._claim_intent(tmp_path, "orch.alice", "sess-orch")  # noqa: SLF001 - unit under test
    assert nonce is None
    assert intent.exists(), "a fresh latch that is not readable yet must not be reclaimed"


def test_a_refused_create_aborts_cleanly_instead_of_crashing(
    fixture: RunFixture, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A create the platform refuses is a lost claim, never a traceback.

    Only ``FileExistsError`` used to be handled, so any other OS error on
    the latch left the CLI with an uncaught exception and exit code 1 —
    which this CLI's contract reserves for validation findings. The real
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
    nonce, problem = semantic_gate._claim_intent(tmp_path, "orch.alice", "sess-orch")  # noqa: SLF001 - unit under test
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
        semantic_gate._release_intent(tmp_path, nonce)  # noqa: SLF001 - unit under test
    finally:
        reader.join(timeout=10)
    assert not intent.exists(), "a released latch must not survive its holder"


def test_a_flickering_competitor_cannot_evict_the_mutex_owner(fixture: RunFixture) -> None:
    """AG3-179 regression: the loser's latch holds must not abort the owner.

    The rightful owner claims the latch four times (acquire, revalidate,
    write, release). A competitor that takes the latch between two of them
    used to end the owner's run with exit 2 — so under contention nobody
    got through at all.
    """
    fixture.units_path.unlink()
    intent = fixture.run_dir / semantic_gate.INTENT_NAME
    stop = threading.Event()

    def flicker() -> None:
        while not stop.is_set():
            try:
                descriptor = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                time.sleep(0.005)  # the owner holds it; a competitor never steals
                continue
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(semantic_gate._intent_payload("other.writer", "sess-other", "flicker"))  # noqa: SLF001 - competitor payload
            time.sleep(0.04)
            with contextlib.suppress(OSError):
                intent.unlink()  # only ever the latch this thread created exclusively
            time.sleep(0.04)

    competitor = threading.Thread(target=flicker, name="latch-flicker")
    competitor.start()
    try:
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        stop.set()
        competitor.join(timeout=10)
    assert code == 0, "a competitor holding the latch briefly must not abort the mutex owner"
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

    def claim_then_replace(run_dir: Path, principal: str, session: str) -> tuple[str | None, str | None]:
        claimed, problem = original_claim(run_dir, principal, session)
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
