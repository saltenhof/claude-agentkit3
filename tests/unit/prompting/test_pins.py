"""Tests for prompt run pin persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import ProjectError
from agentkit.prompt_composer.pins import (
    ensure_prompt_run_pin,
    load_prompt_run_pin,
)

if TYPE_CHECKING:
    from pathlib import Path


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
