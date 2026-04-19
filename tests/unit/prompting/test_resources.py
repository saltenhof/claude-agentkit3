"""Tests for bundled prompt template resources."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import ProjectError
from agentkit.prompt_composer.resources import (
    MANIFEST_PATH,
    PROJECT_LOCK_RELPATH,
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_manifest_sha256,
    prompt_template_path,
    prompt_template_relpath,
    prompt_template_sha256,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_prompt_manifest_exists() -> None:
    assert MANIFEST_PATH.is_file()


def test_prompt_manifest_exposes_bundle_identity() -> None:
    assert prompt_bundle_id() == "internal-bootstrap-prompts"
    assert prompt_bundle_version() == "1"
    assert len(prompt_manifest_sha256()) == 64


def test_prompt_template_path_points_to_resource_file() -> None:
    path = prompt_template_path("worker-implementation")
    assert path.name == "worker-implementation.md"
    assert path.is_file()


def test_prompt_template_relpath_is_bundle_relative() -> None:
    relpath = prompt_template_relpath("worker-implementation")
    assert relpath == "internal/prompts/worker-implementation.md"


def test_prompt_template_sha256_is_stable_hex_digest() -> None:
    digest = prompt_template_sha256("worker-implementation")
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_load_prompt_template_reads_utf8_content() -> None:
    content = load_prompt_template("worker-implementation")
    assert content.startswith("# Worker-Prompt: Implementation Story {story_id}")


def test_project_root_requires_explicit_prompt_binding_lock(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="Prompt bundle lock is missing"):
        prompt_bundle_id(tmp_path)


def test_project_root_binding_is_preferred(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    content = (
        "# Project Bound Prompt {story_id}\n"
        "[SENTINEL:worker-implementation-v1:{story_id}]\n"
    )
    (bundle_dir / "worker-implementation.md").write_text(
        content,
        encoding="utf-8",
    )
    digest = prompt_template_sha256("worker-implementation")
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": digest,
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    lock_dir = tmp_path / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True)
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "binding_root": "prompts",
                "bundle_root": str(bundle_dir),
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(
                    (bundle_dir / "manifest.json")
                    .read_text(encoding="utf-8")
                    .encode("utf-8"),
                ).hexdigest(),
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": digest,
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    assert prompt_bundle_id(tmp_path) == "project-bound"
    assert prompt_bundle_version(tmp_path) == "99"
    assert len(prompt_manifest_sha256(tmp_path)) == 64
    assert prompt_template_path(
        "worker-implementation",
        project_root=tmp_path,
    ) == (bundle_dir / "worker-implementation.md")


def test_project_binding_lock_detects_manifest_drift(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "worker-implementation.md").write_text(
        "# drifted\n[SENTINEL:worker-implementation-v1:{story_id}]\n",
        encoding="utf-8",
    )
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": "deadbeef",
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    lock_dir = tmp_path / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True)
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "bundle_root": str(bundle_dir),
                "manifest_file": "manifest.json",
                "manifest_sha256": "deadbeef",
                "templates": {
                    "worker-implementation": {
                        "relpath": "internal/prompts/worker-implementation.md",
                        "sha256": "deadbeef",
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    try:
        prompt_bundle_id(tmp_path)
    except ProjectError as exc:
        assert "digest mismatch" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected prompt bundle lock validation to fail")
