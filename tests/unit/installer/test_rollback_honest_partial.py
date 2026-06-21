"""Unit: honest rollback report when a compensating delete fails (AG3-048).

Codex-r2 ERROR 2 — ``_rollback_bindings`` must NOT swallow a failing
``unbind_skill`` and must NOT let the caller claim a clean rollback. When the
repository ``delete`` raises during rollback (e.g. a DB outage that removes the
symlinks but leaves the persisted binding row), the installer surfaces the
orphaned/partial state in the raised ``InstallationError`` so it is retryable —
it never lies about a full rollback.

These tests run on ANY host (no symlinks, no DB): they inject a fake
``Skills`` top-surface and a fake bundle store, exercising the installer's
transactional control flow directly. Nothing here is made green by skipping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    _bind_mandatory_skills,
    _rollback_bindings,
)
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore

if TYPE_CHECKING:
    from pathlib import Path


class _FakeStore:
    """Bundle store stub: resolves every mandatory bundle to a dummy root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_bundle(self, bundle_id: str) -> SkillBundle:
        bundle_root = self._root / bundle_id / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        return SkillBundle(
            bundle_id=bundle_id,
            bundle_version="4.0.0",
            bundle_root=bundle_root,
            manifest_digest="0" * 64,
        )


class _FakeSkills:
    """Skills stub.

    * ``bind_skill`` succeeds for the first skill, then raises for the second
      (simulating a malformed bundle / profile mismatch mid-transaction).
    * ``unbind_skill`` raises for the already-bound first skill (simulating a
      DB outage during the compensating repository ``delete``), succeeds for
      anything else.
    """

    def __init__(self, fail_on_bind_index: int, fail_unbind_for: set[str]) -> None:
        self._fail_on_bind_index = fail_on_bind_index
        self._fail_unbind_for = fail_unbind_for
        self.bound: list[str] = []
        self.unbind_attempts: list[str] = []

    def bind_skill(self, skill_name: str, bundle_root: Path, project_root: Path) -> None:
        del bundle_root, project_root
        if len(self.bound) == self._fail_on_bind_index:
            raise RuntimeError(f"bind failed for {skill_name}")
        self.bound.append(skill_name)

    def unbind_skill(self, skill_name: str, project_root: Path) -> None:
        del project_root
        self.unbind_attempts.append(skill_name)
        if skill_name in self._fail_unbind_for:
            raise RuntimeError(f"DB outage: delete failed for {skill_name}")


def _config(
    tmp_path: Path, skills: object, store: object
) -> InstallConfig:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    return InstallConfig(
        project_key="rollback-it",
        project_name="rollback-it",
        project_root=root,
        skills=skills,  # type: ignore[arg-type]
        skill_bundle_store=store,  # type: ignore[arg-type]
        skill_bundle_ids={name: f"{name}-core" for name in MANDATORY_SKILLS},
        # AG3-052: conscious Sonar opt-out (no live Sonar; FK-03 §3 default
        # is available:true). This install fails earlier at skill-bind anyway.
        sonarqube_available=False,
    )


def test_rollback_failure_reports_orphaned_state_not_clean_rollback(
    tmp_path: Path,
) -> None:
    """Bind fails on the SECOND skill; the compensating unbind of the FIRST
    skill fails (repo delete outage). The installer must raise
    ``RollbackIncomplete`` and name the orphaned binding — it must NOT claim a
    clean ``BindFailed`` rollback.
    """
    first = MANDATORY_SKILLS[0]
    second = MANDATORY_SKILLS[1]
    skills = _FakeSkills(fail_on_bind_index=1, fail_unbind_for={first})
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    with pytest.raises(InstallationError) as exc_info:
        _bind_mandatory_skills(config, config.project_root)

    detail = exc_info.value.detail
    # Honest: the rollback could not fully compensate -> NOT "BindFailed".
    assert detail.get("cause") == "RollbackIncomplete"
    assert detail.get("skill_name") == second
    orphaned = detail.get("orphaned_bindings")
    assert isinstance(orphaned, list)
    assert [o["skill_name"] for o in orphaned] == [first]
    assert "DB outage" in orphaned[0]["error"]
    # The error message must surface the orphan, not claim "rolled back all".
    assert "orphaned" in str(exc_info.value).lower()
    assert "rolled back all" not in str(exc_info.value).lower()
    # ACCURACY (AG3-048 Codex-r3 ERROR 2): ONLY the truly-bound first skill is
    # in the rollback set. The failing SECOND skill is self-atomic (it produced
    # no side effect, so it was never appended to ``bound_so_far``) and is
    # therefore NOT compensated and NOT reported as a (false) orphan.
    assert skills.unbind_attempts == [first]


