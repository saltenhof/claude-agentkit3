"""Prompt composition -- builds complete prompts from templates and context.

Owner: ``materialization`` sub of the prompt-runtime BC (bc-cut-decisions
§BC 10; module prefix ``agentkit.backend.prompt_runtime``). Renders dynamic
prompts and materializes run-scoped agent prompt instances under
``{project_root}/.agentkit/prompts/{run_id}/{invocation_id}/prompt.md``
(FK-44 §44.4.1). Static prompts are projected from the pinned central
bundle file via hardlink/symlink (copy only as platform fallback). The
loose run-scoped ``manifest.json`` is a convenience file for agents and
**not** the audit truth -- the audit record is persisted via
``artifacts.ArtifactManager`` (FK-44 §44.6, see ``audit.py``/``runtime.py``).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.core_types import SpawnReason
from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.paths import prompt_instance_dir
from agentkit.backend.prompt_runtime.pins import resolve_run_prompt_binding
from agentkit.backend.prompt_runtime.resources import (
    load_prompt_template,
    load_prompt_template_from_binding,
    prompt_template_relpath,
    prompt_template_relpath_from_binding,
    prompt_template_sha256,
    prompt_template_sha256_from_binding,
    resolve_bootstrap_prompt_binding,
)
from agentkit.backend.prompt_runtime.selectors import select_template_name
from agentkit.backend.prompt_runtime.sentinels import extract_sentinel
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryMode, StoryType


# Run-scoped materialized prompt-instance filename (FK-44 §44.4.1).
_PROMPT_INSTANCE_FILENAME = "prompt.md"


@dataclass(frozen=True)
class ComposedPrompt:
    content: str
    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_manifest_sha256: str
    logical_prompt_id: str
    template_name: str
    template_relpath: str
    render_mode: str
    template_sha256: str
    render_input_digest: str
    output_sha256: str
    story_id: str
    sentinel: str


@dataclass(frozen=True)
class MaterializedPromptInstance:
    prompt_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class StaticMaterializedPromptInstance:
    """Result of a static (hardlink/symlink/copy) prompt projection.

    Attributes:
        prompt_path: Run-scoped instance path that agents consume.
        render_mode: Always ``"static"`` (FK-44 §44.4.1).
        link_mode: How the projection was created -- ``"hardlink"``,
            ``"symlink"`` or ``"copy"`` (copy only as platform fallback).
        template_sha256: Digest of the canonical template bytes.
        output_sha256: Digest of the materialized bytes (equals
            ``template_sha256`` for a faithful static projection).
    """

    prompt_path: Path
    render_mode: str
    link_mode: str
    template_sha256: str
    output_sha256: str


@dataclass(frozen=True)
class ComposeConfig:
    story_type: StoryType
    execution_route: StoryMode | None = None
    spawn_reason: SpawnReason = SpawnReason.INITIAL
    round_nr: int = 1
    feedback: str = ""


@dataclass(frozen=True)
class WorkerWorktreeContext:
    """Rendered worker worktree context from FK-22 §22.6.4."""

    prompt_markdown: str
    spawn_cwd: str
    worktree_map: dict[str, str]


@dataclass(frozen=True)
class _ResolvedPromptSource:
    binding_bundle_id: str
    binding_bundle_version: str
    binding_manifest_sha256: str
    template_text: str
    template_relpath: str
    template_sha256: str


def _build_placeholder_map(
    ctx: StoryContext,
    config: ComposeConfig,
) -> dict[str, str]:
    project_root = str(ctx.project_root) if ctx.project_root is not None else "N/A"
    body = (
        config.feedback
        if config.spawn_reason is SpawnReason.REMEDIATION
        else ctx.title
    )
    worktree_context = build_worker_worktree_context(ctx)
    return {
        "story_id": ctx.story_id,
        "title": ctx.title,
        "mode": str(ctx.execution_route.value) if ctx.execution_route else "N/A",
        "size": "N/A",
        "body": body,
        "project_root": project_root,
        "round_nr": str(config.round_nr),
        "feedback": config.feedback,
        "worktree_context": worktree_context.prompt_markdown,
        "spawn_cwd": worktree_context.spawn_cwd,
    }


def build_worker_worktree_context(ctx: StoryContext) -> WorkerWorktreeContext:
    """Build the worker-facing worktree context.

    For multi-repo stories, FK-22 §22.6.4 requires a worktree map from
    repo name to worktree path and uses the first participating repo
    only as deterministic spawn CWD. For single-repo stories, the worker
    receives one worktree path and no map.
    """
    repo_names = list(ctx.participating_repos)
    worktree_map = {
        repo_name: _format_prompt_path(path)
        for repo_name, path in ctx.worktree_map.items()
    }

    if len(repo_names) >= 2:
        rows = [
            "| Repo | Worktree-Pfad |",
            "|---|---|",
        ]
        for repo_name in repo_names:
            rows.append(f"| {repo_name} | {worktree_map.get(repo_name, 'N/A')} |")
        spawn_cwd = worktree_map.get(repo_names[0], "N/A")
        prompt_markdown = "\n".join(
            [
                "Multi-Repo-Worktree-Map:",
                *rows,
                "",
                f"Spawn-CWD: {spawn_cwd}",
                (
                    "Schreiben in nicht-teilnehmende Repos ist verboten; "
                    "nicht-teilnehmende Repos sind nur lesend zu nutzen."
                ),
            ],
        )
        return WorkerWorktreeContext(
            prompt_markdown=prompt_markdown,
            spawn_cwd=spawn_cwd,
            worktree_map=worktree_map,
        )

    single_path = (
        _format_prompt_path(ctx.worktree_path)
        if ctx.worktree_path is not None
        else "N/A"
    )
    if repo_names and repo_names[0] in worktree_map:
        single_path = worktree_map[repo_names[0]]
    prompt_markdown = "\n".join(
        [
            f"Worktree-Pfad: {single_path}",
            f"Spawn-CWD: {single_path}",
            (
                "Schreiben in nicht-teilnehmende Repos ist verboten; "
                "nicht-teilnehmende Repos sind nur lesend zu nutzen."
            ),
        ],
    )
    return WorkerWorktreeContext(
        prompt_markdown=prompt_markdown,
        spawn_cwd=single_path,
        worktree_map=worktree_map,
    )


def _format_prompt_path(path: Path) -> str:
    """Render filesystem paths in prompts with stable separators."""
    return path.as_posix()


def _logical_prompt_id(template_name: str) -> str:
    return f"prompt.{template_name}"


def _render_input_digest(placeholders: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(placeholders, sort_keys=True).encode("utf-8"),
    ).hexdigest()


def _resolve_prompt_source(
    *,
    template_name: str,
    project_root: Path | None,
    story_id: str,
    run_id: str | None,
) -> _ResolvedPromptSource:
    if project_root is None:
        binding = resolve_bootstrap_prompt_binding()
        # Bootstrap (non-project) context: no run pin exists; resolve from
        # the internal resource manifest.
        return _ResolvedPromptSource(
            binding_bundle_id=binding.bundle_id,
            binding_bundle_version=binding.bundle_version,
            binding_manifest_sha256=binding.manifest_sha256,
            template_text=load_prompt_template(template_name),
            template_relpath=prompt_template_relpath(template_name),
            template_sha256=prompt_template_sha256(template_name),
        )
    if run_id is None:
        raise ProjectError(
            "Prompt composition for a project-bound run requires run_id",
            detail={"story_id": story_id},
        )
    # Active run: the pin is the authority. Template bytes AND metadata
    # (relpath, sha256) are resolved from the pin-resolved binding, never
    # from the (possibly rebound) project lock -- this is what makes
    # binding_changes_affect_only_future_runs (C2, FK-44 §44.3) hold for the
    # actual materialized content, not only for the binding coordinates.
    binding = resolve_run_prompt_binding(project_root, run_id)
    return _ResolvedPromptSource(
        binding_bundle_id=binding.bundle_id,
        binding_bundle_version=binding.bundle_version,
        binding_manifest_sha256=binding.manifest_sha256,
        template_text=load_prompt_template_from_binding(template_name, binding),
        template_relpath=prompt_template_relpath_from_binding(
            template_name,
            binding,
        ),
        template_sha256=prompt_template_sha256_from_binding(
            template_name,
            binding,
        ),
    )


def compose_named_prompt(
    ctx: StoryContext,
    template_name: str,
    config: ComposeConfig,
    *,
    run_id: str | None = None,
) -> ComposedPrompt:
    project_root = ctx.project_root
    source = _resolve_prompt_source(
        template_name=template_name,
        project_root=project_root,
        story_id=ctx.story_id,
        run_id=run_id,
    )
    placeholders = _build_placeholder_map(ctx, config)
    render_input_digest = _render_input_digest(placeholders)
    content = source.template_text.format_map(placeholders)

    sentinel_data = extract_sentinel(content)
    if sentinel_data is None:
        msg = (
            f"Rendered template '{template_name}' does not contain a "
            f"valid sentinel marker"
        )
        raise ValueError(msg)

    sentinel = (
        f"[SENTINEL:{sentinel_data['template']}"
        f"-v{sentinel_data['version']}"
        f":{sentinel_data['story_id']}]"
    )
    output_sha256 = hashlib.sha256(
        content.encode("utf-8"),
    ).hexdigest()

    return ComposedPrompt(
        content=content,
        prompt_bundle_id=source.binding_bundle_id,
        prompt_bundle_version=source.binding_bundle_version,
        prompt_manifest_sha256=source.binding_manifest_sha256,
        logical_prompt_id=_logical_prompt_id(template_name),
        template_name=template_name,
        template_relpath=source.template_relpath,
        render_mode="rendered",
        template_sha256=source.template_sha256,
        render_input_digest=render_input_digest,
        output_sha256=output_sha256,
        story_id=ctx.story_id,
        sentinel=sentinel,
    )


def compose_prompt(
    ctx: StoryContext,
    config: ComposeConfig,
    *,
    run_id: str | None = None,
) -> ComposedPrompt:
    template_name = select_template_name(
        story_type=config.story_type,
        execution_route=config.execution_route,
        spawn_reason=config.spawn_reason,
    )
    return compose_named_prompt(
        ctx,
        template_name,
        config,
        run_id=run_id,
    )


def write_prompt(
    prompt: ComposedPrompt,
    output_dir: Path,
    *,
    spawn_reason: SpawnReason = SpawnReason.INITIAL,
    round_nr: int = 1,
) -> Path:
    filename = f"{prompt.template_name}--{spawn_reason.value}--r{round_nr}.md"
    path = output_dir / filename
    atomic_write_text(path, prompt.content)
    return path


def write_prompt_instance(
    prompt: ComposedPrompt,
    project_root: Path,
    *,
    run_id: str,
    invocation_id: str,
) -> MaterializedPromptInstance:
    """Write the canonical run-scoped prompt artifact set."""

    output_dir = prompt_instance_dir(project_root, run_id, invocation_id)
    # Materialization resolves the EXISTING pin (fail-closed if missing); it
    # must NOT re-pin from the current project lock, otherwise a legitimate
    # mid-run rebind would trip a spurious PROMPT_RUN_PIN_MISMATCH (C2, FK-44
    # §44.3). The pin is established at run start via create_run_pin.
    binding = resolve_run_prompt_binding(project_root, run_id)
    if (
        prompt.prompt_bundle_id != binding.bundle_id
        or prompt.prompt_bundle_version != binding.bundle_version
        or prompt.prompt_manifest_sha256 != binding.manifest_sha256
    ):
        raise ProjectError(
            "Prompt instance metadata does not match the active run pin",
            detail={
                "run_id": run_id,
                "expected": {
                    "prompt_bundle_id": binding.bundle_id,
                    "prompt_bundle_version": binding.bundle_version,
                    "prompt_manifest_sha256": binding.manifest_sha256,
                },
                "actual": {
                    "prompt_bundle_id": prompt.prompt_bundle_id,
                    "prompt_bundle_version": prompt.prompt_bundle_version,
                    "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                },
            },
        )
    prompt_path = output_dir / _PROMPT_INSTANCE_FILENAME
    manifest_path = output_dir / "manifest.json"
    # newline="" disables platform newline translation so the on-disk bytes
    # equal prompt.content.encode("utf-8") byte-for-byte. prompt.output_sha256
    # is computed from those bytes, so the audit digest faithfully reflects
    # the consumed bytes on every platform (FK-44 §44.6, byte reproducibility).
    atomic_write_text(prompt_path, prompt.content, newline="")
    atomic_write_text(
        manifest_path,
        json.dumps(
            {
                "run_id": run_id,
                "invocation_id": invocation_id,
                "story_id": prompt.story_id,
                "prompt_bundle_id": prompt.prompt_bundle_id,
                "prompt_bundle_version": prompt.prompt_bundle_version,
                "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                "prompt_instance_id": invocation_id,
                "logical_prompt_id": prompt.logical_prompt_id,
                "template_name": prompt.template_name,
                "template_relpath": prompt.template_relpath,
                "render_mode": prompt.render_mode,
                "template_sha256": prompt.template_sha256,
                "render_input_digest": prompt.render_input_digest,
                "output_sha256": prompt.output_sha256,
                "artifact_path": prompt_path.relative_to(project_root).as_posix(),
                "prompt_file": _PROMPT_INSTANCE_FILENAME,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return MaterializedPromptInstance(
        prompt_path=prompt_path,
        manifest_path=manifest_path,
    )


def _project_static_prompt(source: Path, target: Path) -> str:
    """Project ``source`` to ``target`` and report the link mode used.

    FK-44 §44.4.1: static prompts are projected from the pinned central
    bundle file via hardlink (preferred), then symlink, falling back to a
    copy only when the platform rejects both. Returns the mode used.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    try:
        os.link(source, target)
        return "hardlink"
    except OSError as link_exc:
        if not _can_fallback_to_symlink(link_exc):
            _raise_static_projection_error(source, target, link_exc)
    try:
        os.symlink(source, target)
        return "symlink"
    except OSError as symlink_exc:
        if not _can_fallback_to_copy(symlink_exc):
            _raise_static_projection_error(source, target, symlink_exc)
    import shutil

    try:
        shutil.copy2(source, target)
    except OSError as copy_exc:
        _raise_static_projection_error(source, target, copy_exc)
    return "copy"


