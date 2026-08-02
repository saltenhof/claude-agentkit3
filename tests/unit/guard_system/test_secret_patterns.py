"""Shared secret-pattern source tests for hook and structural scans."""

from __future__ import annotations

import pytest

from agentkit.backend.governance.guard_system import secret_patterns
from agentkit.backend.governance.guard_system.secret_scan import scan_paths_and_diff

# Prefixes are split so this file never carries a complete credential shape --
# the pre-commit scan reads its own diff.
AWS_PREFIX = "AK" "IA"
GITHUB_PREFIX = "gh" "p_"
OPENAI_PREFIX = "sk" "-"

AWS_BODY = "IOSFODNN7EXAMPLE"
GITHUB_BODY = "0123456789abcdef0123456789abcdef0123"
OPENAI_BODY = "0123456789abcdefghijklmn"


def test_secret_file_patterns_cover_required_groups() -> None:
    paths = (
        "config/credentials.json",
        "config/serviceaccount.json",
        "env/APP_SECRET_VALUE",
        "env/API_TOKEN.txt",
        "env/DB_PASSWORD.txt",
        "release/signing.keystore",
        "release/signing.jks",
    )
    hits = secret_patterns.find_secret_file_hits(paths)
    assert {hit.path for hit in hits} == set(paths)


def test_secret_content_patterns_cover_required_prefixes() -> None:
    diff = "\n".join(
        (
            "diff --git a/a.py b/a.py",
            "+++ b/a.py",
            f"+aws = '{AWS_PREFIX}{AWS_BODY}'",
            "diff --git a/b.py b/b.py",
            "+++ b/b.py",
            f"+github = '{GITHUB_PREFIX}{GITHUB_BODY}'",
            "diff --git a/c.py b/c.py",
            "+++ b/c.py",
            f"+openai = '{OPENAI_PREFIX}{OPENAI_BODY}'",
        )
    )
    result = scan_paths_and_diff((), diff)
    assert [hit.pattern.value for hit in result.content_hits] == [
        AWS_PREFIX,
        GITHUB_PREFIX,
        OPENAI_PREFIX,
    ]


@pytest.mark.parametrize(
    "line",
    [
        # The concrete blocker: prose from concept/ that carries the prefix
        # inside a word. Blocked every full commit in a consuming project.
        "Der Score folgt der risk-adjusted-attraction aus der Formal-Spec.",
        "Task-Registry, Desk-Setup und Whisky-Tasting sind keine Secrets.",
        "grep -rn 'ghp_' docs/ | wc -l",
        "AKIAS ist kein Schluessel, sondern ein Tippfehler.",
    ],
)
def test_prefix_inside_a_word_is_not_a_secret(line: str) -> None:
    assert secret_patterns.secret_content_pattern_for(line) is None


@pytest.mark.parametrize(
    ("prefix", "body"),
    [
        (AWS_PREFIX, AWS_BODY),
        (GITHUB_PREFIX, GITHUB_BODY),
        (OPENAI_PREFIX, OPENAI_BODY),
    ],
)
def test_token_at_line_start_and_after_separators_is_a_secret(
    prefix: str,
    body: str,
) -> None:
    token = f"{prefix}{body}"
    for line in (token, f"key = '{token}'", f"Authorization: Bearer {token}"):
        assert secret_patterns.secret_content_pattern_for(line) is not None


@pytest.mark.parametrize(
    ("prefix", "body"),
    [
        (AWS_PREFIX, AWS_BODY),
        (GITHUB_PREFIX, GITHUB_BODY),
        (OPENAI_PREFIX, OPENAI_BODY),
    ],
)
def test_token_shorter_than_the_issued_shape_is_not_a_secret(
    prefix: str,
    body: str,
) -> None:
    minimum = next(
        pattern.min_body_length
        for pattern in secret_patterns.SECRET_CONTENT_PATTERNS
        if pattern.value == prefix
    )
    too_short = f"x = '{prefix}{body[: minimum - 1]}'"
    assert secret_patterns.secret_content_pattern_for(too_short) is None


def test_token_body_length_matches_the_issued_credential_shape() -> None:
    lengths = {
        pattern.value: pattern.min_body_length
        for pattern in secret_patterns.SECRET_CONTENT_PATTERNS
    }
    assert lengths == {AWS_PREFIX: 16, GITHUB_PREFIX: 36, OPENAI_PREFIX: 20}
    assert len(AWS_BODY) == 16
    assert len(GITHUB_BODY) == 36
    assert len(OPENAI_BODY) == 24


def test_clean_paths_and_diff_are_clean() -> None:
    result = scan_paths_and_diff(("src/app.py",), "+++ b/src/app.py\n+value = 1\n")
    assert result.clean is True


def test_hook_scanner_and_pattern_module_share_one_source() -> None:
    diff = f"+++ b/app.py\n+token = '{GITHUB_PREFIX}{GITHUB_BODY}'\n"
    result = scan_paths_and_diff(("prod/credentials.json",), diff)
    assert result.file_hits[0].pattern in secret_patterns.SECRET_FILE_PATTERNS
    assert result.content_hits[0].pattern in secret_patterns.SECRET_CONTENT_PATTERNS
