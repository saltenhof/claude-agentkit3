"""Unit tests for integration_stabilization domain models (AC1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudget,
    StabilizationBudgetCaps,
)


def _make_budget_caps(
    max_loops: int = 5,
    max_new_surfaces: int = 3,
    max_contract_changes: int = 2,
    max_regressions_per_cycle: int = 1,
) -> StabilizationBudgetCaps:
    return StabilizationBudgetCaps(
        max_loops=max_loops,
        max_new_surfaces=max_new_surfaces,
        max_contract_changes=max_contract_changes,
        max_regressions_per_cycle=max_regressions_per_cycle,
    )


def _make_manifest(**kwargs: object) -> IntegrationScopeManifest:
    defaults: dict[str, object] = {
        "version": 1,
        "project_key": "PROJ",
        "story_id": "PROJ-42",
        "implementation_contract": "integration_stabilization",
        "target_seams": ("src/api/", "src/db/"),
        "allowed_repos_paths": ("worktrees/main/",),
        "integration_targets": ("e2e_login", "e2e_checkout"),
        "allowed_contract_changes": ("add_endpoint",),
        "stabilization_budget": _make_budget_caps(),
        "out_of_contract_examples": ("src/unrelated/",),
    }
    defaults.update(kwargs)
    return IntegrationScopeManifest(**defaults)  # type: ignore[arg-type]


def _make_approval(manifest: IntegrationScopeManifest) -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=manifest.project_key,
        story_id=manifest.story_id,
        run_id="run-001",
        manifest_version=manifest.version,
        manifest_hash=manifest.content_hash,
    )


# ---------------------------------------------------------------------------
# AC1: Mandatory field presence
# ---------------------------------------------------------------------------


class TestIntegrationScopeManifestFields:
    """AC1: manifest has all FK-05 §5.5.2 required fields."""

    def test_all_mandatory_fields_present(self) -> None:
        m = _make_manifest()
        assert m.project_key == "PROJ"
        assert m.story_id == "PROJ-42"
        assert m.implementation_contract == "integration_stabilization"
        assert m.target_seams == ("src/api/", "src/db/")
        assert m.allowed_repos_paths == ("worktrees/main/",)
        assert m.integration_targets == ("e2e_login", "e2e_checkout")
        assert m.allowed_contract_changes == ("add_endpoint",)
        assert isinstance(m.stabilization_budget, StabilizationBudgetCaps)
        assert m.out_of_contract_examples == ("src/unrelated/",)
        assert m.version == 1
        assert m.content_hash  # non-empty hash

    def test_content_hash_computed_deterministically(self) -> None:
        m1 = _make_manifest()
        m2 = _make_manifest()
        assert m1.content_hash == m2.content_hash

    def test_content_hash_changes_on_field_change(self) -> None:
        m1 = _make_manifest(project_key="PROJ")
        m2 = _make_manifest(project_key="OTHER")
        assert m1.content_hash != m2.content_hash

    def test_model_is_frozen(self) -> None:
        m = _make_manifest()
        with pytest.raises((AttributeError, TypeError, PydanticValidationError)):
            m.version = 99  # type: ignore[misc]

    def test_lists_coerced_to_tuples(self) -> None:
        m = IntegrationScopeManifest(
            version=1,
            project_key="PROJ",
            story_id="PROJ-42",
            implementation_contract="integration_stabilization",
            target_seams=["src/api/"],  # type: ignore[arg-type]
            allowed_repos_paths=["worktrees/main/"],  # type: ignore[arg-type]
            integration_targets=["e2e_login"],  # type: ignore[arg-type]
            allowed_contract_changes=[],  # type: ignore[arg-type]
            stabilization_budget=_make_budget_caps(),
        )
        assert isinstance(m.target_seams, tuple)
        assert isinstance(m.allowed_repos_paths, tuple)

    def test_validate_contract_field_raises_on_wrong_value(self) -> None:
        """AC1: invalid contract rejected at model construction (fail-closed)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="integration_stabilization"):
            _make_manifest(implementation_contract="standard")

    def test_validate_contract_field_passes_on_correct_value(self) -> None:
        m = _make_manifest()
        m.validate_contract_field()  # must not raise


