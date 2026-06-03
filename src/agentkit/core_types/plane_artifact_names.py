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

#: Wiederkehrende Verzeichnis-Segmente (Sonar S1192 — Literal nur einmal).
_AGENTKIT_DIR = ".agentkit"
_CLAUDE_DIR = ".claude"

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
    _AGENTKIT_DIR,
    "governance",
    "freeze.json",
)

#: Projekt-relativer POSIX-Pfad-String derselben Freeze-Export-Wahrheit (FK-55
#: §55.10.5). Aus ``GOVERNANCE_FREEZE_EXPORT_PARTS`` abgeleitet — kein zweites
#: Literal.
GOVERNANCE_FREEZE_EXPORT_RELPATH: str = "/".join(GOVERNANCE_FREEZE_EXPORT_PARTS)


# ---------------------------------------------------------------------------
# Self-Protection-Pfade (FK-30 §30.5.4 / FK-15 §15.7.1) — SINGLE SOURCE.
#
# Der Governance-Selbstschutz (FK-30 §30.5.4) schuetzt eine feste Menge von
# Hook-Settings-, CCAG-Symlink-, Konfigurations-, Manifest- und Lock-/Edge-
# Bundle-Pfaden vor jeder Mutation durch nicht-offizielle Principals. Die
# zugehoerigen Pfad-Literale leben hier (core_types) als SINGLE SOURCE OF TRUTH,
# damit der geschuetzte ``agentkit.governance``-Namespace (insbesondere der
# ``SelfProtectionGuard``) keine zweite Wahrheit fuer geschuetzte Pfade haelt
# (CLAUDE.md SINGLE SOURCE OF TRUTH / Truth-Boundary, FK-55 §55.4 governance_plane).
#
# Die Pfadklasse ``governance_plane`` (``.agentkit/governance``, ``_temp/governance``,
# ``.agent-guard``) und ``git_internal`` (``.git``) deckt der PathClassifier bereits
# ab (FK-55 §55.4). Die folgenden Pfade liegen NICHT in der Pfadklassifikation,
# weil sie harness-spezifische Bindungspunkte sind — der SelfProtectionGuard ist
# ihr Owner und klassifiziert sie ueber diese Segment-Tupel.
# ---------------------------------------------------------------------------

#: Harness-spezifische Hook-Settings-Dateien (FK-30 §30.5.4 / FK-76 §76.5):
#: Claude-Code ``.claude/settings.json`` (FK-76 §76.5.1) sowie die beiden
#: Codex-Dateien — die allgemeine Codex-Konfiguration ``.codex/config.toml`` und
#: die produktive Codex-HOOK-Settings-Datei ``.codex/hooks.json`` (FK-76 §76.5.2;
#: ``CodexSettingsWriter.settings_path``). FK-30 §30.5.4 fuehrt nur das harness-
#: neutrale „harness-eigenes Aequivalent" und verweist fuer die konkrete Datei auf
#: FK-76 §76.5; dort ist ``.codex/hooks.json`` die normative Hook-Settings-Datei,
#: ueber die der Agent die Hooks deaktivieren koennte — daher ebenfalls geschuetzt.
#: Jeder Eintrag ist ein projekt-relatives POSIX-Segment-Tupel.
SELF_PROTECTION_HOOK_SETTINGS_PARTS: tuple[tuple[str, ...], ...] = (
    (_CLAUDE_DIR, "settings.json"),
    (".codex", "config.toml"),
    (".codex", "hooks.json"),
)

#: CCAG-Regel- und Skill-Symlink-Verzeichnisse (FK-30 §30.5.4 / FK-15 §15.7.1):
#: der kanonische CCAG-Regelpfad ``.agentkit/ccag/rules`` (FK-15 §15.7.1 erste
#: Zeile der geschuetzten Pfade — der eigentliche Owner-Pfad, nicht nur sein
#: Symlink), der harness-spezifische Symlink ``.claude/ccag/rules`` (Symlink auf
#: den kanonischen Pfad) und ``.claude/skills`` (CCAG-/Skill-Symlink-Targets).
#: Verzeichnis-Praefixe — jede Mutation UNTER diesen Pfaden ist geschuetzt.
SELF_PROTECTION_SYMLINK_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    (_AGENTKIT_DIR, "ccag", "rules"),
    (_CLAUDE_DIR, "ccag", "rules"),
    (_CLAUDE_DIR, "skills"),
)

#: Kanonische Governance-Konfigurations-/Manifest-Dateien (FK-30 §30.5.4):
#: ``.agentkit/config/project.yaml`` und ``.installed-manifest.json``.
SELF_PROTECTION_CONFIG_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    (_AGENTKIT_DIR, "config", "project.yaml"),
    (".installed-manifest.json",),
)

__all__ = [
    "CONTENT_PLANE_FILES",
    "CONTROL_PLANE_FILES",
    "GOVERNANCE_FREEZE_EXPORT_PARTS",
    "GOVERNANCE_FREEZE_EXPORT_RELPATH",
    "SELF_PROTECTION_CONFIG_FILE_PARTS",
    "SELF_PROTECTION_HOOK_SETTINGS_PARTS",
    "SELF_PROTECTION_SYMLINK_DIR_PARTS",
]
