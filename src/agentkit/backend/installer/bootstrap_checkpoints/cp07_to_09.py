"""Checkpoint handlers CP 7, CP 8, CP 9 (FK-50 §50.3 / §50.5).

* CP 7 — State-Backend project registration (idempotent). Transferred from the
  legacy ``_run_cp7_state_backend_registration`` (behaviour preserved).
* CP 8 — skill links via ``Skills.bind_skill`` AND the prompt-bundle binding via
  ``PromptRuntime.update_binding`` (BOTH binding paths, FK-50 §50.3 CP 8 / §50.5,
  story AC6).
* CP 9 — hook registration via ``Governance.register_hooks`` (FK-50 §50.3 CP 9,
  story AC7) — the deliberate §50.3 correction away from a static settings
  deploy, preserving deployed behaviour equivalence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
)
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult

#: Machine reason for a CP 8/CP 9 read-only mode where the binding/hook is
#: present and current.
REASON_BINDING_CURRENT = "binding_current"


def cp07_backend_registration(context: CheckpointContext) -> CheckpointResult:
    """CP 7 — register the project in the State-Backend (idempotent).

    Register mode: delegates to the transferred CP 7 implementation
    (``_run_cp7_state_backend_registration``) — fresh -> CREATED, identical
    digest -> SKIPPED, divergent digest -> UPDATED, missing/invalid coordinates
    -> FAILED (fail-closed, FK-50 §50.6).

    Dry-run/verify: read-only. Computes the digest and looks up the existing
    registration to report the status the register run WOULD produce, without
    writing. A missing/invalid coordinate is still FAILED (the precondition
    holds in every mode).
    """
    from agentkit.backend.installer.github_coordinates import validate_github_coordinate
    from agentkit.backend.installer.registration import (
        CP7_STATE_BACKEND_REGISTRATION,
        REASON_INVALID_GITHUB_COORDINATES,
        REASON_MISSING_GITHUB_COORDINATES,
    )
    from agentkit.backend.installer.runner import (
        PROJECT_CONFIG_VERSION,
        _canonical_config_digest,
        _resolve_registration_repo,
        _run_cp7_state_backend_registration,
    )

    config = context.config
    yaml_data = context.run_state.project_yaml
    if yaml_data is None:  # pragma: no cover - CP 5 always precedes CP 7
        raise RuntimeError("CP 7 requires CP 5 project.yaml on the run-state.")

    if context.mode.mutations_allowed:
        return _run_cp7_state_backend_registration(config, context.project_root, yaml_data)

    # ---- read-only (dry_run / verify): mirror the register decision ----
    start = time.monotonic()
    owner = config.github_owner
    repo_name = config.github_repo
    if owner is None or repo_name is None or not owner.strip() or not repo_name.strip():
        return make_result(
            CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail="Missing or empty github_owner/github_repo (FK-50 §50.3 CP 7).",
            reason=REASON_MISSING_GITHUB_COORDINATES,
            start=start,
        )
    if validate_github_coordinate(owner, repo_name) is None:
        return make_result(
            CP7_STATE_BACKEND_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"Malformed github_owner={owner!r}/github_repo={repo_name!r}.",
            reason=REASON_INVALID_GITHUB_COORDINATES,
            start=start,
        )
    digest = _canonical_config_digest(yaml_data)
    repo = _resolve_registration_repo(config, context.project_root)
    existing = repo.get(config.project_key)
    if existing is None:
        planned = CheckpointStatus.CREATED
        detail = f"Would register project {config.project_key!r} (digest {digest[:12]})."
    elif existing.config_digest == digest:
        planned = CheckpointStatus.PASS
        detail = f"Project {config.project_key!r} already registered (digest match)."
    else:
        planned = CheckpointStatus.UPDATED
        detail = (
            f"Project {config.project_key!r} digest changed "
            f"({existing.config_digest[:12]} -> {digest[:12]}); would upgrade."
        )
    _ = PROJECT_CONFIG_VERSION  # documents the version the register run records
    if is_dry_run(context.mode):
        return planned_result(
            CP7_STATE_BACKEND_REGISTRATION,
            planned_status=planned,
            detail=detail,
            start=start,
        )
    return make_result(
        CP7_STATE_BACKEND_REGISTRATION,
        status=planned,
        detail=detail,
        start=start,
    )


def cp08_skill_bindings(context: CheckpointContext) -> CheckpointResult:
    """CP 8 — bind skill links AND the prompt-bundle binding (BOTH paths).

    FK-50 §50.3 CP 8 / §50.5 (story AC6): CP 8 binds the mandatory skill links
    through the agent-skills top-surface ``Skills.bind_skill`` AND updates the
    prompt-bundle binding through ``PromptRuntime.update_binding``. Both calls
    are part of CP 8.

    Register mode: resolves (preflight, no writes) + binds the mandatory skills
    transactionally (transferred from the legacy ``_resolve_mandatory_skill_bundles``
    / ``_bind_resolved_skills``), then updates the prompt-bundle binding from
    the central store manifest.

    Dry-run/verify: read-only. Resolves the bundles (a missing bundle is still a
    fail-closed error in the resolution preflight) but performs NO link creation
    and NO ``update_binding`` write.
    """
    from agentkit.backend.installer.runner import (
        PROMPT_MANIFEST_FILENAME,
        _ensure_prompt_bundle_store_entry,
        _load_prompt_bundle_manifest,
        _resolve_mandatory_skill_bundles,
        _resolve_prompt_source_dir,
        deploy_post_registration_artifacts,
    )

    start = time.monotonic()
    config = context.config
    root = context.project_root

    # Preflight resolution validates the bundles in EVERY mode (a missing
    # mandatory bundle is fail-closed even in a plan — story would-be CREATED is
    # only honest if the bundles actually resolve). ``_resolve_mandatory_skill_bundles``
    # is pure resolution (NO project/store writes).
    _skills, resolved = _resolve_mandatory_skill_bundles(config, root)
    skill_names = [name for name, _root in resolved]

    if not context.mode.mutations_allowed:
        # AG3-088 FIX (story AC10-AC12): dry_run AND verify MUST mutate NOTHING —
        # not even the central prompt-bundle store. ``_ensure_prompt_bundle_store_entry``
        # creates dirs / copies files into the store, so it MUST NOT run in a
        # read-only mode. The plan only needs the bundle_id/version, which the
        # SOURCE manifest carries; ``_load_prompt_bundle_manifest`` is read-only
        # (it reads the source manifest and never writes the store).
        prompt_source_dir = _resolve_prompt_source_dir(config)
        manifest, _ = _load_prompt_bundle_manifest(prompt_source_dir)
        bundle_id = str(manifest["bundle_id"])
        bundle_version = str(manifest["bundle_version"])
        detail = (
            f"Would bind skills {skill_names} via Skills.bind_skill and update "
            f"the prompt binding to {bundle_id}@{bundle_version} via "
            "PromptRuntime.update_binding."
        )
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_08_SKILL_BINDINGS,
                planned_status=CheckpointStatus.CREATED,
                detail=detail,
                start=start,
            )
        # AG3-176 R8: VERIFY must read-only resolve BOTH harness links and pin
        # them to the same expected bundle id/version/digest — never unconditional
        # PASS/binding_current.
        verify_err = _verify_skill_harness_pins(root, resolved)
        if verify_err is not None:
            return make_result(
                nid.CP_08_SKILL_BINDINGS,
                status=CheckpointStatus.FAILED,
                detail=verify_err,
                reason="skill_binding_pin_mismatch",
                start=start,
            )
        return make_result(
            nid.CP_08_SKILL_BINDINGS,
            status=CheckpointStatus.PASS,
            detail=(
                f"Both harness skill links pin to expected immutable bundles "
                f"{skill_names} (AG3-176 R8); prompt would be "
                f"{bundle_id}@{bundle_version}."
            ),
            reason=REASON_BINDING_CURRENT,
            start=start,
        )

    # Capture the harness settings baseline BEFORE the static-resource deploy may
    # overwrite the settings files with the bundled template, so CP 9's governance
    # idempotency compares against the prior GOVERNANCE result (not the template).
    from agentkit.backend.installer.runner import (
        _default_governance_hook_settings_paths,
        _file_digests,
    )

    settings_paths = _default_governance_hook_settings_paths(root)
    baseline: dict[object, str] = dict(_file_digests(settings_paths).items())
    context.run_state.hook_settings_baseline = baseline

    # ---- register: deploy the active project-local bindings (CP 8 region) ----
    # The central prompt-bundle store entry is materialised HERE (register only,
    # AFTER the mutations_allowed guard) — it creates dirs / copies files, so it
    # must never run in dry_run/verify (story AC10-AC12). It is the source of the
    # bundle_id/version used by the prompt-binding write below.
    prompt_source_dir = _resolve_prompt_source_dir(config)
    _, manifest, _ = _ensure_prompt_bundle_store_entry(prompt_source_dir)
    bundle_id = str(manifest["bundle_id"])
    bundle_version = str(manifest["bundle_version"])

    # ``deploy_post_registration_artifacts`` binds the skill links
    # (``Skills.bind_skill``, path 1), the prompt bindings, the static harness
    # resources, gitignore, control-plane and codex settings (behaviour
    # transferred from the legacy install body). The prompt-bundle binding
    # (``PromptRuntime.update_binding``, path 2) is the explicit CP 8 second
    # binding path (FK-50 §50.5, story AC6).
    for rel in deploy_post_registration_artifacts(config, root):
        if rel not in context.run_state.created_files:
            context.run_state.created_files.append(rel)
    _update_prompt_binding(context, bundle_id, bundle_version, PROMPT_MANIFEST_FILENAME)
    return make_result(
        nid.CP_08_SKILL_BINDINGS,
        status=CheckpointStatus.CREATED,
        detail=(
            f"Bound skills {skill_names} and prompt binding "
            f"{bundle_id}@{bundle_version} (+ harness bindings)."
        ),
        start=start,
    )


def _read_skill_manifest(bundle_root: Path) -> dict[str, object] | None:
    """Read a skill-bundle ``manifest.json`` fail-closed (installer-local helper)."""
    import json

    path = bundle_root / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _verify_skill_harness_pins(
    project_root: Path,
    resolved: list[tuple[str, Path]],
) -> str | None:
    """Read-only VERIFY for both harness skill links (AG3-176 R8).

    For every mandatory skill, both Claude and Codex bind points must:
    * exist as directory links (symlink/junction);
    * resolve to targets whose ``manifest.json`` declares the same
      ``bundle_id`` / ``bundle_version`` / ``manifest_digest`` as the
      expected immutable pin from resolution;
    * agree with each other (no cross-harness version divergence).

    Returns ``None`` when current, else a human detail string for FAILED.
    """
    # Public skills package surface only (architecture-conformance / AC001).
    import hashlib
    import json

    from agentkit.backend.skills import (
        HarnessKind,
        is_directory_link,
        read_directory_link_target,
    )

    def _digest(manifest: dict[str, object]) -> str:
        payload = {k: v for k, v in manifest.items() if k != "manifest_digest"}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    harness_dirs = {
        HarnessKind.CLAUDE_CODE: project_root / ".claude" / "skills",
        HarnessKind.CODEX: project_root / ".codex" / "skills",
    }

    for skill_name, expected_root in resolved:
        expected_manifest = _read_skill_manifest(expected_root)
        if not expected_manifest:
            return (
                f"Expected bundle for skill '{skill_name}' has no readable "
                f"manifest at {expected_root} (fail-closed VERIFY)."
            )
        expected_id = str(expected_manifest.get("bundle_id") or "")
        expected_ver = str(expected_manifest.get("bundle_version") or "")
        expected_digest = expected_manifest.get("manifest_digest")
        if not isinstance(expected_digest, str) or not expected_digest:
            return (
                f"Expected bundle for skill '{skill_name}' lacks manifest_digest "
                f"(fail-closed VERIFY)."
            )
        if expected_digest != _digest(expected_manifest):
            return (
                f"Expected bundle for skill '{skill_name}' has corrupt "
                f"manifest_digest (declared != runtime algorithm)."
            )

        for harness, skills_dir in harness_dirs.items():
            link_path = skills_dir / skill_name
            if not is_directory_link(link_path):
                return (
                    f"VERIFY failed: harness link missing or not a directory link "
                    f"for skill '{skill_name}' (harness={harness.value}, "
                    f"path={link_path})."
                )
            try:
                target = read_directory_link_target(link_path).resolve()
            except OSError as exc:
                return (
                    f"VERIFY failed: cannot resolve harness link for skill "
                    f"'{skill_name}' (harness={harness.value}): {exc}"
                )
            if not target.is_dir():
                return (
                    f"VERIFY failed: harness link target for skill '{skill_name}' "
                    f"(harness={harness.value}) is not a directory: {target}"
                )
            target_manifest = _read_skill_manifest(target)
            if not target_manifest:
                return (
                    f"VERIFY failed: link target for skill '{skill_name}' "
                    f"(harness={harness.value}) has no manifest.json — mutable "
                    f"or non-bundle target refused (path={target})."
                )
            tid = str(target_manifest.get("bundle_id") or "")
            tver = str(target_manifest.get("bundle_version") or "")
            tdigest = target_manifest.get("manifest_digest")
            if tid != expected_id or tver != expected_ver:
                return (
                    f"VERIFY failed: skill '{skill_name}' harness={harness.value} "
                    f"pins {tid}@{tver}, expected {expected_id}@{expected_ver}."
                )
            if not isinstance(tdigest, str) or tdigest != expected_digest:
                return (
                    f"VERIFY failed: skill '{skill_name}' harness={harness.value} "
                    f"digest mismatch (got={tdigest!r}, expected={expected_digest!r})."
                )
            if tdigest != _digest(target_manifest):
                return (
                    f"VERIFY failed: skill '{skill_name}' harness={harness.value} "
                    f"target manifest_digest does not match runtime algorithm "
                    f"(tampered or corrupt target at {target})."
                )

    return None


def _update_prompt_binding(
    context: CheckpointContext,
    bundle_id: str,
    bundle_version: str,
    manifest_filename: str,
) -> None:
    """Update the prompt-bundle binding via ``PromptRuntime.update_binding``.

    FK-50 §50.5: the second CP 8 binding path. Idempotent at the file level —
    when the on-disk lock already matches the desired content the write is
    skipped, but ``update_binding`` is the canonical owner-BC entry point and is
    always used to (re)materialise a divergent lock.
    """
    from agentkit.backend.installer.paths import prompt_bundle_lock_path, prompt_bundle_store_dir
    from agentkit.backend.prompt_runtime.runtime import (
        PromptRuntime,
        build_prompt_bundle_lock_content,
    )

    bundle_root = prompt_bundle_store_dir(bundle_id, bundle_version)
    manifest_text = (bundle_root / manifest_filename).read_text(encoding="utf-8")
    desired = build_prompt_bundle_lock_content(
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        manifest_file=manifest_filename,
        manifest_text=manifest_text,
    )
    lock_path = prompt_bundle_lock_path(context.project_root)
    if lock_path.is_file() and lock_path.read_text(encoding="utf-8") == desired:
        return
    PromptRuntime(context.project_root).update_binding(bundle_id, bundle_version)
    rel = str(lock_path.relative_to(context.project_root))
    if rel not in context.run_state.created_files:
        context.run_state.created_files.append(rel)


def cp09_hook_registration(context: CheckpointContext) -> CheckpointResult:
    """CP 9 — register project hooks via ``Governance.register_hooks`` (AC7).

    FK-50 §50.3 CP 9 (deliberate §50.3 correction): hooks are registered through
    the governance top-surface ``Governance.register_hooks`` rather than a static
    settings deploy. Behaviour preserved: the same default hook definitions are
    registered and the same harness settings are materialised (the transferred
    ``_register_default_governance_hooks`` drives both).

    Dry-run/verify: read-only — reports the planned registration without calling
    ``register_hooks``.
    """
    from agentkit.backend.installer.runner import _register_default_governance_hooks

    start = time.monotonic()
    if not context.mode.mutations_allowed:
        detail = "Would register default project hooks via Governance.register_hooks."
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_09_HOOK_REGISTRATION,
                planned_status=CheckpointStatus.CREATED,
                detail=detail,
                start=start,
            )
        return make_result(
            nid.CP_09_HOOK_REGISTRATION,
            status=CheckpointStatus.PASS,
            detail=detail,
            reason=REASON_ALREADY_SATISFIED,
            start=start,
        )

    from pathlib import Path

    baseline_raw = context.run_state.hook_settings_baseline
    baseline: dict[Path, str] = {
        Path(str(path)): digest for path, digest in baseline_raw.items()
    }
    changed = _register_default_governance_hooks(
        context.config, context.project_root, before=baseline or None
    )
    for rel in changed:
        if rel not in context.run_state.created_files:
            context.run_state.created_files.append(rel)
    status = CheckpointStatus.CREATED if changed else CheckpointStatus.PASS
    detail = (
        f"Registered project hooks via Governance.register_hooks (materialised "
        f"{len(changed)} settings file(s))."
    )
    return make_result(
        nid.CP_09_HOOK_REGISTRATION, status=status, detail=detail, start=start
    )


__all__ = [
    "REASON_BINDING_CURRENT",
    "cp07_backend_registration",
    "cp08_skill_bindings",
    "cp09_hook_registration",
]
