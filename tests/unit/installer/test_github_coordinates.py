"""Unit tests for the installer github-coordinates derivation (AG3-039 R5).

Covers the remote-URL parser and the ``git remote get-url origin`` derivation,
including every fail-closed path (non-github / malformed / missing remote /
git failure) so a CLI install can rely on a ``None`` to mean "demand the flags".
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.installer.github_coordinates import (
    derive_github_coordinates,
    parse_github_remote_url,
    validate_github_coordinate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/widget", ("acme", "widget")),
        ("https://github.com/acme/widget.git", ("acme", "widget")),
        ("https://github.com/acme/widget/", ("acme", "widget")),
        ("https://user@github.com/acme/widget.git", ("acme", "widget")),
        ("git@github.com:acme/widget.git", ("acme", "widget")),
        ("git@github.com:acme/widget", ("acme", "widget")),
        ("ssh://git@github.com/acme/widget.git", ("acme", "widget")),
        ("  https://github.com/acme/widget.git  ", ("acme", "widget")),
    ],
)
def test_parse_github_remote_url_accepts_github_shapes(
    url: str, expected: tuple[str, str]
) -> None:
    assert parse_github_remote_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://gitlab.com/acme/widget.git",  # non-github host => fail-closed
        "https://example.com/acme/widget",
        "not-a-url",
        "https://github.com/onlyowner",  # missing repo
        "git@github.com:onlyowner",
        "https://github.com//widget",  # empty owner
    ],
)
def test_parse_github_remote_url_rejects_non_github_or_malformed(url: str) -> None:
    assert parse_github_remote_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        # AG3-039 R6 E-b: malformed / path-traversal coordinates fail closed.
        "https://github.com/../repo.git",  # path-traversal owner
        "https://github.com/owner/..",  # path-traversal repo
        "https://github.com/owner/.",  # current-dir repo token
        "https://github.com/acme/.git",  # repo is a bare ".git" => "." => reject
        "git@github.com:acme/.git",
        "https://github.com/-bad/repo.git",  # leading-hyphen owner
        "https://github.com/bad-/repo.git",  # trailing-hyphen owner
        "https://github.com/ac me/repo.git",  # space in owner
        "https://github.com/acme/re po.git",  # space in repo
        "https://github.com/a--b/repo.git",  # consecutive hyphens in owner
        # owner > 39 chars => reject
        "https://github.com/" + ("a" * 40) + "/repo.git",
        # repo > 100 chars => reject
        "https://github.com/acme/" + ("r" * 101) + ".git",
    ],
)
def test_parse_github_remote_url_rejects_malformed_coordinates(url: str) -> None:
    assert parse_github_remote_url(url) is None


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        ("acme", "widget"),
        ("a", "b"),
        ("a-b-c", "my.repo_name-1"),
        ("a" * 39, "r" * 100),  # max lengths
        ("Acme123", "Repo_With.Dots-and-dashes"),
        ("a-b", "repo.js"),  # single internal hyphen owner, dotted repo
        ("a", "b"),  # single-char owner and repo
        ("acme", "_x"),  # repo may start with underscore
        ("a" * 39, "demo"),  # owner exactly 39 chars
        ("acme", "r" * 100),  # repo exactly 100 chars
    ],
)
def test_validate_github_coordinate_accepts_valid(owner: str, repo: str) -> None:
    assert validate_github_coordinate(owner, repo) == (owner, repo)


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        # AG3-039 R7 ERROR-1: ``$`` + ``.match`` tolerates a trailing ``\n``;
        # ``re.fullmatch`` rejects ANY trailing newline / control char.
        ("acme\n", "repo"),  # trailing LF owner
        ("acme", "repo\n"),  # trailing LF repo
        ("acme\r", "repo"),  # trailing CR owner
        ("ac\nme", "repo"),  # embedded newline owner
        ("acme", "re\npo"),  # embedded newline repo
        ("acme\t", "repo"),  # trailing tab owner
        ("acme", "repo\t"),  # trailing tab repo
        ("acme ", "repo"),  # trailing space owner
        ("acme", "repo "),  # trailing space repo
        ("ac\x00me", "repo"),  # embedded NUL owner
        ("acme", "re\x00po"),  # embedded NUL repo
        ("acme\x07", "repo"),  # embedded BEL control char owner
        # GitHub logins/repos are ASCII alnum (+hyphen/dot/underscore); Unicode
        # letters must be rejected, never silently accepted.
        ("äcme", "repo"),  # non-ASCII letter owner
        ("acme", "rëpo"),  # non-ASCII letter repo
        ("ＡＣＭＥ", "repo"),  # fullwidth latin owner
    ],
)
def test_validate_github_coordinate_rejects_control_and_unicode(
    owner: str, repo: str
) -> None:
    """ERROR-1: control chars / trailing newline / non-ASCII are fail-closed."""
    assert validate_github_coordinate(owner, repo) is None


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        ("", "repo"),  # empty owner
        ("acme", ""),  # empty repo
        ("   ", "repo"),  # whitespace owner
        ("acme", "   "),  # whitespace repo
        ("..", "repo"),  # path-traversal owner
        ("acme", ".."),  # path-traversal repo
        ("acme", "."),  # current-dir repo token
        ("-bad", "repo"),  # leading hyphen owner
        ("bad-", "repo"),  # trailing hyphen owner
        ("a--b", "repo"),  # consecutive hyphens owner
        ("ac me", "repo"),  # space in owner
        ("acme", "re po"),  # space in repo
        ("acme", ".hidden"),  # leading dot repo
        ("acme/evil", "repo"),  # slash in owner
        ("acme", "re/po"),  # slash in repo
        ("a" * 40, "repo"),  # owner too long
        ("acme", "r" * 101),  # repo too long
    ],
)
def test_validate_github_coordinate_rejects_invalid(owner: str, repo: str) -> None:
    assert validate_github_coordinate(owner, repo) is None


def test_derive_github_coordinates_from_origin_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parseable origin remote yields the (owner, repo) pair."""

    def fake_run(
        argv: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert list(argv) == [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "get-url",
            "origin",
        ]
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout="git@github.com:acme/widget.git\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert derive_github_coordinates(tmp_path) == ("acme", "widget")


def test_derive_github_coordinates_returns_none_on_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero git exit (no repo / no origin remote) fails closed to None."""

    def fake_run(
        argv: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, returncode=128, stdout="", stderr="fatal: not a git repository"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert derive_github_coordinates(tmp_path) is None


def test_derive_github_coordinates_returns_none_when_git_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git not installed (FileNotFoundError) fails closed to None, never raises."""

    def fake_run(_argv: Sequence[str], **_kwargs: object) -> object:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert derive_github_coordinates(tmp_path) is None


def test_derive_github_coordinates_returns_none_on_unparseable_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-github origin URL yields None (caller must demand the flags)."""

    def fake_run(
        argv: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout="https://gitlab.com/acme/widget.git\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert derive_github_coordinates(tmp_path) is None
