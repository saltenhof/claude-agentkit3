"""Contract tests for the review-preflight prompt bundle entry."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from agentkit.backend.prompt_runtime.resources import MANIFEST_PATH, load_prompt_template


@pytest.mark.contract
def test_review_preflight_template_manifest_entry_hash_matches_resource() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    templates = manifest["templates"]
    entry = templates["review-preflight"]
    template_path = MANIFEST_PATH.parent.parent.parent / Path(entry["relpath"])
    content = template_path.read_text(encoding="utf-8")

    # Bumped 5 -> 6 on 2026-08-02: AG3-120 changed template BODIES without moving
    # the version key, so the immutable, version-keyed prompt-bundle store held
    # two different contents under "5" and every machine that had installed
    # before AG3-120 failed closed with "Canonical prompt bundle store collision".
    # A content change REQUIRES a version bump; this pin is what enforces it.
    assert manifest["bundle_version"] == "6"
    assert entry["relpath"] == "internal/prompts/review-preflight.md"
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == entry["sha256"]
    assert load_prompt_template("review-preflight") == content


@pytest.mark.contract
def test_review_preflight_sentinel_is_isolated_from_template_review_guard() -> None:
    template = load_prompt_template("review-preflight")

    assert "[PREFLIGHT:review-preflight-v1:{story_id}]" in template
    assert re.search(r"\[TEMPLATE:[^\]]+\]", template) is None
    assert re.search(r"\[SENTINEL:[^\]]+\]", template) is None
