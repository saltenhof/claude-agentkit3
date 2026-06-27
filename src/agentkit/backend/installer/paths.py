"""Standard paths for AgentKit's target project layout."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from agentkit.backend.core_types.plane_artifact_names import INSTALLED_MANIFEST_FILENAME

AGENTKIT_DIR: str = ".agentkit"
CLAUDE_DIR: str = ".claude"
CODEX_DIR: str = ".codex"
CONFIG_DIR: str = f"{AGENTKIT_DIR}/config"
MANIFESTS_DIR: str = f"{AGENTKIT_DIR}/manifests"
PROMPTS_DIR: str = f"{AGENTKIT_DIR}/prompts"
STATIC_PROMPTS_DIR: str = "prompts"
TOOLS_DIR: str = "tools"
AGENTKIT_TOOLS_DIR: str = f"{TOOLS_DIR}/agentkit"
HOOKS_DIR: str = f"{AGENTKIT_DIR}/hooks"
STORIES_DIR: str = "stories"
CONCEPTS_DIR: str = "concepts"
CODEBASE_DIR: str = "codebase"
PROJECT_TEMP_DIR: str = "temp"
INPUT_DIR: str = "input"
MEETINGS_DIR: str = f"{INPUT_DIR}/_meetings"
GUARDRAILS_DIR: str = "guardrails"
TEMP_DIR: str = "_temp"
QA_DIR: str = f"{TEMP_DIR}/qa"
PROJECT_CONFIG_FILE: str = "project.yaml"
CONTROL_PLANE_CONFIG_FILE: str = "control-plane.json"
#: Project-root install manifest carrying the spawn skill-proof token, the
#: authorized prompt paths and the template-manifest hash (FK-31 §31.7.4). It is
#: the AUTHORITATIVE artifact the AG3-086 prompt-integrity guard reads at
#: ``project_root / ".installed-manifest.json"``. Re-exported from the BC-neutral
#: ``core_types`` SINGLE SOURCE OF TRUTH (no second literal; never a second path).
INSTALLED_MANIFEST_FILE: str = INSTALLED_MANIFEST_FILENAME
CLAUDE_SETTINGS_FILE: str = "settings.json"
CODEX_CONFIG_FILE: str = "config.toml"
PROMPT_BUNDLE_LOCK_FILE: str = "prompt-bundle.lock.json"
PROMPT_BUNDLE_STORE_ENV: str = "AGENTKIT_PROMPT_BUNDLE_STORE_ROOT"
#: Env override for the SEPARATE materialized-skill-variant store (AG3-111,
#: FK-43 §43.4.1.1). This store holds substituted SKILL.md harness variants for
#: placeholder-bearing skills. It lives in the AK3 install/state area, NOT under
#: the ``SkillBundleStore`` root and is EXPLICITLY excluded from bundle discovery
#: (FIX Q1) — generated, project-specific variants must never pollute the
#: canonical bundle namespace nor write into the packaged ``resources/`` tree.
MATERIALIZED_SKILL_VARIANT_STORE_ENV: str = "AGENTKIT_MATERIALIZED_SKILL_VARIANT_STORE_ROOT"
PIPELINE_CONFIG_FILE: str = "story-pipeline.yaml"
PHASE_RUNS_DIR: str = "phase-runs"
CONTEXT_FILE: str = "context.json"
PHASE_STATE_FILE: str = "phase-state.json"


def agentkit_dir(project_root: Path) -> Path:
    return project_root / AGENTKIT_DIR


def claude_settings_path(project_root: Path) -> Path:
    return project_root / CLAUDE_DIR / CLAUDE_SETTINGS_FILE


def codex_config_path(project_root: Path) -> Path:
    return project_root / CODEX_DIR / CODEX_CONFIG_FILE


def config_dir(project_root: Path) -> Path:
    return project_root / CONFIG_DIR


def manifests_dir(project_root: Path) -> Path:
    return project_root / MANIFESTS_DIR


def project_config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / PROJECT_CONFIG_FILE


def control_plane_config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / CONTROL_PLANE_CONFIG_FILE


def installed_manifest_path(project_root: Path) -> Path:
    """Return the canonical install-manifest path (FK-31 §31.7.4).

    The file lives at the project ROOT (``.installed-manifest.json``), NOT under
    ``.agentkit/config/`` — this matches the exact path the AG3-086 prompt-integrity
    guard reads (``governance/runner.py`` ``_installed_skill_proof``) so producer and
    consumer agree on one location.
    """
    return project_root / INSTALLED_MANIFEST_FILE


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


def default_materialized_skill_variant_store_root() -> Path:
    """Return the default root for the materialized-skill-variant store (AG3-111).

    Resolution order mirrors the prompt-bundle-store pattern:

    1. ``AGENTKIT_MATERIALIZED_SKILL_VARIANT_STORE_ROOT`` env override (operator/test).
    2. The AK3 install/state area (``%PROGRAMDATA%\\AgentKit\\...`` on Windows,
       ``/var/lib/agentkit/...`` on POSIX).

    This store is SEPARATE from the ``SkillBundleStore`` root (which defaults to the
    packaged shipped bundles and is discovery-scanned) and is never scanned for
    bundles (FK-43 §43.4.1.1, FIX Q1).
    """
    override = os.environ.get(MATERIALIZED_SKILL_VARIANT_STORE_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "AgentKit" / "materialized-skill-variants"
    return Path("/var/lib/agentkit/materialized-skill-variants")


def materialized_skill_variant_store_root(explicit_root: Path | None = None) -> Path:
    """Return the materialized-skill-variant store root (explicit or default)."""
    if explicit_root is not None:
        return explicit_root
    return default_materialized_skill_variant_store_root()


def materialized_skill_variant_input_digest(
    *,
    project_key: str,
    skill_proof_token: str,
    gh_owner: str,
    gh_repo: str,
    project_prefix: str,
    bundle_id: str,
    bundle_version: str,
) -> str:
    """Return the input-digest that keys a materialized variant directory (AG3-111).

    FIX Q1: the variant directory is keyed by a SHA-256 over the FULL
    materialization-relevant input — ``project_key`` + the resolved
    ``agent_spawn_skill_proof`` token + the four FK-03 config values
    (``gh_owner``/``gh_repo``/``project_prefix``/``project_key``) +
    ``bundle_id@bundle_version``. Any changed input yields a NEW, different digest
    directory (immutable variants, no in-place mutation); an unchanged input yields
    a stable digest -> byte-identical re-materialization (idempotency, FK-51).

    The components are joined with a ``\\x00`` separator so no value can spoof a
    boundary (e.g. ``("ab", "c")`` differs from ``("a", "bc")``).

    Returns:
        The hex SHA-256 digest string.
    """
    components = (
        project_key,
        skill_proof_token,
        gh_owner,
        gh_repo,
        project_prefix,
        f"{bundle_id}@{bundle_version}",
    )
    canonical = "\x00".join(components).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def materialized_skill_variant_dir(
    project_key: str,
    bundle_id: str,
    bundle_version: str,
    input_digest: str,
    skill: str,
    *,
    store_root: Path | None = None,
) -> Path:
    """Return the digest-keyed variant directory for one materialized skill (AG3-111).

    Layout (FIX Q1):
    ``{store}/{project_key}/{bundle_id}@{bundle_version}/{input_digest}/{skill}/``.
    """
    return (
        materialized_skill_variant_store_root(store_root)
        / project_key
        / f"{bundle_id}@{bundle_version}"
        / input_digest
        / skill
    )


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


def temp_dir(project_root: Path) -> Path:
    return project_root / TEMP_DIR


def qa_dir(project_root: Path) -> Path:
    return project_root / QA_DIR


def qa_story_dir(project_root: Path, story_id: str) -> Path:
    return qa_dir(project_root) / story_id


def project_root_for_story_dir(story_dir: Path) -> Path | None:
    if story_dir.parent.name != STORIES_DIR:
        return None
    return story_dir.parent.parent


def resolve_qa_story_dir(
    story_dir: Path,
    *,
    story_id: str,
    project_root: Path | None = None,
) -> Path:
    resolved_root = project_root or project_root_for_story_dir(story_dir)
    if resolved_root is None:
        return story_dir
    return qa_story_dir(resolved_root, story_id)

__all__ = [
    "AGENTKIT_DIR",
    "CONFIG_DIR",
    "CONTEXT_FILE",
    "CLAUDE_DIR",
    "CLAUDE_SETTINGS_FILE",
    "CODEX_CONFIG_FILE",
    "CODEX_DIR",
    "CODEBASE_DIR",
    "CONCEPTS_DIR",
    "CONTROL_PLANE_CONFIG_FILE",
    "GUARDRAILS_DIR",
    "HOOKS_DIR",
    "INPUT_DIR",
    "INSTALLED_MANIFEST_FILE",
    "MANIFESTS_DIR",
    "MEETINGS_DIR",
    "PHASE_RUNS_DIR",
    "PHASE_STATE_FILE",
    "PIPELINE_CONFIG_FILE",
    "PROJECT_TEMP_DIR",
    "MATERIALIZED_SKILL_VARIANT_STORE_ENV",
    "PROMPT_BUNDLE_LOCK_FILE",
    "PROMPT_BUNDLE_STORE_ENV",
    "PROJECT_CONFIG_FILE",
    "PROMPTS_DIR",
    "QA_DIR",
    "STATIC_PROMPTS_DIR",
    "STORIES_DIR",
    "TEMP_DIR",
    "TOOLS_DIR",
    "AGENTKIT_TOOLS_DIR",
    "agentkit_dir",
    "claude_settings_path",
    "codex_config_path",
    "config_dir",
    "control_plane_config_path",
    "default_materialized_skill_variant_store_root",
    "default_prompt_bundle_store_root",
    "installed_manifest_path",
    "materialized_skill_variant_dir",
    "materialized_skill_variant_input_digest",
    "materialized_skill_variant_store_root",
    "manifests_dir",
    "prompt_instance_dir",
    "prompt_pin_dir",
    "prompt_bundle_lock_path",
    "prompt_bundle_store_dir",
    "prompt_bundle_store_root",
    "prompt_run_pin_path",
    "project_root_for_story_dir",
    "project_config_path",
    "qa_dir",
    "qa_story_dir",
    "resolve_qa_story_dir",
    "runtime_prompts_dir",
    "static_prompts_dir",
    "stories_dir",
    "story_dir",
    "temp_dir",
]
