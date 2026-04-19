"""Tests for prompt run pin persistence."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import ProjectError
from agentkit.prompt_composer.pins import (
    ensure_prompt_run_pin,
    initialize_prompt_run_pin,
    load_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_composer.resources import PROJECT_LOCK_RELPATH

if TYPE_CHECKING:
    from pathlib import Path


def _write_binding_lock(project_root: Path) -> None:
    bundle_dir = project_root / "bundle"
    bundle_dir.mkdir(parents=True)
    template_content = (
        "# Project Bound Prompt {story_id}\n"
        "[SENTINEL:worker-implementation-v1:{story_id}]\n"
    )
    (bundle_dir / "worker-implementation.md").write_text(
        template_content,
        encoding="utf-8",
    )
    manifest_text = json.dumps(
        {
            "bundle_id": "project-bound",
            "bundle_version": "99",
            "templates": {
                "worker-implementation": {
                    "relpath": "internal/prompts/worker-implementation.md",
                    "sha256": sha256(
                        template_content.encode("utf-8"),
                    ).hexdigest(),
                },
            },
        },
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True)
    (project_root / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "binding_root": "prompts",
                "bundle_root": str(bundle_dir),
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(
                    manifest_text.encode("utf-8"),
                ).hexdigest(),
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": sha256(
                            template_content.encode("utf-8"),
                        ).hexdigest(),
                    },
                },
            },
        ),
        encoding="utf-8",
    )


def test_ensure_prompt_run_pin_writes_pin_file(tmp_path: Path) -> None:
    path = ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    assert path.is_file()
    loaded = load_prompt_run_pin(tmp_path, "run-1")
    assert loaded is not None
    assert loaded.prompt_bundle_id == "bundle-a"
    assert loaded.prompt_bundle_version == "1"
    assert loaded.prompt_manifest_sha256 == "abc123"


def test_ensure_prompt_run_pin_is_idempotent(tmp_path: Path) -> None:
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    loaded = load_prompt_run_pin(tmp_path, "run-1")
    assert loaded is not None
    assert loaded.prompt_bundle_id == "bundle-a"


def test_ensure_prompt_run_pin_rejects_mid_run_drift(tmp_path: Path) -> None:
    ensure_prompt_run_pin(
        tmp_path,
        run_id="run-1",
        prompt_bundle_id="bundle-a",
        prompt_bundle_version="1",
        prompt_manifest_sha256="abc123",
    )

    with pytest.raises(ProjectError, match="Prompt run pin mismatch"):
        ensure_prompt_run_pin(
            tmp_path,
            run_id="run-1",
            prompt_bundle_id="bundle-a",
            prompt_bundle_version="2",
            prompt_manifest_sha256="def456",
        )


def test_initialize_prompt_run_pin_uses_project_binding(tmp_path: Path) -> None:
    _write_binding_lock(tmp_path)

    pin = initialize_prompt_run_pin(tmp_path, run_id="run-1")

    assert pin.prompt_bundle_id == "project-bound"
    assert pin.prompt_bundle_version == "99"
    assert len(pin.prompt_manifest_sha256) == 64


def test_resolve_run_prompt_binding_requires_existing_pin(tmp_path: Path) -> None:
    _write_binding_lock(tmp_path)

    with pytest.raises(ProjectError, match="Prompt run pin is missing"):
        resolve_run_prompt_binding(tmp_path, "run-1")


def test_resolve_run_prompt_binding_rejects_binding_drift(tmp_path: Path) -> None:
    _write_binding_lock(tmp_path)
    initialize_prompt_run_pin(tmp_path, run_id="run-1")

    lock = json.loads((tmp_path / PROJECT_LOCK_RELPATH).read_text(encoding="utf-8"))
    lock["bundle_version"] = "100"
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(lock),
        encoding="utf-8",
    )

    with pytest.raises(ProjectError, match="Prompt run pin mismatch"):
        resolve_run_prompt_binding(tmp_path, "run-1")
