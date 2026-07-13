"""Integration test: level-4 feedback fidelity runs a REAL evaluation (AG3-067).

Proves the closure ``ProductiveDocFidelityFeedbackPort`` runs the SAME productive
``ConformanceService.check_fidelity(level=feedback)`` path the Layer-2 reviewers
use -- a real ``StructuredEvaluator`` over an injected Layer-2 ``LlmClient``
(``role=doc_fidelity``), the ``doc-fidelity-feedback.md`` prompt
(``expected_checks=["feedback_fidelity"]``), against the final diff vs the
existing project docs (FK-38 §38.3.1).

The ONLY doubled boundary is the LLM transport itself (a fake-but-real
``LlmClient`` returning a known verdict -- the verify-system external grenze).
Everything else is real: the manifest-index reference resolution, the prompt
bundle materialization, the state-backend run scope, and the verdict mapping.

This replaces the prior "test theatre" that passed only because the level-4 path
crashed (exception-to-warning). Here a PASS verdict yields ``(True, None)`` and a
FAIL verdict yields a NON-BLOCKING warning + failure-corpus incident candidate --
two DISTINCT real outcomes, never a closure blockade (FK-38 §38.3).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.runtime_ports import ProductiveDocFidelityFeedbackPort
from agentkit.backend.installer.paths import PROMPT_BUNDLE_STORE_ENV, prompt_bundle_store_dir
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.prompt_runtime.resources import (
    PROJECT_LOCK_RELPATH,
    load_prompt_template,
)
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "TEST-501"
_RUN_ID = "run-feedback-001"
#: The single conformance template the feedback level materializes (FK-38 §38.3.1).
_FEEDBACK_TEMPLATE = "doc-fidelity-feedback"


@dataclass
class _ScriptedFeedbackLlmClient:
    """Fake-but-real Layer-2 ``LlmClient`` returning a fixed feedback verdict.

    This is a genuine ``LlmClient`` (``complete(*, role, prompt) -> str``): it
    returns the wire JSON the ``StructuredEvaluator`` actually parses, so the
    whole productive evaluation runs for real. ``status`` drives PASS vs FAIL.
    """

    status: str = "PASS"
    calls: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, *, role: str, prompt: str) -> str:
        self.calls.append(role)
        self.prompts.append(prompt)
        return json.dumps(
            [
                {
                    "check_id": "feedback_fidelity",
                    "status": self.status,
                    "reason": f"feedback fidelity {self.status.lower()}",
                }
            ]
        )


def _write_prompt_binding(project_root: Path) -> None:
    """Bind the real ``doc-fidelity-feedback`` template into the project bundle."""
    content = load_prompt_template(_FEEDBACK_TEMPLATE)
    bundle_dir = prompt_bundle_store_dir(
        "project-bound", "99", store_root=project_root / "prompt-bundles"
    )
    (bundle_dir / "internal" / "prompts").mkdir(parents=True)
    (bundle_dir / "internal" / "prompts" / f"{_FEEDBACK_TEMPLATE}.md").write_text(
        content, encoding="utf-8"
    )
    entries = {
        _FEEDBACK_TEMPLATE: {
            "relpath": f"internal/prompts/{_FEEDBACK_TEMPLATE}.md",
            "sha256": sha256(content.encode("utf-8")).hexdigest(),
        }
    }
    manifest_text = json.dumps(
        {"bundle_id": "project-bound", "bundle_version": "99", "templates": entries}
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    (project_root / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(manifest_text.encode("utf-8")).hexdigest(),
                "templates": entries,
            }
        ),
        encoding="utf-8",
    )


def _write_manifest_index(project_root: Path) -> None:
    """Write a curated manifest-index matching the feedback fidelity context."""
    docs = project_root / "concepts"
    guardrails = project_root / "_guardrails"
    docs.mkdir(parents=True, exist_ok=True)
    guardrails.mkdir(parents=True, exist_ok=True)
    (docs / "architecture.md").write_text(
        "# Architecture\n\nExisting project documentation.\n", encoding="utf-8"
    )
    (guardrails / "manifest-index.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "path": "concepts/architecture.md",
                        "scope": "architecture",
                        "modules": ["*"],
                        "story_types": ["implementation"],
                        "tags": ["feedback", "document-fidelity", "*"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _init_git_with_diff(project_root: Path) -> None:
    """Initialise a git repo with a HEAD~1..HEAD diff for the final-diff read."""

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Test")
    (project_root / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", "-f", "base.py")
    _git("commit", "-m", "base")
    (project_root / "feature.py").write_text("y = 2\n", encoding="utf-8")
    _git("add", "-f", "feature.py")
    _git("commit", "-m", "feature")


@pytest.fixture
def _feedback_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    # The SQLite state backend derives the story_id from the directory NAME
    # (``_story_id_for``), so the story_dir must be named after the story_id for
    # the run-scope (flow execution) to resolve.
    project_root = tmp_path / _STORY_ID
    project_root.mkdir()
    _init_git_with_diff(project_root)
    _write_manifest_index(project_root)
    _write_prompt_binding(project_root)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(project_root / "prompt-bundles"))

    ctx = StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root,
    )
    save_story_context(project_root, ctx)
    save_flow_execution(
        project_root,
        FlowExecution(
            project_key="test-project",
            story_id=_STORY_ID,
            run_id=_RUN_ID,
            flow_id="closure",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )
    return project_root


def _ctx(project_root: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root,
    )


def _edge_change_evidence(_ctx: StoryContext, _story_dir: Path) -> str:
    """Return representative evidence already reported by the Project Edge."""
    return (
        "diff --git a/feature.py b/feature.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/feature.py\n"
        "@@ -0,0 +1 @@\n"
        "+y = 2"
    )


def test_feedback_fidelity_pass_verdict_runs_real_eval(_feedback_project: Path) -> None:
    """A real PASS verdict from the LLM -> (True, None); the LLM was really called."""
    client = _ScriptedFeedbackLlmClient(status="PASS")
    port = ProductiveDocFidelityFeedbackPort(
        llm_client=client,
        change_evidence_provider=_edge_change_evidence,
    )

    passed, warning = port.evaluate_feedback_fidelity(
        _ctx(_feedback_project), _feedback_project
    )

    assert passed is True
    assert warning is None
    # The real productive path actually invoked the doc_fidelity reviewer -- this
    # is NOT the old exception-to-warning crash path.
    assert client.calls == ["doc_fidelity"]
    assert "diff --git a/feature.py b/feature.py" in client.prompts[0]


def test_feedback_fidelity_fail_verdict_is_nonblocking_warning(
    _feedback_project: Path,
) -> None:
    """A real FAIL verdict -> non-blocking warning + incident candidate (FK-38 §38.3)."""
    client = _ScriptedFeedbackLlmClient(status="FAIL")
    port = ProductiveDocFidelityFeedbackPort(
        llm_client=client,
        change_evidence_provider=_edge_change_evidence,
    )

    passed, warning = port.evaluate_feedback_fidelity(
        _ctx(_feedback_project), _feedback_project
    )

    assert passed is False  # non-blocking: surfaced as a Warning, not a blockade
    assert warning is not None
    assert "feedback_fidelity FAIL" in warning
    assert "incident candidate" in warning
    # FAIL came from a REAL evaluation (verdict), not a setup exception.
    assert "evaluator failed" not in warning
    assert client.calls == ["doc_fidelity"]


def test_feedback_fidelity_failclosed_default_still_runs(_feedback_project: Path) -> None:
    """No injected client -> fail-closed transport yields a REAL FAIL verdict.

    Until the productive LLM pool lands (AG3-070), the default transport is the
    fail-closed ``FailClosedLlmClient``. The conformance service maps that to a
    real ``FidelityResult(conformance_verdict=FAIL)`` -- the level-4 step STILL
    RUNS and yields a non-blocking warning, never a silent skip and never a hard
    closure blockade.
    """
    port = ProductiveDocFidelityFeedbackPort(
        change_evidence_provider=_edge_change_evidence
    )  # llm_client=None -> fail-closed

    passed, warning = port.evaluate_feedback_fidelity(
        _ctx(_feedback_project), _feedback_project
    )

    assert passed is False
    assert warning is not None
    assert "feedback_fidelity" in warning


def test_feedback_fidelity_without_edge_evidence_skips_and_flags_fail_closed(
    _feedback_project: Path,
) -> None:
    """Missing edge change evidence never evaluates a placeholder subject."""
    client = _ScriptedFeedbackLlmClient(status="PASS")
    port = ProductiveDocFidelityFeedbackPort(
        llm_client=client,
        change_evidence_provider=lambda _ctx, _path: None,
    )

    passed, warning = port.evaluate_feedback_fidelity(
        _ctx(_feedback_project), _feedback_project
    )

    assert passed is False
    assert warning is not None
    assert "skipped fail-closed" in warning
    assert "edge-reported change evidence is unavailable" in warning
    assert client.calls == []