def test_clean_rollback_still_reports_bindfailed(tmp_path: Path) -> None:
    """When every compensating unbind succeeds, the installer reports the
    honest clean-rollback path (``BindFailed``), not a false orphan report.
    """
    second = MANDATORY_SKILLS[1]
    skills = _FakeSkills(fail_on_bind_index=1, fail_unbind_for=set())
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    with pytest.raises(InstallationError) as exc_info:
        _bind_mandatory_skills(config, config.project_root)

    detail = exc_info.value.detail
    assert detail.get("cause") == "BindFailed"
    assert detail.get("skill_name") == second
    assert "orphaned_bindings" not in detail
    assert "rolled back all" in str(exc_info.value).lower()


def test_rollback_bindings_collects_all_failures(tmp_path: Path) -> None:
    """``_rollback_bindings`` attempts every skill and returns one entry per
    failed compensation (it does not stop at the first failure).
    """
    first = MANDATORY_SKILLS[0]
    third = MANDATORY_SKILLS[2]
    skills = _FakeSkills(fail_on_bind_index=99, fail_unbind_for={first, third})
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)

    orphaned = _rollback_bindings(
        skills,  # type: ignore[arg-type]
        root,
        [first, MANDATORY_SKILLS[1], third],
    )

    assert skills.unbind_attempts == [first, MANDATORY_SKILLS[1], third]
    assert sorted(o["skill_name"] for o in orphaned) == sorted([first, third])


def test_first_skill_fails_pre_side_effect_is_not_a_false_orphan(
    tmp_path: Path,
) -> None:
    """ERROR 2 accuracy — a ``bind_skill`` that raises BEFORE any side effect
    (here the FIRST skill) must produce a clean ``BindFailed`` with an EMPTY
    orphan set. Nothing was bound, so nothing can be a (false) orphan; the
    failing skill itself is never reported as orphaned.
    """
    first = MANDATORY_SKILLS[0]
    # fail_on_bind_index=0 -> the very first bind raises before any side effect.
    # unbind would even fail if attempted, proving the rollback set is empty.
    skills = _FakeSkills(fail_on_bind_index=0, fail_unbind_for=set(MANDATORY_SKILLS))
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    with pytest.raises(InstallationError) as exc_info:
        _bind_mandatory_skills(config, config.project_root)

    detail = exc_info.value.detail
    # Clean rollback path, NOT a false RollbackIncomplete / orphan.
    assert detail.get("cause") == "BindFailed"
    assert detail.get("skill_name") == first
    assert "orphaned_bindings" not in detail
    # No skill was ever fully bound -> nothing was compensated.
    assert skills.unbind_attempts == []
    assert "rolled back all" in str(exc_info.value).lower()