def _can_fallback_to_symlink(exc: OSError) -> bool:
    return exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17


def _can_fallback_to_copy(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 1314


def _raise_static_projection_error(
    source: Path,
    target: Path,
    exc: OSError,
) -> None:
    raise ProjectError(
        f"Failed to project static prompt from {source} to {target}: {exc}",
        detail={"source": str(source), "target": str(target), "error": str(exc)},
    ) from exc


def materialize_static_prompt_instance(
    project_root: Path,
    *,
    run_id: str,
    invocation_id: str,
    template_name: str,
) -> StaticMaterializedPromptInstance:
    """Materialize a static agent prompt by projecting the pinned bundle file.

    Resolves the pin-authoritative bundle for the run, locates the
    canonical template inside the central bundle store, and projects it to
    the run-scoped instance path via hardlink/symlink/copy (FK-44
    §44.4.1). The source/target therefore share the same bytes; for a
    hardlink they share the same inode.

    Args:
        project_root: Project root.
        run_id: Active run id (must already be pinned).
        invocation_id: Spawn/invocation id.
        template_name: Logical template name to project.

    Returns:
        A ``StaticMaterializedPromptInstance`` with the projection mode and
        digests.

    Raises:
        ProjectError: If the run pin/bundle is missing or the projection
            fails (fail-closed).
    """
    # Resolve the EXISTING pin (fail-closed if missing); never re-pin from the
    # current lock (C2, FK-44 §44.3).
    binding = resolve_run_prompt_binding(project_root, run_id)
    # Pin-authoritative: relpath and template digest come from the
    # pin-resolved binding, not the (possibly rebound) project lock, so a
    # mid-run rebind cannot change the static projection source (C2, FK-44
    # §44.3).
    relpath = prompt_template_relpath_from_binding(template_name, binding)
    template_sha256 = prompt_template_sha256_from_binding(
        template_name,
        binding,
    )
    source = binding.bundle_root / relpath
    if not source.is_file():
        raise ProjectError(
            f"Static prompt source is missing in the pinned bundle: {source}",
            detail={
                "run_id": run_id,
                "template_name": template_name,
                "source": str(source),
            },
        )
    output_dir = prompt_instance_dir(project_root, run_id, invocation_id)
    prompt_path = output_dir / _PROMPT_INSTANCE_FILENAME
    link_mode = _project_static_prompt(source, prompt_path)
    output_sha256 = hashlib.sha256(
        prompt_path.read_bytes(),
    ).hexdigest()
    return StaticMaterializedPromptInstance(
        prompt_path=prompt_path,
        render_mode="static",
        link_mode=link_mode,
        template_sha256=template_sha256,
        output_sha256=output_sha256,
    )


__all__ = [
    "ComposeConfig",
    "ComposedPrompt",
    "MaterializedPromptInstance",
    "StaticMaterializedPromptInstance",
    "WorkerWorktreeContext",
    "build_worker_worktree_context",
    "compose_named_prompt",
    "compose_prompt",
    "materialize_static_prompt_instance",
    "write_prompt",
    "write_prompt_instance",
]
