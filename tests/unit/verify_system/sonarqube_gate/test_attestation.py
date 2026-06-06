"""Unit tests for the commit-bound SonarQube attestation (FK-33 §33.6.3).

Covers AC1 (green-definition: QG-OK + Overall-Zero) and AC2 (commit
binding: stale revision is invalid; derived config_hash).
"""

from __future__ import annotations

import pytest

from agentkit.verify_system.sonarqube_gate import SonarAttestation, is_green


def _attestation(**overrides: object) -> SonarAttestation:
    base: dict[str, object] = {
        "commit_sha": "c0ffee",
        "tree_hash": "deadbeef",
        "analysis_id": "AX-1",
        "ce_task_id": "CE-1",
        "quality_gate_status": "OK",
        "quality_gate_hash": "qgh",
        "quality_profile_hash": "qph",
        "analysis_scope_hash": "ash",
        "new_code_definition": "PREVIOUS_VERSION",
        "exception_ledger_hash": "elh",
        "last_analyzed_revision": "rev-2",
        "sonarqube_version": "26.4",
        "branch_plugin_version": "1.23.0",
        "scanner_version": "5.0",
        "status": "READ",
    }
    base.update(overrides)
    return SonarAttestation(**base)  # type: ignore[arg-type]


class TestGreenDefinition:
    """AC1: green iff QG OK AND zero overall open non-accepted issues."""

    def test_qg_ok_and_zero_overall_is_green(self) -> None:
        att = _attestation(quality_gate_status="OK")
        assert is_green(att, overall_open_issue_count=0) is True

    def test_qg_ok_but_overall_issues_is_red(self) -> None:
        """QG OK but Overall-Code has open issues -> NOT green (Broken-Window)."""
        att = _attestation(quality_gate_status="OK")
        assert is_green(att, overall_open_issue_count=3) is False

    def test_qg_error_is_red_even_with_zero_overall(self) -> None:
        att = _attestation(quality_gate_status="ERROR")
        assert is_green(att, overall_open_issue_count=0) is False


class TestCommitBinding:
    """AC2: stale revision is invalid; no bare projectKey live-read."""

    def test_bound_to_matching_head(self) -> None:
        att = _attestation(last_analyzed_revision="rev-2")
        assert att.is_bound_to("rev-2") is True

    def test_stale_revision_is_not_bound(self) -> None:
        att = _attestation(last_analyzed_revision="rev-1")
        assert att.is_bound_to("rev-2") is False


class TestConfigHash:
    """AC2: config_hash is derived, deterministic, and not a stored field."""

    def test_config_hash_is_deterministic(self) -> None:
        att = _attestation()
        assert att.config_hash() == att.config_hash()
        assert len(att.config_hash()) == 64  # noqa: PLR2004

    def test_config_hash_changes_with_quality_gate_hash(self) -> None:
        a = _attestation(quality_gate_hash="x").config_hash()
        b = _attestation(quality_gate_hash="y").config_hash()
        assert a != b

    def test_config_hash_changes_with_version(self) -> None:
        a = _attestation(branch_plugin_version="1.23.0").config_hash()
        b = _attestation(branch_plugin_version="1.24.0").config_hash()
        assert a != b

    def test_config_hash_not_an_attestation_field(self) -> None:
        """config_hash is derived, never an extra=forbid model field."""
        assert "config_hash" not in SonarAttestation.model_fields

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="overall_zero_violations|extra"):
            _attestation(overall_zero_violations=True)


class TestMandatoryFieldFailClosed:
    """ERROR-1: a READ attestation can NEVER carry an empty MANDATORY field."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "commit_sha",
            "tree_hash",
            "analysis_id",
            "ce_task_id",
            "quality_gate_status",
            "quality_gate_hash",
            "quality_profile_hash",
            "analysis_scope_hash",
            "new_code_definition",
            "exception_ledger_hash",
            "last_analyzed_revision",
            "sonarqube_version",
            "branch_plugin_version",
            "scanner_version",
        ],
    )
    def test_empty_mandatory_field_rejected_for_read(self, field_name: str) -> None:
        with pytest.raises(ValueError, match="missing mandatory"):
            _attestation(**{field_name: ""})

    def test_whitespace_only_mandatory_field_rejected_for_read(self) -> None:
        with pytest.raises(ValueError, match="missing mandatory"):
            _attestation(commit_sha="   ")

    def test_empty_new_code_definition_rejected_for_read(self) -> None:
        """new_code_definition is a mandatory first-class attribute of the
        formal sonar-attestation entity: a code-producing project under the
        gate always has an active new-code period, so an empty value is a
        fail-closed precondition violation (ERROR-1)."""
        with pytest.raises(ValueError, match="missing mandatory"):
            _attestation(new_code_definition="")

    def test_non_read_status_skips_mandatory_check(self) -> None:
        """A non-READ attestation (e.g. a placeholder/unread marker) is not
        subject to the mandatory-binding rule; only READ is enforced."""
        att = _attestation(commit_sha="", status="UNREAD")
        assert att.commit_sha == ""
