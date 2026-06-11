"""Unit tests for the CustomizationFootprint read-aggregate (AG3-089 AC7 / AC8).

AC7: the footprint aggregates the FOUR owner sources (pipeline-config digest,
CCAG ``load_rules``, prompt ``resolve_project_prompt_binding``, skill
``Skills.resolve_binding``) — one set customization per source.

AC8 / F-51-023: a write path (cleanup / binding) that would touch a detected
customization blocks/reports and mutates NOTHING.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.unit.installer.upgrade.conftest import (
    InMemoryRegistrationRepo,
    register_project,
    write_valid_project_yaml,
)

from agentkit.installer.upgrade.footprint import (
    CustomizationFootprint,
    CustomizationKind,
    CustomizationPoint,
    CustomizationPreservationError,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_ccag_rule(project_root: Path) -> None:
    """Write one project-specific CCAG block rule (governance-and-guards source)."""
    rules_dir = project_root / ".agentkit" / "ccag" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "global.yaml").write_text(
        "- rule_id: no-rm-rf\n"
        "  tool: Bash\n"
        "  block_pattern: 'rm -rf'\n"
        "  scope: all\n"
        "  reason: project rule\n",
        encoding="utf-8",
    )


def _bind_prompt(project_root: Path, store_root: Path) -> None:
    """Create a real project prompt binding via PromptRuntime.update_binding."""
    from agentkit.installer.paths import prompt_bundle_store_dir
    from agentkit.prompt_runtime.runtime import PromptRuntime

    bundle_root = prompt_bundle_store_dir(
        "custom-bundle", "9.9.9", store_root=store_root
    )
    bundle_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "bundle_id": "custom-bundle",
        "bundle_version": "9.9.9",
        "templates": {"sys": "sys.md"},
    }
    (bundle_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    PromptRuntime(project_root).update_binding("custom-bundle", "9.9.9")


class _BoundSkillsSurface:
    """Minimal real-shaped ``Skills`` stand-in returning one binding.

    Not a mock of behaviour under test: it is a deterministic agent-skills
    top-surface double that returns a real :class:`SkillBinding` for one skill,
    so the footprint's ``Skills.resolve_binding`` read path is exercised without a
    live state backend. Only ``resolve_binding`` is consumed by the footprint.
    """

    def __init__(self, bound_skill: str) -> None:
        self._bound_skill = bound_skill

    def resolve_binding(self, project_root: Path, skill_name: str) -> object | None:
        from agentkit.skills.binding import (
            SkillBinding,
            SkillBindingMode,
            SkillLifecycleStatus,
        )

        if skill_name != self._bound_skill:
            return None
        return SkillBinding(
            binding_id="b1",
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id="execute-userstory-custom",
            bundle_version="9.9.9",
            target_path=project_root / ".claude" / "skills" / skill_name,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=datetime.now(tz=UTC),
        )


def test_footprint_aggregates_four_sources(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7: one set customization per source -> all four KINDS detected."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    store_root = tmp_path / "store"

    monkeypatch.setenv("AGENTKIT_PROMPT_BUNDLE_STORE_ROOT", str(store_root))

    # 1) pipeline-config: a VALID project.yaml read through the owner surface
    # (load_project_config) whose on-disk digest != the registered digest.
    write_valid_project_yaml(
        project_root, extra_pipeline={"max_feedback_rounds": 7}
    )
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest="a-different-registered-digest",
    )
    # 2) CCAG rule.
    _write_ccag_rule(project_root)
    # 3) prompt binding.
    _bind_prompt(project_root, store_root)
    # 4) skill binding (injected surface).
    skills = _BoundSkillsSurface(bound_skill="execute-userstory")

    footprint = CustomizationFootprint.detect(
        project_root,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        project_key=project_root.stem,
        skills=skills,  # type: ignore[arg-type]
    )

    kinds = {point.kind for point in footprint.points}
    assert CustomizationKind.PIPELINE_CONFIG in kinds
    assert CustomizationKind.CCAG_RULE in kinds
    assert CustomizationKind.PROMPT_BINDING in kinds
    assert CustomizationKind.SKILL_BINDING in kinds


def test_footprint_empty_when_nothing_customised(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """No registration / config / rules / bindings -> empty footprint."""
    project_root = tmp_path / "proj"
    project_root.mkdir()

    footprint = CustomizationFootprint.detect(
        project_root,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        project_key=project_root.stem,
    )

    assert footprint.is_empty


def test_footprint_pipeline_config_no_point_when_digest_matches(
    tmp_path: Path,
    registration_repo: InMemoryRegistrationRepo,
) -> None:
    """A digest that MATCHES the registration is not a customization."""
    from agentkit.installer.upgrade._digest import config_file_digest

    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = write_valid_project_yaml(project_root)
    register_project(
        registration_repo,
        project_root=project_root,
        project_key=project_root.stem,
        config_digest=config_file_digest(config_path),
    )

    footprint = CustomizationFootprint.detect(
        project_root,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        project_key=project_root.stem,
    )

    assert footprint.points_of(CustomizationKind.PIPELINE_CONFIG) == ()


def test_guard_write_blocks_detected_customization_no_mutation() -> None:
    """AC8 / F-51-023: guard_write blocks a detected customization (no mutation)."""
    footprint = CustomizationFootprint(
        points=(
            CustomizationPoint(
                kind=CustomizationKind.PIPELINE_CONFIG,
                identifier="ccag:no-rm-rf",
                detail="x",
            ),
        )
    )

    with pytest.raises(CustomizationPreservationError) as exc:
        footprint.guard_write("ccag:no-rm-rf", write_path="binding")

    assert "F-51-023" in str(exc.value)


def test_guard_write_allows_unknown_identifier() -> None:
    """A non-customization identifier is not blocked."""
    footprint = CustomizationFootprint()

    # No raise -> the write path may proceed.
    footprint.guard_write("not-a-customization", write_path="cleanup")
