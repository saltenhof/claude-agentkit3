"""Integration test: VerifySystem QA-subflow with the wired LLM Layer-2 runner.

AG3-043 §2.1.9 / §2.1.7: a full ``run_qa_subflow`` with a real
``ParallelEvalRunner`` (three roles) backed by a scripted LLM (the only
external grenze) and a stub prompt materializer. Asserts:
  - the three role LayerResults aggregate into ``decision.layer_results``,
  - the LLM verdict drives the overall PASS/FAIL,
  - a FAIL from any role fails the subflow fail-closed.

No core logic (runner / evaluator / policy engine / VerifySystem) is stubbed.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import ArtifactEnvelope, ArtifactManager, ArtifactReference
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system import VerifyContextBundle, VerifySystem
from agentkit.verify_system.contract import PhaseEnvelopeView
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    ReviewerRole,
    StructuredEvaluator,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import Finding, Severity, TrustClass
from agentkit.verify_system.stage_registry import StageRegistry
from integration.implementation_evidence_support import (
    bind_implementation_qa_preconditions,
)

if TYPE_CHECKING:
    from pathlib import Path

_QA_PASS = [
    {"check_id": cid, "status": "PASS"}
    for cid in (
        "ac_fulfilled", "impl_fidelity", "scope_compliance", "impact_violation",
        "arch_conformity", "proportionality", "error_handling", "authz_logic",
        "silent_data_loss", "backward_compat", "observability", "doc_impact",
    )
]
_STRUCTURAL_STAGE_METADATA = {
    "stage_ids": tuple(
        stage.stage_id
        for stage in StageRegistry().layer1_stages_for(
            StoryType.IMPLEMENTATION, are_enabled=False
        )
    )
    + ("sonarqube_gate",)
}


class _RecordingArtifactManager(ArtifactManager):
    def __init__(self) -> None:
        self.written_envelopes: list[ArtifactEnvelope] = []

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        self.written_envelopes.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"recording/{envelope.stage}/{envelope.attempt}",
        )


class _StubMaterializer:
    def context_for(self, bundle: object) -> tuple[object, str]:
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.types import StoryMode, StoryType

        story_id = getattr(bundle, "story_id", "TEST-001")
        ctx = StoryContext(
            project_key="test-project",
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        return ctx, story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: object,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        del ctx, story_id, template_override
        return f"PROMPT:{role.value}", "a" * 64


class _RoleScriptedClient:
    def __init__(self, by_role: dict[str, list[dict[str, str]]]) -> None:
        self.by_role = by_role
        self.roles_called: list[str] = []

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        self.roles_called.append(role)
        return json.dumps(self.by_role[role])


@pytest.fixture
def _git_worktree(tmp_path: Path) -> Path:
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
    _write_manifest_index(tmp_path)
    return tmp_path


def _write_manifest_index(project_root: Path) -> None:
    reference_path = project_root / "concepts" / "architecture.md"
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_text("# Architecture\n\nImplementation guardrail.\n", encoding="utf-8")
    manifest_path = project_root / "_guardrails" / "manifest-index.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({
            "documents": [
                {
                    "path": "concepts/architecture.md",
                    "scope": "architecture",
                    "modules": ["*"],
                    "story_types": ["implementation"],
                    "tags": ["*"],
                }
            ],
        }),
        encoding="utf-8",
    )


def _make_system(
    client: _RoleScriptedClient, manager: _RecordingArtifactManager
) -> VerifySystem:
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    runner = ParallelEvalRunner(evaluator)
    return VerifySystem(
        layer_1=_PassingLayer("structural"),
        layer_2a=_UnusedLayer("qa_review"),
        layer_2b=_UnusedLayer("semantic_review"),
        layer_2c=_UnusedLayer("doc_fidelity"),
        layer_3=_PassingLayer("adversarial"),
        policy_engine=PolicyEngine(max_major_findings=0),
        artifact_manager=manager,
        layer2_runner=runner,
    )


class _UnusedLayer:
    """A Layer-2 reviewer double that must NOT be called when the runner is wired."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, ctx: object, story_dir: object, *, review_input: object = None) -> object:
        self.calls += 1
        raise AssertionError("Layer-2 reviewer must not run when layer2_runner is wired")


