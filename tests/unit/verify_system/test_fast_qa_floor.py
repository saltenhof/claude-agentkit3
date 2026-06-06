"""Fast-mode QA floor tests (AG3-018 DELTA-C, FK-24 §24.3.4).

In ``mode == fast`` the QA-subflow degenerates to Layer 1 (structural) + the
hard tests-green floor; Layers 2 (LLM), 3 (adversarial), 4 (policy) and the
feedback/remediation loop are SKIPPED. A red test (or an unconfirmable result)
is a fail-closed FAIL (NO ERROR BYPASSING).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import ArtifactEnvelope, ArtifactManager, ArtifactReference
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system import VerifyContextBundle, VerifySystem
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture(autouse=True)
def _git_worktree(tmp_path: Path) -> None:
    """A real git worktree so the QA-cycle fingerprint computes (no fail-open)."""
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Test")
    (tmp_path / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", ".")
    _git("commit", "-m", "base")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")


class _RecordingLayer:
    def __init__(self, name: str, *, passed: bool = True) -> None:
        self._name = name
        self._passed = passed
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self, ctx: object, story_dir: Path, *, review_input: object = None
    ) -> LayerResult:
        del ctx, story_dir, review_input
        self.calls += 1
        return LayerResult(layer=self._name, passed=self._passed, findings=())


class _RecordingArtifactManager(ArtifactManager):
    def __init__(self) -> None:
        self.written: list[ArtifactEnvelope] = []

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        self.written.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"rec/{envelope.stage}/{envelope.attempt}",
        )


class _FastStoryContextPort:
    def load(self, story_dir: Path) -> object:
        del story_dir
        return StoryContext(
            project_key="proj",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.FAST,
        )


def _make_fast_system(
    *,
    layer_1: _RecordingLayer | None = None,
    layer_2a: _RecordingLayer | None = None,
    layer_3: _RecordingLayer | None = None,
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None,
) -> tuple[VerifySystem, _RecordingLayer, _RecordingLayer, _RecordingLayer]:
    l1 = layer_1 or _RecordingLayer("structural")
    l2a = layer_2a or _RecordingLayer("qa_review")
    l3 = layer_3 or _RecordingLayer("adversarial")
    vs = VerifySystem(
        layer_1=l1,
        layer_2a=l2a,
        layer_2b=_RecordingLayer("semantic_review"),
        layer_2c=_RecordingLayer("doc_fidelity"),
        layer_3=l3,
        policy_engine=PolicyEngine(),
        artifact_manager=_RecordingArtifactManager(),
        story_context_port=_FastStoryContextPort(),
        fast_test_runner=fast_test_runner,
    )
    return vs, l1, l2a, l3


def _bundle(tmp_path: Path) -> VerifyContextBundle:
    return VerifyContextBundle(
        run_id="run-test-001", story_dir=tmp_path, phase_envelope=None, attempt=1
    )


def _target() -> ArtifactReference:
    return ArtifactReference(
        artifact_class=ArtifactClass.WORKER,
        story_id="TEST-001",
        run_id="run-test-001",
        record_key="envelopes/worker/TEST-001/1",
    )


def test_fast_floor_runs_only_layer1_and_tests_green(tmp_path: Path) -> None:
    vs, l1, l2a, l3 = _make_fast_system(
        fast_test_runner=lambda _d: (True, None)
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
    )
    assert outcome.verdict is PolicyVerdict.PASS
    # Layer 1 (structural) ran; Layers 2/3 did NOT.
    assert l1.calls == 1
    assert l2a.calls == 0
    assert l3.calls == 0
    # No remediation/escalation loop on the fast path.
    assert outcome.escalated is False
    assert outcome.feedback is None


def test_fast_floor_red_tests_fail(tmp_path: Path) -> None:
    vs, _l1, l2a, l3 = _make_fast_system(
        fast_test_runner=lambda _d: (False, "2 tests failed")
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
    )
    assert outcome.verdict is PolicyVerdict.FAIL
    # Still skipped Layers 2/3 (no LLM/adversarial on the fast path).
    assert l2a.calls == 0
    assert l3.calls == 0
    assert any("2 tests failed" in f.message for f in outcome.decision.all_findings)


def test_fast_floor_unconfirmable_tests_fail_closed(tmp_path: Path) -> None:
    # No fast_test_runner wired -> the floor is unconfirmable -> FAIL (NO ERROR
    # BYPASSING; a fast story without a confirmed test result must not pass).
    vs, _l1, _l2a, _l3 = _make_fast_system(fast_test_runner=None)
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
    )
    assert outcome.verdict is PolicyVerdict.FAIL


def test_fast_floor_structural_failure_fails(tmp_path: Path) -> None:
    # A failing structural layer fails the floor even with green tests.
    vs, _l1, _l2a, _l3 = _make_fast_system(
        layer_1=_RecordingLayer("structural", passed=False),
        fast_test_runner=lambda _d: (True, None),
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
    )
    assert outcome.verdict is PolicyVerdict.FAIL
