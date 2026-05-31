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

from agentkit.telemetry.errors import ProjectionRecordTypeMismatchError
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from agentkit.state_backend.store.projection_repositories import (
        ProjectionRepositories,
    )
    from agentkit.telemetry.projection_records import ProjectionRecord


# ---------------------------------------------------------------------------
# ProjectionKind (FK-69 §69.3 — exakt 7 Tabellen)
# ---------------------------------------------------------------------------


class ProjectionKind(StrEnum):
    """Kanonische Enum-Werte fuer alle FK-69-Tabellen.

    DRIFT 1 (aufgeloest): FK-69 §69.3/§69.4 autorisiert genau 7 Tabellen.
    Story-Skizze §2.1.1 nannte faelschlich 8 Werte inkl. WORKFLOW_METRICS --
    das ist NICHT in FK-69 und wird hier weggelassen.
    """

    QA_STAGE_RESULTS = "qa_stage_results"
    QA_FINDINGS = "qa_findings"
    STORY_METRICS = "story_metrics"
    PHASE_STATE_PROJECTION = "phase_state_projection"
    FC_INCIDENTS = "fc_incidents"
    FC_PATTERNS = "fc_patterns"
    FC_CHECK_PROPOSALS = "fc_check_proposals"


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
            (fc_*-Purge vertagt auf AG3-028).
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
    """
    from agentkit.closure import StoryMetricsRecord as _StoryMetricsRecord

    return {
        ProjectionKind.QA_STAGE_RESULTS: QAStageResultRecord,
        ProjectionKind.QA_FINDINGS: QAFindingRecord,
        ProjectionKind.STORY_METRICS: _StoryMetricsRecord,
        # PHASE_STATE_PROJECTION hat keinen BC-eigenen Record-Typ in AG3-035;
        # Write-Owner ist pipeline_engine.PhaseExecutor (nicht ueber Accessor).
        # FC_*-Record-Typen fehlen noch; AG3-028 bringt fc-Repos + Schreibpfade.
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
            ProjectionRecordTypeMismatchError: Wenn ``type(record)`` nicht dem
                erwarteten Typ fuer ``projection_kind`` entspricht.
            NotImplementedError: Fuer ProjectionKinds ohne aktiven Schreibpfad
                in AG3-035 (PHASE_STATE_PROJECTION, FC_*).
        """
        kind_map = _get_kind_to_record_type()
        expected_type = kind_map.get(projection_kind)
        if expected_type is None:
            raise NotImplementedError(
                f"ProjectionKind {projection_kind!r} hat keinen aktiven "
                "Schreibpfad in AG3-035. "
                f"PHASE_STATE_PROJECTION: Write-Owner ist pipeline_engine.PhaseExecutor. "
                f"FC_*-Schreibpfade: vertagt auf AG3-028 (fc-Repos + Schreibpfad dort)."
            )

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
            NotImplementedError: Fuer ProjectionKinds ohne aktiven Lese-Pfad
                in AG3-035 (FC_*).
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
        elif projection_kind is ProjectionKind.PHASE_STATE_PROJECTION:
            # Read-Pfad via ProjectionAccessor fuer phase_state_projection:
            # derzeit nicht implementiert (Write-Owner ist PhaseExecutor, kein
            # eigenstaendiger Read-Accessor in AG3-035 vorgesehen).
            raise NotImplementedError(
                "PHASE_STATE_PROJECTION-Read via ProjectionAccessor ist in "
                "AG3-035 nicht implementiert. Reads laufen direkt via "
                "facade.load_phase_state / load_phase_state_global."
            )
        else:
            raise NotImplementedError(
                f"FC_*-Read-Pfade (fc_incidents, fc_patterns, fc_check_proposals) "
                f"sind mit den fc-Repos nach AG3-028 vertagt. "
                f"ProjectionKind: {projection_kind!r}"
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

        DRIFT 2 (aufgeloest, AG3-035): Reset-Purge ist run_id-scoped, nicht
        bloss story_id-scoped. Story-Skizze ``purge_for_story(story_id)`` war
        unterspezifiziert. Signatur: ``purge_run(project_key, story_id, run_id)``.

        DRIFT 3 (vertagt, AG3-028): fc_*-Purge wird mit dem fc-Schreibpfad
        nach AG3-028 implementiert. Per FK-69 §69.9 MUSS ein zurueckgesetzter
        run_id seine fc_incidents entfernen und fc_patterns neu berechnen --
        das wird mit den fc-Repos in AG3-028 implementiert.
        # DRIFT-AG3-028

        Purge deckt die Tabellen ab, deren Repos/Schreibpfade in AG3-035
        existieren: qa_stage_results, qa_findings, story_metrics,
        phase_state_projection.

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
                else:
                    continue  # pragma: no cover
                purged_rows[kind] = count
            except Exception as exc:  # noqa: BLE001
                errors.append(f"purge_run {kind!r}: {type(exc).__name__}: {exc}")

        return PurgeResult(purged_rows=purged_rows, errors=errors)

    def write_qa_layer_batch(
        self,
        stage_result: QAStageResultRecord,
        finding_records: list[QAFindingRecord],
    ) -> None:
        """Schreibe FK-69-QA-Projektionsdaten fuer einen Layer-Batch atomar.

        Dies ist der Einzel-Layer-Schreibpfad fuer den ProjectionAccessor.
        Schreibt stage_result und alle finding_records via die injizierten Repos.
        Der Accessor ist damit die EINE Schreibgrenze fuer FK-69-QA-Read-Models
        (FK-69 §69.4, SINGLE SOURCE OF TRUTH, Befund D AG3-035 Remediation).

        Hinweis zur Transaktionalitaet: Dieser Pfad erzeugt pro write() eine
        eigene Transaktion (kein gemeinsamer Transaktionskontext).
        Der atomare Batch-Pfad innerhalb der Driver-Transaktion
        (``persist_layer_artifact_rows``) nutzt die within-conn-Methoden der
        konkreten Repo-Implementierungen direkt -- die Transaktion bleibt im
        Driver (FK-69 §69.4, Befund D Option i).

        Args:
            stage_result: QA-Stage-Ergebnis-Record fuer diesen Layer.
            finding_records: Liste aller QA-Finding-Records fuer diesen Layer.
        """
        self._repos.qa_stage_results.write(stage_result)
        for finding in finding_records:
            self._repos.qa_findings.write(finding)


__all__ = [
    "ProjectionAccessor",
    "ProjectionFilter",
    "ProjectionKind",
    "PurgeResult",
]
