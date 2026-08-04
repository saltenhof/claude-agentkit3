"""Project directory and repository scaffold helpers for the installer."""


from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import ProjectError

if TYPE_CHECKING:
    from agentkit.backend.installer.runner import InstallConfig

from agentkit.backend.installer.paths import (
    CLAUDE_DIR,
    CODEBASE_DIR,
    CONCEPTS_DIR,
    GUARDRAILS_DIR,
    INPUT_DIR,
    MEETINGS_DIR,
    PROJECT_TEMP_DIR,
    config_dir,
    manifests_dir,
    runtime_prompts_dir,
    stories_dir,
)


def _resources_target_project_dir() -> Path:
    package_dir = Path(__file__).resolve().parent.parent.parent
    resources_dir = package_dir / "bundles" / "target_project"
    if not resources_dir.is_dir():
        raise ProjectError(
            f"Resources directory not found: {resources_dir}",
            detail={"resources_dir": str(resources_dir)},
        )
    return resources_dir


def _effective_multi_repo(config: InstallConfig) -> bool:
    """Return the persisted repository mode for the target project."""
    return config.multi_repo or len(config.repositories or []) > 1


def _build_repo_entries(config: InstallConfig) -> list[dict[str, str]]:
    """Build the ``repositories`` list for ``project.yaml``.

    Mirrors the declared repositories verbatim (carrying optional
    ``language``/``test_command``/``build_command`` fields when present) and
    falls back to the single default ``app`` repo when none are declared.
    Extracted from ``_build_project_yaml`` to keep its cognitive complexity
    within the S3776 budget (no behaviour change).

    Args:
        config: The install configuration carrying ``repositories``.

    Returns:
        The list of repository entry mappings for ``project.yaml``.
    """
    if not config.repositories:
        if config.multi_repo:
            raise ProjectError(
                "Multi-repo default scaffold requires explicit code repositories.",
                detail={
                    "multi_repo": True,
                    "default_project_structure": config.default_project_structure,
                    "expected": "Provide explicit repositories under codebase/<repo-name>.",
                },
            )
        if not config.default_project_structure:
            return [{"name": "app", "path": "."}]
        return [{"name": "app", "path": CODEBASE_DIR}]
    repos: list[dict[str, str]] = []
    for repo in config.repositories:
        entry: dict[str, str] = {
            "name": repo["name"],
            "path": repo["path"],
        }
        # AG3-088 (FK-50 §50.3 CP 10c): carry ``are_scope`` through so CP 10c can
        # validate each code repo's ARE scope against ``are.module_scope_map``.
        for optional_field in (
            "language",
            "test_command",
            "build_command",
            "are_scope",
            "remote_url",
        ):
            if optional_field in repo:
                entry[optional_field] = repo[optional_field]
        repos.append(entry)
    return repos


def _deploy_directory_structure(
    resources_dir: Path,
    target_root: Path,
) -> list[str]:
    created: list[str] = []

    for item in sorted(resources_dir.rglob("*")):
        rel = item.relative_to(resources_dir)
        if rel.parts[0] == "templates":
            continue

        target = target_root / rel
        if item.is_dir() and not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(rel))

    return created


_LINK_BINDPOINT_GITIGNORE_ENTRIES: tuple[str, ...] = (".claude/skills/", ".codex/skills/")
_PROJECT_SECRET_GITIGNORE_ENTRIES: tuple[str, ...] = (
    "/.agentkit/credentials",
    "/.agentkit/credentials.pending",
)


_PYTHON_CACHE_GITIGNORE_ENTRIES: tuple[str, ...] = ("__pycache__/", "*.py[cod]")


_GITKEEP_FILENAME = ".gitkeep"


