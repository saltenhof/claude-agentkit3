"""Real two-process mutex race: exactly one writer may take over (FK-78 78.4)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel, semantic_gate
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import TOOLS_DIR
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

GATE_SCRIPT = TOOLS_DIR / "concept_toolchain" / "semantic_gate.py"

#: Both processes block on this barrier file, then race for the takeover.
RACE_DRIVER = """
import subprocess, sys, time
script, project_root, run_rel, start_at = sys.argv[1:5]
while time.time() < float(start_at):
    time.sleep(0.001)
completed = subprocess.run(
    [sys.executable, script, "--project-root", project_root, "units", run_rel,
     "--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1"],
    check=False, capture_output=True, encoding="utf-8",
)
print(completed.returncode)
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


def race_two_processes(fixture: RunFixture, tmp_path: Path) -> list[int]:
    """Start two real processes that hit the mutex at the same wall-clock instant."""
    import time

    driver = tmp_path / "race_driver.py"
    driver.write_text(RACE_DRIVER, encoding="utf-8")
    start_at = str(time.time() + 1.5)
    arguments = [sys.executable, str(driver), str(GATE_SCRIPT), str(fixture.project_root), fixture.run_rel, start_at]

    def launch() -> subprocess.CompletedProcess[str]:
        return subprocess.run(arguments, check=False, capture_output=True, encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(launch), pool.submit(launch)]]
    return [int(result.stdout.strip().splitlines()[-1]) for result in results]


def test_two_processes_racing_a_takeover_never_mutate_concurrently(fixture: RunFixture, tmp_path: Path) -> None:
    """Both may run (serialized), but never hold the mutex at the same time.

    Under tight dual-process scheduling (especially Windows), both contenders
    can occasionally abort on coordination intent before either completes the
    takeover write (exit 2/2). Retry with a clean expired-mutex state so the
    liveness property is still proven without accepting concurrent mutation.
    """
    codes: list[int] = []
    for attempt in range(5):
        if fixture.units_path.exists():
            fixture.units_path.unlink()
        mutex_path = fixture.run_dir / "RUN.mutex"
        intent_path = fixture.run_dir / semantic_gate.INTENT_NAME
        if mutex_path.exists():
            mutex_path.unlink()
        if intent_path.exists():
            intent_path.unlink()
        write_expired_mutex(fixture)
        codes = race_two_processes(fixture, tmp_path)
        assert set(codes) <= {0, 2}, codes
        if 0 in codes:
            break
        # Both aborted on intent contention — retry with a fresh expired mutex.
        time.sleep(0.05 * (attempt + 1))
    assert 0 in codes, f"no writer won the race after retries: {codes}"
    # No writer left the mutex or the takeover intent behind.
    assert not (fixture.run_dir / "RUN.mutex").exists()
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()
    # The mutated register is contract-conform, i.e. no interleaved write happened.
    rows, issues = runmodel.load_source_units(fixture.units_path, require_disposition=False)
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
    codes = race_two_processes(fixture, tmp_path)
    assert codes == [2, 2], codes
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


def test_held_coordination_intent_blocks_a_second_writer(
    fixture: RunFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A live coordination intent makes every competing writer abort."""
    write_expired_mutex(fixture)
    write_intent(fixture)
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 2
    assert "coordination intent" in capsys.readouterr().err
    surviving = json.loads((fixture.run_dir / semantic_gate.INTENT_NAME).read_text(encoding="utf-8"))
    assert surviving["intent_nonce"] == "foreign-intent", "a live foreign intent must survive untouched"


def test_stale_intent_is_only_cleared_when_identity_still_matches(fixture: RunFixture) -> None:
    """Compare-before-delete: a reclaimer that observes a changed intent loses."""
    write_expired_mutex(fixture)
    write_intent(fixture, acquired_at="2020-01-01T00:00:00Z")
    original_load = semantic_gate.runmodel.load_intent_state
    calls = {"count": 0}

    def load_then_swap(path: Path) -> object:
        state = original_load(path)
        calls["count"] += 1
        if calls["count"] == 1:  # after the first observation another holder appears
            write_intent(fixture, nonce="fresh-intent")
        return state

    semantic_gate.runmodel.load_intent_state = load_then_swap  # type: ignore[assignment]  # noqa: SLF001 - race injection
    try:
        code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    finally:
        semantic_gate.runmodel.load_intent_state = original_load  # type: ignore[assignment]  # noqa: SLF001 - restore
    assert code == 2
    surviving = json.loads((fixture.run_dir / semantic_gate.INTENT_NAME).read_text(encoding="utf-8"))
    assert surviving["intent_nonce"] == "fresh-intent", "the newly claimed intent must not be removed"


def test_mutex_replaced_under_intent_aborts_the_loser(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """The identity CAS rejects a taker whose observed mutex was replaced."""
    write_expired_mutex(fixture)
    original_claim = semantic_gate._claim_intent  # noqa: SLF001 - race injection point

    def claim_then_replace(run_dir: Path, principal: str, session: str) -> str | None:
        claimed = original_claim(run_dir, principal, session)
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
        return claimed

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
