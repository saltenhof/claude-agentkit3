"""Skills top-surface (AG3-027, FK-43, bc-cut-decisions.md §BC 11).

Implements the four top-level methods defined in FK-43 §43.1 and FK-50 CP8:

* ``bind_skill``        — link-based harness binding, platform-aware
  (symlink on POSIX, directory junction on Windows; FK-43 §43.4.1/§43.4.1.1)
* ``resolve_binding``   — lookup of an existing binding
* ``list_bound_skills`` — project-scoped listing
* ``collect_quality_metrics`` — projection-backed fail-closed skill quality
  aggregation (FK-43 §43.6.2).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
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
    SkillBindingPartialStateError,
    SkillBundleDigestMismatchError,
    SkillProfileNotSupportedError,
)
from agentkit.skills.links import (
    create_directory_link,
    is_directory_link,
    remove_directory_link,
)
from agentkit.skills.quality_metric import (
    SkillQualityMetric,
    SourceWindow,
    collect_quality_metrics,
)

if TYPE_CHECKING:
    from pathlib import Path  # noqa: TC003  # used only in annotations (from __future__ annotations)

    from agentkit.skills.bundle_store import SkillBundleStore
    from agentkit.skills.repository import SkillBindingRepository
    from agentkit.telemetry.projection_accessor import ProjectionAccessor

# ---------------------------------------------------------------------------
# Harness-specific binding paths  (FK-43 §43.4.1, FK-30 §30.11)
# ---------------------------------------------------------------------------

def _harness_skill_dir(project_root: Path, harness: HarnessKind) -> Path:
    """Return the harness-specific skills directory within *project_root*.

    * Claude Code: ``{project_root}/.claude/skills/``
    * Codex:       ``{project_root}/.codex/skills/``
      (FK-30 §30.11 Codex binding point; path convention follows FK-30
      §30.11 as interpreted in AG3-027; update if FK-30 mandates a
      different path in a future revision)
    """
    if harness == HarnessKind.CLAUDE_CODE:
        return project_root / ".claude" / "skills"
    if harness == HarnessKind.CODEX:
        return project_root / ".codex" / "skills"  # FK-30 §30.11 Codex binding point
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


def _create_harness_links(
    skill_name: str,
    bundle_root: Path,
    project_root: Path,
    harnesses: tuple[HarnessKind, ...],
) -> SkillBindingMode:
    """Create one link per harness; rolls back partial state on failure.

    Platform-aware per FK-43 §43.4.1.1: a symbolic link on POSIX, a directory
    junction on Windows (via :mod:`agentkit.skills.links`). Invariant
    ``project_binding_is_link_only``: never falls back to a file copy. Returns
    the :class:`SkillBindingMode` actually used (consistent across harnesses on
    a given platform) so the caller can persist the truthful mode.

    HONEST ROLLBACK (AG3-048 Codex-r5 FINDING 1): when creation of a later link
    fails, the rollback removes the already-created links AND re-checks each one
    afterwards. If any created link SURVIVES the rollback (e.g. its removal raised
    ``OSError``), the function MUST NOT propagate only the original creation
    error — that would leave a residual harness artifact unreported (silent
    partial state). Instead it raises ``SkillBindingPartialStateError`` carrying
    the residual links, exactly the way ``bind_skill``'s self-atomic cleanup
    reports a ``RollbackIncomplete``. When the rollback fully succeeds, the
    original error propagates unchanged.

    AG3-048 Codex-r6 FINDING 1: the rollback routes the removal+re-check through
    the SINGLE shared ``_remove_links_honest`` helper rather than re-implementing
    the suppress/re-check dance inline (one honest discipline, no whack-a-mole).
    """
    created: list[Path] = []
    mode = SkillBindingMode.SYMLINK
    try:
        for harness in harnesses:
            skills_dir = _harness_skill_dir(project_root, harness)
            skills_dir.mkdir(parents=True, exist_ok=True)
            link_path = skills_dir / skill_name
            if is_directory_link(link_path):
                remove_directory_link(link_path)
            try:
                mode = create_directory_link(link_path, bundle_root)
            except OSError as exc:
                raise SkillBindingFailedError(
                    f"Failed to create the binding link for skill '{skill_name}' "
                    f"(harness={harness}). A thin link is mandatory — copying the "
                    f"bundle is forbidden (project_binding_is_link_only). "
                    f"Original error: {exc}",
                    detail={
                        "skill_name": skill_name,
                        "harness": str(harness),
                        "link_path": str(link_path),
                        "bundle_root": str(bundle_root),
                        "os_error": str(exc),
                    },
                ) from exc
            created.append(link_path)
    except Exception as exc:
        # AG3-048 Codex-r4 FINDING 1: roll back ALL already-created links on ANY
        # failure during creation — not only ``SkillBindingFailedError``. A
        # ``mkdir`` error, a removal failure on a pre-existing link, or any other
        # exception must not leave link-1 behind after link-2 fails.
        #
        # AG3-048 Codex-r5 FINDING 1: the rollback is HONEST — after attempting to
        # remove each created link we re-check it; any that survives is tracked as
        # residual partial state. We never raise ONLY the original error while a
        # created artifact remains unreported.
        #
        # AG3-048 Codex-r6 FINDING 1: the removal+re-check goes through the ONE
        # shared honest helper ``_remove_links_honest``. ``created`` already holds
        # the harness-qualified link paths, so we re-check exactly those.
        residual_links = _remove_links_honest(created)
        if residual_links:
            raise SkillBindingPartialStateError(
                f"Creating harness links for skill '{skill_name}' failed and "
                "the rollback could NOT fully undo the partial state; residual "
                "link(s) remain (NOT a clean failure).",
                detail={
                    "skill_name": skill_name,
                    "project_root": str(project_root),
                    "bundle_root": str(bundle_root),
                    "residual_links": [str(p) for p in residual_links],
                    "persisted_row_remains": False,
                    "original_error": str(exc),
                },
            ) from exc
        raise
    return mode


def _verify_harness_links(
    skill_name: str,
    project_root: Path,
    harnesses: tuple[HarnessKind, ...],
) -> None:
    """Post-bind verification: each harness link must exist (symlink or junction)."""
    for harness in harnesses:
        link_path = _harness_skill_dir(project_root, harness) / skill_name
        if not is_directory_link(link_path):
            raise SkillBindingFailedError(
                f"Post-bind verification failed: binding link missing for "
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


@dataclass(frozen=True)
class _CleanupResidual:
    """What a binding-artifact removal could NOT undo (AG3-048 Codex-r4 FINDING 1).

    Attributes:
        residual_links: Harness binding-link paths (symlink or junction) that
            still exist after removal attempted (and failed) to detach them.
        persisted_row_remains: ``True`` when the binding row delete failed and a
            persisted row may still exist.
    """

    residual_links: list[Path] = field(default_factory=list)
    persisted_row_remains: bool = False

    @property
    def is_clean(self) -> bool:
        """Return ``True`` when nothing remains (removal fully succeeded)."""
        return not self.residual_links and not self.persisted_row_remains


def _remove_links_honest(link_paths: list[Path]) -> list[Path]:
    """Detach each binding link in *link_paths* and report the survivors.

    AG3-048 Codex-r6 FINDING 1 — THE single honest link-removal discipline. This
    is the ONE place that removes harness binding links. For each path it attempts
    removal via :func:`agentkit.skills.links.remove_directory_link` (a junction is
    detached with ``os.rmdir`` so the central target is NEVER touched; a symlink
    with ``unlink``) — suppressing only the ``OSError`` of that single filesystem
    call — and then RE-CHECKS whether a link/artifact still exists; any path that
    SURVIVES is appended to the returned residual list. Nothing is ever silently
    swallowed — a suppressed ``OSError`` that left the artifact on disk surfaces as
    a residual entry; one whose artifact is nonetheless gone (idempotent
    re-removal) does not. A removal sub-failure on one path must not stop removal
    of the others.

    Args:
        link_paths: The fully-qualified harness binding-link paths to remove.

    Returns:
        The paths that still exist after the removal attempt (empty when every
        link is gone).
    """
    import contextlib

    residual_links: list[Path] = []
    for link_path in link_paths:
        with contextlib.suppress(OSError):
            if is_directory_link(link_path):
                remove_directory_link(link_path)
            elif link_path.exists():
                # Not a link but present (unexpected real artifact) — remove it
                # without recursing through anything; surfaces as residual if it
                # cannot be removed.
                link_path.unlink()
        # Re-check: a suppressed OSError (or a still-present artifact) means the
        # link survived — record it, never silently swallow it.
        if is_directory_link(link_path) or link_path.exists():
            residual_links.append(link_path)
    return residual_links


# ---------------------------------------------------------------------------
# Skills top-surface
# ---------------------------------------------------------------------------

class Skills:
    """Top-surface for the agent-skills BC (FK-43, bc-cut-decisions.md §BC 11).

    Provides the four canonical top-level methods:

    * ``bind_skill`` — link-based project binding (symlink on POSIX, directory
      junction on Windows) with multi-harness support
    * ``resolve_binding`` — lookup
    * ``list_bound_skills`` — project-scoped listing
    * ``collect_quality_metrics`` — reads telemetry projections fail-closed

    Invariant enforced: ``project_binding_is_link_only``
    (formal.skills-and-bundles.invariants). File-copying is forbidden.

    Args:
        bundle_store: Systemwide registry of available skill bundles.
        binding_repo: Storage port for ``SkillBinding`` persistence.
        projection_accessor: Optional telemetry projection read boundary for
            skill-quality aggregation.
    """

    def __init__(
        self,
        bundle_store: SkillBundleStore,
        binding_repo: SkillBindingRepository,
        projection_accessor: ProjectionAccessor | None = None,
    ) -> None:
        self._bundle_store = bundle_store
        self._binding_repo = binding_repo
        self._projection_accessor = projection_accessor

    # ------------------------------------------------------------------
    # bind_skill
    # ------------------------------------------------------------------

    def bind_skill(
        self,
        skill_name: str,
        bundle_root: Path,
        project_root: Path,
    ) -> None:
        """Bind a skill bundle to a project via harness-specific links.

        Pass-2 (Codex giftig 2026-05-24): strictly FK-43 §43.4.1 + FK-50 CP8 —
        the signature is exactly the three mandatory parameters; no additional
        kwargs. Links are created per mandatory harness (Claude Code +
        Codex from FK-43 §43.4.1 AK4; multi-harness mandatory from day one).

        Platform-dependent (FK-43 §43.4.1.1): a symlink on POSIX, a directory
        junction on Windows. The junction needs no Developer Mode; the mode
        actually used is persisted in the ``SkillBinding``.

        Lifecycle (formal.skills-and-bundles.state-machine):
        REQUESTED -> PROFILE_RESOLVED -> BUNDLE_SELECTED -> BOUND -> VERIFIED.
        Profile/bundle resolution is caller preparation (FK-50 CP6/CP7);
        ``bind_skill`` receives a concrete ``bundle_root`` and walks the
        lifecycle stages deterministically to persistence.

        Invariant ``project_binding_is_link_only``: no file-copying is
        permitted. If the OS link call fails, ``SkillBindingFailedError`` is
        raised immediately (no copy fallback).

        Args:
            skill_name: Logical skill name (e.g. ``"implement"``).
            bundle_root: Absolute path to the bundle directory.
            project_root: Root of the target project. Used as the source for
                ``SkillBinding.project_key`` (stem of the path) — consistent
                with ``resolve_binding`` / ``list_bound_skills`` lookup.

        Raises:
            SkillBindingFailedError: When ``project_root`` or ``bundle_root``
                do not exist, or when the binding link cannot be created.
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

        # Multi-harness mandatory from day one (FK-43 §43.4.1 AK4).
        harnesses: tuple[HarnessKind, ...] = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)
        canonical_target = (
            _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / skill_name
        )

        # SELF-ATOMIC bind (AG3-048 Codex-r3 ERROR 2 + Codex-r7 FINDING 1): link
        # creation is INSIDE the try so that ANY failure triggers the self-atomic
        # cleanup below. This is decisive on a REBIND: ``_create_harness_links``
        # removes the prior link before creating the new one, so a failed link
        # creation would otherwise leave the harness link gone WHILE a stale
        # persisted row from the previous (successful) bind survives — an
        # unreported inconsistent partial state. Running the cleanup
        # (``_remove_binding_artifacts``: detach remaining links + delete the
        # persisted row) makes the outcome binary — fully bound (links + VERIFIED
        # row) or fully clean (no link, no row) — else a surfaced
        # ``SkillBindingPartialStateError``. A caller's transactional rollback
        # therefore never sees a half-bound skill nor a row pointing at a removed
        # link. ``binding_mode`` is the actual mode used (SYMLINK/JUNCTION).
        try:
            binding_mode = _create_harness_links(
                skill_name, bundle_root, project_root, harnesses
            )
            binding = SkillBinding(
                binding_id=bid,
                project_key=effective_project_key,
                skill_name=skill_name,
                bundle_id=effective_bundle_id,
                bundle_version=effective_bundle_version,
                target_path=canonical_target,
                binding_mode=binding_mode,
                status=SkillLifecycleStatus.BOUND,
                pinned_at=pinned_at,
            )
            self._binding_repo.save(binding)

            _verify_harness_links(skill_name, project_root, harnesses)

            # Update status to VERIFIED.
            verified_binding = SkillBinding(
                binding_id=bid,
                project_key=effective_project_key,
                skill_name=skill_name,
                bundle_id=effective_bundle_id,
                bundle_version=effective_bundle_version,
                target_path=canonical_target,
                binding_mode=binding_mode,
                status=SkillLifecycleStatus.VERIFIED,
                pinned_at=pinned_at,
            )
            self._binding_repo.save(verified_binding)
        except Exception as exc:
            # AG3-048 Codex-r4 FINDING 1: narrow ``except BaseException`` ->
            # ``except Exception`` so KeyboardInterrupt/SystemExit propagate
            # untouched. Cleanup is HONEST: when it cannot fully undo the
            # partial state, surface the residual so the caller can never
            # mistake the failure for a fully-clean one.
            residual = self._remove_binding_artifacts(skill_name, project_root, harnesses)
            if not residual.is_clean:
                raise SkillBindingPartialStateError(
                    f"Binding skill '{skill_name}' failed and the self-atomic "
                    "cleanup could NOT fully undo the partial state; residual "
                    "side effects remain (NOT a clean failure).",
                    detail={
                        "skill_name": skill_name,
                        "project_root": str(project_root),
                        "residual_links": [
                            str(p) for p in residual.residual_links
                        ],
                        "persisted_row_remains": residual.persisted_row_remains,
                        "original_error": str(exc),
                    },
                ) from exc
            raise

    def _remove_binding_artifacts(
        self,
        skill_name: str,
        project_root: Path,
        harnesses: tuple[HarnessKind, ...],
    ) -> _CleanupResidual:
        """Remove ALL binding artifacts (harness links + persisted row).

        AG3-048 Codex-r6 FINDING 1 — THE single honest removal discipline shared
        by every cleanup/unbind path (``_cleanup_partial_bind`` self-atomic
        cleanup AND the public ``unbind_skill``). It:

        1. detaches each harness binding link and RE-CHECKS it via the one shared
           ``_remove_links_honest`` helper (a survivor is recorded, never
           silently swallowed);
        2. attempts the repo ``delete`` and records ``persisted_row_remains`` on
           any failure (tracked, not swallowed — no bare ``except: pass``).

        Each step's failure is captured rather than re-raised so the ORIGINAL
        failure of the caller propagates and a sub-failure of one step never
        stops the remaining steps. The returned ``_CleanupResidual`` is the
        single source of truth for "what could NOT be removed"; ``is_clean`` is
        ``True`` only when every link is gone AND the row was deleted.

        Returns:
            A ``_CleanupResidual`` describing what could NOT be removed. Empty /
            ``is_clean`` when the removal fully succeeded.
        """
        link_paths = [
            _harness_skill_dir(project_root, harness) / skill_name
            for harness in harnesses
        ]
        residual_links = _remove_links_honest(link_paths)

        persisted_row_remains = False
        try:
            self._binding_repo.delete(project_root.stem, skill_name)
        except Exception:  # noqa: BLE001  # best-effort; tracked, not swallowed
            persisted_row_remains = True

        return _CleanupResidual(
            residual_links=residual_links,
            persisted_row_remains=persisted_row_remains,
        )

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
    # unbind_skill
    # ------------------------------------------------------------------

    def unbind_skill(self, skill_name: str, project_root: Path) -> None:
        """Remove a skill's harness links and its persisted binding.

        Inverse of ``bind_skill``. Idempotent: a missing link or absent
        binding is not an error (re-running a clean unbind is a no-op). Used by
        the installer for transactional rollback when binding the mandatory-skill
        set fails part-way (FAIL-CLOSED, no partial install — FK-50 §50.5).

        Removal order mirrors ``bind_skill`` creation: links first (both
        harnesses), then the persisted binding.

        AG3-048 Codex-r6 FINDING 1: unbind is HONEST. It routes through the ONE
        shared ``_remove_binding_artifacts`` discipline (the same helper used by
        the self-atomic bind cleanup), which detaches each harness link AND
        re-checks it, and deletes the persisted row tracking failure. A Windows
        junction is detached with ``os.rmdir`` (never recursing into the central
        target). If the removal could NOT fully complete (a link survived its
        removal even though the repo row was deleted, or the row delete failed),
        unbind RAISES ``SkillBindingPartialStateError`` carrying the residual
        instead of returning silently. This is what lets the installer's
        ``_rollback_bindings`` map a non-clean unbind to ``RollbackIncomplete`` —
        a left-behind harness artifact can NEVER be mistaken for a clean rollback
        (NO ERROR BYPASSING, no bare ``except OSError: pass``).

        Args:
            skill_name: Logical skill name to unbind.
            project_root: Root of the target project.

        Raises:
            SkillBindingPartialStateError: When the removal left residual partial
                state (a harness link could not be detached, and/or the
                persisted binding row could not be deleted).
        """
        harnesses: tuple[HarnessKind, ...] = (
            HarnessKind.CLAUDE_CODE,
            HarnessKind.CODEX,
        )
        residual = self._remove_binding_artifacts(skill_name, project_root, harnesses)
        if not residual.is_clean:
            raise SkillBindingPartialStateError(
                f"Unbinding skill '{skill_name}' could NOT fully remove its "
                "binding artifacts; residual side effects remain (NOT a clean "
                "unbind — the installer rollback must treat this as incomplete).",
                detail={
                    "skill_name": skill_name,
                    "project_root": str(project_root),
                    "residual_links": [
                        str(p) for p in residual.residual_links
                    ],
                    "persisted_row_remains": residual.persisted_row_remains,
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

    def collect_quality_metrics(
        self,
        skill_name: str,
        *,
        project_key: str,
        source_window: SourceWindow,
    ) -> SkillQualityMetric:
        """Return quality metrics for a skill (FK-43 §43.6.2).

        The aggregation reads story metrics and ``FC_INCIDENTS`` exclusively via
        ``Telemetry.ProjectionAccessor.read_projection``. Current source records
        do not carry skill/version attribution, so the returned model reports
        ``bundle_version=None`` and ``attribution=UNATTRIBUTABLE``.
        """
        return collect_quality_metrics(
            skill_name,
            project_key=project_key,
            source_window=source_window,
            projection_accessor=self._projection_accessor,
        )
