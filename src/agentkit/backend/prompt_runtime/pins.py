"""Run-level prompt pin persistence and validation.

Owner: ``bundle_pinning`` sub of the prompt-runtime BC (bc-cut-decisions
§BC 10). Materializes ``RunPromptPin`` instances under
``.agentkit/manifests/prompt-pins/{run_id}.json`` and resolves the
pin-authoritative bundle for an active run.

C2 invariant (FK-44 §44.3 / formal.prompt-runtime.invariants
``binding_changes_affect_only_future_runs``): once a run is pinned, the
run pin is the authority. A later legitimate ``update_binding`` on the
project lock affects only future runs; the active run keeps resolving
its pinned bundle from the central store. Only genuine corruption (the
pinned bundle/manifest is missing or its digest diverges from the pin)
is fail-closed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.paths import prompt_run_pin_path
from agentkit.backend.prompt_runtime.resources import (
    PROJECT_LOCK_RELPATH,
    PromptBundleBinding,
    resolve_pinned_prompt_binding,
    resolve_project_prompt_binding,
)
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

PROMPT_RUN_PIN_MISMATCH = "Prompt run pin mismatch"

#: Default manifest filename when a legacy pin omits ``prompt_manifest_file``.
_DEFAULT_MANIFEST_FILE = "manifest.json"


class PromptRunPin(BaseModel):
    """Pin record for an active run (Pydantic v2; FK-44 §44.3).

    Maps to the formal entity ``prompt-runtime.entity.run-prompt-pin``.
    ``resolved_prompt_bundle_version`` and
    ``resolved_prompt_bundle_manifest_digest`` are exposed as read-only
    aliases over the wire-stable field names.

    Attributes:
        run_id: Run identifier (identity key).
        project_key: Stable technical key of the owning project
            (cross-reference to the formal ``project-prompt-binding``
            entity). Best-effort: resolved from the canonical project config
            when present, ``None`` for bare/bootstrap fixtures without one.
        prompt_bundle_id: Pinned bundle identifier.
        prompt_bundle_version: Pinned bundle version
            (``resolved_prompt_bundle_version``).
        prompt_manifest_sha256: Pinned manifest digest
            (``resolved_prompt_bundle_manifest_digest``).
        prompt_manifest_file: Manifest filename inside the bundle root.
        pinned_at: UTC timestamp the pin was first written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    project_key: str | None = None
    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_manifest_sha256: str
    prompt_manifest_file: str = _DEFAULT_MANIFEST_FILE
    pinned_at: datetime

    @property
    def resolved_prompt_bundle_version(self) -> str:
        """Formal-entity alias for the pinned bundle version."""
        return self.prompt_bundle_version

    @property
    def resolved_prompt_bundle_manifest_digest(self) -> str:
        """Formal-entity alias for the pinned manifest digest."""
        return self.prompt_manifest_sha256