def test_truly_bound_prior_skill_compensation_failure_is_a_real_orphan(
    tmp_path: Path,
) -> None:
    """ERROR 2 accuracy — a truly-bound PRIOR skill whose compensating delete
    fails IS reported as a real orphan. Bind succeeds for skills 0 and 1, fails
    on skill 2; the compensation of the truly-bound skill 1 fails -> skill 1 is
    a genuine orphan, skill 0 (clean compensation) is not, and skill 2 (failed
    pre/at side effect, self-atomic) is not.
    """
    second = MANDATORY_SKILLS[1]
    third = MANDATORY_SKILLS[2]
    skills = _FakeSkills(fail_on_bind_index=2, fail_unbind_for={second})
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    with pytest.raises(InstallationError) as exc_info:
        _bind_mandatory_skills(config, config.project_root)

    detail = exc_info.value.detail
    assert detail.get("cause") == "RollbackIncomplete"
    assert detail.get("skill_name") == third
    orphaned = detail.get("orphaned_bindings")
    assert isinstance(orphaned, list)
    # ONLY the truly-bound skill 1 (whose delete failed) is a real orphan.
    assert [o["skill_name"] for o in orphaned] == [second]
    # The failing skill 2 was self-atomic -> never in the rollback set. Skills
    # 0 and 1 (truly bound) are compensated; skill 2 is not.
    assert skills.unbind_attempts == [MANDATORY_SKILLS[0], second]


def test_failing_skill_partial_state_is_reported_as_rollback_incomplete(
    tmp_path: Path,
) -> None:
    """AG3-048 Codex-r4 FINDING 1 (test b): when the FAILING skill's own bind
    leaves residual partial state (its self-atomic cleanup could not fully undo),
    ``bind_skill`` raises ``SkillBindingPartialStateError``. The installer must
    treat that as a real orphan/incomplete (``RollbackIncomplete``) — NEVER as a
    clean ``BindFailed``. Host-independent (no symlinks, no DB).
    """
    from agentkit.backend.skills.errors import SkillBindingPartialStateError

    class _PartialStateSkills:
        """First skill binds cleanly; the SECOND skill's bind fails AND leaves
        residual partial state (persist + cleanup both failed)."""

        def __init__(self) -> None:
            self.bound: list[str] = []
            self.unbind_attempts: list[str] = []

        def bind_skill(
            self, skill_name: str, bundle_root: Path, project_root: Path
        ) -> None:
            del bundle_root, project_root
            if len(self.bound) == 1:
                raise SkillBindingPartialStateError(
                    f"bind failed and cleanup incomplete for {skill_name}",
                    detail={
                        "skill_name": skill_name,
                        "residual_links": [
                            f"/proj/.claude/skills/{skill_name}",
                            f"/proj/.codex/skills/{skill_name}",
                        ],
                        "persisted_row_remains": True,
                        "original_error": "DB outage during persist",
                    },
                )
            self.bound.append(skill_name)

        def unbind_skill(self, skill_name: str, project_root: Path) -> None:
            del project_root
            self.unbind_attempts.append(skill_name)
            if skill_name in fail_unbind_for:
                raise RuntimeError(f"DB outage: delete failed for {skill_name}")

    first = MANDATORY_SKILLS[0]
    second = MANDATORY_SKILLS[1]
    # The prior truly-bound skill's compensating unbind ALSO fails, so it is a
    # genuine orphan too — alongside the failing skill's own residual state.
    fail_unbind_for = {first}
    skills = _PartialStateSkills()
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    with pytest.raises(InstallationError) as exc_info:
        _bind_mandatory_skills(config, config.project_root)

    detail = exc_info.value.detail
    # NOT a clean BindFailed — the failing skill left residual state.
    assert detail.get("cause") == "RollbackIncomplete"
    assert detail.get("skill_name") == second
    orphaned = detail.get("orphaned_bindings")
    assert isinstance(orphaned, list)
    names = sorted(o["skill_name"] for o in orphaned)
    # Both the truly-bound prior skill (unbind failed) AND the failing skill
    # itself (residual partial state) are orphans.
    assert names == sorted([first, second])
    failing_entry = next(o for o in orphaned if o["skill_name"] == second)
    # Codex-r7: residual is STRUCTURED — a list of paths and a bool flag, not a
    # flattened string, so a machine consumer can enumerate the survivors.
    assert isinstance(failing_entry["residual_links"], list)
    assert failing_entry["residual_links"] == [
        f"/proj/.claude/skills/{second}",
        f"/proj/.codex/skills/{second}",
    ]
    assert failing_entry.get("persisted_row_remains") is True
    assert "rolled back all" not in str(exc_info.value).lower()


