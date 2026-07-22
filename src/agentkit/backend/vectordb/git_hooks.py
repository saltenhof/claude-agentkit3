"""Materialise project-local pre-commit / post-commit hooks (AG3-176 AC4/R6).

Reuses the FK-51 hook_migration markers and surgical dispatch append so
existing secret-detection is never replaced wholesale. Dispatch itself is
argv-safe via :mod:`agentkit.backend.vectordb.hook_dispatch`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 -- Path used at runtime
from typing import Final

from agentkit.backend.installer.upgrade.hook_migration import (
    GIT_HOOK_DISPATCH_MARKERS,
    has_dispatch_block,
)

SECRET_DETECTION_MARKER: Final = "agentkit secret-detection"

POST_COMMIT_MARKERS: Final[tuple[str, ...]] = (
    "# >>> agentkit post-commit concept >>>",
    "# <<< agentkit post-commit concept <<<",
)

_HOOKS_REL: Final = ("tools", "hooks")
_PRE_COMMIT: Final = "pre-commit"
_POST_COMMIT: Final = "post-commit"


@dataclass(frozen=True)
class HookMaterializeResult:
    """Outcome of hook materialisation."""

    pre_commit_path: Path
    post_commit_path: Path
    pre_commit_written: bool
    post_commit_written: bool
    detail: str


def hooks_dir(project_root: Path) -> Path:
    return project_root.joinpath(*_HOOKS_REL)


def pre_commit_path(project_root: Path) -> Path:
    return hooks_dir(project_root) / _PRE_COMMIT


def post_commit_path(project_root: Path) -> Path:
    return hooks_dir(project_root) / _POST_COMMIT


def _normalize_concepts_dir(concepts_dir: str) -> str:
    rel = concepts_dir.strip().replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("concepts_dir must be non-empty for hook dispatch")
    return rel


def _dispatch_block(*, concepts_dir: str, mode: str) -> str:
    """Render the marked AgentKit dispatch block using the Python dispatcher."""
    cdir = _normalize_concepts_dir(concepts_dir)
    if mode == "pre-commit":
        start, end = GIT_HOOK_DISPATCH_MARKERS
        cmd = (
            'python -m agentkit.backend.vectordb.hook_dispatch pre-commit '
            '--project-root "$REPO_ROOT" '
            f'--concepts-dir "{cdir}"'
        )
        body = (
            f"{start}\n"
            "# Path-based concept validation (FK-30 §30.5.3 / AG3-176 R6)\n"
            f"# concepts_dir={cdir}\n"
            f"{cmd}\n"
            f"{end}\n"
        )
        return body
    start, end = POST_COMMIT_MARKERS
    cmd = (
        'python -m agentkit.backend.vectordb.hook_dispatch post-commit '
        '--project-root "$REPO_ROOT" '
        f'--concepts-dir "{cdir}"'
    )
    return (
        f"{start}\n"
        f"# concepts_dir={cdir}\n"
        f"{cmd}\n"
        f"{end}\n"
    )


def _base_secret_pre_commit() -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"# {SECRET_DETECTION_MARKER} (global, FK-15 §15.5.2 / AG3-176 R6)\n"
        "set -euo pipefail\n"
        'REPO_ROOT="$(git rev-parse --show-toplevel)"\n'
        'cd "$REPO_ROOT"\n'
        'PYTHON="${PYTHON:-python}"\n'
        'echo "[pre-commit] Running global secret scan..."\n'
        '"$PYTHON" -m agentkit.backend.governance.guard_system.secret_scan '
        '--staged --repo-root "$REPO_ROOT"\n'
    )


def _base_post_commit() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# AgentKit post-commit (FK-30 §30.5.4a / AG3-176 R6)\n"
        "set -u\n"
        'REPO_ROOT="$(git rev-parse --show-toplevel)"\n'
        'cd "$REPO_ROOT"\n'
    )


def pre_commit_is_current(content: str, *, concepts_dir: str) -> bool:
    """True when secret-detection + marked dispatch with validate are present."""
    if SECRET_DETECTION_MARKER not in content:
        return False
    if "agentkit.backend.governance.guard_system.secret_scan" not in content:
        return False
    if not has_dispatch_block(content):
        return False
    if "hook_dispatch pre-commit" not in content:
        return False
    if "--staged" not in content and "validate" not in content:
        # dispatcher handles --staged internally; require dispatch command
        pass
    cdir = _normalize_concepts_dir(concepts_dir)
    return f'--concepts-dir "{cdir}"' in content or f"concepts_dir={cdir}" in content


def post_commit_is_current(content: str, *, concepts_dir: str) -> bool:
    if not all(m in content for m in POST_COMMIT_MARKERS):
        return False
    if "hook_dispatch post-commit" not in content:
        return False
    cdir = _normalize_concepts_dir(concepts_dir)
    return f'--concepts-dir "{cdir}"' in content or f"concepts_dir={cdir}" in content


def materialize_concept_git_hooks(
    project_root: Path,
    *,
    concepts_dir: str,
    mutate: bool,
) -> HookMaterializeResult:
    """Materialise pre-commit + post-commit under ``tools/hooks/``.

    Surgical (AG3-176 R6 / FK-51 §51.6.1):
    * Recognised AgentKit secret-detection pre-commit: append/update dispatch
      block only; secret-detection lines stay.
    * Unrecognised customizations: fail-closed detail, no silent rewrite when
      mutate=True would destroy foreign content — backup + write only if the
      file is absent or already AgentKit-origin.
    """
    pre_path = pre_commit_path(project_root)
    post_path = post_commit_path(project_root)
    dispatch_pre = _dispatch_block(concepts_dir=concepts_dir, mode="pre-commit")
    dispatch_post = _dispatch_block(concepts_dir=concepts_dir, mode="post-commit")

    pre_exists = pre_path.is_file()
    post_exists = post_path.is_file()
    pre_content = pre_path.read_text(encoding="utf-8") if pre_exists else ""
    post_content = post_path.read_text(encoding="utf-8") if post_exists else ""

    pre_current = pre_exists and pre_commit_is_current(
        pre_content, concepts_dir=concepts_dir
    )
    post_current = post_exists and post_commit_is_current(
        post_content, concepts_dir=concepts_dir
    )
    pre_needed = not pre_current
    post_needed = not post_current

    if not mutate:
        return HookMaterializeResult(
            pre_commit_path=pre_path,
            post_commit_path=post_path,
            pre_commit_written=False,
            post_commit_written=False,
            detail=(
                f"Would materialise concept hooks "
                f"(pre_commit_change={pre_needed}, post_commit_change={post_needed})."
            ),
        )

    if not pre_needed and not post_needed:
        return HookMaterializeResult(
            pre_commit_path=pre_path,
            post_commit_path=post_path,
            pre_commit_written=False,
            post_commit_written=False,
            detail="Concept pre-commit and post-commit hooks already current.",
        )

    from agentkit.backend.installer.file_ops import atomic_write_text

    hooks_dir(project_root).mkdir(parents=True, exist_ok=True)
    pre_written = False
    post_written = False

    if pre_needed:
        if pre_exists and SECRET_DETECTION_MARKER not in pre_content:
            # Unrecognised foreign hook: fail-closed for manual resolution
            # (do not destroy; backup and refuse automated rewrite).
            bak = pre_path.with_suffix(pre_path.suffix + ".bak")
            bak.write_bytes(pre_path.read_bytes())
            return HookMaterializeResult(
                pre_commit_path=pre_path,
                post_commit_path=post_path,
                pre_commit_written=False,
                post_commit_written=False,
                detail=(
                    "Unrecognised pre-commit customization preserved as "
                    f"{bak.name}; refusing silent rewrite (AG3-176 R6 / FK-51). "
                    "Resolve manually then re-run."
                ),
            )
        if pre_exists and SECRET_DETECTION_MARKER in pre_content:
            # Surgical: keep existing secret-detection body, replace only
            # AgentKit dispatch markers if present, else append.
            body = pre_content
            if has_dispatch_block(body):
                # Replace between markers
                start = body.find(GIT_HOOK_DISPATCH_MARKERS[0])
                end = body.find(GIT_HOOK_DISPATCH_MARKERS[1])
                if start >= 0 and end >= 0:
                    end += len(GIT_HOOK_DISPATCH_MARKERS[1])
                    body = body[:start] + dispatch_pre + body[end:].lstrip("\n")
                else:
                    if not body.endswith("\n"):
                        body += "\n"
                    body += dispatch_pre
            else:
                if not body.endswith("\n"):
                    body += "\n"
                # Ensure REPO_ROOT is set for dispatch
                if "REPO_ROOT=" not in body:
                    body = (
                        body.rstrip()
                        + '\nREPO_ROOT="$(git rev-parse --show-toplevel)"\n'
                    )
                body += dispatch_pre
            atomic_write_text(pre_path, body)
        else:
            atomic_write_text(pre_path, _base_secret_pre_commit() + dispatch_pre)
        _try_chmod_executable(pre_path)
        pre_written = True

    if post_needed:
        if post_exists and all(m in post_content for m in POST_COMMIT_MARKERS):
            start = post_content.find(POST_COMMIT_MARKERS[0])
            end = post_content.find(POST_COMMIT_MARKERS[1])
            if start >= 0 and end >= 0:
                end += len(POST_COMMIT_MARKERS[1])
                body = (
                    post_content[:start]
                    + dispatch_post
                    + post_content[end:].lstrip("\n")
                )
            else:
                body = post_content.rstrip() + "\n" + dispatch_post
            atomic_write_text(post_path, body)
        else:
            atomic_write_text(post_path, _base_post_commit() + dispatch_post)
        _try_chmod_executable(post_path)
        post_written = True

    return HookMaterializeResult(
        pre_commit_path=pre_path,
        post_commit_path=post_path,
        pre_commit_written=pre_written,
        post_commit_written=post_written,
        detail=(
            f"Materialised concept hooks "
            f"(pre_commit_written={pre_written}, post_commit_written={post_written})."
        ),
    )


def _try_chmod_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
    except OSError:
        return


__all__ = [
    "POST_COMMIT_MARKERS",
    "SECRET_DETECTION_MARKER",
    "HookMaterializeResult",
    "hooks_dir",
    "materialize_concept_git_hooks",
    "post_commit_is_current",
    "post_commit_path",
    "pre_commit_is_current",
    "pre_commit_path",
]