def _read_foreign_text(path: Path) -> str:
    """Read a file AK3 does not own, losslessly.

    The installer appends to files the project brought with it. A `.gitignore`
    with a cp1252 comment and CRLF endings is legitimate and none of AK3's
    business -- but a read-modify-write must return every byte it did not touch.
    Two things are needed for that, and one alone is not enough:

    * ``surrogateescape`` carries bytes that are not valid UTF-8 through the
      decode unchanged. Strict decoding would abort the install; replacing
      decoding would silently write U+FFFD over the project's own line.
    * ``newline=""`` switches OFF universal-newline translation. Without it the
      read alone turns every CRLF into LF, and the write turns the whole file
      over -- lossless codec, rewritten file.
    """
    with path.open("r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        return handle.read()


def _write_foreign_text(path: Path, content: str) -> None:
    """Write back text obtained from :func:`_read_foreign_text`, byte for byte."""
    with path.open("w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(content)


def _newline_of(text: str) -> str:
    """Return the line ending the file already uses -- never a new convention."""
    return "\r\n" if "\r\n" in text else "\n"


def _append_gitignore_block(existing: str, comment: str, entries: list[str]) -> str:
    """Append a section to ``existing`` WITHOUT rewriting a byte of it."""
    newline = _newline_of(existing)
    parts = [existing]
    if existing and not existing.endswith(("\n", "\r")):
        parts.append(newline)  # terminate the project's unterminated last line
    if existing.strip() and not existing.endswith((newline * 2, "\n\n")):
        parts.append(newline)  # blank separator before the new section
    parts.append(comment + newline)
    parts.extend(entry + newline for entry in entries)
    return "".join(parts)


def _ensure_link_bindpoint_gitignore(root: Path) -> str | None:
    """Idempotently git-ignore the harness link bind points in *root*.

    Appends the harness bind points, the dedicated project credential file,
    and Python cache artefacts to ``{root}/.gitignore`` (creating the file if absent). Git and
    backups follow a junction, so a bound bind point would otherwise commit the
    central bundle content into the project repo (FK-43 §43.4.1.1). Only the
    ``skills`` subdir is ignored — sibling harness config such as
    ``.claude/settings.json`` stays tracked.

    Returns:
        The project-relative ``.gitignore`` path when it was created or modified,
        otherwise ``None`` (already complete — idempotent).
    """
    def _norm(entry: str) -> str:
        return entry.strip().rstrip("/")

    gitignore_path = root / ".gitignore"
    existing = _read_foreign_text(gitignore_path) if gitignore_path.is_file() else ""
    present = {_norm(line) for line in existing.splitlines()}
    required = (
        *_LINK_BINDPOINT_GITIGNORE_ENTRIES,
        *_PROJECT_SECRET_GITIGNORE_ENTRIES,
        *_PYTHON_CACHE_GITIGNORE_ENTRIES,
    )
    missing = [entry for entry in required if _norm(entry) not in present]
    if not missing:
        return None

    _write_foreign_text(
        gitignore_path,
        _append_gitignore_block(
            existing,
            "# AgentKit local bindings and credentials",
            missing,
        ),
    )
    return str(gitignore_path.relative_to(root))


def _ensure_default_scaffold_gitignore(config: InstallConfig, root: Path) -> str | None:
    """Ensure root-repo ignores for the optional default project scaffold.

    FK-10 §10.3.1a: ``temp/`` is always ignored in the default scaffold.
    ``codebase/`` is ignored only in multi-repo mode; in single-repo mode it is
    productive source under the root repository and must remain tracked.
    """
    required = [f"/{PROJECT_TEMP_DIR}/"]
    if _effective_multi_repo(config):
        required.append(f"/{CODEBASE_DIR}/")
    forbidden = [] if _effective_multi_repo(config) else [f"/{CODEBASE_DIR}/"]

    gitignore_path = root / ".gitignore"
    existing = _read_foreign_text(gitignore_path) if gitignore_path.is_file() else ""
    # `keepends` keeps every line ending exactly as the project wrote it; only
    # the forbidden lines are dropped, and nothing else is re-serialised.
    kept = [line for line in existing.splitlines(keepends=True) if line.strip() not in forbidden]
    present = {line.strip() for line in existing.splitlines()}
    missing = [entry for entry in required if entry not in present]
    changed = len(kept) != len(existing.splitlines(keepends=True))
    if not missing and not changed:
        return None

    remaining = "".join(kept)
    new_text = (
        _append_gitignore_block(remaining, "# AgentKit default project scaffold", missing)
        if missing
        else remaining
    )
    _write_foreign_text(gitignore_path, new_text)
    return str(gitignore_path.relative_to(root))


def _default_scaffold_base_dirs(root: Path) -> list[Path]:
    return [
        root / CONCEPTS_DIR,
        root / CODEBASE_DIR,
        root / PROJECT_TEMP_DIR,
        root / INPUT_DIR,
        root / MEETINGS_DIR,
        root / GUARDRAILS_DIR,
        stories_dir(root),
    ]


def _create_missing_dirs(root: Path, directories: list[Path]) -> list[str]:
    created: list[str] = []
    for directory in directories:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory.relative_to(root)))
    return created


