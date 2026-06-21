"""Path/object classes and deterministic path classification (FK-55 §55.4/§55.10.2).

:class:`PathClass` transcribes the **eight** canonical path classes of FK-55
§55.4 (same wire values as the FK-55 glossary ``path-class`` term) — exactly
eight, no synthetic ninth value (AG3-032 AK3 / FK-55 §55.4).

:class:`PathClassifier` normalizes a target path to exactly one class using only
cheap prefix / suffix matching (FK-55 §55.10.2 performance rule — no semantic
shell interpretation). If no rule matches, :meth:`PathClassifier.classify`
returns ``None`` — the *unclassified sentinel*. There is no 9th wire
:class:`PathClass` and no 9th matrix column: the enforcement turns an
unclassified target into a hard ``BLOCK`` directly (FK-55 §55.10.2: "If a target
cannot be resolved cheaply and canonically, the decision is fail-closed BLOCK").
Returning a sentinel — rather than a synthetic enum member — keeps the matrix at
the canonical 8 columns while staying fail-closed.

Story scope (FK-55 §55.7.1) is the set of participating-repo / worktree roots,
project-local story working dirs and registered sandboxes — NOT a substring
match on the story id. A real worktree without the id in its path classifies
in-scope; an arbitrary path that merely contains the id does not.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from agentkit.backend.core_types.plane_artifact_names import (
    CONTENT_PLANE_FILES,
    CONTROL_PLANE_FILES,
    SELF_PROTECTION_CONFIG_FILE_PARTS,
    SELF_PROTECTION_HOOK_SETTINGS_PARTS,
    SELF_PROTECTION_SYMLINK_DIR_PARTS,
)
from agentkit.backend.core_types.qa_artifact_names import ALL_QA_ARTIFACT_FILES, GUARDRAIL_FILE

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class PathClass(StrEnum):
    """The eight canonical AK3 path/object classes (FK-55 §55.4).

    Wire values are normative (FK-55 glossary ``path-class``). There are exactly
    eight members; there is deliberately **no** ``UNCLASSIFIED`` enum value — an
    unclassifiable target is represented by the ``None`` sentinel returned by
    :meth:`PathClassifier.classify` and turned into a hard ``BLOCK`` by the
    enforcement (FK-55 §55.10.2).
    """

    CODEBASE_STORY_SCOPE = "codebase_story_scope"
    CODEBASE_OUT_OF_SCOPE = "codebase_out_of_scope"
    QA_SANDBOX = "qa_sandbox"
    CONTROL_PLANE = "control_plane"
    CONTENT_PLANE = "content_plane"
    GOVERNANCE_PLANE = "governance_plane"
    GIT_INTERNAL = "git_internal"
    REPO_ADMIN_SURFACE = "repo_admin_surface"


#: Content-plane artifact basenames (FK-55 §55.4). Wire strings live in
#: ``core_types.plane_artifact_names`` (truth boundary: governance modules may
#: not hold these literals). Orchestrator-locked.
_CONTENT_PLANE_FILES: frozenset[str] = frozenset(CONTENT_PLANE_FILES)

#: Control-plane artifact basenames (FK-55 §55.4). Wire strings live in
#: ``core_types.plane_artifact_names``. Orchestrator-readable.
_CONTROL_PLANE_FILES: frozenset[str] = frozenset(CONTROL_PLANE_FILES)

#: QA-artifact basenames that are content of the QA-Subflow (FK-27). They live
#: under the QA story dir; writing them out of band is governance-protected.
_QA_ARTIFACT_FILES: frozenset[str] = frozenset(
    {*ALL_QA_ARTIFACT_FILES, GUARDRAIL_FILE}
)

#: Self-protection registry EXACT-file segment tuples (FK-30 §30.5.4): harness
#: hook-settings (``.claude/settings.json``, ``.codex/config.toml``,
#: ``.codex/hooks.json``) plus governance config / installer manifest
#: (``.agentkit/config/project.yaml``, ``.installed-manifest.json``). They are
#: "guardrail states" in the FK-55 §55.4 sense — platform self-governance
#: state that "only official service paths" may mutate — and therefore classify
#: as :attr:`PathClass.GOVERNANCE_PLANE` (AG3-033: closes the dead-whitelist
#: inconsistency where these paths were UNCLASSIFIED and hard-blocked for ALL
#: principals before the SelfProtectionGuard could narrow by zone). Wire literals
#: live in ``core_types.plane_artifact_names`` (SINGLE SOURCE OF TRUTH /
#: Truth-Boundary — no second source here).
_SELF_PROTECTION_FILE_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_HOOK_SETTINGS_PARTS,
    *SELF_PROTECTION_CONFIG_FILE_PARTS,
)

#: Self-protection registry DIRECTORY-prefix segment tuples (FK-30 §30.5.4 /
#: FK-15 §15.7.1): the CCAG-rule / skill-symlink dirs (``.agentkit/ccag/rules``,
#: ``.claude/ccag/rules``, ``.claude/skills``). A mutation UNDER any of these is
#: governance-plane (FK-55 §55.4 guardrail states). Same canonical source.
_SELF_PROTECTION_DIR_PARTS: tuple[tuple[str, ...], ...] = (
    *SELF_PROTECTION_SYMLINK_DIR_PARTS,
)


class PathClassifier:
    """Deterministically maps a target path to a :class:`PathClass` or ``None``.

    The classification is fail-closed and order-sensitive: the most protected
    classes are tested first so a path under, e.g., ``.git/`` can never be
    re-interpreted as story scope (FK-55 §55.10.2 — Bash file mutations under
    ``.git/**``, ``_temp/governance/**`` and content-plane must be recognised
    directly).

    Story scope (FK-55 §55.7.1) is resolved against the *actual* story-scope
    roots passed in ``story_scope_roots`` (participating-repo / worktree roots,
    project-local story dirs, registered sandboxes), not a substring match on
    the story id.
    """

    def classify(
        self,
        path: Path | str,
        project_root: Path | str,
        story_id: str | None = None,
        story_scope_roots: Sequence[str] | None = None,
    ) -> PathClass | None:
        """Classify ``path`` relative to ``project_root`` and the active story.

        Args:
            path: The target path of the operation (may be absolute or
                project-relative; OS-native or POSIX separators).
            project_root: The project root the path is resolved against.
            story_id: The active story id, used to recognise the QA story dir
                and the repo-admin story surface. ``None`` when no story is
                bound.
            story_scope_roots: The FK-55 §55.7.1 story-scope roots
                (participating-repo / worktree roots, registered sandboxes).
                A path under any of these roots classifies as
                ``CODEBASE_STORY_SCOPE``. ``None`` / empty when no story scope
                is bound.

        Returns:
            Exactly one :class:`PathClass`, or ``None`` when no rule matches
            (the unclassified sentinel — the enforcement turns this into a
            fail-closed ``BLOCK``, FK-55 §55.10.2).
        """
        segments = _norm_segments(path)
        if not segments:
            return None
        basename = segments[-1]

        if ".git" in segments:
            return PathClass.GIT_INTERNAL
        if self._is_governance_plane(segments):
            return PathClass.GOVERNANCE_PLANE
        if self._is_qa_sandbox(segments):
            return PathClass.QA_SANDBOX
        if self._is_repo_admin_surface(segments, story_id):
            return PathClass.REPO_ADMIN_SURFACE
        if basename in _CONTENT_PLANE_FILES or basename in _QA_ARTIFACT_FILES:
            return PathClass.CONTENT_PLANE
        if basename in _CONTROL_PLANE_FILES:
            return PathClass.CONTROL_PLANE
        if self._is_story_scope(path, project_root, story_id, story_scope_roots):
            return PathClass.CODEBASE_STORY_SCOPE
        if self._is_productive_codebase(segments):
            return PathClass.CODEBASE_OUT_OF_SCOPE
        return None

    @staticmethod
    def _is_governance_plane(segments: list[str]) -> bool:
        # _temp/governance/**, lock exports, guardrail states (FK-55 §55.4).
        if ".agentkit" in segments and "governance" in segments:
            return True
        if ".agent-guard" in segments:
            return True
        if "_temp" in segments and "governance" in segments:
            return True
        # Self-protection registry (FK-30 §30.5.4): harness hook-settings,
        # CCAG-/skill-symlink dirs and governance config / installer manifest are
        # "guardrail states" (FK-55 §55.4 governance_plane: "only official
        # service paths"). Precise: exact files + dir-prefix runs only — NOT all of
        # ``.claude``/``.codex`` (arbitrary harness working files stay
        # unclassified). AG3-033: this makes the capability matrix coherent
        # (worker DENY, official principals ALLOW) so the SelfProtectionGuard can
        # narrow harness-zone paths to pipeline_deterministic only.
        if _ends_with_file(segments, _SELF_PROTECTION_FILE_PARTS):
            return True
        return _contains_dir_run(segments, _SELF_PROTECTION_DIR_PARTS)

    @staticmethod
    def _is_qa_sandbox(segments: list[str]) -> bool:
        # _temp/adversarial/{story_id}/, ephemeral QA work areas (FK-55 §55.4).
        return "_temp" in segments and "adversarial" in segments

    @staticmethod
    def _is_repo_admin_surface(segments: list[str], story_id: str | None) -> bool:
        # Story status / story attributes in the AK3 story backend; split/reset actions.
        if "stories" not in segments:
            return False
        if story_id is None:
            return "stories" in segments
        try:
            idx = segments.index("stories")
        except ValueError:
            return False
        tail = segments[idx + 1 :]
        return story_id in tail and "status.yaml" in tail

    @staticmethod
    def _is_story_scope(
        path: Path | str,
        project_root: Path | str,
        story_id: str | None,
        story_scope_roots: Sequence[str] | None,
    ) -> bool:
        """Story scope = under a participating worktree/sandbox root (FK-55 §55.7.1).

        A path is in story scope iff it lies under one of the bound story-scope
        roots (worktree roots / registered sandboxes / project-local story dir).
        We do NOT match on the story id appearing as a path segment: a real
        worktree need not carry the id, and an arbitrary path that merely
        contains the id is not in scope.
        """
        if story_id is None:
            return False
        target = _norm_segments(path)
        if not target:
            return False
        # Resolve the candidate roots: explicit scope roots (worktree roots /
        # sandboxes) plus the project-local story working dir under the project
        # root (FK-55 §55.7.1 item 2).
        roots: list[list[str]] = []
        for root in story_scope_roots or ():
            root_segments = _norm_segments(root)
            if root_segments:
                roots.append(root_segments)
        # Project-local story dir (e.g. <project_root>/<story_id>/...).
        project_segments = _norm_segments(project_root)
        if project_segments:
            roots.append([*project_segments, story_id])
        return any(_is_under(target, root) for root in roots)

    @staticmethod
    def _is_productive_codebase(segments: list[str]) -> bool:
        # Productive repo paths outside the story scope (FK-55 §55.4).
        return "src" in segments or "tests" in segments


def _is_under(target: list[str], root: list[str]) -> bool:
    """Return whether ``target`` segments are equal to or below ``root``.

    Cheap prefix comparison only (FK-55 §55.10.2): no filesystem access.
    """
    if not root or len(root) > len(target):
        return False
    return target[: len(root)] == root


def _ends_with_file(segments: list[str], file_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` ends with one of the exact protected file tuples.

    Cheap suffix comparison only (FK-55 §55.10.2): no filesystem access.
    """
    return any(
        len(parts) <= len(segments) and parts == tuple(segments[-len(parts) :])
        for parts in file_parts
    )


def _contains_dir_run(segments: list[str], dir_parts: tuple[tuple[str, ...], ...]) -> bool:
    """Whether ``segments`` contains one of the protected dir tuples as a run.

    A mutation UNDER (or AT) a protected directory matches. Cheap contiguous-run
    comparison only (FK-55 §55.10.2): no filesystem access.
    """
    return any(_run_matches(segments, parts) for parts in dir_parts)


def _run_matches(segments: list[str], parts: tuple[str, ...]) -> bool:
    """Whether ``parts`` appears as a contiguous run within ``segments``."""
    width = len(parts)
    if width == 0 or width > len(segments):
        return False
    return any(
        parts == tuple(segments[start : start + width])
        for start in range(len(segments) - width + 1)
    )


def _norm_segments(path: Path | str) -> list[str]:
    """Split a path into non-empty segments, tolerating OS/POSIX separators.

    Cheap normalization only (FK-55 §55.10.2): no filesystem access, no symlink
    resolution. Handles both ``\\`` (Windows) and ``/`` (POSIX) so a Linux CI
    run and a Windows dev run classify identically.
    """
    raw = str(path).replace("\\", "/")
    posix = PurePosixPath(raw)
    parts = [p for p in posix.parts if p not in ("", "/")]
    if not parts:
        # Pure Windows drive paths (``C:\\x``) degrade to a single part above;
        # fall back to the Windows parser for robustness.
        parts = [p for p in PureWindowsPath(str(path)).parts if p not in ("", "\\")]
    return [p for p in parts if not _is_drive_or_root(p)]


def _is_drive_or_root(segment: str) -> bool:
    return segment.endswith(":") or segment in ("/", "\\")


__all__ = [
    "PathClass",
    "PathClassifier",
]
