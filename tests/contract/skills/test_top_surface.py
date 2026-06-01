"""Contract tests for the Skills top-surface (AG3-027).

Pins:
1. Exact method signatures for all four top-level methods.
2. Architecture conformance: agentkit.skills must NOT import from
   agentkit.state_backend.store or agentkit.installer.
3. Installer-consumability probe: Skills.bind_skill is callable with the
   signature the installer will use (skill_name, bundle_root, project_root).
4. SkillBindingRepository satisfies the Protocol (InMemory implementation).
"""

from __future__ import annotations

import ast
import inspect
import tempfile
from pathlib import Path

import pytest

from agentkit.skills.links import create_directory_link, is_directory_link
from agentkit.skills.top import Skills


def _directory_links_supported() -> bool:
    """Return True when the OS/process can create a binding link.

    Uses the production link layer (symlink on POSIX, directory junction on
    Windows). The junction needs no Developer Mode, so this is True on every
    supported platform; the probe only guards exotic filesystems.
    """
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        link = Path(d) / "link"
        try:
            create_directory_link(link, src)
            return True
        except OSError:
            return False


_LINKS_AVAILABLE = _directory_links_supported()

# ---------------------------------------------------------------------------
# 1. Signature pinning
# ---------------------------------------------------------------------------

class TestSkillsSignatures:
    """All four top-surface methods have stable, pinned signatures."""

    def test_init_signature(self) -> None:
        sig = inspect.signature(Skills.__init__)
        params = list(sig.parameters)
        assert params == ["self", "bundle_store", "binding_repo"]

    def test_bind_skill_signature(self) -> None:
        """FK-43 §43.1: bind_skill takes exactly self, skill_name, bundle_root, project_root."""
        sig = inspect.signature(Skills.bind_skill)
        params = list(sig.parameters)
        # Strict: no extra keyword-only parameters (Pass-2 Codex giftig fix).
        assert params == ["self", "skill_name", "bundle_root", "project_root"]

    def test_bind_skill_required_params_order(self) -> None:
        """The three required positional parameters are skill_name, bundle_root, project_root."""
        sig = inspect.signature(Skills.bind_skill)
        positional = [
            name
            for name, p in sig.parameters.items()
            if name != "self"
            and p.default is inspect.Parameter.empty
            and p.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        ]
        assert positional == ["skill_name", "bundle_root", "project_root"]

    def test_resolve_binding_signature(self) -> None:
        sig = inspect.signature(Skills.resolve_binding)
        params = list(sig.parameters)
        assert params == ["self", "project_root", "skill_name"]

    def test_list_bound_skills_signature(self) -> None:
        sig = inspect.signature(Skills.list_bound_skills)
        params = list(sig.parameters)
        assert params == ["self", "project_root"]

    def test_collect_quality_metrics_signature(self) -> None:
        sig = inspect.signature(Skills.collect_quality_metrics)
        params = list(sig.parameters)
        assert params == ["self", "skill_name"]


# ---------------------------------------------------------------------------
# 2. Architecture conformance
# ---------------------------------------------------------------------------

_SKILLS_SRC = (
    Path(__file__).parent.parent.parent.parent
    / "src"
    / "agentkit"
    / "skills"
)

_FORBIDDEN_IMPORTS = [
    "agentkit.state_backend.store",
    "agentkit.installer",
]


