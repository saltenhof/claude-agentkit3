"""Closure merge sequence (FK-29 §29.1a / §29.1.4, BC 7 ``MergeSequence``).

Thin orchestration of the Pre-Merge-Scan-and-Merge-Block under the
merge-serialization lock. This module OWNS the canonical pre-push green barrier
ORDER only -- it builds no second merge, gate, Sonar or lock truth. It CONSUMES
the AG3-056 Pre-Merge-Verification-Runner contract
(``agentkit.verify_system.pre_merge_runner.contract``) for the commit-bound
Build/Test + Sonar scan ports; the dependency direction is strictly
``closure -> verify_system.pre_merge_runner`` (never the reverse). It runs, in
the strict locked order (FK-29 §29.1a.3, NO ERROR BYPASSING):

1. **lock** -- capture ``locked_sha`` of the current ``origin/main`` (the CAS/lease
   base for the later ff-update), then fetch and assert ``origin/main`` still
   equals ``locked_sha`` (lock drift => re-setup the whole block);
2. **integrate-latest-main** into the story branch (the "integrated candidate")
   over the injected :class:`GitBackend`;
3. **clean workspace** -- ``git clean -xfd`` + assert ``git status --porcelain``
   is empty, so the scan measures exactly the committed tree;
4. **capture** the integrated-candidate ``commit_sha`` + ``tree_hash`` (the
   binding the scan attestation and the later merge must both match), build the
   AG3-056 :class:`CandidateRef` from it;
5. **Build/Test** on the integrated candidate via the injected, commit-bound
   AG3-056 :class:`BuildTestPort` (a red/aborted/unreachable run escalates --
   NEVER a silent merge without a confirmed build);
6. **Sonar scan** on the integrated candidate via the AG3-056
   :class:`PreMergeScanPort` -- PRODUCES the fresh, commit-bound attestation
   (``ScanOutcome.attestation``) carrying the Sonar-proven ``commit_sha`` +
   ``tree_hash``;
7. **tree+commit binding** (E3) -- assert ``scan.produced`` AND
   ``scan.commit_sha == candidate.commit_sha`` AND ``scan.tree_hash ==
   candidate.tree_hash`` (the attested revision IS the revision about to be
   merged); any mismatch / absence escalates (no sham verification);
8. **IntegrityGate** Dim 1-9 -- VERIFIES the FRESH ``ScanOutcome.attestation``
   (Dim 9, FK-35 §35.2.4a) AFTER the scan and BEFORE the push; the barrier
   passes the fresh attestation to ``IntegrityGate.evaluate`` so Dim 9 evaluates
   exactly it and never re-reads the worktree; a FAIL escalates;
9. **CAS guard** -- re-assert ``origin/main == locked_sha`` (main drifted since
   the lock => re-setup the block, never merge against a stale base);
10. **Saga + atomic CAS push** -- the AG3-009 multi-repo closure saga building
    blocks perform the story-branch push and the ff-only merge; the final
    ``origin/main`` update is an ATOMIC compare-and-swap against ``locked_sha``
    (``git push --force-with-lease=main:<locked_sha>``, E4): a concurrent advance
    is a fail-closed escalation with rollback, NEVER a clobber (FK-29 §29.1.5
    ff_only; ``--force-with-lease`` to the exact locked sha is a CAS, not a
    history rewrite).

Checkpoint timing (E5, FK-29 §29.1.0/§29.1.3): the block returns its reached
:class:`ClosureProgress`; ``story_branch_pushed`` is set ONLY after the push
succeeded and ``merge_done`` ONLY after the CAS main-update succeeded on ALL
repos. The caller persists each checkpoint AFTER its side-effect succeeds, so a
crash mid-side-effect never marks it done; ``on_resume`` re-runs only the
incomplete substate (no double-merge). The locked block is ATOMAR: it has NO
intra-lock sub-checkpoints beyond those durable booleans.

In ``mode == fast`` (§29.1a.6) the integrate/build/test/scan and the
nine-dimension IntegrityGate are replaced by the Sanity-Gate (tests green +
worktree clean + pre-merge rebase OK); a sanity violation / rebase conflict
escalates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from agentkit.closure.multi_repo_saga import (
    ClosureRepo,
    SubprocessGitBackend,
    local_ff_merge_with_rollback,
    push_story_branches,
    teardown_worktrees,
)
from agentkit.story_context_manager.models import ClosureProgress
from agentkit.verify_system.pre_merge_runner.contract import (
    BuildTestOutcome,
    BuildTestPort,
    CandidateRef,
    PreMergeScanPort,
    ScanOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from agentkit.closure.multi_repo_saga import GitBackend
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.governance.integrity_gate.dim9_sonar import FreshAttestation
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType

    #: Checkpoint sink the block calls IMMEDIATELY after each durable side-effect
    #: (FIX-4/E5): the handler persists the reached ``ClosureProgress`` before the
    #: next irreversible step, so a crash mid-side-effect never marks it done.
    CheckpointSink = Callable[[ClosureProgress], None]


@dataclass(frozen=True)
class RepoRunners:
    """The commit-bound runner pair for ONE participating repo (FIX-C).

    Each :class:`ClosureRepo` is verified against ITS OWN root: the AG3-056
    :class:`PreMergeScanPort` / :class:`BuildTestPort` are built per
    ``repo_root`` (each with its own ledger + tree-hash resolver), so a repo's
    Build/Test, scan, ledger hash, tree hash and :class:`CandidateRef` bind to
    that repo -- never to the first repo's root (the FIX-6-part-B defect). A
    single-repo run is the one-entry case. ``scan_port`` is ``None`` for a
    ``SONAR_ABSENT`` repo (Build/Test still runs; scan + Dim 9 skipped).

    Attributes:
        scan_port: The repo's integrated-candidate Sonar scan seam (``None`` for
            a declared-absent Sonar on that repo).
        build_test_port: The repo's integrated-candidate Build/Test seam.
    """

    scan_port: PreMergeScanPort | None
    build_test_port: BuildTestPort | None

#: The reference base branch the barrier integrates and ff-merges against.
#: The AG3-056 contract types (``BuildTestOutcome``/``BuildTestPort``/
#: ``CandidateRef``/``PreMergeScanPort``/``ScanOutcome``) are imported above and
#: re-exported via ``__all__`` -- closure consumers get them from this canonical
#: surface WITHOUT a second definition (SSOT: the runner contract).
_BASE_BRANCH = "main"


class MergeBlockStatus(StrEnum):
    """Outcome of the Pre-Merge-Scan-and-Merge-Block (FK-29 §29.1a)."""

    MERGED = "MERGED"
    ESCALATED = "ESCALATED"


class MergeApplicability(StrEnum):
    """Typed pre-merge applicability for an impl/bugfix story (FIX-3, FK-33 §33.6.5).

    Resolved at the applicability layer (the composition root, which owns the
    config reads) from the story type + the ``ci``/``sonarqube`` availability —
    NEVER inferred inside the block from ``None`` ports. The block consumes this
    to decide WHICH barrier steps apply, so a declared absence never silently
    merges code unverified (NO ERROR BYPASSING):

    * ``FULL`` -- CI present AND Sonar present: Build/Test + integrated-candidate
      Sonar scan + IntegrityGate Dim 1-9 (Dim 9 verifies the fresh attestation).
    * ``SONAR_ABSENT`` -- CI present but Sonar DECLARED absent
      (``sonarqube.available == false``): the integrated-candidate scan + Dim 9
      are not-applicable (skipped, no ``SONAR_NOT_GREEN``), but Build/Test STILL
      runs and the merge is STILL gated on Build/Test green + the rest of the
      IntegrityGate. Sonar absence never skips Build/Test or the merge gating.
    * ``CI_ABSENT`` -- CI DECLARED absent (``ci.available == false`` / no
      stanza): for a code-producing story there is no Build/Test+scan runner =>
      the integrated candidate cannot be verified => FAIL-CLOSED (cannot verify
      => cannot merge). The handler escalates; the block never merges.
    """

    FULL = "FULL"
    SONAR_ABSENT = "SONAR_ABSENT"
    CI_ABSENT = "CI_ABSENT"


@dataclass(frozen=True)
class IntegratedCandidate:
    """The committed integrated candidate the scan and the merge must both bind to.

    Captured after ``integrate-latest-main`` + clean-workspace (FK-29 §29.1a.3
    steps b/c). ``commit_sha`` + ``tree_hash`` are the binding the scan
    attestation must carry (step d) and the value the ``tree_hash(scan) ==
    tree_hash(merge)`` invariant (step 5) is checked against. The closure owns
    this candidate (and ``locked_sha`` for the CAS); the AG3-056
    :class:`CandidateRef` is BUILT from it via :meth:`to_candidate_ref` when the
    runner ports are called (the runner contract carries no lock concepts).

    Attributes:
        commit_sha: The integrated-candidate HEAD commit on the story branch.
        tree_hash: The integrated-candidate HEAD tree hash.
        locked_sha: The ``origin/main`` HEAD captured at lock acquisition (the
            CAS/lease base for the ff-update, FK-29 §29.1a.3 step 7). Stays in
            closure -- it never leaks into the AG3-056 contract.
    """

    commit_sha: str
    tree_hash: str
    locked_sha: str

    def to_candidate_ref(self, *, branch: str) -> CandidateRef:
        """Build the AG3-056 :class:`CandidateRef` for the runner ports.

        Args:
            branch: The integrated-candidate story branch the scan/build runs on.

        Returns:
            A :class:`CandidateRef` carrying the candidate branch/commit/tree
            (no lock concepts -- ``locked_sha`` stays in closure).
        """
        return CandidateRef(
            branch=branch,
            commit_sha=self.commit_sha,
            tree_hash=self.tree_hash,
        )


@dataclass(frozen=True)
class SanityOutcome:
    """Result of the fast-mode Sanity-Gate (FK-29 §29.1a.6).

    The Sanity-Gate replaces the integrated-candidate scan AND the nine-dimension
    IntegrityGate in ``mode == fast``: tests green AND worktree clean AND a clean
    pre-merge rebase onto ``main``. Any violation (including a rebase conflict)
    escalates to the human (the human actively accompanies a fast story).

    Attributes:
        passed: ``True`` only when tests are green, the worktree is clean and the
            pre-merge rebase onto ``main`` succeeded.
        reason: A human-facing reason when ``passed`` is ``False`` (e.g. a rebase
            conflict).
    """

    passed: bool
    reason: str | None = None


class SanityGatePort(Protocol):
    """Capability seam for the fast-mode Sanity-Gate (FK-29 §29.1a.6).

    The productive implementation checks tests-green + worktree-clean +
    pre-merge-rebase-OK. The external git/test boundary is stubbed in tests.
    """

    def evaluate(self, story_dir: Path, story_type: StoryType) -> SanityOutcome:
        """Evaluate the fast-mode sanity precondition for the merge."""
        ...


@dataclass(frozen=True)
class MergeBlockResult:
    """Result of the Pre-Merge-Scan-and-Merge-Block.

    Attributes:
        status: ``MERGED`` (all of the barrier + push/merge succeeded) or
            ``ESCALATED`` (any hard blocker).
        progress: The :class:`ClosureProgress` reached inside the block. On
            ESCALATED only the checkpoints that durably completed are ``true``
            (e.g. ``story_branch_pushed`` but not ``merge_done`` when the
            main-update CAS failed). The caller persists each checkpoint as it is
            reached (E5). Note: ``integrity_passed`` is the gate PASS of THIS
            block run (bound to the fresh attestation), NOT a separately
            resumable intra-lock checkpoint (FK-29 §29.1.3).
        errors: Hard-blocker reasons (empty on MERGED).
    """

    status: MergeBlockStatus
    progress: ClosureProgress
    errors: tuple[str, ...] = ()


def _is_fast(ctx: StoryContext) -> bool:
    """Resolve the fast axis from the typed mode profile (FK-24 §24.3.3).

    The fast/standard axis lives on ``StoryContext.mode`` (``WireStoryMode``),
    a SEPARATE axis from ``execution_route``. This is the typed switch the Closure
    fast-mode weiche (§29.1a.6) keys on -- no string/flag cascade.
    """
    from agentkit.story_context_manager.story_model import WireStoryMode

    return ctx.mode is WireStoryMode.FAST


def run_pre_merge_and_merge_block(  # noqa: PLR0913 -- a fail-closed barrier wires many DI seams
    ctx: StoryContext,
    *,
    story_dir: Path,
    repos: tuple[ClosureRepo, ...],
    integrity_gate: IntegrityGate,
    scan_port: PreMergeScanPort | None,
    build_test_port: BuildTestPort | None,
    sanity_port: SanityGatePort,
    applicability: MergeApplicability = MergeApplicability.FULL,
    sonar_config: object | None = None,
    git_backend: GitBackend | None = None,
    checkpoint: CheckpointSink | None = None,
    progress: ClosureProgress | None = None,
    repo_runners: Mapping[Path, RepoRunners] | None = None,
) -> MergeBlockResult:
    """Run the locked Pre-Merge-Scan-and-Merge-Block in the canonical order.

    Standard (``mode != fast``) order, FK-29 §29.1a.3 (the order is STRUCTURAL,
    NO ERROR BYPASSING -- not a flag cascade): lock/``locked_sha`` ->
    integrate-latest-main -> clean workspace -> capture candidate commit/tree ->
    Build/Test (AG3-056 port) -> integrated-candidate Sonar scan (AG3-056 port,
    fresh commit-bound attestation) -> tree+commit binding (E3) -> IntegrityGate
    Dim 1-9 (verifies the fresh attestation) -> CAS/lease re-assert
    ``origin/main == locked_sha`` -> saga push + ff-merge + atomic CAS main-update
    (E4). Any blocker escalates with NO push and NO main update.

    Fast (``mode == fast``) order, FK-29 §29.1a.6: the integrate/build/test/scan
    and the nine-dimension IntegrityGate are SKIPPED; the Sanity-Gate (tests green
    + worktree clean + pre-merge rebase OK) is the merge precondition. A sanity
    violation / rebase conflict escalates. On a Sanity PASS the same saga building
    blocks perform push/merge/CAS.

    Args:
        ctx: The run :class:`StoryContext` (story type + mode).
        story_dir: The story working directory.
        repos: The participating repos (one element => single-repo path; the
            same saga building blocks, one merge truth). The integrated-candidate
            barrier is the single-repo path; a multi-repo (``>= 2``) run escalates
            fail-closed (per-repo barrier binding needs a State change -- out of
            scope here).
        integrity_gate: The injected AG3-034 gate (verifier of the fresh
            attestation, not owner).
        scan_port: The AG3-056 integrated-candidate scan seam (producer of the
            fresh attestation). ``None`` for a DECLARED-ABSENT CI/Sonar
            (``ci.available == false``, FK-29 §29.1.1 / FK-33 §33.6.5 "absent !=
            broken"): the Build/Test + scan steps are skipped and the gate runs
            without a fresh Sonar attestation (Dim 9 resolves not-applicable).
            An applicable-but-unreachable runner is NOT ``None`` -- the comp-root
            raises before wiring (fail-closed), never a silent skip.
        build_test_port: The AG3-056 integrated-candidate Build/Test seam.
            ``None`` for the same declared-absent case as ``scan_port``.
        sanity_port: The fast-mode Sanity-Gate seam.
        sonar_config: The project ``sonarqube`` config (FK-03), threaded into the
            fresh-attestation Dim-9 version-drift check (§35.2.4a item 5). The
            composition root resolves it (truth boundary); ``None`` only for a
            declared-absent scan (no attestation -> no drift check needed).
        git_backend: Optional git backend for the barrier + the saga (stubbed in
            tests; the real subprocess backend in production).

    Returns:
        A :class:`MergeBlockResult`.

    Notes:
        ``progress`` carries the durable :class:`ClosureProgress` recovery
        checkpoints (FK-29 §29.1.0/§29.1.3). The granular booleans are skipped
        on resume (FIX-A): ``merge_done`` returns MERGED immediately;
        ``story_branch_pushed`` (and not ``merge_done``) SKIPS scan/gate/push and
        goes straight to the ff/CAS merge of the already-pushed, already-verified
        story branch (ff-only + ``--force-with-lease`` is the safety -- a diverged
        main / lease failure fails closed, NEVER a re-scan or a forced
        non-ff merge); ``integrity_passed`` (and not ``story_branch_pushed``)
        SKIPS scan/gate, (re-)pushes then ff/CAS-merges. Dim 1-9 is NEVER re-run
        once ``integrity_passed`` is durable.
    """
    sink: CheckpointSink = checkpoint if checkpoint is not None else _no_checkpoint
    current = progress if progress is not None else ClosureProgress()
    if _is_fast(ctx):
        return _run_fast_block(
            ctx,
            story_dir=story_dir,
            repos=repos,
            sanity_port=sanity_port,
            git_backend=git_backend,
            checkpoint=sink,
            progress=current,
        )
    # FIX-3: CI declared absent for a code-producing story => no Build/Test+scan
    # runner => the integrated candidate cannot be verified => FAIL-CLOSED. Never
    # merge code unverified (the handler normally escalates earlier; this is the
    # block's own fail-closed backstop).
    if applicability is MergeApplicability.CI_ABSENT:
        return _escalated(
            ClosureProgress(),
            "pre-merge CI is declared absent for a code-producing story: cannot "
            "run Build/Test or the integrated-candidate scan -> cannot verify -> "
            "fail-closed (no merge of unverified code, FK-29 §29.1a / FK-33 "
            "§33.6.5)",
        )
    # FIX-A: recovery-aware dispatch over the granular durable booleans (FK-29
    # §29.1.0/§29.1.3). Skip every step whose checkpoint is already true; resume
    # at the first genuinely-incomplete substate -- NEVER re-run Dim 1-9 or
    # re-push when its checkpoint already proves it ran.
    resume = _resume_merge_only(ctx, repos, current, git_backend, sink)
    if resume is not None:
        return resume
    return _run_standard_block(
        ctx,
        story_dir=story_dir,
        repos=repos,
        integrity_gate=integrity_gate,
        scan_port=scan_port,
        build_test_port=build_test_port,
        applicability=applicability,
        sonar_config=sonar_config,
        git_backend=git_backend,
        checkpoint=sink,
        repo_runners=repo_runners,
    )


def _resume_merge_only(
    ctx: StoryContext,
    repos: tuple[ClosureRepo, ...],
    progress: ClosureProgress,
    git_backend: GitBackend | None,
    checkpoint: CheckpointSink,
) -> MergeBlockResult | None:
    """Dispatch a recovery resume that SKIPS the green barrier (FIX-A).

    Returns ``None`` when the full block must run (no durable
    ``integrity_passed``); otherwise the result of the skip-to-merge /
    skip-to-push resume:

    * ``merge_done`` -> already merged: return MERGED (no side-effect).
    * ``story_branch_pushed`` (not ``merge_done``) -> SKIP scan/gate/push; ff/CAS
      merge the already-pushed verified branch (``skip_push=True``).
    * ``integrity_passed`` (not ``story_branch_pushed``) -> SKIP scan/gate;
      (re-)push then ff/CAS merge (``skip_push=False``).

    The integrated-candidate scan attestation proved integrity on the original
    run; it is NOT re-produced. Safety without a persisted candidate is the
    ff-only + ``--force-with-lease`` merge against a freshly captured
    ``locked_sha`` (a diverged main / lease failure escalates fail-closed).
    """
    if progress.merge_done:
        return MergeBlockResult(status=MergeBlockStatus.MERGED, progress=progress)
    if not progress.integrity_passed:
        return None  # nothing durable yet -> run the full barrier
    if not repos:
        return _escalated(
            progress, "no participating repo for the recovery merge resume"
        )
    git = git_backend or SubprocessGitBackend()
    candidates = _capture_resume_candidates(git, repos)
    if isinstance(candidates, MergeBlockResult):
        return candidates
    return _run_merge_with_cas(
        ctx,
        candidates,
        git,
        checkpoint,
        base_progress=progress,
        skip_push=progress.story_branch_pushed,
    )


def _capture_resume_candidates(
    git: GitBackend, repos: tuple[ClosureRepo, ...]
) -> list[tuple[ClosureRepo, IntegratedCandidate]] | MergeBlockResult:
    """Capture each repo's current ``locked_sha`` for a recovery merge (FIX-A).

    On resume there is no persisted integrated candidate (the six booleans are
    the only recovery truth, FK-29 §29.1.3). The already-verified story branch is
    ff/CAS-merged against a freshly captured ``origin/main`` (the lease base); the
    candidate commit/tree are unused on this path (no re-scan). A failed capture
    escalates fail-closed.
    """
    candidates: list[tuple[ClosureRepo, IntegratedCandidate]] = []
    for repo in repos:
        locked = git.run(repo, "rev-parse", _origin_ref())
        if not locked.ok or not locked.stdout.strip():
            return _escalated(
                ClosureProgress(integrity_passed=True),
                _git_error(repo, "capture locked_sha for recovery merge", locked),
            )
        candidates.append(
            (
                repo,
                IntegratedCandidate(
                    commit_sha="", tree_hash="", locked_sha=locked.stdout.strip()
                ),
            )
        )
    return candidates


def _no_checkpoint(progress: ClosureProgress) -> None:
    """Default no-op checkpoint sink (the caller persists the final progress)."""
    del progress


def _run_standard_block(
    ctx: StoryContext,
    *,
    story_dir: Path,
    repos: tuple[ClosureRepo, ...],
    integrity_gate: IntegrityGate,
    scan_port: PreMergeScanPort | None,
    build_test_port: BuildTestPort | None,
    applicability: MergeApplicability,
    sonar_config: object | None,
    git_backend: GitBackend | None,
    checkpoint: CheckpointSink,
    repo_runners: Mapping[Path, RepoRunners] | None,
) -> MergeBlockResult:
    """Run the locked pre-push green barrier then the saga, order enforced.

    Each step is a fail-closed gate before the next; the order is structural
    (FK-29 §29.1a.3). The barrier owns lock/integrate/clean/capture/tree-bind/CAS
    PER PARTICIPATING REPO (FIX-6, FK-29 §29.1.6: each repo on its own integrated
    candidate); the saga building blocks own push/ff-merge (one merge truth); the
    final ``origin/main`` update is an atomic CAS against the per-repo
    ``locked_sha`` (E4). A single-repo run is the one-element case of the same
    path (no second merge truth).

    FIX-C: each repo is verified against ITS OWN runner pair. When
    ``repo_runners`` maps ``repo.repo_root -> RepoRunners`` the per-repo
    scan/build ports (each bound to that repo's root/ledger/tree) are selected;
    otherwise the single ``scan_port``/``build_test_port`` is the one-repo
    fallback.
    """
    if not repos:
        return _escalated(
            ClosureProgress(),
            "no participating repo for the integrated-candidate barrier",
        )
    git = git_backend or SubprocessGitBackend()

    # Per-repo green barrier (FIX-6): each repo is independently locked,
    # integrated, cleaned, captured, built/scanned and Dim-9 verified, with its
    # CAS pre-check. ANY repo failing escalates the WHOLE block with NO push on
    # any repo (no merge of a partially-verified multi-repo set).
    candidates: list[tuple[ClosureRepo, IntegratedCandidate]] = []
    for repo in repos:
        repo_scan, repo_build = _runners_for(
            repo, repo_runners, scan_port, build_test_port
        )
        wiring_error = _verify_runner_wiring(applicability, repo_scan, repo_build)
        if wiring_error is not None:
            return wiring_error
        verified = _verify_repo_candidate(
            ctx,
            story_dir=story_dir,
            repo=repo,
            git=git,
            integrity_gate=integrity_gate,
            scan_port=repo_scan,
            build_test_port=repo_build,
            applicability=applicability,
            sonar_config=sonar_config,
        )
        if isinstance(verified, MergeBlockResult):
            return verified
        candidates.append((repo, verified))

    # FIX-4/E5: all repos' Dim 1-9 PASSed -> persist ``integrity_passed`` BEFORE
    # the first irreversible side-effect (the push). A crash here resumes the
    # whole atomar block (no intra-lock sub-checkpoint, FK-29 §29.1.3).
    checkpoint(ClosureProgress(integrity_passed=True))

    # All repos green: push + ff-only merge + per-repo ATOMIC CAS main-update via
    # the AG3-009 saga building blocks, with partial-failure rollback (E4).
    return _run_merge_with_cas(ctx, candidates, git, checkpoint)


def _runners_for(
    repo: ClosureRepo,
    repo_runners: Mapping[Path, RepoRunners] | None,
    scan_port: PreMergeScanPort | None,
    build_test_port: BuildTestPort | None,
) -> tuple[PreMergeScanPort | None, BuildTestPort | None]:
    """Select the runner pair bound to ``repo``'s own root (FIX-C).

    Prefers the per-repo :class:`RepoRunners` keyed by ``repo.repo_root`` (each
    pair built with that repo's ledger + tree-hash resolver, so the verification
    binds to ITS root). Falls back to the single ``scan_port``/``build_test_port``
    (the single-repo / one-entry case).
    """
    if repo_runners is not None:
        pair = repo_runners.get(repo.repo_root)
        if pair is not None:
            return pair.scan_port, pair.build_test_port
    return scan_port, build_test_port


def _verify_runner_wiring(
    applicability: MergeApplicability,
    scan_port: PreMergeScanPort | None,
    build_test_port: BuildTestPort | None,
) -> MergeBlockResult | None:
    """Fail closed on a runner-wiring bug (FIX-3); else ``None``.

    FIX-3: Build/Test ALWAYS runs for a code-producing story (a CI facet,
    applicable for both FULL and SONAR_ABSENT). Only the integrated-candidate
    Sonar scan + Dim 9 are skipped when Sonar is declared absent. A missing
    Build/Test runner -- or a missing scan runner under FULL applicability -- is
    a wiring bug, not a declared absence (a declared-absent Sonar is
    SONAR_ABSENT, resolved at the applicability layer).
    """
    if build_test_port is None:
        return _escalated(
            ClosureProgress(),
            "pre-merge Build/Test runner is not wired for a code-producing story "
            "(fail-closed: never merge without a confirmed integrated-candidate "
            "build, FK-29 §29.1a.3 c)",
        )
    if applicability is MergeApplicability.FULL and scan_port is None:
        return _escalated(
            ClosureProgress(),
            "pre-merge scan runner is not wired for a Sonar-applicable (FULL) "
            "story: a declared-absent Sonar resolves to SONAR_ABSENT, not a "
            "missing port; fail-closed",
        )
    return None


def _verify_repo_candidate(  # noqa: PLR0911 -- one fail-closed return per barrier step
    ctx: StoryContext,
    *,
    story_dir: Path,
    repo: ClosureRepo,
    git: GitBackend,
    integrity_gate: IntegrityGate,
    scan_port: PreMergeScanPort | None,
    build_test_port: BuildTestPort | None,
    applicability: MergeApplicability,
    sonar_config: object | None,
) -> IntegratedCandidate | MergeBlockResult:
    """Run the locked green barrier for ONE repo (FK-29 §29.1a.3 a-g, FIX-6).

    Lock (``locked_sha``) -> integrate-latest-main -> clean -> capture the
    integrated-candidate commit/tree -> Build/Test -> integrated-candidate Sonar
    scan (FULL only) -> E3 tree+commit binding -> IntegrityGate Dim 1-9 (verifies
    the fresh attestation) -> CAS/lease pre-check (``origin/main == locked_sha``).
    Returns the verified :class:`IntegratedCandidate` (carrying the per-repo
    ``locked_sha`` for the later CAS), or a fail-closed :class:`MergeBlockResult`
    on ANY barrier step.
    """
    # Steps a-c: lock -> integrate-latest-main -> clean -> capture commit/tree.
    candidate = _prepare_integrated_candidate(git, repo)
    if isinstance(candidate, MergeBlockResult):
        return candidate
    candidate_ref = candidate.to_candidate_ref(branch=_story_branch(ctx.story_id))

    # Build/Test ALWAYS runs (CI facet); a non-None build_test_port is a
    # precondition the caller validated via ``_verify_runner_wiring``.
    assert build_test_port is not None  # noqa: S101 -- validated by the caller (FIX-8)
    build = build_test_port.run(candidate_ref)
    if not build.green:
        return _escalated(
            ClosureProgress(),
            f"[{repo.name}] "
            + (build.reason or "integrated-candidate Build/Test was not green"),
        )

    fresh: FreshAttestation | None = None
    if applicability is MergeApplicability.FULL:
        # Step d (AG3-056): the scan PRODUCES the fresh, commit-bound attestation
        # + the FULL AG3-052 gate outcome (must run before the gate).
        assert scan_port is not None  # noqa: S101 -- validated by the caller (FIX-8)
        scan = scan_port.produce_attestation(candidate_ref)
        # Step e (E3): the scan is bound to EXACTLY the candidate commit + tree.
        binding_error = _verify_scan_binding(scan, candidate)
        if binding_error is not None:
            return _escalated(ClosureProgress(), f"[{repo.name}] {binding_error}")
        fresh = _fresh_attestation(scan, candidate, sonar_config)
    # SONAR_ABSENT: scan + Dim 9 not-applicable; Build/Test ran, merge stays
    # gated (FK-33 §33.6.5 "absent != broken").

    # Step f: the gate VERIFIES the FRESH attestation (Dim 9, FK-35 §35.2.4a),
    # AFTER the scan and BEFORE the push (never re-reads the worktree).
    gate_result = integrity_gate.evaluate(
        story_dir,
        ctx.story_type,
        fresh_attestation=fresh,
    )
    if not gate_result.passed:
        return _escalated(
            ClosureProgress(),
            f"[{repo.name}] IntegrityGate did not pass: {gate_result.failure_reason}",
        )

    # Step g (CAS/lease pre-check): re-assert origin/main == locked_sha.
    cas_error = _verify_main_unchanged(git, repo, candidate.locked_sha)
    if cas_error is not None:
        return _escalated(ClosureProgress(), cas_error)
    return candidate


def _run_fast_block(
    ctx: StoryContext,
    *,
    story_dir: Path,
    repos: tuple[ClosureRepo, ...],
    sanity_port: SanityGatePort,
    git_backend: GitBackend | None,
    checkpoint: CheckpointSink,
    progress: ClosureProgress,
) -> MergeBlockResult:
    """Fast-mode: Sanity-Gate replaces scan + 9-dim IntegrityGate (§29.1a.6).

    The Sanity-Gate + ``locked_sha`` capture run PER participating repo (FIX-6);
    any sanity violation / capture failure escalates the whole block before any
    push.
    """
    if not repos:
        return _escalated(
            ClosureProgress(),
            "no participating repo for the fast-mode sanity gate",
        )
    # FIX-A: a fast resume past the Sanity-Gate (the fast-mode integrity proof)
    # SKIPS the sanity re-evaluation and the push as appropriate, going straight
    # to the ff/CAS merge of the already-pushed branch.
    resume = _resume_merge_only(ctx, repos, progress, git_backend, checkpoint)
    if resume is not None:
        return resume
    git = git_backend or SubprocessGitBackend()
    candidates: list[tuple[ClosureRepo, IntegratedCandidate]] = []
    for repo in repos:
        sanity = sanity_port.evaluate(story_dir, ctx.story_type)
        if not sanity.passed:
            return _escalated(
                ClosureProgress(),
                f"[{repo.name}] "
                + (
                    sanity.reason
                    or "fast-mode sanity gate failed (tests/worktree/rebase)"
                ),
            )
        # Sanity PASS is the fast-mode equivalent of integrity_passed for the
        # merge. Fast still ff-merges; capture the locked_sha so the main update
        # is a CAS. The fast path carries no integrated-candidate scan, so the
        # candidate's commit/tree are not used for binding -- only ``locked_sha``.
        locked = git.run(repo, "rev-parse", _origin_ref())
        if not locked.ok or not locked.stdout.strip():
            return _escalated(
                ClosureProgress(),
                _git_error(repo, "capture locked_sha (origin/main HEAD)", locked),
            )
        candidates.append(
            (
                repo,
                IntegratedCandidate(
                    commit_sha="",
                    tree_hash="",
                    locked_sha=locked.stdout.strip(),
                ),
            )
        )
    # FIX-4/E5: the fast-mode Sanity-Gate PASS is the merge precondition; persist
    # ``integrity_passed`` before the first irreversible push.
    checkpoint(ClosureProgress(integrity_passed=True))
    return _run_merge_with_cas(ctx, candidates, git, checkpoint)


def _fresh_attestation(
    scan: ScanOutcome,
    candidate: IntegratedCandidate,
    sonar_config: object | None,
) -> FreshAttestation | None:
    """Build the Dim-9 :class:`FreshAttestation` from the fresh scan outcome.

    Returns ``None`` only when the scan carried no attestation (a declared-absent
    Sonar run -- the gate then resolves Dim 9 not-applicable via its own
    capability path). When the scan produced an attestation it is passed to the
    gate so Dim 9 verifies exactly it against the candidate commit binding and
    the FK-03 version expectation (no worktree re-read, FK-35 §35.2.4a).
    """
    if scan.attestation is None:
        return None
    from agentkit.config.models import SonarQubeConfig
    from agentkit.governance.integrity_gate.dim9_sonar import FreshAttestation

    config = sonar_config if isinstance(sonar_config, SonarQubeConfig) else None
    return FreshAttestation(
        attestation=scan.attestation,
        expected_main_revision=candidate.commit_sha,
        config=config,
        gate_outcome=scan.gate_outcome,
    )


def _prepare_integrated_candidate(
    git: GitBackend, repo: ClosureRepo
) -> IntegratedCandidate | MergeBlockResult:
    """Lock, integrate latest main, clean, and capture the candidate commit/tree.

    FK-29 §29.1a.3 steps a-c: acquire the merge lock (``locked_sha :=
    origin/main``), fetch + assert ``origin/main == locked_sha`` (lock drift =>
    re-setup), integrate ``origin/main`` into the story branch, ``git clean -xfd``
    + assert an empty ``git status --porcelain``, then capture the integrated
    HEAD commit + tree. Any git failure / merge conflict / dirty tree escalates
    the whole block (atomar, no intra-lock checkpoint).
    """
    locked = git.run(repo, "rev-parse", _origin_ref())
    if not locked.ok or not locked.stdout.strip():
        return _escalated(
            ClosureProgress(),
            _git_error(repo, "capture locked_sha (origin/main HEAD)", locked),
        )
    locked_sha = locked.stdout.strip()

    fetch = git.run(repo, "fetch", "origin", _BASE_BRANCH)
    if not fetch.ok:
        return _escalated(
            ClosureProgress(), _git_error(repo, "fetch origin main", fetch)
        )
    refetched = git.run(repo, "rev-parse", _origin_ref())
    if not refetched.ok or refetched.stdout.strip() != locked_sha:
        return _escalated(
            ClosureProgress(),
            (
                "merge-lock drift: origin/main moved between lock acquisition and "
                "fetch -- re-setup the block on a fresh locked_sha (FK-29 §29.1a.3)"
            ),
        )

    integrate = git.run(repo, "merge", "--no-ff", "--no-edit", _origin_ref())
    if not integrate.ok:
        # Leave no half-merge behind, then escalate (main-drift => Remediation-Loop
        # in the concept; from the barrier's view a non-integrable candidate is a
        # fail-closed block, FK-29 §29.1a.4).
        git.run(repo, "merge", "--abort")
        return _escalated(
            ClosureProgress(),
            _git_error(repo, "integrate origin/main into story branch", integrate),
        )

    clean = git.run(repo, "clean", "-xfd")
    if not clean.ok:
        return _escalated(
            ClosureProgress(), _git_error(repo, "clean workspace (git clean -xfd)", clean)
        )
    status = git.run(repo, "status", "--porcelain")
    if not status.ok:
        return _escalated(
            ClosureProgress(), _git_error(repo, "verify clean workspace", status)
        )
    if status.stdout.strip():
        return _escalated(
            ClosureProgress(),
            "integrated workspace is not clean after integrate-main (uncommitted "
            "changes present) -- the scan tree would not be reproducible",
        )

    commit = git.run(repo, "rev-parse", "HEAD")
    tree = git.run(repo, "rev-parse", "HEAD^{tree}")
    if not commit.ok or not commit.stdout.strip():
        return _escalated(
            ClosureProgress(), _git_error(repo, "capture candidate commit", commit)
        )
    if not tree.ok or not tree.stdout.strip():
        return _escalated(
            ClosureProgress(), _git_error(repo, "capture candidate tree", tree)
        )
    return IntegratedCandidate(
        commit_sha=commit.stdout.strip(),
        tree_hash=tree.stdout.strip(),
        locked_sha=locked_sha,
    )


def _verify_scan_binding(
    scan: ScanOutcome, candidate: IntegratedCandidate
) -> str | None:
    """Verify the scan bound to EXACTLY the candidate commit + tree (E3).

    FK-29 §29.1a.3 step 5 / Codex-ERROR-2/-4: assert ``scan.produced`` AND
    ``scan.commit_sha == candidate.commit_sha`` AND ``scan.tree_hash ==
    candidate.tree_hash`` (the Sonar-proven revision IS the revision about to be
    merged). Returns an error string on any failure, else ``None``. All checks
    are fail-closed -- a non-produced / unbound / mismatched scan never merges.
    """
    if not scan.produced:
        return (
            "integrated-candidate scan did not produce a bound attestation"
            f"{f': {scan.reason}' if scan.reason else ''} "
            "(fail-closed before the gate, FK-29 §29.1a.3)"
        )
    if scan.commit_sha is None or scan.tree_hash is None:
        return (
            "integrated-candidate scan produced an attestation with no commit/tree "
            "binding -- cannot prove scan == merge (fail-closed, no sham verification)"
        )
    if scan.commit_sha != candidate.commit_sha:
        return (
            "commit_sha(scan) != commit_sha(merge): the attested commit "
            f"{scan.commit_sha!r} is not the integrated-candidate commit "
            f"{candidate.commit_sha!r} about to be merged (E3, FK-29 §29.1a.3)"
        )
    if scan.tree_hash != candidate.tree_hash:
        return (
            "tree_hash(scan) != tree_hash(merge): the attested tree "
            f"{scan.tree_hash!r} is not the integrated-candidate tree "
            f"{candidate.tree_hash!r} about to be merged (FK-29 §29.1a.3 step 5)"
        )
    return None


def _verify_main_unchanged(
    git: GitBackend, repo: ClosureRepo, locked_sha: str
) -> str | None:
    """Re-assert ``origin/main == locked_sha`` before the push (CAS/lease guard).

    FK-29 §29.1a.3 step 7: ``main`` is ff-updated only if the remote ``main``
    still stands on ``locked_sha``. If it drifted since the lock, re-setup the
    block rather than merge against a stale base. This pre-read narrows the race;
    the atomic lease at push time (E4) closes it. Returns an error string on
    drift / a failed re-read, else ``None``.
    """
    git.run(repo, "fetch", "origin", _BASE_BRANCH)
    current = git.run(repo, "rev-parse", _origin_ref())
    if not current.ok or not current.stdout.strip():
        return _git_error(repo, "re-read origin/main for CAS", current)
    if current.stdout.strip() != locked_sha:
        return (
            "compare-and-swap failed: origin/main moved away from locked_sha "
            f"{locked_sha!r} (now {current.stdout.strip()!r}) -- another merge "
            "landed; re-setup the block (FK-29 §29.1a.3 step 7)"
        )
    return None


def _origin_ref() -> str:
    """The fully-qualified remote base ref the barrier locks/integrates against."""
    return f"origin/{_BASE_BRANCH}"


def _story_branch(story_id: str) -> str:
    """The story branch name the candidate scan/build/push run on (FK-12 §12.4)."""
    return f"story/{story_id}"


def _run_merge_with_cas(
    ctx: StoryContext,
    candidates: list[tuple[ClosureRepo, IntegratedCandidate]],
    git: GitBackend,
    checkpoint: CheckpointSink,
    *,
    base_progress: ClosureProgress | None = None,
    skip_push: bool = False,
) -> MergeBlockResult:
    """Push story branches, ff-merge, then per-repo ATOMIC CAS-update main (E4/FIX-6).

    Consumes the AG3-009 saga building blocks (one merge truth -- no second merge
    implementation): :func:`push_story_branches` (all repos) then
    :func:`local_ff_merge_with_rollback` (all repos, with the saga's local
    rollback of prior repos on a merge failure). The final ``origin/main`` update
    is a PER-REPO atomic compare-and-swap against each repo's own ``locked_sha``
    via ``git push --force-with-lease=main:<locked_sha_repo> origin main`` (E4):
    a repo's push SUCCEEDS only if its remote ``main`` is still at its
    ``locked_sha``. A single-repo run is the one-element case (no second path).

    FIX-B (all-or-nothing at the REMOTE level): on the FIRST repo whose CAS is
    rejected, every repo whose remote ``main`` was ALREADY advanced by this run is
    rolled back at the REMOTE (``git push --force-with-lease=main:<just_pushed_sha>
    origin <pre_merge_sha>:main``) AND its local ff-merge is reset, then the block
    escalates. After a failure NO repo's ``origin/main`` may carry the story merge
    -- NEVER a forced overwrite of a concurrent advance (FK-29 §29.1.5 ff_only;
    ``--force-with-lease`` to the exact sha is a CAS, not a history rewrite).

    FIX-A (recovery resume): when ``skip_push`` the story branches are already
    pushed (a ``story_branch_pushed`` resume), so the push step is skipped and the
    block goes straight to the ff/CAS merge of the already-pushed verified branch.

    Checkpoint timing (E5): ``story_branch_pushed`` is set ONLY after the pushes
    succeeded on all repos; ``merge_done`` ONLY after the per-repo CAS main-update
    succeeded on ALL repos.
    """
    repos = tuple(repo for repo, _candidate in candidates)
    base = base_progress or ClosureProgress(integrity_passed=True)

    if skip_push:
        pushed_progress = base.model_copy(
            update={"integrity_passed": True, "story_branch_pushed": True}
        )
    else:
        push = push_story_branches(repos, ctx.story_id, backend=git)
        if not push.success:
            return MergeBlockResult(
                status=MergeBlockStatus.ESCALATED,
                progress=base,  # push failed -> story_branch_pushed stays false
                errors=tuple(push.errors),
            )
        pushed_progress = base.model_copy(
            update={"integrity_passed": True, "story_branch_pushed": True}
        )
        # FIX-4/E5: the story-branch push landed (resumable) -> persist
        # ``story_branch_pushed`` IMMEDIATELY, before the merge/CAS side-effects.
        checkpoint(pushed_progress)

    merge = local_ff_merge_with_rollback(
        repos,
        ctx.story_id,
        base=_BASE_BRANCH,
        progress=pushed_progress,
        backend=git,
    )
    if not merge.success:
        return MergeBlockResult(
            status=MergeBlockStatus.ESCALATED,
            progress=pushed_progress,  # local ff-merge failed -> no merge_done
            errors=tuple(merge.errors),
        )

    # Per-repo ATOMIC CAS main-update (E4). Track which remotes this run already
    # advanced (and to which sha) so a later repo's failure can roll the remote
    # main back (FIX-B: no partial cross-repo REMOTE merge survives a failure).
    pushed_remotes: list[tuple[ClosureRepo, str]] = []
    for repo, candidate in candidates:
        # FIX-B edge (fail-closed): a remote may be advanced ONLY if its
        # just-pushed sha is known and recorded in ``pushed_remotes`` for rollback
        # coverage. If the post-merge local HEAD cannot be read, pushing the remote
        # would advance an ``origin/main`` that a LATER repo's failure could never
        # roll back (no leased sha) -- a real fail-open. So require the sha BEFORE
        # any push: an unknown post-merge HEAD rolls back every local merge so far
        # and escalates, with NO remote push for this repo.
        new_main = _local_head(git, repo)
        if new_main is None:
            rollback_errors = _rollback_after_cas_failure(
                git, candidates, pushed_remotes, merge.pre_merge_shas
            )
            return MergeBlockResult(
                status=MergeBlockStatus.ESCALATED,
                progress=pushed_progress,  # no remote pushed -> merge_done stays false
                errors=(
                    f"[{repo.name}] post-merge HEAD unreadable after a successful "
                    "local ff-merge: refusing the remote CAS push because its "
                    "just-pushed sha would be unknown and unrollbackable "
                    "(fail-closed, FK-29 §29.1.5 -- no remote advance without "
                    "rollback coverage)",
                    *rollback_errors,
                ),
            )
        cas_error = _cas_push_main(git, repo, candidate.locked_sha)
        if cas_error is None:
            pushed_remotes.append((repo, new_main))
            continue
        rollback_errors = _rollback_after_cas_failure(
            git, candidates, pushed_remotes, merge.pre_merge_shas
        )
        return MergeBlockResult(
            status=MergeBlockStatus.ESCALATED,
            progress=pushed_progress,  # a CAS push failed -> merge_done stays false
            errors=(cas_error, *rollback_errors),
        )

    merged_progress = pushed_progress.model_copy(update={"merge_done": True})
    # FIX-4/E5: the per-repo CAS main-update succeeded on ALL repos -> persist
    # ``merge_done`` IMMEDIATELY (before teardown, a non-irreversible cleanup), so
    # a crash during teardown resumes from ``merge_done=true`` (no re-merge).
    checkpoint(merged_progress)
    teardown_worktrees(repos, ctx.story_id, backend=git)
    return MergeBlockResult(status=MergeBlockStatus.MERGED, progress=merged_progress)


def _local_head(git: GitBackend, repo: ClosureRepo) -> str | None:
    """Read the local ``HEAD`` sha after the ff-merge (the sha pushed to main).

    Used as the ``--force-with-lease`` base when rolling a REMOTE back (FIX-B):
    the remote rollback leases against EXACTLY the sha this run just wrote, so it
    never clobbers a concurrent third-party advance. Returns ``None`` on a read
    failure; the caller then fails closed and refuses the remote CAS push for that
    repo (a remote is advanced ONLY if its just-pushed sha is known and recorded
    in ``pushed_remotes`` for rollback coverage), rolling back every local merge so
    far instead of leaving an unrollbackable ``origin/main`` advance.
    """
    head = git.run(repo, "rev-parse", "HEAD")
    if not head.ok or not head.stdout.strip():
        return None
    return head.stdout.strip()


def _cas_push_main(git: GitBackend, repo: ClosureRepo, locked_sha: str) -> str | None:
    """Atomically update ``origin/main`` only if it is still at ``locked_sha`` (E4).

    ``git push --force-with-lease=main:<locked_sha> origin main``: the remote
    accepts the push ONLY when its ``main`` still points at ``locked_sha`` (the
    exact expected sha). A concurrent advance makes git reject the lease -> the
    caller escalates + rolls back (never a clobber). Returns an error string on
    rejection / failure, else ``None`` (the update landed).
    """
    lease = f"--force-with-lease={_BASE_BRANCH}:{locked_sha}"
    result = git.run(repo, "push", lease, "origin", _BASE_BRANCH)
    if result.ok:
        return None
    return (
        "atomic main-update CAS rejected (origin/main no longer at locked_sha "
        f"{locked_sha!r} -- a concurrent advance landed): "
        f"{_git_error(repo, 'push --force-with-lease origin main', result)} "
        "(fail-closed escalation + rollback, never a clobber; FK-29 §29.1.5)"
    )


def _rollback_after_cas_failure(
    git: GitBackend,
    candidates: list[tuple[ClosureRepo, IntegratedCandidate]],
    pushed_remotes: list[tuple[ClosureRepo, str]],
    pre_merge_shas: Mapping[str, str],
) -> tuple[str, ...]:
    """Undo a partial cross-repo merge after a CAS failure (FIX-B + FIX-6).

    Two levels, all-or-nothing:

    1. REMOTE (FIX-B): every repo whose ``origin/main`` this run ALREADY advanced
       is reset back to its pre-merge sha with
       ``git push --force-with-lease=main:<just_pushed_sha> origin <pre_merge>:main``
       -- a CAS leased against the exact sha we wrote (never a clobber of a third
       party). After this NO repo's ``origin/main`` carries the story merge.
    2. LOCAL (FIX-6): every local ff-merge is reset to its pre-merge sha so a
       re-setup starts from a clean base on every participating repo.

    Returns the aggregated rollback error messages (empty on full success).
    """
    errors: list[str] = []
    for repo, just_pushed_sha in pushed_remotes:
        errors.extend(
            _rollback_remote_main(
                git, repo, just_pushed_sha, pre_merge_shas.get(repo.name)
            )
        )
    for repo, _candidate in candidates:
        errors.extend(
            _rollback_one_local_merge(git, repo, pre_merge_shas.get(repo.name))
        )
    return tuple(errors)


def _rollback_remote_main(
    git: GitBackend,
    repo: ClosureRepo,
    just_pushed_sha: str,
    pre_merge_sha: str | None,
) -> tuple[str, ...]:
    """Reset ONE repo's already-advanced ``origin/main`` to its pre-merge sha (FIX-B).

    ``git push --force-with-lease=main:<just_pushed_sha> origin <pre_merge>:main``:
    the lease is the sha THIS run wrote, so the reset lands only if no third party
    advanced main further (else it fails closed, surfaced as an error -- never a
    blind clobber). Empty tuple on success.
    """
    if not pre_merge_sha:
        return (
            f"[{repo.name}] cannot roll back remote main: pre_merge_sha unknown "
            "(partial cross-repo merge may survive -- manual recovery, FIX-B)",
        )
    lease = f"--force-with-lease={_BASE_BRANCH}:{just_pushed_sha}"
    refspec = f"{pre_merge_sha}:{_BASE_BRANCH}"
    result = git.run(repo, "push", lease, "origin", refspec)
    if not result.ok:
        return (
            _git_error(repo, "rollback remote main (push --force-with-lease)", result)
            + " (partial cross-repo REMOTE merge may survive -- escalate, FIX-B)",
        )
    return ()


def _rollback_one_local_merge(
    git: GitBackend, repo: ClosureRepo, pre_merge_sha: str | None
) -> tuple[str, ...]:
    """Roll ONE repo's local ff-merge back to its pre-merge sha (empty on success)."""
    if not pre_merge_sha:
        return (f"[{repo.name}] cannot roll back local ff-merge: pre_merge_sha unknown",)
    checkout = git.run(repo, "checkout", _BASE_BRANCH)
    if not checkout.ok:
        return (_git_error(repo, f"rollback checkout {_BASE_BRANCH}", checkout),)
    reset = git.run(repo, "reset", "--hard", pre_merge_sha)
    if not reset.ok:
        return (_git_error(repo, "rollback reset --hard", reset),)
    return ()


def _escalated(progress: ClosureProgress, reason: str) -> MergeBlockResult:
    """Build an ESCALATED block result with a single reason."""
    return MergeBlockResult(
        status=MergeBlockStatus.ESCALATED,
        progress=progress,
        errors=(reason,),
    )


def _git_error(repo: ClosureRepo, action: str, result: object) -> str:
    """Build a uniform fail-closed message for a failed barrier git command."""
    stderr = getattr(result, "stderr", "") or ""
    code = getattr(result, "returncode", "?")
    detail = stderr.strip() or f"exit {code}"
    return f"[{repo.name}] {action} failed: {detail}"


__all__ = [
    "BuildTestOutcome",
    "BuildTestPort",
    "CandidateRef",
    "ClosureRepo",
    "IntegratedCandidate",
    "MergeApplicability",
    "MergeBlockResult",
    "MergeBlockStatus",
    "PreMergeScanPort",
    "RepoRunners",
    "SanityGatePort",
    "SanityOutcome",
    "ScanOutcome",
    "run_pre_merge_and_merge_block",
]
