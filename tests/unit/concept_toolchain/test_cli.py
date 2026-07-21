"""CLI smoke tests for check.py (exit codes, envelope, human output)."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

from concept_toolchain.findings import CheckResult, Finding, exit_code, to_envelope
from tests.unit.concept_toolchain.conftest import CHECK_SCRIPT, concept_doc, write_doc, write_governance_config

if TYPE_CHECKING:
    from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def test_all_green_corpus_exits_zero(green_corpus: Path) -> None:
    completed = run_cli("--project-root", str(green_corpus), "all")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[frontmatter] OK" in completed.stdout
    assert "[references] OK" in completed.stdout
    assert "[formal] OK" in completed.stdout
    assert "[projection] OK" in completed.stdout


def test_findings_exit_one(green_corpus: Path) -> None:
    dead = concept_doc("DK-02", defers="defers_to:\n  - target: FK-99\n    scope: nowhere\n    reason: dead")
    write_doc(green_corpus, "concept/domain-design/02-dead.md", dead)
    completed = run_cli("--project-root", str(green_corpus), "frontmatter")
    assert completed.returncode == 1
    assert "[ERROR] frontmatter.defers-to" in completed.stdout


def test_usage_error_exits_three(green_corpus: Path) -> None:
    completed = run_cli("--project-root", str(green_corpus), "bogus-command")
    assert completed.returncode == 3


def test_missing_subcommand_exits_three(green_corpus: Path) -> None:
    completed = run_cli("--project-root", str(green_corpus))
    assert completed.returncode == 3


def test_missing_config_exits_two(tmp_path: Path) -> None:
    completed = run_cli("--project-root", str(tmp_path), "frontmatter")
    assert completed.returncode == 2
    assert "INCOMPLETE" in completed.stderr


def test_invalid_config_exits_three(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    config_path = tmp_path / "concept" / "_meta" / "concept-governance.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["unexpected_field"] = True
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    completed = run_cli("--project-root", str(tmp_path), "frontmatter")
    assert completed.returncode == 3
    assert "unexpected_field" in completed.stderr


def test_json_envelope_schema(green_corpus: Path) -> None:
    dead = concept_doc("DK-02", defers="defers_to:\n  - target: FK-99\n    scope: nowhere\n    reason: dead")
    write_doc(green_corpus, "concept/domain-design/02-dead.md", dead)
    completed = run_cli("--project-root", str(green_corpus), "--json", "all")
    assert completed.returncode == 1
    envelope = json.loads(completed.stdout)
    assert envelope["schema_version"] == "1.0.0"
    assert envelope["command"] == "all"
    assert envelope["check_set"] == ["frontmatter", "references", "formal", "projection"]
    assert envelope["complete"] is True
    assert envelope["findings"], "expected findings in the envelope"
    for finding in envelope["findings"]:
        assert set(finding) == {"check_id", "severity", "path", "locator", "message"}
        assert finding["severity"] == "ERROR"


def test_exit_code_precedence() -> None:
    finding = Finding(check_id="x", severity="ERROR", path="p", locator="l", message="m")
    assert exit_code([CheckResult(check_id="a")]) == 0
    assert exit_code([CheckResult(check_id="a", findings=[finding])]) == 1
    assert exit_code([CheckResult(check_id="a", complete=False), CheckResult(check_id="b", findings=[finding])]) == 2


def test_envelope_serialization_is_deterministic() -> None:
    first = Finding(check_id="b", severity="ERROR", path="z", locator="L2", message="m")
    second = Finding(check_id="a", severity="ERROR", path="a", locator="L1", message="m")
    envelope = to_envelope("all", ["a", "b"], [CheckResult(check_id="a", findings=[first, second])])
    findings = envelope["findings"]
    assert isinstance(findings, list)
    assert [item["path"] for item in findings] == ["a", "z"]
