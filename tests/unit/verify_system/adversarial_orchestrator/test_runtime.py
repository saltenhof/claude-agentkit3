"""Unit tests for the deterministic Layer-3 adversarial runtime (FK-48 §48.1, AG3-079).

Covers the promotion/quarantine paths (AC4), the mandatory sparring + telemetry
proof (AC3/AC6), the adversarial.json materialisation (AC5), the Layer3->Layer2
feedback (AC8) and the end-to-end runtime (AC1/AC2). The LLM/sub-agent boundary
is the ONLY mock: a fake :class:`LlmClient` (the AG3-065 transport surface) and a
fake resolver. Everything else (promotion/quarantine/artifact/telemetry/feedback)
is exercised with real files / a real ArtifactManager.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
)
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.verify_system.adversarial_orchestrator.runtime import runner as _runner
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.artifact import (
    AdversarialResultReadError,
    build_result_artifact,
    read_sandbox_result,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.feedback import (
    mandatory_target_resolution_feedback,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
    AdversarialTelemetryCounts,
    PromotionSummary,
    SandboxResult,
    SandboxTest,
    SparringProof,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.promotion import (
    QUARANTINE_DIRNAME,
    PromotionPath,
    promote_sandbox_tests,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.runner import (
    run_adversarial_runtime,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.sparring import (
    ADVERSARIAL_SPARRING_ROLE,
    AdversarialSparringError,
    run_mandatory_sparring,
)
from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.backend.verify_system.remediation.finding_resolution import (
    FindingResolutionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# --- LLM/transport boundary doubles (the only allowed mock boundary) ---------


class _FakeSparringClient:
    """A fake AG3-065 transport (LlmClient) returning a fixed sparring reply."""

    def __init__(self, reply: str = "case a\ncase b\ncase c") -> None:
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, role: str, prompt: str) -> str:
        self.calls.append((role, prompt))
        return self._reply


class _FailingSparringClient:
    """A fake transport that fails closed (pool unreachable)."""

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        raise LlmClientError(f"pool unreachable for role={role!r}")


class _FixedResolver:
    """Resolves the sparring role to a fixed pool name (records the pool label)."""

    def resolve(self, role: str) -> str:
        assert role == ADVERSARIAL_SPARRING_ROLE
        return "grok"


def _telemetry(
    *,
    start: int = 1,
    end: int = 1,
    sparring: int = 1,
    created: int = 0,
    executed: int = 1,
) -> AdversarialTelemetryCounts:
    """Build a conformant §48.1.8 telemetry-count block (FK-48 §48.1.8)."""
    return AdversarialTelemetryCounts(
        adversarial_start=start,
        adversarial_end=end,
        adversarial_sparring=sparring,
        adversarial_test_created=created,
        adversarial_test_executed=executed,
    )


# --- Promotion / quarantine (AC4) -------------------------------------------


def _write_sandbox_test(sandbox: Path, name: str, *, body: str) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / name).write_text(body, encoding="utf-8")


def test_promotion_pass_goes_to_suite(tmp_path: Path) -> None:
    """AC4 path 1: schema-valid + executable + non-duplicate + PASS -> tests/."""
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    _write_sandbox_test(
        sandbox, "test_edge_pass.py", body="def test_edge_pass():\n    assert True\n"
    )
    test = SandboxTest(
        sandbox_relpath="test_edge_pass.py",
        qualified_name="test_edge_pass::test_edge_pass",
        outcome="PASS",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    assert decisions[0].path is PromotionPath.SUITE
    assert summary.promoted_to_suite == 1
    assert (tests_root / "test_edge_pass.py").is_file()
    assert not (tests_root / QUARANTINE_DIRNAME).exists()


def test_promotion_fail_goes_to_quarantine(tmp_path: Path) -> None:
    """AC4 path 2: schema-valid + executable + non-duplicate + FAIL -> quarantine."""
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    _write_sandbox_test(
        sandbox, "test_edge_fail.py", body="def test_edge_fail():\n    assert False\n"
    )
    test = SandboxTest(
        sandbox_relpath="test_edge_fail.py",
        qualified_name="test_edge_fail::test_edge_fail",
        outcome="FAIL",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    assert decisions[0].path is PromotionPath.QUARANTINE
    assert summary.promoted_to_quarantine == 1
    # The failing test lands in quarantine, NOT in the green suite.
    assert (tests_root / QUARANTINE_DIRNAME / "test_edge_fail.py").is_file()
    assert not (tests_root / "test_edge_fail.py").exists()


def test_promotion_syntax_error_stays_ephemeral(tmp_path: Path) -> None:
    """AC4 path 3a: a dry-run (syntax) error -> stays ephemeral in the sandbox."""
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    _write_sandbox_test(
        sandbox, "test_broken.py", body="def test_broken(:\n    assert True\n"
    )
    test = SandboxTest(
        sandbox_relpath="test_broken.py",
        qualified_name="test_broken::test_broken",
        outcome="PASS",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    assert decisions[0].path is PromotionPath.EPHEMERAL
    assert "dry-run-error" in decisions[0].reason
    assert summary.not_promoted == 1
    assert not (tests_root / "test_broken.py").exists()


def test_promotion_duplicate_stays_ephemeral(tmp_path: Path) -> None:
    """AC4 path 3b: a module-qualified-name duplicate -> stays ephemeral."""
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    # An existing test under tests/ with the SAME module-qualified name.
    (tests_root / "test_dup.py").write_text(
        "def test_dup():\n    assert True\n", encoding="utf-8"
    )
    _write_sandbox_test(
        sandbox, "test_dup.py", body="def test_dup():\n    assert True\n"
    )
    test = SandboxTest(
        sandbox_relpath="test_dup.py",
        qualified_name="test_dup::test_dup",
        outcome="PASS",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    assert decisions[0].path is PromotionPath.EPHEMERAL
    assert "duplicate" in decisions[0].reason
    assert summary.not_promoted == 1


def test_promotion_dedup_is_module_qualified_same_stem_different_module(
    tmp_path: Path,
) -> None:
    """AC4: same stem + same function in a DIFFERENT module is NOT a duplicate.

    The dedup identity is the MODULE-QUALIFIED test name (rooted dotted module
    path + function), not the bare file stem. An existing
    ``unit/foo/test_x.py::test_a`` must NOT collapse a sandbox test whose
    module-qualified name is ``integration.foo.test_x::test_a``.
    """
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    existing = tests_root / "unit" / "foo"
    existing.mkdir(parents=True)
    (existing / "test_x.py").write_text(
        "def test_a():\n    assert True\n", encoding="utf-8"
    )
    _write_sandbox_test(
        sandbox, "test_x.py", body="def test_a():\n    assert True\n"
    )
    # Same stem (test_x) + same function (test_a) but a DIFFERENT module path.
    test = SandboxTest(
        sandbox_relpath="test_x.py",
        qualified_name="integration.foo.test_x::test_a",
        outcome="PASS",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    # NOT collapsed -> promoted into the suite.
    assert decisions[0].path is PromotionPath.SUITE
    assert summary.promoted_to_suite == 1


def test_promotion_dedup_detects_module_qualified_duplicate(tmp_path: Path) -> None:
    """AC4: an identical MODULE-QUALIFIED name IS a duplicate -> stays ephemeral."""
    sandbox = tmp_path / "sandbox"
    tests_root = tmp_path / "tests"
    pkg = tests_root / "unit" / "foo"
    pkg.mkdir(parents=True)
    (pkg / "test_x.py").write_text(
        "def test_a():\n    assert True\n", encoding="utf-8"
    )
    _write_sandbox_test(
        sandbox, "test_x.py", body="def test_a():\n    assert True\n"
    )
    # Identical module-qualified name as the existing unit/foo/test_x.py::test_a.
    test = SandboxTest(
        sandbox_relpath="test_x.py",
        qualified_name="unit.foo.test_x::test_a",
        outcome="PASS",
    )
    decisions, summary = promote_sandbox_tests(
        tests=[test], sandbox_dir=sandbox, tests_root=tests_root
    )
    assert decisions[0].path is PromotionPath.EPHEMERAL
    assert "duplicate" in decisions[0].reason
    assert summary.not_promoted == 1


# --- Mandatory sparring + telemetry (AC3/AC6) -------------------------------


def test_sparring_emits_both_telemetry_facts() -> None:
    """AC3: a sparring call emits llm_call(role=adversarial_sparring) + adversarial_sparring."""
    emitter = MemoryEmitter()
    client = _FakeSparringClient()
    proof = run_mandatory_sparring(
        sparring_client=client,
        emitter=emitter,
        story_id="AG3-079",
        run_id="run-1",
        prompt="what did I miss?",
        resolver=_FixedResolver(),
    )
    assert proof.pool == "grok"
    assert proof.adversarial_sparring_events == 1
    assert proof.llm_call_sparring_events == 1
    assert client.calls == [(ADVERSARIAL_SPARRING_ROLE, "what did I miss?")]

    llm_calls = emitter.query("AG3-079", EventType.LLM_CALL)
    assert len(llm_calls) == 1
    assert llm_calls[0].payload["role"] == ADVERSARIAL_SPARRING_ROLE
    sparring_events = emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING)
    assert len(sparring_events) == 1
    assert sparring_events[0].payload["pool"] == "grok"


def test_sparring_fails_closed_on_transport_error() -> None:
    """AC3: a failed transport call raises AdversarialSparringError (no telemetry)."""
    emitter = MemoryEmitter()
    with pytest.raises(AdversarialSparringError, match="FAIL-CLOSED"):
        run_mandatory_sparring(
            sparring_client=_FailingSparringClient(),
            emitter=emitter,
            story_id="AG3-079",
            run_id="run-1",
            prompt="x",
        )
    # No telemetry emitted on a failed sparring call.
    assert emitter.query("AG3-079", EventType.LLM_CALL) == []
    assert emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING) == []


# --- Feedback Layer 3 -> Layer 2 (AC8) --------------------------------------


def test_feedback_unmet_target_partially_resolves_finding() -> None:
    """AC8: an unfulfilled mandatory target -> finding >= partially_resolved."""
    sandbox_result = SandboxResult(
        story_id="AG3-079",
        tests_executed=1,
        mandatory_target_results=(
            {"target_id": "qa_review.neg_case", "status": "MISSING"},  # not addressed
        ),
    )
    artifact = build_result_artifact(
        sandbox_result=sandbox_result,
        run_id="run-1",
        sparring=SparringProof(
            pool="grok", adversarial_sparring_events=1, llm_call_sparring_events=1
        ),
        promotion=PromotionSummary(),
        telemetry=_telemetry(),
    )
    feedback = mandatory_target_resolution_feedback(artifact)
    assert feedback == {
        ("qa_review", "neg_case"): FindingResolutionStatus.PARTIALLY_RESOLVED
    }


def test_feedback_fulfilled_target_does_not_reopen_finding() -> None:
    """AC8: TESTED+PASS or justified UNRESOLVABLE -> no re-open."""
    sandbox_result = SandboxResult(
        story_id="AG3-079",
        tests_executed=2,
        tests=(
            SandboxTest(
                sandbox_relpath="test_a.py",
                qualified_name="test_a::test_a",
                outcome="PASS",
                target_id="qa_review.neg_a",
            ),
        ),
        mandatory_target_results=(
            {"target_id": "qa_review.neg_a", "status": "TESTED", "test_file": "test_a.py"},
            {
                "target_id": "qa_review.neg_b",
                "status": "UNRESOLVABLE",
                "reason": "external service state not reproducible",
            },
        ),
    )
    artifact = build_result_artifact(
        sandbox_result=sandbox_result,
        run_id="run-1",
        sparring=SparringProof(
            pool="grok", adversarial_sparring_events=1, llm_call_sparring_events=1
        ),
        promotion=PromotionSummary(),
        telemetry=_telemetry(),
    )
    assert mandatory_target_resolution_feedback(artifact) == {}


def test_feedback_tested_but_failing_reopens_finding() -> None:
    """AC8: TESTED + test FAIL -> finding >= partially_resolved (proven defect)."""
    sandbox_result = SandboxResult(
        story_id="AG3-079",
        tests_executed=1,
        tests=(
            SandboxTest(
                sandbox_relpath="test_a.py",
                qualified_name="test_a::test_a",
                outcome="FAIL",
                target_id="qa_review.neg_a",
            ),
        ),
        mandatory_target_results=(
            {"target_id": "qa_review.neg_a", "status": "TESTED", "test_file": "test_a.py"},
        ),
    )
    artifact = build_result_artifact(
        sandbox_result=sandbox_result,
        run_id="run-1",
        sparring=SparringProof(
            pool="grok", adversarial_sparring_events=1, llm_call_sparring_events=1
        ),
        promotion=PromotionSummary(),
        telemetry=_telemetry(),
    )
    assert mandatory_target_resolution_feedback(artifact) == {
        ("qa_review", "neg_a"): FindingResolutionStatus.PARTIALLY_RESOLVED
    }


# --- Artifact read fail-closed ----------------------------------------------


def test_read_sandbox_result_fails_closed_when_absent(tmp_path: Path) -> None:
    """AC5: a missing sandbox result.json fails closed (no PASS without evidence)."""
    with pytest.raises(AdversarialResultReadError, match="absent"):
        read_sandbox_result(tmp_path / "missing")


# --- End-to-end runtime (AC1/AC2/AC5/AC6) -----------------------------------


def _write_sandbox_result(sandbox: Path, result: dict[str, object]) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "result.json").write_text(json.dumps(result), encoding="utf-8")


def test_runtime_end_to_end_emits_five_events_and_materializes_artifact(
    tmp_path: Path,
) -> None:
    """AC1/2/5/6: full runtime emits the five events + materialises adversarial.json."""
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    tests_root = tmp_path / "tests"
    _write_sandbox_test(
        sandbox, "test_edge.py", body="def test_edge():\n    assert True\n"
    )
    _write_sandbox_result(
        sandbox,
        {
            "story_id": "AG3-079",
            "status": "PASS",
            "tests_executed": 1,
            "tests": [
                {
                    "sandbox_relpath": "test_edge.py",
                    "qualified_name": "test_edge::test_edge",
                    "outcome": "PASS",
                }
            ],
        },
    )
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tests_root,
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
        resolver=_FixedResolver(),
    )
    # AC1: real verdict (PASS with evidence), not a passthrough.
    assert result.layer_result.passed is True
    # AC6: the five telemetry events with the FK-48 §48.1.8 counts.
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_START)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_END)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_TEST_CREATED)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_TEST_EXECUTED)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING)) == 1
    assert len(emitter.query("AG3-079", EventType.LLM_CALL)) == 1
    # AC2: the PASS test was promoted into the suite; production code untouched.
    assert (tests_root / "test_edge.py").is_file()
    # AC5: adversarial.json materialised under the canonical producer/stage.
    envelope = manager.read_latest(
        story_id="AG3-079",
        run_id="run-1",
        artifact_class=ArtifactClass.QA,
        stage=ADVERSARIAL_STAGE,
    )
    assert envelope.producer.name == ADVERSARIAL_PRODUCER
    assert envelope.stage == ADVERSARIAL_STAGE
    assert envelope.payload["schema_version"] == "3.1"
    assert "mandatory_target_results" in envelope.payload
    assert envelope.payload["sparring"]["adversarial_sparring_events"] == 1
    # AC7 (FK-48 §48.1.8): the materialised payload carries the exact emitted
    # lifecycle counts the integrity gate verifies (exactly-1 start/end).
    telemetry = envelope.payload["telemetry"]
    assert telemetry["adversarial_start"] == 1
    assert telemetry["adversarial_end"] == 1
    assert telemetry["adversarial_sparring"] == 1
    assert telemetry["adversarial_test_created"] == 1
    assert telemetry["adversarial_test_executed"] == 1


def test_runtime_fails_when_sparring_call_fails(tmp_path: Path) -> None:
    """AC1/AC3: a failed sparring call -> Layer-3 FAIL (no PASS without sparring)."""
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    tests_root = tmp_path / "tests"
    _write_sandbox_result(
        sandbox,
        {"story_id": "AG3-079", "status": "PASS", "tests_executed": 1, "tests": []},
    )
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FailingSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tests_root,
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
    )
    assert result.layer_result.passed is False
    assert any(f.check == "sparring_missing" for f in result.layer_result.findings)
    # No sparring telemetry was emitted; the artifact still records zero counts.
    assert result.artifact.sparring.adversarial_sparring_events == 0
    assert emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING) == []


def test_sparring_fails_closed_when_pool_resolution_fails() -> None:
    """AC3 NO FALLBACK: an unresolvable pool label fails closed (no default-pool fallback).

    Story §2.2 hard-requires NO fallback for the AG3-065 sparring transport: a
    resolver/transport failure must FAIL the sparring step (Layer-3 FAIL), never
    substitute the role wire-string as a default pool label. No telemetry is
    emitted because the call never happens.
    """
    emitter = MemoryEmitter()

    class _FailingResolver:
        def resolve(self, role: str) -> str:
            raise LlmClientError(f"no pool for role={role!r}")

    with pytest.raises(AdversarialSparringError, match="NO FALLBACK"):
        run_mandatory_sparring(
            sparring_client=_FakeSparringClient(),
            emitter=emitter,
            story_id="AG3-079",
            run_id="run-1",
            prompt="x",
            resolver=_FailingResolver(),
        )
    # NO FALLBACK -> the sparring call never happened -> no telemetry.
    assert emitter.query("AG3-079", EventType.LLM_CALL) == []
    assert emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING) == []


def test_runtime_fails_on_unfulfilled_mandatory_target(tmp_path: Path) -> None:
    """AC1/AC8: an unfulfilled mandatory target -> Layer-3 FAIL + feedback."""
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    tests_root = tmp_path / "tests"
    _write_sandbox_result(
        sandbox,
        {
            "story_id": "AG3-079",
            "status": "PASS",
            "tests_executed": 1,
            "tests": [],
            "mandatory_target_results": [
                {"target_id": "qa_review.neg_case", "status": "MISSING"}
            ],
        },
    )
    manager = build_artifact_manager(tmp_path)
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=MemoryEmitter(),
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tests_root,
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
    )
    assert result.layer_result.passed is False
    assert any(f.check == "qa_review.neg_case" for f in result.layer_result.findings)
    assert result.resolution_feedback == {
        ("qa_review", "neg_case"): FindingResolutionStatus.PARTIALLY_RESOLVED
    }


def test_runtime_fails_when_no_test_executed(tmp_path: Path) -> None:
    """AC1: a run with zero executed tests -> Layer-3 FAIL (no silent PASS)."""
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    tests_root = tmp_path / "tests"
    _write_sandbox_result(
        sandbox,
        {"story_id": "AG3-079", "status": "PASS", "tests_executed": 0, "tests": []},
    )
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tests_root,
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
    )
    assert result.layer_result.passed is False
    assert any(
        f.check == "no_test_executed" for f in result.layer_result.findings
    )
    # The five lifecycle events still bracket the run (start/end exactly once).
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_START)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_END)) == 1


# --- AC7: telemetry counts reflect REAL emission, never a predicted +1 -------


def _passing_sandbox(sandbox: Path, *, tests_executed: int = 1) -> None:
    """Write a conformant sandbox result with one PASS edge-case test."""
    _write_sandbox_test(
        sandbox, "test_edge.py", body="def test_edge():\n    assert True\n"
    )
    _write_sandbox_result(
        sandbox,
        {
            "story_id": "AG3-079",
            "status": "PASS",
            "tests_executed": tests_executed,
            "tests": [
                {
                    "sandbox_relpath": "test_edge.py",
                    "qualified_name": "test_edge::test_edge",
                    "outcome": "PASS",
                }
            ],
        },
    )


def test_runtime_telemetry_counts_equal_really_emitted_events(tmp_path: Path) -> None:
    """AC7: the persisted telemetry counts EQUAL the events the emitter actually holds.

    Proves the counts are read from real emission (the ``_LifecycleEmitter``
    tally), not predicted: every count in ``adversarial.json`` matches the number
    of events the (independent) ``MemoryEmitter`` recorded — in particular
    ``adversarial_end`` is 1 because the end event was REALLY emitted, not +1'd.
    """
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    _passing_sandbox(sandbox)
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tmp_path / "tests",
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
        resolver=_FixedResolver(),
    )
    telemetry = result.artifact.telemetry
    # The recorded counts EQUAL what the emitter genuinely observed (no +1).
    assert telemetry.adversarial_start == len(
        emitter.query("AG3-079", EventType.ADVERSARIAL_START)
    )
    assert telemetry.adversarial_end == len(
        emitter.query("AG3-079", EventType.ADVERSARIAL_END)
    )
    assert telemetry.adversarial_sparring == len(
        emitter.query("AG3-079", EventType.ADVERSARIAL_SPARRING)
    )
    assert telemetry.adversarial_test_created == len(
        emitter.query("AG3-079", EventType.ADVERSARIAL_TEST_CREATED)
    )
    assert telemetry.adversarial_test_executed == len(
        emitter.query("AG3-079", EventType.ADVERSARIAL_TEST_EXECUTED)
    )
    # Exactly-1 end on the happy path (emitted before capture, finally is no-op).
    assert telemetry.adversarial_end == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_END)) == 1


def test_runtime_records_zero_end_when_end_emission_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: a run whose end event is NOT really emitted records ``adversarial_end != 1``.

    The whole point of AC7: the gate must verify REAL emission. We suppress the
    ``adversarial_end`` emission (simulating an emitter that never lands the end
    event). The persisted artifact must then truthfully record
    ``adversarial_end == 0`` (NOT a self-attested 1) so Dim 6 fails closed — no
    silent +1 prediction papers over the missing event.
    """

    def _suppressed_end(
        emitter: object, story_id: str, run_id: str, phase: object
    ) -> None:
        # The end event is never forwarded to the wrapped emitter -> never counted.
        del emitter, story_id, run_id, phase

    monkeypatch.setattr(_runner, "_emit_end_once", _suppressed_end)

    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    _passing_sandbox(sandbox)
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    result = run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tmp_path / "tests",
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
        resolver=_FixedResolver(),
    )
    # No end event was really emitted -> the artifact records the REAL count: 0.
    assert result.artifact.telemetry.adversarial_end == 0
    assert emitter.query("AG3-079", EventType.ADVERSARIAL_END) == []
    # The persisted payload carries adversarial_end=0 -> Dim 6 verifies a real,
    # missing end event (see test_dimensions::test_dim6_fails_when_zero_*).
    envelope = manager.read_latest(
        story_id="AG3-079",
        run_id="run-1",
        artifact_class=ArtifactClass.QA,
        stage=ADVERSARIAL_STAGE,
    )
    assert envelope.payload["telemetry"]["adversarial_end"] == 0


