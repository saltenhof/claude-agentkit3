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
from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactManager,
    EnvelopeValidator,
    ProducerRegistry,
)
from agentkit.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.failure_corpus import FailureCorpus
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.governance.integrity_gate.dim9_sonar import SonarDimensionPort
    from agentkit.governance.repository import SetupContextRepository
    from agentkit.governance.setup_preflight_gate.phase import SetupPhaseHandler
    from agentkit.skills import Skills
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.telemetry.projection_accessor import ProjectionAccessor
    from agentkit.verify_system.qa_cycle.invalidation import (
        ArtifactInvalidationEvent,
        ArtifactInvalidationSink,
    )
    from agentkit.verify_system.sonarqube_gate.port import SonarGateInputPort
    from agentkit.verify_system.system import VerifySystem


def build_producer_registry() -> ProducerRegistry:
    """Erzeugt eine frische ``ProducerRegistry`` und ruft alle bekannten
    BC-Init-Hooks auf.

    Aktueller Stand: ``register_verify_producers`` (AG3-023) und
    ``register_prompt_runtime_producers`` (AG3-015, FK-44 §44.6 --
    ``ArtifactClass.PROMPT_AUDIT``) sind angebunden. Weitere BC-Init-Hooks
    (worker, telemetry, governance, closure ...) werden in ihren
    Folgestories analog ergaenzt.

    Returns:
        Eine ``ProducerRegistry`` mit allen heute bekannten Producern.

    Notes:
        Reihenfolge der Init-Hooks ist deterministisch (BC-alphabetisch
        bzw. Capability-Reihenfolge). Jeder Hook ist idempotent.
    """
    registry = ProducerRegistry()
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


def build_verify_system(
    store_dir: Path,
    *,
    max_major_findings: int = 0,
    max_feedback_rounds: int | None = None,
    sonar_gate_port: SonarGateInputPort | None = None,
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

    Returns:
        ``VerifySystem`` mit allen fuenf Sub-Komponenten und einem
        vollstaendig verdrahteten ``ArtifactManager``.
    """
    from agentkit.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.verify_system.system import VerifySystem

    manager = build_artifact_manager(store_dir)
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        max_feedback_rounds=max_feedback_rounds,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        sonar_gate_port=sonar_gate_port,
        invalidation_sink=build_artifact_invalidation_sink(store_dir),
    )


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
    "build_artifact_invalidation_sink",
    "build_artifact_manager",
    "build_failure_corpus",
    "build_integrity_gate",
    "build_phase_state_residue_probe",
    "build_producer_registry",
    "build_projection_accessor",
    "build_setup_phase_handler",
    "build_setup_preflight_gate",
    "build_skills",
    "build_sonar_gate_port",
    "build_verify_system",
]
