"""Contract tests: the guardrail-enforcing code is itself under ruff and mypy.

`scripts/` and `tools/` decide whether a change may pass. Until AG3-218 they
were the only productive code in this repository exempt from the rules they
enforce: `Jenkinsfile` ran `ruff check src tests` and `mypy src`, and
`[tool.mypy]` named the installed package only. A `C901` sat unnoticed in the
concept-frontmatter gate, a second one in the concept compiler, and a
functional defect in the remote-gate script went unreported for weeks.

These tests pin the wiring, not the findings. They fail when someone narrows
the checked set again -- which is the failure mode that produced the story.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
CHECKED_ROOTS = ("src", "scripts", "tools")


def _jenkinsfile() -> str:
    return (REPO_ROOT / "Jenkinsfile").read_text(encoding="utf-8")


def _stage_body(name: str) -> str:
    """Return one Jenkins stage body, from its header to the next stage."""
    text = _jenkinsfile()
    start = text.index(f"stage('{name}')")
    next_stage = text.find("stage('", start + 1)
    return text[start:next_stage] if next_stage != -1 else text[start:]


def test_mypy_config_declares_every_checked_root() -> None:
    """`[tool.mypy] files` is the single declaration of the checked set."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_config = config["tool"]["mypy"]

    assert mypy_config["strict"] is True
    assert list(mypy_config["files"]) == list(CHECKED_ROOTS)
    # `packages = ["agentkit"]` would silently drop scripts/ and tools/ again.
    assert "packages" not in mypy_config
    assert "modules" not in mypy_config


def test_mypy_path_matches_the_runtime_module_identities() -> None:
    """Modules must type-check under the names they are imported by at runtime."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_path = list(config["tool"]["mypy"]["mypy_path"])

    # `scripts/ci/*.py` insert these two roots on sys.path and then import
    # `agentkit.*` and `concept_*.*` as top-level modules.
    assert "src" in mypy_path
    assert "tools" in mypy_path
    assert "scripts/ci" in mypy_path


def test_every_tools_package_is_reachable_from_a_declared_root() -> None:
    """A new package under tools/ is covered without editing any config."""
    packages = sorted(
        path.parent.name
        for path in (REPO_ROOT / "tools").glob("*/__init__.py")
    )
    assert packages, "tools/ carries no packages -- the guard would be vacuous"
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "tools" in list(config["tool"]["mypy"]["files"])


def test_jenkins_ruff_stage_covers_scripts_and_tools() -> None:
    """The blocking ruff stage lints all four roots."""
    body = _stage_body("Ruff")
    assert "python -m ruff check src tests scripts tools" in body
    # No `set +e` / `|| true`: the stage must fail the build.
    assert "set +e" not in body
    assert "|| true" not in body


def test_jenkins_mypy_stage_passes_no_path_argument() -> None:
    """A CLI path replaces `[tool.mypy] files` and would shrink the check."""
    body = _stage_body("Mypy")
    assert "python -m mypy src" not in body
    assert "python -m mypy --strict" in body
    assert "set +e" not in body
    assert "|| true" not in body


def test_jenkins_mypy_stage_runs_every_platform() -> None:
    """Platform-conditional code must type-check on all three targets."""
    body = _stage_body("Mypy")
    assert "for platform in win32 linux darwin" in body
    assert '--platform "${platform}"' in body


def test_pre_commit_hook_lints_all_four_roots() -> None:
    """The local hook uses the same ruff scope as the pipeline."""
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "ruff check src tests scripts tools" in hook


def test_claude_md_documents_the_widened_commands() -> None:
    """The documented standard check must not point back at the narrow scope."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "ruff check src tests scripts tools" in claude_md
    assert "ruff check src tests`" not in claude_md
    assert "python -m mypy src`" not in claude_md
