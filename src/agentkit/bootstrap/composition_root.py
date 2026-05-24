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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactManager,
    EnvelopeValidator,
    ProducerRegistry,
)
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.verify_system.register import register_verify_producers

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.governance.repository import SetupContextRepository
    from agentkit.verify_system.system import VerifySystem


def build_producer_registry() -> ProducerRegistry:
    """Erzeugt eine frische ``ProducerRegistry`` und ruft alle bekannten
    BC-Init-Hooks auf.

    Aktueller Stand (AG3-023): nur ``register_verify_producers`` ist
    angebunden. Weitere BC-Init-Hooks (worker, telemetry, governance,
    closure ...) werden in ihren Folgestories analog ergaenzt.

    Returns:
        Eine ``ProducerRegistry`` mit allen heute bekannten Producern.

    Notes:
        Reihenfolge der Init-Hooks ist deterministisch (BC-alphabetisch
        bzw. Capability-Reihenfolge); Verify ist heute die einzige
        registrierte Quelle.
    """
    registry = ProducerRegistry()
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
) -> VerifySystem:
    """Erzeugt einen vollstaendig verdrahteten ``VerifySystem``.

    Composition-Root fuer die QA-Subflow-Top-Surface (AG3-026):
    instanziiert alle fuenf Sub-Komponenten und verdrahtet einen echten
    ``ArtifactManager`` (inkl. ProducerRegistry) als Persistenz-Facade.

    Args:
        store_dir: Basisverzeichnis des State-Backends. Wird an
            ``build_artifact_manager`` durchgereicht.
        max_major_findings: Schwellenwert fuer die PolicyEngine (Anzahl
            tolerierter MAJOR-Findings; 0 = jedes MAJOR blockiert).

    Returns:
        ``VerifySystem`` mit allen fuenf Sub-Komponenten und einem
        vollstaendig verdrahteten ``ArtifactManager``.
    """
    from agentkit.verify_system.system import VerifySystem

    manager = build_artifact_manager(store_dir)
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        artifact_manager=manager,
    )


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


__all__ = [
    "build_artifact_manager",
    "build_integrity_gate",
    "build_producer_registry",
    "build_setup_preflight_gate",
    "build_verify_system",
]
