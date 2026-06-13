"""Governance-observer configuration accessor (FK-93 §93.5).

Config owner is the ``governance`` BC.  The three parameters
``governance.window_size``, ``governance.risk_threshold`` and
``governance.cooldown_s`` are stored in :class:`~agentkit.config.models.GovernanceConfig`
(the project-level config model) — this module provides a typed accessor
so the observer never reads scattered hard-coded values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.config.models import GovernanceConfig

#: Default rolling-window width in events (FK-93 §93.5).
DEFAULT_WINDOW_SIZE: int = 50
#: Default risk-score threshold (FK-93 §93.5).
DEFAULT_RISK_THRESHOLD: int = 30
#: Default adjudication cooldown in seconds (FK-93 §93.5).
DEFAULT_COOLDOWN_S: int = 300


def get_window_size(cfg: GovernanceConfig | None) -> int:
    """Return ``governance.window_size`` from config or the FK-93 §93.5 default.

    Args:
        cfg: Optional :class:`~agentkit.config.models.GovernanceConfig`.

    Returns:
        Rolling-window width (number of most-recent events to aggregate).
    """
    if cfg is not None:
        return cfg.window_size
    return DEFAULT_WINDOW_SIZE


def get_risk_threshold(cfg: GovernanceConfig | None) -> int:
    """Return ``governance.risk_threshold`` from config or the FK-93 §93.5 default.

    Args:
        cfg: Optional :class:`~agentkit.config.models.GovernanceConfig`.

    Returns:
        Risk-score threshold above which adjudication is triggered.
    """
    if cfg is not None:
        return cfg.risk_threshold
    return DEFAULT_RISK_THRESHOLD


def get_cooldown_s(cfg: GovernanceConfig | None) -> int:
    """Return ``governance.cooldown_s`` from config or the FK-93 §93.5 default.

    Args:
        cfg: Optional :class:`~agentkit.config.models.GovernanceConfig`.

    Returns:
        Cooldown in seconds between adjudications of the same signal type.
    """
    if cfg is not None:
        return cfg.cooldown_s
    return DEFAULT_COOLDOWN_S
