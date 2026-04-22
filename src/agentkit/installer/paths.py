"""Standard paths for AgentKit's target project layout."""

from __future__ import annotations

import os
from pathlib import Path

AGENTKIT_DIR: str = ".agentkit"
CONFIG_DIR: str = f"{AGENTKIT_DIR}/config"
MANIFESTS_DIR: str = f"{AGENTKIT_DIR}/manifests"
PROMPTS_DIR: str = f"{AGENTKIT_DIR}/prompts"
STATIC_PROMPTS_DIR: str = "prompts"
TOOLS_DIR: str = "tools"
AGENTKIT_TOOLS_DIR: str = f"{TOOLS_DIR}/agentkit"
HOOKS_DIR: str = f"{AGENTKIT_DIR}/hooks"
STORIES_DIR: str = "stories"
PROJECT_CONFIG_FILE: str = "project.yaml"
CONTROL_PLANE_CONFIG_FILE: str = "control-plane.json"
PROMPT_BUNDLE_LOCK_FILE: str = "prompt-bundle.lock.json"
PROMPT_BUNDLE_STORE_ENV: str = "AGENTKIT_PROMPT_BUNDLE_STORE_ROOT"
PIPELINE_CONFIG_FILE: str = "story-pipeline.yaml"
PHASE_RUNS_DIR: str = "phase-runs"
CONTEXT_FILE: str = "context.json"
PHASE_STATE_FILE: str = "phase-state.json"


def agentkit_dir(project_root: Path) -> Path:
    return project_root / AGENTKIT_DIR


def config_dir(project_root: Path) -> Path:
    return project_root / CONFIG_DIR


def manifests_dir(project_root: Path) -> Path:
    return project_root / MANIFESTS_DIR


def project_config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / PROJECT_CONFIG_FILE


def control_plane_config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / CONTROL_PLANE_CONFIG_FILE


def default_prompt_bundle_store_root() -> Path:
    override = os.environ.get(PROMPT_BUNDLE_STORE_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "AgentKit" / "prompt-bundles"
    return Path("/var/lib/agentkit/prompt-bundles")


def prompt_bundle_store_root(explicit_root: Path | None = None) -> Path:
    if explicit_root is not None:
        return explicit_root
    return default_prompt_bundle_store_root()


def prompt_bundle_store_dir(
    bundle_id: str,
    bundle_version: str,
    *,
    store_root: Path | None = None,
) -> Path:
    return prompt_bundle_store_root(store_root) / bundle_id / bundle_version


def prompt_bundle_lock_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / PROMPT_BUNDLE_LOCK_FILE


def static_prompts_dir(project_root: Path) -> Path:
    return project_root / STATIC_PROMPTS_DIR


def runtime_prompts_dir(project_root: Path) -> Path:
    return project_root / PROMPTS_DIR


def prompt_pin_dir(project_root: Path) -> Path:
    return manifests_dir(project_root) / "prompt-pins"


def prompt_run_pin_path(project_root: Path, run_id: str) -> Path:
    return prompt_pin_dir(project_root) / f"{run_id}.json"


def prompt_instance_dir(
    project_root: Path,
    run_id: str,
    invocation_id: str,
) -> Path:
    return runtime_prompts_dir(project_root) / run_id / invocation_id


def stories_dir(project_root: Path) -> Path:
    return project_root / STORIES_DIR


def story_dir(project_root: Path, story_id: str) -> Path:
    return project_root / STORIES_DIR / story_id

__all__ = [
    "AGENTKIT_DIR",
    "CONFIG_DIR",
    "CONTEXT_FILE",
    "CONTROL_PLANE_CONFIG_FILE",
    "HOOKS_DIR",
    "MANIFESTS_DIR",
    "PHASE_RUNS_DIR",
    "PHASE_STATE_FILE",
    "PIPELINE_CONFIG_FILE",
    "PROMPT_BUNDLE_LOCK_FILE",
    "PROMPT_BUNDLE_STORE_ENV",
    "PROJECT_CONFIG_FILE",
    "PROMPTS_DIR",
    "STATIC_PROMPTS_DIR",
    "STORIES_DIR",
    "TOOLS_DIR",
    "AGENTKIT_TOOLS_DIR",
    "agentkit_dir",
    "config_dir",
    "control_plane_config_path",
    "default_prompt_bundle_store_root",
    "manifests_dir",
    "prompt_instance_dir",
    "prompt_pin_dir",
    "prompt_bundle_lock_path",
    "prompt_bundle_store_dir",
    "prompt_bundle_store_root",
    "prompt_run_pin_path",
    "project_config_path",
    "runtime_prompts_dir",
    "static_prompts_dir",
    "stories_dir",
    "story_dir",
]
