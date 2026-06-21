"""Commit-bound Sonar-scan runner for the pre-merge barrier (AG3-056).

Fulfils :class:`PreMergeScanPort`: it EXECUTES (CI-triggers) a Sonar scan on
the integrated candidate and returns a :class:`ScanOutcome` whose
commit-binding is PROVEN by Sonar itself — never a stale local
``report-task.txt`` and never a locally-stapled commit on a foreign
analysis (fixes Review-ERROR-1 + ERROR-2).

Flow (AG3-056 AC1/AC2/AC4 + FIX-1..FIX-4):

1. Obtain the ONE CI run for the candidate from the shared
   :class:`CandidateRunCache` (FIX-3 — the SAME run backs both the scan and
   the build/test facet). The run produces its OWN ``report-task.txt``
   (``ceTaskId``/``projectKey``/server metadata — NO ``analysisId``, ERROR-A;
   NO ``branch``, ERROR-2).
2. Require the commit Jenkins ACTUALLY built (``built_commit``) to equal the
   candidate commit (FIX-3): a job that silently builds branch-tip cannot
   report green for a foreign commit.
3. Build a COMPLETE, commit-bound :class:`SonarAttestation` by REUSING
   AG3-052's :func:`read_commit_bound_attestation` (FIX-4), bound to the
   freshly-triggered run's ``analysisId``/``ceTaskId`` (never a local
   ``.scannerwork``). ``last_analyzed_revision`` is read via the authoritative
   ``api/project_analyses/search`` chain (FIX-2 — no ``component.version``
   fallback); ``tree_hash`` is derived from the proven candidate commit
   (``git rev-parse <commit>^{tree}``); ``exception_ledger_hash`` from the
   ledger actually used.
4. Prove the binding: the resolved analysisId is found among the CANDIDATE
   branch's analyses (``project_analyses/search`` scoped to
   ``candidate.branch``) with revision == candidate commit (ERROR-2 — the
   branch proof IS finding the analysisId on the candidate branch;
   :func:`prove_binding` then confirms the revision).
5. Run the FULL AG3-052 gate over THIS run's analysis (FIX-1): the
   Single-Match ledger reconciler + the accepted-exception transition + the
   post-apply quality-gate / open-issue re-read + the Broken-Window
   overall-zero criterion, via :func:`evaluate_sonarqube_gate` — the SAME
   green truth as the impl-phase gate (no raw ``quality_gate_status``
   shortcut, no second green truth).
6. Only on proof: ``ScanOutcome(produced=True, commit_sha=<candidate>,
   tree_hash=<proven>, attestation=<fresh, complete>, gate_outcome=<full
   AG3-052 outcome>)`` — the supplied attestation + gate outcome are what the
   Closure IntegrityGate Dim 9 evaluates (FIX-1); it MUST NOT re-read the
   worktree and MUST NOT recompute green itself.

Any failure (unreachable CI/Sonar, no analysis from the run, built-commit
mismatch, revision/branch mismatch, unresolvable tree hash, malformed
responses) yields a fail-closed ``ScanOutcome(produced=False, reason=...)``
with ``attestation=None``. Green/attestation logic is REUSED from AG3-052.

Pipeline contract (FIX-2): the candidate scan MUST run with
``sonar.scm.revision=<candidate.commit_sha>`` so Sonar records the exact
analysed revision; the productive wiring passes it through the CI run
parameters and the analyses-search chain reads it back as proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.verify_system.pre_merge_runner.binding import prove_binding
from agentkit.backend.verify_system.pre_merge_runner.ci_run import CiRunUnavailableError
from agentkit.backend.verify_system.pre_merge_runner.contract import ScanOutcome
from agentkit.backend.verify_system.sonarqube_gate import (
    SonarApplicability,
    build_issue_applier,
    evaluate_sonarqube_gate,
)
from agentkit.backend.verify_system.sonarqube_gate.adapter import (
    BoundAnalysis,
    read_commit_bound_attestation,
    read_open_issues,
    read_post_apply_state,
)
from agentkit.integration_clients.sonar import SonarApiError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.verify_system.pre_merge_runner.ci_run import (
        CandidateRunCache,
        CiRunResult,
    )
    from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef
    from agentkit.backend.verify_system.sonarqube_gate import SonarGateOutcome
    from agentkit.backend.verify_system.sonarqube_gate.attestation import SonarAttestation
    from agentkit.backend.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
    from agentkit.integration_clients.sonar import SonarClient


class TreeHashResolver(Protocol):
    """Resolves the git tree hash of a commit (fail-closed seam).

    The productive implementation runs ``git rev-parse <commit>^{tree}`` in
    the integrated-candidate repo; tests supply a deterministic fake. A
    resolution failure raises so the runner never stamps an empty tree hash
    into a "produced" attestation (FIX-4).
    """

    def __call__(self, commit_sha: str) -> str:
        """Return the tree hash of ``commit_sha`` (raise on failure)."""
        ...


@dataclass(frozen=True)
class GitTreeHashResolver:
    """Productive :class:`TreeHashResolver` over ``agentkit.backend.utils.git``.

    Attributes:
        repo_root: Root of the git repository holding the candidate commit.
    """

    repo_root: Path

    def __call__(self, commit_sha: str) -> str:
        from agentkit.backend.utils.git import tree_hash_of_commit

        return tree_hash_of_commit(self.repo_root, commit_sha)


@dataclass(frozen=True)
class CiSonarScanRunner:
    """Productive :class:`PreMergeScanPort` over a shared CI run + Sonar client.

    Attributes:
        run_cache: The shared :class:`CandidateRunCache` that triggers ONE CI
            run per candidate and serves it to both the scan and the
            build/test facet (FIX-3).
        client: The thin ``integrations.sonar`` client (scoped token) used to
            read the attestation Sonar holds for the run's analysis.
        config: The resolved ``sonarqube`` config stanza.
        ledger: The accepted-exception ledger actually used for this analysis
            (its content hash is bound into the attestation, FIX-4).
        tree_resolver: Resolves ``tree_hash`` from the proven candidate commit
            (``git rev-parse <commit>^{tree}``, FIX-4) — never a local HEAD.
    """

    run_cache: CandidateRunCache
    client: SonarClient
    config: SonarQubeConfig
    ledger: AcceptedExceptionLedger
    tree_resolver: TreeHashResolver

    def produce_attestation(self, candidate: CandidateRef) -> ScanOutcome:
        """Execute a scan on the candidate and return a proven outcome.

        Args:
            candidate: The integrated-candidate commit to scan.

        Returns:
            ``ScanOutcome(produced=True, attestation=<fresh, complete>, ...)``
            ONLY when Sonar proved the analysis is bound to the candidate;
            otherwise a fail-closed ``produced=False`` outcome (attestation
            ``None``) with a machine reason.
        """
        if not candidate.commit_sha:
            return ScanOutcome(produced=False, reason="candidate_commit_sha_missing")
        try:
            run = self.run_cache.run_for(candidate)
            built_check = _check_built_commit(run, candidate.commit_sha)
            if built_check is not None:
                return built_check
            built = self._read_attestation(run, candidate)
        except CiRunUnavailableError as exc:
            return ScanOutcome(produced=False, reason=f"ci_run_unavailable: {exc}")
        except SonarApiError as exc:
            return ScanOutcome(produced=False, reason=f"sonar_unreachable: {exc}")
        if built is None:
            return ScanOutcome(produced=False, reason="no_analysis_from_run")
        attestation, analysis = built

        proof = prove_binding(
            attestation,
            candidate_commit_sha=candidate.commit_sha,
        )
        if not proof.bound:
            return ScanOutcome(produced=False, reason=proof.reason)

        # FIX-1: run the FULL AG3-052 gate over THIS run's analysis (Single-Match
        # ledger reconcile + accepted-exception transition + post-apply QG/open
        # re-read + Broken-Window overall-zero) so the Closure Dim-9 consumes the
        # SAME green truth as the impl-phase gate — never the raw pre-apply
        # ``attestation.quality_gate_status``. A configured-but-unreachable Sonar
        # on the gate re-read fails the gate closed (carried in the outcome).
        try:
            gate_outcome = self._evaluate_gate(attestation, analysis, candidate)
        except SonarApiError as exc:
            return ScanOutcome(produced=False, reason=f"sonar_unreachable: {exc}")

        # Binding proven by Sonar: surface the FRESH, complete attestation AND the
        # full gate outcome so the consumer (Dim 9) evaluates exactly them (FIX-1)
        # and never re-reads the worktree. commit/tree come from the proven
        # analysis.
        return ScanOutcome(
            produced=True,
            commit_sha=candidate.commit_sha,
            tree_hash=attestation.tree_hash,
            attestation=attestation,
            gate_outcome=gate_outcome,
        )

    def _read_attestation(
        self, run: CiRunResult, candidate: CandidateRef
    ) -> tuple[SonarAttestation, BoundAnalysis] | None:
        """Build the run's COMPLETE commit-bound attestation + its coordinates.

        Returns ``None`` when the run produced no analysis reference (no scan
        from the run) — fail-closed downstream. Otherwise REUSES AG3-052's
        :func:`read_commit_bound_attestation`, bound to the run's analysisId
        with the candidate's proven tree hash and the ledger hash, and returns
        the :class:`BoundAnalysis` coordinates so the gate evaluation (FIX-1)
        can re-read this run's issues / post-apply state.
        """
        if not run.ce_task_id:
            return None
        if not run.component:
            raise SonarApiError(
                "run report-task carried no projectKey/component "
                "(cannot read the bound analysis, FK-33 §33.6.3)"
            )
        if not run.scanner_version:
            raise SonarApiError(
                "CI run exposed no SONAR_SCANNER_VERSION for the analysis of "
                f"ceTaskId={run.ce_task_id!r} (FK-33 §33.6.3, fail-closed — "
                "never a placeholder scanner version in a produced attestation)"
            )
        try:
            tree_hash = self.tree_resolver(candidate.commit_sha)
        except Exception as exc:  # noqa: BLE001 — any resolver failure fails closed
            raise SonarApiError(
                f"could not resolve tree hash for {candidate.commit_sha!r} "
                f"(FIX-4, fail-closed — no empty tree stamping): {exc}"
            ) from exc
        if not tree_hash:
            raise SonarApiError(
                f"empty tree hash for {candidate.commit_sha!r} "
                "(FIX-4, fail-closed)"
            )
        analysis = BoundAnalysis(
            ce_task_id=run.ce_task_id,
            component=run.component,
            # ERROR-2: scope the analysis to the CANDIDATE branch. The branch
            # proof is "the resolved analysisId is found among THIS branch's
            # analyses with revision == candidate.commit_sha" (read in
            # ``read_last_analyzed_revision`` via project_analyses/search
            # branch=candidate.branch) — never a non-real report-task field.
            branch=candidate.branch,
            commit_sha=candidate.commit_sha,
            tree_hash=tree_hash,
            scanner_version=run.scanner_version,
        )
        attestation = read_commit_bound_attestation(
            self.client,
            self.config,
            analysis,
            exception_ledger_hash=self.ledger.content_hash(),
        )
        return attestation, analysis

    def _evaluate_gate(
        self,
        attestation: SonarAttestation,
        analysis: BoundAnalysis,
        candidate: CandidateRef,
    ) -> SonarGateOutcome:
        """Run the FULL AG3-052 gate over the run's analysis (FIX-1).

        Reuses :func:`evaluate_sonarqube_gate` (the impl-phase green truth):
        the current branch-scan issues (``issues/search``), the ledger the
        runner holds, the scoped-token issue applier and the post-apply re-read
        — all over the same Sonar client / analysis the attestation was built
        from. The applicability is APPLICABLE: the runner is only built for an
        ``available == true`` Sonar on a code-producing candidate (the
        composition root resolves declared absence to ``None`` and never builds
        this runner). The stale-check uses the candidate commit (the analysed
        revision the attestation is bound to), not ``main`` HEAD: the scan
        analysed the integrated candidate (FK-29 §29.1a.3 d).
        """
        current_issues = read_open_issues(self.client, analysis)
        return evaluate_sonarqube_gate(
            applicability=SonarApplicability.APPLICABLE,
            attestation=attestation,
            main_head_revision=candidate.commit_sha,
            ledger_entries=self.ledger.entries,
            current_issues=current_issues,
            issue_applier=build_issue_applier(self.client),
            post_apply_reader=lambda: read_post_apply_state(self.client, analysis),
        )


def _check_built_commit(run: CiRunResult, commit_sha: str) -> ScanOutcome | None:
    """Fail closed unless Jenkins actually built the candidate commit (FIX-3)."""
    if run.built_commit is None:
        return ScanOutcome(
            produced=False,
            reason="built_commit_unknown: Jenkins exposed no built revision",
        )
    if run.built_commit != commit_sha:
        return ScanOutcome(
            produced=False,
            reason=(
                f"built_commit_mismatch: built={run.built_commit!r} "
                f"candidate={commit_sha!r}"
            ),
        )
    return None


__all__ = ["CiSonarScanRunner", "GitTreeHashResolver", "TreeHashResolver"]
