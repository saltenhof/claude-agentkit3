"""PromptRuntime -- top-surface facade of the prompt-runtime BC.

bc-cut-decisions §BC 10 (``exposure: top``). This is the only admissible
entry surface for other BCs:

- ``verify_system.LlmEvaluator`` resolves evaluator prompts exclusively via
  ``materialize_prompt`` (FK-44 §44.4.2).
- ``installation-and-bootstrap`` (FK-50 §50.5) updates the project binding
  exclusively via ``update_binding``.

The class is a thin, typed facade over the existing subs
(``composer`` = materialization, ``pins`` = bundle_pinning,
``resources`` = bundle_store) and the ``audit`` module. It does not hold a
second source of truth; the lock and run pins remain the authoritative
state. Audit records are persisted via the injected
``artifacts.ArtifactManager`` (FK-44 §44.6, FK-71).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.installer.paths import (
    prompt_bundle_lock_path,
    prompt_bundle_store_dir,
)
from agentkit.prompt_runtime.audit import (
    PromptAuditHash,
    build_prompt_audit_envelope,
    compute_prompt_audit_hash,
    empty_render_input_digest,
    persist_prompt_audit,
)
from agentkit.prompt_runtime.composer import (
    ComposeConfig,
    StaticMaterializedPromptInstance,
    compose_named_prompt,
    materialize_static_prompt_instance,
    write_prompt_instance,
)
from agentkit.prompt_runtime.pins import (
    PromptRunPin,
    initialize_prompt_run_pin,
    load_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_runtime.resources import (
    prompt_template_relpath_from_binding,
    reject_stale_local_prompt_cache,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager, ArtifactReference
    from agentkit.story_context_manager.models import StoryContext


def build_prompt_bundle_lock_content(
    *,
    bundle_id: str,
    bundle_version: str,
    manifest_file: str,
    manifest_text: str,
) -> str:
    """Build the canonical ``prompt-bundle.lock.json`` content (FK-44 §44.2).

    Single source of truth for the lock layout, shared by
    ``PromptRuntime.update_binding`` and the installer (FK-50 §50.5) so the
    binding is composed in exactly one place.

    Args:
        bundle_id: Bound bundle identifier.
        bundle_version: Bound bundle version.
        manifest_file: Manifest filename inside the bundle root.
        manifest_text: Raw manifest bytes as text (digest is computed here).

    Returns:
        Deterministic JSON text (sorted keys, trailing newline).

    Raises:
        ProjectError: If the manifest is not a JSON object or lacks a
            templates mapping (fail-closed).
    """
    manifest = json.loads(manifest_text)
    if not isinstance(manifest, dict):
        raise ProjectError(
            "Prompt bundle manifest must be a JSON object",
            detail={"bundle_id": bundle_id, "bundle_version": bundle_version},
        )
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise ProjectError(
            "Prompt bundle manifest is missing a templates mapping",
            detail={"bundle_id": bundle_id, "bundle_version": bundle_version},
        )
    manifest_sha256 = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    lock_data = {
        "bundle_id": bundle_id,
        "bundle_version": bundle_version,
        "binding_root": "prompts",
        "manifest_file": manifest_file,
        "manifest_sha256": manifest_sha256,
        "templates": templates,
    }
    return json.dumps(lock_data, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class PromptInstance:
    """Run-scoped prompt instance plus its persisted audit reference.

    Maps to the formal entity ``prompt-runtime.entity.prompt-instance``.

    Attributes:
        prompt_path: The materialized prompt file agents consume.
        render_mode: ``"static"`` or ``"rendered"`` (FK-44 §44.4.1).
        audit_hash: The digest triple proving template and output bytes.
        audit_reference: ArtifactManager reference of the audit record.
    """

    prompt_path: Path
    render_mode: str
    audit_hash: PromptAuditHash
    audit_reference: ArtifactReference


class PromptRuntime:
    """Top-surface of the prompt-runtime BC (bc-cut-decisions §BC 10).

    Args:
        project_root: Project root holding ``.agentkit/``.
        artifact_manager: Injected ``ArtifactManager`` -- the only
            admissible audit persistence layer (FK-44 §44.6, FK-71).
            Optional: binding-only callers (e.g. the installer via
            ``update_binding``, FK-50 §50.5) do not need it. It is
            **required** for ``materialize_prompt``; calling that without a
            manager is fail-closed.
    """

    def __init__(
        self,
        project_root: Path,
        artifact_manager: ArtifactManager | None = None,
    ) -> None:
        self._project_root = project_root
        self._artifact_manager = artifact_manager

    def _require_artifact_manager(self) -> ArtifactManager:
        if self._artifact_manager is None:
            raise ProjectError(
                "PromptRuntime requires an ArtifactManager to persist "
                "prompt-audit records (FK-44 §44.6)",
                detail={"project_root": str(self._project_root)},
            )
        return self._artifact_manager

    # ------------------------------------------------------------------
    # create_run_pin (FK-44 §44.3, command pin-run-prompt-bundle)
    # ------------------------------------------------------------------

    def create_run_pin(self, run_id: str) -> PromptRunPin:
        """Resolve the current project binding and pin it onto the run.

        Write-once per run identity; a re-pin with diverging coordinates
        is rejected fail-closed by the underlying pin store.

        Args:
            run_id: Run identifier.

        Returns:
            The persisted ``PromptRunPin``.
        """
        return initialize_prompt_run_pin(self._project_root, run_id=run_id)

    # ------------------------------------------------------------------
    # update_binding (FK-44 §44.3 / FK-50 §50.5)
    # ------------------------------------------------------------------

    def update_binding(self, bundle_id: str, version: str) -> None:
        """Update the project prompt binding for *future* runs (FK-44 §44.3).

        Resolves the bundle's manifest from the installer-managed central
        store and rewrites the lock-authoritative
        ``.agentkit/config/prompt-bundle.lock.json``. Already pinned active
        runs are unaffected (C2 invariant
        ``binding_changes_affect_only_future_runs``).

        Sole caller is ``installation-and-bootstrap`` (FK-50 §50.5).

        Args:
            bundle_id: New bundle identifier.
            version: New bundle version.

        Raises:
            ProjectError: If the central bundle/manifest is missing or
                malformed (fail-closed).
        """
        bundle_root = prompt_bundle_store_dir(bundle_id, version)
        manifest_file = "manifest.json"
        manifest_path = bundle_root / manifest_file
        if not manifest_path.is_file():
            raise ProjectError(
                f"Cannot bind missing prompt bundle manifest: {manifest_path}",
                detail={
                    "bundle_id": bundle_id,
                    "bundle_version": version,
                    "manifest_path": str(manifest_path),
                },
            )
        manifest_text = manifest_path.read_text(encoding="utf-8")
        content = build_prompt_bundle_lock_content(
            bundle_id=bundle_id,
            bundle_version=version,
            manifest_file=manifest_file,
            manifest_text=manifest_text,
        )
        lock_path = prompt_bundle_lock_path(self._project_root)
        atomic_write_text(lock_path, content)

    # ------------------------------------------------------------------
    # compute_audit_hash (FK-44 §44.6)
    # ------------------------------------------------------------------

    def compute_audit_hash(
        self,
        *,
        template_text: str,
        render_inputs: dict[str, str],
        output_text: str,
    ) -> PromptAuditHash:
        """Compute the deterministic ``PromptAuditHash`` (FK-44 §44.6).

        Args:
            template_text: Canonical template bytes as text.
            render_inputs: Render input map (empty for static prompts).
            output_text: Final materialized bytes as text.

        Returns:
            The frozen ``PromptAuditHash``.
        """
        return compute_prompt_audit_hash(
            template_text=template_text,
            render_inputs=render_inputs,
            output_text=output_text,
        )

    # ------------------------------------------------------------------
    # materialize_prompt (FK-44 §44.4.1, §44.4.2, §44.6)
    # ------------------------------------------------------------------

    def materialize_prompt(
        self,
        ctx: StoryContext,
        template_name: str,
        config: ComposeConfig,
        *,
        run_id: str,
        invocation_id: str,
        render_mode: str = "rendered",
        attempt: int = 1,
    ) -> PromptInstance:
        """Materialize a run-scoped agent prompt instance and persist its audit.

        Dynamic prompts (``render_mode="rendered"``) are rendered from the
        pinned bundle and written to the run-scoped path; static prompts
        (``render_mode="static"``) are projected from the pinned central
        bundle file via hardlink/symlink/copy (FK-44 §44.4.1). In both
        cases a ``PromptAuditHash``-bearing record is persisted via the
        injected ``ArtifactManager`` (FK-44 §44.6) -- never as a loose JSON
        file standing in as audit truth.

        Args:
            ctx: Story context (carries ``project_root``, ``story_id``).
            template_name: Logical template name.
            config: Compose configuration (story type, spawn reason, ...).
            run_id: Active run id (pinned before first invocation).
            invocation_id: Spawn/invocation id.
            render_mode: ``"rendered"`` (default) or ``"static"``.
            attempt: Audit attempt counter (>= 1).

        Returns:
            A ``PromptInstance`` with the path, mode, digests and audit ref.

        Raises:
            ProjectError: On missing pin/bundle, stale local cache, or an
                unknown ``render_mode`` (fail-closed).
        """
        if render_mode == "static":
            return self._materialize_static(
                run_id=run_id,
                invocation_id=invocation_id,
                template_name=template_name,
                story_id=ctx.story_id,
                attempt=attempt,
            )
        if render_mode == "rendered":
            return self._materialize_rendered(
                ctx=ctx,
                template_name=template_name,
                config=config,
                run_id=run_id,
                invocation_id=invocation_id,
                attempt=attempt,
            )
        raise ProjectError(
            f"Unknown render_mode: {render_mode!r}",
            detail={"render_mode": render_mode, "run_id": run_id},
        )

    def _materialize_rendered(
        self,
        *,
        ctx: StoryContext,
        template_name: str,
        config: ComposeConfig,
        run_id: str,
        invocation_id: str,
        attempt: int,
    ) -> PromptInstance:
        prompt = compose_named_prompt(ctx, template_name, config, run_id=run_id)
        materialized = write_prompt_instance(
            prompt,
            self._project_root,
            run_id=run_id,
            invocation_id=invocation_id,
        )
        audit_hash = PromptAuditHash(
            template_sha256=prompt.template_sha256,
            render_input_digest=prompt.render_input_digest,
            output_sha256=prompt.output_sha256,
        )
        artifact_path = materialized.prompt_path.relative_to(
            self._project_root,
        ).as_posix()
        reference = self._persist_audit(
            story_id=prompt.story_id,
            run_id=run_id,
            invocation_id=invocation_id,
            attempt=attempt,
            logical_prompt_id=prompt.logical_prompt_id,
            template_relpath=prompt.template_relpath,
            prompt_bundle_version=prompt.prompt_bundle_version,
            prompt_bundle_manifest_digest=prompt.prompt_manifest_sha256,
            render_mode="rendered",
            audit_hash=audit_hash,
            artifact_path=artifact_path,
        )
        return PromptInstance(
            prompt_path=materialized.prompt_path,
            render_mode="rendered",
            audit_hash=audit_hash,
            audit_reference=reference,
        )

    def _materialize_static(
        self,
        *,
        run_id: str,
        invocation_id: str,
        template_name: str,
        story_id: str,
        attempt: int,
    ) -> PromptInstance:
        static: StaticMaterializedPromptInstance = (
            materialize_static_prompt_instance(
                self._project_root,
                run_id=run_id,
                invocation_id=invocation_id,
                template_name=template_name,
            )
        )
        binding = resolve_run_prompt_binding(self._project_root, run_id)
        template_relpath = prompt_template_relpath_from_binding(
            template_name,
            binding,
        )
        # Static projection: the audit digests come from the projected file's
        # RAW bytes (computed in the composer via read_bytes), never from a
        # re-decode/re-encode round-trip -- so output_sha256 faithfully
        # reflects the bytes on disk (FK-44 §44.6, byte reproducibility).
        # template_sha256 is the verified pinned-template digest; the
        # render-input digest is the empty-map digest (no rendering occurred).
        audit_hash = PromptAuditHash(
            template_sha256=static.template_sha256,
            render_input_digest=empty_render_input_digest(),
            output_sha256=static.output_sha256,
        )
        artifact_path = static.prompt_path.relative_to(
            self._project_root,
        ).as_posix()
        reference = self._persist_audit(
            story_id=story_id,
            run_id=run_id,
            invocation_id=invocation_id,
            attempt=attempt,
            logical_prompt_id=f"prompt.{template_name}",
            template_relpath=template_relpath,
            prompt_bundle_version=binding.bundle_version,
            prompt_bundle_manifest_digest=binding.manifest_sha256,
            render_mode="static",
            audit_hash=audit_hash,
            artifact_path=artifact_path,
        )
        return PromptInstance(
            prompt_path=static.prompt_path,
            render_mode="static",
            audit_hash=audit_hash,
            audit_reference=reference,
        )

    def _persist_audit(
        self,
        *,
        story_id: str,
        run_id: str,
        invocation_id: str,
        attempt: int,
        logical_prompt_id: str,
        template_relpath: str,
        prompt_bundle_version: str,
        prompt_bundle_manifest_digest: str,
        render_mode: str,
        audit_hash: PromptAuditHash,
        artifact_path: str,
    ) -> ArtifactReference:
        envelope = build_prompt_audit_envelope(
            story_id=story_id,
            run_id=run_id,
            invocation_id=invocation_id,
            attempt=attempt,
            logical_prompt_id=logical_prompt_id,
            template_relpath=template_relpath,
            prompt_bundle_version=prompt_bundle_version,
            prompt_bundle_manifest_digest=prompt_bundle_manifest_digest,
            render_mode=render_mode,
            audit_hash=audit_hash,
            artifact_path=artifact_path,
        )
        return persist_prompt_audit(self._require_artifact_manager(), envelope)

    # ------------------------------------------------------------------
    # reject_stale_local_prompt_cache (FK-44 §44.5)
    # ------------------------------------------------------------------

    def reject_stale_local_prompt_cache(
        self,
        *,
        run_id: str,
        local_prompt_path: Path,
        template_name: str,
    ) -> None:
        """Reject a stale mutable project-local prompt copy (FK-44 §44.5).

        Resolves the pin-authoritative bundle for the run and rejects a
        project-local prompt file that diverges from the bound bundle
        template (invariant
        ``project_local_prompt_copy_is_never_authoritative``).

        Args:
            run_id: Active run id.
            local_prompt_path: Project-local prompt file to check.
            template_name: Logical template name.

        Raises:
            ProjectError: If the local file is a stale cache (fail-closed).
        """
        binding = resolve_run_prompt_binding(self._project_root, run_id)
        # Pin-authoritative relpath (C2): the canonical template path is read
        # from the pin-resolved binding, not the rebound project lock, so the
        # stale-cache check compares against the pinned bundle template.
        template_relpath = prompt_template_relpath_from_binding(
            template_name,
            binding,
        )
        reject_stale_local_prompt_cache(
            self._project_root,
            binding=binding,
            local_prompt_path=local_prompt_path,
            template_relpath=template_relpath,
        )

    def load_run_pin(self, run_id: str) -> PromptRunPin | None:
        """Load an existing run pin if present (read-only helper)."""
        return load_prompt_run_pin(self._project_root, run_id)


__all__ = [
    "PromptInstance",
    "PromptRuntime",
    "build_prompt_bundle_lock_content",
]
