"""Wire-string constants for content/control-plane artifact filenames.

Cross-cutting data values (analogous to ``qa_artifact_names``): the canonical
filenames of the content- and control-plane artifacts from FK-55 §55.4. They
live here (core_types), NOT in the protected ``agentkit.governance`` namespace,
because some of these strings are listed in
``concept/formal-spec/truth-boundary-checker/invariants.md``
(``forbidden_json_truth_filenames`` / ``forbidden_json_truth_globs``) and may
not appear literally in protected modules.

Callers:
- ``agentkit.governance.principal_capabilities.paths`` — imports the strings
  for path classification (FK-55 §55.4), keeping the literals out of the
  governance namespace (truth-boundary conformance).

Concept anchors:
- ``FK-55 §55.4`` — path/object classes (content_plane / control_plane).
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` lines 24-54.
"""

from __future__ import annotations

from agentkit.core_types.qa_artifact_names import HANDOVER_FILE

#: Recurring directory segments (Sonar S1192 — literal only once).
_AGENTKIT_DIR = ".agentkit"
_CLAUDE_DIR = ".claude"

#: Content-plane artifact filenames (FK-55 §55.4: context.json, are_bundle.json,
#: handover-/bundle-like content artifacts). Orchestrator-locked.
CONTENT_PLANE_FILES: tuple[str, ...] = (
    "context.json",
    "are_bundle.json",
    "are-bundle.json",
    HANDOVER_FILE,
)

#: Control-plane artifact filenames (FK-55 §55.4: phase_state_projection,
#: markers, reduced control artifacts). Orchestrator-readable.
CONTROL_PLANE_FILES: tuple[str, ...] = (
    "phase_state_projection.json",
    "phase-state-projection.json",
    "marker.json",
    "scope.json",
    "lock.json",
    "mode.json",
)

#: Canonical governance-plane path of the dual conflict-freeze materialization
#: (FK-55 §55.10.5 / FK-31 §31.2.7 / AG3-023): the local, hook-readable
#: ``freeze.json`` projection of the canonical backend freeze record. Lives here
#: (core_types) as SINGLE SOURCE OF TRUTH so that neither the protected
#: ``agentkit.governance`` namespace nor the ``state_backend`` duplicates the
#: path literal (CLAUDE.md SINGLE SOURCE OF TRUTH / truth boundary, FK-55 §55.4
#: governance_plane). Project-relative POSIX path; ``GOVERNANCE_FREEZE_EXPORT_PARTS``
#: is the same truth as a segment tuple for ``pathlib``-based callers.
GOVERNANCE_FREEZE_EXPORT_PARTS: tuple[str, ...] = (
    _AGENTKIT_DIR,
    "governance",
    "freeze.json",
)

#: Project-relative POSIX path string of the same freeze-export truth (FK-55
#: §55.10.5). Derived from ``GOVERNANCE_FREEZE_EXPORT_PARTS`` — no second
#: literal.
GOVERNANCE_FREEZE_EXPORT_RELPATH: str = "/".join(GOVERNANCE_FREEZE_EXPORT_PARTS)


# ---------------------------------------------------------------------------
# Self-protection paths (FK-30 §30.5.4 / FK-15 §15.7.1) — SINGLE SOURCE.
#
# The governance self-protection (FK-30 §30.5.4) protects a fixed set of
# hook-settings, CCAG-symlink, configuration, manifest and lock-/edge-bundle
# paths from any mutation by non-official principals. The associated path
# literals live here (core_types) as SINGLE SOURCE OF TRUTH so that the
# protected ``agentkit.governance`` namespace (in particular the
# ``SelfProtectionGuard``) holds no second truth for protected paths
# (CLAUDE.md SINGLE SOURCE OF TRUTH / truth boundary, FK-55 §55.4 governance_plane).
#
# The path class ``governance_plane`` (``.agentkit/governance``, ``_temp/governance``,
# ``.agent-guard``) and ``git_internal`` (``.git``) are already covered by the
# PathClassifier (FK-55 §55.4). The following paths are NOT in the path
# classification, because they are harness-specific binding points — the
# SelfProtectionGuard is their owner and classifies them via these segment tuples.
# ---------------------------------------------------------------------------

