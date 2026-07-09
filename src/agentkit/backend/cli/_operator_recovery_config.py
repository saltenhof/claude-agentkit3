"""Project-key and time-window resolution for operator recovery commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from datetime import datetime


_PROJECT_KEY_OVERRIDE_HELP = "Project key override"
_CONFIG_PATH_OVERRIDE_HELP = "Config path override"


class _ConfigResolutionError(Exception):
    """Raised when ``--config`` is provided but fails to yield a project_key."""


def _resolve_project_key(args: argparse.Namespace) -> str | None:
    """Resolve ``project_key`` from CLI args with config and env fallback.

    Resolution order (story §2.1.1):

    1. ``--project`` flag (explicit override).
    2. ``--config`` path: load :class:`~agentkit.backend.config.models.ProjectConfig`
       and read ``project_key``.  When ``--config`` IS provided but the config
       cannot be loaded or yields no key, raises :class:`_ConfigResolutionError`
       (fail-closed — do NOT silently fall through to the env var).
    3. ``AGENTKIT_PROJECT_KEY`` environment variable (only reached when
       ``--config`` was NOT provided).

    Args:
        args: Parsed argparse namespace (may have ``project`` and/or ``config``).

    Returns:
        The resolved project key string, or ``None`` if none found.

    Raises:
        _ConfigResolutionError: When ``--config`` is provided but missing,
            unreadable, or yields no ``project_key``.
    """
    explicit = getattr(args, "project", None)
    if explicit:
        return str(explicit)

    config_path_raw = getattr(args, "config", None)
    if config_path_raw is not None:
        # --config was explicitly provided (even if blank/empty): fail-closed.
        # An empty string is an invalid path — do NOT fall through to the env
        # var.  Only when --config is completely absent (None, the argparse
        # default) may resolution continue to AGENTKIT_PROJECT_KEY.
        stripped = config_path_raw.strip() if isinstance(config_path_raw, str) else ""
        if not stripped:
            raise _ConfigResolutionError(
                "--config was provided but the value is empty or blank. Pass a valid config file path or omit --config entirely."
            )
        try:
            from agentkit.backend.config.loader import load_project_config

            cfg = load_project_config(Path(stripped))
            key = getattr(cfg, "project_key", None)
            if key:
                return str(key)
            raise _ConfigResolutionError(f"Config at {stripped!r} loaded successfully but contains no project_key.")
        except _ConfigResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _ConfigResolutionError(f"Failed to load config from {stripped!r}: {exc}") from exc

    env_key = os.environ.get("AGENTKIT_PROJECT_KEY", "").strip()
    return env_key or None


def _parse_since_cutoff(since_raw: str) -> datetime:
    """Parse a ``--since`` value into a timezone-aware :class:`datetime`.

    Supported forms (MAJOR 5 fix):

    - Window: ``{N}d``, ``{N}h``, ``{N}m`` (e.g. ``7d``, ``24h``, ``30m``).
      Resolved as ``now(UTC) - timedelta``.
    - ISO-8601 timestamp (with or without timezone).  When no timezone is
      given the value is treated as UTC (tz-aware comparison requires a
      timezone).

    Args:
        since_raw: Raw ``--since`` string from the CLI.

    Returns:
        A timezone-aware :class:`datetime` representing the cutoff.

    Raises:
        ValueError: When the value cannot be parsed into either form.
    """
    import re
    from datetime import UTC, datetime, timedelta

    # Window form: Nd / Nh / Nm
    window_match = re.fullmatch(r"(\d+)([dhm])", since_raw.strip())
    if window_match:
        qty = int(window_match.group(1))
        unit = window_match.group(2)
        if unit == "d":
            delta = timedelta(days=qty)
        elif unit == "h":
            delta = timedelta(hours=qty)
        else:
            delta = timedelta(minutes=qty)
        return datetime.now(UTC) - delta

    # ISO-8601 form: try fromisoformat (Python 3.11+ handles Z suffix too)
    try:
        dt = datetime.fromisoformat(since_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass

    raise ValueError(
        f"Cannot parse --since {since_raw!r}: expected a window like 7d/24h/30m "
        "or an ISO-8601 timestamp (e.g. 2025-01-01T00:00:00Z)."
    )


__all__ = [
    "_CONFIG_PATH_OVERRIDE_HELP",
    "_ConfigResolutionError",
    "_PROJECT_KEY_OVERRIDE_HELP",
    "_parse_since_cutoff",
    "_resolve_project_key",
]