def _resolve_project_key(project_root: Path) -> str | None:
    """Resolve the owning project_key from the canonical project config.

    Best-effort: returns ``None`` when no validated project config exists
    (bare/bootstrap fixtures). Reads the single canonical config source -- it
    does NOT introduce a second project-key truth.
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import ConfigError

    try:
        return load_project_config(project_root).project_key
    except ConfigError:
        return None


def initialize_prompt_run_pin(project_root: Path, *, run_id: str) -> PromptRunPin:
    """Resolve the current project binding and persist the canonical run pin."""

    binding = resolve_project_prompt_binding(project_root)
    manifest_file = binding.manifest_path.name
    ensure_prompt_run_pin(
        project_root,
        run_id=run_id,
        project_key=_resolve_project_key(project_root),
        prompt_bundle_id=binding.bundle_id,
        prompt_bundle_version=binding.bundle_version,
        prompt_manifest_sha256=binding.manifest_sha256,
        prompt_manifest_file=manifest_file,
    )
    pin = load_prompt_run_pin(project_root, run_id)
    if pin is None:  # pragma: no cover
        raise ProjectError(
            "Prompt run pin could not be loaded after initialization",
            detail={"run_id": run_id},
        )
    return pin


def ensure_run_prompt_pin_present(project_root: Path, *, run_id: str) -> PromptRunPin:
    """Idempotently ensure a run pin exists, without re-validating it.

    Create-if-absent only: if a pin for ``run_id`` already exists it is
    returned as-is and **never** compared against the current project lock.
    This is the consumer-side entry (e.g. the verify prompt-audit path,
    bc-cut-decisions §BC 10) -- it must not trip a spurious
    ``PROMPT_RUN_PIN_MISMATCH`` after a legitimate ``update_binding`` on the
    project lock (C2 invariant ``binding_changes_affect_only_future_runs``,
    FK-44 §44.3). Only when no pin exists yet is the current project binding
    resolved and pinned.

    Args:
        project_root: Project root holding ``.agentkit/``.
        run_id: Active run identifier.

    Returns:
        The existing or freshly created ``PromptRunPin``.
    """

    existing = load_prompt_run_pin(project_root, run_id)
    if existing is not None:
        return existing
    return initialize_prompt_run_pin(project_root, run_id=run_id)


def load_prompt_run_pin(project_root: Path, run_id: str) -> PromptRunPin | None:
    """Load an existing run-level prompt pin if present."""

    path = prompt_run_pin_path(project_root, run_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    pinned_at_raw = data.get("pinned_at")
    pinned_at = (
        datetime.fromisoformat(str(pinned_at_raw))
        if pinned_at_raw is not None
        else datetime.now(tz=UTC)
    )
    project_key_raw = data.get("project_key")
    return PromptRunPin(
        run_id=str(data["run_id"]),
        project_key=(
            str(project_key_raw) if project_key_raw is not None else None
        ),
        prompt_bundle_id=str(data["prompt_bundle_id"]),
        prompt_bundle_version=str(data["prompt_bundle_version"]),
        prompt_manifest_sha256=str(data["prompt_manifest_sha256"]),
        prompt_manifest_file=str(
            data.get("prompt_manifest_file", _DEFAULT_MANIFEST_FILE),
        ),
        pinned_at=pinned_at,
    )


def ensure_prompt_run_pin(
    project_root: Path,
    *,
    run_id: str,
    prompt_bundle_id: str,
    prompt_bundle_version: str,
    prompt_manifest_sha256: str,
    prompt_manifest_file: str = _DEFAULT_MANIFEST_FILE,
    project_key: str | None = None,
) -> Path:
    """Persist or validate the canonical prompt pin for a run.

    The pin is write-once per run identity. A second call with diverging
    bundle coordinates for the same ``run_id`` is mid-run pin corruption
    and is rejected fail-closed.
    """

    existing = load_prompt_run_pin(project_root, run_id)
    path = prompt_run_pin_path(project_root, run_id)
    if existing is not None:
        if (
            existing.prompt_bundle_id != prompt_bundle_id
            or existing.prompt_bundle_version != prompt_bundle_version
            or existing.prompt_manifest_sha256 != prompt_manifest_sha256
        ):
            _raise_prompt_run_pin_mismatch(
                path=path,
                run_id=run_id,
                expected=_pin_detail(
                    prompt_bundle_id=existing.prompt_bundle_id,
                    prompt_bundle_version=existing.prompt_bundle_version,
                    prompt_manifest_sha256=existing.prompt_manifest_sha256,
                ),
                actual=_pin_detail(
                    prompt_bundle_id=prompt_bundle_id,
                    prompt_bundle_version=prompt_bundle_version,
                    prompt_manifest_sha256=prompt_manifest_sha256,
                ),
            )
        return path

    pin_data: dict[str, object] = {
        "run_id": run_id,
        "prompt_bundle_id": prompt_bundle_id,
        "prompt_bundle_version": prompt_bundle_version,
        "prompt_manifest_sha256": prompt_manifest_sha256,
        "prompt_manifest_file": prompt_manifest_file,
        "pinned_at": datetime.now(tz=UTC).isoformat(),
    }
    if project_key is not None:
        pin_data["project_key"] = project_key
    atomic_write_text(
        path,
        json.dumps(pin_data, indent=2, sort_keys=True) + "\n",
    )
    return path


def resolve_run_prompt_binding(project_root: Path, run_id: str) -> PromptBundleBinding:
    """Resolve the active run's prompt binding via the persisted run pin.

    The run pin is the authority (FK-44 §44.3). The pinned bundle is
    resolved directly from the installer-managed central store using the
    pinned ``bundle_id``/``bundle_version``. A later legitimate rebind of
    the project lock does **not** affect this resolution (C2 invariant
    ``binding_changes_affect_only_future_runs``).

    Args:
        project_root: Project root.
        run_id: Active run identifier.

    Returns:
        The pin-authoritative ``PromptBundleBinding``.

    Raises:
        ProjectError: If the run pin is missing, or the pinned bundle /
            manifest is missing or its digest diverges from the pin
            (genuine corruption, fail-closed).
    """

    pin = load_prompt_run_pin(project_root, run_id)
    if pin is None:
        raise ProjectError(
            "Prompt run pin is missing",
            detail={"path": str(prompt_run_pin_path(project_root, run_id))},
        )

    return resolve_pinned_prompt_binding(
        project_root,
        bundle_id=pin.prompt_bundle_id,
        bundle_version=pin.prompt_bundle_version,
        manifest_file=pin.prompt_manifest_file,
        expected_manifest_sha256=pin.prompt_manifest_sha256,
    )


def _pin_detail(
    *,
    prompt_bundle_id: str,
    prompt_bundle_version: str,
    prompt_manifest_sha256: str,
) -> dict[str, str]:
    return {
        "prompt_bundle_id": prompt_bundle_id,
        "prompt_bundle_version": prompt_bundle_version,
        "prompt_manifest_sha256": prompt_manifest_sha256,
    }


def _raise_prompt_run_pin_mismatch(
    *,
    path: Path,
    run_id: str,
    expected: dict[str, str],
    actual: dict[str, str],
) -> None:
    raise ProjectError(
        PROMPT_RUN_PIN_MISMATCH,
        detail={
            "path": str(path),
            "run_id": run_id,
            "expected": expected,
            "actual": actual,
        },
    )


__all__ = [
    "PROJECT_LOCK_RELPATH",
    "PromptRunPin",
    "ensure_prompt_run_pin",
    "ensure_run_prompt_pin_present",
    "initialize_prompt_run_pin",
    "load_prompt_run_pin",
    "resolve_run_prompt_binding",
]
