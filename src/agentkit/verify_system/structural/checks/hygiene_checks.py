"""Code-hygiene checks (FK-27 §27.4.2 / FK-33 §33.3.2).

All three are MINOR (FK-27 §27.4.2): they scan the changed files for TODO/FIXME
markers, disabled tests and large commented-out code blocks.

The set of files to scan is sourced from INDEPENDENT system evidence (the real
``git diff`` changed files in ``ChangeEvidence.changed_files``) so the scan does
not depend on a worker-declared file list (FK-33 §33.5: prefer system evidence).
When the system evidence is unavailable (no git provider wired) the checks fall
back to the worker manifest's declared ``files`` / ``produced_files`` -- this is
permissible because hygiene findings are MINOR (Trust-C is allowed for
non-blocking findings, FK-33 §33.5.2), and it is at most additive. When neither
source yields files there is nothing to scan and the checks PASS.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from agentkit.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.core_types import Severity
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence

__all__ = [
    "check_hygiene_commented_code",
    "check_hygiene_disabled_tests",
    "check_hygiene_todo_fixme",
]

_WORKER_MANIFEST_FILE = "worker-manifest.json"
#: FK-27 §27.4.2 ``hygiene.todo_fixme`` markers.
_TODO_FIXME_RE = re.compile(r"\b(TODO|FIXME)\b")
#: FK-27 §27.4.2 ``hygiene.disabled_tests`` markers (Java + Python).
_DISABLED_TEST_RE = re.compile(
    r"@Disabled\b|@Ignore\b|@pytest\.mark\.skip\b|@unittest\.skip\b"
)
#: A "large" commented-out code block: >= this many consecutive comment lines
#: that look like code (FK-27 §27.4.2 ``hygiene.commented_code``).
_COMMENTED_BLOCK_MIN_LINES = 5
_PY_COMMENT_RE = re.compile(r"^\s*#")
_CODE_TOKEN_RE = re.compile(r"[=(){}\[\];]|(\b(def|class|return|import|if|for)\b)")


def _changed_files(story_dir: Path, evidence: ChangeEvidence | None) -> list[Path]:
    """Resolve changed files to scan: SYSTEM diff first, manifest as fallback.

    Prefers ``ChangeEvidence.changed_files`` (the real ``git diff`` set). Falls
    back to the worker manifest's declared files only when the system evidence is
    unavailable (permissible for the MINOR hygiene checks; additive only).
    """
    rels = (
        list(evidence.changed_files)
        if evidence is not None and evidence.available
        else _manifest_declared_files(story_dir)
    )
    files: list[Path] = []
    for entry in rels:
        candidate = story_dir / entry
        if candidate.is_file():
            files.append(candidate)
    return files


def _manifest_declared_files(story_dir: Path) -> list[str]:
    """Read the worker manifest's declared files (fallback only, fail-soft)."""
    path = story_dir / _WORKER_MANIFEST_FILE
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    if not isinstance(manifest, dict):
        return []
    raw = manifest.get("files")
    if raw is None:
        raw = manifest.get("produced_files")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, str)]


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def _finding(check: str, severity: Severity, message: str, file_path: Path) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
        file_path=str(file_path),
    )


def check_hygiene_todo_fixme(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence | None = None,
) -> Finding | None:
    """FK-27 §27.4.2 ``hygiene.todo_fixme``: no TODO/FIXME in changed files.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: MINOR).
        evidence: System change evidence (the ``git diff`` changed-file set);
            ``None`` falls back to the worker manifest (additive, MINOR).

    Returns:
        ``None`` on PASS; a MINOR finding at the first TODO/FIXME marker.
    """
    del ctx
    for file_path in _changed_files(story_dir, evidence):
        for lineno, line in enumerate(_read_lines(file_path), start=1):
            if _TODO_FIXME_RE.search(line):
                return Finding(
                    layer="structural",
                    check="hygiene.todo_fixme",
                    severity=severity,
                    message="TODO/FIXME marker in changed file (FK-27 §27.4.2)",
                    trust_class=TrustClass.SYSTEM,
                    file_path=str(file_path),
                    line_number=lineno,
                )
    return None


def check_hygiene_disabled_tests(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence | None = None,
) -> Finding | None:
    """FK-27 §27.4.2 ``hygiene.disabled_tests``: no disabled/skipped tests.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: MINOR).
        evidence: System change evidence (the ``git diff`` changed-file set);
            ``None`` falls back to the worker manifest (additive, MINOR).

    Returns:
        ``None`` on PASS; a MINOR finding at the first disabled-test marker.
    """
    del ctx
    for file_path in _changed_files(story_dir, evidence):
        for lineno, line in enumerate(_read_lines(file_path), start=1):
            if _DISABLED_TEST_RE.search(line):
                return Finding(
                    layer="structural",
                    check="hygiene.disabled_tests",
                    severity=severity,
                    message="disabled/skipped test marker in changed file "
                    "(FK-27 §27.4.2)",
                    trust_class=TrustClass.SYSTEM,
                    file_path=str(file_path),
                    line_number=lineno,
                )
    return None


def check_hygiene_commented_code(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence | None = None,
) -> Finding | None:
    """FK-27 §27.4.2 ``hygiene.commented_code``: no large commented code blocks.

    A block of >= ``_COMMENTED_BLOCK_MIN_LINES`` consecutive ``#`` comment
    lines that look like code (carry code tokens) is flagged.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: MINOR).
        evidence: System change evidence (the ``git diff`` changed-file set);
            ``None`` falls back to the worker manifest (additive, MINOR).

    Returns:
        ``None`` on PASS; a MINOR finding at the first large commented block.
    """
    del ctx
    for file_path in _changed_files(story_dir, evidence):
        finding = _scan_commented_block(file_path, severity)
        if finding is not None:
            return finding
    return None


def _scan_commented_block(file_path: Path, severity: Severity) -> Finding | None:
    """Return a finding for the first large commented-out code block, else None."""
    run_start = 0
    run_codey = 0
    for lineno, line in enumerate(_read_lines(file_path), start=1):
        if _PY_COMMENT_RE.match(line):
            if run_codey == 0:
                run_start = lineno
            if _CODE_TOKEN_RE.search(line):
                run_codey += 1
                if run_codey >= _COMMENTED_BLOCK_MIN_LINES:
                    return _finding(
                        "hygiene.commented_code", severity,
                        f"large commented-out code block starting at line "
                        f"{run_start} (FK-27 §27.4.2)",
                        file_path,
                    )
        else:
            run_codey = 0
    return None
