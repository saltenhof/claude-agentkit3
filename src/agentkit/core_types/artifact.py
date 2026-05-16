"""ArtifactClass und EnvelopeStatus — Artefakt-Klassifikation.

Source of truth:
- ArtifactClass: FK-71 §71.1.1, Z. 90-99 (acht Artefaktklassen, lower-case).
- EnvelopeStatus: FK-71 §71.2, Z. 145 (PASS/FAIL/WARN/ERROR, upper-case).

Wire-Werte fuer ArtifactClass sind lowercase und konsistent mit dem
Postgres-CHECK-Constraint aus AG3-023 §2.1.4.
"""

from __future__ import annotations

from enum import StrEnum


class ArtifactClass(StrEnum):
    """Erzeugerklasse eines Artefakts pro FK-71 §71.1.1.

    Attributes:
        WORKER: Worker-Agent-Output (worker-manifest, protocol, Code).
        QA: QA-Subflow-Output (structural, policy, semantic_review).
        PIPELINE: Pipeline-Runner-Output (story_contexts, flow_executions).
        TELEMETRY: Telemetrie-Events / Export-Bundle.
        GOVERNANCE: Guard-/Integrity-Gate-Output.
        ENTWURF: Worker-Entwurfsartefakt (Exploration-Phase).
        HANDOVER: Worker-Handover (Implementation-Phase).
        ADVERSARIAL_TEST_SANDBOX: Adversarial-Test-Sandbox-Verzeichnis.
    """

    WORKER = "worker"
    QA = "qa"
    PIPELINE = "pipeline"
    TELEMETRY = "telemetry"
    GOVERNANCE = "governance"
    ENTWURF = "entwurf"
    HANDOVER = "handover"
    ADVERSARIAL_TEST_SANDBOX = "adversarial_test_sandbox"


class EnvelopeStatus(StrEnum):
    """Artefakt-Envelope-Status pro FK-71 §71.2.

    LLM-Check-Status ``PASS_WITH_CONCERNS`` wird beim Aggregieren auf
    ``WARN`` gemappt — dieses Mapping lebt in AG3-022, nicht hier.

    Attributes:
        PASS: Check bestanden.
        FAIL: Check nicht bestanden — blockiert Story.
        WARN: Aggregat eines ``PASS_WITH_CONCERNS``-LLM-Status.
        ERROR: Infrastruktur-Fehler (kein LLM-Ergebnis).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    ERROR = "ERROR"
