"""Productive wiring of the pre-merge runners (AG3-056).

This is the ONE place that turns the live config (the ``ci``/``sonarqube``
stanzas + resolved tokens) into productive
:class:`PreMergeScanPort` / :class:`BuildTestPort` runners for the Closure
pre-merge barrier (AG3-053). The Closure consumer calls this to obtain real,
commit-bound runners; the seam stays fakeable for tests.

Applicability (AG3-056 §2.1.4, mirrors FK-33 §33.6.5 "absent != broken"):

* ``ci.available == false`` (deliberate, declared absence) -> the runner is
  NOT APPLICABLE; this returns ``None`` and the consumer treats it as a
  declared skip (NOT a failure).
* ``ci.available == true`` but the endpoint/token cannot be resolved
  (configured-but-unreachable / misconfigured) -> fail-closed:
  :class:`PreMergeRunnerUnavailableError` is raised. It is NEVER downgraded
  to a silent not-applicable skip.

The Sonar scan runner additionally needs the ``sonarqube`` stanza + token; a
code-producing project must declare both (config-load enforces it). When
Sonar is declared absent on a CI-present project this is a misconfiguration
for the pre-merge barrier and fails closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.pre_merge_runner.build_test_runner import CiBuildTestRunner
from agentkit.backend.verify_system.pre_merge_runner.ci_run import (
    CandidateRunCache,
    JenkinsCiBackend,
)
from agentkit.backend.verify_system.pre_merge_runner.scan_runner import (
    CiSonarScanRunner,
)
from agentkit.backend.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger

if TYPE_CHECKING:
    from agentkit.backend.config.models import JenkinsConfig, SonarQubeConfig
    from agentkit.backend.verify_system.pre_merge_runner.contract import (
        BuildTestPort,
        PreMergeScanPort,
    )

#: Repo-relative accepted-exception ledger artefact (FK-33 §33.6.4, FK-71),
#: shared with the AG3-052 gate. Absent file == valid empty ledger.
_LEDGER_REL = Path(".agentkit") / "sonar" / "accepted-exceptions.json"


class PreMergeRunnerUnavailableError(Exception):
    """The pre-merge runners are APPLICABLE but cannot be wired (fail-closed).

    Raised when ``ci.available == true`` (the runner is required) but the CI
    or Sonar endpoint/token cannot be resolved. The Closure pre-merge barrier
    converts this into an escalation — NEVER a silent skip (AG3-056 §2.1.4).
    """


@dataclass(frozen=True)
class PreMergeRunners:
    """The pair of commit-bound runners for the pre-merge barrier.

    Attributes:
        scan: The :class:`PreMergeScanPort` (commit-bound Sonar scan).
        build_test: The :class:`BuildTestPort` (commit-bound build+test).
    """

    scan: PreMergeScanPort
    build_test: BuildTestPort


def build_pre_merge_runners(
    ci_config: JenkinsConfig | None,
    sonar_config: SonarQubeConfig | None,
    repo_root: Path,
    *,
    ci_token: str | None = None,
    sonar_token: str | None = None,
) -> PreMergeRunners | None:
    """Build the productive pre-merge runners from the live config.

    Both runners share ONE :class:`CandidateRunCache` (and therefore ONE CI
    run per candidate, FIX-3), so AG3-053 obtains build/test + scan for one
    candidate from one run with a single triggered build.

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza (``None`` only
            for non-code-producing projects).
        sonar_config: The resolved ``sonarqube`` config stanza.
        repo_root: Root of the integrated-candidate git repository, used to
            derive the proven commit's ``tree_hash`` (FIX-4) and to load the
            accepted-exception ledger bound into the attestation.
        ci_token: The resolved Jenkins token (from ``ci.token_env``). When
            ``None`` the env var is read here.
        sonar_token: The resolved Sonar token (from ``sonarqube.token_env``).
            When ``None`` the env var is read here.

    Returns:
        * ``None`` when the runner is NOT applicable as a deliberate, declared
          absence (no ``ci`` stanza or ``ci.available == false``). The
          consumer treats this as a declared skip.
        * a :class:`PreMergeRunners` pair when the runner is applicable and
          the CI + Sonar endpoints resolve.

    Raises:
        PreMergeRunnerUnavailableError: When the runner is APPLICABLE
            (``ci.available == true``) but the CI or Sonar endpoint/token
            cannot be resolved (fail-closed; never a silent skip).
    """
    if ci_config is None or not ci_config.available:
        return None

    backend = _build_ci_backend(ci_config, ci_token)
    run_cache = CandidateRunCache(backend=backend)
    scan_runner = _build_scan_runner(
        sonar_config, run_cache, repo_root, sonar_token
    )
    build_test_runner = CiBuildTestRunner(run_cache=run_cache)
    return PreMergeRunners(scan=scan_runner, build_test=build_test_runner)


def build_build_test_runner(
    ci_config: JenkinsConfig | None,
    repo_root: Path,
    *,
    ci_token: str | None = None,
) -> BuildTestPort | None:
    """Build ONLY the commit-bound Build/Test runner from the live CI config.

    Additive companion to :func:`build_pre_merge_runners` (AG3-056 §2.1.4): the
    Closure barrier needs a Build/Test runner WITHOUT a Sonar scan runner when
    Sonar is DECLARED absent on a CI-present code-producing project (FK-33
    §33.6.5 "absent != broken", AG3-053 FIX-3). This builds the same CI backend
    and :class:`CiBuildTestRunner` as the paired wiring (no second CI truth);
    the integrated-candidate scan + Dim 9 are then skipped by the consumer.

    Args:
        ci_config: The resolved ``ci`` (Jenkins) config stanza.
        repo_root: Unused here (the build/test facet needs no tree/ledger read);
            kept for signature symmetry with :func:`build_pre_merge_runners`.
        ci_token: The resolved Jenkins token (read from env when ``None``).

    Returns:
        * ``None`` for a declared-absent CI (no ``ci`` stanza / ``available ==
          false``).
        * a :class:`BuildTestPort` when CI is applicable and resolvable.

    Raises:
        PreMergeRunnerUnavailableError: When CI is APPLICABLE but the endpoint /
            token cannot be resolved (fail-closed; never a silent skip).
    """
    del repo_root
    if ci_config is None or not ci_config.available:
        return None
    backend = _build_ci_backend(ci_config, ci_token)
    run_cache = CandidateRunCache(backend=backend)
    return CiBuildTestRunner(run_cache=run_cache)


def _build_ci_backend(
    ci_config: JenkinsConfig, ci_token: str | None
) -> JenkinsCiBackend:
    from agentkit.integration_clients.jenkins import JenkinsClient

    if not ci_config.base_url or not ci_config.pipeline:
        raise PreMergeRunnerUnavailableError(
            "ci.available=true requires base_url and pipeline (AG3-056 §2.1.6)"
        )
    token = ci_token if ci_token is not None else _resolve_token(
        ci_config.token_env, what="ci"
    )
    client = JenkinsClient(ci_config.base_url, token, user=ci_config.user)
    return JenkinsCiBackend(
        client=client,
        pipeline=ci_config.pipeline,
        poll_timeout_seconds=ci_config.poll_timeout_seconds,
        poll_interval_seconds=ci_config.poll_interval_seconds,
    )


def _build_scan_runner(
    sonar_config: SonarQubeConfig | None,
    run_cache: CandidateRunCache,
    repo_root: Path,
    sonar_token: str | None,
) -> CiSonarScanRunner:
    from agentkit.integration_clients.sonar import SonarClient

    if sonar_config is None or not sonar_config.available:
        raise PreMergeRunnerUnavailableError(
            "the pre-merge scan runner requires an available sonarqube stanza "
            "(a CI-present code-producing project must declare Sonar present, "
            "AG3-056 §2.1.3 / FK-33 §33.6.3)"
        )
    if not sonar_config.base_url:
        raise PreMergeRunnerUnavailableError(
            "sonarqube.available=true requires base_url (FK-03 §3)"
        )
    token = sonar_token if sonar_token is not None else _resolve_token(
        sonar_config.token_env, what="sonarqube"
    )
    client = SonarClient(sonar_config.base_url, token)
    return CiSonarScanRunner(
        run_cache=run_cache,
        client=client,
        config=sonar_config,
        ledger=_load_ledger(repo_root),
    )


def _load_ledger(repo_root: Path) -> AcceptedExceptionLedger:
    """Load the accepted-exception ledger from the candidate repo (fail-closed).

    An ABSENT ledger file is a valid empty ledger (no exceptions declared); a
    PRESENT-but-invalid ledger fails closed (the attestation must not bind a
    corrupt exception set, FK-33 §33.6.4). Reused 1:1 from the AG3-052 gate
    discipline (no second ledger truth).
    """
    path = repo_root / _LEDGER_REL
    if not path.is_file():
        return AcceptedExceptionLedger()
    try:
        return AcceptedExceptionLedger.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise PreMergeRunnerUnavailableError(
            f"accepted-exception ledger at {path} is unreadable/invalid: {exc}"
        ) from exc


def _resolve_token(token_env: str | None, *, what: str) -> str:
    if not token_env:
        raise PreMergeRunnerUnavailableError(
            f"{what}.token_env is not set on an available=true config "
            "(cannot authenticate the scoped client)"
        )
    token = os.environ.get(token_env)
    if not token:
        raise PreMergeRunnerUnavailableError(
            f"{what} token env {token_env!r} is unset/empty "
            "(no scoped token for the client)"
        )
    return token


__all__ = [
    "PreMergeRunnerUnavailableError",
    "PreMergeRunners",
    "build_build_test_runner",
    "build_pre_merge_runners",
]
