"""Every shipped JSON bundle template must load through the production loaders.

Placeholders (``<...>``) are replaced with schema-valid example values by a
small helper; an unreplaced placeholder or a loader issue fails the test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel
from concept_toolchain.config import load_governance_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from concept_toolchain.runmodel import Issue

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "src" / "agentkit" / "bundles" / "skill_bundles" / "concept-incubation-core" / "4.0.0" / "templates"

PLACEHOLDER_VALUES = {
    "<YYYY-MM-DD>": "2026-07-19",
    "<slug>": "mini",
    "<uuid8>": "ab12cd34",
    "<run_id>": "2026-07-19-mini-ab12cd34",
    "<commit-sha>": "a" * 40,
    "<iso-utc>": "2026-07-19T10:00:00Z",
    "<sha256>": "0" * 64,
    "<principal>": "orch.alice",
    "<opaque>": "sess-1",
    "<claude-code|codex>": "claude-code",
    "<model-id>": "model-x",
    "<short title>": "Run title",
    "<pid>": "worker-one",
    "<scope>": "sample-scope",
    "<why>": "reason",
    "<who>": "owner",
    "<path#anchor>": "concept/domain-design/01-sample.md#anchor",
    "<harness>": "claude-code",
    "<receipt_id>": "RCP-ab12cd34-0001",
    "<atom_id>": "ATM-ab12cd34-0001",
    "<anchor>": "sample-anchor",
    "<path>": "concept/technical-design/10_sample.md",
    "<reviewer-principal>": "rev.bob",
    "<reviewer-opaque>": "sess-review",
}


def materialize(name: str, tmp_path: Path) -> Path:
    text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    for placeholder, value in PLACEHOLDER_VALUES.items():
        text = text.replace(placeholder, value)
    assert "<" not in text, f"unreplaced placeholder in {name}: {text[text.index('<'):text.index('<') + 40]!r}"
    target = tmp_path / name
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


LOADERS: dict[str, Callable[[Path], tuple[object, list[Issue]]]] = {
    "RUN.json": runmodel.load_run_state,
    "LEASE.json": runmodel.load_lease,
    "ROUND.json": runmodel.load_round_state,
    "promotion-manifest.json": runmodel.load_promotion_manifest,
    "projection-manifest.json": runmodel.load_projection_manifest,
    "scope-lock.json": runmodel.load_scope_lock,
    "projection-receipt.json": runmodel.load_projection_receipt,
}


def test_all_json_templates_are_covered() -> None:
    shipped = {entry.name for entry in TEMPLATES_DIR.glob("*.json")}
    assert shipped == set(LOADERS) | {"concept-governance.json"}


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_template_loads_through_production_loader(name: str, tmp_path: Path) -> None:
    target = materialize(name, tmp_path)
    model, issues = LOADERS[name](target)
    assert issues == [], f"{name}: {[f'{issue.locator}: {issue.message}' for issue in issues]}"
    assert model is not None


def test_governance_template_loads_through_config_loader(tmp_path: Path) -> None:
    meta = tmp_path / "concept" / "_meta"
    meta.mkdir(parents=True)
    text = (TEMPLATES_DIR / "concept-governance.json").read_text(encoding="utf-8")
    (meta / "concept-governance.json").write_text(text, encoding="utf-8", newline="\n")
    config = load_governance_config(tmp_path)
    assert config.lock_backend == "filesystem"


def test_round_template_receipt_is_parser_valid(tmp_path: Path) -> None:
    """Regression: outcome received with receipt null was parser-invalid."""
    payload = json.loads(materialize("ROUND.json", tmp_path).read_text(encoding="utf-8"))
    participant = payload["participants"][0]
    assert participant["outcome"] == "received"
    assert isinstance(participant["receipt"], dict)