class _PassingLayer:
    """A benign passing QALayer double (used for layer_1 / layer_3)."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, ctx: object, story_dir: object, *, review_input: object = None) -> object:
        from agentkit.verify_system.protocols import LayerResult

        del ctx, story_dir, review_input
        return LayerResult(
            layer=self._name,
            passed=True,
            findings=(),
            metadata=(
                _STRUCTURAL_STAGE_METADATA if self._name == "structural" else {}
            ),
        )


def _bundle(tmp_path: Path) -> VerifyContextBundle:
    return VerifyContextBundle(
        run_id="run-001", story_dir=tmp_path, phase_envelope=None, attempt=1
    )


def _target() -> ArtifactReference:
    return ArtifactReference(
        artifact_class=ArtifactClass.WORKER,
        story_id="TEST-001",
        run_id="run-001",
        record_key="envelopes/worker/TEST-001/1",
    )


def _review_input() -> Layer2ReviewInput:
    return Layer2ReviewInput(
        story_spec="brief",
        diff_summary="tests/test_x.py changed; test_a test_b test_c",
        concept_excerpt="FK-27",
        handover="coverage: 90%; test_a test_b test_c",
    )


def test_all_three_roles_pass_yields_pass(_git_worktree: Path) -> None:
    tmp_path = _git_worktree
    client = _RoleScriptedClient({
        "qa_review": _QA_PASS,
        "semantic_review": [{"check_id": "systemic_adequacy", "status": "PASS"}],
        "doc_fidelity": [{"check_id": "impl_fidelity", "status": "PASS"}],
    })
    manager = _RecordingArtifactManager()
    vs = _make_system(client, manager)
    vs = bind_implementation_qa_preconditions(
        vs, tmp_path, story_id="TEST-001", run_id="run-001"
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
        review_input=_review_input(),
    )
    assert outcome.verdict is PolicyVerdict.PASS
    layer_names = [lr.layer for lr in outcome.decision.layer_results]
    assert "qa_review" in layer_names
    assert "semantic_review" in layer_names
    assert "doc_fidelity" in layer_names
    assert set(client.roles_called) == {"qa_review", "semantic_review", "doc_fidelity"}


def test_one_role_fail_fails_subflow(_git_worktree: Path) -> None:
    tmp_path = _git_worktree
    qa_fail = [dict(c) for c in _QA_PASS]
    qa_fail[0]["status"] = "FAIL"
    qa_fail[0]["reason"] = "AC not met"
    client = _RoleScriptedClient({
        "qa_review": qa_fail,
        "semantic_review": [{"check_id": "systemic_adequacy", "status": "PASS"}],
        "doc_fidelity": [{"check_id": "impl_fidelity", "status": "PASS"}],
    })
    manager = _RecordingArtifactManager()
    vs = _make_system(client, manager)
    vs = bind_implementation_qa_preconditions(
        vs, tmp_path, story_id="TEST-001", run_id="run-001"
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
        review_input=_review_input(),
    )
    assert outcome.verdict is PolicyVerdict.FAIL
    qa_result = next(
        lr for lr in outcome.decision.layer_results if lr.layer == "qa_review"
    )
    assert qa_result.passed is False


def test_llm_transport_failure_is_failclosed_blocking(_git_worktree: Path) -> None:
    tmp_path = _git_worktree

    class _Boom:
        def complete(self, *, role: str, prompt: str) -> str:
            del role, prompt
            return "not json at all"

    evaluator = StructuredEvaluator(_Boom(), _StubMaterializer())
    runner = ParallelEvalRunner(evaluator)
    manager = _RecordingArtifactManager()
    vs = VerifySystem(
        layer_1=_PassingLayer("structural"),
        layer_2a=_UnusedLayer("qa_review"),
        layer_2b=_UnusedLayer("semantic_review"),
        layer_2c=_UnusedLayer("doc_fidelity"),
        layer_3=_PassingLayer("adversarial"),
        policy_engine=PolicyEngine(max_major_findings=0),
        artifact_manager=manager,
        layer2_runner=runner,
    )
    vs = bind_implementation_qa_preconditions(
        vs, tmp_path, story_id="TEST-001", run_id="run-001"
    )
    outcome = vs.run_qa_subflow(
        ctx=_bundle(tmp_path),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=_target(),
        review_input=_review_input(),
    )
    assert outcome.verdict is PolicyVerdict.FAIL
    # All three Layer-2 roles must be BLOCKING (no silent skip).
    l2 = [lr for lr in outcome.decision.layer_results if lr.layer in {
        "qa_review", "semantic_review", "doc_fidelity"
    }]
    assert len(l2) == 3  # noqa: PLR2004
    assert all(not lr.passed for lr in l2)


def test_llm_partially_resolved_blocks_closure_via_ssot(_git_worktree: Path) -> None:
    """E5: an LLM ``partially_resolved`` verdict reaches the ONE closure SSOT.

    In round 2 the LLM reports the round-1 finding (``qa_review:ac_fulfilled``)
    as ``partially_resolved`` while the 12 regular checks all PASS. The
    deterministic assessor alone would see the finding GONE from the current
    round (PASS checks emit no finding) and classify it FULLY_RESOLVED -> no
    block. Only because the LLM resolution verdict is merged into the canonical
    finding-resolution map (E5) does ``closure_blocked`` become True. This is
    the precise regression for "LLM resolution lived only in metadata".
    """
    tmp_path = _git_worktree
    prev_finding = Finding(
        layer="qa_review",
        check="ac_fulfilled",
        severity=Severity.BLOCKING,
        message="round-1 AC gap",
        trust_class=TrustClass.VERIFIED_LLM,
    )
    qa_round2 = [dict(c) for c in _QA_PASS]
    qa_round2.append({
        "check_id": "finding_resolution_qa_review:ac_fulfilled",
        "status": "PASS_WITH_CONCERNS",
        "resolution": "partially_resolved",
        "reason": "edge case still open",
    })
    client = _RoleScriptedClient({
        "qa_review": qa_round2,
        "semantic_review": [{"check_id": "systemic_adequacy", "status": "PASS"}],
        "doc_fidelity": [{"check_id": "impl_fidelity", "status": "PASS"}],
    })
    manager = _RecordingArtifactManager()
    vs = _make_system(client, manager)
    vs = bind_implementation_qa_preconditions(
        vs, tmp_path, story_id="TEST-001", run_id="run-001"
    )
    # Active cycle so the remediation context advances to round 2.
    from datetime import UTC, datetime

    view = PhaseEnvelopeView(
        qa_cycle_id="a1b2c3d4e5f6",
        qa_cycle_round=1,
        evidence_epoch=datetime(2026, 5, 19, tzinfo=UTC),
        evidence_fingerprint="f" * 64,
    )
    bundle = VerifyContextBundle(
        run_id="run-001", story_dir=tmp_path, phase_envelope=view, attempt=2,
        project_root=tmp_path,
    )
    outcome = vs.run_qa_subflow(
        ctx=bundle,
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
        target=_target(),
        review_input=_review_input(),
        previous_findings=(prev_finding,),
    )
    assert outcome.closure_blocked is True


def test_build_verify_system_wires_layer2_runner_productively(tmp_path: Path) -> None:
    """E6: the composition root wires Layer 2 to RUN in the default path.

    ``build_verify_system`` (no explicit client) must NOT leave
    ``layer2_llm_client`` None / fall back to the deterministic stub reviewers.
    It wires the fail-closed ``FailClosedLlmClient`` so Layer 2 actually runs
    and FAILS CLOSED (FK-27 §27.5 "Reviews finden IMMER statt"; FK-34 §34.5.1).
    Verified at the REAL productive entry point, not just a test double.
    """
    from agentkit.bootstrap.composition_root import build_verify_system
    from agentkit.verify_system.llm_evaluator.llm_client import FailClosedLlmClient

    vs = build_verify_system(tmp_path)
    assert isinstance(vs.layer2_llm_client, FailClosedLlmClient)
    assert vs.layer2_runner is None  # built per-run, not at composition
