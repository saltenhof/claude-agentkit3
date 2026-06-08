"""Integration: SonarQube-Green-Gate stage end-to-end in the QA-subflow.

AG3-052 §2.1.7 / AC4 / AC6. Builds a full ``VerifySystem`` with a
recording ArtifactManager and a ``SonarGateInputPort`` whose inputs are
derived from a STUBBED Sonar HTTP client (only the external HTTP boundary
is faked, MOCKS-Ausnahme). The capability + reconciler + applicability
logic runs for real, driven through ``run_qa_subflow``.

Proves:
* APPLICABLE green  -> verdict PASS, gate envelope status PASS;
* APPLICABLE red    -> verdict FAIL (BLOCKING from the gate);
* APPLICABLE 0/>1 ledger match -> verdict FAIL VOR der Policy (the gate
  fail-closes before policy aggregation can emit PASS) -- AC4 wiring;
* E4 (rot->grün through the accept via the POST-apply RE-READ): with 1 open
  issue + ERROR gate, a single-match ledger accept transitions the issue in
  Sonar; the gate RE-READS the recomputed gate (now OK + 0 open) and flips
  green. NO AK subtraction — the stub re-read reflects the real Sonar state;
* an open issue WITHOUT a ledger match stays red (the re-read still shows
  ERROR + 1 open);
* available:false   -> stage SKIP, policy still runs -> PASS;
* mode fast         -> the ``sonarqube_gate`` stage DROPS entirely (AG3-052
  contract, AC6). The full fast-mode QA-subflow terminal (Policy-Engine skip
  via the tests-green floor) is FK-24 §24.3.4 / FK-27 §27.6a, NOT this story;
  the test below pins only the Sonar-stage drop, not a fast Policy verdict.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import ArtifactEnvelope, ArtifactManager, ArtifactReference
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system import VerifyContextBundle, VerifySystem
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import LayerResult
from agentkit.verify_system.sonarqube_gate import (
    AcceptedExceptionLedgerEntry,
    SonarApplicability,
    SonarAttestation,
    SonarIssue,
)
from agentkit.verify_system.sonarqube_gate.port import PostApplyGateState, SonarGateInputs
from agentkit.verify_system.stage_registry import StageRegistry

if TYPE_CHECKING:
    from pathlib import Path

_HEAD = "rev-2"


@pytest.fixture(autouse=True)
def _git_worktree(tmp_path: Path) -> None:
    """Initialise a real git worktree in ``tmp_path`` (hermetic, no fail-open).

    AG3-041 wired ``compute_evidence_fingerprint`` (``git diff
    origin/main..HEAD``) into ``run_qa_subflow`` -> ``start_cycle``. The
    productive ``story_dir`` is ALWAYS a git worktree with an ``origin/main``
    ref; these tests pass ``tmp_path`` as ``story_dir``, so they must stand up
    a genuine repo. Without it the (correct, fail-closed) fingerprint crashes
    when pytest places ``tmp_path`` OUTSIDE the checkout (Jenkins ``/tmp/...``)
    where git finds no ``.git`` via the upward search. A single base commit on
    ``main`` plus a local ``origin/main`` ref makes the diff range deterministic
    independent of where ``tmp_path`` lives.
    """

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
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, ctx: object, story_dir: Path, *, review_input: object = None) -> LayerResult:  # noqa: ARG002
        metadata: dict[str, object] = {}
        if self._name == "structural":
            registry = StageRegistry()
            metadata["stage_ids"] = tuple(
                stage.stage_id
                for stage in registry.layer1_stages_for(
                    StoryType.IMPLEMENTATION, are_enabled=False
                )
            )
        return LayerResult(layer=self._name, passed=True, findings=(), metadata=metadata)


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


@dataclass
class _StubSonarClient:
    """Stub HTTP boundary modelling the REAL Sonar Accepted-counts-green rule.

    Holds the open issues for the branch scan. ``transition_issue(... ,
    'accept')`` moves an issue into the Accepted set, so it leaves the
    open-non-accepted view. ``project_status`` recomputes the gate exactly as
    Sonar does: OK iff there are zero open non-accepted issues, else ERROR.
    The gate's POST-apply RE-READ (E4) therefore observes the recomputed
    verdict — no AK-side subtraction.
    """

    issues: tuple[SonarIssue, ...] = ()
    accepted: set[str] = field(default_factory=set)

    def open_issues(self) -> tuple[SonarIssue, ...]:
        """Open non-accepted issues (resolved=false), as issues/search."""
        return tuple(i for i in self.issues if i.issue_key not in self.accepted)

    def transition_issue(self, issue_key: str) -> None:
        self.accepted.add(issue_key)

    def quality_gate_status(self) -> str:
        return "OK" if not self.open_issues() else "ERROR"

    def post_apply_state(self) -> PostApplyGateState:
        return PostApplyGateState(
            quality_gate_status=self.quality_gate_status(),
            overall_open_issue_count=len(self.open_issues()),
        )


@dataclass(frozen=True)
class _StubSonarGatePort:
    """Resolves gate inputs using the stubbed client (real capability path).

    The attestation's ``quality_gate_status`` is the PRE-apply read (used only
    for the commit-binding stale-check). The green verdict comes from the
    POST-apply ``post_apply_reader``, which re-reads the recomputed gate from
    the stub client after the reconciler's accepts.
    """

    applicability: SonarApplicability
    attestation: SonarAttestation | None
    ledger_entries: tuple[AcceptedExceptionLedgerEntry, ...]
    client: _StubSonarClient

    def resolve_inputs(self, story_id: str, story_dir: object) -> SonarGateInputs:  # noqa: ARG002
        return SonarGateInputs(
            applicability=self.applicability,
            attestation=self.attestation,
            main_head_revision=_HEAD,
            ledger_entries=self.ledger_entries,
            current_issues=self.client.open_issues(),
            issue_applier=self.client.transition_issue,
            post_apply_reader=self.client.post_apply_state,
        )


def _attestation(status: str = "OK") -> SonarAttestation:
    return SonarAttestation(
        commit_sha="c0ffee",
        tree_hash="deadbeef",
        analysis_id="AX-1",
        ce_task_id="CE-1",
        quality_gate_status=status,
        quality_gate_hash="qgh",
        quality_profile_hash="qph",
        analysis_scope_hash="ash",
        new_code_definition="PREVIOUS_VERSION",
        exception_ledger_hash="elh",
        last_analyzed_revision=_HEAD,
        sonarqube_version="26.4",
        branch_plugin_version="1.23.0",
        scanner_version="5.0",
        status="READ",
    )


def _ledger_entry() -> AcceptedExceptionLedgerEntry:
    return AcceptedExceptionLedgerEntry(
        rule_key="python:S1192",
        file_path="src/a.py",
        normalized_code_fingerprint="fp-x",
        expected_message_pattern="dup",
        rationale="r",
        approved_by=("a", "b", "c"),
        approved_commit="c0ffee",
        expiry="",
        scope="branch-only",
    )


def _system(port: object, manager: _RecordingArtifactManager) -> VerifySystem:
    return VerifySystem(
        layer_1=_RecordingLayer("structural"),
        layer_2a=_RecordingLayer("qa_review"),
        layer_2b=_RecordingLayer("semantic_review"),
        layer_2c=_RecordingLayer("doc_fidelity"),
        layer_3=_RecordingLayer("adversarial"),
        policy_engine=PolicyEngine(max_major_findings=0),
        artifact_manager=manager,
        sonar_gate_port=port,  # type: ignore[arg-type]
    )


def _run(vs: VerifySystem, tmp_path: Path) -> object:
    return vs.run_qa_subflow(
        ctx=VerifyContextBundle(
            run_id="run-1", story_dir=tmp_path, phase_envelope=None, attempt=1
        ),
        story_id="TEST-001",
        qa_context=QaContext.IMPLEMENTATION_INITIAL,
        target=ArtifactReference(
            artifact_class=ArtifactClass.WORKER,
            story_id="TEST-001",
            run_id="run-1",
            record_key="envelopes/worker/TEST-001/1",
        ),
    )


def _gate_envelope(manager: _RecordingArtifactManager) -> ArtifactEnvelope:
    gate = [e for e in manager.written_envelopes if e.stage == "sonarqube_gate"]
    assert len(gate) == 1
    return gate[0]


def _gate_status(envelope: ArtifactEnvelope) -> str:
    metadata = envelope.payload["metadata"]
    assert isinstance(metadata, dict)
    return str(metadata["gate_status"])


class TestApplicableFlows:
    def test_applicable_green_passes(self, tmp_path: Path) -> None:
        manager = _RecordingArtifactManager()
        port = _StubSonarGatePort(
            applicability=SonarApplicability.APPLICABLE,
            attestation=_attestation("OK"),
            ledger_entries=(),
            client=_StubSonarClient(),  # no open issues => re-read OK + 0
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.PASS  # type: ignore[attr-defined]
        assert _gate_envelope(manager).status.value == "PASS"

    def test_applicable_red_fails(self, tmp_path: Path) -> None:
        manager = _RecordingArtifactManager()
        # An open issue with no ledger match: the post-apply re-read still
        # reports ERROR + 1 open => red (no AK subtraction can hide it).
        issue = SonarIssue(
            issue_key="K0",
            rule_key="python:S100",
            normalized_code_fingerprint="fp-r",
            message="bad",
        )
        port = _StubSonarGatePort(
            applicability=SonarApplicability.APPLICABLE,
            attestation=_attestation("ERROR"),
            ledger_entries=(),
            client=_StubSonarClient(issues=(issue,)),
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.FAIL  # type: ignore[attr-defined]
        assert _gate_envelope(manager).status.value == "FAIL"
        # E3: APPLICABLE fail-closed routes DIRECTLY to `failed` WITHOUT the
        # policy engine — no decision.json policy artefact is written.
        decisions = [
            e for e in manager.written_envelopes if e.stage == "qa-policy-decision"
        ]
        assert decisions == []

    def test_reconciler_zero_match_fails_before_policy(self, tmp_path: Path) -> None:
        """AC4 wiring: a 0-match ledger fail-closes the gate (BLOCKING) so the
        policy can NEVER aggregate a PASS -- even with a green attestation."""
        manager = _RecordingArtifactManager()
        port = _StubSonarGatePort(
            applicability=SonarApplicability.APPLICABLE,
            attestation=_attestation("OK"),
            ledger_entries=(_ledger_entry(),),
            client=_StubSonarClient(issues=()),  # zero matches
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.FAIL  # type: ignore[attr-defined]
        gate = _gate_envelope(manager)
        assert gate.status.value == "FAIL"
        assert "ledger_reconcile_fail_closed" in str(gate.payload)

    def test_reconciler_single_match_flips_red_to_green(self, tmp_path: Path) -> None:
        """E4 (POST-apply RE-READ): ERROR gate + 1 open issue + single-match
        ledger.

        The reconciler transitions the matched issue to Accepted in the stub
        Sonar; the gate then RE-READS the recomputed gate — Sonar reports OK +
        0 open (the Accepted issue left the gate). The gate flips red->green
        THROUGH the real re-read, with NO AK-side subtraction. The pre-apply
        attestation status is ERROR, proving the verdict comes from the
        re-read and not from the (stale) attestation.
        """
        manager = _RecordingArtifactManager()
        issue = SonarIssue(
            issue_key="K1",
            rule_key="python:S1192",
            normalized_code_fingerprint="fp-x",
            message="dup literal",
        )
        client = _StubSonarClient(issues=(issue,))
        # Pre-apply: ERROR + 1 open (adapter-realistic). Sonar never reports
        # OK while an open non-accepted issue exists.
        assert client.quality_gate_status() == "ERROR"
        port = _StubSonarGatePort(
            applicability=SonarApplicability.APPLICABLE,
            attestation=_attestation("ERROR"),
            ledger_entries=(_ledger_entry(),),
            client=client,
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.PASS  # type: ignore[attr-defined]
        assert _gate_envelope(manager).status.value == "PASS"
        # The accept was actually applied to the stub Sonar (E4 wiring).
        assert client.accepted == {"K1"}

    def test_open_issue_without_ledger_match_stays_red(self, tmp_path: Path) -> None:
        """E4: 1 open issue + NO ledger entry => no accept => re-read ERROR + 1
        => red.

        Proves it is the ACCEPT (not a count fudge) that flips the verdict:
        the same open issue without a matching ledger entry stays red after
        the post-apply re-read.
        """
        manager = _RecordingArtifactManager()
        issue = SonarIssue(
            issue_key="K2",
            rule_key="python:S1192",
            normalized_code_fingerprint="fp-z",
            message="dup literal",
        )
        port = _StubSonarGatePort(
            applicability=SonarApplicability.APPLICABLE,
            attestation=_attestation("ERROR"),
            ledger_entries=(),
            client=_StubSonarClient(issues=(issue,)),
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.FAIL  # type: ignore[attr-defined]
        gate = _gate_envelope(manager)
        assert gate.status.value == "FAIL"
        assert "overall_open_issues_post=1" in str(gate.payload)


class TestNotApplicableFlows:
    def test_unavailable_skips_policy_passes(self, tmp_path: Path) -> None:
        manager = _RecordingArtifactManager()
        port = _StubSonarGatePort(
            applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE,
            attestation=None,
            ledger_entries=(),
            client=_StubSonarClient(),
        )
        outcome = _run(_system(port, manager), tmp_path)
        assert outcome.verdict is PolicyVerdict.PASS  # type: ignore[attr-defined]
        gate = _gate_envelope(manager)
        assert gate.status.value == "PASS"
        assert _gate_status(gate) == "sonarqube_gate_not_applicable"

    def test_fast_drops_the_sonarqube_gate_stage(self, tmp_path: Path) -> None:
        """AG3-052 CONTRACT (AC6 / §2.1.5): mode fast DROPS the sonarqube_gate stage.

        This test pins ONLY AG3-052's own contract: at a fast resolution the
        ``sonarqube_gate`` stage is dropped entirely — no gate ``LayerResult``,
        no Sonar gate envelope, no Sonar verdict feeding the policy.
        The state machine knows no ``not_applicable_fast`` Sonar status.

        SCOPE BOUNDARY (NOT AG3-052): the FULL fast-mode QA-subflow TERMINAL —
        skipping the Policy Engine (Layer 4) and Layers 2-3 and terminating via
        the Layer-1 tests-green floor (invariant
        ``fast-mode-terminates-via-tests-green-floor-without-policy``) — is
        OWNED BY FK-24 §24.3.4 / FK-27 §27.6a, NOT this story. The
        ``tests_green_floor`` step does not exist in the code yet, so here the
        remaining layers + the Policy Engine still run (PRE-EXISTING,
        FOREIGN-OWNED behaviour, present before AG3-052). This test therefore
        does NOT assert ``fast => full Policy-PASS`` as a *conformant end
        state*; it only verifies the Sonar-stage drop. Whether the policy runs
        at all under fast is FK-24/FK-27's call, deliberately not pinned here.

        See ``test_runtime_wiring.py`` for the REAL anchor wiring (E2): the
        productive ``build_sonar_gate_port_for_run`` resolves ``mode == fast``
        to a genuine ``NOT_APPLICABLE_FAST`` port (not an absent skip).
        """
        manager = _RecordingArtifactManager()
        port = _StubSonarGatePort(
            applicability=SonarApplicability.NOT_APPLICABLE_FAST,
            attestation=None,
            ledger_entries=(),
            client=_StubSonarClient(),
        )
        outcome = _run(_system(port, manager), tmp_path)

        # AG3-052 contract: the sonarqube_gate stage produced NOTHING.
        gate_envelopes = [
            e for e in manager.written_envelopes if e.stage == "sonarqube_gate"
        ]
        assert gate_envelopes == []  # stage dropped: no Sonar artefact
        # No Sonar LayerResult fed the decision (no sonarqube layer in results).
        decision = outcome.decision  # type: ignore[attr-defined]
        assert all(
            lr.layer != "sonarqube_gate" for lr in decision.layer_results
        )
        # NOTE: the overall verdict here is whatever the (foreign-owned, still
        # running) policy yields over the OTHER layers; AG3-052 makes no claim
        # about a fast-mode terminal. With the recording stub layers all green
        # it happens to be PASS, but that is NOT this story's contract.

    def test_default_port_skips_when_no_sonar_wired(self, tmp_path: Path) -> None:
        """Default VerifySystem (no sonar port) => the gate stage SKIPs.

        The overall verdict may be FAIL (the real Layer-1/2/3 layers run
        against an empty story dir), but the SonarQube gate itself must
        emit a NON-blocking SKIP (no Sonar verdict, no fail-closed), since
        no Sonar is wired (``available == false``).
        """
        manager = _RecordingArtifactManager()
        vs = VerifySystem.create_default(artifact_manager=manager)
        _run(vs, tmp_path)
        gate = _gate_envelope(manager)
        assert gate.status.value == "PASS"
        assert _gate_status(gate) == "sonarqube_gate_not_applicable"
