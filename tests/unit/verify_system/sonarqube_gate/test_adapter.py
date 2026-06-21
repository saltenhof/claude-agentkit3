"""Unit tests for the productive SonarGateInputPort adapter (AG3-052 E1/E4).

Only the external HTTP boundary (``SonarClient``) is stubbed (MOCKS-Ausnahme);
the adapter orchestration, fail-closed behaviour and the ``Administer Issues``
applier run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agentkit.backend.config.models import SonarQubeConfig
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.sonarqube_gate import (
    AcceptedExceptionLedger,
    AcceptedExceptionLedgerEntry,
    BoundAnalysis,
    ConfiguredSonarGateInputPort,
    ReconcilerApplyError,
    SonarApplicability,
    build_issue_applier,
    resolve_analysis_id,
)
from agentkit.integration_clients.sonar import SonarApiError, SonarHttpResponse

_HEAD = "rev-9"


@dataclass
class _StubSonarClient:
    """Stub of the thin HTTP boundary mirroring the REAL Web-API shapes.

    ``ce/task`` resolves the analysisId (ERROR-A); ``project_status`` carries
    ONLY ``projectStatus.{status,periods}`` (no invented hash fields); the
    integrity hashes come from the qualitygates/qualityprofiles/settings
    endpoints (ERROR-B). Only the external system is faked.
    """

    qg_status: str = "OK"
    revision: str = _HEAD
    version: str = "26.4"
    analysis_id: str = "AX-1"
    ce_status: str = "SUCCESS"
    issues: tuple[dict[str, str], ...] = ()
    transition_should_fail: bool = False
    transitioned: list[tuple[str, str]] = field(default_factory=list)
    tagged: list[tuple[str, str]] = field(default_factory=list)

    def ce_task(self, ce_task_id: str) -> SonarHttpResponse:
        del ce_task_id
        task: dict[str, object] = {"id": "CE-1", "status": self.ce_status}
        if self.ce_status == "SUCCESS":
            task["analysisId"] = self.analysis_id
        return SonarHttpResponse(status_code=200, json_body={"task": task})

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "projectStatus": {
                    "status": self.qg_status,
                    "conditions": [],
                    "periods": [{"mode": "PREVIOUS_VERSION"}],
                }
            },
        )

    def project_analyses_search(
        self, project: str, *, branch: str | None = None
    ) -> SonarHttpResponse:
        del project, branch
        if self.revision == "":
            # No revision reported by Sonar (fail-closed path, FIX-2).
            return SonarHttpResponse(status_code=200, json_body={"analyses": []})
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "analyses": [{"key": self.analysis_id, "revision": self.revision}]
            },
        )

    def system_status(self) -> SonarHttpResponse:
        return SonarHttpResponse(
            status_code=200,
            json_body={"id": "srv-1", "version": self.version, "status": "UP"},
        )

    def qualitygates_get_by_project(self, project: str) -> SonarHttpResponse:
        del project
        return SonarHttpResponse(
            status_code=200,
            json_body={"qualityGate": {"id": "1", "name": "AK3 Way"}},
        )

    def qualitygates_show(self, name: str) -> SonarHttpResponse:
        del name
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "id": "1",
                "name": "AK3 Way",
                "conditions": [
                    {"id": 1, "metric": "new_violations", "op": "GT", "error": "0"}
                ],
            },
        )

    def qualityprofiles_search(self, project: str) -> SonarHttpResponse:
        del project
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "profiles": [
                    {
                        "key": "py-1",
                        "name": "Sonar way",
                        "language": "py",
                        "rulesUpdatedAt": "2026-01-01T00:00:00+0000",
                        "lastUsed": "2026-06-01T00:00:00+0000",
                    }
                ]
            },
        )

    def settings_values(
        self, *, component: str, keys: tuple[str, ...] = ()
    ) -> SonarHttpResponse:
        del component, keys
        return SonarHttpResponse(
            status_code=200,
            json_body={"settings": [{"key": "sonar.sources", "value": "src"}]},
        )

    def search_issues(self, params: object) -> SonarHttpResponse:
        del params
        return SonarHttpResponse(status_code=200, json_body={"issues": list(self.issues)})

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        if self.transition_should_fail:
            raise SonarApiError("transition denied")
        self.transitioned.append((issue_key, transition))
        return SonarHttpResponse(status_code=200, json_body={})

    def set_issue_tags(self, issue_key: str, tags: str) -> SonarHttpResponse:
        self.tagged.append((issue_key, tags))
        return SonarHttpResponse(status_code=200, json_body={})


def _config() -> SonarQubeConfig:
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONARQUBE_TOKEN",
        scanner_version="5.0.1",
    )


def _bound() -> BoundAnalysis:
    return BoundAnalysis(
        ce_task_id="CE-1",
        component="proj",
        branch="feature",
        commit_sha="c0ffee",
        tree_hash="deadbeef",
        scanner_version="5.0.1",
    )


def _port(client: _StubSonarClient, ledger: AcceptedExceptionLedger) -> ConfiguredSonarGateInputPort:
    return ConfiguredSonarGateInputPort(
        config=_config(),
        client=client,  # type: ignore[arg-type]
        fast=False,
        story_type=StoryType.IMPLEMENTATION,
        ledger=ledger,
        bound_analysis=_bound(),
        main_head_revision=_HEAD,
    )


class TestApplicableInputs:
    def test_green_inputs_build_attestation(self) -> None:
        client = _StubSonarClient(qg_status="OK", issues=())
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is not None
        assert inputs.attestation.quality_gate_status == "OK"
        assert inputs.attestation.last_analyzed_revision == _HEAD

    def test_current_issues_read_for_reconciler(self) -> None:
        client = _StubSonarClient(
            issues=(
                {"key": "K1", "rule": "python:S1", "hash": "fp1", "message": "m1"},
                {"key": "K2", "rule": "python:S2", "hash": "fp2", "message": "m2"},
            )
        )
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        assert {i.issue_key for i in inputs.current_issues} == {"K1", "K2"}

    def test_post_apply_reader_rereads_quality_gate(self) -> None:
        """E4: the adapter supplies a post_apply_reader that RE-READS Sonar.

        It returns the recomputed QG verdict + the fresh open-non-accepted
        count (here OK + 0), NOT a stale subtraction.
        """
        client = _StubSonarClient(qg_status="OK", issues=())
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        assert inputs.post_apply_reader is not None
        post = inputs.post_apply_reader()
        assert post.quality_gate_status == "OK"
        assert post.overall_open_issue_count == 0

    def test_post_apply_reader_fail_closed_on_api_error(self) -> None:
        """E4: a Sonar failure on the post-apply re-read surfaces as ValueError.

        The gate's fail-closed boundary catches ``OSError/ValueError`` from the
        reader, so the adapter translates a ``SonarApiError`` into ``ValueError``.

        The attestation read (resolve_inputs) succeeds on the FIRST
        ``project_status`` call; the POST-apply re-read (the SECOND call) is
        the one that goes unreachable — this isolates the re-read boundary.
        """
        @dataclass
        class _SecondStatusBreaksClient(_StubSonarClient):
            status_calls: int = 0

            def project_status(  # type: ignore[override]
                self, *, analysis_id: str | None = None, ce_task_id: str | None = None
            ) -> SonarHttpResponse:
                self.status_calls += 1
                if self.status_calls >= 2:
                    raise SonarApiError("post-apply status unreachable")
                return super().project_status(
                    analysis_id=analysis_id, ce_task_id=ce_task_id
                )

        inputs = _port(
            _SecondStatusBreaksClient(), AcceptedExceptionLedger()
        ).resolve_inputs("S-1", None)
        # The attestation read succeeded (first call), so the inputs resolve
        # APPLICABLE with an attestation and a wired re-reader.
        assert inputs.attestation is not None
        assert inputs.post_apply_reader is not None
        with pytest.raises(ValueError, match="post-apply Sonar re-read failed"):
            inputs.post_apply_reader()

    def test_issue_applier_transitions_in_sonar(self) -> None:
        client = _StubSonarClient(
            issues=({"key": "K1", "rule": "python:S1", "hash": "fp1", "message": "dup"},)
        )
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        inputs.issue_applier("K1")
        assert client.transitioned == [("K1", "accept")]
        assert client.tagged and client.tagged[0][0] == "K1"

    def test_issue_applier_fail_closed_on_api_error(self) -> None:
        client = _StubSonarClient(transition_should_fail=True)
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        with pytest.raises(ReconcilerApplyError):
            inputs.issue_applier("K1")


class TestFailClosed:
    def test_api_error_resolves_applicable_fail_closed(self) -> None:
        @dataclass
        class _BrokenClient(_StubSonarClient):
            def system_status(self) -> SonarHttpResponse:  # type: ignore[override]
                raise SonarApiError("unreachable")

        inputs = _port(_BrokenClient(), AcceptedExceptionLedger()).resolve_inputs("S-1", None)
        # Configured-but-unreachable => APPLICABLE with attestation=None
        # (fail-closed), NEVER NOT_APPLICABLE.
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_missing_revision_fail_closed_no_commit_sha_fallback(self) -> None:
        """FIX-2: a missing Sonar-reported revision FAILs closed.

        Previously the adapter fell back to ``analysis.commit_sha`` (fail-open,
        fabricating the binding locally). Now an empty/absent revision from
        ``project_analyses/search`` raises ``SonarApiError`` inside the read,
        which ``resolve_inputs`` turns into an APPLICABLE fail-closed input
        (``attestation=None``) — never a stapled local commit.
        """
        client = _StubSonarClient(revision="")  # Sonar reports no revision
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_missing_quality_gate_status_fail_closed(self) -> None:
        @dataclass
        class _NoStatusClient(_StubSonarClient):
            def project_status(  # type: ignore[override]
                self, *, analysis_id: str | None = None, ce_task_id: str | None = None
            ) -> SonarHttpResponse:
                del analysis_id, ce_task_id
                return SonarHttpResponse(status_code=200, json_body={})

        inputs = _port(_NoStatusClient(), AcceptedExceptionLedger()).resolve_inputs("S", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_ce_task_pending_fail_closed_no_analysis_id(self) -> None:
        """ERROR-A: a non-terminal ce/task => no analysisId => fail closed."""
        client = _StubSonarClient(ce_status="PENDING")
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_missing_server_version_fail_closed(self) -> None:
        """ERROR-1: api/system/status with NO version => fail closed.

        ``sonarqube_version`` is a mandatory FK-33 §33.6.3 binding; an absent
        version must not be stamped as ``""`` (which would silently pass).
        """
        @dataclass
        class _NoVersionClient(_StubSonarClient):
            def system_status(self) -> SonarHttpResponse:  # type: ignore[override]
                # Real system/status with version OMITTED (not empty-string).
                return SonarHttpResponse(
                    status_code=200, json_body={"id": "srv-1", "status": "UP"}
                )

        inputs = _port(
            _NoVersionClient(), AcceptedExceptionLedger()
        ).resolve_inputs("S", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_absent_periods_fail_closed(self) -> None:
        """ERROR-1: a project_status with NO new-code period fails closed.

        ``new_code_definition`` is a mandatory first-class attribute of the
        formal sonar-attestation entity; a code-producing project under the
        gate always has an active new-code period, so an absent
        ``projectStatus.periods`` (and no legacy ``period``) is a broken
        precondition => APPLICABLE fail-closed (attestation=None), never a
        silently empty binding.
        """
        @dataclass
        class _NoPeriodsClient(_StubSonarClient):
            def project_status(  # type: ignore[override]
                self, *, analysis_id: str | None = None, ce_task_id: str | None = None
            ) -> SonarHttpResponse:
                del analysis_id, ce_task_id
                # Real project_status WITHOUT any periods (new code unset).
                return SonarHttpResponse(
                    status_code=200,
                    json_body={
                        "projectStatus": {"status": self.qg_status, "conditions": []}
                    },
                )

        inputs = _port(
            _NoPeriodsClient(), AcceptedExceptionLedger()
        ).resolve_inputs("S", None)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_new_code_definition_read_from_periods_array(self) -> None:
        """ERROR-1: the REAL periods[] array shape (not a dict) is parsed."""
        @dataclass
        class _PeriodsArrayClient(_StubSonarClient):
            def project_status(  # type: ignore[override]
                self, *, analysis_id: str | None = None, ce_task_id: str | None = None
            ) -> SonarHttpResponse:
                del analysis_id, ce_task_id
                return SonarHttpResponse(
                    status_code=200,
                    json_body={
                        "projectStatus": {
                            "status": self.qg_status,
                            "conditions": [],
                            "periods": [
                                {
                                    "index": 1,
                                    "mode": "NUMBER_OF_DAYS",
                                    "date": "2026-01-01T00:00:00+0000",
                                    "parameter": "30",
                                }
                            ],
                        }
                    },
                )

        inputs = _port(
            _PeriodsArrayClient(), AcceptedExceptionLedger()
        ).resolve_inputs("S", None)
        att = inputs.attestation
        assert att is not None
        assert att.new_code_definition == "NUMBER_OF_DAYS"

    def test_new_code_definition_read_from_legacy_period_dict(self) -> None:
        """ERROR-1: a legacy singular ``period`` dict (older servers) is still
        accepted for backward compatibility."""
        @dataclass
        class _LegacyPeriodClient(_StubSonarClient):
            def project_status(  # type: ignore[override]
                self, *, analysis_id: str | None = None, ce_task_id: str | None = None
            ) -> SonarHttpResponse:
                del analysis_id, ce_task_id
                return SonarHttpResponse(
                    status_code=200,
                    json_body={
                        "projectStatus": {
                            "status": self.qg_status,
                            "conditions": [],
                            "period": {"mode": "PREVIOUS_VERSION", "index": 1},
                        }
                    },
                )

        inputs = _port(
            _LegacyPeriodClient(), AcceptedExceptionLedger()
        ).resolve_inputs("S", None)
        att = inputs.attestation
        assert att is not None
        assert att.new_code_definition == "PREVIOUS_VERSION"

    def test_computed_integrity_hashes_are_sourced(self) -> None:
        """ERROR-B: the integrity hashes are COMPUTED 64-char sha256 digests
        from authoritative endpoints, not invented literal fields."""
        client = _StubSonarClient(qg_status="OK")
        inputs = _port(client, AcceptedExceptionLedger()).resolve_inputs("S", None)
        att = inputs.attestation
        assert att is not None
        assert len(att.quality_gate_hash) == 64
        assert len(att.quality_profile_hash) == 64
        assert len(att.analysis_scope_hash) == 64
        assert att.scanner_version == "5.0.1"
        assert att.analysis_id == "AX-1"


class TestNotApplicableResolution:
    def test_fast_returns_not_applicable_fast(self) -> None:
        port = ConfiguredSonarGateInputPort(
            config=_config(),
            client=_StubSonarClient(),  # type: ignore[arg-type]
            fast=True,
            story_type=StoryType.IMPLEMENTATION,
            ledger=AcceptedExceptionLedger(),
            bound_analysis=_bound(),
            main_head_revision=_HEAD,
        )
        inputs = port.resolve_inputs("S-1", None)
        assert inputs.applicability is SonarApplicability.NOT_APPLICABLE_FAST
        assert inputs.attestation is None


class TestResolveAnalysisId:
    """ERROR-A: analysisId resolved from a terminal-SUCCESS ce/task only."""

    def test_success_with_analysis_id(self) -> None:
        client = _StubSonarClient(analysis_id="AX-7", ce_status="SUCCESS")
        assert resolve_analysis_id(client, "CE-1") == "AX-7"  # type: ignore[arg-type]

    def test_empty_ce_task_id_fails_closed(self) -> None:
        with pytest.raises(SonarApiError, match="without a ceTaskId"):
            resolve_analysis_id(_StubSonarClient(), "")  # type: ignore[arg-type]

    def test_pending_fails_closed(self) -> None:
        client = _StubSonarClient(ce_status="PENDING")
        with pytest.raises(SonarApiError, match="not terminal SUCCESS"):
            resolve_analysis_id(client, "CE-1")  # type: ignore[arg-type]

    def test_failed_fails_closed(self) -> None:
        client = _StubSonarClient(ce_status="FAILED")
        with pytest.raises(SonarApiError, match="not terminal SUCCESS"):
            resolve_analysis_id(client, "CE-1")  # type: ignore[arg-type]

    def test_success_without_analysis_id_fails_closed(self) -> None:
        @dataclass
        class _NoAnalysisId(_StubSonarClient):
            def ce_task(self, ce_task_id: str) -> SonarHttpResponse:  # type: ignore[override]
                del ce_task_id
                return SonarHttpResponse(
                    status_code=200, json_body={"task": {"status": "SUCCESS"}}
                )

        with pytest.raises(SonarApiError, match="no analysisId"):
            resolve_analysis_id(_NoAnalysisId(), "CE-1")  # type: ignore[arg-type]


class TestBuildIssueApplier:
    def test_applier_calls_transition_and_tags(self) -> None:
        client = _StubSonarClient()
        applier = build_issue_applier(client)  # type: ignore[arg-type]
        applier("K9")
        assert client.transitioned == [("K9", "accept")]

    def test_applier_fail_closed(self) -> None:
        applier = build_issue_applier(_StubSonarClient(transition_should_fail=True))  # type: ignore[arg-type]
        with pytest.raises(ReconcilerApplyError):
            applier("K9")


def test_ledger_entries_passed_through() -> None:
    entry = AcceptedExceptionLedgerEntry(
        rule_key="python:S1192",
        file_path="src/a.py",
        normalized_code_fingerprint="fp-x",
        expected_message_pattern="dup",
        rationale="r",
        approved_by=("a", "b", "c"),
        approved_commit="c0ffee",
        expiry="",
        scope="branch-only",
    )
    ledger = AcceptedExceptionLedger(entries=(entry,))
    client = _StubSonarClient(
        issues=({"key": "K1", "rule": "python:S1192", "hash": "fp-x", "message": "dup"},)
    )
    inputs = _port(client, ledger).resolve_inputs("S-1", None)
    assert inputs.ledger_entries == (entry,)