#: Harness-specific hook-settings files (FK-30 §30.5.4 / FK-76 §76.5):
#: Claude Code ``.claude/settings.json`` (FK-76 §76.5.1) as well as the two
#: Codex files — the general Codex configuration ``.codex/config.toml`` and
#: the productive Codex HOOK settings file ``.codex/hooks.json`` (FK-76 §76.5.2;
#: ``CodexSettingsWriter.settings_path``). FK-30 §30.5.4 only mentions the
#: harness-neutral "harness-own equivalent" and refers for the concrete file to
#: FK-76 §76.5; there ``.codex/hooks.json`` is the normative hook-settings file
#: through which the agent could disable the hooks — hence also protected.
#: Each entry is a project-relative POSIX segment tuple.
SELF_PROTECTION_HOOK_SETTINGS_PARTS: tuple[tuple[str, ...], ...] = (
    (_CLAUDE_DIR, "settings.json"),
    (".codex", "config.toml"),
    (".codex", "hooks.json"),
)

#: CCAG-rule and skill symlink directories (FK-30 §30.5.4 / FK-15 §15.7.1):
#: the canonical CCAG rule path ``.agentkit/ccag/rules`` (FK-15 §15.7.1 first
#: line of the protected paths — the actual owner path, not just its symlink),
#: the harness-specific symlink ``.claude/ccag/rules`` (symlink to the canonical
#: path) and ``.claude/skills`` (CCAG-/skill symlink targets).
#: Directory prefixes — any mutation UNDER these paths is protected.
SELF_PROTECTION_SYMLINK_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    (_AGENTKIT_DIR, "ccag", "rules"),
    (_CLAUDE_DIR, "ccag", "rules"),
    (_CLAUDE_DIR, "skills"),
)

# ---------------------------------------------------------------------------
# Install-manifest contract (FK-31 §31.7.4 / AG3-110) — SINGLE SOURCE OF TRUTH.
#
# ``.installed-manifest.json`` (project root) carries the spawn-skill-proof token
# under the top-level key ``agent_spawn_skill_proof``. The producer (BC
# installation-and-bootstrap, ``installer.installed_manifest``) and the read-time
# substitutor (BC agent-skills, ``skills.placeholder``) share this contract; the
# consumer (BC governance-and-guards, AG3-086 prompt-integrity guard) keys on the
# same literals. They live here (core_types, BC-neutral, foundation) so that
# neither agent-skills on installer nor installer on agent-skills must build an
# operative contract dependency (no BC back-edge / cycle avoidance) and no module
# holds a second literal (CLAUDE.md SINGLE SOURCE OF TRUTH). A contract test pins
# these values against the real AG3-086 reader.
# ---------------------------------------------------------------------------

#: Project-root filename of the installed manifest (FK-31 §31.7.4).
INSTALLED_MANIFEST_FILENAME: str = ".installed-manifest.json"

#: Top-level JSON key of the authoritative spawn-skill-proof token (FK-31 §31.7.4).
#: Byte-identical to the AG3-086 consumer key (``governance/runner.py``
#: ``_MANIFEST_SKILL_PROOF_KEY``) — the only valid manifest key for the token.
AGENT_SPAWN_SKILL_PROOF_KEY: str = "agent_spawn_skill_proof"

#: Canonical governance configuration/manifest files (FK-30 §30.5.4):
#: ``.agentkit/config/project.yaml`` and ``.installed-manifest.json``.
SELF_PROTECTION_CONFIG_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    (_AGENTKIT_DIR, "config", "project.yaml"),
    (INSTALLED_MANIFEST_FILENAME,),
)

__all__ = [
    "AGENT_SPAWN_SKILL_PROOF_KEY",
    "CONTENT_PLANE_FILES",
    "CONTROL_PLANE_FILES",
    "GOVERNANCE_FREEZE_EXPORT_PARTS",
    "GOVERNANCE_FREEZE_EXPORT_RELPATH",
    "INSTALLED_MANIFEST_FILENAME",
    "SELF_PROTECTION_CONFIG_FILE_PARTS",
    "SELF_PROTECTION_HOOK_SETTINGS_PARTS",
    "SELF_PROTECTION_SYMLINK_DIR_PARTS",
]
