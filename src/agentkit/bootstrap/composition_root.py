"""Composition-Root: explizite App-Initialisierung ohne ``__init__.py``-Side-Effects.

Bietet Builder-Funktionen, die in der App-Initialisierung (z. B. CLI,
Pipeline-Engine-Hochfahren, Test-Fixture) aufgerufen werden. Kein
Modul-Import-Side-Effect; jeder Builder ist explizit zu rufen.

Quelle:
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.2`` —
  Composition-Root-Variante
- ``concept/_meta/bc-cut-decisions.md §BC 8 artifacts`` — Producer-Registry
- AK3-Schnitt-Disziplin: kein operativer Code in ``__init__.py``
- AG3-026 §Station 5 -- ``build_verify_system`` ergaenzt.
- AG3-031 Pass-5 §E9 -- ``build_integrity_gate``, ``build_setup_preflight_gate``
  ergaenzt; direkte Runtime-Imports aus ``governance.integrity_gate`` und
  ``governance.setup_preflight_gate.phase`` sind damit in den Composition-Root
  verlagert (DI-Muster).
- AG3-035 -- ``build_projection_accessor`` ergaenzt (FK-69 ProjectionAccessor).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactManager,
    EnvelopeValidator,
    ProducerRegistry,
)
from agentkit.exploration.register import register_exploration_producers
from agentkit.implementation.register import register_implementation_producers
from agentkit.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.closure.merge_sequence import (
        MergeApplicability,
        PreMergeScanPort,
        RepoRunners,
        SanityGatePort,
    )
    from agentkit.closure.multi_repo_saga import GitBackend as RepoGitBackend
    from agentkit.closure.phase import (
        ClosurePhaseHandler,
        ClosureProgressStore,
        ModeLockReleasePort,
    )
    from agentkit.closure.post_merge_finalization.finalization import (
        DocFidelityFeedbackPort,
        GuardDeactivationPort,
        VectorDbSyncPort,
    )
    from agentkit.exploration.phase import ExplorationPhaseHandler
    from agentkit.exploration.review import ExplorationReview
    from agentkit.failure_corpus import FailureCorpus
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.governance.integrity_gate.dim9_sonar import SonarDimensionPort
    from agentkit.governance.repository import SetupContextRepository
    from agentkit.governance.setup_preflight_gate.phase import SetupPhaseHandler
    from agentkit.kpi_analytics import KpiAnalytics
    from agentkit.requirements_coverage.contract import CoverageVerdict
    from agentkit.requirements_coverage.top import (
        RequirementsCoverage as RequirementsCoverageProto,
    )
    from agentkit.skills import Skills
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.story_model import ChangeImpact
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.telemetry.projection_accessor import ProjectionAccessor
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient
    from agentkit.verify_system.pre_merge_runner.contract import BuildTestPort
    from agentkit.verify_system.qa_cycle.invalidation import (
        ArtifactInvalidationEvent,
        ArtifactInvalidationSink,
    )
    from agentkit.verify_system.review_completion import (
        ReviewCompletionEvent,
        ReviewCompletionSink,
    )
    from agentkit.verify_system.sonarqube_gate.port import SonarGateInputPort
    from agentkit.verify_system.structural.checker import AreGateProvider
    from agentkit.verify_system.structural.checks import (
        BuildTestEvidence,
        BuildTestEvidencePort,
    )
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence
    from agentkit.verify_system.system import VerifySystem


def build_producer_registry() -> ProducerRegistry:
    """Erzeugt eine frische ``ProducerRegistry`` und ruft alle bekannten
    BC-Init-Hooks auf.

    Current state: ``register_exploration_producers`` (AG3-045,
    ``ArtifactClass.ENTWURF``), ``register_implementation_producers`` (AG3-044,
    ``ArtifactClass.HANDOVER``), ``register_verify_producers`` (AG3-023 +
    AG3-044 ``ArtifactClass.ADVERSARIAL_TEST_SANDBOX``) and
    ``register_prompt_runtime_producers`` (AG3-015, FK-44 §44.6 --
    ``ArtifactClass.PROMPT_AUDIT``) are wired. Further BC-init hooks
    (telemetry, governance, closure ...) are added analogously in their
    follow-up stories.

    Returns:
        Eine ``ProducerRegistry`` mit allen heute bekannten Producern.

    Notes:
        Reihenfolge der Init-Hooks ist deterministisch (BC-alphabetisch
        bzw. Capability-Reihenfolge). Jeder Hook ist idempotent.
    """
    from agentkit.exploration.review.register import (
        register_exploration_review_producers,
    )

    registry = ProducerRegistry()
    register_exploration_producers(registry)
    register_exploration_review_producers(registry)
    register_implementation_producers(registry)
    register_prompt_runtime_producers(registry)
    register_verify_producers(registry)
    return registry


def build_artifact_manager(store_dir: Path) -> ArtifactManager:
    """Erzeugt einen vollstaendig verdrahteten ``ArtifactManager``.

    Composition-Root fuer den Artefakt-Schreib-/Lese-Pfad: bindet die
    Producer-Registry, den Envelope-Validator und das
    StateBackend-Repository zusammen. Konsument-BCs (z. B.
    ``verify_system.artifacts``) erhalten den Manager via DI und kennen
    die Repository-Implementierung nicht.

    Args:
        store_dir: Basisverzeichnis des State-Backends (SQLite legt
            unter ``store_dir/.agentkit/...`` an; Postgres ignoriert
            den Pfad).

    Returns:
        ``ArtifactManager`` mit allen verify-Producern registriert.
    """
    registry = build_producer_registry()
    validator = EnvelopeValidator(registry)
    repository = StateBackendArtifactRepository(store_dir)
    return ArtifactManager(repository, validator)


def build_kpi_analytics(store_dir: Path) -> KpiAnalytics:
    """Wire a ``KpiAnalytics`` facade onto the real FactStore (AG3-038).

    Composition-Root for the analytics read path: binds the StateBackend fact
    repository onto the FactStore and injects it into ``KpiAnalytics``, so
    ``get_dashboard_view`` reads the canonical fact tables (FK-62 §62.3). The
    consumer BC knows only the ``FactRepository`` Protocol (AC8); the concrete
    adapter is bound here. ``refresh_worker`` stays ``None`` until the follow-up
    RefreshWorker story, so ``refresh_analytics`` returns SKIPPED (FAIL-CLOSED).

    Args:
        store_dir: State-backend base dir (SQLite stores under
            ``store_dir/.agentkit/...``; Postgres ignores it).

    Returns:
        A ``KpiAnalytics`` facade with a live FactStore read path.
    """
    from agentkit.kpi_analytics import KpiAnalytics, KpiCatalog
    from agentkit.kpi_analytics.fact_store import FactStore
    from agentkit.state_backend.store.fact_repository import (
        StateBackendFactRepository,
    )

    fact_store = FactStore(StateBackendFactRepository(store_dir))
    return KpiAnalytics(catalog=KpiCatalog(), fact_store=fact_store)


def build_exploration_review(
    ctx: StoryContext,
    story_dir: Path,
    *,
    llm_client: LlmClient | None = None,
) -> ExplorationReview:
    """Wire the three-stage exploration exit-gate (AG3-046, FK-23 §23.5).

    Composition root for :class:`ExplorationReview`: builds the Stage 1
    document-fidelity checker and the Stage 2a design-review runner over the
    Layer-2 :class:`StructuredEvaluator`, the
    :class:`PromptRuntimeMaterializer` (FK-44 §44.4.2 prompt source) and the
    :class:`ArtifactReviewResultSink` (QA-artifact persistence). Stage 2b
    design-challenge is wired as ``None`` (mandate-gated activation is AG3-047).

    The LLM transport defaults to the fail-closed :class:`FailClosedLlmClient`
    (no LLM pool is wired productively yet, FK-11 follow-up): every gate stage
    then FAILS CLOSED at the LLM boundary rather than silently approving (NO
    ERROR BYPASSING). Once the pool adapter exists the caller injects it here.

    Args:
        ctx: The story context for the run (carries ``project_root`` /
            ``story_id``; required by the prompt materializer).
        story_dir: Story working directory (run-scope + artifact store root).
        llm_client: Optional Layer-2 LLM transport. ``None`` => the fail-closed
            :class:`FailClosedLlmClient` (gate fails closed until a pool exists).

    Returns:
        A wired :class:`ExplorationReview`.
    """
    from agentkit.exploration.review.design_review import DesignReviewRunner
    from agentkit.exploration.review.doc_fidelity import DocFidelityChecker
    from agentkit.exploration.review.persistence import ArtifactReviewResultSink
    from agentkit.exploration.review.review import ExplorationReview as _Review
    from agentkit.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

    manager = build_artifact_manager(story_dir)
    client = llm_client or FailClosedLlmClient()
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=story_dir,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
    )
    evaluator = StructuredEvaluator(client, materializer)
    sink = ArtifactReviewResultSink(manager)
    return _Review(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=manager,
    )


def build_exploration_phase_handler(
    story_dir: Path,
    *,
    review: ExplorationReview | None = None,
) -> ExplorationPhaseHandler:
    """Wire the registrable ``ExplorationPhaseHandler`` surface (AG3-045/AG3-046).

    Composition root for the exploration-phase handler (BC 5,
    ``exploration-and-design``): wires the bloodgroup-A handler to the
    state-backend adapter that fulfils the two boundary ports
    (``RunScopeResolver`` + ``ChangeFrameReader``). The A-core therefore does
    NOT import ``state_backend.store`` itself and does no direct filesystem I/O
    (ARCH-22 / ARCH-31).

    Per PO decision 2026-06-05 ("Option Y") the handler produces NO change-frame:
    it consumes / validates the change-frame persisted by the exploration worker
    (AG3-055). Without a valid change-frame the phase is fail-closed (ESCALATED).

    AG3-046: when a valid change-frame is present the handler runs the three-stage
    exit-gate (:class:`ExplorationReview`). The review is built per-run (it needs
    the ``StoryContext`` for the prompt materializer) via
    :func:`build_exploration_review`; the productive per-run injection +
    ``PhaseHandlerRegistry`` registration is owned by AG3-054. ``review=None``
    (the default here) fails closed: a valid frame with no review wired returns
    ``FAILED`` (never auto-APPROVE, NO ERROR BYPASSING).

    Args:
        story_dir: Story working directory (bound ``FlowExecution`` + the read
            surface root). Passed to the adapter's ``ArtifactManager`` and the
            handler config.
        review: Optional pre-built three-stage exit-gate. ``None`` fails closed
            on a valid change-frame (AG3-054 injects the per-run review).

    Returns:
        A wired ``ExplorationPhaseHandler``.
    """
    from agentkit.exploration.phase import (
        ExplorationConfig,
    )
    from agentkit.exploration.phase import (
        ExplorationPhaseHandler as _ExplorationPhaseHandler,
    )
    from agentkit.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )

    adapter = StateBackendExplorationChangeFrameAdapter(
        build_artifact_manager(story_dir)
    )
    return _ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        review=review,
        config=ExplorationConfig(story_dir=story_dir),
    )


def build_verify_system(
    store_dir: Path,
    *,
    max_major_findings: int = 0,
    max_feedback_rounds: int | None = None,
    sonar_gate_port: SonarGateInputPort | None = None,
    layer2_llm_client: LlmClient | None = None,
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None,
    structural_build_test_port: BuildTestEvidencePort | None = None,
    structural_are_provider: AreGateProvider | None = None,
) -> VerifySystem:
    """Erzeugt einen vollstaendig verdrahteten ``VerifySystem``.

    Composition-Root fuer die QA-Subflow-Top-Surface (AG3-026):
    instanziiert alle fuenf Sub-Komponenten und verdrahtet einen echten
    ``ArtifactManager`` (inkl. ProducerRegistry) als Persistenz-Facade.

    AG3-035 (echter Drift-Fix): verdrahtet zusaetzlich den
    ``StateBackendVerifyStoryContextAdapter`` als ``story_context_port``, damit
    ``verify_system`` den ``StoryContext`` ueber einen Port aufloest statt via
    direktem ``state_backend.store``-Import (BC-Topologie).

    AG3-052 (FK-33 §33.6): der ``sonarqube_gate``-Andockpunkt nutzt einen
    ``SonarGateInputPort``. Bei ``sonarqube.available == true`` reicht der
    Aufrufer (Pipeline-Engine) den produktiven
    :class:`ConfiguredSonarGateInputPort` ueber ``sonar_gate_port`` ein (gebaut
    via :func:`build_sonar_gate_port` mit den per-Run aufgeloesten
    Koordinaten); ohne Injektion bleibt der Absent-Default-Port aktiv
    (``available == false`` => Stage SKIP). So bleibt ein
    konfiguriert-aber-unerreichbares Sonar fail-closed, ohne dass dieser
    Builder die per-Story-Koordinaten kennen muss.

    Args:
        store_dir: Basisverzeichnis des State-Backends. Wird an
            ``build_artifact_manager`` durchgereicht.
        max_major_findings: Schwellenwert fuer die PolicyEngine (Anzahl
            tolerierter MAJOR-Findings; 0 = jedes MAJOR blockiert).
        max_feedback_rounds: Ceiling fuer den Subflow-internen Remediation-Loop
            (FK-03 §3.4.2 / FK-38, ``policy.max_feedback_rounds``). Der Aufrufer
            (Phase-Handler) loest ihn aus der Pipeline-Config auf und reicht ihn
            ein; ``None`` => Controller-Default (3). Der
            ``RemediationLoopController`` ist der harte Owner der Schranke
            (nicht ueberspringbar, NO ERROR BYPASSING).
        sonar_gate_port: Optionaler produktiver ``SonarGateInputPort``
            (FK-33 §33.6). ``None`` => Absent-Default-Port.
        layer2_llm_client: Optionaler ``LlmClient`` (AG3-043 E6, FK-27 §27.5).
            ``None`` => der Composition-Root verdrahtet den fail-closed
            :class:`FailClosedLlmClient`, damit Layer 2 im Default-Pfad WIRKLICH
            laeuft (drei parallele LLM-Bewertungen) statt still auf die
            deterministischen Stub-Reviewer zurueckzufallen. Solange die
            konkrete LLM-Pool-Auswahl (FK-11, Folge-Story) fehlt, schlaegt der
            fail-closed Client jeden ``complete``-Aufruf fehl -> Layer 2
            FAIL-CLOSED (kein stiller Skip, FK-34 §34.5.1). Sobald der
            Pool-Adapter existiert, reicht der Aufrufer ihn hier ein.

    Returns:
        ``VerifySystem`` mit allen fuenf Sub-Komponenten und einem
        vollstaendig verdrahteten ``ArtifactManager`` sowie einem produktiv
        verdrahteten Layer-2-LLM-Client (E6).
    """
    from agentkit.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.verify_system.structural.checker import FULL_STAGE_REGISTRY
    from agentkit.verify_system.system import VerifySystem

    manager = build_artifact_manager(store_dir)
    resolved_llm_client = layer2_llm_client or FailClosedLlmClient()
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        max_feedback_rounds=max_feedback_rounds,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        sonar_gate_port=sonar_gate_port,
        invalidation_sink=build_artifact_invalidation_sink(store_dir),
        # FIX-C (FK-27 §27.4.3 / §27.5.5): after each Layer-2 review artefact
        # write the QA-subflow emits a canonical ``llm_call_complete`` event
        # (per reviewer role) so ``guard.multi_llm`` counts a COMPLETED review.
        # Without this productive sink the count is always 0 and the gate is
        # inert/over-blocking. The telemetry import lives here, not in the BC.
        review_completion_sink=build_review_completion_sink(store_dir),
        layer2_llm_client=resolved_llm_client,
        fast_test_runner=fast_test_runner,
        # AG3-042: the PRODUCTIVE path wires the full FK-27 §27.4 Layer-1 stage
        # catalogue (StructuralChecker + PolicyEngine fail-closed check).
        stage_registry=FULL_STAGE_REGISTRY,
        # AG3-042: the FK-27 §27.4.3 recurring guards count canonical
        # ``execution_events`` via a port so verify-system never imports
        # ``state_backend.store`` directly (BC-topology, AG3-035).
        structural_telemetry_port=_StateBackendTelemetryEventCountPort(),
        # FIX-3 (FK-33 §33.5): the BLOCKING branch/commit/push/secrets/impact
        # checks decide on INDEPENDENT system git evidence, wired here as the
        # productive subprocess-git provider (verify-system stays free of
        # subprocess; the import lives in this composition root). NEVER the
        # worker manifest.
        structural_change_evidence_port=_SubprocessGitChangeEvidenceProvider(),
        # FIX-1: the REAL build/test evidence port + the real ARE provider need
        # per-run config (the project ``ci`` stanza / ``features.are``) the
        # builder does not have, so the per-run caller (ImplementationPhaseHandler)
        # resolves and injects them via :func:`build_structural_build_test_port`
        # / :func:`build_structural_are_provider`. Absent here => the fail-closed
        # default ports (build/test BLOCKING fail, ARE stage not planned), so a
        # bare build_verify_system never over-blocks a story with a fabricated
        # green NOR silently disables ARE.
        structural_build_test_port=structural_build_test_port,
        structural_are_provider=structural_are_provider,
    )


@dataclass(frozen=True)
class _StateBackendTelemetryEventCountPort:
    """State-backed ``TelemetryEventQueryPort`` (FK-27 §27.4.3, AG3-042).

    Counts canonical ``execution_events`` of a given type for a story via the
    state-backend facade, scoped to ``(project_key, story_id, run_id)`` per
    FK-33 §33.3.2 -- a recurring-guard count must not bleed across projects or
    across prior runs of the same story. When the caller does not supply a
    ``run_id`` the adapter resolves the ACTIVE run for ``story_dir`` (via the
    persisted run scope) so a prior, reset, or replayed run never counts toward
    the current guard. The ``state_backend.store`` import lives HERE (the
    composition root), not in ``verify_system`` (BC-topology, AG3-035). Counts
    fail soft to ``0`` on any backend error so the BLOCKING guards stay
    fail-closed (a missing/unreadable event store yields ``0`` -> FAIL).
    """

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Count matching canonical ``execution_events`` (``0`` on error).

        Scoped to ``(project_key, story_id, run_id)`` (FK-33 §33.3.2). When
        ``run_id`` is ``None`` the active run for ``story_dir`` is resolved so
        a prior run's events are excluded. When ``role`` is given, only events
        whose ``payload['role']`` matches are counted (FK-27 §27.4.3 Gate 2:
        ``llm_call_complete`` events carry the reviewer role in their payload).
        """
        from agentkit.state_backend.store import load_execution_events

        resolved_run_id = run_id or self._resolve_active_run_id(story_dir)
        if resolved_run_id is None:
            # FIX-B (FK-33 §33.3.2 run scope, fail-CLOSED): when the run scope
            # cannot be resolved we MUST NOT query unscoped. A
            # ``load_execution_events(..., run_id=None)`` would count across ALL
            # runs of the story, so the must-have-events guards
            # (``guard.review_compliance`` / ``guard.multi_llm`` /
            # ``guard.llm_reviews``) could PASS on a prior run's telemetry
            # (fail-open). Returning 0 makes every BLOCKING must-have-events
            # guard FAIL closed on an unresolvable run scope, and never lets
            # ``guard.no_violations`` free-pass on stale events: a
            # ``count_events`` of 0 there means "no integrity_violation visible
            # for this run", which is the only honest reading when the run scope
            # is unknown (the violation, if any, lives under a resolvable run).
            return 0
        try:
            events = load_execution_events(
                story_dir,
                project_key=project_key,
                story_id=story_id,
                run_id=resolved_run_id,
                event_type=event_type,
            )
        except Exception:  # noqa: BLE001 -- fail-soft to 0 (fail-closed guard).
            return 0
        if role is None:
            return len(events)
        return sum(
            1
            for event in events
            if isinstance(getattr(event, "payload", None), dict)
            and event.payload.get("role") == role
        )

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        """Whether the active run scope for ``story_dir`` resolves (FIX-B).

        FK-33 §33.3.2: ``guard.no_violations`` PASSES on a ``0`` count, so it
        must fail closed when the run scope is unknown rather than free-pass on
        stale/unknown telemetry. Returns ``True`` iff the persisted run scope
        yields a run id.
        """
        return self._resolve_active_run_id(story_dir) is not None

    def _resolve_active_run_id(self, story_dir: Path) -> str | None:
        """Resolve the active run id for ``story_dir`` (``None`` when unknown).

        FK-33 §33.3.2 run scope: the recurring guards count events of the
        CURRENT run only. The authoritative run correlation is the persisted
        run scope of the story's flow execution.
        """
        from agentkit.state_backend.store import facade

        try:
            scope = facade.resolve_runtime_scope(story_dir)
        except Exception:  # noqa: BLE001 -- unresolved scope -> no run filter
            return None
        return getattr(scope, "run_id", None)


