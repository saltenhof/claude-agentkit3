"""Config digest helper shared by the upgrade footprint and scenario decision.

The customization detection (FK-51 §51.8) and the §51.3 scenario decision both
need the canonical digest of the on-disk ``project.yaml`` to compare against the
registered ``config_digest``. The canonicalisation MUST match
``installer.runner._canonical_config_digest`` (the CP 7 idempotency key) so the
"digest == file hash" decision (FK-51 §51.3.1/§51.3.2) is consistent with the
registration the installer wrote — no second, divergent digest truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from agentkit.exceptions import ConfigError

if TYPE_CHECKING:
    from pathlib import Path


def config_file_digest(config_path: Path) -> str:
    """Return the canonical ``config_digest`` of the on-disk ``project.yaml``.

    Reads the YAML mapping and feeds it to the SAME canonical digest function the
    installer's CP 7 uses (``_canonical_config_digest``), so the resulting digest
    is comparable to ``ProjectRegistration.config_digest`` (FK-51 §51.3 / §51.8).

    Args:
        config_path: Path to the project's ``project.yaml``.

    Returns:
        The canonical SHA-256 digest of the config mapping.

    Raises:
        ConfigError: When the file is missing, not valid YAML, or not a mapping.
    """
    from agentkit.installer.runner import _canonical_config_digest

    if not config_path.is_file():
        raise ConfigError(
            f"Config file not found for digest: {config_path}",
            detail={"config_path": str(config_path)},
        )
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid YAML in config file: {config_path}",
            detail={"config_path": str(config_path), "error": str(exc)},
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigError(
            f"Config file must be a YAML mapping: {config_path}",
            detail={"config_path": str(config_path)},
        )
    return _canonical_config_digest(dict(loaded))


__all__ = ["config_file_digest"]
