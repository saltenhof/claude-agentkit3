"""Regression pins for backend-owned third-system validation."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.backend.cli.main import main
from agentkit.backend.installer.runner import InstallConfig
from agentkit.harness_client.projectedge.credentials import (
    activate_project_credentials,
    prepare_project_api_token,
    project_credentials_path,
    write_pending_project_credentials,
)

if TYPE_CHECKING:
    import argparse


#: One tree entry: its kind, its kind-specific payload and its permission bits.
#:
#: ``payload`` is the file content for a regular file, the RAW link target for a
#: symlink (never the target's content) and ``None`` for a directory.
TreeEntry = tuple[str, bytes | str | None, int]


def _symlinks_are_creatable() -> bool:
    """Probe whether this process may create a symlink (Windows privilege)."""
    with tempfile.TemporaryDirectory() as raw:
        probe = Path(raw)
        (probe / "target").write_text("probe", encoding="utf-8")
        try:
            os.symlink(probe / "target", probe / "link")
        except (OSError, NotImplementedError):
            return False
    return True


#: Creating a symlink on Windows needs ``SeCreateSymbolicLinkPrivilege`` (Developer
#: Mode or an elevated shell); an unprivileged Windows worker cannot BUILD the
#: fixture. The comparison itself is platform-independent and runs everywhere --
#: only the symlink-construction cases below are gated, and they DO run on the
#: Linux CI worker that owns the full-suite proof.
_SYMLINKS_CREATABLE = _symlinks_are_creatable()


def _tree_snapshot(root: Path) -> dict[str, TreeEntry]:
    """Capture the complete tree below *root* -- not only its file contents.

    A snapshot that reads only ``read_bytes()`` of ``is_file()`` entries reports
    two trees as equal although they differ: an added or removed EMPTY directory
    is invisible, a regular file swapped for a SYMLINK of the same content is
    invisible, a re-pointed symlink whose new target holds the same bytes is
    invisible, and a permission change is invisible. This snapshot records the
    kind, the kind-specific payload and the permission bits of every entry, so
    each of those differences shows up as an inequality.

    Symlinks are recorded by their RAW target and are never followed, so a link
    to a directory neither hides the link nor duplicates the directory's contents.

    Args:
        root: The directory whose complete tree is captured.

    Returns:
        A mapping of the POSIX relative path of every entry to its
        :data:`TreeEntry`.
    """
    snapshot: dict[str, TreeEntry] = {}
    _collect_tree(root, root, snapshot)
    return snapshot


def _collect_tree(root: Path, current: Path, snapshot: dict[str, TreeEntry]) -> None:
    """Record every entry of *current* into *snapshot*, recursing into real dirs."""
    for entry in sorted(current.iterdir()):
        relative = entry.relative_to(root).as_posix()
        mode = stat.S_IMODE(entry.lstat().st_mode)
        if entry.is_symlink():
            snapshot[relative] = ("symlink", PurePath(os.readlink(entry)).as_posix(), mode)
            continue
        if entry.is_dir():
            snapshot[relative] = ("dir", None, mode)
            _collect_tree(root, entry, snapshot)
            continue
        snapshot[relative] = ("file", entry.read_bytes(), mode)


def _content_only_snapshot(root: Path) -> dict[str, bytes]:
    """Reproduce the file-contents-only comparison this module used before.

    Kept as an explicit witness: every dimension test below asserts that this
    weaker view reports the two trees as EQUAL while :func:`_tree_snapshot`
    reports the real difference.
    """
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _two_trees(tmp_path: Path) -> tuple[Path, Path]:
    """Create two sibling roots that hold the same single file."""
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root in (left, right):
        root.mkdir()
        (root / "kept.txt").write_bytes(b"same")
    return left, right


def test_tree_snapshot_sees_an_empty_directory_the_content_view_misses(
    tmp_path: Path,
) -> None:
    """AG3-214 B3: an added EMPTY directory is a real difference."""
    left, right = _two_trees(tmp_path)
    (right / "empty-dir").mkdir()

    assert _content_only_snapshot(left) == _content_only_snapshot(right)
    assert _tree_snapshot(left) != _tree_snapshot(right)
    assert "empty-dir" not in _tree_snapshot(left)
    assert _tree_snapshot(right)["empty-dir"][0] == "dir"


@pytest.mark.skipif(
    not _SYMLINKS_CREATABLE,
    reason="creating a symlink requires SeCreateSymbolicLinkPrivilege on Windows",
)
def test_tree_snapshot_sees_a_symlink_replacing_a_regular_file(tmp_path: Path) -> None:
    """AG3-214 B3: a symlink is not the same artifact as a file of equal content."""
    left, right = _two_trees(tmp_path)
    for root in (left, right):
        (root / "source.txt").write_bytes(b"payload")
    (left / "entry.txt").write_bytes(b"payload")
    os.symlink(right / "source.txt", right / "entry.txt")

    assert _content_only_snapshot(left) == _content_only_snapshot(right)
    left_snapshot = _tree_snapshot(left)
    right_snapshot = _tree_snapshot(right)
    assert left_snapshot != right_snapshot
    assert left_snapshot["entry.txt"][0] == "file"
    assert right_snapshot["entry.txt"][0] == "symlink"


@pytest.mark.skipif(
    not _SYMLINKS_CREATABLE,
    reason="creating a symlink requires SeCreateSymbolicLinkPrivilege on Windows",
)
def test_tree_snapshot_sees_a_repointed_symlink_with_identical_target_content(
    tmp_path: Path,
) -> None:
    """AG3-214 B3: the link TARGET is part of the tree, not only what it reads as."""
    left, right = _two_trees(tmp_path)
    for root in (left, right):
        (root / "first.txt").write_bytes(b"payload")
        (root / "second.txt").write_bytes(b"payload")
    os.symlink(left / "first.txt", left / "entry.txt")
    os.symlink(right / "second.txt", right / "entry.txt")

    assert _content_only_snapshot(left) == _content_only_snapshot(right)
    left_snapshot = _tree_snapshot(left)
    right_snapshot = _tree_snapshot(right)
    assert left_snapshot != right_snapshot
    assert left_snapshot["entry.txt"][1] != right_snapshot["entry.txt"][1]


def test_tree_snapshot_sees_a_permission_change(tmp_path: Path) -> None:
    """AG3-214 B3: a file turned read-only is a difference on every platform.

    Windows maps ``chmod`` onto the read-only attribute only, so the two modes
    differ there in fewer bits than on POSIX -- but they DO differ, which is what
    the comparison has to notice.
    """
    left, right = _two_trees(tmp_path)
    (left / "kept.txt").chmod(0o644)
    (right / "kept.txt").chmod(0o444)

    assert _content_only_snapshot(left) == _content_only_snapshot(right)
    left_snapshot = _tree_snapshot(left)
    right_snapshot = _tree_snapshot(right)
    assert left_snapshot != right_snapshot
    assert left_snapshot["kept.txt"][2] != right_snapshot["kept.txt"][2]
    (right / "kept.txt").chmod(0o644)


@pytest.mark.skipif(
    not _SYMLINKS_CREATABLE,
    reason="creating a symlink requires SeCreateSymbolicLinkPrivilege on Windows",
)
def test_tree_snapshot_does_not_descend_into_a_symlinked_directory(
    tmp_path: Path,
) -> None:
    """A linked directory is recorded as a link, never walked as if it were one."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "foreign.txt").write_bytes(b"foreign")
    os.symlink(outside, root / "linked")

    snapshot = _tree_snapshot(root)
    assert snapshot["linked"][0] == "symlink"
    assert "linked/foreign.txt" not in snapshot


