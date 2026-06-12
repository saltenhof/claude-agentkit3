"""Materialized/substituted harness-variant binding (AG3-111, FK-43 §43.4.1.1).

This module is the agent-skills BC's Fachlogik owner for the SECOND, materialized
binding mode. For a placeholder-bearing skill (a bundle ``.md`` file carrying at
least one ``{{...}}`` token) the installer must deliver the SUBSTITUTED content to
the harness — the four FK-03 placeholders and the manifest-fed
``{{AGENT_SPAWN_SKILL_PROOF}}`` (AG3-110) must be resolved in the content the
harness actually reads through the bind point (FK-43 §43.2.3/§43.4.2, FK-31 §31.7.4).

LIEFERMUSTER (FK-43 §43.4.1.1): the installer materializes a substituted COPY of the
neutral skill representation into a SEPARATE store in the AK3 install area and links
the harness bind point at THAT variant instead of the raw ``bundle_root``. The
project bind point stays a thin LINK — ``project_binding_is_link_only`` is NOT broken
(the substituted copy lives in the central AK3 store, never in the project repo).

OWNERSHIP / NO-CYCLE: this surface REUSES :class:`PlaceholderSubstitutor`
(AG3-027/AG3-110) — substitution is never re-implemented here. The digest-keyed
variant directory is computed by the installer BC (``installer/paths.py``) and passed
IN as ``variant_dir`` so the agent-skills BC carries no back-edge to the installer BC
(same boundary discipline ``placeholder.py`` uses for the manifest filename via
``core_types``).

SELF-ATOMIC: variant write + harness links are transactional. On ANY failure the
already-written variant content AND any created link are rolled back so no residual
half-materialized bind point survives (mirrors the AG3-048 ``bind_skill`` discipline).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.skills.binding import (
    HarnessKind,
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.skills.errors import SkillBindingFailedError, SkillBindingPartialStateError
from agentkit.skills.links import (
    create_directory_link,
    is_directory_link,
    remove_directory_link,
)
from agentkit.skills.placeholder import PlaceholderSubstitutor

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from agentkit.config.models import ProjectConfig
    from agentkit.skills.repository import SkillBindingRepository

#: Matches any ``{{...}}`` placeholder token (mirrors ``placeholder._PLACEHOLDER_RE``;
#: a local copy keeps detection inside this surface without importing the private
#: regex — both derive from the FK-43 §43.4.2 token grammar).
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

#: The mandatory harnesses bound on every platform (FK-43 §43.4.1 AK4): Claude Code
#: + Codex. Mirrors the tuple ``Skills.bind_skill`` uses.
_MANDATORY_HARNESSES: tuple[HarnessKind, ...] = (HarnessKind.CLAUDE_CODE, HarnessKind.CODEX)


def _harness_skill_dir(project_root: Path, harness: HarnessKind) -> Path:
    """Return the harness-specific skills bind directory (FK-43 §43.4.1)."""
    if harness == HarnessKind.CLAUDE_CODE:
        return project_root / ".claude" / "skills"
    if harness == HarnessKind.CODEX:
        return project_root / ".codex" / "skills"
    msg = f"Unknown harness: {harness}"  # pragma: no cover - exhaustive StrEnum
    raise ValueError(msg)  # pragma: no cover


def _iter_bundle_markdown(bundle_root: Path) -> Iterable[Path]:
    """Yield every ``.md`` file under *bundle_root* (FK-43 §43.4.2 ".md only")."""
    return sorted(p for p in bundle_root.rglob("*.md") if p.is_file())


def bundle_has_placeholders(bundle_root: Path) -> bool:
    """Return ``True`` when any ``.md`` of *bundle_root* carries a ``{{...}}`` token.

    Deterministic mode selector (FK-43 §43.4.2 "Nur in .md-Dateien"): a bundle whose
    markdown carries at least one placeholder is bound via the materialized variant;
    a placeholder-free bundle keeps the raw ``bundle_root`` link unchanged.

    Args:
        bundle_root: The systemwide bundle directory.

    Returns:
        Whether at least one ``.md`` file contains a ``{{...}}`` placeholder.
    """
    return any(
        _PLACEHOLDER_RE.search(md.read_text(encoding="utf-8"))
        for md in _iter_bundle_markdown(bundle_root)
    )


def _write_variant_if_changed(target: Path, content: str) -> None:
    """Write *content* to *target* only when it differs (idempotent, FK-51).

    Mirrors the installer's ``_write_text_if_changed`` semantics: an unchanged file
    is left untouched (byte-stable re-materialization), so a re-install under the
    same input digest produces a byte-identical variant.
    """
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _materialize_variant_tree(
    bundle_root: Path,
    variant_dir: Path,
    config: ProjectConfig,
    project_root: Path,
    substitutor: PlaceholderSubstitutor,
) -> None:
    """Copy *bundle_root* into *variant_dir*, substituting every ``.md`` file.

    Non-``.md`` bundle files are copied verbatim (FK-43 §43.4.2: substitution touches
    ``.md`` only). ``.md`` files run through
    :meth:`PlaceholderSubstitutor.substitute_spawn_header` which resolves all five
    placeholders (four FK-03 + the manifest-fed ``{{AGENT_SPAWN_SKILL_PROOF}}``) and
    raises ``UnknownPlaceholderError`` fail-closed when the manifest token is missing.
    """
    import shutil

    bundle_files = sorted(p for p in bundle_root.rglob("*") if p.is_file())
    for src in bundle_files:
        rel = src.relative_to(bundle_root)
        dst = variant_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".md":
            substituted = substitutor.substitute_spawn_header(
                src.read_text(encoding="utf-8"), config, project_root
            )
            _write_variant_if_changed(dst, substituted)
        elif not (dst.is_file() and dst.read_bytes() == src.read_bytes()):
            shutil.copyfile(src, dst)


def _link_harness_bindpoints(
    skill_name: str,
    variant_dir: Path,
    project_root: Path,
    harnesses: tuple[HarnessKind, ...],
) -> SkillBindingMode:
    """Link each harness bind point at *variant_dir*; return the mode used.

    A mid-loop failure is NOT rolled back here — the caller
    (:func:`bind_skill_materialized`) owns the self-atomic rollback over ALL
    candidate bind points, so a link created before the failure is still detached.
    """
    mode = SkillBindingMode.SYMLINK
    for harness in harnesses:
        skills_dir = _harness_skill_dir(project_root, harness)
        skills_dir.mkdir(parents=True, exist_ok=True)
        link_path = skills_dir / skill_name
        if is_directory_link(link_path):
            remove_directory_link(link_path)
        try:
            mode = create_directory_link(link_path, variant_dir)
        except OSError as exc:
            raise SkillBindingFailedError(
                f"Failed to link the materialized variant for skill '{skill_name}' "
                f"(harness={harness}). Original error: {exc}",
                detail={
                    "skill_name": skill_name,
                    "harness": str(harness),
                    "link_path": str(link_path),
                    "variant_dir": str(variant_dir),
                    "os_error": str(exc),
                },
            ) from exc
    return mode


def _remove_links_best_effort(link_paths: list[Path]) -> list[Path]:
    """Detach each link and return the ones that survived (honest rollback)."""
    import contextlib

    residual: list[Path] = []
    for link_path in link_paths:
        with contextlib.suppress(OSError):
            if is_directory_link(link_path):
                remove_directory_link(link_path)
        if is_directory_link(link_path):
            residual.append(link_path)
    return residual


def bind_skill_materialized(
    skill_name: str,
    bundle_root: Path,
    project_root: Path,
    *,
    config: ProjectConfig,
    variant_dir: Path,
    binding_repo: SkillBindingRepository,
    binding_id: str,
    bundle_id: str,
    bundle_version: str,
) -> SkillBinding:
    """Materialize a substituted variant and link the harness bind points at it.

    The SECOND binding mode (FK-43 §43.4.1.1) for a placeholder-bearing skill:

    1. substitute every bundle ``.md`` (all five placeholders) into *variant_dir*
       (digest-keyed, computed by the installer BC) — fail-closed if the manifest
       token is missing (``substitute_spawn_header`` raises);
    2. link ``.claude/skills/<skill>`` and ``.codex/skills/<skill>`` at *variant_dir*
       (NOT the raw ``bundle_root``);
    3. persist a ``SkillBinding`` (UNCHANGED schema — the materialized mode is derived
       from the link target, not a new field; AG3-111 §2.1 item 1b).

    SELF-ATOMIC (mirrors AG3-048 ``bind_skill``): on ANY failure the created links are
    rolled back AND the variant content removed, so no residual half-materialized bind
    point survives. When the link rollback itself fails, a
    ``SkillBindingPartialStateError`` carries the residual links.

    Args:
        skill_name: Logical skill name.
        bundle_root: Systemwide bundle directory (neutral representation).
        project_root: Target-project root (bind points + ``.installed-manifest.json``).
        config: Project configuration (resolves the four FK-03 placeholders).
        variant_dir: The digest-keyed variant directory in the AK3 install store
            (computed by the installer via ``installer.paths``).
        binding_repo: Persistence port for the ``SkillBinding`` row.
        binding_id: Deterministic binding id (installer-supplied, matches ``bind_skill``).
        bundle_id: Bundle identifier (persisted on the binding row).
        bundle_version: Bundle version (persisted on the binding row).

    Returns:
        The persisted ``SkillBinding`` (status ``VERIFIED``).

    Raises:
        UnknownPlaceholderError: When a ``.md`` placeholder cannot be resolved
            (e.g. the manifest token is missing — fail-closed, install aborts).
        SkillBindingFailedError: When a bind point cannot be linked.
        SkillBindingPartialStateError: When a failure's rollback left a residual link.
    """
    import shutil

    substitutor = PlaceholderSubstitutor()
    variant_written = False
    # Track whether a binding row has been persisted so the rollback path can
    # delete it and keep the detail field ``persisted_row_remains`` honest
    # (AC8 / AG3-048 self-atomic rollback discipline).
    row_persisted = False
    try:
        # 1. Materialize the substituted variant (fail-closed on a missing token).
        _materialize_variant_tree(
            bundle_root, variant_dir, config, project_root, substitutor
        )
        variant_written = True

        # 2. Link the harness bind points at the variant (not the raw bundle).
        binding_mode = _link_harness_bindpoints(
            skill_name, variant_dir, project_root, _MANDATORY_HARNESSES
        )

        # 3. Persist the binding (UNCHANGED schema; mode derived from link target).
        pinned_at = datetime.now(tz=UTC)
        canonical_target = (
            _harness_skill_dir(project_root, HarnessKind.CLAUDE_CODE) / skill_name
        )
        binding = SkillBinding(
            binding_id=binding_id,
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            target_path=canonical_target,
            binding_mode=binding_mode,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=pinned_at,
        )
        binding_repo.save(binding)
        # A row is now persisted; the rollback path must delete it on any
        # subsequent failure so no orphan row survives a partial bind.
        row_persisted = True
        verified = SkillBinding(
            binding_id=binding_id,
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            target_path=canonical_target,
            binding_mode=binding_mode,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=pinned_at,
        )
        binding_repo.save(verified)
    except Exception as exc:
        # Roll back over ALL candidate bind points (both harnesses), not only the
        # links this caller saw returned: a link created INSIDE
        # ``_link_harness_bindpoints`` before it raised mid-loop is otherwise
        # orphaned (the function never returns its partial ``created`` list). Mirrors
        # ``top.py._remove_binding_artifacts``, which detaches all harness links
        # regardless of how far the bind got.
        all_bindpoints = [
            _harness_skill_dir(project_root, harness) / skill_name
            for harness in _MANDATORY_HARNESSES
        ]
        residual_links = _remove_links_best_effort(all_bindpoints)
        # Best-effort variant teardown: the variant is digest-keyed and recoverable,
        # but a failed materialization must not leave a half-written tree behind.
        # ``ignore_errors=True`` keeps the teardown from masking the ORIGINAL failure.
        if variant_written or variant_dir.exists():
            shutil.rmtree(variant_dir, ignore_errors=True)
        # Delete the persisted binding row so no orphan row survives (AC8 /
        # AG3-048 self-atomic discipline). ``delete`` is a no-op when absent,
        # so calling it unconditionally is safe even if only one save succeeded.
        row_deletion_failed = False
        if row_persisted:
            try:
                binding_repo.delete(project_root.stem, skill_name)
                row_persisted = False  # deletion succeeded; row is gone
            except Exception:  # noqa: BLE001
                row_deletion_failed = True
        if residual_links or row_deletion_failed:
            raise SkillBindingPartialStateError(
                f"Materializing skill '{skill_name}' failed and the rollback could "
                "NOT fully clean up (NOT a clean failure).",
                detail={
                    "skill_name": skill_name,
                    "project_root": str(project_root),
                    "variant_dir": str(variant_dir),
                    "residual_links": [str(p) for p in residual_links],
                    "persisted_row_remains": row_persisted,
                    "original_error": str(exc),
                },
            ) from exc
        raise
    return verified


__all__ = [
    "bind_skill_materialized",
    "bundle_has_placeholders",
]
