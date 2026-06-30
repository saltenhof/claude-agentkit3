"""Level-2 hybrid update driver (FK-10 §10.2.8, AG3-122).

The update model is HYBRID: the Core announces ``min``/``recommended``/``blocked``
versions over ``/v1`` (the compat window, FK-91 §91.1a / AG3-121); the dev machine
PULLS and activates locally via ``agentkit update`` (no server push of
executables). This module is the PURE decision driver: given the locally installed
agent-runtime version and the compat window read from the Core, it classifies the
update fail-closed.

FAIL-CLOSED reaction matrix (FK-10 §10.2.8):

* **BLOCKED (non-PASS exit):** the local runtime is below ``min`` or appears in
  ``blocked`` — "a hook that cannot prove its compatibility never returns PASS".
* **WARNING (proceed):** the local runtime is inside the window but below
  ``recommended``.
* **PASS:** the local runtime is ``>= recommended``.

Every non-blocked outcome carries the §10.2.8 re-install hint: running harness
sessions must be restarted after a package/bundle update (two-stage skill load,
FK-43). The actual package/bundle pull is the dev's own action (the shared
``agentkit`` package is never self-mutated from inside a running process); this
driver decides and instructs, it does not execute ``pip install``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

#: §10.2.8 re-install obligation surfaced on every non-blocked update outcome.
REINSTALL_HINT = (
    "Re-install obligation (FK-10 §10.2.8): restart running harness sessions "
    "after a package/bundle update so the two-stage skill load (FK-43) re-binds "
    "the new bundle. No server push of executables — pull and activate locally."
)


class UpdateStatus(Enum):
    """Typed fail-closed update classification (FK-10 §10.2.8)."""

    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"


class UpdateCompatError(Exception):
    """Raised when the compat window read from the Core is malformed (fail-closed)."""


@dataclass(frozen=True)
class UpdateDecision:
    """Result of evaluating the local runtime against the Core compat window.

    Attributes:
        status: The fail-closed classification.
        local_version: The locally installed agent-runtime version.
        min_version: The lowest still-supported version announced by the Core.
        recommended_version: The recommended version announced by the Core.
        blocked: The explicitly blocked versions announced by the Core.
        reason: Human-readable explanation of the classification.
        reinstall_hint: The §10.2.8 re-install hint (empty when blocked).
    """

    status: UpdateStatus
    local_version: str
    min_version: str
    recommended_version: str
    blocked: tuple[str, ...]
    reason: str
    reinstall_hint: str

    @property
    def is_pass(self) -> bool:
        """Return whether the local runtime is compatible (not blocked)."""
        return self.status is not UpdateStatus.BLOCKED


def evaluate_update(
    local_version: str, compat_window: Mapping[str, object]
) -> UpdateDecision:
    """Classify a local runtime against the Core ``/v1/compat`` window (fail-closed).

    Args:
        local_version: The locally installed agent-runtime package version.
        compat_window: The decoded ``GET /v1/compat`` body (FK-91 §91.1a). The
            ``agent_runtime`` axis carries ``min``/``recommended``/``blocked``.

    Returns:
        The :class:`UpdateDecision`.

    Raises:
        UpdateCompatError: When the window is structurally invalid or carries an
            unparsable version (fail-closed; an unreadable window is never
            treated as PASS).
    """
    runtime = _require_axis(compat_window, "agent_runtime")
    min_version = _require_str(runtime, "min")
    recommended = _require_str(runtime, "recommended")
    blocked = _require_blocked(runtime)

    local = _parse_version(local_version)
    if local_version in blocked:
        return _blocked(
            local_version,
            min_version,
            recommended,
            blocked,
            f"agent-runtime {local_version!r} is in the Core's blocked set",
        )
    if _compare(local, _parse_version(min_version)) < 0:
        return _blocked(
            local_version,
            min_version,
            recommended,
            blocked,
            f"agent-runtime {local_version!r} is below the minimum supported "
            f"version {min_version!r}",
        )
    if _compare(local, _parse_version(recommended)) < 0:
        return UpdateDecision(
            status=UpdateStatus.WARNING,
            local_version=local_version,
            min_version=min_version,
            recommended_version=recommended,
            blocked=blocked,
            reason=(
                f"agent-runtime {local_version!r} is inside the window but below "
                f"the recommended version {recommended!r}; update advised"
            ),
            reinstall_hint=REINSTALL_HINT,
        )
    return UpdateDecision(
        status=UpdateStatus.PASS,
        local_version=local_version,
        min_version=min_version,
        recommended_version=recommended,
        blocked=blocked,
        reason=f"agent-runtime {local_version!r} is compatible (>= {recommended!r})",
        reinstall_hint=REINSTALL_HINT,
    )


def _blocked(
    local_version: str,
    min_version: str,
    recommended: str,
    blocked: tuple[str, ...],
    reason: str,
) -> UpdateDecision:
    """Build a BLOCKED decision (no re-install hint — the update cannot proceed)."""
    return UpdateDecision(
        status=UpdateStatus.BLOCKED,
        local_version=local_version,
        min_version=min_version,
        recommended_version=recommended,
        blocked=blocked,
        reason=reason,
        reinstall_hint="",
    )


def _require_axis(window: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Return the ``key`` version axis sub-mapping, fail-closed."""
    axis = window.get(key)
    if not isinstance(axis, Mapping):
        msg = f"compat window is missing a valid {key!r} axis (got {type(axis).__name__})"
        raise UpdateCompatError(msg)
    return axis


def _require_str(axis: Mapping[str, object], key: str) -> str:
    """Return a non-empty string field of a version axis, fail-closed."""
    value = axis.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"compat window axis is missing a valid {key!r} string"
        raise UpdateCompatError(msg)
    return value


def _require_blocked(axis: Mapping[str, object]) -> tuple[str, ...]:
    """Return the ``blocked`` version tuple of a version axis, fail-closed."""
    raw = axis.get("blocked", ())
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        msg = "compat window axis 'blocked' must be a list of version strings"
        raise UpdateCompatError(msg)
    blocked: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            msg = "compat window axis 'blocked' must contain only version strings"
            raise UpdateCompatError(msg)
        blocked.append(item)
    return tuple(blocked)


def _parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted numeric version into a comparable tuple (fail-closed)."""
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        msg = f"version {value!r} is not a dotted numeric version"
        raise UpdateCompatError(msg) from exc


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Compare two zero-padded version tuples, returning -1/0/+1."""
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


__all__ = [
    "REINSTALL_HINT",
    "UpdateCompatError",
    "UpdateDecision",
    "UpdateStatus",
    "evaluate_update",
]