class TestManifestApprovalRecordFields:
    """AC1: approval record has mandatory FK-05 §5.5.4 fields."""

    def test_all_fields_present(self) -> None:
        m = _make_manifest()
        rec = _make_approval(m)
        assert rec.project_key == "PROJ"
        assert rec.story_id == "PROJ-42"
        assert rec.run_id == "run-001"
        assert rec.manifest_version == 1
        assert rec.manifest_hash == m.content_hash

    def test_record_is_frozen(self) -> None:
        m = _make_manifest()
        rec = _make_approval(m)
        with pytest.raises((AttributeError, TypeError, PydanticValidationError)):
            rec.run_id = "other"  # type: ignore[misc]

    def test_binds_manifest_true_on_match(self) -> None:
        m = _make_manifest()
        rec = _make_approval(m)
        assert rec.binds_manifest(m) is True

    def test_binds_manifest_false_on_hash_mismatch(self) -> None:
        m = _make_manifest()
        rec = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=m.version,
            manifest_hash="deadbeef",
        )
        assert rec.binds_manifest(m) is False

    def test_binds_manifest_false_on_version_mismatch(self) -> None:
        m = _make_manifest()
        rec = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-001",
            manifest_version=99,
            manifest_hash=m.content_hash,
        )
        assert rec.binds_manifest(m) is False


class TestStabilizationBudget:
    """AC1/AC4: budget caps and exhaustion checks."""

    def test_caps_are_frozen(self) -> None:
        caps = _make_budget_caps()
        with pytest.raises((AttributeError, TypeError, PydanticValidationError)):
            caps.max_loops = 99  # type: ignore[misc]

    def test_budget_is_frozen(self) -> None:
        budget = StabilizationBudget(caps=_make_budget_caps())
        with pytest.raises((AttributeError, TypeError, PydanticValidationError)):
            budget.loops_used = 99  # type: ignore[misc]

    def test_loops_not_exhausted_initially(self) -> None:
        b = StabilizationBudget(caps=_make_budget_caps(max_loops=5))
        assert b.loops_exhausted is False
        assert b.any_cap_exhausted is False

    def test_loops_exhausted(self) -> None:
        b = StabilizationBudget(caps=_make_budget_caps(max_loops=2), loops_used=2)
        assert b.loops_exhausted is True
        assert b.any_cap_exhausted is True
        assert "loops" in b.exhausted_caps()

    def test_new_surfaces_exhausted(self) -> None:
        b = StabilizationBudget(
            caps=_make_budget_caps(max_new_surfaces=1), new_surfaces_used=1
        )
        assert b.surfaces_exhausted is True
        assert "new_surfaces" in b.exhausted_caps()

    def test_contract_changes_exhausted(self) -> None:
        b = StabilizationBudget(
            caps=_make_budget_caps(max_contract_changes=2),
            contract_changes_used=2,
        )
        assert b.contract_changes_exhausted is True
        assert "contract_changes" in b.exhausted_caps()

    def test_regressions_per_cycle_exhausted(self) -> None:
        b = StabilizationBudget(
            caps=_make_budget_caps(max_regressions_per_cycle=1),
            regressions_this_cycle=1,
        )
        assert b.regressions_exhausted is True
        assert "regressions_per_cycle" in b.exhausted_caps()

    def test_all_caps_clean(self) -> None:
        b = StabilizationBudget(
            caps=_make_budget_caps(),
            loops_used=1,
            new_surfaces_used=1,
            contract_changes_used=0,
            regressions_this_cycle=0,
        )
        assert b.any_cap_exhausted is False
        assert b.exhausted_caps() == []
