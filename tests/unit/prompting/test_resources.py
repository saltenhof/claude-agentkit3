"""Tests for bundled prompt template resources."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.prompt_composer.resources import (
    MANIFEST_PATH,
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
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


def test_project_root_binding_is_preferred(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    content = (
        "# Project Bound Prompt {story_id}\n"
        "[SENTINEL:worker-implementation-v1:{story_id}]\n"
    )
    (prompts_dir / "worker-implementation.md").write_text(
        content,
        encoding="utf-8",
    )
    digest = prompt_template_sha256("worker-implementation")
    (prompts_dir / "manifest.json").write_text(
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

    assert prompt_bundle_id(tmp_path) == "project-bound"
    assert prompt_bundle_version(tmp_path) == "99"
    assert prompt_template_path(
        "worker-implementation",
        project_root=tmp_path,
    ) == (prompts_dir / "worker-implementation.md")
