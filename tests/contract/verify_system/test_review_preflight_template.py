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

    assert manifest["bundle_version"] == "5"
    assert entry["relpath"] == "internal/prompts/review-preflight.md"
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == entry["sha256"]
    assert load_prompt_template("review-preflight") == content


@pytest.mark.contract
def test_review_preflight_sentinel_is_isolated_from_template_review_guard() -> None:
    template = load_prompt_template("review-preflight")

    assert "[PREFLIGHT:review-preflight-v1:{story_id}]" in template
    assert re.search(r"\[TEMPLATE:[^\]]+\]", template) is None
    assert re.search(r"\[SENTINEL:[^\]]+\]", template) is None
