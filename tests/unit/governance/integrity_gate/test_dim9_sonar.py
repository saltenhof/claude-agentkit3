"""Unit tests for IntegrityGate Dimension 9 — SONARQUBE_GREEN (FK-35 §35.2.4a).

Two layers (AG3-034 Remediation R2-C/A2/G):

1. ``verify_sonarqube_green`` is a thin MAPPER of the canonical AG3-052
   :class:`SonarGateOutcome` onto a ``DimensionResult`` — it re-implements NONE
   of the §35.2.4a conditions (those live in ``evaluate_sonarqube_gate``, tested
   in ``tests/unit/verify_system/sonarqube_gate/test_gate.py``).  These tests pin
   the mapping: green outcome -> PASS; failed/missing outcome -> fail-closed.
2. ``ProductiveSonarDimensionPort`` is the genuine AG3-052 CONSUMER: it routes
   the gate context through ``build_sonar_gate_port_for_run`` +
   ``evaluate_sonarqube_gate``.  The consumer-path tests stub ONLY the
   capability/HTTP boundary (the loaders + the Sonar client), exercising the
   real applicability resolution and the real evaluator (no second mechanic, no
   None-stub loader).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance.integrity_gate.dim9_sonar import (
    SONAR_NOT_GREEN,
    Dim9Resolution,
    verify_sonarqube_green,
)
from agentkit.governance.integrity_gate.dimensions import IntegrityDimension
from agentkit.verify_system.sonarqube_gate import SonarApplicability, SonarGateOutcome

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Layer 1 — verify_sonarqube_green maps the AG3-052 outcome (no re-evaluation).
# ---------------------------------------------------------------------------


def _resolution(outcome: SonarGateOutcome | None) -> Dim9Resolution:
    return Dim9Resolution(
        applicability=SonarApplicability.APPLICABLE, outcome=outcome
    )


def test_green_outcome_maps_to_pass() -> None:
    outcome = SonarGateOutcome(
        applicability=SonarApplicability.APPLICABLE,
        passed=True,
        gate_status="sonarqube_gate_passed",
    )
    result = verify_sonarqube_green(_resolution(outcome))
    assert result.passed is True
    assert result.dimension is IntegrityDimension.SONARQUBE_GREEN
    assert result.failure_reason is None


def test_failed_outcome_maps_to_fail_closed() -> None:
    outcome = SonarGateOutcome(
        applicability=SonarApplicability.APPLICABLE,
        passed=False,
        gate_status="failed",
        failure_reason="stale_attestation: last_analyzed_revision=...",
    )
    result = verify_sonarqube_green(_resolution(outcome))
    assert result.passed is False
    assert result.failure_reason == SONAR_NOT_GREEN
    assert "stale_attestation" in result.detail


def test_missing_outcome_on_applicable_fails_closed() -> None:
    # APPLICABLE but the capability produced no outcome (configured-but-
    # unreachable) -> fail-closed, never a silent pass.
    result = verify_sonarqube_green(_resolution(None))
    assert result.passed is False
    assert result.failure_reason == SONAR_NOT_GREEN
    assert "configured-but-unreachable" in result.detail


@pytest.mark.parametrize(
    "applicability",
    [
        SonarApplicability.NOT_APPLICABLE_UNAVAILABLE,
        SonarApplicability.NOT_APPLICABLE_FAST,
    ],
)
def test_not_applicable_is_dropped_upstream(
    applicability: SonarApplicability,
) -> None:
    # dimensions_for omits Dim 9 when not applicable; verify_sonarqube_green is
    # never reached for these.  Asserted via the dimensions_for contract here.
    from agentkit.governance.integrity_gate.dimensions import dimensions_for
    from agentkit.story_context_manager.types import StoryType

    assert IntegrityDimension.SONARQUBE_GREEN not in dimensions_for(
        StoryType.IMPLEMENTATION, sonar_applicable=False
    )
    assert applicability is not SonarApplicability.APPLICABLE


# ---------------------------------------------------------------------------
# Layer 2 — ProductiveSonarDimensionPort genuinely CONSUMES the AG3-052 API.
# ---------------------------------------------------------------------------

from agentkit.governance.integrity_gate import IntegrityGateContext  # noqa: E402
from agentkit.governance.integrity_gate.dim9_port import (  # noqa: E402
    ProductiveSonarDimensionPort,
)
from agentkit.story_context_manager.models import StoryContext  # noqa: E402
from agentkit.story_context_manager.story_model import WireStoryMode  # noqa: E402
from agentkit.story_context_manager.types import StoryMode, StoryType  # noqa: E402


def _gate_ctx(story_dir: Path) -> IntegrityGateContext:
    return IntegrityGateContext(
        story_dir=story_dir, story_type=StoryType.IMPLEMENTATION
    )


def _impl_context(project_root: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.STANDARD,
        project_root=project_root,
        title="dim9 consumer",
    )


def test_consumer_path_no_config_is_not_applicable_skip(tmp_path: Path) -> None:
    # build_sonar_gate_port_for_run(None, ...) returns None (deliberate absence)
    # -> Dim 9 NOT_APPLICABLE skip (FK-33 §33.6.5).  The consumer path resolves
    # this through the REAL build_sonar_gate_port_for_run (no stub of it).
    ctx = _impl_context(tmp_path)
    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: None,  # no sonar config (deliberate absence)
        lambda gate_ctx: ctx,
    )
    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.NOT_APPLICABLE_UNAVAILABLE
    assert resolution.outcome is None


def test_consumer_path_applicable_missing_scan_fails_closed(tmp_path: Path) -> None:
    # available==true but NO scan artefact in the worktree (Closure pre-merge
    # scan OOS) -> build_sonar_gate_port_for_run returns a fail-closed APPLICABLE
    # port (attestation=None) and evaluate_sonarqube_gate yields a failed outcome
    # -> the consumer path surfaces a failed SonarGateOutcome (NOT a None-stub).
    from agentkit.config.models import SonarQubeConfig

    config = SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar.invalid:9901",
        token_env="SONAR_TOKEN_TEST",
    )
    ctx = _impl_context(tmp_path)  # no .scannerwork/report-task.txt present
    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: config,
        lambda gate_ctx: ctx,
    )
    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.APPLICABLE
    assert resolution.outcome is not None
    assert resolution.outcome.passed is False
    assert resolution.outcome.gate_status == "failed"
    # And the Dim-9 mapper turns that into a fail-closed result.
    dim9 = verify_sonarqube_green(resolution)
    assert dim9.passed is False
    assert dim9.failure_reason == SONAR_NOT_GREEN


def test_consumer_path_unreadable_context_fails_closed(tmp_path: Path) -> None:
    # A code story whose context is unresolvable -> APPLICABLE-but-unresolvable
    # -> Dim 9 fails closed (cannot prove a deliberate skip).
    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: None,
        lambda gate_ctx: None,  # unreadable context
    )
    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.APPLICABLE
    assert resolution.outcome is None
    dim9 = verify_sonarqube_green(resolution)
    assert dim9.passed is False
    assert dim9.failure_reason == SONAR_NOT_GREEN


# ---------------------------------------------------------------------------
# Layer 2b — the GENUINE GREEN consumer path (R3-G): ProductiveSonarDimensionPort
# routes through the REAL build_sonar_gate_port_for_run + the REAL
# ConfiguredSonarGateInputPort.resolve_inputs + the REAL evaluate_sonarqube_gate;
# only the external HTTP boundary (SonarClient) is faked (MOCKS exception).  A
# commit-bound green attestation => Dim 9 PASS.
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402

from agentkit.config.models import SonarQubeConfig  # noqa: E402


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(root: Path) -> str:
    """Create a real one-commit git repo on ``main``; return its HEAD revision."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@e.st")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return _git(root, "rev-parse", "HEAD")


