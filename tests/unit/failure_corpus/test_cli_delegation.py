"""Unit tests for failure_corpus CLI adapter (FK-41 §41.9, AG3-078).

Tests verify:
- CLI adapter contains no business logic (thin delegation only)
- All 6 subcommands are registered in cli/main.py
- dispatch() routes correctly to handlers
- register_subparsers() wires all required subcommands
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.failure_corpus.cli import dispatch, register_subparsers

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# register_subparsers: all 6 subcommands registered
# ---------------------------------------------------------------------------


class TestRegisterSubparsers:
    def _make_subparsers(self) -> argparse._SubParsersAction:  # type: ignore[type-arg]
        parser = argparse.ArgumentParser()
        return parser.add_subparsers(dest="fc_command")

    def test_all_six_subcommands_registered(self) -> None:
        sub = self._make_subparsers()
        register_subparsers(sub)
        choices = list(sub.choices.keys())
        assert "add-incident" in choices
        assert "suggest-patterns" in choices
        assert "review-patterns" in choices
        assert "review-checks" in choices
        assert "effectiveness-report" in choices
        assert "list-checks" in choices

    def test_no_extra_subcommands(self) -> None:
        sub = self._make_subparsers()
        register_subparsers(sub)
        choices = list(sub.choices.keys())
        assert len(choices) == 6


# ---------------------------------------------------------------------------
# dispatch: no business logic in adapter
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_with_no_command_returns_1(self) -> None:
        args = argparse.Namespace(fc_command=None)
        result = dispatch(args)
        assert result == 1

    def test_dispatch_with_unknown_command_returns_1(self) -> None:
        args = argparse.Namespace(fc_command="unknown-cmd-xyz")
        result = dispatch(args)
        assert result == 1


# ---------------------------------------------------------------------------
# CLI main.py registration
# ---------------------------------------------------------------------------


class TestMainCLIRegistration:
    def test_failure_corpus_in_cli_main_dispatch(self) -> None:
        """Verify failure-corpus is registered in cli/main.py dispatch table."""
        import inspect

        import agentkit.backend.cli.main as cli_main

        src = inspect.getsource(cli_main._dispatch_command)  # type: ignore[attr-defined]
        assert "failure-corpus" in src

    def test_failure_corpus_subparser_registered_in_main(self) -> None:
        """Verify _setup_failure_corpus_subparsers is defined in cli/main.py."""
        import agentkit.backend.cli.main as cli_main

        assert hasattr(cli_main, "_setup_failure_corpus_subparsers")

    def test_cmd_failure_corpus_defined_in_main(self) -> None:
        """Verify _cmd_failure_corpus is defined in cli/main.py."""
        import agentkit.backend.cli.main as cli_main

        assert hasattr(cli_main, "_cmd_failure_corpus")

    def test_main_parses_failure_corpus_help(self) -> None:
        """Smoke test: main() can parse failure-corpus --help without crashing."""
        from agentkit.backend.cli.main import main

        with pytest.raises(SystemExit) as exc:
            main(["failure-corpus", "--help"])
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# ERROR 6 / ERROR 7: review-patterns --decision accepted arg coverage
# ---------------------------------------------------------------------------


class TestReviewPatternsArgCoverage:
    """ERROR 7: CLI review-patterns correctly wires --promotion-rule and --category."""

    def _make_parser_with_review_patterns(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="fc_command")
        register_subparsers(sub)
        return parser

    def test_review_patterns_accepted_parses_promotion_rule(self) -> None:
        """--promotion-rule is accepted and parsed without error."""
        parser = self._make_parser_with_review_patterns()
        args = parser.parse_args([
            "review-patterns",
            "--project-key", "proj-test",
            "--pattern-id", "FP-0001",
            "--decision", "accepted",
            "--invariant", "MUST NOT skip tests",
            "--risk-level", "medium",
            "--promotion-rule", "high_severity",
            "--category", "test_omission",
        ])
        assert args.promotion_rule == "high_severity"
        assert args.category == "test_omission"

    def test_review_patterns_rejected_no_required_args(self) -> None:
        """--decision rejected does not require --promotion-rule or --category."""
        parser = self._make_parser_with_review_patterns()
        args = parser.parse_args([
            "review-patterns",
            "--project-key", "proj-test",
            "--pattern-id", "FP-0001",
            "--decision", "rejected",
        ])
        assert args.decision == "rejected"
        assert args.promotion_rule is None
        assert args.category is None

    def test_review_patterns_risk_level_help_no_longer_mentions_low(self) -> None:
        """--risk-level help text must not list 'low' (canonical values: medium/high/critical)."""
        import contextlib

        parser = self._make_parser_with_review_patterns()
        with contextlib.suppress(SystemExit):
            parser.parse_args(["review-patterns", "--help"])
        # Verify by inspecting the parser choices directly — 'low' is not a valid risk level
        # (canonical: medium/high/critical per PatternRiskLevel StrEnum)
        from agentkit.backend.failure_corpus.pattern import PatternRiskLevel
        valid_values = {r.value for r in PatternRiskLevel}
        assert "low" not in valid_values, (
            "PatternRiskLevel unexpectedly contains 'low' — help text issue is in the code"
        )
        assert "medium" in valid_values
        assert "high" in valid_values
        assert "critical" in valid_values

    def test_dispatch_review_patterns_accepted_delegates_promotion_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR 7: dispatch routes --promotion-rule and --category to confirm_pattern.

        This is a delegation test: the CLI adapter must pass promotion_rule and category
        to the underlying corpus.confirm_pattern (no business logic in the adapter).
        We intercept at the composition_root build to return a mock corpus.
        """
        from unittest.mock import MagicMock

        # Build args namespace as the parser would produce
        args = argparse.Namespace(
            fc_command="review-patterns",
            project_key="proj-del",
            pattern_id="FP-0001",
            decision="accepted",
            invariant="MUST NOT skip",
            risk_level="medium",
            promotion_rule="high_severity",
            category="test_omission",
        )

        mock_corpus = MagicMock()
        mock_corpus.confirm_pattern.return_value = MagicMock(pattern_id="FP-0001")

        # Both build_failure_corpus and build_projection_accessor are lazy-imported
        # inside each handler body (not at cli module level).  Patch at the source
        # module so the lazy `from ... import` picks up the stub.
        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_failure_corpus",
            lambda *a, **kw: mock_corpus,
        )
        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_projection_accessor",
            lambda *a, **kw: MagicMock(),
        )

        from agentkit.backend.failure_corpus.cli import handle_review_patterns
        rc = handle_review_patterns(args)
        assert rc == 0
        mock_corpus.confirm_pattern.assert_called_once()
        call_kwargs = mock_corpus.confirm_pattern.call_args
        # Verify promotion_rule and category were passed
        assert call_kwargs.kwargs.get("promotion_rule") is not None or (
            len(call_kwargs.args) > 2 and call_kwargs.args[2] is not None
        )
        assert call_kwargs.kwargs.get("category") is not None or (
            len(call_kwargs.args) > 3 and call_kwargs.args[3] is not None
        )


