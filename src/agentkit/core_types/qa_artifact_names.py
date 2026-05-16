"""Wire-String-Konstanten fuer QA-Artefakt-Dateinamen (Cross-Cutting).

Diese Modulposition haelt die kanonischen Wire-Strings der QA-Artefakte
als reine Datenwerte ohne BC-Verantwortung. Sie ist Cross-Cutting und
NICHT Teil eines geschuetzten Modul-Prefix-Bereichs nach
``concept/formal-spec/truth-boundary-checker/invariants.md`` (siehe
``protected_module_prefixes``: ``agentkit.governance`` / ``agentkit.pipeline``
/ ``agentkit.qa.structural`` duerfen diese Strings literal nicht
enthalten).

Aufrufer:
- ``agentkit.state_backend`` (Persistenz, Projection-Schreibpfad) — darf
  die Strings produktiv nutzen (state_backend ist T-Treiber, nicht
  protected).
- ``agentkit.governance.guard_system.protected_paths`` — importiert die
  Strings hier und buendelt sie zur Hook-Konfigurations-Tuple. Damit
  bleiben die Literale aus dem governance-Namespace draussen
  (Truth-Boundary-Conformance).

Konzept-Anker:
- ``FK-31 §31.3`` — QA-Artefakt-Schutz (Hook-Konfiguration in
  governance.guard_system).
- ``concept/formal-spec/truth-boundary-checker/invariants.md`` Z. 24-52
  (protected/allowed module prefixes; forbidden_json_truth_filenames).
- ``concept/_meta/bc-cut-decisions.md §BC 8 Refactor-Liste Pkt. 24``.
"""

from __future__ import annotations

#: Layer-Artefakt-Dateinamen pro QA-Layer (FK-31 §31.3 / FK-27 §27.4-§27.6).
LAYER_ARTIFACT_FILES: dict[str, str] = {
    "structural": "structural.json",
    "semantic": "semantic-review.json",
    "adversarial": "adversarial.json",
}

#: Dateiname des Verify-Decision-Artefakts (Layer 4 Policy, FK-27 §27.7).
VERIFY_DECISION_FILE: str = "verify-decision.json"

#: Dateiname des Guardrail-Artefakts (siehe FK-31 §31.3).
GUARDRAIL_FILE: str = "guardrail.json"

__all__ = [
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "VERIFY_DECISION_FILE",
]
