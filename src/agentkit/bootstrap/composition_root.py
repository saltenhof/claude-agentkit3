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
    from pathlib import Path

    from agentkit.failure_corpus import FailureCorpus
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.governance.repository import SetupContextRepository
    from agentkit.skills import Skills
    from agentkit.telemetry.projection_accessor import ProjectionAccessor
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
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        sonar_gate_port=sonar_gate_port,
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


def build_integrity_gate() -> IntegrityGate:
    """Erzeugt einen vollstaendig verdrahteten ``IntegrityGate``.

    Composition-Root fuer die Closure-Phase (AG3-031 Pass-5 Fix E9):
    Instanziiert ``StateBackendIntegrityGateStateAdapter`` und reicht ihn
    als ``state_port`` an ``IntegrityGate`` weiter.  Consuminerende Module
    duerfen nicht selbst aus ``state_backend.store`` importieren.

    Returns:
        ``IntegrityGate`` mit dem State-Backend-Adapter als State-Port.
    """
    from agentkit.governance.integrity_gate import IntegrityGate as _IntegrityGate
    from agentkit.state_backend.store.integrity_gate_repository import (
        StateBackendIntegrityGateStateAdapter,
    )

    return _IntegrityGate(state_port=StateBackendIntegrityGateStateAdapter())


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
    "build_artifact_manager",
    "build_failure_corpus",
    "build_integrity_gate",
    "build_producer_registry",
    "build_projection_accessor",
    "build_setup_preflight_gate",
    "build_skills",
    "build_sonar_gate_port",
    "build_verify_system",
]
