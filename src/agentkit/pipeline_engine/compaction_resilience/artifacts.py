"""Compose-time resume-capsule and spawn-spec production."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.boundary.shared.time import now_iso
from agentkit.pipeline_engine.compaction_resilience.models import (
    SpawnSpec,
    build_spawn_key,
)
from agentkit.pipeline_engine.compaction_resilience.paths import (
    resume_capsule_path,
    spawn_spec_path,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.prompt_runtime.composer import ComposeConfig
    from agentkit.story_context_manager.models import StoryContext

GUARDRAIL_VERSION = "2026-06-09.fk36"
RESUME_CAPSULE_MAX_CHARS = 8000


@dataclass(frozen=True)
class CompactionArtifacts:
    """Files produced beside a materialized prompt for compaction recovery."""

    spawn_key: str
    spawn_spec_path: Path
    resume_capsule_path: Path
    spawn_spec: SpawnSpec


def sha256_file(path: Path) -> str:
    """Return the SHA256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_compaction_artifacts(
    ctx: StoryContext,
    config: ComposeConfig,
    *,
    project_root: Path,
    prompt_file: Path,
    agent_type_base: str,
) -> CompactionArtifacts:
    """Write FK-36 resume-capsule and spawn-spec artifacts from structured data."""
    spawn_key = build_spawn_key(
        agent_type_base=agent_type_base,
        story_id=ctx.story_id,
        round_nr=config.round_nr,
    )
    capsule_path = resume_capsule_path(project_root, ctx.story_id, spawn_key)
    capsule = build_resume_capsule(
        ctx,
        prompt_file=prompt_file,
        spawn_key=spawn_key,
        guardrail_version=GUARDRAIL_VERSION,
    )
    atomic_write_text(capsule_path, capsule, newline="")
    spec_path = spawn_spec_path(project_root, ctx.story_id, spawn_key)
    spec = SpawnSpec(
        story_id=ctx.story_id,
        project_key=ctx.project_key,
        spawn_key=spawn_key,
        agent_type_base=agent_type_base,
        round=config.round_nr,
        prompt_file=prompt_file.resolve(),
        prompt_hash=sha256_file(prompt_file),
        resume_capsule_file=capsule_path.resolve(),
        resume_capsule_hash=sha256_file(capsule_path),
        guardrail_version=GUARDRAIL_VERSION,
        created_at=now_iso(),
    )
    atomic_write_text(
        spec_path,
        spec.model_dump_json(indent=2, by_alias=False) + "\n",
        newline="",
    )
    return CompactionArtifacts(
        spawn_key=spawn_key,
        spawn_spec_path=spec_path,
        resume_capsule_path=capsule_path,
        spawn_spec=spec,
    )


def build_resume_capsule(
    ctx: StoryContext,
    *,
    prompt_file: Path,
    spawn_key: str,
    guardrail_version: str,
) -> str:
    """Build the bounded structured resume capsule, never from prompt truncation."""
    sections = [
        "# Resume Capsule",
        "",
        f"- story_id: {ctx.story_id}",
        f"- project_key: {ctx.project_key}",
        f"- story_type: {ctx.story_type.value}",
        f"- execution_route: {ctx.execution_route.value if ctx.execution_route else 'none'}",
        f"- title: {_single_line(ctx.title)}",
        f"- spawn_key: {spawn_key}",
        f"- prompt_file: {prompt_file.resolve().as_posix()}",
        "",
        "## Scope",
        f"- project_root: {_path_or_na(ctx.project_root)}",
        f"- worktree_path: {_path_or_na(ctx.worktree_path)}",
        f"- participating_repos: {_json_list(ctx.participating_repos)}",
        f"- worktree_map: {_json_map({key: path.as_posix() for key, path in ctx.worktree_map.items()})}",
        f"- concept_paths: {_json_list(list(ctx.concept_paths))}",
        "",
        "## Story Contract",
        f"- story_size: {ctx.story_size.value}",
        f"- implementation_contract: {ctx.implementation_contract.value if ctx.implementation_contract else 'none'}",
        f"- labels: {_json_list(ctx.labels)}",
        f"- change_impact: {ctx.change_impact.value if ctx.change_impact else 'unknown'}",
        f"- concept_quality: {ctx.concept_quality.value if ctx.concept_quality else 'unknown'}",
        f"- new_structures: {ctx.new_structures}",
        "",
        f"## Guardrail Invariants ({guardrail_version})",
        "- Zero Debt: complete the agreed scope; do not leave silent gaps.",
        "- No Mock/Stub Ban: use real components except for narrow unit-test isolation.",
        "- No Error Bypassing: fix failing checks instead of weakening or skipping them.",
        "- Data Extraction Completeness: preserve authoritative structured data boundaries.",
        "- Evidence Required: no deliverable is complete without verifiable proof.",
        "",
        "## Canonical Long Form",
        "Use the prompt_file above as the single source of truth for the full task.",
        "",
    ]
    capsule = "\n".join(sections)
    if len(capsule) <= RESUME_CAPSULE_MAX_CHARS:
        return capsule
    suffix = "\n[resume capsule truncated to 8000 characters]\n"
    return capsule[: RESUME_CAPSULE_MAX_CHARS - len(suffix)] + suffix


def _single_line(value: str) -> str:
    return _clip(" ".join(value.split()), limit=512)


def _path_or_na(path: Path | None) -> str:
    return "N/A" if path is None else path.as_posix()


def _json_list(value: list[str]) -> str:
    return _clip(json.dumps(value, sort_keys=True), limit=1200)


def _json_map(value: dict[str, str]) -> str:
    return _clip(json.dumps(value, sort_keys=True), limit=1200)


def _clip(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "...[truncated]"
    return value[: limit - len(suffix)] + suffix


__all__ = [
    "CompactionArtifacts",
    "GUARDRAIL_VERSION",
    "RESUME_CAPSULE_MAX_CHARS",
    "build_resume_capsule",
    "sha256_file",
    "write_compaction_artifacts",
]
