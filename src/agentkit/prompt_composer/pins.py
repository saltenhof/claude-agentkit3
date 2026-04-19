"""Run-level prompt pin persistence and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.installer.paths import prompt_run_pin_path
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class PromptRunPin:
    run_id: str
    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_manifest_sha256: str


def load_prompt_run_pin(project_root: Path, run_id: str) -> PromptRunPin | None:
    """Load an existing run-level prompt pin if present."""

    path = prompt_run_pin_path(project_root, run_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PromptRunPin(
        run_id=str(data["run_id"]),
        prompt_bundle_id=str(data["prompt_bundle_id"]),
        prompt_bundle_version=str(data["prompt_bundle_version"]),
        prompt_manifest_sha256=str(data["prompt_manifest_sha256"]),
    )


def ensure_prompt_run_pin(
    project_root: Path,
    *,
    run_id: str,
    prompt_bundle_id: str,
    prompt_bundle_version: str,
    prompt_manifest_sha256: str,
) -> Path:
    """Persist or validate the canonical prompt pin for a run."""

    existing = load_prompt_run_pin(project_root, run_id)
    path = prompt_run_pin_path(project_root, run_id)
    if existing is not None:
        if (
            existing.prompt_bundle_id != prompt_bundle_id
            or existing.prompt_bundle_version != prompt_bundle_version
            or existing.prompt_manifest_sha256 != prompt_manifest_sha256
        ):
            raise ProjectError(
                "Prompt run pin mismatch",
                detail={
                    "path": str(path),
                    "run_id": run_id,
                    "expected": {
                        "prompt_bundle_id": existing.prompt_bundle_id,
                        "prompt_bundle_version": existing.prompt_bundle_version,
                        "prompt_manifest_sha256": existing.prompt_manifest_sha256,
                    },
                    "actual": {
                        "prompt_bundle_id": prompt_bundle_id,
                        "prompt_bundle_version": prompt_bundle_version,
                        "prompt_manifest_sha256": prompt_manifest_sha256,
                    },
                },
            )
        return path

    atomic_write_text(
        path,
        json.dumps(
            {
                "run_id": run_id,
                "prompt_bundle_id": prompt_bundle_id,
                "prompt_bundle_version": prompt_bundle_version,
                "prompt_manifest_sha256": prompt_manifest_sha256,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return path


__all__ = [
    "PromptRunPin",
    "ensure_prompt_run_pin",
    "load_prompt_run_pin",
]
