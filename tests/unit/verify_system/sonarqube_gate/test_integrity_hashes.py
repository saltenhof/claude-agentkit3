"""Unit tests for deterministic Sonar integrity-hash computation (ERROR-B).

The integrity hashes (quality-gate / quality-profile / analysis-scope) are
COMPUTED from authoritative Sonar Web-API data in ONE place; these tests prove
they are deterministic, ORDER-INDEPENDENT, and fail closed when a required
authoritative read is unavailable. Only the thin HTTP boundary is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from agentkit.backend.verify_system.sonarqube_gate.integrity_hashes import (
    compute_analysis_scope_hash,
    compute_quality_gate_hash,
    compute_quality_profile_hash,
)
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

_PROJECT = "proj"


@dataclass
class _FakeClient:
    """Fake thin Sonar client mirroring the REAL Web-API response shapes."""

    gate_conditions: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[dict[str, Any]] = field(default_factory=list)
    settings: list[dict[str, Any]] = field(default_factory=list)
    raise_on: str | None = None

    def qualitygates_get_by_project(self, project: str) -> SonarHttpResponse:
        del project
        self._maybe_raise("qualitygates_get_by_project")
        return SonarHttpResponse(
            status_code=200, json_body={"qualityGate": {"id": "1", "name": "AK3 Way"}}
        )

    def qualitygates_show(self, name: str) -> SonarHttpResponse:
        del name
        self._maybe_raise("qualitygates_show")
        return SonarHttpResponse(
            status_code=200,
            json_body={"id": "1", "name": "AK3 Way", "conditions": self.gate_conditions},
        )

    def qualityprofiles_search(self, project: str) -> SonarHttpResponse:
        del project
        self._maybe_raise("qualityprofiles_search")
        return SonarHttpResponse(status_code=200, json_body={"profiles": self.profiles})

    def settings_values(
        self, *, component: str, keys: tuple[str, ...] = ()
    ) -> SonarHttpResponse:
        del component, keys
        self._maybe_raise("settings_values")
        return SonarHttpResponse(status_code=200, json_body={"settings": self.settings})

    def _maybe_raise(self, op: str) -> None:
        if self.raise_on == op:
            raise SonarApiError(f"fake unreachable on {op}")


_COND_A = {"id": 1, "metric": "new_violations", "op": "GT", "error": "0"}
_COND_B = {"id": 2, "metric": "coverage", "op": "LT", "error": "80"}
_PROF_PY = {"key": "py-1", "language": "py", "rulesUpdatedAt": "t1", "lastUsed": "t2"}
_PROF_JS = {"key": "js-1", "language": "js", "rulesUpdatedAt": "t3", "lastUsed": "t4"}


class TestQualityGateHash:
    def test_order_independent_over_conditions(self) -> None:
        first = compute_quality_gate_hash(
            _FakeClient(gate_conditions=[_COND_A, _COND_B]), _PROJECT  # type: ignore[arg-type]
        )
        second = compute_quality_gate_hash(
            _FakeClient(gate_conditions=[_COND_B, _COND_A]), _PROJECT  # type: ignore[arg-type]
        )
        assert first == second
        assert len(first) == 64

    def test_changed_threshold_changes_hash(self) -> None:
        base = compute_quality_gate_hash(
            _FakeClient(gate_conditions=[_COND_A]), _PROJECT  # type: ignore[arg-type]
        )
        changed = {**_COND_A, "error": "1"}
        other = compute_quality_gate_hash(
            _FakeClient(gate_conditions=[changed]), _PROJECT  # type: ignore[arg-type]
        )
        assert base != other

    def test_missing_gate_fails_closed(self) -> None:
        client = _FakeClient(raise_on="qualitygates_get_by_project")
        with pytest.raises(SonarApiError):
            compute_quality_gate_hash(client, _PROJECT)  # type: ignore[arg-type]

    def test_no_quality_gate_object_fails_closed(self) -> None:
        @dataclass
        class _NoGate(_FakeClient):
            def qualitygates_get_by_project(self, project: str) -> SonarHttpResponse:
                del project
                return SonarHttpResponse(status_code=200, json_body={})

        with pytest.raises(SonarApiError, match="no qualityGate object"):
            compute_quality_gate_hash(_NoGate(), _PROJECT)  # type: ignore[arg-type]

    def test_gate_without_name_fails_closed(self) -> None:
        @dataclass
        class _NoName(_FakeClient):
            def qualitygates_get_by_project(self, project: str) -> SonarHttpResponse:
                del project
                return SonarHttpResponse(
                    status_code=200, json_body={"qualityGate": {"id": "1"}}
                )

        with pytest.raises(SonarApiError, match="no qualityGate.name"):
            compute_quality_gate_hash(_NoName(), _PROJECT)  # type: ignore[arg-type]

    def test_optional_op_error_default_to_empty(self) -> None:
        """A condition without op/error still hashes (optional fields => '')."""
        digest = compute_quality_gate_hash(
            _FakeClient(gate_conditions=[{"metric": "coverage"}]), _PROJECT  # type: ignore[arg-type]
        )
        assert len(digest) == 64


class TestQualityProfileHash:
    def test_order_independent_over_profiles(self) -> None:
        first = compute_quality_profile_hash(
            _FakeClient(profiles=[_PROF_PY, _PROF_JS]), _PROJECT  # type: ignore[arg-type]
        )
        second = compute_quality_profile_hash(
            _FakeClient(profiles=[_PROF_JS, _PROF_PY]), _PROJECT  # type: ignore[arg-type]
        )
        assert first == second
        assert len(first) == 64

    def test_rules_update_changes_hash(self) -> None:
        base = compute_quality_profile_hash(
            _FakeClient(profiles=[_PROF_PY]), _PROJECT  # type: ignore[arg-type]
        )
        updated = {**_PROF_PY, "rulesUpdatedAt": "t-newer"}
        other = compute_quality_profile_hash(
            _FakeClient(profiles=[updated]), _PROJECT  # type: ignore[arg-type]
        )
        assert base != other

    def test_no_profiles_fails_closed(self) -> None:
        with pytest.raises(SonarApiError):
            compute_quality_profile_hash(_FakeClient(profiles=[]), _PROJECT)  # type: ignore[arg-type]

    def test_profile_without_required_field_fails_closed(self) -> None:
        # A profile entry missing the required ``language`` fails closed.
        client = _FakeClient(profiles=[{"key": "py-1"}])
        with pytest.raises(SonarApiError, match="language"):
            compute_quality_profile_hash(client, _PROJECT)  # type: ignore[arg-type]


class TestAnalysisScopeHash:
    def test_order_independent_over_settings(self) -> None:
        a = {"key": "sonar.sources", "value": "src"}
        b = {"key": "sonar.exclusions", "values": ["**/gen/**", "**/build/**"]}
        first = compute_analysis_scope_hash(
            _FakeClient(settings=[a, b]), _PROJECT  # type: ignore[arg-type]
        )
        # Same settings, reversed list AND reversed multi-value order.
        b_rev = {"key": "sonar.exclusions", "values": ["**/build/**", "**/gen/**"]}
        second = compute_analysis_scope_hash(
            _FakeClient(settings=[b_rev, a]), _PROJECT  # type: ignore[arg-type]
        )
        assert first == second
        assert len(first) == 64

    def test_ignores_unrelated_settings(self) -> None:
        scoped = {"key": "sonar.sources", "value": "src"}
        noise = {"key": "sonar.login", "value": "secret"}
        with_noise = compute_analysis_scope_hash(
            _FakeClient(settings=[scoped, noise]), _PROJECT  # type: ignore[arg-type]
        )
        without = compute_analysis_scope_hash(
            _FakeClient(settings=[scoped]), _PROJECT  # type: ignore[arg-type]
        )
        assert with_noise == without

    def test_changed_scope_changes_hash(self) -> None:
        base = compute_analysis_scope_hash(
            _FakeClient(settings=[{"key": "sonar.sources", "value": "src"}]),  # type: ignore[arg-type]
            _PROJECT,
        )
        other = compute_analysis_scope_hash(
            _FakeClient(settings=[{"key": "sonar.sources", "value": "lib"}]),  # type: ignore[arg-type]
            _PROJECT,
        )
        assert base != other

    def test_unreachable_settings_fails_closed(self) -> None:
        client = _FakeClient(raise_on="settings_values")
        with pytest.raises(SonarApiError):
            compute_analysis_scope_hash(client, _PROJECT)  # type: ignore[arg-type]

    def test_non_list_settings_fails_closed(self) -> None:
        @dataclass
        class _BadSettings(_FakeClient):
            def settings_values(
                self, *, component: str, keys: tuple[str, ...] = ()
            ) -> SonarHttpResponse:
                del component, keys
                return SonarHttpResponse(status_code=200, json_body={})

        with pytest.raises(SonarApiError, match="no settings array"):
            compute_analysis_scope_hash(_BadSettings(), _PROJECT)  # type: ignore[arg-type]

    def test_field_values_setting_is_normalized(self) -> None:
        """A field-valued scope setting (e.g. coverage exclusions blocks) is
        normalised order-independently."""
        a = {
            "key": "sonar.coverage.exclusions",
            "fieldValues": [{"path": "a"}, {"path": "b"}],
        }
        b = {
            "key": "sonar.coverage.exclusions",
            "fieldValues": [{"path": "b"}, {"path": "a"}],
        }
        first = compute_analysis_scope_hash(_FakeClient(settings=[a]), _PROJECT)  # type: ignore[arg-type]
        second = compute_analysis_scope_hash(_FakeClient(settings=[b]), _PROJECT)  # type: ignore[arg-type]
        assert first == second
        assert len(first) == 64