def _default_scaffold_tracked_dirs(config: InstallConfig, root: Path) -> list[Path]:
    tracked = [
        root / CONCEPTS_DIR,
        root / INPUT_DIR,
        root / MEETINGS_DIR,
        root / GUARDRAILS_DIR,
        stories_dir(root),
    ]
    if not _effective_multi_repo(config):
        tracked.append(root / CODEBASE_DIR)
    return tracked


def _ensure_default_scaffold_gitkeep(config: InstallConfig, root: Path) -> list[str]:
    """Track empty, persistent default-scaffold directories in Git.

    Git does not version directories by themselves. FK-10 marks concepts/,
    guardrails/, input/, stories/ and single-repo codebase/ as persistent
    project content, so an empty new project needs placeholders there. temp/ is
    intentionally excluded because it has no persistence claim and is gitignored.
    """
    changed: list[str] = []
    for directory in _default_scaffold_tracked_dirs(config, root):
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / _GITKEEP_FILENAME
        if marker.exists():
            continue
        marker.write_text("", encoding="utf-8", errors="replace")
        changed.append(str(marker.relative_to(root)))
    return changed


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and next(path.iterdir(), None) is None


def _clone_repo(remote_url: str, target: Path) -> None:
    result = subprocess.run(
        ["git", "clone", remote_url, str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ProjectError(
            f"Failed to clone code repository into {target}.",
            detail={
                "remote_url": remote_url,
                "target": str(target),
                "stderr": result.stderr.strip(),
            },
        )


def _materialize_scaffold_repo_dir(root: Path, repo: dict[str, str]) -> str | None:
    repo_path = Path(repo["path"])
    if repo_path in (Path("."), Path(CODEBASE_DIR)) or repo_path.is_absolute():
        return None

    target = root / repo_path
    remote_url = repo.get("remote_url")
    if target.is_file():
        raise ProjectError(
            f"Default scaffold code repository path is a file: {repo_path}",
            detail={"path": str(repo_path), "repo": repo.get("name")},
        )
    if (target / ".git").is_dir():
        return None
    if remote_url is not None:
        if target.exists() and not _is_empty_dir(target):
            raise ProjectError(
                f"Default scaffold code repository path is non-empty and not a Git repo: {repo_path}",
                detail={"path": str(repo_path), "repo": repo.get("name")},
            )
        existed = target.exists()
        _clone_repo(remote_url, target)
        return None if existed else str(target.relative_to(root))
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        return str(target.relative_to(root))
    return None


def _materialize_scaffold_repo_dirs(config: InstallConfig, root: Path) -> list[str]:
    created: list[str] = []
    for repo in _build_repo_entries(config):
        rel = _materialize_scaffold_repo_dir(root, repo)
        if rel is not None:
            created.append(rel)
    return created


def scaffold_project_structure(config: InstallConfig, root: Path) -> list[str]:
    """Materialise the NEUTRAL project directory scaffold (CP 5 region).

    Transferred verbatim from the legacy ``install_agentkit`` pre-CP-7 body
    (behaviour preserved): the bundles/target_project directory mirror plus
    the empty runtime working directories. NEUTRAL structure only — no active
    harness binding is written here (those are deferred to STRICTLY after CP 7,
    the ``state_backend_registration_precedes_bundle_binding`` invariant).

    Args:
        config: The install configuration.
        root: The target-project root.

    Returns:
        The project-relative paths of the directories created (for reporting).
    """
    resources_dir = _resources_target_project_dir()
    created = _deploy_directory_structure(resources_dir, root)
    for runtime_dir in (
        config_dir(root),
        runtime_prompts_dir(root),
        manifests_dir(root),
        root / CLAUDE_DIR / "context",
    ):
        runtime_dir.mkdir(parents=True, exist_ok=True)
    if config.default_project_structure:
        created.extend(_create_missing_dirs(root, _default_scaffold_base_dirs(root)))
        created.extend(_materialize_scaffold_repo_dirs(config, root))
        created.extend(_ensure_default_scaffold_gitkeep(config, root))
        gitignore_rel = _ensure_default_scaffold_gitignore(config, root)
        if gitignore_rel is not None and gitignore_rel not in created:
            created.append(gitignore_rel)
    return created