def test_install_config_has_no_dev_third_system_client_slots() -> None:
    """The installer cannot receive a dev-side Sonar/Jenkins client."""
    forbidden = {
        "sonar_client",
        "sonar_token_permissions",
        "sonar_branch_plugin_self_test",
        "sonar_scan_runner",
        "ci_client",
    }
    assert forbidden.isdisjoint(InstallConfig.__dataclass_fields__)


def test_register_and_verify_instantiate_no_sonar_or_jenkins_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both CLI flows reach the engine without constructing third-system clients."""

    class _Result:
        success = True
        checkpoint_results: tuple[object, ...] = ()

    modes: list[str] = []

    def _run(_config: object, *, mode: object) -> _Result:
        modes.append(str(getattr(mode, "value", mode)))
        return _Result()

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a third-system client was instantiated in the dev process")

    monkeypatch.setattr(
        "agentkit.backend.installer.bootstrap_checkpoints.orchestrator."
        "run_checkpoint_install",
        _run,
    )
    monkeypatch.setattr("agentkit.integration_clients.sonar.SonarClient.__init__", _forbidden)
    monkeypatch.setattr(
        "agentkit.integration_clients.jenkins.JenkinsClient.__init__", _forbidden
    )

    def _writer_ready(
        config: object,
        args: object,
        op_id: str,
    ) -> object:
        del config, op_id
        from agentkit.backend.cli.auth_commands import prepare_installer_auth_context

        return prepare_installer_auth_context(cast("argparse.Namespace", args))

    monkeypatch.setattr(
        "agentkit.backend.cli.installer_commands._wire_register_config_to_writer",
        _writer_ready,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.writer_client.InstallerWriterClient.assert_ready",
        lambda _client: None,
    )
    common = [
        "--project-key",
        "ak3",
        "--project-name",
        "AgentKit",
        "--project-root",
        str(tmp_path),
        "--github-owner",
        "openai",
        "--github-repo",
        "agentkit",
    ]
    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-existing-credential",
    )
    activate_project_credentials(credential_path)

    assert main(["register-project", *common]) == 0
    assert main(["verify-project", *common]) == 0
    assert modes == ["register", "verify"]


def test_register_project_backend_unreachable_preserves_every_local_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """register-project fails before any local effect when no writer exists."""
    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-backend-failure-prerequisite",
    )
    activate_project_credentials(credential_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-backend-failure-prerequisite",
    )
    before = _tree_snapshot(tmp_path)

    exit_code = main(
        [
            "register-project",
            "--project-key",
            "ak3",
            "--project-name",
            "AgentKit",
            "--project-root",
            str(tmp_path),
            "--github-owner",
            "openai",
            "--github-repo",
            "agentkit",
            "--control-plane-base-url",
            "https://127.0.0.1:1",
        ]
    )

    assert exit_code != 0
    assert "ControlPlaneWriterUnavailable" in capsys.readouterr().err
    assert _tree_snapshot(tmp_path) == before


def test_upgrade_project_without_writer_preserves_every_local_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """upgrade-project names writer unavailability before mutating the project."""

    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-upgrade-writer-prerequisite",
    )
    activate_project_credentials(credential_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-upgrade-writer-prerequisite",
    )
    marker = tmp_path / "owned.txt"
    marker.write_text("unchanged", encoding="utf-8")
    (tmp_path / "owned-empty-dir").mkdir()
    before = _tree_snapshot(tmp_path)

    exit_code = main(
        [
            "upgrade-project",
            "--project-key",
            "ak3",
            "--project-root",
            str(tmp_path),
            "--github-owner",
            "openai",
            "--github-repo",
            "agentkit",
            "--target-config-version",
            "4.0",
            "--control-plane-base-url",
            "https://127.0.0.1:1",
        ]
    )

    assert exit_code != 0
    assert "ControlPlaneWriterUnavailable" in capsys.readouterr().err
    assert _tree_snapshot(tmp_path) == before
