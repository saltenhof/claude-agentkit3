"""Run-ownership domain vocabulary (blood-type A: technology-free core).

This module holds the canonical, technology-free ownership vocabulary of the
session-ownership model (FK-17 §17.2c, FK-56 §56.8a,
``formal.operating-modes.entities``): the :data:`SessionId` semantic type, the
closed :class:`OwnershipStatus` / :class:`OwnershipAcquisition` enum spaces and
the invariant name/bound constants that the persistence layer enforces.

It is deliberately AT-free (no transactions, no SQL, no I/O): the constraint
*mechanics* for the ``at_most_one_active_ownership_per_story`` invariant live in
the ``state_backend`` repository/DDL layer (blood-type AT/T). Only the *meaning*
lives here.

Concept anchors:
    - FK-17 §17.2c (``OwnershipStatus`` / ``OwnershipAcquisition`` enum spaces),
      §17.3a.15 (``RunOwnershipRecord`` attribute contract, ``ownership_epoch``
      >= 1), §17.3a.16 (``binding_version`` >= 1).
    - FK-56 §56.7a (``binding_invalid`` reason as an attribute; the
      ``ownership_transferred`` revocation reason), §56.8a (partial-unique
      active invariant, epoch semantics).
    - ``formal.operating-modes.invariants.at_most_one_active_ownership_per_story``.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import NewType

__all__ = (
    "AT_MOST_ONE_ACTIVE_OWNERSHIP_PER_STORY",
    "BINDING_VERSION_SQL_CHECK",
    "INITIAL_OPERATION_EPOCH",
    "INITIAL_OWNERSHIP_EPOCH",
    "MIN_BINDING_VERSION",
    "MIN_INSTANCE_INCARNATION",
    "MIN_OPERATION_EPOCH",
    "MIN_OWNERSHIP_EPOCH",
    "MIN_QUEUE_POSITION",
    "OWNERSHIP_TRANSFERRED_REVOCATION_REASON",
    "BindingRevocationReason",
    "BindingStatus",
    "OwnershipAcquisition",
    "OwnershipStatus",
    "SessionId",
    "is_canonical_binding_version",
)

#: Semantic type for a client session identifier (FK-17 §17.2b: systemwide
#: unique, stable per session). Modelled as a ``NewType`` over ``str`` so the
#: ownership surface can name the concept without a runtime wrapper; existing
#: ``session_id: str`` fields stay wire-compatible.
SessionId = NewType("SessionId", str)


class OwnershipStatus(StrEnum):
    """Closed status space of a ``RunOwnershipRecord`` (FK-17 §17.2c).

    ``ACTIVE`` is the only admission-relevant status; every other value is an
    audit fact (FK-56 §56.8a,
    ``historical_ownership_records_are_never_admission_evidence``).

    ``TRANSFERRED`` is part of the canonical vocabulary but has **no writer** in
    the current normative strand: no path (takeover/disown/recovery) sets it,
    and any attempt to persist it is fail-closed rejected until a normative
    concretisation exists (AG3-137 scope §1). A run-continuing takeover is an
    in-place CAS on the SAME row (owner change, ``ownership_epoch + 1``, record
    stays ``ACTIVE``) and never sets ``TRANSFERRED``.
    """

    ACTIVE = "active"
    TRANSFERRED = "transferred"
    ENDED = "ended"
    RESET = "reset"
    SPLIT = "split"
    CLOSED = "closed"


class OwnershipAcquisition(StrEnum):
    """Closed acquisition-path space of a ``RunOwnershipRecord`` (FK-17 §17.2c)."""

    SETUP = "setup"
    TAKEOVER = "takeover"
    RECOVERY = "recovery"


class BindingStatus(StrEnum):
    """Closed status space of a ``SessionRunBinding`` (FK-56 §56.7a).

    A binding is ``ACTIVE`` or ``REVOKED``; the revocation *reason* is a
    separate machine-readable attribute (``binding_invalid`` is a mode, not a
    per-cause status).
    """

    ACTIVE = "active"
    REVOKED = "revoked"


class BindingRevocationReason(StrEnum):
    """Known machine-readable binding revocation reasons (FK-56 §56.7a).

    The reason is an attribute of a revoked binding, not a status per cause.
    ``OWNERSHIP_TRANSFERRED`` is the concept-named reason introduced with the
    ownership transfer (§56.13). The reason column stays an open ``TEXT`` at the
    schema level so downstream stories (AG3-142/148/149) may extend the
    vocabulary without a schema change; this enum documents the known values.
    """

    OWNERSHIP_TRANSFERRED = "ownership_transferred"


#: Enforced-by-persistence invariant name (``formal.operating-modes.invariants``).
AT_MOST_ONE_ACTIVE_OWNERSHIP_PER_STORY = "at_most_one_active_ownership_per_story"

#: The concept-named revocation reason string (FK-56 §56.7a).
OWNERSHIP_TRANSFERRED_REVOCATION_REASON = (
    BindingRevocationReason.OWNERSHIP_TRANSFERRED.value
)

#: ``ownership_epoch`` lower bound and the setup start value (FK-17 §17.3a.15:
#: ``>= 1``, begins with setup, monotone increasing).
MIN_OWNERSHIP_EPOCH = 1
INITIAL_OWNERSHIP_EPOCH = 1

#: ``binding_version`` lower bound (FK-17 §17.3a.16: ``>= 1``).
MIN_BINDING_VERSION = 1

#: Canonical ``binding_version`` value domain (FK-17 §17.3a.16): a base-10
#: integer ``>= 1`` with NO leading-zero ambiguity, NO sign, NO ``bind-``/
#: ``exit-`` correlation prefix and NO whitespace. The value stays a ``str`` at
#: the record/wire level (it flows verbatim into derived lock projections), but
#: its domain is a monotone positive integer, enforced at BOTH the record
#: boundary (:func:`is_canonical_binding_version`) and the persistence boundary
#: (:data:`BINDING_VERSION_SQL_CHECK`). The two encodings are kept deliberately
#: in lock-step (same accept/reject set); changing one requires changing the
#: other. Their *spelling* differs on purpose: the Python side uses ``\d`` under
#: :data:`re.ASCII` (so ``\d`` stays strictly ``[0-9]`` and never widens to
#: Unicode digits), whereas the Postgres ``CHECK`` keeps ``[0-9]`` because
#: Postgres ARE ``\d`` would broaden with locale.
_CANONICAL_BINDING_VERSION_RE = re.compile(r"[1-9]\d*", re.ASCII)

#: Postgres regex fragment mirroring :func:`is_canonical_binding_version` for the
#: schema ``CHECK`` constraint (fresh CREATE TABLE and existing-schema ALTER).
#: ``~`` is a partial match in Postgres, hence the explicit ``^``/``$`` anchors.
BINDING_VERSION_SQL_CHECK = "^[1-9][0-9]*$"


def is_canonical_binding_version(value: str) -> bool:
    """Return whether *value* is a canonical ``binding_version`` (FK-17 §17.3a.16).

    A canonical value is a base-10 integer ``>= 1`` in its shortest form: a
    leading non-zero digit followed by any digits. This rejects the empty
    string, whitespace, ``bind-<uuid>``/``exit-<id>`` correlation tokens, signs,
    decimals, ``0`` and leading-zero forms (``001``). ``re.fullmatch`` anchors
    the whole string (no ``$``-before-newline tolerance).

    Args:
        value: The candidate version token.

    Returns:
        ``True`` iff *value* is a canonical monotone positive integer string.
    """
    return _CANONICAL_BINDING_VERSION_RE.fullmatch(value) is not None

#: ``instance_incarnation`` lower bound (FK-91 §91.1a rule 16: monotone boot
#: incarnation counter, first boot is 1).
MIN_INSTANCE_INCARNATION = 1

#: ``queue_position`` lower bound for an object-mutation claim (0-based FIFO).
MIN_QUEUE_POSITION = 0

#: ``operation_epoch`` lower bound (AG3-138, ``formal.state-storage.invariants``
#: ``operation_finalize_requires_cas_on_operation_epoch``): the fencing token
#: stamped on a claim at acquisition time and bumped ONLY by an explicit
#: ``admin_abort_inflight_operation``/startup-reconciliation finalize -- never by
#: wall clock. The first (and, absent an abort, only) epoch of a claim's lifetime
#: is 1 (AG3-139: there is no CAS takeover of a foreign claim anymore -- a claim's
#: epoch changes ONLY via an explicit admin-abort/startup-reconciliation finalize).
MIN_OPERATION_EPOCH = 1
INITIAL_OPERATION_EPOCH = 1
