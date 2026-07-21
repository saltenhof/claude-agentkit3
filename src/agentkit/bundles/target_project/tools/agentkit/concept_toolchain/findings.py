"""Finding model, JSON envelope, and exit-code policy (FK-78 section 78.14).

Exit codes: ``0`` PASS, ``1`` findings (ERROR), ``2`` missing prerequisites
or a declared INCOMPLETE partial run, ``3`` usage/configuration errors
(returned by the CLI layer, never by :func:`exit_code`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ENVELOPE_SCHEMA_VERSION = "1.0.0"

EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_INCOMPLETE = 2
EXIT_USAGE = 3


@dataclass(frozen=True)
class Finding:
    """One deterministic blocking finding. Severity is uniformly ERROR."""

    check_id: str
    severity: str
    path: str
    locator: str
    message: str


@dataclass
class CheckResult:
    """Result of one executed check.

    Attributes:
        check_id: Stable identifier of the executed check.
        findings: Blocking ERROR findings.
        complete: ``False`` when prerequisites were missing and the check
            could not run to completion (never for a fully executed check).
        incomplete_reason: Human-readable reason when ``complete`` is False.
        reports: Pre-rendered non-blocking report lines (e.g. baselined
            reference findings). Reports never enter the JSON envelope.
        summary: Short human-readable success summary.
    """

    check_id: str
    findings: list[Finding] = field(default_factory=list)
    complete: bool = True
    incomplete_reason: str | None = None
    reports: list[str] = field(default_factory=list)
    summary: str = ""


def to_envelope(command: str, check_set: list[str], results: Iterable[CheckResult]) -> dict[str, object]:
    """Serialize results into the FK-78 JSON envelope."""
    materialized = list(results)
    findings = sorted(
        (finding for result in materialized for finding in result.findings),
        key=lambda item: (item.path, item.locator, item.check_id, item.message),
    )
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "command": command,
        "check_set": list(check_set),
        "complete": all(result.complete for result in materialized),
        "findings": [
            {
                "check_id": finding.check_id,
                "severity": finding.severity,
                "path": finding.path,
                "locator": finding.locator,
                "message": finding.message,
            }
            for finding in findings
        ],
    }


def exit_code(results: Sequence[CheckResult]) -> int:
    """Map executed check results onto the FK-78 exit-code contract.

    Incompleteness dominates: a partial run never yields a clean PASS and
    its finding list is not authoritative, so it exits ``2`` even when
    findings were collected (the envelope still carries them).
    """
    if any(not result.complete for result in results):
        return EXIT_INCOMPLETE
    if any(result.findings for result in results):
        return EXIT_FINDINGS
    return EXIT_PASS


def error(check_id: str, path: str, locator: str, message: str) -> Finding:
    """Build an ERROR finding."""
    return Finding(check_id=check_id, severity="ERROR", path=path, locator=locator, message=message)
