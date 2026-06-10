"""Fail-closed mandatory-target feedback read (AG3-067 def-5, FK-38 §38.1.4).

``_mandatory_target_feedback_findings`` feeds BLOCKING extra findings into the
remediation loop. A genuinely-absent ``adversarial.json``
(``ArtifactNotFoundError``) correctly means "no mandatory targets". But a BROKEN
artifact access (unreadable envelope, broken payload) must NOT silently vanish as
"no targets" -- that would drop a mandatory target. These tests pin the
fail-closed behaviour: absent -> ``()``; broken -> ``MandatoryTargetReadError``;
valid -> the real ``Finding`` mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import ArtifactNotFoundError
from agentkit.verify_system.errors import MandatoryTargetReadError
from agentkit.verify_system.protocols import Severity
from agentkit.verify_system.system import _mandatory_target_feedback_findings

if TYPE_CHECKING:
    from agentkit.core_types import ArtifactClass


@dataclass
class _ReadLatestStub:
    """Stub artifact_manager whose ``read_latest`` is scripted."""

    behavior: str = "absent"
    payload: object = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)

    def read_latest(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> object:
        self.seen.append((story_id, stage))
        if self.behavior == "absent":
            raise ArtifactNotFoundError("no adversarial artifact in scope")
        if self.behavior == "broken":
            raise OSError("backend read failed: corrupt envelope row")
        return SimpleNamespace(payload=self.payload)


def _system(stub: _ReadLatestStub) -> object:
    return SimpleNamespace(artifact_manager=stub)


def test_round_one_short_circuits_before_any_read() -> None:
    """Round 1 never reads the adversarial artifact (feedback starts at round 2)."""
    stub = _ReadLatestStub(behavior="broken")
    findings = _mandatory_target_feedback_findings(
        _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=1
    )
    assert findings == ()
    assert stub.seen == []  # no read attempted -> no spurious fail-closed


def test_absent_adversarial_means_no_targets() -> None:
    """A genuinely-absent adversarial.json -> no mandatory targets (not an error)."""
    stub = _ReadLatestStub(behavior="absent")
    findings = _mandatory_target_feedback_findings(
        _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
    )
    assert findings == ()


def test_broken_adversarial_fails_closed() -> None:
    """A broken artifact access fails closed -- it must NOT vanish as 'no targets'."""
    stub = _ReadLatestStub(behavior="broken")
    with pytest.raises(MandatoryTargetReadError) as exc_info:
        _mandatory_target_feedback_findings(
            _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
        )
    # The root cause is preserved (chained), never erased.
    assert isinstance(exc_info.value.__cause__, OSError)
    assert "FAIL-CLOSED" in str(exc_info.value)


def test_present_envelope_with_none_payload_fails_closed() -> None:
    """A PRESENT envelope with a None payload -> FAIL-CLOSED (r2).

    ``envelope.payload or {}`` previously masked this into "no targets". A
    present-but-None payload is a broken artifact, not a genuinely-absent one.
    """
    stub = _ReadLatestStub(behavior="valid", payload=None)
    with pytest.raises(MandatoryTargetReadError) as exc_info:
        _mandatory_target_feedback_findings(
            _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
        )
    assert "FAIL-CLOSED" in str(exc_info.value)


def test_present_envelope_with_non_mapping_payload_fails_closed() -> None:
    """A PRESENT envelope whose payload is not a mapping -> FAIL-CLOSED (r2)."""
    stub = _ReadLatestStub(behavior="valid", payload=["not", "a", "mapping"])
    with pytest.raises(MandatoryTargetReadError):
        _mandatory_target_feedback_findings(
            _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
        )


def test_present_payload_missing_results_key_means_no_targets() -> None:
    """A present payload with NO mandatory_target_results key -> () (no raise)."""
    stub = _ReadLatestStub(behavior="valid", payload={"other": "value"})
    findings = _mandatory_target_feedback_findings(
        _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
    )
    assert findings == ()


def test_present_payload_non_list_results_fails_closed() -> None:
    """A present payload with a non-list mandatory_target_results -> FAIL-CLOSED (r2)."""
    stub = _ReadLatestStub(
        behavior="valid", payload={"mandatory_target_results": "broken"}
    )
    with pytest.raises(MandatoryTargetReadError):
        _mandatory_target_feedback_findings(
            _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
        )


def test_valid_adversarial_maps_unmet_targets_to_findings() -> None:
    """A valid envelope with an unmet target -> a real BLOCKING adversarial Finding."""
    stub = _ReadLatestStub(
        behavior="valid",
        payload={
            "mandatory_target_results": [
                {"target_id": "edge-case-empty-input", "status": "NOT_TESTED"},
                {"target_id": "covered", "status": "TESTED"},
            ]
        },
    )
    findings = _mandatory_target_feedback_findings(
        _system(stub), story_id="TEST-1", run_id="run-1", qa_cycle_round=2
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.layer == "adversarial"
    assert finding.check == "edge-case-empty-input"
    assert finding.severity is Severity.BLOCKING
