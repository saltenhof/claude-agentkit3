"""Atomic owner for mandatory pre/post-commit dispatch materialization."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

GIT_HOOK_DISPATCH_MARKERS: Final[tuple[str, str]] = (
    "# >>> agentkit pre-commit dispatch >>>",
    "# <<< agentkit pre-commit dispatch <<<",
)
POST_COMMIT_DISPATCH_MARKERS: Final[tuple[str, str]] = (
    "# >>> agentkit post-commit dispatch >>>",
    "# <<< agentkit post-commit dispatch <<<",
)
_SECRET_DETECTION_MARKER: Final = "agentkit secret-detection"
_LEGACY_SECRET_MARKER: Final = "# agentkit secret-detection (global)"
_LEGACY_SECRET_MODULE: Final = (
    "agentkit.backend.governance.guard_system.secret_scan"
)
_HOOKS_PATH_VALUE: Final = "tools/hooks/"
_GIT_CONFIG_KEY: Final = "core.hooksPath"
_PRESERVED_SUFFIX: Final = ".bak"
_SHEBANG: Final = "#!/bin/sh\n"


@dataclass(frozen=True)
class GitHookMigrationOutcome:
    """Result of atomically materializing and activating the hook pair."""

    migrated: bool
    backup_path: Path | None
    detail: str


@dataclass(frozen=True)
class _FileBeforeImage:
    path: Path
    content: bytes | None
    mode: int | None


def _pre_commit_path(project_root: Path) -> Path:
    return project_root / "tools" / "hooks" / "pre-commit"


def _post_commit_path(project_root: Path) -> Path:
    return project_root / "tools" / "hooks" / "post-commit"


def _preserved_path(hook_path: Path) -> Path:
    return hook_path.with_name(hook_path.name + _PRESERVED_SUFFIX)


def _is_marker_line(line: str, marker: str) -> bool:
    """Return whether ``line`` IS the sentinel, not merely contains it.

    A foreign hook that mentions the sentinel -- ``echo '# >>> ... >>>'`` -- must
    not be read as a managed block; substring matching let the removal path
    delete the foreign code between two such mentions.
    """
    return line.strip() == marker


def has_dispatch_block(content: str) -> bool:
    """Return whether ``content`` carries the complete managed marker pair."""
    lines = content.splitlines()
    return all(
        any(_is_marker_line(line, marker) for line in lines)
        for marker in GIT_HOOK_DISPATCH_MARKERS
    )


def _read_before(path: Path) -> _FileBeforeImage:
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlinked hook path: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"hook path is not a regular file: {path}")
    return _FileBeforeImage(
        path=path,
        content=path.read_bytes() if path.is_file() else None,
        mode=stat.S_IMODE(path.stat().st_mode) if path.is_file() else None,
    )


def _decode_hook(before: _FileBeforeImage) -> str:
    if before.content is None:
        return ""
    # `surrogateescape` carries bytes that are not valid UTF-8 through unchanged
    # and back out on write, so there is no rejection path left to handle: a
    # foreign hook with a cp1252 comment is preserved, not refused.
    return before.content.decode("utf-8", errors="surrogateescape")


def _remove_managed_block(
    lines: list[str],
    markers: tuple[str, str],
) -> list[str]:
    output: list[str] = []
    inside = False
    found_start = False
    for line in lines:
        if _is_marker_line(line, markers[0]):
            if inside or found_start:
                raise ValueError("hook contains duplicate managed dispatch blocks")
            inside = True
            found_start = True
            continue
        if _is_marker_line(line, markers[1]):
            if not inside:
                raise ValueError("hook contains an unmatched dispatch end marker")
            inside = False
            continue
        if not inside:
            output.append(line)
    if inside:
        raise ValueError("hook contains an unterminated managed dispatch block")
    return output


def _is_legacy_secret_marker_candidate(line: str) -> bool:
    """Return whether ``line`` is an AgentKit secret-owner MARKER, not a mention.

    A foreign hook that echoes the words -- ``echo "agentkit secret-detection
    enabled"`` -- carries the text but is the project's own code. Only a comment
    line qualifies; a comment that deviates from the canonical marker still
    raises downstream, so an AgentKit variant is never rewritten half-way.
    """
    stripped = line.strip()
    return stripped.startswith("#") and _SECRET_DETECTION_MARKER in stripped


def _remove_legacy_secret_owner(lines: list[str]) -> list[str]:
    """Remove the canonical legacy AgentKit secret owner, retaining foreign code."""
    marker_indexes = [
        index for index, line in enumerate(lines) if _is_legacy_secret_marker_candidate(line)
    ]
    if not marker_indexes:
        return lines
    _verify_legacy_interpreter(lines)
    remove = set(marker_indexes)
    for marker_index in marker_indexes:
        remove.add(_legacy_secret_command_index(lines, marker_index))
    return [line for index, line in enumerate(lines) if index not in remove]


def _verify_legacy_interpreter(lines: list[str]) -> None:
    if not lines or lines[0].strip() not in {
        "#!/bin/sh",
        "#!/usr/bin/env sh",
        "#!/bin/bash",
        "#!/usr/bin/env bash",
    }:
        raise ValueError(
            "legacy AgentKit secret block occurs under an unknown interpreter"
        )


def _legacy_secret_command_index(lines: list[str], marker_index: int) -> int:
    if lines[marker_index].strip() != _LEGACY_SECRET_MARKER:
        raise ValueError(
            "unrecognised AgentKit secret marker; refusing a partial rewrite"
        )
    for index in range(marker_index + 1, len(lines)):
        candidate = lines[index].strip()
        if not candidate:
            continue
        try:
            argv = tuple(shlex.split(candidate, posix=True))
        except ValueError as exc:
            raise ValueError(
                "legacy AgentKit secret command is not valid shell argv"
            ) from exc
        if (
            len(argv) == 4
            and argv[0] in {"python", "python3"}
            and argv[1:] == ("-m", _LEGACY_SECRET_MODULE, "--staged")
        ):
            return index
        raise ValueError(
            "legacy AgentKit secret marker is not followed by its canonical "
            "secret-scan command"
        )
    raise ValueError("legacy AgentKit secret marker has no canonical command")


def _foreign_body(
    content: str,
    markers: tuple[str, str],
    *,
    remove_legacy_secret: bool,
) -> str:
    lines = _remove_managed_block(content.splitlines(keepends=True), markers)
    if remove_legacy_secret:
        lines = _remove_legacy_secret_owner(lines)
    body = "".join(lines)
    if not body.strip() or (
        lines
        and lines[0].startswith("#!")
        and not "".join(lines[1:]).strip()
    ):
        return ""
    if not lines or not lines[0].startswith("#!"):
        raise ValueError(
            "foreign hook has no interpreter shebang; refusing to guess one"
        )
    return body


def _dispatch_interpreter() -> str:
    """Return the ABSOLUTE interpreter the git hooks must dispatch through.

    A bare ``python`` was written into both hooks until 2026-08-02. Whatever
    interpreter happened to be first on the committing shell's ``PATH`` then ran
    the dispatch — an interpreter that generally does NOT carry AK3's
    dependencies, because AK3 lives in its own venv. The failure surfaced at the
    first commit of the installed project, as a missing third-party import, long
    after the installer had reported success.

    This is the SAME defect the MCP registration carried, one level further out,
    and it is resolved through the SAME owner: there is exactly one answer to
    "which interpreter is AK3's", and it lives in :mod:`mcp_registration`.
    Duplicating the resolution here would recreate the drift it removes.
    """
    from agentkit.backend.installer.mcp_registration import (
        resolve_story_knowledge_base_command,
    )

    return resolve_story_knowledge_base_command()


def _render_chain(hook_name: str) -> str:
    preserved_name = hook_name + _PRESERVED_SUFFIX
    return (
        f'PRESERVED_HOOK="$(dirname "$0")/{preserved_name}"\n'
        'if [ -x "$PRESERVED_HOOK" ]; then\n'
        '  "$PRESERVED_HOOK" "$@" || exit $?\n'
        "fi\n"
    )


def _render_pre_commit(*, has_foreign: bool) -> str:
    content = _SHEBANG + (
        f"{GIT_HOOK_DISPATCH_MARKERS[0]}\n"
        'PROJECT_ROOT="$(git rev-parse --show-toplevel)" || exit 1\n'
        f"{shlex.quote(_dispatch_interpreter())} -m agentkit.backend.vectordb.hook_dispatch "
        '--project-root "$PROJECT_ROOT" --phase pre-commit || exit $?\n'
        f"{GIT_HOOK_DISPATCH_MARKERS[1]}\n"
    )
    return content + (_render_chain("pre-commit") if has_foreign else "")


def _render_post_commit(*, has_foreign: bool) -> str:
    content = _SHEBANG + (
        f"{POST_COMMIT_DISPATCH_MARKERS[0]}\n"
        'PROJECT_ROOT="$(git rev-parse --show-toplevel)" || exit 1\n'
        f"{shlex.quote(_dispatch_interpreter())} -m agentkit.backend.vectordb.hook_dispatch "
        '--project-root "$PROJECT_ROOT" --phase post-commit || exit $?\n'
        f"{POST_COMMIT_DISPATCH_MARKERS[1]}\n"
    )
    return content + (_render_chain("post-commit") if has_foreign else "")


def _current_hooks_path(project_root: Path) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603
            [
                "git",
                "-C",
                str(project_root),
                "config",
                "--local",
                "--get",
                _GIT_CONFIG_KEY,
            ],
            # BYTES: the two channels carry different contracts and `text=True`
            # can only give them one decoder. The VALUE is compared and written
            # back on rollback, so it must survive losslessly; stderr is
            # diagnosis and is flattened, so a bad byte in an error message
            # cannot raise on its way out and bury the real failure.
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"cannot read core.hooksPath: {exc}") from exc
    if completed.returncode == 1:
        return None
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"cannot read core.hooksPath: {detail}")
    value = completed.stdout.decode("utf-8", errors="surrogateescape").rstrip("\r\n")
    if not value:
        raise OSError("core.hooksPath is present with an empty value")
    return value


def _write_hooks_path(project_root: Path, value: str | None) -> None:
    command = [
        "git",
        "-C",
        str(project_root),
        "config",
        "--local",
    ]
    if value is None:
        command.extend(("--unset-all", _GIT_CONFIG_KEY))
    else:
        command.extend((_GIT_CONFIG_KEY, value))
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"cannot update core.hooksPath: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        raise OSError(f"cannot update core.hooksPath: {detail}")


def _publish_hook(path: Path, content: str) -> None:
    from agentkit.backend.utils.io import atomic_write_text

    # `surrogateescape` mirrors `_decode_hook`: a foreign hook body that is not
    # UTF-8 -- a cp1252 comment is enough -- comes back out as the bytes it went
    # in as. Strict encoding here would reject the very hook we preserved.
    atomic_write_text(path, content, newline="", errors="surrogateescape")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _restore_file(before: _FileBeforeImage) -> None:
    """Restore a before-image BYTE for byte -- a rollback may not reinterpret."""
    if before.content is None:
        if before.path.exists() or before.path.is_symlink():
            before.path.unlink()
        return
    # The image was taken with `read_bytes`; decoding it here only invented a
    # way for the rollback to fail on content it had already captured intact.
    tmp = before.path.with_suffix(before.path.suffix + ".restore-tmp")
    try:
        tmp.write_bytes(before.content)
        os.replace(str(tmp), str(before.path))
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise
    if before.mode is None:
        raise OSError(f"existing hook before-image has no file mode: {before.path}")
    os.chmod(before.path, before.mode)


def _foreign_bodies(
    before_files: tuple[_FileBeforeImage, ...],
) -> tuple[str, str]:
    current_pre = _decode_hook(before_files[0])
    current_post = _decode_hook(before_files[1])
    current_pre_preserved = _decode_hook(before_files[2])
    current_post_preserved = _decode_hook(before_files[3])
    pre_is_canonical = current_pre == _render_pre_commit(
        has_foreign=bool(current_pre_preserved),
    )
    post_is_canonical = current_post == _render_post_commit(
        has_foreign=bool(current_post_preserved),
    )
    if not pre_is_canonical and current_pre_preserved:
        raise ValueError(
            f"preserved pre-commit chain is already occupied: {before_files[2].path}"
        )
    if not post_is_canonical and current_post_preserved:
        raise ValueError(
            f"preserved post-commit chain is already occupied: {before_files[3].path}"
        )
    pre_foreign = (
        _foreign_body(
            current_pre_preserved,
            GIT_HOOK_DISPATCH_MARKERS,
            remove_legacy_secret=True,
        )
        if pre_is_canonical
        else _foreign_body(
            current_pre,
            GIT_HOOK_DISPATCH_MARKERS,
            remove_legacy_secret=True,
        )
    )
    post_foreign = (
        _foreign_body(
            current_post_preserved,
            POST_COMMIT_DISPATCH_MARKERS,
            remove_legacy_secret=False,
        )
        if post_is_canonical
        else _foreign_body(
            current_post,
            POST_COMMIT_DISPATCH_MARKERS,
            remove_legacy_secret=False,
        )
    )
    return pre_foreign, post_foreign


def _publish_hook_state(
    project_root: Path,
    hook_paths: tuple[Path, Path],
    preserved_paths: tuple[Path, Path],
    foreign_bodies: tuple[str, str],
) -> None:
    expected = (
        _render_pre_commit(has_foreign=bool(foreign_bodies[0])),
        _render_post_commit(has_foreign=bool(foreign_bodies[1])),
    )
    for path, content in zip(hook_paths, expected, strict=True):
        _publish_hook(path, content)
    for path, body in zip(preserved_paths, foreign_bodies, strict=True):
        if body:
            _publish_hook(path, body)
        elif path.exists():
            path.unlink()
    _verify_hook_files(project_root)
    _write_hooks_path(project_root, _HOOKS_PATH_VALUE)
    verify_git_hook_dispatch(project_root)


def _restore_mutation(
    before_files: tuple[_FileBeforeImage, ...],
    project_root: Path,
    hooks_path_before: str | None,
) -> None:
    errors: list[str] = []
    for before in reversed(before_files):
        try:
            _restore_file(before)
        except OSError as exc:
            errors.append(str(exc))
    try:
        current = _current_hooks_path(project_root)
        if current != hooks_path_before:
            _write_hooks_path(project_root, hooks_path_before)
    except OSError as exc:
        errors.append(str(exc))
    hooks_dir = _pre_commit_path(project_root).parent
    tools_dir = hooks_dir.parent
    for directory in (hooks_dir, tools_dir):
        with suppress(OSError):
            directory.rmdir()
    if errors:
        raise OSError("hook rollback failed: " + "; ".join(errors))


def migrate_git_hook_dispatch(project_root: Path) -> GitHookMigrationOutcome:
    """Atomically write, verify, then activate the surgical hook pair."""
    pre = _pre_commit_path(project_root)
    post = _post_commit_path(project_root)
    pre_preserved = _preserved_path(pre)
    post_preserved = _preserved_path(post)
    hook_paths = (pre, post)
    preserved_paths = (pre_preserved, post_preserved)
    before_files = tuple(
        _read_before(path)
        for path in (*hook_paths, *preserved_paths)
    )
    hooks_path_before = _current_hooks_path(project_root)
    current_pre = _decode_hook(before_files[0])
    current_post = _decode_hook(before_files[1])
    current_pre_preserved = _decode_hook(before_files[2])
    current_post_preserved = _decode_hook(before_files[3])
    foreign_bodies = _foreign_bodies(before_files)
    pre_foreign, post_foreign = foreign_bodies
    expected = (
        _render_pre_commit(has_foreign=bool(pre_foreign)),
        _render_post_commit(has_foreign=bool(post_foreign)),
    )
    current_preserved = (current_pre_preserved, current_post_preserved)
    desired_preserved = foreign_bodies
    changed = (
        current_pre != expected[0]
        or current_post != expected[1]
        or current_preserved != desired_preserved
        or (
            bool(pre_foreign)
            and not os.access(before_files[2].path, os.X_OK)
        )
        or (
            bool(post_foreign)
            and not os.access(before_files[3].path, os.X_OK)
        )
        or hooks_path_before != _HOOKS_PATH_VALUE
    )
    if not changed:
        verify_git_hook_dispatch(project_root)
        return GitHookMigrationOutcome(
            migrated=False,
            backup_path=None,
            detail="Canonical hook pair and core.hooksPath are already current.",
        )
    try:
        _publish_hook_state(
            project_root,
            hook_paths,
            preserved_paths,
            foreign_bodies,
        )
    except (OSError, ValueError) as exc:
        try:
            _restore_mutation(
                before_files,
                project_root,
                hooks_path_before,
            )
        except OSError as rollback_exc:
            raise OSError(
                f"hook migration failed ({exc}); {rollback_exc}",
            ) from rollback_exc
        raise
    backup = pre_preserved if pre_foreign else None
    return GitHookMigrationOutcome(
        migrated=True,
        backup_path=backup,
        detail="Canonical hook pair was verified before core.hooksPath activation.",
    )


def _verify_hook_files(project_root: Path) -> None:
    pre = _pre_commit_path(project_root)
    post = _post_commit_path(project_root)
    if not pre.is_file() or not post.is_file():
        raise ValueError("canonical pre-commit/post-commit hooks are missing")
    pre_foreign = _preserved_path(pre).is_file()
    post_foreign = _preserved_path(post).is_file()
    if pre.read_text(encoding="utf-8", errors="replace") != _render_pre_commit(
        has_foreign=pre_foreign,
    ):
        raise ValueError("pre-commit canonical dispatch block is incomplete")
    if post.read_text(encoding="utf-8", errors="replace") != _render_post_commit(
        has_foreign=post_foreign,
    ):
        raise ValueError("post-commit canonical dispatch block is incomplete")
    for preserved, markers, remove_secret in (
        (_preserved_path(pre), GIT_HOOK_DISPATCH_MARKERS, True),
        (_preserved_path(post), POST_COMMIT_DISPATCH_MARKERS, False),
    ):
        if not preserved.is_file():
            continue
        content = preserved.read_text(encoding="utf-8", errors="replace")
        if (
            _foreign_body(
                content,
                markers,
                remove_legacy_secret=remove_secret,
            )
            != content
        ):
            raise ValueError(
                f"preserved hook is not a canonical foreign body: {preserved}"
            )
        if not os.access(preserved, os.X_OK):
            raise ValueError(f"preserved hook is not executable: {preserved}")


def verify_git_hook_dispatch(project_root: Path) -> None:
    """Verify the exact hook pair, activation, and runtime argv contract."""
    from agentkit.backend.vectordb.hook_dispatch import (
        post_commit_commands,
        pre_commit_commands,
    )

    _verify_hook_files(project_root)
    if _current_hooks_path(project_root) != _HOOKS_PATH_VALUE:
        raise ValueError("core.hooksPath does not activate the canonical hook pair")
    configured = project_root / "__configured_concepts_dir__"
    secret, validate = pre_commit_commands(
        project_root,
        configured.relative_to(project_root),
    )
    build, sync = post_commit_commands(
        project_root,
        configured.relative_to(project_root),
    )
    expected_path = str(configured)
    if (
        secret[-1] != "--staged"
        or validate[-2:] != ("validate", "--staged")
        or expected_path not in validate
    ):
        raise ValueError("pre-commit staged validation contract is incomplete")
    if (
        build[-1] != "build"
        or sync[-1] != "sync"
        or "--full" in sync
        or expected_path not in build
        or expected_path not in sync
    ):
        raise ValueError("post-commit must build before sync on the configured path")


__all__ = [
    "GIT_HOOK_DISPATCH_MARKERS",
    "POST_COMMIT_DISPATCH_MARKERS",
    "GitHookMigrationOutcome",
    "has_dispatch_block",
    "migrate_git_hook_dispatch",
    "verify_git_hook_dispatch",
]