#: Forbidden secret-shaped file extensions in a changeset (FK-27 §27.4.2).
_SECRET_EXTENSIONS: tuple[str, ...] = (".env", ".pem", ".key", ".pfx", ".p12")
#: Test-file path markers used to count test files in a changeset (FK-27
#: ``test.count``): a changed path is a test file when its name matches.
_TEST_FILE_MARKERS: tuple[str, ...] = ("test_", "_test.", "/tests/", "tests/")


@dataclass(frozen=True)
class _SubprocessGitChangeEvidenceProvider:
    """Productive ``ChangeEvidencePort`` over real ``git`` (FIX-3, FK-33 §33.5).

    Collects INDEPENDENT system evidence about the story's change set by running
    read-only ``git`` commands in the story worktree (NEVER the worker manifest):
    the actual checked-out branch, the commit history since ``origin/main`` (the
    base ref), the upstream-push state, the diff's changed + secret-shaped files
    and the diff-derived actual change impact (FK-23 §23.8). The ``git`` import
    (subprocess) lives HERE in the composition root, keeping ``verify_system``
    free of subprocess. Any git error yields ``available=False`` so the BLOCKING
    checks fail closed (NO ERROR BYPASSING; never a fall-back to self-report).
    """

    base_ref: str = "origin/main"

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Collect the system change evidence (``available=False`` on any error)."""
        from agentkit.verify_system.structural.system_evidence import ChangeEvidence

        branch = self._git(story_dir, "rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            return ChangeEvidence(available=False)
        base = self._merge_base(story_dir)
        commits = self._commit_messages(story_dir, base)
        changed = self._changed_files(story_dir, base)
        secret_files = tuple(
            f for f in changed if f.lower().endswith(_SECRET_EXTENSIONS)
        )
        actual_impact = _derive_actual_impact(changed)
        return ChangeEvidence(
            available=True,
            current_branch=branch,
            commit_messages=commits,
            pushed=self._is_pushed(story_dir),
            secret_files=secret_files,
            changed_files=changed,
            actual_impact=actual_impact,
        )

    def _merge_base(self, story_dir: Path) -> str | None:
        """Resolve the base ref to diff against (``origin/main``, else empty)."""
        return self._git(story_dir, "merge-base", self.base_ref, "HEAD")

    def _commit_messages(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        rng = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "log", "--format=%B%x00", rng)
        if out is None:
            return ()
        return tuple(m.strip() for m in out.split("\x00") if m.strip())

    def _changed_files(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        spec = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "diff", "--name-only", spec)
        if out is None:
            return ()
        return tuple(line.strip() for line in out.splitlines() if line.strip())

    def _is_pushed(self, story_dir: Path) -> bool:
        """Whether the branch has an upstream whose tip contains HEAD."""
        upstream = self._git(
            story_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )
        if upstream is None:
            return False
        head = self._git(story_dir, "rev-parse", "HEAD")
        upstream_sha = self._git(story_dir, "rev-parse", upstream)
        if head is None or upstream_sha is None:
            return False
        # The branch is pushed when the upstream is an ancestor of (or equal to)
        # HEAD's pushed tip; conservatively require the upstream to contain HEAD.
        contains = self._git(
            story_dir, "merge-base", "--is-ancestor", head, upstream
        )
        return contains is not None

    def _git(self, story_dir: Path, *args: str) -> str | None:
        """Run a read-only git command; return stripped stdout or ``None``."""
        import subprocess  # noqa: PLC0415 -- comp-root owns the subprocess import

        try:
            result = subprocess.run(  # noqa: S603 -- fixed git argv, no shell
                ["git", "-C", str(story_dir), *args],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


#: Diff size threshold below which a single-component change stays ``LOCAL``.
_LOCAL_FILE_THRESHOLD = 3
#: Number of distinct top-level components that marks a CROSS_COMPONENT change.
_CROSS_COMPONENT_DIRS = 2


def _derive_actual_impact(changed_files: tuple[str, ...]) -> ChangeImpact | None:
    """Derive the SYSTEM actual change impact from the diff (FK-23 §23.8).

    A deterministic, diff-based proxy (no worker input): more distinct top-level
    components touched => higher impact. This is the independent measurement the
    BLOCKING ``impact.violation`` check compares against the worker's declared
    budget. ``None`` only for an empty diff (nothing changed).
    """
    from agentkit.story_context_manager.story_model import ChangeImpact

    if not changed_files:
        return None
    top_dirs = {f.split("/", 1)[0] for f in changed_files if "/" in f} or {""}
    distinct = len(top_dirs)
    if distinct <= 1:
        return (
            ChangeImpact.LOCAL
            if len(changed_files) <= _LOCAL_FILE_THRESHOLD
            else ChangeImpact.COMPONENT
        )
    if distinct == _CROSS_COMPONENT_DIRS:
        return ChangeImpact.CROSS_COMPONENT
    return ChangeImpact.ARCHITECTURE_IMPACT


def build_artifact_invalidation_sink(store_dir: Path) -> ArtifactInvalidationSink:
    """Build the productive ``artifact_invalidated`` telemetry sink (AG3-041 §2.1.3).

    Composition-Root wiring for FK-27 §27.2.3: every cycle-bound QA artefact
    moved to ``stale/`` on ``advance_qa_cycle`` emits an ``artifact_invalidated``
    telemetry event through the canonical :class:`StateBackendEmitter`. This is
    the productive default for ``build_verify_system`` — NOT a no-op stub.
    ``verify_system`` only knows the ``ArtifactInvalidationSink`` Protocol; the
    telemetry import lives here, keeping the BC free of a telemetry dependency.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``artifact_invalidated`` events.
    """
    from agentkit.telemetry.storage import StateBackendEmitter

    return _TelemetryArtifactInvalidationSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryArtifactInvalidationSink:
    """Adapt ``ArtifactInvalidationEvent`` facts onto the telemetry emitter.

    Bridges the ``verify_system`` invalidation Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.2.3 / FK-68). Each invalidation fact
    becomes an ``EventType.ARTIFACT_INVALIDATED`` event carrying the moved
    file, the old epoch and the source/stale paths. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the file
    move has already happened, so a telemetry hiccup never corrupts QA truth.
    """

    emitter: EventEmitter

    def artifact_invalidated(self, event: ArtifactInvalidationEvent) -> None:
        """Emit an ``artifact_invalidated`` telemetry event for one moved file.

        Args:
            event: The invalidation fact (story, filename, epoch, paths).
        """
        from agentkit.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.ARTIFACT_INVALIDATED,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "filename": event.filename,
                    "old_epoch": event.old_epoch,
                    "source_path": str(event.source_path),
                    "stale_path": str(event.stale_path),
                },
            )
        )


def build_review_completion_sink(store_dir: Path) -> ReviewCompletionSink:
    """Build the productive ``llm_call_complete`` telemetry sink (FIX-C).

    Composition-Root wiring for FK-27 §27.4.3 / §27.5.5: after each Layer-2
    review artefact is written, the QA-subflow emits a canonical
    ``llm_call_complete`` execution event (carrying the reviewer role) through
    the canonical :class:`StateBackendEmitter`. This is what the
    ``guard.multi_llm`` Gate 2 counts (per mandatory reviewer role) so the gate
    is meaningful: it passes a genuine multi-LLM run and FAILS when reviews are
    missing (FK-37 §37.1.6). ``verify_system`` only knows the
    ``ReviewCompletionSink`` Protocol; the telemetry import lives HERE.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``llm_call_complete`` events.
    """
    from agentkit.telemetry.storage import StateBackendEmitter

    return _TelemetryReviewCompletionSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryReviewCompletionSink:
    """Adapt ``ReviewCompletionEvent`` facts onto the telemetry emitter (FIX-C).

    Bridges the ``verify_system`` review-completion Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.4.3 / §27.5.5). Each completion fact
    becomes an ``EventType.LLM_CALL_COMPLETE`` event whose payload ``role``
    matches the ``guard.multi_llm`` per-role filter. The event is emitted ONLY
    after the review artefact write succeeded (the caller invokes the sink after
    a successful envelope write), per FK-27 §27.4.3. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the review
    artefact is already written, so a telemetry hiccup never corrupts QA truth.
    The run scope is resolved by the emitter from ``store_dir`` (the SAME run
    scope the recurring-guard count reads), so the emitted event lands under the
    active run and the run-scoped Gate-2 count finds it (FK-33 §33.3.2).
    """

    emitter: EventEmitter

    def review_completed(self, event: ReviewCompletionEvent) -> None:
        """Emit an ``llm_call_complete`` telemetry event for one completed review.

        Args:
            event: The completion fact (story, reviewer role, artefact filename).
        """
        from agentkit.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.LLM_CALL_COMPLETE,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "role": event.role,
                    "artifact_filename": event.artifact_filename,
                },
            )
        )


def build_sonar_gate_port(
    config: object,
    *,
    client: object,
    fast: bool,
    story_type: object,
    ledger: object,
    bound_analysis: object,
    main_head_revision: str,
) -> SonarGateInputPort:
    """Build the productive ``sonarqube_gate`` port (FK-33 §33.6, AG3-052).

    When ``sonarqube.available == false`` the gate is deliberately absent
    (not-applicable) and the absent default port is returned — never the
    fail-closed adapter (FK-33 §33.6.5 "absent != broken"). Otherwise the
    :class:`ConfiguredSonarGateInputPort` is wired with the per-run
    collaborators; it fails closed on any unreachable/unreadable input.

    The per-run coordinates (the commit-bound analysis, the loaded ledger,
    main HEAD, the fast axis/story type) are resolved by the caller (pipeline
    engine) and passed in; this keeps ``build_verify_system`` free of
    per-story knowledge. The objects are typed loosely here to avoid
    importing the capability submodules at module top-level; they are
    validated by the adapter.

    Args:
        config: The resolved ``SonarQubeConfig``.
        client: A connected ``integrations.sonar`` ``SonarClient``.
        fast: Whether the run is in ``fast`` mode (FK-24 §24.3.3) — the
            SEPARATE fast/standard axis (``story_context.mode is
            WireStoryMode.FAST``), NOT ``execution_route``.
        story_type: Resolved ``StoryType``.
        ledger: The loaded ``AcceptedExceptionLedger``.
        bound_analysis: The commit-bound ``BoundAnalysis`` coordinates.
        main_head_revision: Authoritative current main HEAD revision.

    Returns:
        A productive ``SonarGateInputPort`` (or the absent default port
        when ``available == false``).
    """
    from agentkit.config.models import SonarQubeConfig
    from agentkit.integrations.sonar import SonarClient
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate.adapter import (
        BoundAnalysis,
        ConfiguredSonarGateInputPort,
    )
    from agentkit.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
    from agentkit.verify_system.sonarqube_gate.port import (
        ABSENT_SONAR_GATE_PORT,
    )

    if not isinstance(config, SonarQubeConfig):
        msg = f"config must be a SonarQubeConfig; got {type(config).__name__}"
        raise TypeError(msg)
    if not config.available:
        # Deliberately absent Sonar => not-applicable skip; never fail-closed.
        return ABSENT_SONAR_GATE_PORT
    if not isinstance(client, SonarClient):
        msg = f"client must be a SonarClient; got {type(client).__name__}"
        raise TypeError(msg)
    if not isinstance(ledger, AcceptedExceptionLedger):
        msg = f"ledger must be an AcceptedExceptionLedger; got {type(ledger).__name__}"
        raise TypeError(msg)
    if not isinstance(bound_analysis, BoundAnalysis):
        msg = f"bound_analysis must be a BoundAnalysis; got {type(bound_analysis).__name__}"
        raise TypeError(msg)
    if not isinstance(story_type, StoryType):
        msg = f"story_type must be a StoryType; got {type(story_type).__name__}"
        raise TypeError(msg)
    return ConfiguredSonarGateInputPort(
        config=config,
        client=client,
        fast=bool(fast),
        story_type=story_type,
        ledger=ledger,
        bound_analysis=bound_analysis,
        main_head_revision=main_head_revision,
    )


def build_skills(
    store_dir: Path,
    *,
    bundle_store_root: Path | None = None,
) -> Skills:
    """Erzeugt eine vollstaendig verdrahtete ``Skills``-Top-Surface (AG3-048).

    Composition-Root fuer den agent-skills-BC (FK-43, bc-cut-decisions.md §BC 11
    + §BC 12), analog ``build_artifact_manager``: bindet den systemweiten
    ``SkillBundleStore`` und das produktive
    ``StateBackendSkillBindingRepository`` zu einer ``Skills``-Instanz. Aufrufer
    (Installer, runtime, Tests) erhalten ``Skills`` ueber DI und kennen die
    Repository-Implementierung nicht.

    Architecture Conformance: ``agentkit.skills`` importiert NICHT aus
    ``state_backend.store``; die Verdrahtung der State-Backend-Persistenz
    geschieht ausschliesslich hier im Composition-Root.

    Args:
        store_dir: Basisverzeichnis des State-Backends (SQLite legt unter
            ``store_dir/.agentkit/...`` an; Postgres ignoriert den Pfad).
        bundle_store_root: Optionaler Override fuer den systemweiten
            Skill-Bundle-Store. ``None`` -> Plattform-Default (FK-43 §43.5.2).

    Returns:
        ``Skills`` mit ``SkillBundleStore`` + ``StateBackendSkillBindingRepository``.
    """
    from agentkit.skills import Skills as _Skills
    from agentkit.skills.bundle_store import SkillBundleStore as _SkillBundleStore
    from agentkit.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    bundle_store = _SkillBundleStore(store_root=bundle_store_root)
    repository = StateBackendSkillBindingRepository(store_dir)
    return _Skills(bundle_store=bundle_store, binding_repo=repository)


def build_integrity_gate(store_dir: Path | None = None) -> IntegrityGate:
    """Erzeugt einen vollstaendig verdrahteten ``IntegrityGate``.

    Composition-Root fuer die Closure-Phase (AG3-031 Pass-5 Fix E9):
    Instanziiert ``StateBackendIntegrityGateStateAdapter`` als ``state_port``.

    AG3-034 (Finding E / Remediation E-F): verdrahtet zusaetzlich den
    ``EnvelopeValidator``, sodass die Pflicht-Artefakt-Vorstufe die
    Envelope-Pflichtfeldpruefung (FK-71 §71.2) fuer **jedes** Pflicht-QA-Artefakt
    (Structural Dim 1 + Decision Dim 4) ausfuehrt (``ENVELOPE_VIOLATION`` bei
    Verstoss).  Die Dimensionen lesen die kanonischen QA-Envelopes selbst ueber
    den ``state_port`` (FK-35 §35.2.4 Producer/Status/Tiefe).

    Dimension 9 (SONARQUBE_GREEN, R2-C/A2): verdrahtet den produktiven
    ``ProductiveSonarDimensionPort``, der die AG3-052-Capability KONSUMIERT
    (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``) — keine
    eigene Attestation-Mechanik, kein None-Stub-Loader.  Die Capability loest die
    Applicability aus ``sonarqube.available`` + Story-``mode`` + Story-Typ auf
    (``available == false`` / fast / non-code => nicht-anwendbar, Dim 9
    entfaellt).  Fuer einen APPLICABLE impl/bugfix-Run liest
    ``build_sonar_gate_port_for_run`` das commit-gebundene Scan-Artefakt; ist es
    abwesend (der integrierte Pre-Merge-Scan FK-29 §29.1a ist OOS), liefert die
    Capability einen fail-closed APPLICABLE-Port (``attestation = None``) und
    ``evaluate_sonarqube_gate`` ein ``failed``-Outcome -> Dim 9 **fail-closed**
    (``SONAR_NOT_GREEN``/ESCALATED), NIEMALS Skip.

    Args:
        store_dir: Basisverzeichnis des State-Backends (SQLite); Postgres
            ignoriert den Pfad.  ``None`` => Default-Store des Repositories.

    Returns:
        ``IntegrityGate`` mit State-Port + Envelope-Validierung + Dim-9-Port.
    """
    from agentkit.governance.integrity_gate import IntegrityGate as _IntegrityGate
    from agentkit.state_backend.store.integrity_gate_repository import (
        StateBackendIntegrityGateStateAdapter,
    )

    validator = EnvelopeValidator(build_producer_registry())
    sonar_port = _build_dim9_sonar_port(store_dir)
    return _IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        envelope_validator=validator,
        sonar_port=sonar_port,
    )


def _build_dim9_sonar_port(store_dir: Path | None) -> SonarDimensionPort:
    """Build the productive Dim-9 ``SonarDimensionPort`` (FK-35 §35.2.4a, R2-C/A2).

    Wires the :class:`ProductiveSonarDimensionPort`, which CONSUMES the AG3-052
    capability (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``)
    for the resolution AND the verdict — no hand-rolled attestation loader, no
    second gate mechanic.  The two injected loaders are the truth-boundary reads
    the composition root owns (``governance`` may not read the StoryContext /
    project config directly): one resolves the run's :class:`StoryContext`, the
    other the project :class:`SonarQubeConfig`.  The capability then resolves
    applicability + the commit-bound inputs and produces the canonical outcome.
    """
    from agentkit.governance.integrity_gate.dim9_port import (
        ProductiveSonarDimensionPort,
    )

    _ = store_dir  # the facade resolves the active backend itself.
    return ProductiveSonarDimensionPort(
        _load_sonar_config,  # type: ignore[arg-type]
        _load_story_context_for_gate,  # type: ignore[arg-type]
    )


def _load_story_context_for_gate(gate_ctx: object) -> object | None:
    """Resolve the run's ``StoryContext`` for the Dim-9 port (truth-boundary read).

    Owned by the composition root: ``governance`` may not read the StoryContext
    directly.  An unreadable/absent context returns ``None`` -> the port treats a
    code story as APPLICABLE-but-unresolvable -> Dim 9 fails closed.
    """
    from agentkit.governance.integrity_gate import IntegrityGateContext
    from agentkit.state_backend.store import facade

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    try:
        return facade.load_story_context(gate_ctx.story_dir)
    except Exception:  # noqa: BLE001 -- unreadable context -> fail-closed downstream
        return None


def _load_sonar_config(gate_ctx: object) -> object | None:
    """Resolve the project ``SonarQubeConfig`` for the Dim-9 port (truth boundary).

    Returns the project's ``sonarqube`` config stanza, or ``None`` ONLY for a
    legitimate, deliberate absence: no resolvable project root, or a successfully
    loaded config that simply omits the ``sonarqube`` stanza (a non-code-producing
    project — ``build_sonar_gate_port_for_run`` then resolves a declared skip,
    FK-33 §33.6.5 "absent != broken").

    FAIL-CLOSED (R3-C/A2, analog AG3-052
    ``test_anchor_propagates_config_error_no_silent_skip``): a BROKEN or unreadable
    project config (``ConfigError``/``OSError`` from ``load_project_config``,
    including the E6 hard-fail on an omitted stanza for a code-producing project)
    is NOT a declared absence.  It MUST NOT be swallowed into ``None`` (which would
    route through the absent-port branch => silent Dim-9 skip).  It PROPAGATES so
    the Dim-9 port fails closed (``SONAR_NOT_GREEN``/escalation), never an inert
    skip (FAIL-CLOSED, ZERO DEBT).  ``governance`` never reads the project config
    directly; this composition-root helper owns the read.

    Equally fail-closed (R4-C/A2): an absent/unresolvable ``project_root`` is a
    declared absence ONLY for a NON-code-producing story (the gate never applies
    to it; ``None`` -> deliberate skip).  For a CODE-PRODUCING story
    (implementation/bugfix) an unresolvable ``project_root`` is a BROKEN
    precondition — the config cannot be loaded, so applicability cannot be
    proven absent.  It MUST raise ``ConfigError`` (fail-closed) rather than
    return ``None``, which would otherwise route through the absent-port branch
    into a silent Dim-9 skip = fail-open.  The code-producing axis is the
    AG3-052 SSOT (``is_code_producing_story``), not a re-derived flag.

    Raises:
        ConfigError: When the project config cannot be loaded/validated for a run
            with a resolvable project root (propagated fail-closed), OR when a
            code-producing story has no resolvable ``project_root`` (broken
            precondition => never a silent skip).
        OSError: When the config files cannot be read (propagated fail-closed).
    """
    from agentkit.config.loader import load_project_config
    from agentkit.exceptions import ConfigError
    from agentkit.governance.integrity_gate import IntegrityGateContext
    from agentkit.state_backend.store import facade
    from agentkit.verify_system.sonarqube_gate import is_code_producing_story

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    try:
        ctx = facade.load_story_context(gate_ctx.story_dir)
    except Exception:  # noqa: BLE001 -- unreadable context -> no config
        return None
    if ctx is None or ctx.project_root is None:
        if is_code_producing_story(gate_ctx.story_type):
            # Code-producing story without a resolvable project root: the config
            # is unloadable, so a deliberate absence cannot be proven. Fail
            # closed (never a silent Dim-9 skip; FK-33 §33.6.5, R4-C/A2).
            msg = (
                "cannot resolve project_root for code-producing story "
                f"{gate_ctx.story_type.value!r}: project config unloadable -> "
                "Dim 9 fail-closed (no silent skip)"
            )
            raise ConfigError(msg)
        return None
    # NO try/except ConfigError/OSError -> None here: a broken/unreadable config
    # is a fail-closed condition, NOT a declared absence (R3-C/A2).
    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    return getattr(pipeline, "sonarqube", None) if pipeline is not None else None


def build_setup_preflight_gate() -> SetupContextRepository:
    """Erzeugt einen verdrahteten ``SetupContextRepository``-Adapter.

    Composition-Root fuer die Setup-Phase (AG3-031 Pass-5 Fix E9):
    Instanziiert ``StateBackendSetupContextAdapter`` und gibt ihn als
    ``SetupContextRepository`` zurueck.  Aufrufer reichen ihn via
    ``SetupPhaseHandler(config, context_repository=...)`` ein.

    Returns:
        ``StateBackendSetupContextAdapter`` als ``SetupContextRepository``.
    """
    from agentkit.state_backend.store.setup_context_repository import (
        StateBackendSetupContextAdapter,
    )

    return StateBackendSetupContextAdapter()


def build_setup_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    dependency_repository: object | None = None,
    green_main_port: object | None = None,
) -> SetupPhaseHandler:
    """Wire a fully-collaborated ``SetupPhaseHandler`` (AG3-034 canonical point).

    Assembles the Setup-phase collaborators the truth-boundary-protected
    handler may not build itself: the context repository, the run-aware
    residue probe (Check 6, Finding B), the project ``ModeLockRepository``
    read path (Check 10) and the optional green-main capability port (FK-22
    §22.4c).  Callers that build a bare ``SetupPhaseHandler(config, repo)``
    miss the residue/mode-lock wiring and the residue check fails closed.

    Args:
        config: The ``SetupConfig``.
        store_dir: State-backend base dir for the residue probe + mode-lock
            repository (SQLite); ``None`` => the config's ``project_root``.
        dependency_repository: Optional ``StoryDependencyRepository`` (Check 4).
        green_main_port: Optional ``MainGreenPort`` (FK-22 §22.4c); ``None`` is
            the absent-Sonar default (green-main SKIPs unless APPLICABLE).

    Returns:
        A wired ``SetupPhaseHandler``.
    """
    from agentkit.governance.setup_preflight_gate.phase import (
        SetupConfig,
        SetupPhaseHandler,
    )
    from agentkit.state_backend.store.mode_lock_repository import ModeLockRepository

    if not isinstance(config, SetupConfig):
        msg = f"config must be a SetupConfig; got {type(config).__name__}"
        raise TypeError(msg)
    return SetupPhaseHandler(
        config,
        build_setup_preflight_gate(),
        dependency_repository=dependency_repository,  # type: ignore[arg-type]
        mode_lock_repository=ModeLockRepository(config.project_root),
        green_main_port=green_main_port,  # type: ignore[arg-type]
        residue_probe=build_phase_state_residue_probe(
            store_dir or config.project_root
        ),
    )


def build_phase_state_residue_probe(
    store_dir: Path | None = None,
) -> Callable[[Path, str], bool]:
    """Build the run-residue probe for Preflight Check 6 (AG3-034 Finding B).

    The canonical residue read (a left-over phase-state of a PRIOR, un-reset
    run) is a state-backend read.  ``governance`` is truth-boundary-protected
    and may NOT call the loader directly (TB003), so this composition-root
    helper owns the read and is INJECTED into the ``SetupPhaseHandler`` as a
    plain callable.

    Excluding the CURRENT run (FK-22 §22.3.1, Check 6): the pipeline persists a
    fresh ``setup``/``PENDING`` phase-state before preflight runs, so a
    ``setup``-phase state in a not-yet-active status (``PENDING``/``IN_PROGRESS``)
    is the run being set up — NOT residue.  Residue is a non-terminal phase-state
    that signals an un-reset prior run: a ``FAILED``/``PAUSED`` state in any
    phase, or any non-terminal state in a phase BEYOND setup
    (``implementation``/``closure`` left-over).

    Args:
        store_dir: Base directory of the state backend (SQLite); ignored by
            Postgres.

    Returns:
        ``check(project_root, story_display_id) -> bool`` (True == residue).
    """
    from agentkit.installer.paths import story_dir
    from agentkit.state_backend.store import facade
    from agentkit.story_context_manager.models import PhaseStatus

    _ = store_dir  # facade resolves the active backend itself.
    stalled = {
        PhaseStatus.FAILED,
        PhaseStatus.PAUSED,
        PhaseStatus.ESCALATED,
        PhaseStatus.BLOCKED,
    }
    fresh_current_run = {PhaseStatus.PENDING, PhaseStatus.IN_PROGRESS}

    def _probe(project_root: Path, story_display_id: str) -> bool:
        s_dir = story_dir(project_root, story_display_id)
        state = facade.load_phase_state(s_dir)
        if state is None or state.status is PhaseStatus.COMPLETED:
            return False
        if state.status in stalled:
            return True  # stalled prior run, regardless of phase
        # PENDING / IN_PROGRESS: residue only when BEYOND the setup phase
        # (a left-over implementation/closure run); a fresh setup state is the
        # current run being set up, not residue.
        return state.phase != "setup" and state.status in fresh_current_run

    return _probe


def build_projection_accessor(store_dir: Path | None = None) -> ProjectionAccessor:
    """Erzeugt einen vollstaendig verdrahteten ``ProjectionAccessor``.

    Composition-Root fuer den FK-69-Projektions-Schreib-/Lese-Pfad (AG3-035):
    Instanziiert alle vier Repository-Adapter und reicht sie via
    ``ProjectionRepositories``-Dataclass in den ``ProjectionAccessor`` ein.
    Konsument-BCs (z. B. ``story_closure.PostMergeFinalization``) erhalten
    den Accessor via DI und kennen die Repository-Implementierungen nicht.

    Architecture Conformance (AC#7): ProjectionAccessor importiert keine
    konkreten Implementierungen aus ``state_backend.store.facade``.

    Args:
        store_dir: Basisverzeichnis des State-Backends. Nur fuer SQLite relevant;
            Postgres ignoriert den Pfad.

    Returns:
        ``ProjectionAccessor`` mit allen vier Repository-Adaptern.
    """
    from agentkit.state_backend.store.projection_repositories import (
        build_projection_repositories,
    )
    from agentkit.telemetry.projection_accessor import (
        ProjectionAccessor as _ProjectionAccessor,
    )

    repos = build_projection_repositories(store_dir)
    return _ProjectionAccessor(repos)


def build_closure_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    project_key: str = "",
) -> ClosurePhaseHandler:
    """Wire a fully-collaborated ``ClosurePhaseHandler`` (FK-29, AG3-053).

    Composition root for the Closure phase (BC 7, ``story-closure``): assembles
    the collaborators the truth-boundary-protected handler may NOT build itself
    (DI pattern, analog ``build_setup_phase_handler`` / ``build_verify_system``).
    The handler ORCHESTRATES the canonical FK-29 §29.1.4 sequence by CALLING
    these capabilities; it builds no second merge/gate/Sonar/lock truth:

    * ``integrity_gate`` -- :func:`build_integrity_gate` (AG3-034 verifier; its
      Dim 9 consumes the AG3-052 Sonar capability to verify the fresh
      attestation, FK-35 §35.2.4a).
    * ``artifact_manager`` -- :func:`build_artifact_manager` (the only Layer-2
      read seam for the Finding-Resolution-Gate, FK-29 §29.2).
    * ``scan_port`` / ``build_test_port`` -- the AG3-056 Pre-Merge-Verification-
      Runner's commit-bound ``CiSonarScanRunner`` / ``CiBuildTestRunner`` (FK-29
      §29.1a.3 steps c/d), wired via ``build_pre_merge_runners`` over one shared
      CI run. ``None`` for a declared-absent CI (``ci.available == false``);
      applicable-but-unreachable raises ``PreMergeRunnerUnavailableError``
      (fail-closed). The old fail-open ``build_sonar_gate_port_for_run`` scan path
      is REMOVED -- AG3-053 consumes AG3-056.
    * ``sonar_config`` -- the FK-03 ``sonarqube`` stanza, threaded into the
      fresh-attestation Dim-9 version-drift check (FK-35 §35.2.4a item 5).
    * ``sanity_port`` -- the fast-mode Sanity-Gate seam (FK-29 §29.1a.6).
    * ``doc_fidelity_port`` -- level-4 doc-fidelity feedback via
      ``verify_system.llm_evaluator`` (FK-38 §38.3.1, non-blocking).
    * ``vectordb_sync_port`` -- the FK-13 §13.7.1 sync trigger (non-blocking).
    * ``guard_deactivation_port`` -- ``Governance.deactivate_locks`` (FK-29 §29.5,
      governance top surface; closure holds no lock logic).

    Args:
        config: A ``ClosureConfig`` carrying ``story_dir`` (+ optional GitHub /
            story-service fields). The collaborator slots are overwritten here.
        store_dir: State-backend base dir (SQLite); ``None`` => the config's
            ``story_dir``.
        project_key: Owning project key for the governance top surface.

    Returns:
        A wired ``ClosurePhaseHandler``.
    """
    from agentkit.closure.phase import ClosureConfig, ClosurePhaseHandler

    if not isinstance(config, ClosureConfig):
        msg = f"config must be a ClosureConfig; got {type(config).__name__}"
        raise TypeError(msg)
    base_dir = store_dir or config.story_dir or Path.cwd()
    config.progress_store = _build_closure_progress_store(base_dir)
    config.integrity_gate = build_integrity_gate(base_dir)
    config.artifact_manager = build_artifact_manager(base_dir)
    ci_config, sonar_config = _resolve_pre_merge_configs(config.story_dir)
    config.sonar_config = sonar_config
    # FIX-C: build a runner pair PER participating repo (each bound to ITS OWN
    # root/ledger/tree), so every repo is verified against its own root. The
    # single-repo path is the one-entry case (config.repos empty => the story_dir
    # repo). The applicability is resolved once (story-type + ci/sonar facets are
    # the same across repos for one story).
    repo_roots = _closure_repo_roots(config, base_dir)
    repo_runners, applicability = _build_per_repo_runners(
        ci_config, sonar_config, repo_roots
    )
    config.merge_applicability = applicability
    primary = repo_runners[repo_roots[0]]
    config.scan_port = primary.scan_port
    config.build_test_port = primary.build_test_port
    config.repo_runners = repo_runners
    config.sanity_port = _build_sanity_gate_port(ci_config)
    config.doc_fidelity_port = _build_doc_fidelity_feedback_port()
    config.vectordb_sync_port = _build_vectordb_sync_port()
    config.guard_deactivation_port = _build_guard_deactivation_port(
        base_dir, project_key=project_key
    )
    config.mode_lock_release_port = _build_mode_lock_release_port(base_dir)
    return ClosurePhaseHandler(config)


def _build_mode_lock_release_port(store_dir: Path) -> ModeLockReleasePort:
    """Build the project mode-lock release seam (FK-24 §24.3.3, AG3-018).

    Delegates to the atomic ``ModeLockRepository.release`` for the mode this story
    acquired at Setup (read from the durable acquire marker). Closure holds no
    mode-lock logic itself.
    """
    from agentkit.closure.runtime_ports import ProductiveModeLockReleasePort
    from agentkit.state_backend.store.mode_lock_repository import ModeLockRepository

    return ProductiveModeLockReleasePort(mode_lock_repo=ModeLockRepository(store_dir))


def _build_closure_progress_store(store_dir: Path) -> ClosureProgressStore:
    """Build the closure checkpoint store (FK-29 §29.1.0, AC003 pipeline surface).

    Phase-state mutation may only happen through a pipeline surface
    (architecture-conformance AC003), so the closure checkpoint writes go through
    the ``pipeline_engine`` :class:`PhaseEnvelopeStore` (over the state-backend
    phase-envelope repository) -- NOT a direct ``save_phase_state`` import in the
    closure BC.
    """
    from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    return PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(store_dir))


class ClosureConfigUnavailableError(Exception):
    """The closure pre-merge config/context is broken (fail-closed, FIX-2).

    Raised by :func:`_resolve_pre_merge_configs` when the story context or the
    project config is PRESENT-but-unreadable/malformed, as opposed to a
    DELIBERATE absence (no ``ci``/``sonarqube`` stanza or ``available == false``).
    A broken config must never silently disable the integrated-candidate
    verification (NO ERROR BYPASSING) -- the composition root surfaces this
    before building the handler so the run escalates rather than merging code
    unverified.
    """


def _resolve_pre_merge_configs(
    story_dir: Path | None,
) -> tuple[object | None, object | None]:
    """Resolve the ``ci`` + ``sonarqube`` config stanzas (truth boundary, AG3-056).

    The composition root owns the project-config read (``governance``/``closure``
    stay free of direct config reads). Resolves the run ``StoryContext`` to find
    the project root, then loads the ``ci`` (Jenkins) and ``sonarqube`` stanzas
    for the AG3-056 pre-merge runner wiring + the Dim-9 version-drift check.

    FIX-2 fail-closed distinction (a broken config must NEVER silently disable
    verification, NO ERROR BYPASSING):

    * DELIBERATE absence -- no ``pipeline`` stanza at all (a non-code-producing
      project never declares CI/Sonar) -> ``(None, None)``: the runner wiring
      treats it as a declared skip and the applicability layer (FIX-3) decides
      per story type whether that is allowed.
    * BROKEN config/context -- an unresolvable project root, an unreadable
      story context, or a config that fails to load/parse -> FAIL-CLOSED
      (:class:`ClosureConfigUnavailableError`). Never downgraded to a declared
      absence.

    A PRESENT stanza with ``available == false`` is also a deliberate absence,
    but that is decided downstream (``build_pre_merge_runners`` returns ``None``
    for it); here we only fail closed on a genuinely broken read.
    """
    from agentkit.config.loader import load_project_config
    from agentkit.state_backend.store import facade

    if story_dir is None:
        raise ClosureConfigUnavailableError(
            "closure config resolution requires a story_dir (FIX-2, fail-closed)"
        )
    try:
        ctx = facade.load_story_context(story_dir)
    except Exception as exc:  # noqa: BLE001 -- broken context is fail-closed, not absence
        raise ClosureConfigUnavailableError(
            f"story context at {story_dir} is unreadable/malformed "
            f"(FIX-2, fail-closed -- never silently skip verification): {exc}"
        ) from exc
    if ctx is None or ctx.project_root is None:
        raise ClosureConfigUnavailableError(
            f"no resolvable story context / project root at {story_dir} "
            "(FIX-2, fail-closed)"
        )
    if not _project_config_present(ctx.project_root):
        # Deliberate absence: the project declares no AK3 config file at all
        # (a non-code-producing project never wires a pipeline). The
        # applicability layer (FIX-3) decides per story type whether a missing
        # runner is allowed -- it is for concept/research, fail-closed for code.
        return (None, None)
    try:
        project_config = load_project_config(ctx.project_root)
    except Exception as exc:  # noqa: BLE001 -- broken config is fail-closed, not absence
        raise ClosureConfigUnavailableError(
            f"project config at {ctx.project_root} is present but "
            f"unreadable/malformed (FIX-2, fail-closed -- a broken config never "
            f"silently disables Sonar/CI): {exc}"
        ) from exc
    pipeline = getattr(project_config, "pipeline", None)
    if pipeline is None:
        # Deliberate absence: no pipeline stanza (non-code-producing project).
        return (None, None)
    return (getattr(pipeline, "ci", None), getattr(pipeline, "sonarqube", None))


def _project_config_present(project_root: Path) -> bool:
    """Whether the project declares an AK3 config file (vs deliberate absence)."""
    from agentkit.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE

    return (project_root / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE).is_file()


def _build_pre_merge_runners(
    ci_config: object | None,
    sonar_config: object | None,
    *,
    repo_root: Path,
) -> tuple[PreMergeScanPort | None, BuildTestPort | None, MergeApplicability]:
    """Wire the AG3-056 pre-merge runners + resolve the typed applicability (FIX-3).

    CONSUMES AG3-056's
    :func:`verify_system.pre_merge_runner.runtime_wiring.build_pre_merge_runners`
    (the old fail-open ``build_sonar_gate_port_for_run`` scan path is REMOVED).
    The applicability is resolved HERE (the applicability layer, FIX-3) from the
    ``ci``/``sonarqube`` availability and threaded onto the handler so a declared
    absence never silently merges code unverified (FK-33 §33.6.5 "absent !=
    broken"):

    * CI DECLARED absent (no stanza / ``ci.available == false``) ->
      ``(None, None, CI_ABSENT)``: for a code-producing story the handler
      fail-closes (cannot verify => cannot merge); for concept/research the
      block is skipped entirely (``uses_merge == False``).
    * CI present + Sonar DECLARED absent (no stanza / ``sonarqube.available ==
      false``) -> ``(None, build_test, SONAR_ABSENT)``: Build/Test runs (built
      via the additive :func:`build_build_test_runner`), the integrated-candidate
      scan + Dim 9 are skipped, the merge stays gated.
    * CI present + Sonar present -> ``(scan, build_test, FULL)`` via
      ``build_pre_merge_runners`` (shared single run-cache).
    * APPLICABLE-but-unreachable (``available == true`` but the endpoint/token
      cannot be resolved) raises ``PreMergeRunnerUnavailableError`` ->
      fail-closed (NEVER a silent skip).

    Args:
        ci_config: The resolved ``JenkinsConfig`` (or ``None``).
        sonar_config: The resolved ``SonarQubeConfig`` (or ``None``).
        repo_root: The integrated-candidate repo root (tree-hash + ledger read).

    Returns:
        ``(scan_port, build_test_port, applicability)``.
    """
    from agentkit.closure.merge_sequence import MergeApplicability
    from agentkit.config.models import JenkinsConfig, SonarQubeConfig
    from agentkit.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
        build_pre_merge_runners,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    typed_sonar = sonar_config if isinstance(sonar_config, SonarQubeConfig) else None

    ci_present = typed_ci is not None and typed_ci.available
    if not ci_present:
        # Declared-absent CI: no Build/Test+scan runner. The handler fail-closes
        # for code-producing stories (FIX-3); concept/research skip the block.
        return (None, None, MergeApplicability.CI_ABSENT)

    sonar_present = typed_sonar is not None and typed_sonar.available
    if not sonar_present:
        # CI present, Sonar declared absent: Build/Test only, scan+Dim9 skipped.
        build_test_port = build_build_test_runner(typed_ci, repo_root)
        return (None, build_test_port, MergeApplicability.SONAR_ABSENT)

    runners = build_pre_merge_runners(typed_ci, typed_sonar, repo_root)
    if runners is None:  # pragma: no cover - ci_present already guaranteed above
        return (None, None, MergeApplicability.CI_ABSENT)
    return (runners.scan, runners.build_test, MergeApplicability.FULL)


def _closure_repo_roots(config: object, base_dir: Path) -> list[Path]:
    """Resolve the participating repo roots for the per-repo runner wiring (FIX-C).

    Mirrors the handler's ``_resolve_repos``: the configured ``ClosureRepo`` roots
    when present, else the single story-dir repo (one entry). Order-preserving and
    de-duplicated so each distinct root gets exactly one runner pair.
    """
    from agentkit.closure.phase import ClosureConfig

    assert isinstance(config, ClosureConfig)  # noqa: S101 - caller validated
    roots: list[Path] = []
    if config.repos:
        for repo in config.repos:
            if repo.repo_root not in roots:
                roots.append(repo.repo_root)
    else:
        roots.append(config.story_dir or base_dir)
    return roots


def _build_per_repo_runners(
    ci_config: object | None,
    sonar_config: object | None,
    repo_roots: list[Path],
) -> tuple[dict[Path, RepoRunners], MergeApplicability]:
    """Build a :class:`RepoRunners` pair per repo root + the shared applicability (FIX-C).

    Each repo root gets its OWN ``CiSonarScanRunner`` / ``CiBuildTestRunner``
    (via :func:`_build_pre_merge_runners`, so its ledger + tree-hash resolver bind
    to that root). The applicability is identical across repos (it derives from
    the story-type + the ci/sonar facets, which are project-wide for one story);
    it is resolved per repo and asserted consistent (a fail-closed invariant).
    """
    from agentkit.closure.merge_sequence import RepoRunners

    runners: dict[Path, RepoRunners] = {}
    resolved_applicability: MergeApplicability | None = None
    for repo_root in repo_roots:
        scan_port, build_test_port, applicability = _build_pre_merge_runners(
            ci_config, sonar_config, repo_root=repo_root
        )
        if resolved_applicability is None:
            resolved_applicability = applicability
        elif applicability is not resolved_applicability:  # pragma: no cover
            msg = (
                "inconsistent pre-merge applicability across repos: "
                f"{resolved_applicability} vs {applicability} "
                "(the ci/sonar facets must be project-wide for one story)"
            )
            raise ClosureConfigUnavailableError(msg)
        runners[repo_root] = RepoRunners(
            scan_port=scan_port, build_test_port=build_test_port
        )
    # ``repo_roots`` always has at least one entry (the story-dir fallback).
    assert resolved_applicability is not None  # noqa: S101 - non-empty roots
    return runners, resolved_applicability


def _build_sanity_gate_port(ci_config: object | None) -> SanityGatePort:
    """Build the fast-mode Sanity-Gate seam (FK-29 §29.1a.6, FIX-6).

    Wires the real subprocess git backend so the adapter genuinely confirms the
    two git-mechanic predicates (worktree clean + pre-merge rebase onto
    ``origin/main`` OK). The third predicate ("tests green") is wired to the SAME
    real AG3-056 Build/Test capability the standard barrier uses, via
    :func:`build_fast_test_runner` (FIX-6 -- one tests-green truth, not a stub).
    When CI is DECLARED absent (no ``ci`` stanza / ``ci.available == false``) no
    real runner exists, so ``test_runner`` stays ``None`` and the gate fails
    closed after the git checks (FAIL-CLOSED -- a fast story whose tests cannot be
    confirmed escalates; the floor is non-disableable, NO ERROR BYPASSING).
    """
    from agentkit.closure.multi_repo_saga import SubprocessGitBackend
    from agentkit.closure.runtime_ports import ProductiveSanityGatePort

    return ProductiveSanityGatePort(
        git_backend=SubprocessGitBackend(),
        test_runner=build_fast_test_runner(ci_config),
    )


def build_fast_test_runner(
    ci_config: object | None,
) -> Callable[[Path], tuple[bool, str | None]] | None:
    """Build the fast-mode tests-green floor runner (AG3-018 FIX-6, FK-24 §24.3.4).

    Wraps the REAL AG3-056 commit-bound :class:`BuildTestPort` (``CiBuildTestRunner``
    over the project's CI) as the ``Callable[[Path], tuple[bool, str | None]]``
    shape consumed by BOTH the fast QA-subflow floor (``build_verify_system
    fast_test_runner``) and the closure Sanity-Gate
    (``ProductiveSanityGatePort.test_runner``) -- ONE tests-green truth, not a
    second mechanism, not a stub.

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza, or ``None``.

    Returns:
        * ``None`` when CI is DECLARED absent (no ``ci`` stanza /
          ``ci.available == false``): no real runner exists, so the fast floor is
          unconfirmable and the consumer fails closed (the non-disableable floor).
        * a :class:`CiBuildTestFastRunner` over the real Build/Test port when CI
          is applicable. An applicable-but-unreachable CI raises
          ``PreMergeRunnerUnavailableError`` (fail-closed; never a silent skip).
    """
    from agentkit.closure.multi_repo_saga import SubprocessGitBackend
    from agentkit.closure.runtime_ports import CiBuildTestFastRunner
    from agentkit.config.models import JenkinsConfig
    from agentkit.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return None
    # ``repo_root`` is unused by the build/test facet (it needs no tree/ledger
    # read); the candidate's tree is resolved per-run from the story worktree.
    build_test_port = build_build_test_runner(typed_ci, Path.cwd())
    if build_test_port is None:  # pragma: no cover - guarded by the check above
        return None
    return CiBuildTestFastRunner(
        build_test_port=build_test_port,
        git_backend=SubprocessGitBackend(),
    )


def _build_doc_fidelity_feedback_port() -> DocFidelityFeedbackPort:
    """Build the level-4 doc-fidelity feedback seam (FK-38 §38.3.1, non-blocking).

    Consumes ``verify_system.llm_evaluator`` (``role=doc_fidelity``). The level-4
    feedback evaluation (``final_diff`` vs existing docs, FK-38 §38.3.1) has no
    productive callable yet; the seam is honest non-blocking — it records a human
    Warning every run until the level-4 capability lands (never a silent no-op).
    """
    from agentkit.closure.runtime_ports import ProductiveDocFidelityFeedbackPort

    return ProductiveDocFidelityFeedbackPort()


def _build_vectordb_sync_port() -> VectorDbSyncPort:
    """Build the VectorDB sync seam (FK-13 §13.7.1, fire-and-forget, non-blocking).

    Triggers an async ``story_sync``. The VectorDB integration is not yet
    available in the target project; the seam is honest non-blocking — it records
    a human Warning when the sync cannot be triggered (the STEP still runs).
    """
    from agentkit.closure.runtime_ports import ProductiveVectorDbSyncPort

    return ProductiveVectorDbSyncPort()


def _build_guard_deactivation_port(
    store_dir: Path, *, project_key: str
) -> GuardDeactivationPort:
    """Build the guard-deactivation seam (FK-29 §29.5, governance top surface).

    Delegates to ``Governance.deactivate_locks`` via a real ``Governance`` wired
    with the state-backend lock/hook/worktree repositories. Closure holds no lock
    logic itself (single delegation step).
    """
    from agentkit.closure.runtime_ports import ProductiveGuardDeactivationPort
    from agentkit.governance import Governance
    from agentkit.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(store_dir),
        lock_repo=LockRecordRepository(store_dir),
        project_key=project_key,
        project_root=store_dir,
        worktree_repo=StateBackendWorktreeRepository(store_dir),
    )
    return ProductiveGuardDeactivationPort(governance)


def build_structural_build_test_port(
    ci_config: object | None,
    story_dir: Path,
) -> BuildTestEvidencePort:
    """Build the REAL Layer-1 build/test evidence port (FIX-1, FK-27 §27.4.2).

    REUSES the AG3-056 commit-bound :class:`CiBuildTestRunner` (the same CI
    Build/Test capability the closure pre-merge barrier + the fast-mode floor
    use -- ONE build/test truth, NO new dependency). The runner reports ONE
    green/red verdict for the integrated candidate commit, which is exactly the
    truth ``build.compile`` AND ``build.test_execution`` (both BLOCKING) need: a
    CI-green run proves the build compiled and the tests passed for that commit.
    The MAJOR ``test.count`` is derived from the SYSTEM ``git diff`` (system
    evidence, not a worker claim).

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza, or ``None``.
        story_dir: The story working directory (git HEAD + diff source).

    Returns:
        * the fail-closed absent port when CI is DECLARED absent (no ``ci``
          stanza / ``ci.available == false``): the build/test evidence is
          unconfirmable so ``build.compile`` / ``build.test_execution`` FAIL
          closed (NO ERROR BYPASSING; never a fabricated green).
        * a :class:`_CiBuildTestEvidenceAdapter` over the real Build/Test port
          when CI is applicable. An applicable-but-unreachable CI raises
          ``PreMergeRunnerUnavailableError`` (fail-closed; never a silent skip).
    """
    from agentkit.config.models import JenkinsConfig
    from agentkit.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )
    from agentkit.verify_system.structural.checks import ABSENT_BUILD_TEST_PORT

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return ABSENT_BUILD_TEST_PORT
    build_test_port = build_build_test_runner(typed_ci, story_dir)
    if build_test_port is None:  # pragma: no cover - guarded by the check above
        return ABSENT_BUILD_TEST_PORT
    from agentkit.closure.multi_repo_saga import SubprocessGitBackend

    return _CiBuildTestEvidenceAdapter(
        build_test_port=build_test_port,
        git_backend=SubprocessGitBackend(),
    )


@dataclass(frozen=True)
class _CiBuildTestEvidenceAdapter:
    """Adapt the AG3-056 ``BuildTestPort`` to the Layer-1 ``BuildTestEvidencePort``.

    Resolves the story worktree's current HEAD into the AG3-056
    :class:`CandidateRef` and runs the commit-bound Build/Test. The CI run's
    single green/red verdict maps to BOTH ``build_ok`` and ``tests_green`` (a
    CI-green run proves the build compiled and tests passed for that commit). The
    test-file count is the SYSTEM ``git diff`` test-file count (system evidence).
    Coverage is reported as confirmed ONLY by the CI run's green (the AG3-056
    runner does not expose a separate coverage number; a green CI run executed
    the suite -- coverage_report_present mirrors the green run, threshold is left
    to the project CI). A red/unreadable run fails closed (``build_ok=False``).

    Attributes:
        build_test_port: The real AG3-056 commit-bound Build/Test port.
        git_backend: Git read port to resolve the worktree HEAD + diff.
    """

    build_test_port: BuildTestPort
    git_backend: RepoGitBackend

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        """Run the commit-bound Build/Test for the worktree HEAD (fail-closed)."""
        from agentkit.closure.multi_repo_saga import ClosureRepo
        from agentkit.verify_system.pre_merge_runner.contract import CandidateRef
        from agentkit.verify_system.structural.checks import BuildTestEvidence

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        branch = self._read(repo, "rev-parse", "--abbrev-ref", "HEAD")
        commit = self._read(repo, "rev-parse", "HEAD")
        tree = self._read(repo, "rev-parse", "HEAD^{tree}")
        if branch is None or commit is None or tree is None:
            return None  # HEAD unresolvable -> evidence unconfirmable (fail-closed)
        outcome = self.build_test_port.run(
            CandidateRef(branch=branch, commit_sha=commit, tree_hash=tree)
        )
        test_file_count = self._diff_test_file_count(repo)
        return BuildTestEvidence(
            build_ok=outcome.green,
            tests_green=outcome.green,
            test_file_count=test_file_count,
            coverage_report_present=outcome.green,
            coverage_meets_threshold=outcome.green,
            detail=outcome.reason,
        )

    def _diff_test_file_count(self, repo: object) -> int:
        from agentkit.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - caller passes ClosureRepo
        out = self._read(repo, "diff", "--name-only", "origin/main...HEAD")
        if out is None:
            out = self._read(repo, "diff", "--name-only", "HEAD")
        if not out:
            return 0
        return sum(
            1
            for line in out.splitlines()
            if any(marker in line for marker in _TEST_FILE_MARKERS)
        )

    def _read(self, repo: object, *args: str) -> str | None:
        from agentkit.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - caller passes ClosureRepo
        result = self.git_backend.run(repo, *args)
        if not result.ok or not result.stdout.strip():
            return None
        return result.stdout.strip()


def build_structural_are_provider(
    are_client: object | None,
    pipeline_config: object,
) -> AreGateProvider:
    """Build the REAL Layer-1 ARE provider (FIX-1, FK-27 §27.4.4).

    Wraps the productive :class:`RequirementsCoverage` top-surface (AG3-030,
    FK-40) so the ``are.gate`` stage activates IFF ``features.are == true`` and
    the coverage verdict comes from the real ``check_gate`` dock-point. ARE is
    NEVER silently disabled: when ``features.are`` is true the provider reports
    ``is_enabled == True`` and the gate runs (fail-closed when the verdict is
    unavailable, ``check_are_gate``).

    Args:
        are_client: The configured ``AreClient`` (``None`` when ARE is off).
        pipeline_config: The project's ``PipelineConfig`` (``features.are``).

    Returns:
        An :class:`_RequirementsCoverageAreProvider` over the wired
        ``RequirementsCoverage``.
    """
    from agentkit.config.models import PipelineConfig
    from agentkit.requirements_coverage.are_client import AreClient
    from agentkit.requirements_coverage.top import RequirementsCoverage

    if not isinstance(pipeline_config, PipelineConfig):
        msg = (
            "pipeline_config must be a PipelineConfig; got "
            f"{type(pipeline_config).__name__}"
        )
        raise TypeError(msg)
    typed_client = are_client if isinstance(are_client, AreClient) else None
    coverage = RequirementsCoverage(typed_client, pipeline_config)
    return _RequirementsCoverageAreProvider(coverage)


@dataclass(frozen=True)
class _RequirementsCoverageAreProvider:
    """Adapt ``RequirementsCoverage`` to the Layer-1 ``AreGateProvider`` (FIX-1).

    ``is_enabled`` reflects ``features.are`` (ONE activation truth);
    ``coverage_verdict`` delegates to the ``check_gate`` dock-point (FK-40
    §40.5.4). A non-PASS / missing verdict drives the fail-closed ``are.gate``
    finding (FK-27 §27.4.4).

    Attributes:
        coverage: The wired ``RequirementsCoverage`` top-surface.
    """

    coverage: RequirementsCoverageProto

    @property
    def is_enabled(self) -> bool:
        """Return whether ``features.are`` is active."""
        return self.coverage.is_enabled

    def coverage_verdict(
        self, story_id: str, project_key: str
    ) -> CoverageVerdict | None:
        """Return the ARE coverage verdict, or ``None`` when ARE is disabled."""
        if not self.coverage.is_enabled:
            return None
        return self.coverage.check_gate(story_id, project_key)


def build_failure_corpus(accessor: ProjectionAccessor) -> FailureCorpus:
    """Erzeugt eine verdrahtete ``FailureCorpus``-Top-Komponente (AG3-028).

    Composition-Root fuer den Failure-Corpus-BC (FK-41 §41.1/§41.4). Verdrahtet
    die ``IncidentTriage`` mit Default-Normalizer und -IngressCriteria und reicht
    den ``ProjectionAccessor`` sowohl als schmalen ``IncidentWriterPort``
    (``record_fc_incident`` -> ``IncidentId``, FK-41 §41.3.1) als auch als
    ``ProjectionReaderPort`` (Corpus-Neuheit, FK-41 §41.4.3) ein (FK-69 §69.9).
    ``failure_corpus`` kennt die fc_incidents-DB-Repo-Adapter NICHT (KONFLIKT-2,
    AC#6): Persistenz/Lesen laufen ueber den ``ProjectionAccessor``.

    Args:
        accessor: Der ``ProjectionAccessor`` als Schreib-/Lesegrenze (erfuellt
            ``IncidentWriterPort`` und ``ProjectionReaderPort`` per Strukturtyping).

    Returns:
        ``FailureCorpus`` mit funktionalem ``record_incident``; die uebrigen
        Top-Methoden sind Vertrags-Slots (NotImplementedError, Folge-Stories).
    """
    from agentkit.failure_corpus import (
        FailureCorpus as _FailureCorpus,
    )
    from agentkit.failure_corpus import (
        IncidentNormalizer,
        IncidentTriage,
        IngressCriteria,
    )

    triage = IncidentTriage(
        normalizer=IncidentNormalizer(),
        criteria=IngressCriteria(),
        writer=accessor,
        reader=accessor,
    )
    return _FailureCorpus(incident_triage=triage)


__all__ = [
    "ClosureConfigUnavailableError",
    "build_artifact_invalidation_sink",
    "build_review_completion_sink",
    "build_artifact_manager",
    "build_closure_phase_handler",
    "build_exploration_phase_handler",
    "build_exploration_review",
    "build_failure_corpus",
    "build_integrity_gate",
    "build_phase_state_residue_probe",
    "build_producer_registry",
    "build_projection_accessor",
    "build_setup_phase_handler",
    "build_setup_preflight_gate",
    "build_skills",
    "build_sonar_gate_port",
    "build_structural_are_provider",
    "build_structural_build_test_port",
    "build_verify_system",
]
