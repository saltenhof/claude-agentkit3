"""Skills top-surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Implements the four top-level methods defined in FK-43 §43.1 and FK-50 CP8:

* ``bind_skill``        — symlink-based harness binding (FK-43 §43.4.1)
* ``resolve_binding``   — lookup of an existing binding
* ``list_bound_skills`` — project-scoped listing
* ``collect_quality_metrics`` — contract slot; raises NotImplementedError
  until the telemetry follow-up story (THEME-007).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.skills.binding import (
    HarnessKind,
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.skills.bundle_store import SkillProfile
from agentkit.skills.errors import (
    SkillBindingFailedError,
    SkillBundleDigestMismatchError,
    SkillProfileNotSupportedError,
)

if TYPE_CHECKING:
    from pathlib import Path  # noqa: TC003  # used only in annotations (from __future__ annotations)

    from agentkit.skills.bundle_store import SkillBundleStore
    from agentkit.skills.repository import SkillBindingRepository

# ---------------------------------------------------------------------------
# Harness-specific binding paths  (FK-43 §43.4.1, FK-30 §30.11)
# ---------------------------------------------------------------------------

def _harness_skill_dir(project_root: Path, harness: HarnessKind) -> Path:
    """Return the harness-specific skills directory within *project_root*.

    * Claude Code: ``{project_root}/.claude/skills/``
    * Codex:       ``{project_root}/.codex/skills/``
      (FK-30 §30.11 Codex-Bindungspunkt; path convention follows FK-30
      §30.11 as interpreted in AG3-027; update if FK-30 mandates a
      different path in a future revision)
    """
    if harness == HarnessKind.CLAUDE_CODE:
        return project_root / ".claude" / "skills"
    if harness == HarnessKind.CODEX:
        return project_root / ".codex" / "skills"  # FK-30 §30.11 Codex-Bindungspunkt
    # Exhaustive — StrEnum ensures only known values pass.
    msg = f"Unknown harness: {harness}"  # pragma: no cover
    raise ValueError(msg)  # pragma: no cover


def _verify_manifest_digest(
    skill_name: str,
    bundle_info: dict[str, object],
    bundle_root: Path,
) -> None:
    """Verify ``manifest_digest`` if declared (FK-43 §43.5.2).

    The digest is computed over the manifest with the ``manifest_digest``
    field excluded (otherwise self-reference would be impossible). When the
    manifest declares no ``manifest_digest`` the check is skipped — AG3-048
    will tighten this by sourcing the expected digest from the bundle-store
    pin record.
    """
    import json

    expected = bundle_info.get("manifest_digest")
    if not isinstance(expected, str):
        return
    payload_without_digest = {k: v for k, v in bundle_info.items() if k != "manifest_digest"}
    canonical = json.dumps(payload_without_digest, sort_keys=True).encode("utf-8")
    actual = hashlib.sha256(canonical).hexdigest()
    if actual == expected:
        return
    raise SkillBundleDigestMismatchError(
        f"Bundle manifest digest mismatch for '{skill_name}'",
        detail={
            "skill_name": skill_name,
            "bundle_root": str(bundle_root),
            "expected": expected,
            "actual": actual,
        },
    )


def _validate_bind_paths(project_root: Path, bundle_root: Path) -> None:
    """Validate that ``project_root`` and ``bundle_root`` exist (fail-closed)."""
    if not project_root.is_dir():
        raise SkillBindingFailedError(
            f"project_root does not exist or is not a directory: {project_root}",
            detail={"project_root": str(project_root)},
        )
    if not bundle_root.is_dir():
        raise SkillBindingFailedError(
            f"bundle_root does not exist or is not a directory: {bundle_root}",
            detail={"bundle_root": str(bundle_root)},
        )


def _create_harness_symlinks(
    skill_name: str,
    bundle_root: Path,
    project_root: Path,
    harnesses: tuple[HarnessKind, ...],
) -> None:
    """Create one symlink per harness; rolls back partial state on failure.

    Invariant ``project_binding_is_symlink_only``: never falls back to file copy.
    """
    import contextlib

    created: list[Path] = []
    try:
        for harness in harnesses:
            skills_dir = _harness_skill_dir(project_root, harness)
            skills_dir.mkdir(parents=True, exist_ok=True)
            link_path = skills_dir / skill_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            try:
                link_path.symlink_to(bundle_root)
            except OSError as exc:
                raise SkillBindingFailedError(
                    f"Failed to create symlink for skill '{skill_name}' "
                    f"(harness={harness}). On Windows, Developer Mode must "
                    f"be enabled or the process must have "
                    f"SeCreateSymbolicLinkPrivilege. Original error: {exc}",
                    detail={
                        "skill_name": skill_name,
                        "harness": str(harness),
                        "link_path": str(link_path),
                        "bundle_root": str(bundle_root),
                        "os_error": str(exc),
                    },
                ) from exc
            created.append(link_path)
    except SkillBindingFailedError:
        for sl in created:
            with contextlib.suppress(OSError):
                sl.unlink(missing_ok=True)
        raise


def _verify_harness_symlinks(
    skill_name: str,
    project_root: Path,
    harnesses: tuple[HarnessKind, ...],
) -> None:
    """Post-bind verification: each harness symlink must exist."""
    for harness in harnesses:
        link_path = _harness_skill_dir(project_root, harness) / skill_name
        if not link_path.is_symlink():
            raise SkillBindingFailedError(
                f"Post-bind verification failed: symlink missing for "
                f"skill '{skill_name}' (harness={harness})",
                detail={"skill_name": skill_name, "link_path": str(link_path)},
            )


def _read_bundle_manifest(bundle_root: Path) -> dict[str, object]:
    """Parse the optional ``manifest.json`` at *bundle_root*.

    Returns an empty dict when no manifest exists. Malformed JSON raises
    ``SkillBindingFailedError`` (fail-closed; a bundle with broken manifest
    must not be bound).
    """
    import json

    manifest = bundle_root / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillBindingFailedError(
            f"Failed to parse manifest.json at {manifest}: {exc}",
            detail={"manifest_path": str(manifest)},
        ) from exc
    if not isinstance(data, dict):
        raise SkillBindingFailedError(
            f"manifest.json at {manifest} must be a JSON object",
            detail={"manifest_path": str(manifest)},
        )
    return data


def _binding_id_for(project_key: str, skill_name: str) -> str:
    """Deterministic binding id from (project_key, skill_name)."""
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # URL namespace
    return str(uuid.uuid5(namespace, f"{project_key}:{skill_name}"))


# ---------------------------------------------------------------------------
# SkillQualityMetric placeholder type
# ---------------------------------------------------------------------------

class SkillQualityMetric:
    """Result type for ``Skills.collect_quality_metrics``.

    Defined here as a forward-compatible placeholder. The full model
    (telemetry projections, failure-corpus analysis) is implemented in a
    follow-up story (THEME-007 / FK-43 §43.6.2).
    """


# ---------------------------------------------------------------------------
# Skills top-surface
# ---------------------------------------------------------------------------

class Skills:
    """Top-surface for the agent-skills BC (FK-43, bc-cut-decisions.md §BC 11).

    Provides the four canonical top-level methods:

    * ``bind_skill`` — symlink-based project binding with multi-harness support
    * ``resolve_binding`` — lookup
    * ``list_bound_skills`` — project-scoped listing
    * ``collect_quality_metrics`` — raises NotImplementedError until THEME-007

    Invariant enforced: ``project_binding_is_symlink_only``
    (formal.skills-and-bundles.invariants). File-copying is forbidden.

    Args:
        bundle_store: Systemwide registry of available skill bundles.
        binding_repo: Storage port for ``SkillBinding`` persistence.
    """

    def __init__(
        self,
        bundle_store: SkillBundleStore,
        binding_repo: SkillBindingRepository,
    ) -> None:
        self._bundle_store = bundle_store
        self._binding_repo = binding_repo

    # ------------------------------------------------------------------
    # bind_skill
    # ------------------------------------------------------------------

    def bind_skill(
        self,
        skill_name: str,
        bundle_root: Path,
        project_root: Path,
    ) -> None:
        """Bind a skill bundle to a project via harness-specific symlinks.

        Pass-2 (Codex giftig 2026-05-24): strikt FK-43 §43.4.1 + FK-50 CP8 —
        Signatur ist genau die drei Pflicht-Parameter; keine zusaetzlichen
        Kwargs. Symlinks werden pro Pflicht-Harness erzeugt (Claude Code +
        Codex aus FK-43 §43.4.1 AK4; Multi-Harness-Pflicht ab Tag 1).

        Lifecycle (formal.skills-and-bundles.state-machine):
        REQUESTED -> PROFILE_RESOLVED -> BUNDLE_SELECTED -> BOUND -> VERIFIED.
        Profile-/Bundle-Resolution ist Caller-Vorarbeit (FK-50 CP6/CP7);
        ``bind_skill`` empfaengt einen konkreten ``bundle_root`` und durchlaeuft
        die Lifecycle-Stages deterministisch zur Persistenz.

        Invariant ``project_binding_is_symlink_only``: no file-copying is
        permitted. If ``Path.symlink_to`` fails on Windows (Developer Mode
        required), ``SkillBindingFailedError`` is raised immediately.

        Args:
            skill_name: Logical skill name (e.g. ``"implement"``).
            bundle_root: Absolute path to the bundle directory.
            project_root: Root of the target project. Used as the source for
                ``SkillBinding.project_key`` (stem of the path) — consistent
                with ``resolve_binding`` / ``list_bound_skills`` lookup.

        Raises:
            SkillBindingFailedError: When ``project_root`` or ``bundle_root``
                do not exist, or when a symlink cannot be created (e.g.
                Windows without Developer Mode).
            SkillBundleDigestMismatchError: When the bundle's manifest digest
                does not match the manifest's declared digest field.
            SkillProfileNotSupportedError: When the bundle declares variants
                but the skill_name resolves to no supported profile.
        """
        _validate_bind_paths(project_root, bundle_root)
        bundle_info = _read_bundle_manifest(bundle_root)
        self._validate_profile_support(skill_name, bundle_info, bundle_root)
        _verify_manifest_digest(skill_name, bundle_info, bundle_root)

        # Effective keys: source of truth = project_root.stem
        # (consistent with resolve_binding / list_bound_skills; FK-43 §43.1)
        effective_project_key = project_root.stem
        effective_bundle_id = str(bundle_info.get("bundle_id") or bundle_root.stem)
        effective_bundle_version = str(bundle_info.get("bundle_version") or "0.0.0")
        pinned_at = datetime.now(tz=UTC)
        bid = _binding_id_for(effective_project_key, skill_name)

        # Symlink creation per harness; multi-harness Pflicht ab Tag 1
        # (FK-43 §43.4.1 AK4).
        harnesses: tuple[HarnessKind, ...] = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)
        _create_harness_symlinks(skill_name, bundle_root, project_root, harnesses)

        canonical_target = (
            _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / skill_name
        )
        binding = SkillBinding(
            binding_id=bid,
            project_key=effective_project_key,
            skill_name=skill_name,
            bundle_id=effective_bundle_id,
            bundle_version=effective_bundle_version,
            target_path=canonical_target,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=pinned_at,
        )
        self._binding_repo.save(binding)

        _verify_harness_symlinks(skill_name, project_root, harnesses)

        # Update status to VERIFIED.
        verified_binding = SkillBinding(
            binding_id=bid,
            project_key=effective_project_key,
            skill_name=skill_name,
            bundle_id=effective_bundle_id,
            bundle_version=effective_bundle_version,
            target_path=canonical_target,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=pinned_at,
        )
        self._binding_repo.save(verified_binding)

    @staticmethod
    def _validate_profile_support(
        skill_name: str,
        bundle_info: dict[str, object],
        bundle_root: Path,
    ) -> None:
        """Raise ``SkillProfileNotSupportedError`` when the bundle's declared
        variants do not cover ``skill_name``'s profile (FK-43 §43.4.1)."""
        variants = bundle_info.get("variants")
        if not isinstance(variants, dict) or not variants:
            return  # Manifests without explicit variants are treated as universal.
        if skill_name in variants.values():
            return
        # Check whether any known SkillProfile maps to this skill_name.
        for profile in SkillProfile:
            if variants.get(profile.value) == skill_name:
                return
        raise SkillProfileNotSupportedError(
            f"Bundle at {bundle_root} declares variants {sorted(variants)} "
            f"but none maps to skill '{skill_name}' (FK-43 §43.4.1)",
            detail={
                "skill_name": skill_name,
                "bundle_root": str(bundle_root),
                "variants": dict(variants),
            },
        )

    # ------------------------------------------------------------------
    # resolve_binding
    # ------------------------------------------------------------------

    def resolve_binding(
        self,
        project_root: Path,
        skill_name: str,
    ) -> SkillBinding | None:
        """Return the current ``SkillBinding`` for a skill in a project.

        Args:
            project_root: Root of the target project.
            skill_name: Logical skill name.

        Returns:
            The ``SkillBinding`` if found, otherwise ``None``.
        """
        project_key = project_root.stem
        return self._binding_repo.load(project_key, skill_name)

    # ------------------------------------------------------------------
    # list_bound_skills
    # ------------------------------------------------------------------

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]:
        """Return all bound skills for a project, sorted by skill_name.

        Args:
            project_root: Root of the target project.

        Returns:
            Sorted list of ``SkillBinding`` objects.
        """
        project_key = project_root.stem
        return self._binding_repo.list_for_project(project_key)

    # ------------------------------------------------------------------
    # collect_quality_metrics
    # ------------------------------------------------------------------

    def collect_quality_metrics(self, skill_name: str) -> SkillQualityMetric:
        """Return quality metrics for a skill (FK-43 §43.6.2).

        Raises:
            NotImplementedError: Always. Full implementation requires a
                telemetry/failure-corpus data source and is deferred to a
                follow-up story (THEME-007 / FK-43 §43.6.2). A missing or
                empty metric would falsely suggest "all OK" (FK-43 §43.6.2);
                therefore this method MUST raise rather than return a
                zeroed-out stub.
        """
        del skill_name  # consumed by follow-up story
        raise NotImplementedError(
            "SkillQualityMetric requires telemetry/failure-corpus data — "
            "follow-up story (THEME-007 / FK-43 §43.6.2)"
        )
