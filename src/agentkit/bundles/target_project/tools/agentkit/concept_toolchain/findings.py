"""Finding model, JSON envelope, and exit-code policy (FK-78 section 78.14).

Exit codes: ``0`` PASS, ``1`` findings (ERROR), ``2`` missing prerequisites
or a declared INCOMPLETE partial run, ``3`` usage/configuration errors
(returned by the CLI layer, never by :func:`exit_code`), ``4`` the work is
settled but an owed cleanup effect did not happen (mutating CLIs only, see
:func:`exit_code_with_owed_effect`).
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

#: The mutation is settled but an owed cleanup effect did not happen, so a
#: file stays behind and blocks every further writer. Its own code, because
#: "work done, cleanup failed" is neither a validation finding (``1`` — the
#: content is wrong) nor a missing prerequisite (``2`` — nothing ran): a
#: consumer must be able to tell the three apart WITHOUT parsing a message.
#: Read-only checks never return it; only a mutating CLI owes effects.
EXIT_OWED_EFFECT = 4


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


def exit_code_with_owed_effect(results: Sequence[CheckResult], *, owed_effect_failed: bool) -> int:
    """Rank the outcomes of a mutating run; teardown never masks the work.

    Precedence, strongest first:

    1. ``2`` — a prerequisite was missing or the run declared itself
       INCOMPLETE. Nothing can be concluded about the content.
    2. ``1`` — the run completed and produced blocking validation findings.
       The content is wrong, and that outranks a cleanup problem.
    3. ``4`` — the run completed cleanly and ONLY an owed cleanup effect
       stayed undone.
    4. ``0`` — nothing to report.

    ``4`` is deliberately the weakest: it tells a consumer "the work is
    done, the run directory needs a hand". Letting it displace ``1`` or
    ``2`` would tell that consumer the work was done when it was not.

    Args:
        results: The executed check results.
        owed_effect_failed: Whether at least one owed cleanup effect could
            not be carried out.

    Returns:
        The FK-78 exit code for this run.
    """
    decided = exit_code(results)
    if decided != EXIT_PASS:
        return decided
    return EXIT_OWED_EFFECT if owed_effect_failed else EXIT_PASS


def error(check_id: str, path: str, locator: str, message: str) -> Finding:
    """Build an ERROR finding."""
    return Finding(check_id=check_id, severity="ERROR", path=path, locator=locator, message=message)
