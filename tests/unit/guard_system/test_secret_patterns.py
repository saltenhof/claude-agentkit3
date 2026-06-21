"""Shared secret-pattern source tests for hook and structural scans."""

from __future__ import annotations

from agentkit.backend.governance.guard_system import secret_patterns
from agentkit.backend.governance.guard_system.secret_scan import scan_paths_and_diff

AWS_PREFIX = "AK" "IA"
GITHUB_PREFIX = "gh" "p_"
OPENAI_PREFIX = "sk" "-"


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
            f"+aws = '{AWS_PREFIX}1234567890'",
            "diff --git a/b.py b/b.py",
            "+++ b/b.py",
            f"+github = '{GITHUB_PREFIX}abc'",
            "diff --git a/c.py b/c.py",
            "+++ b/c.py",
            f"+openai = '{OPENAI_PREFIX}test'",
        )
    )
    result = scan_paths_and_diff((), diff)
    assert [hit.pattern.value for hit in result.content_hits] == [
        AWS_PREFIX,
        GITHUB_PREFIX,
        OPENAI_PREFIX,
    ]


def test_clean_paths_and_diff_are_clean() -> None:
    result = scan_paths_and_diff(("src/app.py",), "+++ b/src/app.py\n+value = 1\n")
    assert result.clean is True


def test_hook_scanner_and_pattern_module_share_one_source() -> None:
    diff = f"+++ b/app.py\n+token = '{GITHUB_PREFIX}example'\n"
    result = scan_paths_and_diff(("prod/credentials.json",), diff)
    assert result.file_hits[0].pattern in secret_patterns.SECRET_FILE_PATTERNS
    assert result.content_hits[0].pattern in secret_patterns.SECRET_CONTENT_PATTERNS
