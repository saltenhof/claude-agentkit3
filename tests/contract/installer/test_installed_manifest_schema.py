"""Contract: install-manifest producer schema pinned 1:1 to the AG3-086 consumer.

The AG3-110 producer writes ``.installed-manifest.json``; the AG3-086 prompt-integrity
guard reads it (``governance/runner.py`` ``_installed_skill_proof`` /
``_MANIFEST_SKILL_PROOF_KEY``). This contract test asserts the producer output is read
NON-EMPTY by the REAL consumer reader (no shadow reader) and pins the top-level key name
+ string type, so producer and consumer can never silently diverge (FIX THE MODEL /
SINGLE SOURCE OF TRUTH). Pure in-memory — no Postgres, no installer run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.core_types.plane_artifact_names import (
    AGENT_SPAWN_SKILL_PROOF_KEY,
    INSTALLED_MANIFEST_FILENAME,
)
from agentkit.backend.governance.runner import (
    _MANIFEST_SKILL_PROOF_KEY,
    _installed_skill_proof,
)
from agentkit.backend.installer.installed_manifest import (
    SKILL_PROOF_KEY,
    build_installed_manifest,
)
from agentkit.backend.installer.paths import installed_manifest_path

if TYPE_CHECKING:
    from pathlib import Path


def _bundle(root: Path) -> Path:
    bundle = root / "execute-userstory"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text("# execute\n", encoding="utf-8")
    return bundle


def test_producer_key_matches_consumer_key() -> None:
    # The single contract anchor: the producer's top-level key is byte-identical to
    # the real consumer's ``_MANIFEST_SKILL_PROOF_KEY``.
    assert SKILL_PROOF_KEY == _MANIFEST_SKILL_PROOF_KEY
    assert SKILL_PROOF_KEY == AGENT_SPAWN_SKILL_PROOF_KEY == "agent_spawn_skill_proof"


def test_producer_filename_matches_consumer_path(tmp_path: Path) -> None:
    # The producer writes to exactly the path the consumer reads
    # (``project_root / ".installed-manifest.json"``).
    assert INSTALLED_MANIFEST_FILENAME == ".installed-manifest.json"
    assert installed_manifest_path(tmp_path) == tmp_path / INSTALLED_MANIFEST_FILENAME


def test_real_consumer_reads_producer_output(tmp_path: Path) -> None:
    # The REAL AG3-086 reader resolves the producer's token NON-EMPTY (no shadow reader).
    manifest = build_installed_manifest(
        tmp_path,
        prompt_template_digests={"worker": "aaa"},
        authorized_prompt_paths=["internal/prompts/worker.md"],
        skill_bundle_roots=[("execute-userstory", _bundle(tmp_path))],
    )
    installed_manifest_path(tmp_path).write_text(
        manifest.to_canonical_json(), encoding="utf-8"
    )

    resolved = _installed_skill_proof(tmp_path)
    assert resolved == manifest.agent_spawn_skill_proof
    assert resolved != ""


def test_consumer_fail_closed_without_manifest(tmp_path: Path) -> None:
    # FAIL-CLOSED: with no manifest the real reader returns "" (Stage-2 block upstream).
    assert _installed_skill_proof(tmp_path) == ""