def test_runtime_emits_end_exactly_once_on_error_path(tmp_path: Path) -> None:
    """AC7: an error before the happy-path end still emits ``adversarial_end`` exactly once.

    The sandbox result is absent (``read_sandbox_result`` fails closed BEFORE the
    happy-path end emission). The ``finally`` is then the SOLE end emitter — and
    it fires exactly once (never 0, never 2). The start event was already emitted.
    """
    sandbox = tmp_path / "missing"  # no result.json -> read fails closed
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    with pytest.raises(AdversarialResultReadError):
        run_adversarial_runtime(
            artifact_manager=manager,
            emitter=emitter,
            sparring_client=_FakeSparringClient(),
            sandbox_dir=sandbox,
            tests_root=tmp_path / "tests",
            story_id="AG3-079",
            run_id="run-1",
            attempt=1,
            resolver=_FixedResolver(),
        )
    # Exactly-1 start AND exactly-1 end even though the body aborted early.
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_START)) == 1
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_END)) == 1


def test_runtime_emits_end_exactly_once_on_happy_path(tmp_path: Path) -> None:
    """AC7: the happy path emits ``adversarial_end`` exactly once (no finally double-emit)."""
    sandbox = tmp_path / "_temp" / "adversarial" / "AG3-079" / "1"
    _passing_sandbox(sandbox)
    manager = build_artifact_manager(tmp_path)
    emitter = MemoryEmitter()
    run_adversarial_runtime(
        artifact_manager=manager,
        emitter=emitter,
        sparring_client=_FakeSparringClient(),
        sandbox_dir=sandbox,
        tests_root=tmp_path / "tests",
        story_id="AG3-079",
        run_id="run-1",
        attempt=1,
        resolver=_FixedResolver(),
    )
    # The happy-path emission + the finally re-call together yield EXACTLY one end.
    assert len(emitter.query("AG3-079", EventType.ADVERSARIAL_END)) == 1


