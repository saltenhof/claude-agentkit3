"""Shared secret-pattern source tests for hook and structural scans."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentkit.backend.governance.guard_system import secret_patterns
from agentkit.backend.governance.guard_system.secret_scan import (
    scan_paths_and_diff,
    scan_staged_diff,
)

# Prefixes are split so this file never carries a complete credential shape --
# the pre-commit scan reads its own diff.
AWS_PREFIX = "AK" "IA"
GITHUB_PREFIX = "gh" "p_"
OPENAI_PREFIX = "sk" "-"

AWS_BODY = "IOSFODNN7EXAMPLE"
GITHUB_BODY = "0123456789abcdef0123456789abcdef0123"
OPENAI_BODY = "proj-0123456789abcdefghijklmn"

CREDENTIALS = ((AWS_PREFIX, AWS_BODY), (GITHUB_PREFIX, GITHUB_BODY), (OPENAI_PREFIX, OPENAI_BODY))

CONCEPT_ROOT = Path(__file__).resolve().parents[3] / "concept"


def _diff(*files: tuple[str, str]) -> str:
    """Render a unified diff in the shape ``git diff --unified=0`` emits."""
    parts: list[str] = []
    for path, line in files:
        parts.extend(
            (
                f"diff --git a/{path} b/{path}",
                f"--- a/{path}",
                f"+++ b/{path}",
                "@@ -0,0 +1 @@",
                f"+{line}",
            )
        )
    return "\n".join(parts)


def test_secret_file_patterns_cover_required_groups() -> None:
    paths = (
        "config/credentials.json",
        "config/serviceaccount.json",
        "env/APP_SECRET_VALUE",
        "env/API_TOKEN.txt",
        "env/DB_PASSWORD.txt",
        "release/signing.keystore",
        "release/signing.jks",
        # FK-15 §15.5.2 norms `.env.*`, not only a bare `.env`.
        "config/.env.local",
        "deploy/app.env.production",
    )
    hits = secret_patterns.find_secret_file_hits(paths)
    assert {hit.path for hit in hits} == set(paths)


def test_secret_content_patterns_cover_required_prefixes() -> None:
    result = scan_paths_and_diff(
        (),
        _diff(
            ("a.py", f"aws = '{AWS_PREFIX}{AWS_BODY}'"),
            ("b.py", f"github = '{GITHUB_PREFIX}{GITHUB_BODY}'"),
            ("c.py", f"openai = '{OPENAI_PREFIX}{OPENAI_BODY}'"),
        ),
    )
    assert [hit.pattern.value for hit in result.content_hits] == [
        AWS_PREFIX,
        GITHUB_PREFIX,
        OPENAI_PREFIX,
    ]
    assert [hit.path for hit in result.content_hits] == ["a.py", "b.py", "c.py"]


def test_every_documented_issuer_family_is_covered() -> None:
    """AWS temporary keys and the full GitHub family must not fall through."""
    families = ("AS" "IA", "gh" "o_", "gh" "u_", "gh" "s_", "gh" "r_", "github" "_pat_")
    for prefix in families:
        line = f"token = '{prefix}{'A' * 40}'"
        assert secret_patterns.secret_content_pattern_for(line) is not None, prefix


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


def test_the_repository_own_concept_prose_is_not_a_secret() -> None:
    """The scanner runs against the real corpus, not against invented lines.

    A pattern set is only usable if it stays silent on the prose it will
    actually meet. This reads the whole concept corpus -- the same text that
    made the previous substring matcher reject every commit.
    """
    offenders: list[str] = []
    for path in sorted(CONCEPT_ROOT.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if secret_patterns.secret_content_pattern_for(line) is not None:
                offenders.append(f"{path.relative_to(CONCEPT_ROOT).as_posix()}:{number}: {line}")
    assert offenders == [], "secret patterns hit concept prose: " + " | ".join(offenders[:5])


@pytest.mark.parametrize(("prefix", "body"), CREDENTIALS)
def test_token_at_line_start_and_after_separators_is_a_secret(prefix: str, body: str) -> None:
    token = f"{prefix}{body}"
    for line in (token, f"key = '{token}'", f"Authorization: Bearer {token}", f'"key":"{token}"'):
        assert secret_patterns.secret_content_pattern_for(line) is not None, line


@pytest.mark.parametrize(("prefix", "body"), CREDENTIALS)
def test_token_shorter_than_the_false_positive_floor_is_not_a_secret(
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


def test_every_floor_stays_below_the_shortest_known_issuance() -> None:
    """The floor is a false-positive bound, never a claimed issuer length.

    Set at or above the real issuance, a shortened or changed upstream format
    would silently stop being detected. The known shapes are longer than every
    floor, with margin.
    """
    floors = {p.value: p.min_body_length for p in secret_patterns.SECRET_CONTENT_PATTERNS}
    for prefix, body in CREDENTIALS:
        assert floors[prefix] < len(body), prefix


def test_clean_paths_and_diff_are_clean() -> None:
    result = scan_paths_and_diff(("src/app.py",), _diff(("src/app.py", "value = 1")))
    assert result.clean is True


def test_added_line_that_starts_with_plus_signs_is_still_scanned() -> None:
    """``++counter`` reaches the parser as ``+++counter`` -- payload, not header."""
    result = scan_paths_and_diff(
        (),
        _diff(("c.c", f"++counter; // key={OPENAI_PREFIX}{OPENAI_BODY}")),
    )
    assert [hit.path for hit in result.content_hits] == ["c.c"]


@pytest.mark.requires_git
def test_scan_reads_a_real_staged_git_diff(tmp_path: Path) -> None:
    """The parser is fed by real ``git diff`` output, not by a handwritten string."""

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    _git("init", "-q")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "T")
    # German prose in the same diff: the scan must survive it on every platform.
    (tmp_path / "doc.md").write_text(
        "Die risk-adjusted-attraction misst die Guete der Massnahme.\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        f"TOKEN = '{GITHUB_PREFIX}{GITHUB_BODY}'\n",
        encoding="utf-8",
    )
    _git("add", ".")

    result = scan_staged_diff(tmp_path)
    assert [(hit.path, hit.pattern.value) for hit in result.content_hits] == [
        ("app.py", GITHUB_PREFIX)
    ]


def test_hook_scanner_and_pattern_module_share_one_source() -> None:
    diff = _diff(("app.py", f"token = '{GITHUB_PREFIX}{GITHUB_BODY}'"))
    result = scan_paths_and_diff(("prod/credentials.json",), diff)
    assert result.file_hits[0].pattern in secret_patterns.SECRET_FILE_PATTERNS
    assert result.content_hits[0].pattern in secret_patterns.SECRET_CONTENT_PATTERNS
