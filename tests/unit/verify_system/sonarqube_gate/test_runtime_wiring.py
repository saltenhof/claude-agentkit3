"""Unit tests for the per-run sonarqube_gate port wiring (AG3-052 E1).

Proves the QA-subflow anchor builds the PRODUCTIVE port for an
``available == true`` run and FAILS CLOSED (APPLICABLE, attestation=None)
when the per-run scan coordinates are missing — never a silent absent skip
(FK-33 §33.6.5). Only the external HTTP boundary is faked; the coordinate
resolution + fail-closed logic runs for real against a real git worktree.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from agentkit.config.models import SonarQubeConfig
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.sonarqube_gate import (
    ConfiguredSonarGateInputPort,
    SonarApplicability,
    build_sonar_gate_port_for_run,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    """Create a real git repo with a main branch and one commit."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@e.st")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")


def _write_report_task(root: Path, *, project_key: str = "proj") -> None:
    scan = root / ".scannerwork"
    scan.mkdir(parents=True, exist_ok=True)
    (scan / "report-task.txt").write_text(
        "\n".join(
            (
                f"projectKey={project_key}",
                "serverUrl=http://sonar:9901",
                "serverVersion=26.4.0.1",
                # A REAL report-task.txt carries only ceTaskId (ERROR-A) and NO
                # top-level branch (ERROR-2); the branch is derived from git.
                "ceTaskId=CE-123",
                "ceTaskUrl=http://sonar:9901/api/ce/task?id=CE-123",
                "dashboardUrl=http://sonar:9901/dashboard?id=proj",
            )
        ),
        encoding="utf-8",
    )


def _config(*, available: bool = True) -> SonarQubeConfig:
    if not available:
        return SonarQubeConfig(available=False, enabled=False)
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONARQUBE_TOKEN_TEST",
        scanner_version="5.0.1",
    )


def _ctx(root: Path, *, mode: StoryMode | None = StoryMode.EXECUTION) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=mode,
        project_root=root,
        worktree_path=root,
    )


def _fast_ctx(root: Path) -> StoryContext:
    """A GENUINE code-producing StoryContext in ``fast`` mode (FK-24 §24.3.3).

    Built through the NORMAL constructor/validation path: ``mode=fast`` is a
    SEPARATE axis from ``execution_route`` (which stays a valid EXECUTION
    path). No ``model_construct`` workaround — the runtime state is exactly
    what the production derivation produces for a fast impl/bugfix story.
    """
    return StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.FAST,
        project_root=root,
        worktree_path=root,
    )


class TestNotApplicableByConfig:
    def test_available_false_returns_none(self, tmp_path: Path) -> None:
        port = build_sonar_gate_port_for_run(
            _config(available=False), _ctx(tmp_path), tmp_path
        )
        assert port is None

    def test_no_stanza_returns_none(self, tmp_path: Path) -> None:
        port = build_sonar_gate_port_for_run(None, _ctx(tmp_path), tmp_path)
        assert port is None


class TestFastResolvesGenuineNotApplicableFast:
    """E2: a Sonar-configured run in fast mode resolves GENUINELY to FAST.

    The builder must NOT return ``None`` (which would route through the absent
    default port to ``NOT_APPLICABLE_UNAVAILABLE``); it returns a port whose
    ``resolve_inputs`` reports ``NOT_APPLICABLE_FAST`` — runtime
    distinguishable from ``available == false``. The full fast terminal
    (Policy-skip via the tests-green floor) stays FK-24 §24.3.4 / FK-27.
    """

    def test_builder_fast_returns_fast_port_not_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        port = build_sonar_gate_port_for_run(
            _config(), _fast_ctx(tmp_path), tmp_path
        )
        assert port is not None  # NOT the absent (None) skip path
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        assert inputs.applicability is SonarApplicability.NOT_APPLICABLE_FAST

    def test_anchor_fast_resolves_fast_distinct_from_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """E2 via the REAL phase anchor: fast => genuine NOT_APPLICABLE_FAST.

        Distinct from ``available == false`` (which resolves
        NOT_APPLICABLE_UNAVAILABLE via the absent port / None).
        """
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _init_repo(tmp_path)
        _write_report_task(tmp_path)
        _write_project_config(tmp_path, available=True)
        port = _resolve_sonar_gate_port(_fast_ctx(tmp_path), tmp_path)
        assert port is not None  # genuine FAST port, NOT the absent skip
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        assert inputs.applicability is SonarApplicability.NOT_APPLICABLE_FAST


class TestApplicableProductive:
    def test_available_true_with_scan_builds_configured_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _init_repo(tmp_path)
        _write_report_task(tmp_path)
        port = build_sonar_gate_port_for_run(_config(), _ctx(tmp_path), tmp_path)
        assert isinstance(port, ConfiguredSonarGateInputPort)
        assert port.bound_analysis.component == "proj"
        assert port.bound_analysis.ce_task_id == "CE-123"
        # ERROR-A: the analysisId is NOT read from the artefact (resolved later
        # via ce/task); the scanner version is the AK3-pinned config value.
        assert port.bound_analysis.scanner_version == "5.0.1"
        assert port.bound_analysis.commit_sha  # bound to the real HEAD
        assert port.main_head_revision  # main HEAD resolved