def _collect_python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _file_imports_forbidden(path: Path, forbidden_prefix: str) -> bool:
    """Return True if the file has a direct import from forbidden_prefix."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_prefix):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(forbidden_prefix):
                return True
    return False


class TestArchitectureConformance:
    """agentkit.skills must not import from state_backend.store or installer
    (FK-43, bc-cut-decisions.md §BC 11, Story AK9).
    """

    @pytest.mark.parametrize("forbidden_prefix", _FORBIDDEN_IMPORTS)
    def test_no_forbidden_import(self, forbidden_prefix: str) -> None:
        violations: list[str] = []
        for py_file in _collect_python_files(_SKILLS_SRC):
            if _file_imports_forbidden(py_file, forbidden_prefix):
                violations.append(str(py_file))

        assert not violations, (
            f"The following files in agentkit.skills import from "
            f"'{forbidden_prefix}', which is forbidden (AK9, BC 11 architecture):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 3. Installer-consumability probe
# ---------------------------------------------------------------------------

class TestInstallerConsumability:
    """Skills.bind_skill is callable with the installer-expected signature.

    The installer (AG3-048) will call:
        skills.bind_skill(skill_name, bundle_root, project_root)

    This test verifies the signature is compatible without touching installer code.
    """

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_bind_skill_callable_with_positional_args(self, tmp_path: Path) -> None:
        from agentkit.skills.bundle_store import SkillBundleStore
        from agentkit.skills.repository import InMemorySkillBindingRepository

        bundle_root = tmp_path / "bundle"
        bundle_root.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        skills = Skills(
            bundle_store=SkillBundleStore(store_root=tmp_path),
            binding_repo=InMemorySkillBindingRepository(),
        )

        # This is the exact call the installer will make (AG3-048 Installer-Andockung).
        # No TypeError means the contract is satisfied.
        skills.bind_skill("implement", bundle_root, project_root)

        # FK-43 §43.4.1 AK4: pflicht-Multi-Harness ab Tag 1 — beide Links da
        # (Symlink auf POSIX, Directory Junction auf Windows).
        claude_link = project_root / ".claude" / "skills" / "implement"
        codex_link = project_root / ".codex" / "skills" / "implement"
        assert is_directory_link(claude_link)
        assert is_directory_link(codex_link)


# ---------------------------------------------------------------------------
# 4. SkillBindingRepository Protocol satisfaction
# ---------------------------------------------------------------------------

class TestRepositoryProtocol:
    """InMemorySkillBindingRepository satisfies SkillBindingRepository protocol."""

    def test_is_instance_of_protocol(self) -> None:
        from agentkit.skills.repository import (
            InMemorySkillBindingRepository,
            SkillBindingRepository,
        )

        repo = InMemorySkillBindingRepository()
        assert isinstance(repo, SkillBindingRepository)

    def test_save_load_roundtrip(self) -> None:
        from datetime import UTC, datetime

        from agentkit.skills.binding import (
            SkillBinding,
            SkillBindingMode,
            SkillLifecycleStatus,
        )
        from agentkit.skills.repository import InMemorySkillBindingRepository

        repo = InMemorySkillBindingRepository()
        binding = SkillBinding(
            binding_id="test-id",
            project_key="proj",
            skill_name="implement",
            bundle_id="core",
            bundle_version="1.0",
            target_path=Path("/tmp/.claude/skills/implement"),
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        repo.save(binding)
        loaded = repo.load("proj", "implement")
        assert loaded is not None
        assert loaded.binding_id == "test-id"

    def test_list_for_project_sorted(self) -> None:
        from datetime import UTC, datetime

        from agentkit.skills.binding import (
            SkillBinding,
            SkillBindingMode,
            SkillLifecycleStatus,
        )
        from agentkit.skills.repository import InMemorySkillBindingRepository

        repo = InMemorySkillBindingRepository()
        for name in ["zzz", "aaa", "mmm"]:
            binding = SkillBinding(
                binding_id=f"id-{name}",
                project_key="proj",
                skill_name=name,
                bundle_id="core",
                bundle_version="1.0",
                target_path=Path(f"/tmp/.claude/skills/{name}"),
                binding_mode=SkillBindingMode.SYMLINK,
                status=SkillLifecycleStatus.VERIFIED,
                pinned_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            repo.save(binding)

        result = repo.list_for_project("proj")
        names = [b.skill_name for b in result]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# 5. Productive StateBackend persistence path (AG3-048)
# ---------------------------------------------------------------------------


class TestProductivePersistencePath:
    """Skills top-surface works end-to-end against the productive
    ``StateBackendSkillBindingRepository`` (AG3-048), not only InMemory.

    Uses the SQLite test-parallel path (``AGENTKIT_ALLOW_SQLITE=1``, set by the
    top-level conftest); Postgres is the canonical runtime backend.
    """

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_bind_resolve_list_via_state_backend_repo(self, tmp_path: Path) -> None:
        from agentkit.skills.binding import SkillLifecycleStatus
        from agentkit.skills.bundle_store import SkillBundleStore
        from agentkit.state_backend.store import reset_backend_cache_for_tests
        from agentkit.state_backend.store.skill_binding_repository import (
            StateBackendSkillBindingRepository,
        )

        reset_backend_cache_for_tests()
        try:
            bundle_root = tmp_path / "bundle"
            bundle_root.mkdir()
            project_root = tmp_path / "project"
            project_root.mkdir()

            skills = Skills(
                bundle_store=SkillBundleStore(store_root=tmp_path / "store"),
                binding_repo=StateBackendSkillBindingRepository(tmp_path / "state"),
            )

            skills.bind_skill("execute-userstory", bundle_root, project_root)

            # resolve_binding reads back through the productive repo.
            binding = skills.resolve_binding(project_root, "execute-userstory")
            assert binding is not None
            assert binding.skill_name == "execute-userstory"
            assert binding.status is SkillLifecycleStatus.VERIFIED

            listed = skills.list_bound_skills(project_root)
            assert [b.skill_name for b in listed] == ["execute-userstory"]
        finally:
            reset_backend_cache_for_tests()
