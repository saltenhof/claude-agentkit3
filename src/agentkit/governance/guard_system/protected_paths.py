"""Protected-Path-Konstanten fuer den QA-Artefakt-Schutz.

Kanonischer Ort: ``agentkit.governance.guard_system.protected_paths``.

Begruendung (FK-31 §31.3 + bc-cut-decisions.md §BC 4 + Refactor-Liste Pkt. 24):
- Die Konstanten konfigurieren den ``qa-artifact-protection``-Hook des
  GuardSystems (FK-31 §31.3, Z. 420-487).
- BC-Cut §BC 4 positioniert das GuardSystem unter ``agentkit.governance.guard_system``.
- Refactor-Pkt. 24: "PROTECTED_ARTIFACTS-Liste gehoert zur Hook-Konfiguration
  in BC 4 (governance.guard_system), nicht zu artifacts oder state_backend".

Truth-Boundary-Disziplin: ``agentkit.governance`` ist
``protected_module_prefix`` laut
``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52.
Die Wire-String-Literale ("structural.json", "decision.json", ...)
duerfen daher nicht **in** diesem Modul stehen. Sie leben als
Cross-Cutting-Konstanten in ``agentkit.core_types.qa_artifact_names``
und werden hier nur zur Tuple-Konfiguration des Hooks importiert.

Quelle:
- FK-31 §31.3 — ``concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md``
  (Z. 420-487)
- ``concept/_meta/bc-cut-decisions.md §BC 4`` — Z. 285-338
- ``concept/_meta/bc-cut-decisions.md §BC 8 Refactor-Liste Pkt. 24`` — Z. 1900
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52
"""

from __future__ import annotations

from agentkit.core_types.plane_artifact_names import (
    GOVERNANCE_FREEZE_EXPORT_RELPATH,
    SELF_PROTECTION_CONFIG_FILE_PARTS,
    SELF_PROTECTION_HOOK_SETTINGS_PARTS,
    SELF_PROTECTION_SYMLINK_DIR_PARTS,
)
from agentkit.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    CHANGE_FRAME_FILE,
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)
from agentkit.state_backend.paths import STATE_DB_DIR, STATE_DB_FILE

#: Schutzliste aller QA-Artefakt-Dateinamen (FK-31 §31.3 + FK-27 §27.7).
#: Schreibzugriff durch Sub-Agents auf diese Dateien ist im GuardSystem
#: geblockt, solange der QA-Artifact-Lock aktiv ist (FK-31 §31.3).
#: Enthaelt alle 6 FK-27-Artefakte + das Guardrail-Artefakt.
PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
)

#: Lokaler Conflict-Freeze-Export (AG3-032, FK-55 §55.10.5 / FK-31 §31.2.7).
#: Projekt-relativer Pfad der dualen Freeze-Materialisierung; gehoert zur
#: ``governance_plane`` (FK-55 §55.4) und darf nur ueber offizielle Servicepfade
#: mutiert werden. Hier als geschuetzter Governance-Pfad registriert (AG3-023).
#: Das Pfad-Literal lebt in ``core_types.plane_artifact_names`` (SINGLE SOURCE OF
#: TRUTH / Truth-Boundary) und wird hier nur re-exportiert — kein Literal in
#: diesem geschuetzten governance-Modul.
PROTECTED_GOVERNANCE_FREEZE_EXPORT: str = GOVERNANCE_FREEZE_EXPORT_RELPATH

#: Exploration change-frame artifact (FK-23 §23.4.3).
#: The exploration worker (AG3-055, BC ``agent-skills``) writes this file to
#: ``_temp/qa/{story_id}/change_frame.json``; AG3-045 defines the schema + the
#: protection mechanics. This constant is the SINGLE SOURCE OF TRUTH for the
#: protected change-frame filename and is consumed EFFECTIVELY by the
#: ``ArtifactGuard`` (``governance.guards.artifact_guard``): a sub-agent write to
#: this file is blocked once the change-frame is **frozen** (guard-context signal
#: ``change_frame_frozen``) OR the freeze state is **unknown** (missing /
#: unreadable ``change_frame_freeze_known``) -- fail-closed (deep-review #5,
#: ARCH-48 default deny). The freeze trigger (setting ``frozen: true`` + feeding
#: ``change_frame_frozen`` and ``change_frame_freeze_known`` into the guard
#: context) is owned by AG3-047 (FK-23 §23.4.3: "protection runs via the hook
#: mechanism, not via file permissions"); a change-frame explicitly known to be
#: NOT frozen (before freeze, FK-25 §25.4.2) is editable, hence no block. The
#: protection mechanics are complete here / in the guard (AG3-045 AC8). The path
#: literal lives in ``core_types.qa_artifact_names`` (truth boundary -- no literal
#: in the protected governance namespace).
PROTECTED_CHANGE_FRAME: str = CHANGE_FRAME_FILE