def _write_report_task(root: Path) -> None:
    scan = root / ".scannerwork"
    scan.mkdir(parents=True, exist_ok=True)
    (scan / "report-task.txt").write_text(
        "\n".join(
            (
                "projectKey=proj",
                "serverUrl=http://sonar:9901",
                "branch=feature/x",
                "ceTaskId=CE-123",
                "analysisId=AX-123",
            )
        ),
        encoding="utf-8",
    )


class _GreenSonarClient:
    """Stub of the thin HTTP boundary only (MOCKS exception, FK-33 §33.6.5).

    Returns a green quality gate, the bound ``revision`` (== main HEAD so the
    stale-check passes) and zero open issues so the REAL evaluator yields green.
    """

    def __init__(self, revision: str) -> None:
        self._revision = revision

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "projectStatus": {
                    "status": "OK",
                    "qualityGateHash": "qgh",
                    "qualityProfileHash": "qph",
                    "analysisScopeHash": "ash",
                    "period": {"mode": "PREVIOUS_VERSION"},
                }
            },
        )

    def component_revision(self, component: str, branch: str | None = None) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        del component, branch
        return SonarHttpResponse(
            status_code=200,
            json_body={"component": {"analysisRevision": self._revision}},
        )

    def system_status(self) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        return SonarHttpResponse(status_code=200, json_body={"version": "26.4"})

    def search_issues(self, params: object) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        del params
        return SonarHttpResponse(status_code=200, json_body={"issues": []})