def test_real_unbind_residual_maps_to_rollback_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG3-048 Codex-r6 FINDING 1 (end-to-end, REAL ``Skills``): when the REAL
    ``Skills.unbind_skill`` cannot fully remove a prior skill's binding (its
    harness symlink survives the ``unlink`` even though the repo row is deleted),
    it raises ``SkillBindingPartialStateError``; the installer's
    ``_rollback_bindings`` must surface that as ``RollbackIncomplete`` — NEVER a
    false-clean rollback.

    Host-independent: the bind of the prior skill is faked into a real on-disk
    artifact + persisted row, and ``Path.unlink`` is patched to fail for that
    artifact (the WinError 1314-class survivor) so no symlink privilege is
    needed. The unbind path runs REAL ``Skills`` code (not a stub).
    """
    from datetime import UTC, datetime
    from pathlib import Path as _Path

    from agentkit.backend.skills.binding import (
        SkillBinding,
        SkillBindingMode,
        SkillLifecycleStatus,
    )
    from agentkit.backend.skills.repository import InMemorySkillBindingRepository
    from agentkit.backend.skills.top import Skills

    first = MANDATORY_SKILLS[0]
    second = MANDATORY_SKILLS[1]
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)

    # Materialise the FIRST skill's binding as a real harness artifact + row so a
    # real unbind has something to (try to) remove.
    claude_link = root / ".claude" / "skills" / first
    claude_link.parent.mkdir(parents=True)
    claude_link.write_text("residual", encoding="utf-8")
    repo = InMemorySkillBindingRepository()
    repo.save(
        SkillBinding(
            binding_id="b-first",
            project_key=root.stem,
            skill_name=first,
            bundle_id=f"{first}-core",
            bundle_version="4.0.0",
            target_path=claude_link,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=datetime.now(tz=UTC),
        )
    )
    real_skills = Skills(bundle_store=SkillBundleStore(), binding_repo=repo)

    real_unlink = _Path.unlink

    def _failing_unlink(self: _Path, *, missing_ok: bool = False) -> None:
        if self == claude_link:
            raise OSError("simulated unlink failure (artifact survives)")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(_Path, "unlink", _failing_unlink)

    # Drive the rollback with the FIRST skill as a truly-bound prior skill.
    orphaned = _rollback_bindings(real_skills, root, [first])

    # The real unbind raised SkillBindingPartialStateError -> captured as orphan.
    assert [o["skill_name"] for o in orphaned] == [first]
    assert "residual" in orphaned[0]["error"].lower() or "could not" in orphaned[
        0
    ]["error"].lower()
    # Codex-r7: the prior skill's residual is preserved STRUCTURED (list of
    # surviving link paths), not swallowed into the message string only.
    assert orphaned[0]["residual_links"] == [str(claude_link)]
    # The repo row was nonetheless deleted (delete ran despite the unlink fail).
    assert repo.load(root.stem, first) is None
    del second  # documents the multi-skill shape; only `first` is bound here.


def test_real_store_discovery_resolves_shipped_bundles() -> None:
    """REAL-code proof for Codex-r2 ERROR 1: a default-built ``SkillBundleStore``
    resolves all four FK-43 §43.3.1 mandatory bundles from the SHIPPED bundles
    via filesystem discovery — no register_bundle, no monkeypatch.
    """
    store = SkillBundleStore()  # default root == shipped bundles
    for skill_name in MANDATORY_SKILLS:
        bundle = store.get_bundle(f"{skill_name}-core")
        assert bundle.bundle_version == "4.0.0"
        assert (bundle.bundle_root / "SKILL.md").is_file()
        assert (bundle.bundle_root / "manifest.json").is_file()
        # Bundle is resolved from AK3's own packaged bundles tree, NOT from
        # the AK2 source repo (which lives under .../claude-agentkit/userstory).
        assert bundle.bundle_root.parts[-2:] == (f"{skill_name}-core", "4.0.0")
        assert "bundles" in bundle.bundle_root.parts
        assert "skill_bundles" in bundle.bundle_root.parts
        assert "userstory" not in bundle.bundle_root.parts
