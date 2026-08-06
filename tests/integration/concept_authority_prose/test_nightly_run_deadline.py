"""AG3-233: the nightly W2/W3 runs abandon a wedged service as NOT_DETERMINED.

The two nightly stages are the only ones that call an external LLM service.
They handled "the script returns an error code" and never "the script never
returns". These proofs use a listener that accepts the TCP connection and then
stays silent -- a refused port would prove something else, because a refused
connect returns immediately.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.unit.tools.concept_governance.helpers import write_doc, write_empty_baseline

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
W2_SCRIPT = REPO_ROOT / "scripts/ci/check_concept_authority_prose.py"
W3_SCRIPT = REPO_ROOT / "scripts/ci/check_concept_scope_consistency.py"
JENKINSFILE = REPO_ROOT / "Jenkinsfile"

DEADLINE_SECONDS = "5"
# One Hub send is bounded at 180s and one acquire at 30s with five retries, so
# a run that ends well inside this budget can only have been abandoned.
ABANDON_BUDGET_SECONDS = 90.0
NOT_DETERMINED_EXIT_CODE = 3


class SilentEndpoint:
    """A listener that accepts the connection and then never answers."""

    def __init__(self) -> None:
        """Bind an ephemeral port and start accepting without replying."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self.port: int = self._server.getsockname()[1]
        self._held: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept_and_hold, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        """Return the base URL of the silent endpoint."""
        return f"http://127.0.0.1:{self.port}"

    def _accept_and_hold(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            self._held.append(connection)

    def close(self) -> None:
        """Release the listener and every held connection."""
        self._server.close()
        for connection in self._held:
            connection.close()


@pytest.fixture
def silent_endpoint() -> Iterator[SilentEndpoint]:
    """Provide an endpoint that accepts and then stays silent."""
    endpoint = SilentEndpoint()
    try:
        yield endpoint
    finally:
        endpoint.close()


def test_w2_abandons_a_silent_hub_at_its_deadline_as_not_determined(
    tmp_path: Path, silent_endpoint: SilentEndpoint
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)

    started = time.monotonic()
    completed = _run_check(
        [str(W2_SCRIPT), "--mode", "nightly"], tmp_path, concept, baseline, silent_endpoint
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == NOT_DETERMINED_EXIT_CODE
    assert "concept-authority-prose: NOT_DETERMINED" in completed.stdout
    assert "RUN_DEADLINE_EXCEEDED" in completed.stdout
    assert "PASS" not in completed.stdout
    assert elapsed < ABANDON_BUDGET_SECONDS


def test_w3_abandons_a_silent_hub_at_its_deadline_as_not_determined(
    tmp_path: Path, silent_endpoint: SilentEndpoint
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    for index in range(2):
        write_doc(
            concept,
            f"lock-{index}.md",
            f"LOCK-{index}",
            "[{scope: lock.lifecycle}]",
            content=f"The lock rule number {index} must hold.",
        )
    write_empty_baseline(baseline)

    started = time.monotonic()
    completed = _run_check([str(W3_SCRIPT)], tmp_path, concept, baseline, silent_endpoint)
    elapsed = time.monotonic() - started

    assert completed.returncode == NOT_DETERMINED_EXIT_CODE
    assert "concept-scope-consistency: NOT_DETERMINED" in completed.stdout
    assert "RUN_DEADLINE_EXCEEDED" in completed.stdout
    assert "PASS" not in completed.stdout
    assert elapsed < ABANDON_BUDGET_SECONDS


@pytest.mark.parametrize("script", [str(W2_SCRIPT), str(W3_SCRIPT)])
def test_a_non_positive_deadline_is_refused_instead_of_disabling_the_bound(script: str) -> None:
    argv = [sys.executable, script, "--deadline-seconds", "0"]
    if script == str(W2_SCRIPT):
        argv.extend(["--mode", "nightly"])

    completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=False, timeout=120)

    assert completed.returncode == 2
    assert "--deadline-seconds must be positive" in completed.stderr


@pytest.mark.parametrize(
    ("stage", "check"),
    [
        ("Concept Authority Prose Nightly (non-blocking)", "W2"),
        ("Concept Scope Consistency Nightly (non-blocking)", "W3"),
    ],
)
@pytest.mark.parametrize(
    ("script_exit", "expected"),
    [
        (0, ""),
        (1, "reported untriaged or operational findings"),
        (NOT_DETERMINED_EXIT_CODE, "NO VERDICT: run abandoned at its deadline"),
        (124, "NO VERDICT: killed by the 35m stage bound"),
        (137, "NO VERDICT: killed by the 35m stage bound"),
    ],
)
def test_nightly_stage_stays_green_for_every_check_outcome(
    tmp_path: Path, stage: str, check: str, script_exit: int, expected: str
) -> None:
    shell = shutil.which("sh")
    if shell is None or shutil.which("timeout") is None:
        pytest.skip("POSIX sh and coreutils timeout are required to execute the stage body")
    workspace = _stage_workspace(tmp_path, script_exit)

    completed = subprocess.run(
        [shell, "-es"],
        input='export PATH="$PWD/bin:$PATH"\n' + _stage_shell_body(stage),
        cwd=workspace, capture_output=True, text=True, encoding="utf-8", check=False, timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert expected in completed.stdout
    if script_exit != 0:
        assert "[ERROR] " + check in completed.stdout


def _run_check(
    argv: list[str], repo_root: Path, concept: Path, baseline: Path, endpoint: SilentEndpoint
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["LLM_HUB_URL"] = endpoint.url
    return subprocess.run(
        [
            sys.executable, *argv,
            "--repo-root", str(repo_root),
            "--concept-root", str(concept),
            "--baseline", str(baseline),
            "--deadline-seconds", DEADLINE_SECONDS,
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        env=environment, timeout=ABANDON_BUDGET_SECONDS,
    )


def _stage_shell_body(stage: str) -> str:
    text = JENKINSFILE.read_text(encoding="utf-8")
    start = text.index(f"stage('{stage}')")
    body = text[text.index("sh '''", start) + len("sh '''") :]
    return body[: body.index("'''")]


def _stage_workspace(tmp_path: Path, script_exit: int) -> Path:
    activate = tmp_path / ".venv/bin/activate"
    activate.parent.mkdir(parents=True, exist_ok=True)
    activate.write_text("", encoding="utf-8")
    stub = tmp_path / "bin/python"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(f"#!/bin/sh\nexit {script_exit}\n", encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    return tmp_path
