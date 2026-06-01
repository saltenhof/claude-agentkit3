"""ProjectionAccessor: zentraler DB-Owner aller FK-69-Read-Models.

Zentrale Schreib- und Lese-Grenze fuer Projektionsdaten (FK-69 §69.3-§69.4).
Alle FK-69-Schreibstellen MUESSEN ueber diesen Accessor laufen; kein BC darf
direkt in die FK-69-Tabellen schreiben (ZERO DEBT, SINGLE SOURCE OF TRUTH).

Architecture Conformance (AC#7):
- ProjectionAccessor importiert KEINE konkreten Implementierungen aus
  ``agentkit.state_backend.store.facade`` oder ``state_backend.store.*``.
- Er haengt ausschliesslich von injizierten Repository-Protocols ab
  (``ProjectionRepositories`` via Dependency Injection).
- Verdrahtung in ``agentkit.bootstrap.composition_root.build_projection_accessor``.

Quellen:
- FK-69 §69.3 -- Tabellenumfang (genau 7 Tabellen)
- FK-69 §69.4 -- Schreib-Ownership
- FK-69 §69.10.1 -- Reset-Purge-Regel (run_id-scoped)
- FK-69 §69.11.5 -- Konsistenzregel: kein FK-69-Zustand nach Reset
- FK-29 §29.6 -- story_metrics: PostMergeFinalization ist Schema-Owner + Writer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.telemetry.errors import (
    ProjectionKindNotAccessorOwnedError,
    ProjectionRecordTypeMismatchError,
)
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.state_backend.store.projection_repositories import (
        ProjectionRepositories,
    )
    from agentkit.telemetry.projection_records import ProjectionRecord
    from agentkit.verify_system.protocols import LayerResult


# ---------------------------------------------------------------------------
# ProjectionKind (FK-69 §69.3 — exakt 7 Tabellen)
# ---------------------------------------------------------------------------


class ProjectionKind(StrEnum):
    """Kanonische Enum-Werte fuer alle FK-69-Tabellen.

    FK-69 §69.3/§69.4 autorisiert genau 7 Tabellen. WORKFLOW_METRICS ist eine
    FK-68-Tabelle (Telemetrie/Eventing), kein FK-69-Read-Model, und gehoert
    nicht hierher. Story AG3-035 §2.1.1/AK2 ist auf diese 7 Werte angeglichen.
    """

    QA_STAGE_RESULTS = "qa_stage_results"
    QA_FINDINGS = "qa_findings"
    STORY_METRICS = "story_metrics"
    PHASE_STATE_PROJECTION = "phase_state_projection"
    FC_INCIDENTS = "fc_incidents"
    FC_PATTERNS = "fc_patterns"
    FC_CHECK_PROPOSALS = "fc_check_proposals"


# ---------------------------------------------------------------------------
# Write/Read-Ownership (FK-69 §69.4) — expliziter Vertrag statt toter Enum-Werte
# ---------------------------------------------------------------------------
#
# FK-69 §69.3 verlangt alle 7 Tabellennamen in ``ProjectionKind``. Die
# Schreib-/Lese-Ownership (§69.4) liegt aber NICHT durchgaengig beim Accessor:
# der Accessor besitzt die QA-, story_metrics- und (seit AG3-028) FC_INCIDENTS-
# Kinds. Die uebrigen Kinds sind bewusst publiziert (FK-69 §69.3), aber extern
# besessen. Der Accessor weist sie fail-closed mit
# ``ProjectionKindNotAccessorOwnedError`` ab und benennt den Owner — kein
# ``NotImplementedError`` als "halb gebaut".

_ACCESSOR_OWNED_KINDS: frozenset[ProjectionKind] = frozenset(
    {
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionKind.QA_FINDINGS,
        ProjectionKind.STORY_METRICS,
        # AG3-028 KONFLIKT-2: fc_incidents ist nach dieser Story accessor-owned
        # (FK-69 §69.9/§69.14 routen fc_* explizit ueber write_projection). Der
        # fc_incidents-Repo-Adapter lebt accessor-seitig in state_backend/store.
        ProjectionKind.FC_INCIDENTS,
    }
)

# Extern besessene Kinds: publiziert in ProjectionKind (FK-69 §69.3), aber der
# Datenpfad gehoert per Design einem anderen Writer/einer anderen Story.
# FC_PATTERNS/FC_CHECK_PROPOSALS bleiben fail-closed bis zu ihren Folge-Stories
# (PatternPromotion/CheckFactory) — FAIL-CLOSED fuer noch nicht gebaute Tabellen.
_FC_FOLLOWUP_OWNER = (
    "failure-corpus Folge-Story (PatternPromotion/CheckFactory; Tabelle noch nicht gebaut)"
)

_EXTERNALLY_OWNED_KINDS: dict[ProjectionKind, str] = {
    ProjectionKind.PHASE_STATE_PROJECTION: (
        "pipeline_engine.PhaseExecutor (FK-69 §69.4 Write-Ownership)"
    ),
    ProjectionKind.FC_PATTERNS: _FC_FOLLOWUP_OWNER,
    ProjectionKind.FC_CHECK_PROPOSALS: _FC_FOLLOWUP_OWNER,
}


# ---------------------------------------------------------------------------
# ProjectionFilter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionFilter:
    """Optionale Filter-Parameter fuer ``read_projection``.

    Alle Felder sind optional. Nur gesetzte Felder werden als WHERE-Bedingung
    angewendet. Mindestens ``story_id`` oder ``run_id`` wird erwartet fuer
    sinnvolle Abfragen (FAIL-CLOSED wird NICHT auf Filter-Vollstaendigkeit
    geprueft; das ist Sache des Aufrufers).

    Attributes:
        project_key: Projekt-Schluessel (Pflicht auf allen FK-69-Tabellen).
        story_id: Story-ID-Filter.
        run_id: Run-ID-Filter (empfohlen fuer run-scoped Abfragen).
        attempt_no: Attempt-Nummer (nur fuer QA-Tabellen relevant).
        stage_id: Stage-ID (nur fuer QA-Tabellen relevant).
    """

    project_key: str | None = None
    story_id: str | None = None
    run_id: str | None = None
    attempt_no: int | None = None
    stage_id: str | None = None


# ---------------------------------------------------------------------------
# PurgeResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurgeResult:
    """Ergebnis einer ``purge_run``-Operation.

    Attributes:
        purged_rows: Anzahl geloeschter Zeilen pro ``ProjectionKind``.
            Nur Tabellen mit aktivem Schreibpfad werden gezaehlt
            (fc_incidents seit AG3-028 inklusive; fc_patterns/fc_check_proposals
            folgen mit ihren Producer-Stories).
        errors: Fehlermeldungen bei partiellen Fehlern (best-effort).
            Leere Liste bedeutet: alle Tabellen erfolgreich geleert.
    """

    purged_rows: dict[ProjectionKind, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ProjectionAccessor
# ---------------------------------------------------------------------------

def _build_kind_to_record_type() -> dict[ProjectionKind, type]:
    """Erzeugt das Mapping ProjectionKind -> erlaubter Record-Typ (FK-69 §69.4).

    Lazy-Initialisierung: vermeidet zirkulaere Imports zwischen telemetry und
    closure beim Package-Init. StoryMetricsRecord wird erst bei erstem Aufruf
    ueber die exponierte Closure-Top-Surface importiert (AC001: kein direkter
    Zugriff auf das interne Submodul post_merge_finalization.records).

    AG3-028 KONFLIKT-2: ``Incident`` ist der fc_incidents-Record-Typ. Er liegt
    im Blatt-Modul ``failure_corpus.incident`` (importiert nur core_types +
    failure_corpus.types, NICHT telemetry) — analog
    ``verify_system.stage_registry.records``. Damit entsteht kein Zyklus
    ``failure_corpus`` <-> ``telemetry``.
    """
    from agentkit.closure import StoryMetricsRecord as _StoryMetricsRecord
    from agentkit.failure_corpus.incident import Incident as _Incident

    return {
        ProjectionKind.QA_STAGE_RESULTS: QAStageResultRecord,
        ProjectionKind.QA_FINDINGS: QAFindingRecord,
        ProjectionKind.STORY_METRICS: _StoryMetricsRecord,
        ProjectionKind.FC_INCIDENTS: _Incident,
        # PHASE_STATE_PROJECTION hat keinen BC-eigenen Record-Typ in AG3-035;
        # Write-Owner ist pipeline_engine.PhaseExecutor (nicht ueber Accessor).
        # FC_PATTERNS/FC_CHECK_PROPOSALS folgen mit ihren Producer-Stories.
    }


# Mapping: ProjectionKind -> erlaubter Record-Typ (FK-69 §69.4)
# Lazy via _build_kind_to_record_type() bei erstem Zugriff (Anti-circular-import).
_KIND_TO_RECORD_TYPE: dict[ProjectionKind, type] | None = None


def _get_kind_to_record_type() -> dict[ProjectionKind, type]:
    """Gibt das Mapping zurück; initialisiert es beim ersten Aufruf."""
    global _KIND_TO_RECORD_TYPE  # noqa: PLW0603
    if _KIND_TO_RECORD_TYPE is None:
        _KIND_TO_RECORD_TYPE = _build_kind_to_record_type()
    return _KIND_TO_RECORD_TYPE


class ProjectionAccessor:
    """DB-Owner aller FK-69-Read-Models und fc_*-Tabellen (FK-69 §69.3).

    Zentrale Schreib- und Lese-Grenze fuer Projektionsdaten. Alle FK-69-Writer
    MUESSEN ueber ``write_projection`` gehen; kein BC schreibt direkt in
    FK-69-Tabellen.

    Dependency Injection via ``ProjectionRepositories``-Dataclass: der Accessor
    importiert KEINE konkreten Repository-Implementierungen (AC#7).

    Args:
        repositories: Buendel aller FK-69-Repository-Adapter.
    """

    def __init__(self, repositories: ProjectionRepositories) -> None:
        self._repos = repositories

    @staticmethod
    def is_accessor_owned(projection_kind: ProjectionKind) -> bool:
        """True, wenn der Accessor den Write-/Read-Pfad fuer ``projection_kind`` besitzt.

        Expliziter FK-69-§69.4-Vertrag: QA-, story_metrics- und (seit AG3-028)
        FC_INCIDENTS-Kinds sind accessor-besessen. Extern besessene Kinds
        (PHASE_STATE_PROJECTION, FC_PATTERNS, FC_CHECK_PROPOSALS) werden von
        ``write_projection``/``read_projection`` fail-closed mit
        ``ProjectionKindNotAccessorOwnedError`` abgewiesen.

        Args:
            projection_kind: Die zu pruefende FK-69-Tabellen-Familie.

        Returns:
            ``True`` fuer accessor-besessene Kinds, sonst ``False``.
        """
        return projection_kind in _ACCESSOR_OWNED_KINDS

    def write_projection(
        self,
        projection_kind: ProjectionKind,
        record: ProjectionRecord,
    ) -> None:
        """Persistiere einen Projektions-Record via den zustaendigen Repository-Adapter.

        Validiert: Record-Typ muss zum ``projection_kind`` passen.
        FAIL-CLOSED: falscher Record-Typ -> ``ProjectionRecordTypeMismatchError``.

        Args:
            projection_kind: Die FK-69-Tabellen-Familie.
            record: Der zu persistierende Record. Typ muss mit ``projection_kind``
                uebereinstimmen (FK-69 §69.4).

        Raises:
            ProjectionKindNotAccessorOwnedError: Fuer extern besessene
                ProjectionKinds (PHASE_STATE_PROJECTION, FC_PATTERNS, FC_CHECK_PROPOSALS). Subklasse von
                ``NotImplementedError``; benennt den Owner (FK-69 §69.4).
            ProjectionRecordTypeMismatchError: Wenn ``type(record)`` nicht dem
                erwarteten Typ fuer ``projection_kind`` entspricht.
        """
        if projection_kind not in _ACCESSOR_OWNED_KINDS:
            raise ProjectionKindNotAccessorOwnedError(
                kind=projection_kind,
                owner=_EXTERNALLY_OWNED_KINDS.get(
                    projection_kind, "unbekannt (kein FK-69-Owner registriert)"
                ),
            )

        kind_map = _get_kind_to_record_type()
        expected_type = kind_map[projection_kind]

        if not isinstance(record, expected_type):
            raise ProjectionRecordTypeMismatchError(
                kind=projection_kind,
                expected=expected_type,
                received=type(record),
            )

        if projection_kind is ProjectionKind.QA_STAGE_RESULTS:
            assert isinstance(record, QAStageResultRecord)
            self._repos.qa_stage_results.write(record)
        elif projection_kind is ProjectionKind.QA_FINDINGS:
            assert isinstance(record, QAFindingRecord)
            self._repos.qa_findings.write(record)
        elif projection_kind is ProjectionKind.STORY_METRICS:
            # StoryMetricsRecord ist runtime-lazy geladen (Anti-circular-import).
            # isinstance-Check erfolgte oben via _get_kind_to_record_type();
            # Any-cast weicht mypy-Narrowing aus, ohne Laufzeit-Import zu benoetigen.
            self._repos.story_metrics.write(record)  # type: ignore[arg-type]
        elif projection_kind is ProjectionKind.FC_INCIDENTS:
            # Incident ist runtime-lazy geladen (Anti-circular-import via
            # _get_kind_to_record_type oben). isinstance-Check erfolgte dort.
            self._repos.fc_incidents.write(record)  # type: ignore[arg-type]
        else:
            # Should not reach here due to _KIND_TO_RECORD_TYPE check above
            raise NotImplementedError(f"Unhandled ProjectionKind: {projection_kind!r}")

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> list[ProjectionRecord]:
        """Lese Projektions-Records gefiltert aus dem State-Backend.

        Args:
            projection_kind: Die FK-69-Tabellen-Familie.
            filter: Optionale Filter-Parameter (project_key, story_id, run_id, ...).

        Returns:
            Liste von ``ProjectionRecord``-Instanzen (leer wenn keine Treffer).

        Raises:
            ProjectionKindNotAccessorOwnedError: Fuer extern besessene
                ProjectionKinds (PHASE_STATE_PROJECTION, FC_PATTERNS, FC_CHECK_PROPOSALS). Subklasse von
                ``NotImplementedError``; benennt den Owner (FK-69 §69.4).
        """
        if projection_kind is ProjectionKind.QA_STAGE_RESULTS:
            return list(
                self._repos.qa_stage_results.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                    attempt_no=filter.attempt_no,
                    stage_id=filter.stage_id,
                )
            )
        elif projection_kind is ProjectionKind.QA_FINDINGS:
            return list(
                self._repos.qa_findings.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                    attempt_no=filter.attempt_no,
                    stage_id=filter.stage_id,
                )
            )
        elif projection_kind is ProjectionKind.STORY_METRICS:
            return list(
                self._repos.story_metrics.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                )
            )
        elif projection_kind is ProjectionKind.FC_INCIDENTS:
            # AG3-028 KONFLIKT-2: fc_incidents ist accessor-owned. Filter ueber
            # story_id/run_id (die Tabelle traegt kein project_key, Story §2.1.5).
            return list(
                self._repos.fc_incidents.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                )
            )
        # Extern besessene Kinds (PHASE_STATE_PROJECTION, FC_PATTERNS,
        # FC_CHECK_PROPOSALS): fail-closed mit Owner-Benennung. phase_state-Reads
        # laufen direkt via facade.load_phase_state; fc_patterns/fc_check_proposals
        # kommen mit ihren Producer-Folge-Stories.
        raise ProjectionKindNotAccessorOwnedError(
            kind=projection_kind,
            owner=_EXTERNALLY_OWNED_KINDS.get(
                projection_kind, "unbekannt (kein FK-69-Owner registriert)"
            ),
        )

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> PurgeResult:
        """Reset-Purge: entfernt alle FK-69-Projektionsdaten fuer (project_key, story_id, run_id).

        FK-69 §69.10.1 Reset-Regel: ein vollstaendiger Reset entfernt ALLE
        FK-69-Zeilen des betroffenen run_id. Filter-Trick in Queries ist
        ungueltig (FK-69 §69.10.1: "Spaeteres Herausfiltern in Queries ist
        unzulaessig").

        Reset-Purge ist run_id-scoped (FK-69 §69.10.1), nicht bloss
        story_id-scoped. Signatur: ``purge_run(project_key, story_id, run_id)``.
        Story AG3-035 §2.1.3/AK1/AK5 ist auf diese Signatur angeglichen.

        AG3-028 KONFLIKT-2 (FK-41 §41.3 / FK-69 §69.9): der vollstaendige Reset
        eines ``run_id`` entfernt jetzt auch alle ``fc_incidents``-Zeilen dieses
        Runs aktiv (kein Filter-Trick). fc_patterns/fc_check_proposals folgen mit
        ihren Producer-Stories (solange diese Tabellen nicht existieren, gibt es
        dort nichts zu purgen).

        Purge deckt die Tabellen ab, deren Repos/Schreibpfade existieren:
        qa_stage_results, qa_findings, story_metrics, phase_state_projection,
        fc_incidents.

        Args:
            project_key: Projekt-Schluessel.
            story_id: Story-ID des zurueckzusetzenden Runs.
            run_id: Run-ID, dessen alle FK-69-Zeilen aktiv geloescht werden.

        Returns:
            ``PurgeResult`` mit ``purged_rows`` (Zaehlung pro Tabelle) und
            ``errors`` (leer wenn alle ok).
        """
        purged_rows: dict[ProjectionKind, int] = {}
        errors: list[str] = []

        for kind in [
            ProjectionKind.QA_STAGE_RESULTS,
            ProjectionKind.QA_FINDINGS,
            ProjectionKind.STORY_METRICS,
            ProjectionKind.PHASE_STATE_PROJECTION,
            ProjectionKind.FC_INCIDENTS,
        ]:
            try:
                if kind is ProjectionKind.QA_STAGE_RESULTS:
                    count = self._repos.qa_stage_results.purge_run(
                        project_key, story_id, run_id
                    )
                elif kind is ProjectionKind.QA_FINDINGS:
                    count = self._repos.qa_findings.purge_run(
                        project_key, story_id, run_id
                    )
                elif kind is ProjectionKind.STORY_METRICS:
                    count = self._repos.story_metrics.purge_run(
                        project_key, story_id, run_id
                    )
                elif kind is ProjectionKind.PHASE_STATE_PROJECTION:
                    count = self._repos.phase_state_projection.purge_run(
                        project_key, story_id, run_id
                    )
                elif kind is ProjectionKind.FC_INCIDENTS:
                    count = self._repos.fc_incidents.purge_run(
                        project_key, story_id, run_id
                    )
                else:
                    continue  # pragma: no cover
                purged_rows[kind] = count
            except Exception as exc:  # noqa: BLE001
                errors.append(f"purge_run {kind!r}: {type(exc).__name__}: {exc}")

        return PurgeResult(purged_rows=purged_rows, errors=errors)

    def record_qa_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Fachlicher Schreib-Eintrittspunkt fuer den QA-Layer-Batch (FK-69 §69.4, AK4).

        Der ProjectionAccessor ist die EINE fachliche Schreibgrenze fuer die
        FK-69-QA-Read-Models (``qa_stage_results``, ``qa_findings``). Der
        produktive QA-Subflow (implementation/verify) MUSS diese Methode rufen
        statt direkt die ``state_backend``-Fassade -- sonst entsteht eine zweite
        operative Wahrheit am Accessor vorbei (SINGLE SOURCE OF TRUTH, AG3-035 #5).

        Atomaritaet: Die Transaktion (qa_stage_results + qa_findings +
        artifact_records in EINER Driver-Transaktion inkl. Platzhalter-
        artifact_id-Ersetzung) bleibt im Driver gekapselt (FK-69 §69.4,
        Befund D Option i). Der Accessor delegiert an den injizierten
        Batch-Port (``ProjectionRepositories.qa_layer_batch``) und zerteilt die
        Transaktion nicht. Der Port kapselt das gemeinsame Schreiben von
        FK-69-QA-Zeilen und Quell-Artefakt -- der Accessor selbst kennt keine
        ``artifact_records``-Details (AC#7: kein facade-Import in telemetry).

        Args:
            story_dir: Story-Arbeitsverzeichnis.
            layer_results: QA-Layer-Ergebnisse dieses Attempts.
            attempt_nr: Attempt-Nummer.
            projection_dir: Optionales Projektionsverzeichnis (Export).

        Returns:
            Tuple der geschriebenen Artefakt-IDs (vom Driver-Batch).
        """
        return self._repos.qa_layer_batch.persist_layer_artifacts(
            story_dir,
            layer_results=layer_results,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        )


__all__ = [
    "ProjectionAccessor",
    "ProjectionFilter",
    "ProjectionKind",
    "PurgeResult",
]
