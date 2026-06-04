"""Installer registration entities (FK-50 §50.3 CP 7 / §50.4).

This module owns the typed registration shape persisted by Installer
Checkpoint 7 (``project_registry``) and the minimal ``CheckpointResult`` type
skeleton from FK-50 §50.4.

Scope (AG3-039 §2.1.2/§2.1.5):
- :class:`ProjectRegistration` — the frozen, ``extra=forbid`` registration
  record (the in-memory mirror of the ``project_registry`` row).
- :class:`RuntimeProfile` — the ``core``/``are`` profile wire enum.
- :class:`CheckpointStatus` + :class:`CheckpointResult` — the FK-50 §50.4 type
  skeleton. The full 12-checkpoint engine is OUT of scope (story §2.2); only
  CP 7 produces a ``CheckpointResult`` for now.

Field set follows the autoritative story §2.1.1/§2.1.2 (table columns 1:1 to
the model). This deliberately uses concrete ``config_version`` /
``registered_at`` / timestamp columns rather than the higher-level attribute
names in ``formal.installer.entities`` (``gh_owner``/``registration_status``/
``registered_bundle_version``); the story is the autoritative implementation
spec and is self-consistent (table <-> model <-> repository).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class RuntimeProfile(StrEnum):
    """Runtime profile of a registered project (FK-50 §50.3 CP 6/CP 7).

    Mirrors the ``project_registry.runtime_profile`` CHECK constraint.
    """

    CORE = "core"
    ARE = "are"


class CheckpointStatus(StrEnum):
    """Outcome status of a single installer checkpoint (FK-50 §50.4)."""

    PASS = "pass"
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


class ProjectRegistration(BaseModel):
    """Canonical project registration record (FK-50 §50.3 CP 7).

    The in-memory mirror of a ``project_registry`` row. Frozen + ``extra=forbid``
    so a registration cannot be mutated in place or silently carry unknown
    fields (FAIL-CLOSED).

    Attributes:
        project_key: Owning project key (primary key).
        project_root: Absolute filesystem root of the project (UNIQUE).
        github_owner: GitHub owner/org of the project's repo.
        github_repo: GitHub repository name.
        runtime_profile: The resolved :class:`RuntimeProfile` (``core``/``are``).
        config_version: The project config (``project.yaml``) schema/content
            version recorded at registration time.
        config_digest: SHA-256 over the canonicalised ``project.yaml`` content;
            drives the idempotency / upgrade decision in CP 7.
        registered_at: Timestamp of the initial registration.
        last_verified_at: Timestamp of the last ``verify-project`` (``None``
            until first verified).
        last_upgraded_at: Timestamp of the last config-digest upgrade (``None``
            until first upgraded).
    """

    project_key: str
    project_root: Path
    github_owner: str
    github_repo: str
    runtime_profile: RuntimeProfile
    config_version: str
    config_digest: str
    registered_at: datetime
    last_verified_at: datetime | None = None
    last_upgraded_at: datetime | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _validate_github_coordinates(self) -> Self:
        """Enforce the SSOT GitHub naming rules on the persisted coordinates.

        Defense-in-depth / data SSOT (AG3-039 R7 ERROR-2): the installer CP 7
        port validates ``github_owner``/``github_repo`` BEFORE constructing a
        registration, so in the normal flow this validator never fires. It is
        the hard floor that makes it IMPOSSIBLE to construct — and therefore to
        persist — a ``ProjectRegistration`` carrying a malformed GitHub
        coordinate, regardless of the code path (a direct
        ``install_agentkit(InstallConfig(...))`` call, a future caller, or a
        test). The single validation truth is
        :func:`validate_github_coordinate`; this validator does NOT introduce a
        second, divergent rule set (FAIL-CLOSED, FIX-THE-MODEL).

        Raises:
            ValueError: When ``(github_owner, github_repo)`` is not a
                well-formed GitHub owner/repo pair.
        """
        from agentkit.installer.github_coordinates import validate_github_coordinate

        if validate_github_coordinate(self.github_owner, self.github_repo) is None:
            raise ValueError(
                f"ProjectRegistration github_owner={self.github_owner!r} / "
                f"github_repo={self.github_repo!r} is not a well-formed GitHub "
                "owner/repo (owner: 1-39 alphanumerics with single internal "
                "hyphens; repo: 1-100 chars of [A-Za-z0-9._-], not '.'/'..' / "
                "leading-dot). A malformed coordinate must never be persisted "
                "(FAIL-CLOSED)."
            )
        return self


class CheckpointResult(BaseModel):
    """Result of a single installer checkpoint (FK-50 §50.4).

    Type skeleton only — the full checkpoint engine is OUT of scope (story
    §2.2). CP 7 emits one of these per install.

    Attributes:
        checkpoint: Stable checkpoint id (e.g. ``"cp_07_state_backend_registration"``).
        status: The :class:`CheckpointStatus` outcome.
        detail: Human-readable description (``None`` when no detail applies).
        reason: Machine-readable, stable reason code for a SKIP/FAIL outcome
            (FK-50 §50.4). ``None`` for non-actionable outcomes
            (PASS/CREATED/UPDATED). Unlike ``detail`` (free-form prose), ``reason``
            is a short, switchable token (e.g. ``"config_digest_unchanged"``,
            ``"missing_github_coordinates"``) so callers can branch on it without
            string-matching prose.
        duration_ms: Wall-clock duration of the checkpoint in milliseconds.
    """

    checkpoint: str
    status: CheckpointStatus
    detail: str | None = None
    reason: str | None = None
    duration_ms: int

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _require_reason_for_skip_or_fail(self) -> Self:
        """Enforce FK-50 §50.4: SKIPPED/FAILED MUST carry a machine-readable reason.

        FK-50 §50.4 requires a stable, machine-readable ``reason`` for every
        actionable (SKIPPED/FAILED) checkpoint outcome so callers can branch on
        the cause without parsing free-form ``detail`` prose. A SKIP/FAIL with an
        absent or blank ``reason`` is a fail-open hole (an unactionable outcome)
        and is rejected. PASS/CREATED/UPDATED are non-actionable and need no
        ``reason``.

        Raises:
            ValueError: When ``status`` is SKIPPED or FAILED and ``reason`` is
                ``None`` or whitespace-only.
        """
        if self.status in {CheckpointStatus.SKIPPED, CheckpointStatus.FAILED} and (
            self.reason is None or not self.reason.strip()
        ):
            raise ValueError(
                f"CheckpointResult with status={self.status.value!r} requires a "
                "non-empty 'reason' (FK-50 §50.4: SKIPPED/FAILED outcomes must "
                "carry a machine-readable reason)."
            )
        return self


#: Stable checkpoint id for the FK-50 §50.3 CP 7 State-Backend registration.
CP7_STATE_BACKEND_REGISTRATION = "cp_07_state_backend_registration"

#: Machine-readable :attr:`CheckpointResult.reason` codes (FK-50 §50.4). Stable
#: tokens so callers branch on them without parsing the free-form ``detail``.
#: CP 7 idempotent re-run: existing registration, identical ``config_digest``.
REASON_CONFIG_DIGEST_UNCHANGED = "config_digest_unchanged"
#: CP 7 fail-closed: mandatory GitHub coordinates absent on the install config.
REASON_MISSING_GITHUB_COORDINATES = "missing_github_coordinates"
#: CP 7 fail-closed: GitHub coordinates PRESENT but malformed (not a well-formed
#: GitHub owner/repo per :func:`validate_github_coordinate`). Distinct from
#: ``missing`` so callers can tell "absent" from "present-but-invalid".
REASON_INVALID_GITHUB_COORDINATES = "invalid_github_coordinates"


__all__ = [
    "CP7_STATE_BACKEND_REGISTRATION",
    "REASON_CONFIG_DIGEST_UNCHANGED",
    "REASON_INVALID_GITHUB_COORDINATES",
    "REASON_MISSING_GITHUB_COORDINATES",
    "CheckpointResult",
    "CheckpointStatus",
    "ProjectRegistration",
    "RuntimeProfile",
]