class TestApplicableFailClosed:
    """available:true but coordinates missing => fail-closed, NEVER absent."""

    def test_missing_report_task_fails_closed_applicable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _init_repo(tmp_path)  # repo exists, but NO report-task.txt
        port = build_sonar_gate_port_for_run(_config(), _ctx(tmp_path), tmp_path)
        assert port is not None  # NOT the absent (None) skip path
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        # FK-33 §33.6.5: configured-but-unreachable stays APPLICABLE and
        # blocks (attestation=None => gate fail-closed), never not-applicable.
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_missing_token_fails_closed_applicable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SONARQUBE_TOKEN_TEST", raising=False)
        _init_repo(tmp_path)
        _write_report_task(tmp_path)
        port = build_sonar_gate_port_for_run(_config(), _ctx(tmp_path), tmp_path)
        assert port is not None
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_no_git_repo_fails_closed_applicable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _write_report_task(tmp_path)  # report-task present, but not a git repo
        port = build_sonar_gate_port_for_run(_config(), _ctx(tmp_path), tmp_path)
        assert port is not None
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None


def _write_project_config(root: Path, *, available: bool) -> None:
    """Write a code-producing project.yaml with an explicit sonarqube stanza."""
    cfg_dir = root / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sonar = (
        "    available: true\n"
        "    enabled: true\n"
        "    base_url: http://sonar:9901\n"
        "    token_env: SONARQUBE_TOKEN_TEST\n"
        "    scanner_version: 5.0.1\n"
        if available
        else "    available: false\n    enabled: false\n"
    )
    (cfg_dir / "project.yaml").write_text(
        "project_key: proj\n"
        "project_name: Proj\n"
        "repositories:\n  - name: app\n    path: .\n"
        # AG3-056: code-producing project must declare the ci stanza too;
        # an explicit opt-out keeps this Sonar-wiring test isolated.
        "pipeline:\n  ci:\n    available: false\n    enabled: false\n"
        "  sonarqube:\n" + sonar,
        encoding="utf-8",
    )


class TestPhaseAnchorResolvesPort:
    """E1: the implementation-phase anchor wires the port from project config."""

    def test_anchor_builds_productive_port_when_available_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _init_repo(tmp_path)
        _write_report_task(tmp_path)
        _write_project_config(tmp_path, available=True)
        port = _resolve_sonar_gate_port(_ctx(tmp_path), tmp_path)
        assert isinstance(port, ConfiguredSonarGateInputPort)

    def test_anchor_returns_none_when_available_false(self, tmp_path: Path) -> None:
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        _write_project_config(tmp_path, available=False)
        port = _resolve_sonar_gate_port(_ctx(tmp_path), tmp_path)
        assert port is None  # absent default applies (declared skip)

    def test_anchor_returns_none_without_project_root(self, tmp_path: Path) -> None:
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        ctx = StoryContext(
            project_key="proj",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=None,
        )
        assert _resolve_sonar_gate_port(ctx, tmp_path) is None

    def test_anchor_fails_closed_when_available_true_but_no_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        monkeypatch.setenv("SONARQUBE_TOKEN_TEST", "tok")
        _init_repo(tmp_path)  # repo but no report-task.txt
        _write_project_config(tmp_path, available=True)
        port = _resolve_sonar_gate_port(_ctx(tmp_path), tmp_path)
        assert port is not None  # NOT the absent skip
        inputs = port.resolve_inputs("AG3-001", tmp_path)
        assert inputs.applicability is SonarApplicability.APPLICABLE
        assert inputs.attestation is None

    def test_anchor_propagates_config_error_no_silent_skip(
        self, tmp_path: Path
    ) -> None:
        """E1: an unloadable/invalid run-config PROPAGATES — never silent skip.

        Wurzelbehebung: the E6 hard-fail (a code-producing project that OMITS
        the sonarqube stanza) raises a ``ConfigError`` on load. The anchor must
        NOT swallow it into ``None`` (which would route to ABSENT_SONAR_GATE
        => NOT_APPLICABLE_UNAVAILABLE, a silent inert skip). It must propagate
        fail-closed (FK-33 §33.6.5, FAIL-CLOSED, ZERO DEBT).
        """
        import pytest as _pytest

        from agentkit.exceptions import ConfigError
        from agentkit.implementation.phase import _resolve_sonar_gate_port

        # Code-producing project (default story_types include implementation)
        # with NO sonarqube stanza => E6 config-load ConfigError.
        cfg_dir = tmp_path / ".agentkit" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "project.yaml").write_text(
            "project_key: proj\n"
            "project_name: Proj\n"
            "repositories:\n  - name: app\n    path: .\n"
            "pipeline:\n  max_feedback_rounds: 3\n",
            encoding="utf-8",
        )
        with _pytest.raises(ConfigError):
            _resolve_sonar_gate_port(_ctx(tmp_path), tmp_path)
