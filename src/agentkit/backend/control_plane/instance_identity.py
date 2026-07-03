"""Backend instance identity resolution (AG3-138, IMPL-003/IMPL-004).

FK-91 §91.1a rule 16 / FK-10 §10.5.4: every in-flight claim carries a stable
``backend_instance_id`` plus a monotone boot incarnation. This module resolves
THIS boot's identity exactly once, deterministically (no wall-clock input to
the decision, only a stamped instant): the first boot ever for an installation
mints a fresh id at incarnation 1; every later boot keeps the SAME id (stable
across restarts, AC3) and increments the incarnation by exactly 1. The
atomicity of the underlying create-or-increment (serialized against a
concurrent boot of the same database) lives in the ``state_backend`` store
layer (:func:`~agentkit.backend.state_backend.store.boot_backend_instance_identity_global`);
this module is the thin, injectable-seam call site that the pre-serve startup
hook (``control_plane_http.app``) invokes exactly once per process boot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord
    from agentkit.backend.control_plane.repository import BackendInstanceIdentityRepository

__all__ = ("resolve_backend_instance_identity",)


def _default_candidate_id() -> str:
    """Mint a fresh candidate id for a genuine first boot (uuid4 hex)."""
    return uuid.uuid4().hex


def _default_now() -> datetime:
    return datetime.now(UTC)


def resolve_backend_instance_identity(
    repo: BackendInstanceIdentityRepository,
    *,
    candidate_id_factory: Callable[[], str] = _default_candidate_id,
    now_fn: Callable[[], datetime] = _default_now,
) -> BackendInstanceIdentityRecord:
    """Resolve THIS boot's backend instance identity (create-or-increment).

    Args:
        repo: The instance-identity persistence port. ``boot_identity`` performs
            the atomic (advisory-lock-guarded) create-or-increment at the store.
        candidate_id_factory: Mints the candidate id used ONLY on a genuine
            first boot (no installation identity exists yet); ignored when one
            already exists. Injectable for deterministic tests.
        now_fn: Resolves the instant to stamp on the identity row. Injectable
            for deterministic tests -- the VALUE stamped is not itself a
            decision input (the create-vs-increment branch and the monotone
            increment are driven entirely by the stored row's presence/absence
            and its current incarnation, never by wall-clock comparison).

    Returns:
        The resolved :class:`BackendInstanceIdentityRecord` for THIS boot: a
        stable ``backend_instance_id`` and a freshly incremented (or initial)
        ``instance_incarnation``.
    """
    return repo.boot_identity(candidate_id_factory(), now_fn())
