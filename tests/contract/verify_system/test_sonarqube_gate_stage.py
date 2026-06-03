"""Contract tests for the SonarQube-Green-Gate (AG3-052 §2.1.7 / AC2/AC3/AC6).

Pins:
* the ``SonarAttestation`` field set 1:1 against the formal entity
  ``formal.deterministic-checks.entities.sonar-attestation`` (plus the
  FK-33 §33.6.3 commit_sha/tree_hash binding -- which IS part of the
  formal attribute list);
* the accepted-exception-ledger-entry fields against the formal entity;
* the ``sonarqube_gate`` stage-registry entry (layer/trust/sequence/
  story-type) against ``formal...sonarqube-gate-stage`` + FK-33 §33.2.2.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from agentkit.verify_system.sonarqube_gate import (
    SONARQUBE_GATE_STAGE,
    AcceptedExceptionLedgerEntry,
    SonarAttestation,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENTITIES = (
    _REPO_ROOT / "concept" / "formal-spec" / "deterministic-checks" / "entities.md"
)
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(.*?)```\s*<!-- FORMAL-SPEC:END -->",
    re.DOTALL,
)


def _load_entities() -> dict[str, list[str]]:
    text = _ENTITIES.read_text(encoding="utf-8")
    match = _FORMAL_BLOCK.search(text)
    assert match is not None, "FORMAL-SPEC block not found in entities.md"
    data: dict[str, Any] = yaml.safe_load(match.group(1))
    return {entity["id"]: list(entity["attributes"]) for entity in data["entities"]}


_ENTITY_ATTRS = _load_entities()


class TestAttestationFieldSet:
    """AC2: SonarAttestation matches the formal entity 1:1 (exact names)."""

    def test_attestation_fields_match_formal_entity(self) -> None:
        formal = set(_ENTITY_ATTRS["deterministic-checks.entity.sonar-attestation"])
        model = set(SonarAttestation.model_fields)
        assert model == formal, (
            f"SonarAttestation fields diverge from the formal entity. "
            f"missing={formal - model}; extra={model - formal}"
        )

    def test_identity_key_is_analysis_id(self) -> None:
        assert "analysis_id" in SonarAttestation.model_fields

    def test_config_hash_is_not_a_field(self) -> None:
        """config_hash is a DERIVED quantity, never a stored attestation field."""
        assert "config_hash" not in SonarAttestation.model_fields

    def test_overall_zero_violations_is_not_a_field(self) -> None:
        assert "overall_zero_violations" not in SonarAttestation.model_fields


class TestLedgerFieldSet:
    """AC3: ledger entry matches the formal entity (incl. fingerprint/approved_by/scope)."""

    def test_ledger_entry_fields_match_formal_entity(self) -> None:
        formal = set(
            _ENTITY_ATTRS["deterministic-checks.entity.accepted-exception-ledger-entry"]
        )
        model = set(AcceptedExceptionLedgerEntry.model_fields)
        assert model == formal, (
            f"AcceptedExceptionLedgerEntry diverges from the formal entity. "
            f"missing={formal - model}; extra={model - formal}"
        )


class TestStageRegistryEntry:
    """AC6: the sonarqube_gate stage entry is pinned (layer/trust/sequence/type)."""

    def test_stage_id(self) -> None:
        assert SONARQUBE_GATE_STAGE.stage_id == "sonarqube_gate"

    def test_layer_one_deterministic(self) -> None:
        assert SONARQUBE_GATE_STAGE.layer == 1
        assert SONARQUBE_GATE_STAGE.kind == "deterministic"

    def test_trust_a_blocking(self) -> None:
        assert SONARQUBE_GATE_STAGE.trust_class == "A"
        assert SONARQUBE_GATE_STAGE.blocking is True

    def test_sequenced_after_adversarial(self) -> None:
        assert SONARQUBE_GATE_STAGE.sequence_after == "adversarial"

    def test_applies_to_impl_and_bugfix(self) -> None:
        assert SONARQUBE_GATE_STAGE.applies_to == frozenset({"implementation", "bugfix"})

    def test_producer(self) -> None:
        assert SONARQUBE_GATE_STAGE.producer == "qa-sonarqube-gate"

    def test_stage_fields_match_formal_entity(self) -> None:
        """The stage definition exposes exactly the formal entity's attributes."""
        formal = set(_ENTITY_ATTRS["deterministic-checks.entity.sonarqube-gate-stage"])
        model = {f.name for f in SONARQUBE_GATE_STAGE.__dataclass_fields__.values()}
        assert model == formal, (
            f"SonarStageDefinition diverges from the formal sonarqube-gate-stage "
            f"entity. missing={formal - model}; extra={model - formal}"
        )
