"""AC4-5 justified baseline, visibility, stale, and version tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from concept_governance.baseline import BaselineDocument, BaselineEntry, BaselineError, load_baseline
from concept_governance.baseline_policy import apply_baseline
from concept_governance.models import AuthorityFinding
from concept_governance.runner import run_authority_check
from tests.unit.tools.concept_governance.helpers import ScriptedEvaluator, write_doc

if TYPE_CHECKING:
    from pathlib import Path


def _finding(*, prompt: str = "authority-prose/v1", model: str = "fixed/v1") -> AuthorityFinding:
    return AuthorityFinding(
        code="UNAUTHORIZED_SCOPE_ASSERTION",
        doc="domain-design/consumer.md",
        anchor="rule-000",
        assertion="The system must retain locks.",
        scope="lock.lifecycle",
        prompt_version=prompt,
        model=model,
        message="unauthorized",
    )


def _entry(
    finding: AuthorityFinding,
    reason: str = "Legacy consumer duplicates the owner rule pending its next edit.",
) -> BaselineEntry:
    fields = {"code", "doc", "anchor", "assertion", "scope", "prompt_version", "model"}
    return BaselineEntry(**finding.model_dump(include=fields), reason=reason)


def test_unjustified_baseline_fails_closed(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    path = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    path.parent.mkdir(parents=True, exist_ok=True)
    item = _finding()
    fields = ("code", "doc", "anchor", "assertion", "scope", "prompt_version", "model")
    path.write_text(
        "version: 1\nentries:\n  - "
        + "\n    ".join(f"{key}: {getattr(item, key)!r}" for key in fields)
        + "\n    reason: '   '\n",
        encoding="utf-8",
    )
    with pytest.raises(BaselineError):
        load_baseline(path)
    evaluator = ScriptedEvaluator(lambda chunk: (_ for _ in ()).throw(AssertionError(chunk)))
    result = run_authority_check(concept, path, evaluator)
    assert not result.ok
    assert [finding.code for finding in result.findings] == ["INVALID_BASELINE"]
    assert evaluator.calls == []


def test_non_baselined_error_and_baselined_report_remains_listed() -> None:
    finding = _finding()
    empty = BaselineDocument(version=1, entries=())
    assert apply_baseline((finding,), empty, "baseline.yaml")[0].severity == "ERROR"

    baseline = BaselineDocument(version=1, entries=(_entry(finding),))
    listed = apply_baseline((finding,), baseline, "baseline.yaml")
    assert listed[0].severity == "REPORT"
    assert listed[0].baselined is True


def test_stale_baseline_is_error() -> None:
    finding = _finding()
    baseline = BaselineDocument(version=1, entries=(_entry(finding),))
    result = apply_baseline((), baseline, "concept/_meta/authority-prose-baseline.yaml")
    assert [item.code for item in result] == ["STALE_BASELINE"]
    assert result[0].severity == "ERROR"


def test_prompt_or_model_change_surfaces_new_finding_and_stale_entry() -> None:
    old = _finding()
    changed = _finding(prompt="authority-prose/v2", model="fixed/v2")
    baseline = BaselineDocument(version=1, entries=(_entry(old),))

    result = apply_baseline((changed,), baseline, "baseline.yaml")

    assert [item.code for item in result] == ["STALE_BASELINE", "UNAUTHORIZED_SCOPE_ASSERTION"]
    assert all(item.severity == "ERROR" for item in result)
