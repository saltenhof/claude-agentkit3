"""Unit tests for resolve_repo_affinity (AG3-068 / FK-21 §21.9).

Pure deterministic logic -- no external boundary, no mocks.
"""

from __future__ import annotations

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
)
from agentkit.story_creation.repo_affinity import resolve_repo_affinity


def _project(repos: list[tuple[str, str]]) -> ProjectConfig:
    """Build a ProjectConfig from ``(name, path)`` pairs.

    The ``name`` and ``path`` are DELIBERATELY distinct so the tests genuinely
    exercise path-matching (FK-21 §21.9.2 matches affected file paths against
    the configured repo ``path`` root, not the display ``name``). A test that
    set ``path=/tmp/{name}`` would mask a name-vs-path regression because the
    two strings would encode the same token.
    """
    return ProjectConfig(
        project_key="test",
        project_name="Test",
        repositories=[
            RepositoryConfig(name=name, path=path) for name, path in repos
        ],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
        ),  # type: ignore[call-arg]
    )


def test_strong_evidence_only_ignores_paths_outside_section() -> None:
    """NEGATIVE: paths from logs/examples outside the section are ignored."""
    body = (
        "# Story\n\n"
        "Some prose referencing `services/api/leak.py` in an example.\n\n"
        "## Logs\n"
        "- services/api/from_log.py\n\n"
        "## Betroffene Dateien\n"
        "- `services/api/main.py`\n"
        "- services/api/util.py\n\n"
        "## Weitere\n"
        "- apps/web/ignored.tsx\n"
    )
    # name != path: matching MUST key off the configured path root.
    config = _project([("backend", "services/api"), ("frontend", "apps/web")])
    result = resolve_repo_affinity(body, config)
    assert result.participating_repos == ("backend",)
    assert result.hit_counts == {"backend": 2}
    assert result.used_module_fallback is False


def test_match_is_against_path_not_name() -> None:
    """NEGATIVE/regression: a path that equals the NAME but not the configured
    path root must NOT match; only the configured ``repo.path`` root counts."""
    body = (
        "## Betroffene Dateien\n"
        "- backend/main.py\n"  # equals the NAME 'backend' but not the path root
        "- services/api/main.py\n"  # equals the configured path root
    )
    config = _project([("backend", "services/api")])
    result = resolve_repo_affinity(body, config)
    # 'backend/main.py' is NOT under the configured root 'services/api' => 1 hit.
    assert result.participating_repos == ("backend",)
    assert result.hit_counts == {"backend": 1}


def test_longest_prefix_match() -> None:
    body = (
        "## Betroffene Dateien\n"
        "- services/api/server.py\n"
        "- services/api/handlers/h.py\n"
    )
    # Overlapping path roots: the longer 'services/api' must win over 'services'.
    config = _project([("monorepo", "services"), ("api", "services/api")])
    result = resolve_repo_affinity(body, config)
    assert result.participating_repos == ("api",)
    assert result.hit_counts == {"api": 2}


def test_deterministic_sort_hits_desc_then_lexicographic() -> None:
    """Determinism: hits descending, ties broken lexicographically."""
    body = (
        "## Betroffene Dateien\n"
        "- repos/zebra/a.py\n"
        "- repos/alpha/a.py\n"
        "- repos/alpha/b.py\n"
        "- repos/mid/a.py\n"
    )
    config = _project(
        [
            ("alpha", "repos/alpha"),
            ("mid", "repos/mid"),
            ("zebra", "repos/zebra"),
        ]
    )
    result = resolve_repo_affinity(body, config)
    # alpha has 2 hits (first), then mid and zebra each 1 -> lexicographic.
    assert result.participating_repos == ("alpha", "mid", "zebra")
    assert result.hit_counts == {"alpha": 2, "mid": 1, "zebra": 1}


def test_tie_break_is_lexicographic() -> None:
    body = (
        "## Betroffene Dateien\n"
        "- repos/zebra/a.py\n"
        "- repos/alpha/a.py\n"
    )
    config = _project([("alpha", "repos/alpha"), ("zebra", "repos/zebra")])
    result = resolve_repo_affinity(body, config)
    # Both 1 hit -> alpha before zebra (first entry = spawn-CWD anchor).
    assert result.participating_repos == ("alpha", "zebra")


def test_root_docs_fallback_via_module_field() -> None:
    """Root/Docs: no listed paths => derive scope from the module field."""
    body = "# Story\n\nNo affected-files section here.\n"
    config = _project([("docs", "documentation"), ("backend", "services/api")])
    # The module field is matched against the configured path root, too.
    result = resolve_repo_affinity(body, config, module="documentation/architecture")
    assert result.participating_repos == ("docs",)
    assert result.used_module_fallback is True


def test_no_paths_no_module_yields_empty() -> None:
    body = "# Story\n\nNothing relevant.\n"
    config = _project([("backend", "services/api")])
    result = resolve_repo_affinity(body, config)
    assert result.participating_repos == ()


def test_windows_configured_path_matches_posix_listed_paths() -> None:
    """A backslash-configured repo path still matches POSIX story.md paths."""
    body = "## Betroffene Dateien\n- services/api/main.py\n"
    config = _project([("backend", "services\\api")])
    result = resolve_repo_affinity(body, config)
    assert result.participating_repos == ("backend",)
    assert result.hit_counts == {"backend": 1}
