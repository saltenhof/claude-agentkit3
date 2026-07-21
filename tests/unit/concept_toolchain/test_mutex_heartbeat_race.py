"""Heartbeat-window interleaving under the single coordination intent (R10-1).

The reviewed hole: with separate write/takeover intents a takeover could
slip between the ownership check and the heartbeat refresh; the refresh
then rewrote the NEW mutex with the OLD nonce. With one shared
coordination intent that interleaving is impossible, and the refresh
additionally revalidates the mutex nonce immediately before writing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import semantic_gate
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import TOOLS_DIR
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

#: Writer that pauses exactly between `_mutex_still_ours` and `_refresh_heartbeat`.
HEARTBEAT_BARRIER_DRIVER = """
import sys, time
from pathlib import Path
tools, project_root, run_rel, barrier = sys.argv[1:5]
sys.path.insert(0, tools)
from concept_toolchain import semantic_gate

original_check = semantic_gate._mutex_still_ours
state = {"paused": False}


def checking(run_dir, nonce, principal, session):
    problem = original_check(run_dir, nonce, principal, session)
    if not state["paused"]:
        state["paused"] = True
        Path(barrier + ".entered").write_text("in", encoding="utf-8")
        while not Path(barrier).exists():
            time.sleep(0.02)
    return problem


semantic_gate._mutex_still_ours = checking
code = semantic_gate.main([
    "--project-root", project_root, "units", run_rel,
    "--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1",
])
print(code)
"""


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=False)


def wait_for(path: Path, *, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


def test_takeover_cannot_interleave_the_heartbeat_window(fixture: RunFixture, tmp_path: Path) -> None:
    """R10-1 (a): a paused writer must not rewrite the new owner's mutex."""
    fixture.units_path.unlink()
    driver = tmp_path / "heartbeat_driver.py"
    driver.write_text(HEARTBEAT_BARRIER_DRIVER, encoding="utf-8")
    barrier = tmp_path / "heartbeat-barrier"
    paused = subprocess.Popen(
        [sys.executable, str(driver), str(TOOLS_DIR), str(fixture.project_root), fixture.run_rel, str(barrier)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    try:
        assert wait_for(tmp_path / "heartbeat-barrier.entered"), "writer never reached the heartbeat window"
        mutex_path = fixture.run_dir / "RUN.mutex"
        paused_nonce = json.loads(mutex_path.read_text(encoding="utf-8"))["nonce"]

        # Simulate the takeover that R10-1 says must not interleave: the new
        # owner installs its own mutex while the old writer sits in the window.
        runfixtures.write_json(
            mutex_path,
            {
                "owner_principal": "other.writer",
                "owner_session": "sess-other",
                "nonce": "new-owner-nonce",
                "acquired_at": runfixtures.now_utc(),
                "heartbeat_at": runfixtures.now_utc(),
                "ttl_seconds": 600,
            },
        )

        barrier.write_text("go", encoding="utf-8")
        stdout, stderr = paused.communicate(timeout=60)
    finally:
        if paused.poll() is None:  # pragma: no cover - defensive cleanup
            paused.kill()
            paused.communicate()

    assert int(stdout.strip().splitlines()[-1]) == 2, stdout + stderr
    assert "taken over by 'other.writer'" in stderr
    surviving = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
    assert surviving["nonce"] == "new-owner-nonce" != paused_nonce, "the heartbeat rewrote the new owner's mutex"
    assert surviving["owner_principal"] == "other.writer"
    assert not fixture.units_path.exists(), "the aborted writer must not have written the register"


def test_heartbeat_refresh_rejects_a_foreign_nonce_directly(fixture: RunFixture) -> None:
    """The refresh itself is a hard abort, not an overwrite."""
    runfixtures.write_json(
        fixture.run_dir / "RUN.mutex",
        {
            "owner_principal": "other.writer",
            "owner_session": "sess-other",
            "nonce": "foreign-nonce",
            "acquired_at": runfixtures.now_utc(),
            "heartbeat_at": runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )
    with pytest.raises(semantic_gate.MutexLostError, match="taken over by"):
        semantic_gate._refresh_heartbeat(  # noqa: SLF001 - refresh guard under test
            fixture.run_dir, "our-nonce", "orch.alice", "sess-orch"
        )
    surviving = json.loads((fixture.run_dir / "RUN.mutex").read_text(encoding="utf-8"))
    assert surviving["nonce"] == "foreign-nonce"


def test_cleanup_never_removes_a_newly_claimed_intent(fixture: RunFixture) -> None:
    """R10-1 (b): the old writer must not delete an intent claimed meanwhile."""
    intent_path = fixture.run_dir / semantic_gate.INTENT_NAME
    runfixtures.write_json(
        intent_path,
        {
            "holder_principal": "other.writer",
            "holder_session": "sess-other",
            "intent_nonce": "fresh-intent",
            "acquired_at": runfixtures.now_utc(),
            "ttl_seconds": 600,
        },
    )
    semantic_gate._release_intent(fixture.run_dir, "stale-intent-nonce")  # noqa: SLF001 - release guard under test
    assert intent_path.is_file(), "a foreign intent must survive a stale holder's cleanup"
    assert json.loads(intent_path.read_text(encoding="utf-8"))["intent_nonce"] == "fresh-intent"
    semantic_gate._release_intent(fixture.run_dir, "fresh-intent")  # noqa: SLF001 - release guard under test
    assert not intent_path.exists()


def test_full_run_leaves_no_intent_behind(fixture: RunFixture) -> None:
    code = semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel, *WRITER_ARGS])
    assert code == 0
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()
    assert not (fixture.run_dir / "RUN.mutex").exists()