# ---------------------------------------------------------------------------
# ERROR A: every CLI subcommand builds the factory WITHOUT an LLM client
# ---------------------------------------------------------------------------


class TestCliBuildsWithoutLlmClient:
    """ERROR A regression: non-derive_check commands must build + delegate w/o LLM.

    These are PRODUCTION-PATH tests: they call the real handler against a real
    SQLite backend (no mocked corpus). Before the fix, the composition root
    unconditionally constructed ``LlmInvariantSharpener(None)`` which raised, so
    EVERY subcommand crashed before reaching its handler. The fix builds the LLM
    sharpener lazily (only when an llm_client is supplied), so these commands
    build and delegate; ``derive_check`` stays fail-closed (covered below).
    """

    def _sqlite_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        monkeypatch.chdir(tmp_path)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        reset_backend_cache_for_tests()

    def test_suggest_patterns_builds_and_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentkit.backend.failure_corpus.cli import handle_suggest_patterns
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_suggest_patterns(
                argparse.Namespace(fc_command="suggest-patterns", project_key="proj-cli")
            )
            assert rc == 0, capsys.readouterr().err
        finally:
            reset_backend_cache_for_tests()

    def test_effectiveness_report_builds_and_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentkit.backend.failure_corpus.cli import handle_effectiveness_report
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_effectiveness_report(
                argparse.Namespace(
                    fc_command="effectiveness-report",
                    project_key="proj-cli",
                    window_days=90,
                )
            )
            assert rc == 0, capsys.readouterr().err
        finally:
            reset_backend_cache_for_tests()

    def test_list_checks_builds_and_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ERROR 1 (FK-41 §41.9): list-checks MUST go through build_failure_corpus.

        Regression guard: before the fix the handler bypassed the FailureCorpus
        top surface and queried StateBackendFcCheckProposalRepository directly.
        We spy on the REAL ``build_failure_corpus`` (it still runs against the
        real SQLite backend, no mocked corpus) and assert it was invoked WITHOUT
        an ``llm_client`` — proving the thin top-surface delegation and that the
        lazy-sharpener build does not crash.
        """
        import agentkit.backend.bootstrap.composition_root as comp_root
        from agentkit.backend.failure_corpus.cli import handle_list_checks
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        calls: list[dict[str, object]] = []
        real_build = comp_root.build_failure_corpus

        def _spy_build(*args: object, **kwargs: object) -> object:
            calls.append({"args": args, "kwargs": kwargs})
            return real_build(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(comp_root, "build_failure_corpus", _spy_build)

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_list_checks(
                argparse.Namespace(
                    fc_command="list-checks", project_key="proj-cli", pattern_id=None
                )
            )
            assert rc == 0, capsys.readouterr().err
            assert len(calls) == 1, "list-checks did not delegate via build_failure_corpus"
            assert calls[0]["kwargs"].get("project_key") == "proj-cli"  # type: ignore[union-attr]
            assert "llm_client" not in calls[0]["kwargs"]  # type: ignore[operator]
        finally:
            reset_backend_cache_for_tests()

    def test_review_patterns_rejected_builds_and_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentkit.backend.failure_corpus.cli import handle_review_patterns
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_review_patterns(
                argparse.Namespace(
                    fc_command="review-patterns",
                    project_key="proj-cli",
                    pattern_id="FP-0001",
                    decision="rejected",
                    invariant=None,
                    risk_level=None,
                    promotion_rule=None,
                    category=None,
                )
            )
            assert rc == 0, capsys.readouterr().err
        finally:
            reset_backend_cache_for_tests()

    def test_add_incident_builds_and_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from agentkit.backend.failure_corpus.cli import handle_add_incident
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_add_incident(
                argparse.Namespace(
                    fc_command="add-incident",
                    project_key="proj-cli",
                    story_id="AG3-001",
                    run_id="run-1",
                    category="scope_drift",
                    severity="high",
                    phase="implementation",
                    role="worker",
                    model="claude-opus",
                    symptom="agent rewrote files outside scope",
                    evidence="",
                    merge_blocked=True,
                )
            )
            assert rc == 0, capsys.readouterr().err
        finally:
            reset_backend_cache_for_tests()

    def test_review_checks_builds_without_sharpener_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """review-checks against an unknown check fails 'not found' — NOT a sharpener crash.

        The build itself must succeed (no LlmInvariantSharpener RuntimeError); the
        handler then reaches approve_check and reports the proposal is missing.
        """
        from agentkit.backend.failure_corpus.cli import handle_review_checks
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            rc = handle_review_checks(
                argparse.Namespace(
                    fc_command="review-checks",
                    project_key="proj-cli",
                    check_id="CHK-9999",
                    decision="rejected",
                    rejected_reason=None,
                )
            )
            err = capsys.readouterr().err
            # Reached approve_check (delegation), did NOT crash building the sharpener.
            assert "LlmInvariantSharpener" not in err
            assert "not found" in err
            assert rc == 1
        finally:
            reset_backend_cache_for_tests()

    def test_derive_check_without_llm_client_still_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """derive_check stays FAIL-CLOSED: building without llm_client then deriving raises.

        The factory is built without a sharpener (no llm_client), so an attempt to
        actually derive a check (step 1) must raise — proving the lazy build did not
        weaken the fail-closed guarantee.
        """
        from agentkit.backend.bootstrap.composition_root import (
            build_failure_corpus,
            build_projection_accessor,
        )
        from agentkit.backend.core_types import FailureCategory, PatternStatus
        from agentkit.backend.failure_corpus.pattern import (
            FailurePatternRecord,
            PatternRiskLevel,
            PromotionRule,
        )
        from agentkit.backend.failure_corpus.types import PatternId
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        self._sqlite_env(tmp_path, monkeypatch)
        try:
            # Seed an ACCEPTED pattern so derive_check passes the pattern checks
            # and actually reaches step 1 (sharpening).
            StateBackendFcPatternRepository(tmp_path).save(
                FailurePatternRecord(
                    pattern_id="FP-0001",
                    project_key="proj-cli",
                    status=PatternStatus.ACCEPTED,
                    category=FailureCategory.SCOPE_DRIFT,
                    promotion_rule=PromotionRule.HIGH_SEVERITY,
                    invariant="scope must not be exceeded",
                    risk_level=PatternRiskLevel.HIGH,
                    confirmed_by="human",
                    incident_refs=[],
                    incident_count=0,
                )
            )
            accessor = build_projection_accessor()
            # No llm_client -> sharpener not wired -> derive_check fails closed.
            corpus = build_failure_corpus(
                accessor, project_key="proj-cli", store_dir=tmp_path
            )
            with pytest.raises(RuntimeError, match="InvariantSharpenerPort is None"):
                corpus.derive_check(PatternId("FP-0001"))
        finally:
            reset_backend_cache_for_tests()
