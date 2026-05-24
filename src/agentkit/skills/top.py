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
from agentkit.skills.errors import SkillBindingFailedError

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


def _compute_manifest_digest(bundle_root: Path) -> str:
    """Return SHA-256 hex digest of the manifest.json at *bundle_root*.

    Returns empty string if no manifest exists (bundle validation may then
    raise ``SkillBundleDigestMismatchError`` if the caller supplied an
    expected digest).
    """
    manifest = bundle_root / "manifest.json"
    if not manifest.is_file():
        return ""
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


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
        *,
        harnesses: tuple[HarnessKind, ...] = (HarnessKind.CLAUDE_CODE,),
        project_key: str = "",
        bundle_id: str = "",
        bundle_version: str = "0.0.0",
        expected_manifest_digest: str | None = None,
    ) -> None:
        """Bind a skill bundle to a project via harness-specific symlinks.

        Lifecycle: REQUESTED -> BUNDLE_SELECTED -> BOUND -> VERIFIED.
        Profile/bundle resolution is Caller-Vorarbeit (FK-43 + FK-50 CP6/CP7);
        ``bind_skill`` receives a concrete ``bundle_root``.

        Invariant ``project_binding_is_symlink_only``: no file-copying is
        permitted. If ``Path.symlink_to`` fails on Windows (Developer Mode
        required), ``SkillBindingFailedError`` is raised immediately.

        Args:
            skill_name: Logical skill name (e.g. ``"implement"``).
            bundle_root: Absolute path to the bundle directory.
            project_root: Root of the target project.
            harnesses: Active harnesses to create symlinks for. Defaults to
                ``(HarnessKind.CLAUDE_CODE,)`` when called without installer
                context (AG3-048 will pass the full harness set).
            project_key: Stable project key used for ``SkillBinding`` records.
                Defaults to the stem of ``project_root`` when empty.
            bundle_id: Bundle identifier for the ``SkillBinding`` record.
                Defaults to the ``bundle_root`` stem when empty.
            bundle_version: Pinned bundle version string.
            expected_manifest_digest: When provided, the actual SHA-256 digest
                of ``bundle_root/manifest.json`` must match this value or
                ``SkillBundleDigestMismatchError`` is raised.

        Raises:
            SkillBindingFailedError: When ``project_root`` or ``bundle_root``
                do not exist, or when a symlink cannot be created (e.g.
                Windows without Developer Mode).
            SkillBundleDigestMismatchError: When the manifest digest does not
                match ``expected_manifest_digest``.
        """
        from agentkit.skills.errors import SkillBundleDigestMismatchError

        # -- Validation --------------------------------------------------------
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

        # -- Manifest digest check --------------------------------------------
        if expected_manifest_digest is not None:
            actual_digest = _compute_manifest_digest(bundle_root)
            if actual_digest != expected_manifest_digest:
                raise SkillBundleDigestMismatchError(
                    f"Bundle manifest digest mismatch for '{skill_name}'",
                    detail={
                        "skill_name": skill_name,
                        "bundle_root": str(bundle_root),
                        "expected": expected_manifest_digest,
                        "actual": actual_digest,
                    },
                )

        # -- Effective keys ----------------------------------------------------
        effective_project_key = project_key or project_root.stem
        effective_bundle_id = bundle_id or bundle_root.stem
        pinned_at = datetime.now(tz=UTC)

        # -- Lifecycle: REQUESTED -> BUNDLE_SELECTED --------------------------
        # (Profile resolution is Caller-Vorarbeit; we start at BUNDLE_SELECTED)
        # Initial binding record at BUNDLE_SELECTED (not yet persisted):
        # We track the binding_id for later persistence.
        bid = _binding_id_for(effective_project_key, skill_name)

        # -- Symlink creation per harness (BUNDLE_SELECTED -> BOUND) ----------
        created_symlinks: list[Path] = []
        try:
            for harness in harnesses:
                skills_dir = _harness_skill_dir(project_root, harness)
                skills_dir.mkdir(parents=True, exist_ok=True)
                link_path = skills_dir / skill_name

                # Invariant: SYMLINK only — no copy fallback.
                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()

                try:
                    link_path.symlink_to(bundle_root)
                except OSError as exc:
                    raise SkillBindingFailedError(
                        f"Failed to create symlink for skill '{skill_name}' "
                        f"(harness={harness}). On Windows, Developer Mode must "
                        f"be enabled or the process must have "
                        f"SeCreateSymbolicLinkPrivilege. "
                        f"Original error: {exc}",
                        detail={
                            "skill_name": skill_name,
                            "harness": str(harness),
                            "link_path": str(link_path),
                            "bundle_root": str(bundle_root),
                            "os_error": str(exc),
                        },
                    ) from exc

                created_symlinks.append(link_path)
        except SkillBindingFailedError:
            # Clean up any symlinks created before the failure.
            import contextlib

            for sl in created_symlinks:
                with contextlib.suppress(OSError):
                    sl.unlink(missing_ok=True)
            raise

        # -- BOUND: Persist binding -------------------------------------------
        # Use the first harness's path as the canonical target_path.
        first_harness = harnesses[0]
        canonical_target = _harness_skill_dir(project_root, first_harness) / skill_name

        binding = SkillBinding(
            binding_id=bid,
            project_key=effective_project_key,
            skill_name=skill_name,
            bundle_id=effective_bundle_id,
            bundle_version=bundle_version,
            target_path=canonical_target,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=pinned_at,
        )
        self._binding_repo.save(binding)

        # -- VERIFIED: Re-check symlinks resolve correctly --------------------
        for harness in harnesses:
            link_path = _harness_skill_dir(project_root, harness) / skill_name
            if not link_path.is_symlink():
                raise SkillBindingFailedError(
                    f"Post-bind verification failed: symlink missing for "
                    f"skill '{skill_name}' (harness={harness})",
                    detail={"skill_name": skill_name, "link_path": str(link_path)},
                )

        # Update status to VERIFIED.
        verified_binding = SkillBinding(
            binding_id=bid,
            project_key=effective_project_key,
            skill_name=skill_name,
            bundle_id=effective_bundle_id,
            bundle_version=bundle_version,
            target_path=canonical_target,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=pinned_at,
        )
        self._binding_repo.save(verified_binding)

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
