"""Severity enum for QA findings and stage results.

Source of truth: FK-27 §27.4.2 — concept/technical-design/27_verify_pipeline_closure_orchestration.md

Severity is the cross-cutting classification of finding-impact across
Verify-System layers. Replaces the v2 CRITICAL/HIGH/MEDIUM/LOW/INFO
scale with the FK-27-normative BLOCKING/MAJOR/MINOR triad.
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Finding severity per FK-27 §27.4.2.

    Wire-values are upper-case strings exactly matching the Python
    member names; the contract test pins each value.

    Attributes:
        BLOCKING: Hartes Hindernis — Story darf nicht weiter.
        MAJOR: Schwerer Befund — sammelt fuer Policy-Aggregation.
        MINOR: Weicher Befund — fliesst in Hygiene-Telemetrie.
    """

    BLOCKING = "BLOCKING"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