def _green_config() -> SonarQubeConfig:
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONARQUBE_TOKEN_TEST",
    )


def test_consumer_path_green_attestation_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3-G(a): the GENUINE green consumer path => Dim 9 PASS.

    ProductiveSonarDimensionPort -> REAL build_sonar_gate_port_for_run -> REAL
    ConfiguredSonarGateInputPort.resolve_inputs -> REAL evaluate_sonarqube_gate.
    Only the SonarClient HTTP boundary is faked; the applicability resolution,
    git commit-binding, ledger reconcile, post-apply re-read and green criterion
    all run for real. Worktree HEAD == main HEAD (one-commit repo on ``main``),
    so the bound revision matches and the stale-check passes.
    """
    monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
    head = _init_repo(tmp_path)
    _write_report_task(tmp_path)

    # Fake ONLY the external HTTP client (the integrations.sonar boundary).
    from agentkit.verify_system.sonarqube_gate import runtime_wiring

    monkeypatch.setattr(
        runtime_wiring,
        "_build_client",
        lambda config, token: _GreenSonarClient(head),
    )

    ctx = StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.STANDARD,
        project_root=tmp_path,
        worktree_path=tmp_path,
        title="dim9 green consumer",
    )
    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: _green_config(),
        lambda gate_ctx: ctx,
    )

    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.APPLICABLE
    assert resolution.outcome is not None
    assert resolution.outcome.passed is True
    assert resolution.outcome.gate_status == "sonarqube_gate_passed"
    dim9 = verify_sonarqube_green(resolution)
    assert dim9.passed is True
    assert dim9.failure_reason is None


# ---------------------------------------------------------------------------
# Layer 2c — the GENUINE RED + STALE consumer paths (R4-G): same real wiring as
# 2b (ProductiveSonarDimensionPort -> REAL build_sonar_gate_port_for_run -> REAL
# ConfiguredSonarGateInputPort.resolve_inputs -> REAL evaluate_sonarqube_gate);
# ONLY the SonarClient HTTP boundary is faked (MOCKS exception).  No hand-built
# SonarGateOutcome.  A red quality gate / a stale (mismatching) analysisRevision
# => Dim 9 fail-closed.
# ---------------------------------------------------------------------------


class _RedSonarClient(_GreenSonarClient):
    """HTTP-boundary stub: bound revision matches (not stale) but QG is RED.

    Inherits the green client's matching ``component_revision`` (so the
    commit-binding/stale-check PASSES) and overrides only ``project_status`` to
    report a red quality gate (``status == "ERROR"``).  The REAL post-apply
    re-read then sees the red verdict => the REAL evaluator yields ``failed``
    (``red_gate``).
    """

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "projectStatus": {
                    "status": "ERROR",
                    "qualityGateHash": "qgh",
                    "qualityProfileHash": "qph",
                    "analysisScopeHash": "ash",
                    "period": {"mode": "PREVIOUS_VERSION"},
                }
            },
        )


class _StaleSonarClient(_GreenSonarClient):
    """HTTP-boundary stub: QG is OK but the analysed revision is STALE.

    Overrides only ``component_revision`` to return an ``analysisRevision`` that
    does NOT equal the worktree/main HEAD.  The REAL ``_read_last_analyzed_revision``
    surfaces that mismatching revision; the REAL evaluator's commit-binding
    stale-check (``attestation.is_bound_to``) fails => ``failed``
    (``stale_attestation``).  No stale green is ever admitted (FK-33 §33.6.3).
    """

    def component_revision(self, component: str, branch: str | None = None) -> object:
        from agentkit.integrations.sonar import SonarHttpResponse

        del component, branch
        return SonarHttpResponse(
            status_code=200,
            json_body={
                "component": {
                    "analysisRevision": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
                }
            },
        )


def _green_ctx(root: Path) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.STANDARD,
        project_root=root,
        worktree_path=root,
        title="dim9 red/stale consumer",
    )


def test_consumer_path_red_quality_gate_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-G(a): a RED quality gate via the GENUINE consumer path => Dim 9 FAIL.

    The bound revision matches (not stale), so the gate proceeds to the REAL
    post-apply re-read, which reports ``status == "ERROR"``.  The REAL
    evaluator yields ``failed`` (``red_gate``); Dim 9 maps it to fail-closed
    ``SONAR_NOT_GREEN``.  Only the HTTP client is faked.
    """
    monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
    head = _init_repo(tmp_path)
    _write_report_task(tmp_path)

    from agentkit.verify_system.sonarqube_gate import runtime_wiring

    monkeypatch.setattr(
        runtime_wiring,
        "_build_client",
        lambda config, token: _RedSonarClient(head),
    )

    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: _green_config(),
        lambda gate_ctx: _green_ctx(tmp_path),
    )

    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.APPLICABLE
    assert resolution.outcome is not None
    assert resolution.outcome.passed is False
    assert resolution.outcome.gate_status == "failed"
    assert resolution.outcome.failure_reason is not None
    assert "red_gate" in resolution.outcome.failure_reason
    dim9 = verify_sonarqube_green(resolution)
    assert dim9.passed is False
    assert dim9.failure_reason == SONAR_NOT_GREEN


