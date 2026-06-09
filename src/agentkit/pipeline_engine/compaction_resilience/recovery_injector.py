"""PreToolUse hook: inject resume capsule after story-scoped compaction."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agentkit.pipeline_engine.compaction_resilience.artifacts import sha256_file
from agentkit.pipeline_engine.compaction_resilience.epoch_store import (
    CompactionEpochRepository,
    build_epoch_repository,
)
from agentkit.pipeline_engine.compaction_resilience.hook_io import (
    emit_additional_context,
    hook_cwd,
    load_json_file,
    read_hook_input,
    warn,
)
from agentkit.pipeline_engine.compaction_resilience.models import (
    AgentManifest,
    coerce_json_object,
    valid_agent_id,
)
from agentkit.pipeline_engine.compaction_resilience.paths import (
    first_tool_path,
    manifest_path,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

_MUTATING_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "Bash", "Agent"})


def run(
    data: dict[str, Any],
    *,
    repository: CompactionEpochRepository | None = None,
    project_root: Path | None = None,
) -> str | None:
    """Process one PreToolUse event. Returns injected context, if any."""
    agent_id = _agent_id_from_input(data)
    if not valid_agent_id(agent_id):
        warn("invalid or missing agent_id; rejecting before path construction")
        return None
    root = project_root or hook_cwd(data)
    path = manifest_path(root, agent_id)
    if not path.is_file():
        warn(f"manifest for agent_id={agent_id!r} is absent; no recovery injection")
        return None
    payload = load_json_file(path)
    if payload is None:
        return None
    try:
        manifest = AgentManifest.model_validate(payload)
    except ValidationError as exc:
        warn(f"manifest validation failed: {exc}; no recovery injection")
        return None
    first_path = first_tool_path(root, agent_id)
    if not first_path.exists():
        atomic_write_text(first_path, "", newline="")
        return None
    repo = repository or build_epoch_repository(root)
    try:
        current_epoch = repo.read_epoch(manifest.project_key, manifest.story_id)
    except Exception as exc:  # noqa: BLE001
        warn(f"epoch store read failed: {exc}; no recovery injection")
        return None
    if current_epoch <= manifest.recovered_epoch:
        return None
    if not _hash_matches(manifest.resume_capsule_file, manifest.resume_capsule_hash):
        warn("resume capsule hash mismatch; no recovery injection")
        return None
    try:
        capsule = manifest.resume_capsule_file.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"cannot read resume capsule: {exc}; no recovery injection")
        return None
    context = _build_context(
        capsule,
        prompt_file=manifest.prompt_file,
        tool_name=str(data.get("tool_name") or ""),
    )
    updated = manifest.model_copy(update={"recovered_epoch": current_epoch})
    atomic_write_text(path, updated.model_dump_json(indent=2) + "\n", newline="")
    emit_additional_context(context)
    return context


def _agent_id_from_input(data: dict[str, Any]) -> str:
    direct = data.get("agent_id")
    if isinstance(direct, str):
        return direct
    tool_context = coerce_json_object(data.get("toolUseContext"))
    candidate = tool_context.get("agent_id")
    if isinstance(candidate, str):
        return candidate
    snake_context = coerce_json_object(data.get("tool_use_context"))
    candidate = snake_context.get("agent_id")
    return candidate if isinstance(candidate, str) else ""


def _hash_matches(path: Path, expected: str) -> bool:
    try:
        return sha256_file(path) == expected
    except OSError:
        return False


def _build_context(capsule: str, *, prompt_file: Path, tool_name: str) -> str:
    warning = (
        "[COMPACTION RECOVERY WARNING - mutating tool allowed after context restore]\n\n"
        if tool_name in _MUTATING_TOOLS
        else ""
    )
    return (
        f"{warning}"
        "[COMPACTION RECOVERY - Original task restored]\n\n"
        f"{capsule}\n\n"
        f"Canonical full prompt: {prompt_file.as_posix()}\n"
        "[END COMPACTION RECOVERY]"
    )


def main() -> None:
    """CLI entry point. Always exits 0 per FK-36 fail-open hook contract."""
    try:
        run(read_hook_input())
    except Exception as exc:  # noqa: BLE001
        warn(f"unexpected recovery_injector failure: {exc}; fail-open")
    sys.exit(0)


if __name__ == "__main__":
    main()
