"""Dev-local SonarQube quality-gate profile check (FK-50 CP 10d).

The CP 10d preconditions fall into two halves that run on two different
machines. The server-side probes -- reachability, ``min_version``, token role,
branch plugin -- are the core's work: it is the core that reaches SonarQube
(FK-33). The check in this module is the other half: it asks whether a file
exists under the project root, and the project root lives on the developer
machine. The core has no such disk, so this decision is taken locally and
never travels (FK-01 section 1.2.3).

The module holds no core import on purpose. It answers with a plain detail
string rather than a ``SonarPreflightResult``, because that result type is
core-owned vocabulary and importing it back would reintroduce exactly the
distribution crossing this split removes (AG3-242).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: Machine reason reported when the configured profile artifact is absent.
DEFAULT_PROFILE_MISSING = "default_profile_missing"


def missing_default_profile(repo_root: Path, default_profile: str) -> str | None:
    """Return the failing detail when the dev-local profile artifact is absent.

    Args:
        repo_root: The project root on the developer machine.
        default_profile: The configured ``quality_gate.default_profile`` path,
            relative to ``repo_root``.

    Returns:
        ``None`` when the artifact is present, otherwise the evidence detail
        naming the resolved path that was expected and not found.
    """
    profile_path = repo_root / default_profile
    if profile_path.is_file():
        return None
    return f"default quality-gate profile not found: {profile_path}"


__all__ = ["DEFAULT_PROFILE_MISSING", "missing_default_profile"]
