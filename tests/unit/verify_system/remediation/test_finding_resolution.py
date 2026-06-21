"""Unit tests for FindingResolutionAssessor (FK-34 / DK-04 §4.6, AG3-041 AC5)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import Severity
from agentkit.backend.verify_system.errors import ResolutionMetadataError
from agentkit.backend.verify_system.protocols import Finding, TrustClass
from agentkit.backend.verify_system.remediation.finding_resolution import (
    LLM_RESOLUTION_METADATA_KEY,
    FindingResolutionAssessor,
    FindingResolutionStatus,
    resolution_map_from_metadata,
    serialize_resolution_map,
)


def _finding(check: str, severity: Severity, *, layer: str = "structural") -> Finding:
    return Finding(
        layer=layer,
        check=check,
        severity=severity,
        message=f"{check} failed",
        trust_class=TrustClass.SYSTEM,
    )


class TestAssess:
    def test_finding_gone_is_fully_resolved(self) -> None:
        previous = (_finding("c1", Severity.BLOCKING),)
        current: tuple[Finding, ...] = ()
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.FULLY_RESOLVED

    def test_reduced_severity_is_partially_resolved(self) -> None:
        previous = (_finding("c1", Severity.BLOCKING),)
        current = (_finding("c1", Severity.MINOR),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert (
            statuses[("structural", "c1")]
            is FindingResolutionStatus.PARTIALLY_RESOLVED
        )

    def test_same_severity_is_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (_finding("c1", Severity.MAJOR),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED

    def test_higher_severity_is_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MINOR),)
        current = (_finding("c1", Severity.BLOCKING),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED

    def test_matching_is_layer_and_check_scoped(self) -> None:
        previous = (_finding("c1", Severity.MAJOR, layer="structural"),)
        # Same check id but different layer -> not a match -> previous is gone.
        current = (_finding("c1", Severity.MAJOR, layer="adversarial"),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert (
            statuses[("structural", "c1")] is FindingResolutionStatus.FULLY_RESOLVED
        )

    def test_most_severe_current_decides(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (
            _finding("c1", Severity.MINOR),
            _finding("c1", Severity.MAJOR),
        )
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED


class TestHasUnresolved:
    def test_true_when_any_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (_finding("c1", Severity.MAJOR),)
        assert FindingResolutionAssessor().has_unresolved(previous, current) is True

    def test_true_when_partially_resolved(self) -> None:
        """E7 (AG3-041 / FK-34 §34.9.4): PARTIALLY_RESOLVED is open/blocking.

        A reduced-severity (but still present) previous finding counts as
        unresolved — the same open-status SSOT that
        ``resolution_map_has_open_findings`` and
        ``RemediationFeedback.has_open_findings`` use. Previously
        ``has_unresolved`` only matched ``NOT_RESOLVED``, silently treating a
        partially-resolved finding as cleared; this asserts the corrected,
        single-truth semantics.
        """
        previous = (_finding("c1", Severity.BLOCKING),)
        current = (_finding("c1", Severity.MINOR),)
        assert FindingResolutionAssessor().has_unresolved(previous, current) is True

    def test_false_when_all_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current: tuple[Finding, ...] = ()
        assert FindingResolutionAssessor().has_unresolved(previous, current) is False


class TestResolutionMapMetadataCodec:
    """E5: round-trip + fail-closed decode of the LLM resolution metadata."""

    def test_serialize_then_decode_round_trips(self) -> None:
        original = {
            ("qa_review", "ac_fulfilled"): FindingResolutionStatus.PARTIALLY_RESOLVED,
            ("semantic_review", "systemic_adequacy"): (
                FindingResolutionStatus.NOT_RESOLVED
            ),
        }
        serialized = serialize_resolution_map(original)
        assert serialized == {
            "qa_review:ac_fulfilled": "partially_resolved",
            "semantic_review:systemic_adequacy": "not_resolved",
        }
        decoded = resolution_map_from_metadata(
            {LLM_RESOLUTION_METADATA_KEY: serialized}
        )
        assert decoded == original

    def test_decode_none_or_absent_is_empty(self) -> None:
        # Absence of any remediation context is the ONLY benign case.
        assert resolution_map_from_metadata(None) == {}
        assert resolution_map_from_metadata({}) == {}
        assert resolution_map_from_metadata({"other": "x"}) == {}

    def test_decode_non_dict_payload_raises(self) -> None:
        """E5 fail-closed: a present-but-non-dict payload is a pipeline bug."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata({LLM_RESOLUTION_METADATA_KEY: "not-a-dict"})

    def test_decode_malformed_key_no_separator_raises(self) -> None:
        """E5 fail-closed: a key without the layer:check separator raises."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {"no_colon_key": "fully_resolved"}}
            )

    def test_decode_malformed_key_too_many_parts_raises(self) -> None:
        """E5 fail-closed: a key with too many separator parts raises."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {"a:b:c": "fully_resolved"}}
            )

    def test_decode_empty_key_part_raises(self) -> None:
        """E5 fail-closed: a key with an empty layer/check part raises."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {":check": "fully_resolved"}}
            )

    def test_decode_unknown_status_value_raises(self) -> None:
        """E5 fail-closed: an unknown status value is a pipeline bug, not skip."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {"qa_review:x": "bogus_status"}}
            )

    def test_decode_non_string_value_raises(self) -> None:
        """E5 fail-closed: a non-string status value raises."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {"qa_review:x": 123}}
            )

    def test_decode_non_string_key_raises(self) -> None:
        """E5 fail-closed: a non-string mapping key raises."""
        with pytest.raises(ResolutionMetadataError):
            resolution_map_from_metadata(
                {LLM_RESOLUTION_METADATA_KEY: {123: "fully_resolved"}}
            )
