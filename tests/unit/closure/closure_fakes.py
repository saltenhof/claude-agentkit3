"""Shared test doubles for the closure phase orchestration tests (AG3-053).

These are stubs at the REAL external boundaries (git backend, Sonar scan, the
fast-mode sanity runner, the level-4 doc-fidelity evaluator, VectorDB sync, the
governance top surface) -- the only places a unit test may stub (the mocks/stubs
exception: external systems). The orchestration / order logic itself is exercised against
real components (the real ``ClosureProgress`` model, the real ``ArtifactManager``,
the real Finding-Resolution-Gate, the real merge saga over a stub ``GitBackend``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.closure.merge_sequence import (
    BuildTestOutcome,
    SanityOutcome,
    ScanOutcome,
)
from agentkit.closure.multi_repo_saga import GitCommandResult

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.closure.merge_sequence import CandidateRef
    from agentkit.closure.multi_repo_saga import ClosureRepo
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate import SonarGateOutcome
    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation


def make_fresh_attestation(
    *,
    commit_sha: str,
    tree_hash: str,
    quality_gate_status: str = "OK",
    sonarqube_version: str = "26.4",
    branch_plugin_version: str = "1.23.0",
    scanner_version: str = "5.0.1",
) -> SonarAttestation:
    """Build a real, complete READ ``SonarAttestation`` for the fresh-scan path.

    The fields satisfy the attestation's mandatory-READ validator (no empty
    binding) and bind ``last_analyzed_revision`` to ``commit_sha`` so Dim 9's
    fresh-attestation commit-binding check passes. Versions default to the FK-03
    defaults (>= the config minima) so the version-drift check is green; tests
    override them to exercise drift.
    """
    from agentkit.verify_system.sonarqube_gate.attestation import (
        ATTESTATION_STATUS_READ,
        SonarAttestation,
    )

    return SonarAttestation(
        commit_sha=commit_sha,
        tree_hash=tree_hash,
        analysis_id="analysis-fresh-001",
        ce_task_id="ce-task-fresh-001",
        quality_gate_status=quality_gate_status,
        quality_gate_hash="qg-hash-001",
        quality_profile_hash="qp-hash-001",
        analysis_scope_hash="scope-hash-001",
        new_code_definition="previous_version",
        exception_ledger_hash="ledger-hash-001",
        last_analyzed_revision=commit_sha,
        sonarqube_version=sonarqube_version,
        branch_plugin_version=branch_plugin_version,
        scanner_version=scanner_version,
        status=ATTESTATION_STATUS_READ,
    )


def make_green_gate_outcome() -> SonarGateOutcome:
    """A FULL AG3-052 green gate outcome (the fresh-scan green truth, FIX-1)."""
    from agentkit.verify_system.sonarqube_gate import (
        SonarApplicability,
        SonarGateOutcome,
    )

    return SonarGateOutcome(
        applicability=SonarApplicability.APPLICABLE,
        passed=True,
        gate_status="sonarqube_gate_passed",
    )


@dataclass
class RecordingScanPort:
    """Stub AG3-056 integrated-candidate scan seam recording its invocation order.

    By default it echoes the candidate commit/tree into the :class:`ScanOutcome`
    (incl. a complete fresh :class:`SonarAttestation`) so the barrier's E3 binding
    check is a trivial PASS (the happy path). ``tree_hash_override`` forces a
    mismatching tree; ``commit_sha_override`` forces a mismatching commit;
    ``omit_binding`` drops the commit/tree binding; ``produced=False`` simulates a
    non-produced scan. Consumes the AG3-056 ``produce_attestation(candidate)``
    signature (no ``story_dir``/``story_type``).
    """

    produced: bool = True
    reason: str | None = None
    tree_hash_override: str | None = None
    commit_sha_override: str | None = None
    omit_binding: bool = False
    with_attestation: bool = True
    calls: list[str] = field(default_factory=list)

    def produce_attestation(self, candidate: CandidateRef) -> ScanOutcome:
        self.calls.append("scan")
        if not self.produced:
            return ScanOutcome(produced=False, reason=self.reason)
        if self.omit_binding:
            return ScanOutcome(produced=True)
        commit = self.commit_sha_override or candidate.commit_sha
        tree = self.tree_hash_override or candidate.tree_hash
        attestation = (
            make_fresh_attestation(commit_sha=commit, tree_hash=tree)
            if self.with_attestation
            else None
        )
        gate_outcome = make_green_gate_outcome() if self.with_attestation else None
        return ScanOutcome(
            produced=True,
            commit_sha=commit,
            tree_hash=tree,
            attestation=attestation,
            gate_outcome=gate_outcome,
        )


@dataclass
class RecordingBuildTestPort:
    """Stub AG3-056 integrated-candidate Build/Test seam; configurable verdict.

    Consumes the AG3-056 ``run(candidate)`` signature (no ``story_dir``/
    ``story_type``).
    """

    green: bool = True
    reason: str | None = None
    calls: list[str] = field(default_factory=list)

    def run(self, candidate: CandidateRef) -> BuildTestOutcome:
        del candidate
        self.calls.append("build_test")
        return BuildTestOutcome(green=self.green, reason=self.reason)


@dataclass
class RecordingIntegrityGate:
    """Stub IntegrityGate recording invocation order; configurable verdict.

    Records the fresh attestation it was handed (``fresh_attestation``) so tests
    can assert the barrier passes the FRESH attestation into Dim 9 (FK-35
    §35.2.4a) rather than letting the gate re-read the worktree.
    """

    passed: bool = True
    failure_reason: str | None = None
    calls: list[str] = field(default_factory=list)
    order_log: list[str] | None = None
    received_fresh_attestation: object | None = field(default=None, init=False)

    def evaluate(
        self,
        story_dir: Path,
        story_type: StoryType,
        *,
        fresh_attestation: object | None = None,
    ) -> _GateResult:
        del story_dir, story_type
        self.calls.append("gate")
        self.received_fresh_attestation = fresh_attestation
        if self.order_log is not None:
            self.order_log.append("gate")
        return _GateResult(passed=self.passed, failure_reason=self.failure_reason)


@dataclass(frozen=True)
class _GateResult:
    """Minimal IntegrityGateResult-shaped result (``passed`` + reason)."""

    passed: bool
    failure_reason: str | None = None


@dataclass
class RecordingSanityPort:
    """Stub fast-mode Sanity-Gate seam; configurable verdict."""

    passed: bool = True
    reason: str | None = None
    calls: list[str] = field(default_factory=list)

    def evaluate(self, story_dir: Path, story_type: StoryType) -> SanityOutcome:
        del story_dir, story_type
        self.calls.append("sanity")
        return SanityOutcome(passed=self.passed, reason=self.reason)


@dataclass
class RecordingDocFidelityPort:
    """Stub level-4 doc-fidelity seam recording invocation order."""

    passed: bool = True
    warning: str | None = None
    order_log: list[str] | None = None
    calls: list[str] = field(default_factory=list)

    def evaluate_feedback_fidelity(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        del ctx, story_dir
        self.calls.append("doc_fidelity")
        if self.order_log is not None:
            self.order_log.append("doc_fidelity")
        return (self.passed, self.warning)


@dataclass
class RecordingVectorDbSyncPort:
    """Stub VectorDB sync seam recording invocation order."""

    triggered: bool = True
    warning: str | None = None
    order_log: list[str] | None = None
    calls: list[str] = field(default_factory=list)

    def trigger_sync(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        del ctx, story_dir
        self.calls.append("vectordb")
        if self.order_log is not None:
            self.order_log.append("vectordb")
        return (self.triggered, self.warning)


@dataclass
class RecordingGuardDeactivationPort:
    """Stub governance guard-deactivation seam recording invocation order."""

    deactivated: bool = True
    warning: str | None = None
    order_log: list[str] | None = None
    calls: list[str] = field(default_factory=list)

    def deactivate(self, story_id: str) -> tuple[bool, str | None]:
        del story_id
        self.calls.append("guard")
        if self.order_log is not None:
            self.order_log.append("guard")
        return (self.deactivated, self.warning)


@dataclass
class StubGitBackend:
    """Stub ``GitBackend`` for the closure barrier + saga (no live git/remote in CI).

    Every git command succeeds by default (the happy path), so the barrier
    captures a stable integrated candidate and the saga reaches ``merge_done``.

    Deterministic ``rev-parse`` answers:

    * ``origin/main`` -> a stable ``main_sha`` (so locked_sha == the re-fetch ==
      the CAS re-read: no lock drift, CAS passes);
    * ``HEAD^{tree}`` -> a stable ``candidate_tree`` (the integrated-candidate
      tree the scan binds to);
    * any other ``rev-parse`` (e.g. ``HEAD``) -> ``candidate_commit`` (also the
      saga's pre-merge-sha capture).

    ``fail_command`` forces a specific git verb to fail (e.g. ``"push"`` for the
    push-failure / partial-push escalation path; ``"clean"`` / ``"merge"`` for
    barrier-step escalations). ``dirty_status`` makes ``git status --porcelain``
    report a non-empty worktree. ``main_drift_sha`` makes the CAS re-read of
    ``origin/main`` return a drifted sha (compare-and-swap failure).
    """

    fail_command: str | None = None
    dirty_status: bool = False
    main_drift_sha: str | None = None
    main_sha: str = "0000main0000"
    candidate_commit: str = "1111commit1111"
    candidate_tree: str = "2222tree2222"
    commands: list[tuple[str, ...]] = field(default_factory=list)
    _origin_reads: int = 0

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        del repo
        self.commands.append(args)
        if self.fail_command is not None and args and args[0] == self.fail_command:
            return GitCommandResult(returncode=1, stderr=f"{self.fail_command} failed")
        if args[:1] == ("rev-parse",):
            return self._rev_parse(args[1:])
        if args[:2] == ("status", "--porcelain"):
            stdout = " M file.py\n" if self.dirty_status else ""
            return GitCommandResult(returncode=0, stdout=stdout)
        return GitCommandResult(returncode=0, stdout="")

    def _rev_parse(self, refs: tuple[str, ...]) -> GitCommandResult:
        ref = refs[0] if refs else ""
        if ref == "origin/main":
            self._origin_reads += 1
            # First two reads = lock + post-fetch assert (must match). A later
            # read is the CAS guard; ``main_drift_sha`` simulates a moved main.
            if self.main_drift_sha is not None and self._origin_reads >= 3:
                return GitCommandResult(returncode=0, stdout=self.main_drift_sha)
            return GitCommandResult(returncode=0, stdout=self.main_sha)
        if ref == "HEAD^{tree}":
            return GitCommandResult(returncode=0, stdout=self.candidate_tree)
        return GitCommandResult(returncode=0, stdout=self.candidate_commit)

    def remove_worktree(self, repo: ClosureRepo) -> None:
        del repo


class NoOpStoryService:
    """Minimal no-op StoryService stub (complete_story succeeds)."""

    def complete_story(self, story_id: str, *, correlation_id: str = "") -> object:
        del story_id, correlation_id
        return object()


def build_progress_store(store_dir: Path) -> object:
    """Build the REAL closure checkpoint store over the state backend.

    The checkpoint writer is the productive ``pipeline_engine`` ``PhaseEnvelopeStore``
    (NOT a stub) -- only the external boundaries are stubbed, not the persistence
    of the ``ClosureProgress`` truth.
    """
    from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    return PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(store_dir))


__all__ = [
    "NoOpStoryService",
    "build_progress_store",
    "make_fresh_attestation",
    "make_green_gate_outcome",
    "RecordingBuildTestPort",
    "RecordingDocFidelityPort",
    "RecordingGuardDeactivationPort",
    "RecordingIntegrityGate",
    "RecordingSanityPort",
    "RecordingScanPort",
    "RecordingVectorDbSyncPort",
    "StubGitBackend",
]
