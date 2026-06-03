"""Unit tests for the productive SonarGateInputPort adapter (AG3-052 E1/E4).

Only the external HTTP boundary (``SonarClient``) is stubbed (MOCKS-Ausnahme);
the adapter orchestration, fail-closed behaviour and the ``Administer Issues``
applier run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agentkit.config.models import SonarQubeConfig
from agentkit.integrations.sonar import SonarApiError, SonarHttpResponse
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.sonarqube_gate import (
    AcceptedExceptionLedger,
    AcceptedExceptionLedgerEntry,
    BoundAnalysis,
    ConfiguredSonarGateInputPort,
    ReconcilerApplyError,
    SonarApplicability,
    build_issue_applier,
)

_HEAD = "rev-9"


@dataclass
class _StubSonarClient:
    """Stub of the thin HTTP boundary (only the external system is faked)."""

    qg_status: str = "OK"
    revision: str = _HEAD
    version: str = "26.4"
    issues: tuple[dict[str, str], ...] = ()
    transition_should_fail: bool = False
    transitioned: list[tuple[str, str]] = field(default_factory=list)
    tagged: list[tuple[str, str]] = field(default_factory=list)

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "projectStatus": {
                    "status": self.qg_status,
                    "qualityGateHash": "qgh",
                    "qualityProfileHash": "qph",
                    "analysisScopeHash": "ash",
                    "period": {"mode": "PREVIOUS_VERSION"},
                }
            },
        )

    def component_revision(self, component: str, branch: str | None = None) -> SonarHttpResponse:
        del component, branch
        return SonarHttpResponse(
            status_code=200, json_body={"component": {"analysisRevision": self.revision}}
        )

    def system_status(self) -> SonarHttpResponse:
        return SonarHttpResponse(status_code=200, json_body={"version": self.version})

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
    )


def _bound() -> BoundAnalysis:
    return BoundAnalysis(
        analysis_id="AX-1",
        ce_task_id="CE-1",
        component="proj",
        branch="feature",
        commit_sha="c0ffee",
        tree_hash="deadbeef",
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