def test_consumer_path_stale_attestation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-G(b): a STALE analysisRevision via the GENUINE consumer path => FAIL.

    The QG would read OK, but the analysed revision (``analysisRevision``) does
    NOT match the worktree/main HEAD.  The REAL evaluator's commit-binding
    stale-check fails BEFORE any green verdict => ``failed``
    (``stale_attestation``); Dim 9 maps it to fail-closed ``SONAR_NOT_GREEN``.
    No stale green is admitted.  Only the HTTP client is faked.
    """
    monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
    head = _init_repo(tmp_path)
    _write_report_task(tmp_path)

    from agentkit.verify_system.sonarqube_gate import runtime_wiring

    monkeypatch.setattr(
        runtime_wiring,
        "_build_client",
        lambda config, token: _StaleSonarClient(head),
    )

    port = ProductiveSonarDimensionPort(
        lambda gate_ctx: _green_config(),
        lambda gate_ctx: _green_ctx(tmp_path),
    )

    resolution = port.resolve_dim9_outcome(_gate_ctx(tmp_path))
    assert resolution.applicability is SonarApplicability.APPLICABLE
    assert resolution.outcome is not None
    assert resolution.outcome.passed is False
    assert resolution.outcome.gate_status == "failed"
    assert resolution.outcome.failure_reason is not None
    assert "stale_attestation" in resolution.outcome.failure_reason
    dim9 = verify_sonarqube_green(resolution)
    assert dim9.passed is False
    assert dim9.failure_reason == SONAR_NOT_GREEN


def test_consumer_path_config_error_propagates_no_silent_skip(
    tmp_path: Path,
) -> None:
    """R3-C/A2: a BROKEN project config PROPAGATES — never a silent Dim-9 skip.

    Mirrors the composition-root truth-boundary loader contract (analog AG3-052
    ``test_anchor_propagates_config_error_no_silent_skip``): the config loader
    raises (broken/unreadable config) and the productive port does NOT swallow it
    into a not-applicable skip. The error propagates fail-closed (FAIL-CLOSED,
    ZERO DEBT).
    """
    from agentkit.exceptions import ConfigError

    def _raising_loader(gate_ctx: object) -> object:
        raise ConfigError("project sonar config is broken/unreadable")

    ctx = StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.STANDARD,
        project_root=tmp_path,
        title="dim9 config-error",
    )
    port = ProductiveSonarDimensionPort(
        _raising_loader,  # type: ignore[arg-type]
        lambda gate_ctx: ctx,
    )
    with pytest.raises(ConfigError):
        port.resolve_dim9_outcome(_gate_ctx(tmp_path))
