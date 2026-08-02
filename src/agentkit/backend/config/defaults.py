"""Default values and constants for AgentKit configuration.

These constants define the canonical defaults used when configuration
values are not explicitly provided in a project's ``project.yaml``.
"""

from __future__ import annotations

DEFAULT_CONFIG_DIR: str = ".agentkit/config"
"""Relative path from project root to the AgentKit configuration directory."""

DEFAULT_CONFIG_FILE: str = "project.yaml"
"""Name of the main project configuration file."""

DEFAULT_STORY_TYPES: tuple[str, ...] = (
    "implementation",
    "bugfix",
    "concept",
    "research",
)
"""Supported story types in the 4-phase pipeline."""

DEFAULT_MAX_FEEDBACK_ROUNDS: int = 3
"""Maximum number of QA feedback rounds before escalation."""

DEFAULT_MAX_REMEDIATION_ROUNDS: int = 2
"""Maximum number of remediation attempts per feedback round."""

DEFAULT_VERIFY_LAYERS: tuple[str, ...] = (
    "structural",
    "semantic",
    "adversarial",
    "policy",
)
"""The four QA layers executed during the implementation QA-subflow."""

# ---------------------------------------------------------------------------
# Core listener ports (FK-10 §10.7.2 port registry) — SINGLE OWNER
# ---------------------------------------------------------------------------
# These three constants are the ONLY place an AK3 Core port literal exists.
# Every consumer (``cli.serve`` profile defaults, the installer-written
# ``control-plane.json``, the SPA dev proxy) derives its value from here. The
# 2026-08-02 incident (a stale ``9080`` survived in the installer while the
# listener had long moved to ``9702``) was caused by exactly that literal being
# repeated per consumer; a second copy must never be introduced.

CORE_UI_PORT: int = 9700
"""SPA frontend port (``agentkit ui``, FK-10 §10.7.2)."""

CORE_UI_BFF_PORT: int = 9701
"""Backend UI-BFF listener port (``agentkit serve --ui-bff``, FK-10 §10.7.2)."""

CORE_PROJECT_API_PORT: int = 9702
"""Backend Project-API listener port (``agentkit serve --project-api``)."""

CORE_LOOPBACK_HOST: str = "127.0.0.1"
"""Loopback bind/dial host: AK3 Core is a localhost deployment (FK-15)."""

DEFAULT_CONTROL_PLANE_BASE_URL: str = f"https://{CORE_LOOPBACK_HOST}:{CORE_PROJECT_API_PORT}"
"""Default Core base URL written into a project's ``control-plane.json``.

DERIVED, never a hand-written literal: the Project-API (FK-10 §10.7.2) is the
mandatory Core endpoint for hooks/edge/CLI, and AK3 Core runs loopback-only
(FK-15). An operator whose Core listens elsewhere overrides it explicitly via
``--control-plane-base-url``.
"""