# ---------------------------------------------------------------------------
# Self-Protection-Pfad-Registry (FK-30 §30.5.4 / FK-15 §15.7.1).
#
# Der ``SelfProtectionGuard`` (AG3-033) bezieht seine geschuetzten Pfade
# ausschliesslich von hier — kein governance-Modul haelt eine zweite Wahrheit
# fuer Protected-Pfade (CLAUDE.md SINGLE SOURCE OF TRUTH; durchgesetzt von
# ``scripts/ci/check_concept_code_contracts.py``). Die Pfad-Literale leben in
# ``core_types.plane_artifact_names`` bzw. ``state_backend.paths`` und werden hier
# nur re-exportiert / zu Konfigurations-Tupeln zusammengezogen.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Self-Protection-ZONEN (FK-30 §30.5.4 / FK-15 §15.7.x).
#
# Der ``SelfProtectionGuard`` (AG3-033) wendet je geschuetzter Zone eine
# eigene, konzept-verankerte Principal-Whitelist an (FK-31 §31.5.4 implizit per
# FK-15 §15.7.3 „Nur Pipeline-Skripte (Zone 2) schreiben Lock-Records"). Kein
# pauschaler Trio-Whitelist mehr. Die Zonen werden hier als Pfad-Mengen
# definiert; die Zone→Principal-Policy ist Owner des Guards (Geschaeftslogik).
# ---------------------------------------------------------------------------

#: ZONE „harness" — harness-spezifische Hook-Settings-Dateien (FK-30 §30.5.4 /
#: FK-76 §76.5) und CCAG-/Skill-Symlink-Verzeichnisse (FK-15 §15.7.1). Diese
#: Bindungspunkte werden ausschliesslich vom Installer (FK-30 §30.3.1 „Aufrufer:
#: Installer"; FK-50 CP 9) ueber ``register_hooks`` materialisiert — ein
#: deterministischer Zone-2-Prozess. Exakte Datei-Tupel.
SELF_PROTECTION_HARNESS_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HOOK_SETTINGS_PARTS,
)

#: ZONE „harness" — Verzeichnis-Praefixe (CCAG-Regeln / Skill-Symlinks, FK-15
#: §15.7.1). Jede Mutation UNTER einem dieser Verzeichnisse gehoert zur
#: harness-Zone.
SELF_PROTECTION_HARNESS_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_SYMLINK_DIR_PARTS,
)

#: ZONE „governance" — Governance-Konfiguration / Installer-Manifest (FK-30
#: §30.5.4: ``.agentkit/config/project.yaml``, ``.installed-manifest.json``).
#: Diese gehoeren — wie Lock-Records und Edge-Bundles — zur Governance-Wahrheit
#: und unterliegen derselben Pipeline-/Admin-Whitelist (FK-15 §15.4.1 Zeile
#: „Zentralen Workflow-State mutieren" / „Lock-Record erstellen/beenden").
SELF_PROTECTION_GOVERNANCE_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_CONFIG_FILE_PARTS,
)

#: Aggregat aller geschuetzten exakten Datei-Pfade (Rueckwaerts-Kompatibilitaet /
#: „ist dieser Pfad ueberhaupt geschuetzt"-Pruefung). Vereinigung der harness- und
#: governance-Zonen.
SELF_PROTECTION_PROTECTED_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HARNESS_FILE_PARTS,
    *SELF_PROTECTION_GOVERNANCE_FILE_PARTS,
)

#: Aggregat aller geschuetzten Verzeichnis-Praefixe (FK-30 §30.5.4). Derzeit
#: deckungsgleich mit der harness-Zone (CCAG-/Skill-Symlinks); die
#: Governance-Plane-Verzeichnisse (``_temp/governance``, ``.agent-guard``, ``.git``)
#: deckt der ``PathClassifier`` ueber Pfadklassen ab, nicht ueber diese Tupel.
SELF_PROTECTION_PROTECTED_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HARNESS_DIR_PARTS,
)

#: Story-Backend-Verzeichnis-Segment (``.agentkit``) und SQLite-Suffixe, ueber
#: die der ``StoryCreationGuard`` (AG3-033) einen direkten Story-DB-INSERT
#: erkennt (FK-21 §21.13 / FK-31 §31.5). Quelle: ``state_backend.paths`` — kein
#: zweites Literal im governance-Modul.
STORY_DB_DIR_SEGMENT: str = STATE_DB_DIR
STORY_DB_SUFFIXES: tuple[str, ...] = tuple(
    sorted({"." + STATE_DB_FILE.rsplit(".", 1)[-1], ".sqlite"})
)

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "PROTECTED_CHANGE_FRAME",
    "PROTECTED_GOVERNANCE_FREEZE_EXPORT",
    "PROTECTED_QA_ARTIFACTS",
    "SELF_PROTECTION_GOVERNANCE_FILE_PARTS",
    "SELF_PROTECTION_HARNESS_DIR_PARTS",
    "SELF_PROTECTION_HARNESS_FILE_PARTS",
    "SELF_PROTECTION_PROTECTED_DIR_PARTS",
    "SELF_PROTECTION_PROTECTED_FILE_PARTS",
    "STORY_DB_DIR_SEGMENT",
    "STORY_DB_SUFFIXES",
    "VERIFY_DECISION_FILE",
]
