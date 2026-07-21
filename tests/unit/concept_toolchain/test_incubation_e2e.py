"""End-to-end happy path: complete mini run through the real CLIs (FK-78).

Builds a full LIGHT_INCUBATION run from a green corpus (templates-shaped
artifacts), runs the semantic-gate mechanics (units, prepare, import) via
the mutating CLI, and then drives the read-only ``check.py`` through
``incubator``, ``promotion``, ``semantic-status``, ``projection`` and
``all --run`` — all with exit 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from tests.unit.concept_toolchain.conftest import CHECK_SCRIPT, TOOLS_DIR
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.requires_git

GATE_SCRIPT = TOOLS_DIR / "concept_toolchain" / "semantic_gate.py"


def run_cli(script: Path, project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--project-root", str(project_root), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def craft_receipt(fixture: RunFixture, gate_key: str) -> Path:
    pack_paths = sorted((fixture.run_dir / "semantic" / "requests").glob(f"{gate_key}-*.json"))
    assert len(pack_paths) == 1, pack_paths
    pack = json.loads(pack_paths[0].read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0.0",
        "gate": pack["gate"],
        "request_digest": pack["request_digest"],
        "model": "review-model",
        "principal_id": "rev.bob",
        "session_ref": f"sess-review-{gate_key}",
        "status": "passed",
        "findings": [],
        "chunk_digests": [chunk["digest"] for chunk in pack["chunks"]],
        "completed_at": "2026-07-19T11:00:00Z",
    }
    receipt_path = fixture.project_root / f"receipt-{gate_key}.json"
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return receipt_path


def test_full_mini_run_reaches_promotion_closure(green_corpus: Path) -> None:
    fixture = build_promotion_run(green_corpus, use_git=True)
    root = fixture.project_root

    for gate_key in ("w2", "w3"):
        prepared = run_cli(GATE_SCRIPT, root, "prepare", fixture.run_rel, *WRITER_ARGS, "--gate", gate_key)
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        receipt = craft_receipt(fixture, gate_key)
        imported = run_cli(GATE_SCRIPT, root, "import", fixture.run_rel, *WRITER_ARGS, str(receipt))
        assert imported.returncode == 0, imported.stdout + imported.stderr

    for command in ("incubator", "promotion", "semantic-status"):
        completed = run_cli(CHECK_SCRIPT, root, command, fixture.run_rel)
        assert completed.returncode == 0, f"{command}:\n{completed.stdout}\n{completed.stderr}"
        assert f"[{command}] OK" in completed.stdout

    projection = run_cli(CHECK_SCRIPT, root, "projection")
    assert projection.returncode == 0, projection.stdout + projection.stderr

    everything = run_cli(CHECK_SCRIPT, root, "--json", "all", "--run", fixture.run_rel)
    assert everything.returncode == 0, everything.stdout + everything.stderr
    envelope = json.loads(everything.stdout)
    assert envelope["complete"] is True
    assert envelope["findings"] == []
    assert envelope["check_set"] == [
        "frontmatter",
        "references",
        "formal",
        "projection",
        "incubator",
        "promotion",
        "semantic-status",
    ]