def test_lifecycle_emitter_does_not_count_failed_forward() -> None:
    """AC7: the tally increments ONLY after a successful forward (no inflated count).

    A forwarding failure must not inflate the recorded count — otherwise a
    suppressed/failing ``adversarial_end`` would still self-attest 1. The tally
    counts real, landed emissions only.
    """

    class _RaisingOnEndEmitter:
        """A test double that fails to land ADVERSARIAL_END (worst-case emitter)."""

        def __init__(self) -> None:
            self.landed: list[EventType] = []

        def emit(self, event: object) -> None:
            evt_type = event.event_type  # type: ignore[attr-defined]
            if evt_type is EventType.ADVERSARIAL_END:
                raise RuntimeError("end event did not land")
            self.landed.append(evt_type)

        def query(
            self, _story_id: str, _event_type: EventType | None = None
        ) -> list[object]:
            return []

    inner = _RaisingOnEndEmitter()
    lifecycle = _runner._LifecycleEmitter(inner)
    _runner._emit(lifecycle, EventType.ADVERSARIAL_START, "AG3-079", "run-1", None)
    assert lifecycle.count(EventType.ADVERSARIAL_START) == 1
    # The end forward raises -> the count must NOT be incremented to a fake 1.
    with pytest.raises(RuntimeError, match="did not land"):
        _runner._emit_end_once(lifecycle, "AG3-079", "run-1", None)
    assert lifecycle.count(EventType.ADVERSARIAL_END) == 0
