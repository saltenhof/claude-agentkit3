"""Contract test: the remote-gate script reads the credential sources that carry.

`scripts/ci/check_remote_gates.ps1` used to source its credentials from
`T:\\seu\\agentkit3-secrets.cmd` -- a machine-local file outside the repository --
via `$env:SONAR_URL` (a key `.env` does not define) and `$env:JENKINS_USER` /
`$env:JENKINS_API_TOKEN`. From a clean shell it aborted with "credentials
missing"; from a stale one Jenkins answered 401. Either way it failed at
AUTHENTICATION instead of at the gate, so a red result carried no information --
and nothing noticed, because `scripts/` was outside every static check.

CLAUDE.md declares the sources that do carry: `.env` in the repo root for
SonarQube, and `var/jenkins-api-token.txt` with user `admin` for Jenkins. The
live proof is a real run; this test keeps the wiring from drifting back.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_remote_gates.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _script_code() -> str:
    """Return the executable script without its comments.

    The header block deliberately names the old, broken credential path so a
    reader understands why the current one exists. Assertions about what the
    script DOES must not trip over that prose.
    """
    text = re.sub(r"<#.*?#>", "", _script(), flags=re.DOTALL)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_script_does_not_depend_on_a_machine_local_secrets_file() -> None:
    assert "agentkit3-secrets.cmd" not in _script_code()


def test_sonar_credentials_come_from_dotenv() -> None:
    text = _script_code()
    # `.env` uses SONAR_HOST_URL; the old `SONAR_URL` key exists nowhere.
    assert "SONAR_HOST_URL" in text
    assert 'Get-DotEnvValue "SONAR_USER"' in text
    assert 'Get-DotEnvValue "SONAR_PASSWORD"' in text


def test_jenkins_credentials_come_from_the_token_file() -> None:
    text = _script_code()
    assert "var\\jenkins-api-token.txt" in text
    assert '{ "admin" }' in text


def test_authentication_is_preemptive() -> None:
    """Jenkins answers anonymously with 403, so a 401 challenge never arrives."""
    text = _script_code()
    assert "Authorization" in text
    assert "Basic " in text
    # `-Credential` only attaches after a challenge Jenkins does not send.
    assert "-Credential" not in text
    assert "-Authentication Basic" not in text


def test_dotenv_is_the_documented_source_in_claude_md() -> None:
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "var/jenkins-api-token.txt" in claude_md
    assert "403" in claude_md
