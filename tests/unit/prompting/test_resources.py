"""Tests for bundled prompt template resources."""

from __future__ import annotations

from agentkit.prompt_composer.resources import (
    MANIFEST_PATH,
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_template_path,
    prompt_template_relpath,
    prompt_template_sha256,
)


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
