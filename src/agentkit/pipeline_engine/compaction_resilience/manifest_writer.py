"""SubagentStart hook: materialize the per-agent FK-36 manifest."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agentkit.boundary.shared.time import now_iso
from agentkit.pipeline_engine.compaction_resilience.artifacts import sha256_file
from agentkit.pipeline_engine.compaction_resilience.epoch_store import (
    CompactionEpochRepository,
    build_epoch_repository,
)
from agentkit.pipeline_engine.compaction_resilience.hook_io import (
    hook_cwd,
    load_json_file,
    read_hook_input,
    warn,
)
from agentkit.pipeline_engine.compaction_resilience.models import (
    AgentManifest,
    SpawnSpec,
    parse_spawn_key,
    valid_agent_id,
)
from agentkit.pipeline_engine.compaction_resilience.paths import (
    manifest_path,
    spawn_spec_path,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


def run(
    data: dict[str, Any],
    *,
    repository: CompactionEpochRepository | None = None,
    project_root: Path | None = None,
) -> bool:
    """Process one SubagentStart event. Returns True when a manifest was written."""
    agent_id = str(data.get("agent_id") or "")
    if not valid_agent_id(agent_id):
        warn("invalid or missing agent_id; rejecting before path construction")
        return False
    spawn_key = str(data.get("agent_type") or data.get("subagent_type") or "")
    parsed = parse_spawn_key(spawn_key)
    if parsed is None:
        warn("spawn_key is not FK-36-managed; no manifest written")
        return False
    root = project_root or _find_project_root(hook_cwd(data), parsed.story_id, spawn_key)
    spec_path = spawn_spec_path(root, parsed.story_id, spawn_key)
    payload = load_json_file(spec_path)
    if payload is None:
        warn(f"spawn-spec missing or invalid at {spec_path}; no manifest written")
        return False
    try:
        spec = SpawnSpec.model_validate(payload)
    except ValidationError as exc:
        warn(f"spawn-spec validation failed at {spec_path}: {exc}; no manifest written")
        return False
    if spec.spawn_key != spawn_key or spec.story_id != parsed.story_id:
        warn("spawn-spec identity does not match spawn_key; no manifest written")
        return False
    if not _hash_matches(spec.resume_capsule_file, spec.resume_capsule_hash):
        warn("resume capsule hash mismatch; no manifest written")
        return False
    repo = repository or build_epoch_repository(root)
    try:
        baseline_epoch = repo.read_epoch(spec.project_key, spec.story_id)
    except Exception as exc:  # noqa: BLE001
        warn(f"epoch store read failed: {exc}; no manifest written")
        return False
    manifest = AgentManifest(
        agent_id=agent_id,
        spawn_key=spawn_key,
        story_id=spec.story_id,
        project_key=spec.project_key,
        prompt_file=spec.prompt_file,
        prompt_hash=spec.prompt_hash,
        resume_capsule_file=spec.resume_capsule_file,
        resume_capsule_hash=spec.resume_capsule_hash,
        guardrail_version=spec.guardrail_version,
        baseline_epoch=baseline_epoch,
        recovered_epoch=baseline_epoch,
        created_at=now_iso(),
    )
    atomic_write_text(
        manifest_path(root, agent_id),
        manifest.model_dump_json(indent=2) + "\n",
        newline="",
    )
    return True


def _find_project_root(cwd: Path, story_id: str, spawn_key: str) -> Path:
    for candidate in (cwd, *cwd.parents):
        if spawn_spec_path(candidate, story_id, spawn_key).is_file():
            return candidate
    return cwd


def _hash_matches(path: Path, expected: str) -> bool:
    try:
        return sha256_file(path) == expected
    except OSError:
        return False


def main() -> None:
    """CLI entry point. Always exits 0 per FK-36 fail-open hook contract."""
    try:
        run(read_hook_input())
    except Exception as exc:  # noqa: BLE001
        warn(f"unexpected manifest_writer failure: {exc}; fail-open")
    sys.exit(0)


if __name__ == "__main__":
    main()
