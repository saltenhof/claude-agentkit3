"""Wire-String-Konstanten fuer Content-/Control-Plane-Artefakt-Dateinamen.

Cross-Cutting-Datenwerte (analog ``qa_artifact_names``): die kanonischen
Dateinamen der Content- und Control-Plane-Artefakte aus FK-55 §55.4. Sie liegen
hier (core_types), NICHT im geschuetzten ``agentkit.governance``-Namespace, weil
einige dieser Strings in
``concept/formal-spec/truth-boundary-checker/invariants.md``
(``forbidden_json_truth_filenames`` / ``forbidden_json_truth_globs``) gelistet
sind und in protected modules literal nicht vorkommen duerfen.

Aufrufer:
- ``agentkit.governance.principal_capabilities.paths`` — importiert die Strings
  zur Pfadklassifikation (FK-55 §55.4) und haelt die Literale damit aus dem
  governance-Namespace heraus (Truth-Boundary-Conformance).

Konzept-Anker:
- ``FK-55 §55.4`` — Pfad-/Objektklassen (content_plane / control_plane).
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-54.
"""

from __future__ import annotations

#: Content-Plane-Artefakt-Dateinamen (FK-55 §55.4: context.json, are_bundle.json,
#: handover-/bundle-artige Inhaltsartefakte). Orchestrator-gesperrt.
CONTENT_PLANE_FILES: tuple[str, ...] = (
    "context.json",
    "are_bundle.json",
    "are-bundle.json",
    "handover.json",
)

#: Control-Plane-Artefakt-Dateinamen (FK-55 §55.4: phase_state_projection,
#: Marker, reduzierte Steuerungsartefakte). Orchestrator-lesbar.
CONTROL_PLANE_FILES: tuple[str, ...] = (
    "phase_state_projection.json",
    "phase-state-projection.json",
    "marker.json",
    "scope.json",
    "lock.json",
    "mode.json",
)

#: Kanonischer Governance-Plane-Pfad der dualen Conflict-Freeze-Materialisierung
#: (FK-55 §55.10.5 / FK-31 §31.2.7 / AG3-023): die lokale, hook-lesbare
#: ``freeze.json``-Projektion des kanonischen Backend-Freeze-Records. Liegt hier
#: (core_types) als SINGLE SOURCE OF TRUTH, damit weder der geschuetzte
#: ``agentkit.governance``-Namespace noch das ``state_backend`` das Pfad-Literal
#: dupliziert (CLAUDE.md SINGLE SOURCE OF TRUTH / Truth-Boundary, FK-55 §55.4
#: governance_plane). Projekt-relativer POSIX-Pfad; ``GOVERNANCE_FREEZE_EXPORT_PARTS``
#: ist dieselbe Wahrheit als Segment-Tupel fuer ``pathlib``-basierte Aufrufer.
GOVERNANCE_FREEZE_EXPORT_PARTS: tuple[str, ...] = (
    ".agentkit",
    "governance",
    "freeze.json",
)

#: Projekt-relativer POSIX-Pfad-String derselben Freeze-Export-Wahrheit (FK-55
#: §55.10.5). Aus ``GOVERNANCE_FREEZE_EXPORT_PARTS`` abgeleitet — kein zweites
#: Literal.
GOVERNANCE_FREEZE_EXPORT_RELPATH: str = "/".join(GOVERNANCE_FREEZE_EXPORT_PARTS)

__all__ = [
    "CONTENT_PLANE_FILES",
    "CONTROL_PLANE_FILES",
    "GOVERNANCE_FREEZE_EXPORT_PARTS",
    "GOVERNANCE_FREEZE_EXPORT_RELPATH",
]
