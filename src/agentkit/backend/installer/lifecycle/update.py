"""Level-2 hybrid update driver (FK-10 §10.2.8, AG3-122).

The update model is HYBRID: the Core announces ``min``/``recommended``/``blocked``
versions over ``/v1`` (the compat window, FK-91 §91.1a / AG3-121); the dev machine
PULLS and activates locally via ``agentkit update`` (no server push of
executables). This module is the PURE decision driver: given the locally installed
agent-runtime version and the compat window read from the Core, it classifies the
update fail-closed.

FAIL-CLOSED reaction matrix (FK-10 §10.2.8). This MIRRORS the server-side
version handshake (``control_plane_http/version_handshake.py``,
``_classify_runtime``) so ``agentkit update`` and the Core agree: a runtime the
server would 426 must never be reported PASS locally.

* **BLOCKED (non-PASS exit):** the local runtime is below ``min``, above ``max``
  or appears in ``blocked`` — "a hook that cannot prove its compatibility never
  returns PASS".
* **WARNING (proceed):** the local runtime is inside the ``[min, max]`` window
  but below ``recommended``.
* **PASS:** the local runtime is ``>= recommended`` (and ``<= max``).

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
REINSTALL_HINT = "Re-install obligation (FK-10 §10.2.8): restart running harness sessions "
REINSTALL_HINT += "after a package/bundle update so the two-stage skill load (FK-43) re-binds "
REINSTALL_HINT += "the new bundle. No server push of executables — pull and activate locally."


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
        max_version: The highest announced version of the current window.
        recommended_version: The recommended version announced by the Core.
        blocked: The explicitly blocked versions announced by the Core.
        reason: Human-readable explanation of the classification.
        reinstall_hint: The §10.2.8 re-install hint (empty when blocked).
    """

    status: UpdateStatus
    local_version: str
    min_version: str
    max_version: str
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
            ``agent_runtime`` axis carries ``min``/``max``/``recommended``/
            ``blocked``; the ``wire`` axis carries the same shape.

    Returns:
        The :class:`UpdateDecision`.

    Raises:
        UpdateCompatError: When the window is structurally invalid or carries an
            unparsable version (fail-closed; an unreadable window is never
            treated as PASS). The ``agent_runtime`` AND ``wire`` axes are both
            required and structurally validated (the server announces both;
            FK-91 §91.1a / ``version_handshake.CompatWindow``).
    """
    runtime = _require_axis(compat_window, "agent_runtime")
    min_version = _require_str(runtime, "min")
    max_version = _require_str(runtime, "max")
    recommended = _require_str(runtime, "recommended")
    blocked = _require_blocked(runtime)
    # The wire axis is a handshake participant the server announces alongside the
    # runtime axis. ``update`` does not classify against it, but a malformed wire
    # axis means an untrustworthy window — validate it fail-closed rather than
    # ignore it (do NOT add a bundle axis; bundle is not part of /v1/compat).
    _require_axis_structure(compat_window, "wire")

    local = _parse_version(local_version)
    if _is_blocked_version(local_version, local, blocked):
        return _blocked(
            local_version,
            min_version,
            max_version,
            recommended,
            blocked,
            f"agent-runtime {local_version!r} is in the Core's blocked set",
        )
    if _compare(local, _parse_version(min_version)) < 0:
        return _blocked(
            local_version,
            min_version,
            max_version,
            recommended,
            blocked,
            f"agent-runtime {local_version!r} is below the minimum supported "
            f"version {min_version!r}",
        )
    if _compare(local, _parse_version(max_version)) > 0:
        # Mirror the server handshake (version_handshake._classify_runtime): a
        # runtime ABOVE max is fail-closed (the server 426s it), so update must
        # not report PASS for the same runtime.
        return _blocked(
            local_version,
            min_version,
            max_version,
            recommended,
            blocked,
            f"agent-runtime {local_version!r} is above the maximum supported "
            f"version {max_version!r}",
        )
    if _compare(local, _parse_version(recommended)) < 0:
        reason = f"agent-runtime {local_version!r} is inside the window but below "
        reason += f"the recommended version {recommended!r}; update advised"
        return UpdateDecision(
            status=UpdateStatus.WARNING,
            local_version=local_version,
            min_version=min_version,
            max_version=max_version,
            recommended_version=recommended,
            blocked=blocked,
            reason=reason,
            reinstall_hint=REINSTALL_HINT,
        )
    return UpdateDecision(
        status=UpdateStatus.PASS,
        local_version=local_version,
        min_version=min_version,
        max_version=max_version,
        recommended_version=recommended,
        blocked=blocked,
        reason=f"agent-runtime {local_version!r} is compatible (>= {recommended!r})",
        reinstall_hint=REINSTALL_HINT,
    )


def _blocked(
    local_version: str,
    min_version: str,
    max_version: str,
    recommended: str,
    blocked: tuple[str, ...],
    reason: str,
) -> UpdateDecision:
    """Build a BLOCKED decision (no re-install hint — the update cannot proceed)."""
    return UpdateDecision(
        status=UpdateStatus.BLOCKED,
        local_version=local_version,
        min_version=min_version,
        max_version=max_version,
        recommended_version=recommended,
        blocked=blocked,
        reason=reason,
        reinstall_hint="",
    )


def _is_blocked_version(
    local_version: str, local: tuple[int, ...], blocked: tuple[str, ...]
) -> bool:
    """Return whether the local runtime matches a blocked version (fail-closed).

    The blocked check is normalized through :func:`_parse_version` exactly like the
    ``min``/``recommended`` comparisons, so a semantically-equal version in a
    different notation does NOT slip past (``"1.2"`` is blocked by a ``"1.2.0"``
    entry and vice versa). A blocked entry matches when it is byte-for-byte equal to
    ``local_version`` OR when it parses to the same numeric version. A malformed
    (unparsable) blocked entry never crashes the comparison: it can still match by
    exact string, otherwise it is skipped safely.

    Args:
        local_version: The locally installed agent-runtime version (raw string).
        local: The parsed numeric form of ``local_version``.
        blocked: The blocked version strings announced by the Core.

    Returns:
        Whether ``local_version`` is blocked.
    """
    for entry in blocked:
        if entry == local_version:
            return True
        try:
            parsed = _parse_version(entry)
        except UpdateCompatError:
            # A malformed blocked entry cannot be compared numerically; the exact
            # string check above already ran, so skip it without crashing.
            continue
        if _compare(local, parsed) == 0:
            return True
    return False


def _require_axis(window: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Return the ``key`` version axis sub-mapping, fail-closed."""
    axis = window.get(key)
    if not isinstance(axis, Mapping):
        msg = f"compat window is missing a valid {key!r} axis (got {type(axis).__name__})"
        raise UpdateCompatError(msg)
    return axis


def _require_axis_structure(window: Mapping[str, object], key: str) -> None:
    """Structurally validate a version axis fail-closed without classifying it.

    Used for the ``wire`` axis: the server announces it (``CompatWindow.wire``),
    so a window missing it or carrying an unparsable ``min``/``max``/
    ``recommended`` is malformed and must fail closed — an untrustworthy window is
    never silently accepted (FK-91 §91.1a). ``blocked`` must be a well-formed list.
    """
    axis = _require_axis(window, key)
    _parse_version(_require_str(axis, "min"))
    _parse_version(_require_str(axis, "max"))
    _parse_version(_require_str(axis, "recommended"))
    _require_blocked(axis)


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
