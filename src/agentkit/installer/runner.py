"""Minimal AgentKit installer for target projects."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.exceptions import InstallationError, ProjectError
from agentkit.installer.codex_settings import write_codex_settings
from agentkit.installer.file_ops import (
    atomic_write_text,
    atomic_write_yaml,
    copy_file,
    create_or_replace_hardlink,
)
from agentkit.installer.paths import (
    AGENTKIT_DIR,
    AGENTKIT_TOOLS_DIR,
    CLAUDE_DIR,
    CODEX_DIR,
    STATIC_PROMPTS_DIR,
    STORIES_DIR,
    claude_settings_path,
    codex_config_path,
    config_dir,
    control_plane_config_path,
    manifests_dir,
    project_config_path,
    prompt_bundle_lock_path,
    prompt_bundle_store_dir,
    runtime_prompts_dir,
    static_prompts_dir,
    stories_dir,
)

if TYPE_CHECKING:
    # AG3-048 Codex-r5 FINDING 3 (BC boundary): the installer is a DIFFERENT BC
    # (BC 12) and must consume the agent-skills BC (BC 11) only through its
    # PUBLIC surface ``agentkit.skills`` — never the internal
    # ``agentkit.skills.bundle_store`` submodule (exposure=internal). The public
    # package re-exports ``SkillBundleStore``/``SkillProfile``/``Skills``.
    from agentkit.skills import SkillBundleStore, SkillProfile, Skills

PROMPT_MANIFEST_FILENAME = "manifest.json"

# FK-43 §43.3.1 mandatory skills the installer MUST bind per activated harness.
# Logical skill names (the installer resolves the profile variant via the
# bundle store, FK-43 §43.4.1). bc-cut-decisions.md §BC 12: installer-Andockung.
MANDATORY_SKILLS: tuple[str, ...] = (
    "create-userstory",
    "execute-userstory",
    "lookup-userstory",
    "llm-discussion",
)

# Default mapping logical mandatory skill name -> systemwide bundle_id.
# FK-43 §43.3.1 ships these as ``<name>-core`` bundle variants (CP6/CP7 profile
# resolution selects the variant); the installer resolves them from the
# systemwide ``SkillBundleStore``. A normal ``agentkit install`` MUST bind all
# four — when the systemwide store has not been provisioned with these bundles
# the installer FAILS CLOSED (``InstallationError(cause=BundleNotFound)``),
# it never silently skips (AG3-048 AC#5/AC#7, FK-50 §50.5).
DEFAULT_MANDATORY_SKILL_BUNDLE_IDS: dict[str, str] = {
    name: f"{name}-core" for name in MANDATORY_SKILLS
}
MISSING_TEMPLATES_MESSAGE = "Prompt bundle manifest is missing templates"
MALFORMED_TEMPLATE_ENTRY_MESSAGE = "Prompt bundle manifest template entry is malformed"
MISSING_TEMPLATE_RELPATH_MESSAGE = (
    "Prompt bundle manifest template entry is missing relpath"
)


def _resources_target_project_dir() -> Path:
    package_dir = Path(__file__).resolve().parent.parent
    resources_dir = package_dir / "resources" / "target_project"
    if not resources_dir.is_dir():
        raise ProjectError(
            f"Resources directory not found: {resources_dir}",
            detail={"resources_dir": str(resources_dir)},
        )
    return resources_dir


def _resources_internal_prompt_dir() -> Path:
    package_dir = Path(__file__).resolve().parent.parent
    resources_dir = package_dir / "resources" / "internal" / "prompts"
    if not resources_dir.is_dir():
        raise ProjectError(
            f"Internal prompt resources directory not found: {resources_dir}",
            detail={"resources_dir": str(resources_dir)},
        )
    return resources_dir


@dataclass
class InstallConfig:
    project_key: str
    project_name: str
    project_root: Path
    repositories: list[dict[str, str]] | None = None
    github_owner: str | None = None
    github_repo: str | None = None
    prompt_bundle_root: Path | None = None
    # AG3-048 (FK-43 §43.4.1, BC 12): the installer binds the mandatory skills
    # via the agent-skills top-surface. ``skills`` is injected (DI); the
    # composition-root builds the default. ``skill_profile`` selects the bundle
    # variant per project (FK-43 §43.3 Profilregel; CP6/CP7 profile resolution).
    # ``skill_bundle_ids`` maps each mandatory logical skill name to the
    # systemwide bundle_id to resolve from the SkillBundleStore.
    #
    # ``skill_bundle_ids = None`` means "use ``DEFAULT_MANDATORY_SKILL_BUNDLE_IDS``"
    # — it does NOT mean "skip binding". A normal install ALWAYS binds the four
    # mandatory skills; when the bundles are unresolvable it fails closed
    # (AG3-048 AC#5/AC#7). To rebind with non-default bundle ids, pass an
    # explicit mapping.
    skills: Skills | None = None
    skill_bundle_store: SkillBundleStore | None = None
    skill_profile: SkillProfile | None = None
    skill_bundle_ids: dict[str, str] | None = None


@dataclass(frozen=True)
class InstallResult:
    success: bool
    project_root: Path
    created_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UninstallResult:
    success: bool
    project_root: Path
    removed_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


def _build_project_yaml(config: InstallConfig) -> dict[str, object]:
    if config.repositories:
        repos: list[dict[str, str]] = []
        for repo in config.repositories:
            entry: dict[str, str] = {
                "name": repo["name"],
                "path": repo["path"],
            }
            if "language" in repo:
                entry["language"] = repo["language"]
            if "test_command" in repo:
                entry["test_command"] = repo["test_command"]
            if "build_command" in repo:
                entry["build_command"] = repo["build_command"]
            repos.append(entry)
    else:
        repos = [{"name": "app", "path": "."}]

    data: dict[str, object] = {
        "project_key": config.project_key,
        "project_name": config.project_name,
        "repositories": repos,
        "story_types": list(DEFAULT_STORY_TYPES),
        "pipeline": {
            "max_feedback_rounds": DEFAULT_MAX_FEEDBACK_ROUNDS,
            "max_remediation_rounds": DEFAULT_MAX_REMEDIATION_ROUNDS,
            "exploration_mode": True,
            "verify_layers": list(DEFAULT_VERIFY_LAYERS),
        },
    }

    if config.github_owner is not None:
        data["github_owner"] = config.github_owner
    if config.github_repo is not None:
        data["github_repo"] = config.github_repo

    return data


def _resolve_prompt_source_dir(config: InstallConfig) -> Path:
    prompt_source_dir = (
        config.prompt_bundle_root
        if config.prompt_bundle_root is not None
        else _resources_internal_prompt_dir()
    )
    if not prompt_source_dir.is_dir():
        raise ProjectError(
            f"Prompt bundle root does not exist: {prompt_source_dir}",
            detail={"prompt_bundle_root": str(prompt_source_dir)},
        )
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ProjectError(
            "Prompt bundle root is missing "
            f"{PROMPT_MANIFEST_FILENAME}: {prompt_source_dir}",
            detail={"prompt_bundle_root": str(prompt_source_dir)},
        )
    return prompt_source_dir


def _load_prompt_bundle_manifest(
    prompt_source_dir: Path,
) -> tuple[dict[str, object], str]:
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    bundle_id = manifest.get("bundle_id")
    bundle_version = manifest.get("bundle_version")
    templates = manifest.get("templates")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ProjectError(
            "Prompt bundle manifest is missing bundle_id",
            detail={"path": str(manifest_path)},
        )
    if not isinstance(bundle_version, str) or not bundle_version:
        raise ProjectError(
            "Prompt bundle manifest is missing bundle_version",
            detail={"path": str(manifest_path)},
        )
    if not isinstance(templates, dict):
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(manifest_path)},
        )
    return manifest, manifest_text


def _ensure_prompt_bundle_store_entry(
    prompt_source_dir: Path,
) -> tuple[Path, dict[str, object], str]:
    manifest, manifest_text = _load_prompt_bundle_manifest(prompt_source_dir)
    bundle_id = str(manifest["bundle_id"])
    bundle_version = str(manifest["bundle_version"])
    canonical_root = prompt_bundle_store_dir(
        bundle_id,
        bundle_version,
    )
    canonical_manifest_path = canonical_root / PROMPT_MANIFEST_FILENAME
    source_digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()

    if canonical_manifest_path.is_file():
        existing_text = canonical_manifest_path.read_text(encoding="utf-8")
        existing_digest = hashlib.sha256(existing_text.encode("utf-8")).hexdigest()
        if existing_digest != source_digest:
            raise ProjectError(
                "Canonical prompt bundle store collision",
                detail={
                    "bundle_id": bundle_id,
                    "bundle_version": bundle_version,
                    "canonical_root": str(canonical_root),
                    "expected_manifest_sha256": source_digest,
                    "actual_manifest_sha256": existing_digest,
                },
            )
        return canonical_root, manifest, manifest_text

    canonical_root.mkdir(parents=True, exist_ok=True)
    templates = manifest["templates"]
    if not isinstance(templates, dict):  # pragma: no cover
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
        )
    for entry in templates.values():
        if not isinstance(entry, dict):  # pragma: no cover
            raise ProjectError(
                MALFORMED_TEMPLATE_ENTRY_MESSAGE,
                detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):  # pragma: no cover
            raise ProjectError(
                MISSING_TEMPLATE_RELPATH_MESSAGE,
                detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
            )
        source = prompt_source_dir / Path(relpath).name
        copy_file(source, canonical_root / Path(relpath))
    copy_file(prompt_source_dir / PROMPT_MANIFEST_FILENAME, canonical_manifest_path)
    return canonical_root, manifest, manifest_text


def _deploy_directory_structure(
    resources_dir: Path,
    target_root: Path,
) -> list[str]:
    created: list[str] = []

    for item in sorted(resources_dir.rglob("*")):
        rel = item.relative_to(resources_dir)
        if rel.parts[0] == "templates":
            continue

        target = target_root / rel
        if item.is_dir() and not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(rel))

    return created


def _deploy_static_resource_files(
    resources_dir: Path,
    target_root: Path,
) -> list[str]:
    created: list[str] = []

    for item in sorted(resources_dir.rglob("*")):
        rel = item.relative_to(resources_dir)
        if rel.parts[0] == "templates" or item.is_dir():
            continue

        target = target_root / rel
        if _copy_file_if_changed(item, target):
            created.append(str(rel))

    return created


def _deploy_prompt_bindings(target_root: Path, prompt_source_dir: Path) -> list[str]:
    created: list[str] = []
    prompt_target_dir = static_prompts_dir(target_root)
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(manifest_path)},
        )

    manifest_target = prompt_target_dir / PROMPT_MANIFEST_FILENAME
    if not _file_contents_match(manifest_path, manifest_target):
        create_or_replace_hardlink(manifest_path, manifest_target)
        created.append(str(manifest_target.relative_to(target_root)))

    for entry in templates.values():
        if not isinstance(entry, dict):
            raise ProjectError(
                MALFORMED_TEMPLATE_ENTRY_MESSAGE,
                detail={"path": str(manifest_path)},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):
            raise ProjectError(
                MISSING_TEMPLATE_RELPATH_MESSAGE,
                detail={"path": str(manifest_path)},
            )
        source = prompt_source_dir / Path(relpath)
        target = prompt_target_dir / Path(relpath).name
        if not _file_contents_match(source, target):
            create_or_replace_hardlink(source, target)
            created.append(str(target.relative_to(target_root)))

    return created


def _write_prompt_bundle_lock(
    target_root: Path,
    *,
    manifest: dict[str, object],
    manifest_text: str,
) -> str | None:
    """Update the project prompt-bundle binding (FK-50 §50.5).

    Delegates the actual binding update to the prompt-runtime top-surface
    ``PromptRuntime.update_binding`` (Owner-BC principle). Idempotence for
    ``created_files`` reporting is preserved by composing the would-be lock
    content via the shared ``build_prompt_bundle_lock_content`` and only
    delegating when it differs from the on-disk lock. The fail-closed path
    is not weakened: ``update_binding`` re-resolves the manifest from the
    installer-managed central store and raises on any inconsistency.

    Imported lazily to avoid an import cycle (``prompt_runtime`` imports
    ``installer.paths``; the installer package eagerly imports this runner).
    """
    from agentkit.prompt_runtime.runtime import (
        PromptRuntime,
        build_prompt_bundle_lock_content,
    )

    bundle_id = str(manifest["bundle_id"])
    bundle_version = str(manifest["bundle_version"])
    desired_content = build_prompt_bundle_lock_content(
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        manifest_file=PROMPT_MANIFEST_FILENAME,
        manifest_text=manifest_text,
    )
    lock_path = prompt_bundle_lock_path(target_root)
    if lock_path.is_file() and (
        lock_path.read_text(encoding="utf-8") == desired_content
    ):
        return None
    PromptRuntime(target_root).update_binding(bundle_id, bundle_version)
    return str(lock_path.relative_to(target_root))


def _write_control_plane_config(target_root: Path) -> str | None:
    config_path = control_plane_config_path(target_root)
    content = (
        json.dumps(
            {
                "base_url": "https://127.0.0.1:9080",
                "ca_file": None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if not _write_text_if_changed(
        config_path,
        content,
    ):
        return None
    return str(config_path.relative_to(target_root))


def _file_contents_match(source: Path, target: Path) -> bool:
    if not target.is_file():
        return False
    return source.read_bytes() == target.read_bytes()


def _copy_file_if_changed(source: Path, target: Path) -> bool:
    if _file_contents_match(source, target):
        return False
    copy_file(source, target)
    return True


def _write_text_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    atomic_write_text(path, content)
    return True


def _write_yaml_if_changed(path: Path, data: dict[str, object]) -> bool:
    if path.is_file():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if existing == data:
            return False
    atomic_write_yaml(path, data)
    return True


def _resolve_skill_profile(config: InstallConfig) -> SkillProfile:
    """Resolve the skill bundle profile for this project (FK-43 §43.3 Profilregel).

    CP6/CP7 profile resolution happens here, BEFORE any ``bind_skill`` call.
    Defaults to ``CORE`` (non-ARE) when the config does not pin a profile.
    """
    from agentkit.skills import SkillProfile as _SkillProfile

    return config.skill_profile if config.skill_profile is not None else _SkillProfile.CORE


def _resolve_skills_and_store(
    config: InstallConfig,
    root: Path,
) -> tuple[Skills, SkillBundleStore]:
    """Return the ``Skills`` top-surface and its ``SkillBundleStore`` (DI).

    Both injected -> use them. Neither injected -> build a wired default whose
    ``Skills`` and ``SkillBundleStore`` share the SAME store object. A partial
    injection is rejected fail-closed (the two would otherwise reference
    different stores and the bundle resolution would diverge from binding).
    """
    if config.skills is not None and config.skill_bundle_store is not None:
        return config.skills, config.skill_bundle_store
    if config.skills is not None or config.skill_bundle_store is not None:
        raise InstallationError(
            "InstallConfig.skills and InstallConfig.skill_bundle_store must be "
            "injected together (or both omitted); a partial injection would "
            "split the bundle store.",
            detail={"cause": "InvalidConfig"},
        )
    from agentkit.skills import SkillBundleStore as _SkillBundleStore
    from agentkit.skills import Skills as _Skills
    from agentkit.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    bundle_store = _SkillBundleStore()
    skills = _Skills(
        bundle_store=bundle_store,
        binding_repo=StateBackendSkillBindingRepository(root),
    )
    return skills, bundle_store


def _rollback_bindings(
    skills: Skills,
    root: Path,
    bound_skill_names: list[str],
) -> list[dict[str, object]]:
    """Undo every link and persisted binding created in this transaction.

    FAIL-CLOSED rollback (FK-50 §50.5, AG3-048 AC#7): delegates to the
    agent-skills top-surface ``Skills.unbind_skill`` for every already-bound
    skill so that a part-way binding failure leaves NO partial install.

    HONEST rollback (Codex-r2 ERROR 2, Codex-r7 FINDING): a compensating
    ``unbind_skill`` that itself fails (e.g. a DB outage during the repo
    ``delete`` leaves the persisted binding row while the links are already gone)
    is NOT swallowed silently. Every skill is still attempted (one failure must
    not stop the rest of the rollback), and the failures are collected and
    returned so the caller can surface the leftover/orphaned state instead of
    falsely claiming a clean rollback. When a ``SkillBindingPartialStateError``
    carries a STRUCTURED residual (``residual_links`` list + ``persisted_row_remains``
    flag), those fields are preserved verbatim in the orphan entry rather than
    being flattened into the message string — a machine consumer must be able to
    enumerate the surviving artifacts. The original binding error must not be
    masked, hence individual failures are captured rather than re-raised here.

    Returns:
        One entry per skill whose rollback failed (empty list when every
        compensation succeeded). Each entry carries ``skill_name`` + ``error``
        and, for a partial-state failure, ``residual_links`` (``list[str]``) and
        ``persisted_row_remains`` (``bool``).
    """
    from agentkit.skills.errors import SkillBindingPartialStateError

    orphaned: list[dict[str, object]] = []
    for skill_name in bound_skill_names:
        try:
            skills.unbind_skill(skill_name, root)
        except SkillBindingPartialStateError as exc:  # structured residual preserved
            # Codex-r7-r2: the partial-state orphan schema is STABLE — both
            # ``residual_links`` (list, possibly empty) and ``persisted_row_remains``
            # (bool) are ALWAYS present so a consumer can rely on them without
            # truthiness probing.
            entry: dict[str, object] = {
                "skill_name": skill_name,
                "error": str(exc),
                "residual_links": [
                    str(r) for r in (exc.detail.get("residual_links") or [])
                ],
                "persisted_row_remains": bool(exc.detail.get("persisted_row_remains")),
            }
            orphaned.append(entry)
        except Exception as exc:  # noqa: BLE001 — honest capture, never silent
            orphaned.append({"skill_name": skill_name, "error": str(exc)})
    return orphaned


def _resolve_mandatory_skill_bundles(
    config: InstallConfig, root: Path
) -> tuple[Skills, list[tuple[str, Path]]]:
    """Resolve (PREFLIGHT) all FK-43 §43.3.1 mandatory skill bundles.

    This is a pure resolution step that writes NOTHING to the project. It is
    invoked at the very start of ``install_agentkit``, BEFORE any scaffold/
    resource/prompt deploy, so that the common install failure — a missing
    mandatory bundle — fails fast and leaves the target project entirely
    untouched (Codex-r7 FINDING: no half-scaffolded project on ``BundleNotFound``).

    BC 12 installer-Andockung: profile resolution (CP6/CP7) precedes binding;
    ``config.skill_bundle_ids is None`` resolves to
    ``DEFAULT_MANDATORY_SKILL_BUNDLE_IDS`` (FK-43 §43.3.1) — it does NOT disable
    binding (AG3-048 AC#5).

    Args:
        config: Install configuration (carries the optional injected ``Skills``
            and the mandatory-skill -> bundle_id mapping).
        root: Project root.

    Returns:
        The resolved ``Skills`` top-surface and a list of
        ``(skill_name, bundle_root)`` pairs ready to bind.

    Raises:
        InstallationError: When a mandatory bundle is not in the system store or
            no bundle id is configured for a mandatory skill
            (``cause=BundleNotFound``).
    """
    from agentkit.skills.errors import SkillBundleNotFoundError

    skills, bundle_store = _resolve_skills_and_store(config, root)
    _resolve_skill_profile(config)  # CP6/CP7 profile resolution (fail early on bad profile)
    bundle_ids = (
        config.skill_bundle_ids
        if config.skill_bundle_ids is not None
        else DEFAULT_MANDATORY_SKILL_BUNDLE_IDS
    )

    resolved: list[tuple[str, Path]] = []
    for skill_name in MANDATORY_SKILLS:
        bundle_id = bundle_ids.get(skill_name)
        if not bundle_id:
            raise InstallationError(
                f"No bundle_id configured for mandatory skill '{skill_name}' "
                "(FK-43 §43.3.1); cannot bind.",
                detail={"cause": "BundleNotFound", "skill_name": skill_name},
            )
        try:
            bundle = bundle_store.get_bundle(bundle_id)
        except SkillBundleNotFoundError as exc:
            raise InstallationError(
                f"Mandatory skill bundle '{bundle_id}' for skill "
                f"'{skill_name}' not found in the systemwide store (FK-43 "
                "§43.3.1); installation aborted (no partial install).",
                detail={
                    "cause": "BundleNotFound",
                    "skill_name": skill_name,
                    "bundle_id": bundle_id,
                    **exc.detail,
                },
            ) from exc
        resolved.append((skill_name, bundle.bundle_root))
    return skills, resolved


def _bind_resolved_skills(
    skills: Skills, resolved: list[tuple[str, Path]], root: Path
) -> None:
    """Bind the PRE-RESOLVED mandatory skills transactionally (Phase 2).

    ``Skills.bind_skill`` is multi-harness (Claude Code + Codex, FK-43 §43.4.1
    AK4) and creates the harness link directories itself — the installer no
    longer ``mkdir``s ``.claude/skills`` directly.

    FAIL-CLOSED, transactional (no partial install — FK-50 §50.5, AC#7):
    ``bind_skill`` is SELF-ATOMIC (on any failure it leaves NO partial state for
    THAT skill — no link, no persisted row; skills/top.py). If a LATER skill's
    ``bind_skill`` raises after an earlier skill already bound, every link AND
    persisted binding of the truly-bound prior skills is rolled back before
    re-raising as ``InstallationError(cause=BindFailed)``. The failing skill
    produced no side effect, so it is never reported as a (false) orphan.

    Args:
        skills: The agent-skills top-surface (from
            :func:`_resolve_mandatory_skill_bundles`).
        resolved: ``(skill_name, bundle_root)`` pairs to bind.
        root: Project root.

    Raises:
        InstallationError: When a bind fails (``cause=BindFailed``; all prior
            state rolled back) or a rollback could not fully compensate
            (``cause=RollbackIncomplete``).
    """
    from agentkit.skills.errors import SkillBindingPartialStateError

    # Bind transactionally (multi-harness links, FK-43 §43.4.1).
    # ``bind_skill`` is SELF-ATOMIC (skills/top.py): on any failure it leaves NO
    # partial state — no link, no persisted binding row. Therefore the
    # failing skill is NEVER appended to ``bound_so_far``; only skills that
    # returned successfully (and so REALLY have persisted state) are in the
    # rollback set. This makes the orphan report ACCURATE: a skill that failed
    # before any side effect can never be reported as a false orphan
    # (AG3-048 Codex-r3 ERROR 2).
    bound_so_far: list[str] = []
    for skill_name, bundle_root in resolved:
        try:
            skills.bind_skill(skill_name, bundle_root, root)
        except SkillBindingPartialStateError as exc:
            # AG3-048 Codex-r4 FINDING 1: the FAILING skill's own self-atomic
            # cleanup could NOT fully undo its partial state (residual link
            # and/or persisted row). This is itself an orphan — it must be
            # reported as RollbackIncomplete, NEVER as a clean BindFailed. Prior
            # truly-bound skills are still compensated and merged into the report.
            orphaned = _rollback_bindings(skills, root, bound_so_far)
            # Codex-r7-r2: stable partial-state schema — both keys ALWAYS present
            # (list possibly empty, bool), consistent with the prior skills'
            # entries from ``_rollback_bindings``, so a consumer can enumerate the
            # surviving artifacts without truthiness probing.
            failing_residual: dict[str, object] = {
                "skill_name": skill_name,
                "error": str(exc),
                "residual_links": [
                    str(r) for r in (exc.detail.get("residual_links") or [])
                ],
                "persisted_row_remains": bool(exc.detail.get("persisted_row_remains")),
            }
            orphaned = [*orphaned, failing_residual]
            orphaned_names = sorted({str(o["skill_name"]) for o in orphaned})
            raise InstallationError(
                f"Binding mandatory skill '{skill_name}' failed AND its own "
                "self-atomic cleanup left residual partial state; "
                f"orphaned bindings remain for {orphaned_names} "
                "(partial install — retry required, FK-50 §50.5).",
                detail={
                    "cause": "RollbackIncomplete",
                    "skill_name": skill_name,
                    "bundle_root": str(bundle_root),
                    "error": str(exc),
                    "orphaned_bindings": orphaned,
                },
            ) from exc
        except Exception as exc:
            # The failing skill produced no side effect (self-atomic bind), so
            # it is NOT in ``bound_so_far``; only truly-bound prior skills are
            # compensated. Any compensation failure here is a GENUINE orphan.
            orphaned = _rollback_bindings(skills, root, bound_so_far)
            if orphaned:
                # HONEST partial-state report (Codex-r2 ERROR 2): a compensating
                # unbind failed (e.g. DB outage during the repo delete), so the
                # rollback is NOT clean. Do not claim "rolled back all" — name
                # the orphaned bindings so the operator can retry/clean them.
                orphaned_names = sorted({str(o["skill_name"]) for o in orphaned})
                raise InstallationError(
                    f"Binding mandatory skill '{skill_name}' failed AND the "
                    "transactional rollback could not fully compensate; "
                    f"orphaned bindings remain for {orphaned_names} "
                    "(partial install — retry required, FK-50 §50.5).",
                    detail={
                        "cause": "RollbackIncomplete",
                        "skill_name": skill_name,
                        "bundle_root": str(bundle_root),
                        "error": str(exc),
                        "orphaned_bindings": orphaned,
                    },
                ) from exc
            raise InstallationError(
                f"Binding mandatory skill '{skill_name}' failed; rolled back "
                "all skill bindings from this install (no partial install, "
                "FK-50 §50.5).",
                detail={
                    "cause": "BindFailed",
                    "skill_name": skill_name,
                    "bundle_root": str(bundle_root),
                    "error": str(exc),
                },
            ) from exc
        # Record ONLY after a successful, fully-committed bind so the rollback
        # set contains exclusively skills with real persisted state.
        bound_so_far.append(skill_name)


def _bind_mandatory_skills(config: InstallConfig, root: Path) -> None:
    """Resolve + bind all FK-43 §43.3.1 mandatory skills (both phases).

    Convenience composition of :func:`_resolve_mandatory_skill_bundles`
    (preflight resolution, no writes) and :func:`_bind_resolved_skills`
    (transactional bind). ``install_agentkit`` deliberately calls the two phases
    SEPARATELY so resolution runs BEFORE any project write (Codex-r7 FINDING —
    no half-scaffold on a missing bundle); callers that do not need that ordering
    split (e.g. focused tests of the bind/rollback orchestration) use this
    wrapper.
    """
    skills, resolved = _resolve_mandatory_skill_bundles(config, root)
    _bind_resolved_skills(skills, resolved, root)


#: Harness link bind points that must be git-ignored in a target project so a
#: Windows junction / POSIX symlink is never committed as the central bundle
#: content (FK-43 §43.4.1.1, invariant
#: project_local_repo_never_contains_canonical_skill_source).
_LINK_BINDPOINT_GITIGNORE_ENTRIES: tuple[str, ...] = (".claude/skills/", ".codex/skills/")


def _ensure_link_bindpoint_gitignore(root: Path) -> str | None:
    """Idempotently git-ignore the harness link bind points in *root*.

    Appends ``.claude/skills/`` and ``.codex/skills/`` to ``{root}/.gitignore``
    (creating the file if absent). Git and backups follow a junction, so a bound
    bind point would otherwise commit the central bundle content into the project
    repo (FK-43 §43.4.1.1). Only the ``skills`` subdir is ignored — sibling
    harness config such as ``.claude/settings.json`` stays tracked.

    Returns:
        The project-relative ``.gitignore`` path when it was created or modified,
        otherwise ``None`` (already complete — idempotent).
    """
    def _norm(entry: str) -> str:
        return entry.strip().rstrip("/")

    gitignore_path = root / ".gitignore"
    existing_lines: list[str] = []
    if gitignore_path.is_file():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    present = {_norm(line) for line in existing_lines}
    missing = [e for e in _LINK_BINDPOINT_GITIGNORE_ENTRIES if _norm(e) not in present]
    if not missing:
        return None

    block: list[str] = []
    if existing_lines and existing_lines[-1].strip() != "":
        block.append("")  # blank separator before the new section
    block.append("# AgentKit skill bind points — links to central bundles (FK-43 §43.4.1.1)")
    block.extend(missing)
    new_text = "\n".join([*existing_lines, *block]).rstrip("\n") + "\n"
    gitignore_path.write_text(new_text, encoding="utf-8")
    return str(gitignore_path.relative_to(root))


def install_agentkit(config: InstallConfig) -> InstallResult:
    root = config.project_root

    if not root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {root}",
            detail={"project_root": str(root)},
        )

    # PREFLIGHT (Codex-r7 FINDING): resolve all mandatory skill bundles BEFORE
    # writing anything to the project. A missing bundle is the common install
    # failure; failing here (no project writes yet) means ``agentkit install``
    # never leaves a half-scaffolded project on ``BundleNotFound``.
    skills, resolved_skill_bundles = _resolve_mandatory_skill_bundles(config, root)

    resources_dir = _resources_target_project_dir()
    prompt_source_dir = _resolve_prompt_source_dir(config)
    canonical_prompt_bundle_root, manifest, manifest_text = (
        _ensure_prompt_bundle_store_entry(prompt_source_dir)
    )
    created = _deploy_directory_structure(resources_dir, root)
    created.extend(_deploy_static_resource_files(resources_dir, root))
    created.extend(_deploy_prompt_bindings(root, canonical_prompt_bundle_root))

    # Runtime working directories that are intentionally empty right after a
    # fresh install. Git cannot track empty directories, so they are absent
    # from the resources/target_project scaffold and the scaffold-mirroring
    # deploy step never creates them. The installer therefore guarantees them
    # explicitly. This set is the mirror image of what ``uninstall_agentkit``
    # removes (keep both in sync):
    #   .agentkit/config    -- also receives files below; created here too
    #   .agentkit/prompts   -- FK-44 prompt-materialization root (prompt_instance_dir)
    #   .agentkit/manifests -- prompt-pin manifests
    #   stories             -- story working tree
    #   .claude/context     -- harness context dir (Claude Code)
    # AG3-048: the ``.claude/skills`` (and ``.codex/skills``) bind points are NO
    # LONGER created here. They are owned by the agent-skills BC: each harness
    # skills directory is created lazily by ``Skills.bind_skill`` when the
    # mandatory skills are bound below (FK-43 §43.4.1; BC 12). The installer no
    # longer ``mkdir``s the skill bind point directly.
    for runtime_dir in (
        config_dir(root),
        runtime_prompts_dir(root),
        manifests_dir(root),
        stories_dir(root),
        root / CLAUDE_DIR / "context",
    ):
        runtime_dir.mkdir(parents=True, exist_ok=True)

    # AG3-048 (FK-43 §43.4.1.1): git-ignore the harness link bind points in the
    # TARGET project BEFORE any link is created (Codex-r7-r2). Git and backups
    # follow a Windows directory junction, so a bound `.claude/skills/` /
    # `.codex/skills/` would otherwise be committed/backed-up as the central
    # bundle content — violating
    # `project_local_repo_never_contains_canonical_skill_source`. Ordering this
    # ahead of binding guarantees a link is NEVER on disk without its ignore rule
    # already in place. Idempotent.
    gitignore_rel = _ensure_link_bindpoint_gitignore(root)
    if gitignore_rel is not None and gitignore_rel not in created:
        created.append(gitignore_rel)

    # AG3-048 (FK-43 §43.3.1, BC 12): bind the PRE-RESOLVED mandatory skills via
    # the agent-skills top-surface. Resolution already happened in the preflight
    # above (before any write), so this step only creates the links + persists
    # the bindings, transactionally (self-atomic per skill, rollback on failure).
    _bind_resolved_skills(skills, resolved_skill_bundles, root)

    prompt_lock = _write_prompt_bundle_lock(
        root,
        manifest=manifest,
        manifest_text=manifest_text,
    )
    if prompt_lock is not None:
        created.append(prompt_lock)
    control_plane_config = _write_control_plane_config(root)
    if control_plane_config is not None:
        created.append(control_plane_config)
    codex_settings = write_codex_settings(root)
    if codex_settings is not None and codex_settings not in created:
        created.append(codex_settings)

    yaml_path = project_config_path(root)
    yaml_data = _build_project_yaml(config)
    if _write_yaml_if_changed(yaml_path, yaml_data):
        created.append(str(yaml_path.relative_to(root)))

    return InstallResult(
        success=True,
        project_root=root,
        created_files=tuple(created),
    )


def _remove_file(path: Path, project_root: Path) -> list[str]:
    if not path.exists():
        return []
    path.unlink()
    return [str(path.relative_to(project_root))]


def _remove_tree(path: Path, project_root: Path) -> list[str]:
    if not path.exists():
        return []
    shutil.rmtree(path)
    return [str(path.relative_to(project_root))]


def _remove_empty_dir(path: Path, project_root: Path) -> list[str]:
    if not path.is_dir() or any(path.iterdir()):
        return []
    path.rmdir()
    return [str(path.relative_to(project_root))]


def _remove_skill_link_bindpoints(project_root: Path) -> list[str]:
    """Detach every harness skill LINK under the bind points (Codex-r7-r2).

    Symmetric to install (FK-43 §43.4.1.1): install creates
    ``.claude/skills/<name>`` and ``.codex/skills/<name>`` as thin links to the
    central bundle, so uninstall must DETACH them — otherwise the junctions /
    symlinks (and their non-empty parent dirs) survive. A junction is detached via
    ``os.rmdir`` (through the agent-skills link layer), NEVER ``shutil.rmtree``,
    which would delete the CENTRAL bundle through the link. Every link under the
    bind point is removed (mandatory AND custom skills).

    Filesystem-only: the central state-backend binding rows are out of
    uninstall's scope — exactly like the project-registration rows that uninstall
    also leaves untouched (uninstall removes project-local artifacts, not central
    state). A re-install rebinds and overwrites those rows.
    """
    from agentkit.skills import is_directory_link, remove_directory_link

    removed: list[str] = []
    for harness_dir in (CLAUDE_DIR, CODEX_DIR):
        skills_dir = project_root / harness_dir / "skills"
        if not skills_dir.is_dir():
            continue
        for entry in sorted(skills_dir.iterdir()):
            if is_directory_link(entry):
                remove_directory_link(entry)
                removed.append(str(entry.relative_to(project_root)))
    return removed


def uninstall_agentkit(project_root: Path) -> UninstallResult:
    """Remove AgentKit-managed install artifacts from a target project."""

    if not project_root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {project_root}",
            detail={"project_root": str(project_root)},
        )

    removed: list[str] = []
    # Detach skill links FIRST (Codex-r7-r2) so the bind-point dirs become empty
    # and removable; a junction is detached without recursing into its target.
    removed.extend(_remove_skill_link_bindpoints(project_root))
    removed.extend(_remove_file(codex_config_path(project_root), project_root))
    removed.extend(_remove_file(claude_settings_path(project_root), project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "context", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    removed.extend(_remove_tree(project_root / AGENTKIT_DIR, project_root))
    removed.extend(_remove_tree(project_root / AGENTKIT_TOOLS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / "tools", project_root))
    removed.extend(_remove_tree(project_root / STATIC_PROMPTS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / STORIES_DIR, project_root))

    return UninstallResult(
        success=True,
        project_root=project_root,
        removed_files=tuple(removed),
    )


__all__ = [
    "MANDATORY_SKILLS",
    "InstallConfig",
    "InstallResult",
    "UninstallResult",
    "install_agentkit",
    "uninstall_agentkit",
]
