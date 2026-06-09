"""Minimal AgentKit installer for target projects."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.config.models import SUPPORTED_CONFIG_VERSION
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
    from agentkit.installer.integration_checkpoints.ci_preflight import (
        CiPreflightResult,
    )
    from agentkit.installer.integration_checkpoints.scanner_harness import ScanRunner
    from agentkit.installer.integration_checkpoints.sonar_preflight import (
        BranchPluginSelfTest,
        SonarPreflightResult,
    )
    from agentkit.installer.registration import CheckpointResult, RuntimeProfile
    from agentkit.installer.repository import ProjectRegistrationRepository
    from agentkit.integrations.jenkins import JenkinsClient
    from agentkit.integrations.sonar import SonarClient
    from agentkit.skills import SkillBundleStore, SkillProfile, Skills

PROMPT_MANIFEST_FILENAME = "manifest.json"

# AG3-039 (FK-50 §50.3 CP 7): the project-config version recorded in the
# ``project_registry`` row. The scaffold project.yaml carries no explicit
# version yet; "1" is the initial recorded version and is bumpable when the
# config schema evolves (FK-51 config migration is a follow-up, story §2.2).
PROJECT_CONFIG_VERSION = "1"

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
    # AG3-052 (FK-50 CP 10d): the SonarQube precondition checkpoint runs
    # applicability-conditional. With ``available: false`` it is SKIPPED and
    # needs no collaborators. With ``available: true`` it is fail-closed and
    # needs a connected ``SonarClient``, the token's effective permissions and
    # the branch-plugin conformance self-test. Only the LIVE SonarQube server +
    # scanner binary is OOS (§2.2): the operator/CI injects ``sonar_client`` and
    # ``sonar_scan_runner`` (the operational ``sonar-scanner`` invocation), and
    # the installer builds the PRODUCTIVE ``SonarClientScannerHarness`` from
    # them (AG3-052 E5). When ``available: true`` and the verification cannot be
    # carried out, CP 10d FAILs closed and ABORTS the install — there is no
    # ``verification_deferred`` escape hatch (a green gate must never be armed
    # against an unverified Sonar, FK-50 §50.6).
    #
    # ``sonar_branch_plugin_self_test`` lets a caller inject a fully-prebuilt
    # self-test (e.g. tests stubbing the HTTP boundary); when it is ``None`` the
    # installer assembles the productive one from ``sonar_client`` +
    # ``sonar_scan_runner``.
    sonar_client: SonarClient | None = None
    sonar_token_permissions: frozenset[str] | None = None
    sonar_branch_plugin_self_test: BranchPluginSelfTest | None = None
    sonar_scan_runner: ScanRunner | None = None
    # AG3-052 Design-Decision (FK-03 §3): the scaffold default for a
    # code-producing project is ``sonarqube.available: true`` — the green gate
    # is a mandatory runtime dependency and an install must DECLARE Sonar
    # present (FK-03 §3 example uses ``available: true`` + endpoint).
    # ``available: false`` is a CONSCIOUS operator opt-out, never an automatic
    # install default. Set ``sonarqube_available=False`` to scaffold the
    # explicit opt-out (e.g. a server-less install or a test fixture with no
    # live Sonar). Consequence (accepted, FAIL-CLOSED): an ``available: true``
    # scaffold with no reachable Sonar makes CP 10d (E5) FAIL closed — the
    # GEWOLLTE prompt to either provision Sonar or set ``available: false``.
    sonarqube_available: bool = True
    # Endpoint used when ``sonarqube_available`` is True (FK-03 §3 example).
    sonarqube_base_url: str = "http://localhost:9901"
    sonarqube_token_env: str = "SONARQUBE_TOKEN"
    # The SonarScanner version AK3 pins and RUNS for the local QA-subflow scan
    # (FK-33 §33.6.3 attestation binding, ERROR-B). Required when
    # ``sonarqube_available`` is True so a produced attestation never carries an
    # empty scanner version (the cross-field rule fails closed otherwise).
    sonarqube_scanner_version: str = "5.0.1"
    # AG3-056 Design-Decision: mirror the Sonar discipline for the CI
    # (Jenkins) pre-merge runner. The scaffold default for a code-producing
    # project is ``ci.available: true`` (+ endpoint + pipeline) — the closure
    # pre-merge barrier (AG3-053) needs a real CI trigger and an install must
    # DECLARE Jenkins present. ``ci.available: false`` is a CONSCIOUS operator
    # opt-out, never an automatic install default. Set ``ci_available=False``
    # to scaffold the explicit opt-out (e.g. a CI-less install or a test
    # fixture with no live Jenkins).
    ci_available: bool = True
    # Endpoint/job used when ``ci_available`` is True.
    ci_base_url: str = "http://localhost:8080"
    ci_token_env: str = "JENKINS_TOKEN"
    ci_pipeline: str = "ak3-pre-merge"
    # AG3-056 (FK-50 CP, FIX-5): the CI (Jenkins) precondition checkpoint runs
    # applicability-conditional, exactly like the Sonar CP 10d check. With
    # ``ci.available: false`` it is SKIPPED and needs no collaborator. With
    # ``ci.available: true`` it is fail-closed and needs a connected
    # ``JenkinsClient`` to verify reachability + token + pipeline existence;
    # when it is ``None`` (and the stanza is available) the checkpoint FAILs
    # closed (``missing_dependency``) and the install ABORTS — a real CI
    # trigger must never be promised against an unverified Jenkins. Only the
    # LIVE Jenkins server is OOS: the operator/CI injects ``ci_client``.
    ci_client: JenkinsClient | None = None
    # AG3-039 (FK-50 §50.3 CP 7): the State-Backend project-registration port.
    # The installer (BC 12) depends only on the
    # ``ProjectRegistrationRepository`` Protocol; the productive
    # ``StateBackendProjectRegistrationRepository`` is wired in by the caller
    # (composition root). When ``None`` the installer builds the default
    # productive adapter scoped to ``project_root``. ``runtime_profile``
    # (``core``/``are``, FK-50 §50.3 CP 6/CP 7) is recorded in the registration
    # row; it defaults to ``core``.
    registration_repo: ProjectRegistrationRepository | None = None
    runtime_profile: RuntimeProfile | None = None


@dataclass(frozen=True)
class InstallResult:
    success: bool
    project_root: Path
    created_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
    # AG3-039 (FK-50 §50.4): per-checkpoint results. Currently only CP 7
    # (State-Backend registration) populates an entry; the full 12-checkpoint
    # engine is OUT of scope (story §2.2) and will populate this typed list when
    # it lands. ``None`` means "no checkpoint results captured" (legacy callers).
    checkpoint_results: tuple[CheckpointResult, ...] | None = None


@dataclass(frozen=True)
class UninstallResult:
    success: bool
    project_root: Path
    removed_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


def _default_sonarqube_stanza(config: InstallConfig) -> dict[str, object]:
    """Return the EXPLICIT scaffold ``sonarqube`` stanza for a code project.

    AG3-052 Design-Decision (FK-03 §3, Konzepttreue): for a code-producing
    project the scaffold default is ``available: true`` (+ ``enabled: true`` +
    endpoint), exactly as the FK-03 §3 example declares it. The green gate is
    a mandatory runtime dependency (FK-10 §10.2.2); a fresh install DECLARES
    Sonar present rather than auto-disabling the gate. ``available: false`` is
    a CONSCIOUS operator opt-out (``config.sonarqube_available = False``),
    never an automatic install default — auto-``false`` would silently
    undercut the gate obligation for fresh code-producing installs (CP 10d
    would be skipped by design).

    Consequence (accepted, FAIL-CLOSED): an ``available: true`` scaffold with
    no reachable Sonar makes CP 10d (E5) FAIL closed — the GEWOLLTE prompt to
    provision Sonar OR consciously set ``available: false``. The stanza is
    ALWAYS explicit (never omitted), so the operator intent is never silent
    (AG3-052 E6).

    Args:
        config: The install configuration; ``sonarqube_available`` selects the
            declared-present default (FK-03 §3) vs the conscious opt-out, and
            ``sonarqube_base_url``/``sonarqube_token_env`` carry the endpoint.

    Returns:
        The ``sonarqube`` stanza mapping for ``project.yaml``.
    """
    stanza: dict[str, object] = {
        "available": config.sonarqube_available,
        "enabled": config.sonarqube_available,
        "min_version": "26.4",
        "plugins": {"community_branch": {"min_version": "1.23.0"}},
        "quality_gate": {
            # Target-project-relative path: the installer deploys the SSOT
            # profile from ``src/agentkit/resources/target_project/sonar/`` to
            # ``<project>/sonar/`` (resource-mirroring deploy), so the project
            # config points at the DEPLOYED location (FK-03's
            # ``resources/target_project/...`` is the SSOT source path).
            "default_profile": "sonar/ak3-default-gate.json",
            "overrides_allowed": True,
        },
    }
    if config.sonarqube_available:
        # FK-03 §3: ``available and enabled`` require base_url + token_env +
        # scanner_version (cross-field rule, no silent localhost-without-auth
        # default; scanner_version is an attestation binding, FK-33 §33.6.3).
        stanza["base_url"] = config.sonarqube_base_url
        stanza["token_env"] = config.sonarqube_token_env
        stanza["scanner_version"] = config.sonarqube_scanner_version
    return stanza


def _default_ci_stanza(config: InstallConfig) -> dict[str, object]:
    """Return the EXPLICIT scaffold ``ci`` (Jenkins) stanza for a code project.

    AG3-056 Design-Decision: mirror the Sonar discipline. For a code-producing
    project the scaffold default is ``available: true`` (+ ``enabled: true`` +
    endpoint + pipeline). The closure pre-merge barrier (AG3-053) needs a real
    CI trigger to build/test + scan the integrated candidate; a fresh install
    DECLARES Jenkins present rather than auto-disabling the runner.
    ``available: false`` is a CONSCIOUS operator opt-out
    (``config.ci_available = False``), never an automatic install default.

    Args:
        config: The install configuration; ``ci_available`` selects the
            declared-present default vs the conscious opt-out, and
            ``ci_base_url``/``ci_token_env``/``ci_pipeline`` carry the endpoint.

    Returns:
        The ``ci`` stanza mapping for ``project.yaml``.
    """
    stanza: dict[str, object] = {
        "available": config.ci_available,
        "enabled": config.ci_available,
    }
    if config.ci_available:
        # ``available and enabled`` require base_url + token_env + pipeline
        # (cross-field rule, no silent localhost/no-pipeline default).
        stanza["base_url"] = config.ci_base_url
        stanza["token_env"] = config.ci_token_env
        stanza["pipeline"] = config.ci_pipeline
    return stanza


def _build_repo_entries(config: InstallConfig) -> list[dict[str, str]]:
    """Build the ``repositories`` list for ``project.yaml``.

    Mirrors the declared repositories verbatim (carrying optional
    ``language``/``test_command``/``build_command`` fields when present) and
    falls back to the single default ``app`` repo when none are declared.
    Extracted from ``_build_project_yaml`` to keep its cognitive complexity
    within the S3776 budget (no behaviour change).

    Args:
        config: The install configuration carrying ``repositories``.

    Returns:
        The list of repository entry mappings for ``project.yaml``.
    """
    if not config.repositories:
        return [{"name": "app", "path": "."}]
    repos: list[dict[str, str]] = []
    for repo in config.repositories:
        entry: dict[str, str] = {
            "name": repo["name"],
            "path": repo["path"],
        }
        for optional_field in ("language", "test_command", "build_command"):
            if optional_field in repo:
                entry[optional_field] = repo[optional_field]
        repos.append(entry)
    return repos


def _build_project_yaml(config: InstallConfig) -> dict[str, object]:
    repos = _build_repo_entries(config)

    story_types = list(DEFAULT_STORY_TYPES)
    pipeline: dict[str, object] = {
        # FK-03 §3.2.1: config_version is mandatory (fail-closed). The installer
        # always emits the current supported version so every scaffold is
        # immediately loadable by the loader without silent omission.
        "config_version": SUPPORTED_CONFIG_VERSION,
        # FK-01 §1.3 P5 / FK-03 §3.1: multi_llm is a mandatory production default
        # (true). The scaffold emits the canonical FK-03 §3.1 example llm_roles
        # block so the freshly installed project is immediately FK-conformant.
        # Operators who are not yet ready for multi-LLM routing must consciously
        # set multi_llm: false and remove the llm_roles stanza — a deliberate opt-
        # out, not an automatic install default.
        "features": {"multi_llm": True},
        "llm_roles": {
            "worker": "claude",
            "qa_review": "chatgpt",
            "semantic_review": "gemini",
            "adversarial_sparring": "grok",
            "doc_fidelity": "gemini",
            "governance_adjudication": "gemini",
            "story_creation_review": "chatgpt",
        },
        "max_feedback_rounds": DEFAULT_MAX_FEEDBACK_ROUNDS,
        "max_remediation_rounds": DEFAULT_MAX_REMEDIATION_ROUNDS,
        "exploration_mode": True,
        "verify_layers": list(DEFAULT_VERIFY_LAYERS),
    }
    # FK-03 §3 / AG3-052 (E6 + Design-Decision): a code-producing project must
    # declare the ``sonarqube`` stanza EXPLICITLY — never rely on omission
    # (config-load rejects a code-producing project with an omitted stanza).
    # The scaffold default is ``available: true`` (+ endpoint) per FK-03 §3 —
    # the green gate is mandatory; ``available: false`` is a conscious operator
    # opt-out (``config.sonarqube_available = False``), not an auto default.
    # With ``available: true`` and no reachable Sonar, CP 10d (E5/FK-50 §50.6)
    # FAILs closed — the intended prompt to provision Sonar or opt out
    # consciously. Non-code-producing scaffolds may omit it, but the default
    # story types are code-producing, so it is always written here.
    if {"implementation", "bugfix"}.intersection(story_types):
        pipeline["sonarqube"] = _default_sonarqube_stanza(config)
        # AG3-056: a code-producing project must likewise declare the ``ci``
        # (Jenkins) stanza EXPLICITLY — never rely on omission (config-load
        # rejects an omitted stanza for a code-producing project). Scaffold
        # default ``available: true`` (+ endpoint + pipeline); ``available:
        # false`` is a conscious operator opt-out (``config.ci_available``).
        pipeline["ci"] = _default_ci_stanza(config)

    data: dict[str, object] = {
        "project_key": config.project_key,
        "project_name": config.project_name,
        "repositories": repos,
        "story_types": story_types,
        "pipeline": pipeline,
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
                    str(r) for r in exc.detail.get("residual_links") or []
                ],
                "persisted_row_remains": bool(exc.detail.get("persisted_row_remains")),
            }
            orphaned.append(entry)
        except Exception as exc:  # noqa: BLE001  # honest capture, never silent
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
                    str(r) for r in exc.detail.get("residual_links") or []
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
    # NEUTRAL STRUCTURE ONLY before CP 7 (B1-Rest, AG3-039 R4): create the
    # directory scaffold (empty dirs, no active payload). The ACTIVE harness
    # bindings — ``.codex/config.toml`` (Codex pre-tool-use hook config) and
    # ``.claude/settings.json`` (Claude Code ``PreToolUse`` hook) plus their
    # referenced hook script / guard rules — are STATIC RESOURCE FILES and must
    # NOT be written before CP 7. Writing them ahead of CP 7 would arm active
    # projectlocal harness bindings against a project whose central state-backend
    # registration has not (yet) completed — a fail-open violation of
    # ``formal.installer.invariant.state_backend_registration_precedes_bundle_binding``
    # and story §2.1.4 ("CP 7 lookup ... before writing OTHER artefacts").
    # The static-file deploy is therefore deferred to STRICTLY AFTER the CP 7
    # FAILED-abort gate below. Empty directories carry no binding and may stay.
    created = _deploy_directory_structure(resources_dir, root)

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

    # FK-50 CP 5: write the project config (project.yaml) FIRST. The CP 7
    # config_digest is computed over its canonicalised content, so it must be on
    # disk before registration. No bundle binding has happened yet.
    yaml_path = project_config_path(root)
    yaml_data = _build_project_yaml(config)
    if _write_yaml_if_changed(yaml_path, yaml_data):
        created.append(str(yaml_path.relative_to(root)))

    # FK-50 CP 7 (AG3-039): State-Backend project registration. Ordered AFTER
    # project.yaml (CP 5) and STRICTLY BEFORE every bundle binding — the prompt
    # bundle binding (FK-50 §50.5), the skill links (CP 8) and the harness
    # settings. This is the
    # ``installer.invariant.state_backend_registration_precedes_bundle_binding``
    # ordering invariant: registration in the central state backend must complete
    # before project-local bundle bindings become active. Idempotent: same digest
    # => SKIPPED (no re-write), divergent digest => update_upgraded, absent =>
    # save; missing GitHub coordinates => FAILED (fail-closed, FK-50 §50.6).
    from agentkit.installer.registration import CheckpointStatus

    cp7_result = _run_cp7_state_backend_registration(config, root, yaml_data)
    checkpoint_results: list[CheckpointResult] = [cp7_result]

    # FK-50 §50.4: a FAILED CP 7 aborts the install BEFORE any bundle binding.
    # This is the fail-closed half of the
    # ``installer.invariant.state_backend_registration_precedes_bundle_binding``
    # ordering invariant: a bundle binding must never become active against a
    # project whose central State-Backend registration did not complete. Returning
    # ``success=True`` here (and binding anyway) would leave the project
    # UNREGISTERED behind active bindings (fail-open). The FAILED CheckpointResult
    # — including its machine-readable ``reason`` — is propagated unchanged so the
    # caller can branch on the precondition violation.
    if cp7_result.status is CheckpointStatus.FAILED:
        return InstallResult(
            success=False,
            project_root=root,
            created_files=tuple(created),
            errors=(cp7_result.detail or cp7_result.reason or "CP 7 registration failed.",),
            checkpoint_results=(cp7_result,),
        )

    # ---- Active projectlocal bindings (FK-50 §50.5 / CP 8) — only AFTER CP 7 ----

    # B1-Rest (AG3-039 R4): the static resource files include the ACTIVE harness
    # bindings (``.codex/config.toml`` Codex hook config, ``.claude/settings.json``
    # ``PreToolUse`` hook) plus the hook script and guard rules they reference.
    # Deploying them here — STRICTLY AFTER the CP 7 FAILED-abort gate — guarantees
    # no active projectlocal harness binding ever exists on disk against a project
    # whose central state-backend registration did not complete. This is the
    # active half of
    # ``formal.installer.invariant.state_backend_registration_precedes_bundle_binding``
    # (story §2.1.4; FK-50 §50.3 CP 7 before CP 8/CP 9, §50.4 FAILED => abort).
    active_binding_paths = _default_governance_hook_settings_paths(root)
    active_binding_before = _file_digests(active_binding_paths)
    static_created = _deploy_static_resource_files(resources_dir, root)
    created.extend(
        rel
        for rel in static_created
        if root / rel not in active_binding_paths
    )
    created.extend(
        _register_default_governance_hooks(
            config,
            root,
            before=active_binding_before,
        )
    )

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

    # Prompt-bundle binding (FK-50 §50.5): materialise the prompt bindings only
    # after the project is registered in the state backend.
    created.extend(_deploy_prompt_bindings(root, canonical_prompt_bundle_root))

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

    # FK-50 CP 10d (AG3-052 E5): applicability-conditional SonarQube
    # precondition checkpoint, run after the project config is on disk.
    # available:false => SKIPPED (reason=not_applicable, NOT FAILED);
    # available:true => fail-closed checks (reachability/version, token role
    # incl. Administer Issues, branch-plugin presence + conformance self-test).
    sonar_cp = _run_cp10d_sonarqube(config, root, yaml_data)
    checkpoint_results.append(_sonar_cp_to_checkpoint_result(sonar_cp))

    # AG3-056 (FIX-5): applicability-conditional CI (Jenkins) precondition
    # checkpoint, mirroring CP 10d. ci.available:false => SKIPPED
    # (reason=not_applicable); ci.available:true => fail-closed checks
    # (reachable, token authenticates, pipeline exists). A FAILED result
    # ABORTS the install — the closure pre-merge barrier must not be promised a
    # real CI trigger against an unverified Jenkins. The PASS/SKIPPED outcome
    # is RECORDED in ``checkpoint_results`` (WARNING-2), mirroring the Sonar CP;
    # a FAILED result never reaches here (it raised + aborted above).
    ci_cp = _run_ci_preflight(config, yaml_data)
    checkpoint_results.append(_ci_cp_to_checkpoint_result(ci_cp))

    return InstallResult(
        success=True,
        project_root=root,
        created_files=tuple(created),
        checkpoint_results=tuple(checkpoint_results),
    )


def _canonical_config_digest(yaml_data: dict[str, object]) -> str:
    """Return the SHA-256 over the canonicalised project.yaml content (CP 7).

    Canonicalisation uses ``json.dumps(..., sort_keys=True)`` so the digest is
    stable under key ordering and whitespace. This is the idempotency key for
    CP 7: an identical config yields an identical digest (SKIPPED), a changed
    config yields a different digest (UPGRADED).
    """
    canonical = json.dumps(yaml_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_registration_repo(
    config: InstallConfig, root: Path
) -> ProjectRegistrationRepository:
    """Return the injected registration repo, or the default productive adapter."""
    if config.registration_repo is not None:
        return config.registration_repo
    from agentkit.state_backend.store.project_registration_repository import (
        StateBackendProjectRegistrationRepository,
    )

    return StateBackendProjectRegistrationRepository(root)


def _register_default_governance_hooks(
    config: InstallConfig,
    root: Path,
    *,
    before: dict[Path, str] | None = None,
) -> list[str]:
    """Register default project hooks through Governance and settings writers."""

    from agentkit.governance.default_hook_definitions import (
        build_default_hook_definitions,
    )
    from agentkit.governance.runner import Governance
    from agentkit.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )

    watched_paths = _default_governance_hook_settings_paths(root)
    before_digests = before or _file_digests(watched_paths)
    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(root),
        lock_repo=LockRecordRepository(root),
        project_key=config.project_key,
        project_root=root,
        worktree_repo=StateBackendWorktreeRepository(root),
    )
    result = governance.register_hooks(build_default_hook_definitions())
    if result.errors:
        raise InstallationError(
            "Default governance hook registration failed.",
            detail={"errors": [str(error) for error in result.errors]},
        )
    after = _file_digests(watched_paths)
    return [
        str(path.relative_to(root))
        for path in watched_paths
        if before_digests.get(path) != after.get(path)
    ]


def _default_governance_hook_settings_paths(root: Path) -> tuple[Path, ...]:
    """Return settings files materialized by default hook registration."""

    return (
        root / ".claude" / "settings.json",
        root / ".codex" / "hooks.json",
    )


def _file_digests(paths: tuple[Path, ...]) -> dict[Path, str]:
    """Return content digests for existing files in ``paths``."""

    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }


def _run_cp7_state_backend_registration(
    config: InstallConfig,
    root: Path,
    yaml_data: dict[str, object],
) -> CheckpointResult:
    """Run FK-50 §50.3 CP 7 — State-Backend project registration (idempotent).

    Computes the ``config_digest`` over the canonicalised project.yaml, looks up
    the existing registration and converges on one consistent state
    (``formal.installer.invariants §register_project_is_idempotent``):

    * no existing registration -> ``save`` a fresh :class:`ProjectRegistration`
      (``CheckpointStatus.CREATED``).
    * existing registration with the SAME ``config_digest`` -> no write,
      ``CheckpointStatus.SKIPPED`` (idempotent re-run).
    * existing registration with a DIVERGENT ``config_digest`` ->
      ``update_upgraded`` (new digest + ``last_upgraded_at``),
      ``CheckpointStatus.UPDATED``.

    The ``project_registry`` row requires ``github_owner``/``github_repo`` NOT
    NULL (story §2.1.1; FK-50 §50.3 CP 7 records GitHub owner/repo as a MANDATORY
    coordinate). When the install config carries no GitHub coordinates, CP 7 is a
    hard precondition failure: it records NOTHING and returns
    ``CheckpointStatus.FAILED`` (FK-50 §50.6 — a CP 7 precondition violation is
    FAILED, never a silent SKIP that leaves the project unregistered after a
    "successful" install). It never fabricates github values (ZERO DEBT) and never
    writes a partial row (FAIL-CLOSED). ``SKIPPED`` is reserved for the genuine
    idempotency case (existing registration, identical ``config_digest``).

    Args:
        config: The install configuration (carries the registration repo, the
            GitHub coordinates and the runtime profile).
        root: Project root (recorded as ``project_root``).
        yaml_data: The project.yaml mapping just written (digest source).

    Returns:
        The :class:`CheckpointResult` for CP 7.
    """
    import time

    from agentkit.installer.github_coordinates import validate_github_coordinate
    from agentkit.installer.registration import (
        CP7_STATE_BACKEND_REGISTRATION,
        REASON_CONFIG_DIGEST_UNCHANGED,
        REASON_INVALID_GITHUB_COORDINATES,
        REASON_MISSING_GITHUB_COORDINATES,
        CheckpointResult,
        CheckpointStatus,
        ProjectRegistration,
        RuntimeProfile,
    )

    start = time.monotonic()
    # FK-50 §50.3 CP 7 lists GitHub owner/repo as MANDATORY coordinates. A
    # missing (``None``) OR empty/whitespace-only coordinate is equally invalid:
    # ``""`` / ``"   "`` carries no GitHub identity and would persist a
    # meaningless ``project_registry`` row (fail-open). Both are treated as a
    # hard precondition violation => FAILED, no write. §50.6 maps a CP 7
    # precondition violation to FAILED. Returning SKIPPED here would leave the
    # project UNREGISTERED after a "successful" install (fail-open). It never
    # fabricates github values (ZERO DEBT) and never writes a partial row.
    owner = config.github_owner
    repo_name = config.github_repo
    if owner is None or repo_name is None or not owner.strip() or not repo_name.strip():
        return CheckpointResult(
            checkpoint=CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "Missing or empty github_owner/github_repo on InstallConfig; "
                "project_registry requires both NOT NULL and non-empty (FK-50 "
                "§50.3 CP 7). CP 7 fails closed rather than leaving the project "
                "unregistered or persisting an empty coordinate."
            ),
            reason=REASON_MISSING_GITHUB_COORDINATES,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    # FAIL-CLOSED / SSOT (AG3-039 R7 ERROR-2): the coordinates are PRESENT but
    # must additionally be WELL-FORMED before they are persisted. The CLI and
    # the remote-URL parser already gate on ``validate_github_coordinate``; a
    # direct ``install_agentkit(InstallConfig(...))`` call would otherwise bypass
    # that single validation truth and persist a malformed coordinate (e.g.
    # ``".."``, ``"-bad"``, a slash- or control-char-laden value). Enforce the
    # SAME predicate at this port so no path can write an invalid row. The
    # downstream ``ProjectRegistration`` model validator is the hard floor; this
    # check turns a would-be ``ValueError`` into a clean FAILED CheckpointResult.
    if validate_github_coordinate(owner, repo_name) is None:
        return CheckpointResult(
            checkpoint=CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Malformed github_owner={owner!r} / github_repo={repo_name!r} "
                "on InstallConfig; not a well-formed GitHub owner/repo (FK-50 "
                "§50.3 CP 7, AG3-039 R6 E-b). CP 7 fails closed rather than "
                "persisting an invalid project_registry coordinate."
            ),
            reason=REASON_INVALID_GITHUB_COORDINATES,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    repo = _resolve_registration_repo(config, root)
    digest = _canonical_config_digest(yaml_data)
    profile = config.runtime_profile or RuntimeProfile.CORE

    existing = repo.get(config.project_key)
    reason: str | None = None
    if existing is None:
        repo.save(
            ProjectRegistration(
                project_key=config.project_key,
                project_root=root,
                github_owner=owner,
                github_repo=repo_name,
                runtime_profile=profile,
                config_version=PROJECT_CONFIG_VERSION,
                config_digest=digest,
                registered_at=datetime.now(tz=UTC),
            )
        )
        status = CheckpointStatus.CREATED
        detail = f"Registered project {config.project_key!r} (digest {digest[:12]})."
    elif existing.config_digest == digest:
        status = CheckpointStatus.SKIPPED
        reason = REASON_CONFIG_DIGEST_UNCHANGED
        detail = (
            f"Project {config.project_key!r} already registered with matching "
            "config_digest; idempotent skip."
        )
    else:
        repo.update_upgraded(config.project_key, datetime.now(tz=UTC), digest)
        status = CheckpointStatus.UPDATED
        detail = (
            f"Project {config.project_key!r} config_digest changed "
            f"({existing.config_digest[:12]} -> {digest[:12]}); upgraded."
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    return CheckpointResult(
        checkpoint=CP7_STATE_BACKEND_REGISTRATION,
        status=status,
        detail=detail,
        reason=reason,
        duration_ms=duration_ms,
    )


def _run_cp10d_sonarqube(
    config: InstallConfig,
    root: Path,
    yaml_data: dict[str, object],
) -> SonarPreflightResult:
    """Run the FK-50 CP 10d SonarQube precondition checkpoint (fail-closed).

    Parses the written ``sonarqube`` stanza into a ``SonarQubeConfig`` and
    runs :func:`check_sonarqube_preconditions`:

    * ``available: false`` => SKIPPED (``reason=not_applicable``), no Sonar
      collaborators needed.
    * ``available: true`` => the fail-closed checks run; a FAILED result
      raises ``InstallationError`` and ABORTS the install (FK-50 §50.6 — the
      green gate must not be armed against an unverifiable Sonar). There is
      NO ``verification_deferred`` escape hatch (AG3-052 E5): if the
      verification cannot be carried out — no ``sonar_client``, no
      branch-plugin self-test (neither injected nor assemblable from a
      ``sonar_scan_runner``), or any failing probe — CP 10d is FAILED and the
      install aborts.

    Productive branch-plugin self-test (AG3-052 E5): when the caller does not
    inject a pre-built ``sonar_branch_plugin_self_test`` but supplies a
    ``sonar_client`` + ``sonar_scan_runner``, the installer assembles the
    PRODUCTIVE :class:`SonarClientScannerHarness` and drives the FK-50 §50.3
    conformance steps through it (``run_branch_plugin_conformance_self_test``).
    Only the LIVE server + scanner (``sonar_scan_runner``) is OOS (§2.2).

    Args:
        config: The install configuration (carries the Sonar collaborators).
        root: Project root (resolves the default-profile path).
        yaml_data: The project.yaml mapping just written (source of the
            ``sonarqube`` stanza).

    Returns:
        The :class:`SonarPreflightResult` (SKIPPED when not applicable, else
        PASS — a FAILED result raises before returning).

    Raises:
        InstallationError: When an APPLICABLE checkpoint FAILs (fail-closed).
    """
    from agentkit.config.models import SonarQubeConfig
    from agentkit.installer.integration_checkpoints import (
        check_sonarqube_preconditions,
    )
    from agentkit.installer.integration_checkpoints.sonar_preflight import (
        CheckpointStatus,
        SonarPreflightResult,
    )

    pipeline = yaml_data.get("pipeline", {})
    stanza = pipeline.get("sonarqube") if isinstance(pipeline, dict) else None
    if not isinstance(stanza, dict):
        # No sonarqube stanza written (non-code-producing scaffold) => the
        # gate is not-applicable; CP 10d is a no-op SKIP.
        return SonarPreflightResult(
            status=CheckpointStatus.SKIPPED, reason="not_applicable"
        )

    sonar_config = SonarQubeConfig.model_validate(stanza)
    self_test = _resolve_branch_plugin_self_test(config)
    result = check_sonarqube_preconditions(
        sonar_config,
        client=config.sonar_client,
        repo_root=root,
        token_permissions=config.sonar_token_permissions or frozenset(),
        branch_plugin_self_test=self_test,
    )
    if result.status == CheckpointStatus.FAILED:
        raise InstallationError(
            "FK-50 CP 10d SonarQube precondition FAILED: "
            f"{result.reason} ({'; '.join(result.details)}). The green gate "
            "must not be armed against an unverifiable Sonar (FK-50 §50.6). "
            "Fix the precondition, or set sonarqube.available=false to opt out.",
            detail={
                "cause": "SonarPreconditionFailed",
                "reason": result.reason,
                "details": list(result.details),
            },
        )
    return result


def _run_ci_preflight(
    config: InstallConfig,
    yaml_data: dict[str, object],
) -> CiPreflightResult:
    """Run the CI (Jenkins) precondition checkpoint (AG3-056 FIX-5, fail-closed).

    Parses the written ``ci`` stanza into a ``JenkinsConfig`` and runs
    :func:`check_ci_preconditions`, mirroring the Sonar CP 10d discipline:

    * ``available: false`` => SKIPPED (``reason=not_applicable``), no Jenkins
      collaborator needed.
    * ``available: true`` => fail-closed checks (reachable, token
      authenticates, pipeline exists). A FAILED result raises
      ``InstallationError`` and ABORTS the install — the closure pre-merge
      barrier (AG3-053) must not be promised a real CI trigger against an
      unverified Jenkins. There is NO escape hatch: a missing ``ci_client``
      on an ``available: true`` stanza FAILs closed (``missing_dependency``).

    Args:
        config: The install configuration (carries the ``ci_client``).
        yaml_data: The project.yaml mapping just written (source of the
            ``ci`` stanza).

    Returns:
        The :class:`CiPreflightResult` (SKIPPED when not applicable, else PASS
        — a FAILED result raises before returning).

    Raises:
        InstallationError: When an APPLICABLE checkpoint FAILs (fail-closed).
    """
    from agentkit.config.models import JenkinsConfig
    from agentkit.installer.integration_checkpoints import (
        CiPreflightResult,
        check_ci_preconditions,
    )
    from agentkit.installer.integration_checkpoints.ci_preflight import (
        CheckpointStatus,
    )

    pipeline = yaml_data.get("pipeline", {})
    stanza = pipeline.get("ci") if isinstance(pipeline, dict) else None
    if not isinstance(stanza, dict):
        # No ci stanza written (non-code-producing scaffold) => the runner is
        # not-applicable; the checkpoint is a no-op SKIP.
        return CiPreflightResult(
            status=CheckpointStatus.SKIPPED, reason="not_applicable"
        )

    ci_config = JenkinsConfig.model_validate(stanza)
    result = check_ci_preconditions(ci_config, client=config.ci_client)
    if result.status == CheckpointStatus.FAILED:
        raise InstallationError(
            "AG3-056 CI (Jenkins) precondition FAILED: "
            f"{result.reason} ({'; '.join(result.details)}). The closure "
            "pre-merge barrier must not be promised a real CI trigger against "
            "an unverifiable Jenkins. Fix the precondition, or set "
            "ci.available=false to opt out.",
            detail={
                "cause": "CiPreconditionFailed",
                "reason": result.reason,
                "details": list(result.details),
            },
        )
    return result


#: Stable checkpoint id for the AG3-052 CP 10d SonarQube precondition.
_SONAR_CHECKPOINT_ID = "cp_10d_sonarqube_precondition"
#: Stable checkpoint id for the AG3-056 CI (Jenkins) precondition (FIX-5).
_CI_CHECKPOINT_ID = "ci_preflight_jenkins_precondition"


def _preflight_to_checkpoint_result(
    checkpoint_id: str,
    *,
    status: str,
    reason: str | None,
    details: tuple[str, ...],
) -> CheckpointResult:
    """Map a preflight result (PASS/SKIPPED/FAILED) to a ``CheckpointResult``.

    Shared by the Sonar CP 10d and the AG3-056 CI preflight recording
    (WARNING-2). The preflight modules use a flat string status
    (``PASS``/``SKIPPED``/``FAILED``); this projects it onto the installer's
    :class:`CheckpointStatus` enum and preserves the machine-readable
    ``reason`` (mandatory for SKIPPED/FAILED, FK-50 §50.4). ``FAILED`` is
    mapped for completeness even though an APPLICABLE failure aborts the
    install before recording.
    """
    from agentkit.installer.registration import CheckpointResult, CheckpointStatus

    status_map = {
        "PASS": CheckpointStatus.PASS,
        "SKIPPED": CheckpointStatus.SKIPPED,
        "FAILED": CheckpointStatus.FAILED,
    }
    mapped = status_map.get(status, CheckpointStatus.FAILED)
    return CheckpointResult(
        checkpoint=checkpoint_id,
        status=mapped,
        detail="; ".join(details) or None,
        reason=reason,
        duration_ms=0,
    )


def _sonar_cp_to_checkpoint_result(result: SonarPreflightResult) -> CheckpointResult:
    """Record the Sonar CP 10d outcome as a ``CheckpointResult`` (WARNING-2)."""
    return _preflight_to_checkpoint_result(
        _SONAR_CHECKPOINT_ID,
        status=result.status,
        reason=result.reason,
        details=result.details,
    )


def _ci_cp_to_checkpoint_result(result: CiPreflightResult) -> CheckpointResult:
    """Record the AG3-056 CI preflight outcome as a ``CheckpointResult`` (FIX-5)."""
    return _preflight_to_checkpoint_result(
        _CI_CHECKPOINT_ID,
        status=result.status,
        reason=result.reason,
        details=result.details,
    )


def _resolve_branch_plugin_self_test(
    config: InstallConfig,
) -> BranchPluginSelfTest | None:
    """Resolve the CP 10d branch-plugin conformance self-test (AG3-052 E5).

    Precedence:

    1. an explicitly injected ``sonar_branch_plugin_self_test`` (tests stub
       the HTTP boundary inside it);
    2. otherwise, when a ``sonar_client`` AND a ``sonar_scan_runner`` are
       present, the PRODUCTIVE :class:`SonarClientScannerHarness` wired into
       ``run_branch_plugin_conformance_self_test``;
    3. otherwise ``None`` — which makes ``check_sonarqube_preconditions`` FAIL
       closed (``missing_dependency``) for an ``available: true`` config (no
       silent skip, FK-50 §50.6).

    Args:
        config: The install configuration carrying the Sonar collaborators.

    Returns:
        A ``BranchPluginSelfTest`` callable, or ``None`` when no verification
        can be assembled.
    """
    if config.sonar_branch_plugin_self_test is not None:
        return config.sonar_branch_plugin_self_test
    if config.sonar_client is None or config.sonar_scan_runner is None:
        return None
    from agentkit.installer.integration_checkpoints.branch_plugin_self_test import (
        run_branch_plugin_conformance_self_test,
    )
    from agentkit.installer.integration_checkpoints.scanner_harness import (
        SonarClientScannerHarness,
    )

    scan_runner = config.sonar_scan_runner

    def _self_test(client: SonarClient) -> bool:
        harness = SonarClientScannerHarness(client=client, scan_runner=scan_runner)
        return run_branch_plugin_conformance_self_test(client, harness)

    return _self_test


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
    removed.extend(_remove_file(project_root / CODEX_DIR / "hooks.json", project_root))
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
    "PROJECT_CONFIG_VERSION",
    "InstallConfig",
    "InstallResult",
    "UninstallResult",
    "install_agentkit",
    "uninstall_agentkit",
]
