"""Sonar accept-frequency signal for the failure-corpus BC (FK-41 §41.10, AG3-078).

Measures the proportion of stories that accepted at least one issue of a rule,
compares against ``sonarqube.accept_frequency_fc_threshold`` (Config field, CP1),
and records a ``policy_violation`` incident via ``record_incident`` if exceeded.

FAIL-CLOSED against CP1 (the config field ``accept_frequency_fc_threshold``):
if ``SonarQubeConfig`` does not carry the field, this module raises an error
(no silent default, no story-local second value).

The threshold comparison logic is testable in isolation via the
``check_accept_frequency`` function which accepts an injected threshold.

Sources:
- FK-41 §41.10 -- Sonar accept-frequency signal
- FK-03 §3.1 -- SonarQubeConfig stanza (CP1: accept_frequency_fc_threshold is a
  Cross-Story-Prerequisite — owner is project-config/AG3-070)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.core_types import FailureCategory

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.failure_corpus.incident import IncidentCandidate
    from agentkit.failure_corpus.types import IncidentId

#: Source identifier used in Sonar accept-frequency incidents.
_SONAR_ACCEPT_FREQ_SOURCE = "sonar-accept-frequency"


def check_accept_frequency(
    *,
    accept_count: int,
    total_count: int,
    threshold: float,
) -> bool:
    """Pure logic: determine if accept frequency exceeds the threshold.

    Decoupled from Config for isolated testing (buildable without CP1).

    Args:
        accept_count: Number of stories that accepted at least one Sonar issue.
        total_count: Total number of stories in the measurement window.
        threshold: Accept-frequency threshold (0.0–1.0).

    Returns:
        True if the accept frequency exceeds (>) the threshold.
    """
    if total_count == 0:
        return False
    frequency = accept_count / total_count
    return frequency > threshold


def _read_threshold_from_config(project_root: Path) -> float:
    """Read ``sonarqube.accept_frequency_fc_threshold`` from project config.

    FAIL-CLOSED: if ``SonarQubeConfig`` does not have the field,
    ``AttributeError`` is raised — no silent default (CP1 gated).

    Args:
        project_root: Project root directory (required by ``load_project_config``).

    Returns:
        The configured threshold value.

    Raises:
        AttributeError: If the config field is absent (CP1 not delivered).
        RuntimeError: If SonarQube config is not available.
    """
    # Attempt to load the config (fail-closed if not available)
    try:
        from agentkit.config import load_project_config

        config = load_project_config(project_root)
        sonar_config = config.sonarqube  # type: ignore[attr-defined]
    except Exception as exc:
        raise RuntimeError(
            "SonarAcceptFrequency: could not load project config "
            f"(CP1 prerequisite unmet): {exc}"
        ) from exc

    # FAIL-CLOSED: the field must exist on SonarQubeConfig
    # (CP1: this field is a cross-story-prerequisite from AG3-070)
    if sonar_config is None or not hasattr(sonar_config, "accept_frequency_fc_threshold"):
        raise AttributeError(
            "SonarAcceptFrequency: SonarQubeConfig.accept_frequency_fc_threshold "
            "is not defined (Cross-Story-Prerequisite CP1; owner: project-config/AG3-070). "
            "This field must be added to SonarQubeConfig before this signal can run. "
            "FAIL-CLOSED: no story-local default (SINGLE SOURCE OF TRUTH)."
        )
    threshold = sonar_config.accept_frequency_fc_threshold
    return float(threshold)


class SonarAcceptFrequencySignal:
    """Sonar accept-frequency signal (FK-41 §41.10, AG3-078).

    Measures the proportion of stories accepting Sonar issues and records
    a ``policy_violation`` incident if the threshold is exceeded.

    Args:
        record_incident_fn: Callable matching ``FailureCorpus.record_incident``
            signature — injected to avoid circular import.
        project_key: Project key for the incident.
        story_id: Story anchor for the incident.
        run_id: Run anchor for the incident.
        model: Model identifier for the incident.
        project_root: Project root directory for loading the threshold from config.
            Required when ``threshold`` is not injected into ``evaluate()``.
    """

    def __init__(
        self,
        record_incident_fn: Callable[[IncidentCandidate], IncidentId],
        project_key: str,
        story_id: str,
        run_id: str,
        model: str = "sonar-signal",
        project_root: Path | None = None,
    ) -> None:
        self._record_incident = record_incident_fn
        self._project_key = project_key
        self._story_id = story_id
        self._run_id = run_id
        self._model = model
        self._project_root = project_root

    def evaluate(
        self,
        *,
        accept_count: int,
        total_count: int,
        rule_key: str = "global",
        threshold: float | None = None,
    ) -> IncidentId | None:
        """Evaluate the accept-frequency signal and record an incident if exceeded.

        Args:
            accept_count: Number of stories accepting at least one Sonar issue.
            total_count: Total stories in measurement window.
            rule_key: Sonar rule key being evaluated (default ``"global"``).
            threshold: Injected threshold for testing (default: read from config via
                ``project_root``).

        Returns:
            The recorded ``IncidentId`` if threshold exceeded, else ``None``.

        Raises:
            AttributeError: If CP1 is not delivered and no threshold injected.
            RuntimeError: If ``project_root`` is None and no threshold injected.
        """
        if threshold is None:
            if self._project_root is None:
                raise RuntimeError(
                    "SonarAcceptFrequencySignal.evaluate: project_root must be set "
                    "when threshold is not injected (CP1 gated config read requires "
                    "project_root). Inject threshold for tests."
                )
            threshold = _read_threshold_from_config(self._project_root)

        exceeded = check_accept_frequency(
            accept_count=accept_count,
            total_count=total_count,
            threshold=threshold,
        )
        if not exceeded:
            return None

        frequency = (accept_count / total_count) if total_count > 0 else 0.0
        return self._emit_incident(rule_key=rule_key, frequency=frequency, threshold=threshold)

    def _emit_incident(
        self,
        *,
        rule_key: str,
        frequency: float,
        threshold: float,
    ) -> IncidentId:
        """Record a policy_violation incident for the exceeded threshold.

        Args:
            rule_key: The Sonar rule key.
            frequency: Observed accept frequency.
            threshold: The configured threshold.

        Returns:
            The recorded ``IncidentId``.
        """
        from agentkit.failure_corpus.incident import IncidentCandidate
        from agentkit.failure_corpus.types import IncidentRole, IncidentSeverity

        symptom = (
            f"Sonar accept-frequency for rule '{rule_key}' is "
            f"{frequency:.1%} (threshold: {threshold:.1%})"
        )
        candidate = IncidentCandidate(
            project_key=self._project_key,
            story_id=self._story_id,
            run_id=self._run_id,
            category=FailureCategory.POLICY_VIOLATION,
            severity=IncidentSeverity.HIGH,
            phase="governance",
            role=IncidentRole.GOVERNANCE,
            model=self._model,
            symptom=symptom,
            evidence=[
                f"sonar_rule={rule_key}",
                f"accept_frequency={frequency:.4f}",
                f"threshold={threshold:.4f}",
                f"source={_SONAR_ACCEPT_FREQ_SOURCE}",
            ],
            merge_blocked=False,
        )
        return self._record_incident(candidate)


__all__ = [
    "SonarAcceptFrequencySignal",
    "check_accept_frequency",
]
