"""Runtime admission dependency wiring and identity guards."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    EdgeCommandRepository,
    ObjectMutationClaimRepository,
)

from ._di import (
    _default_di_execution_contract_digest_reader,
    _default_di_instance_identity,
    _default_di_object_claim_repository,
    _require_postgres_control_plane_backend,
    _resolve_edge_command_repository,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.dispatch import PhaseDispatcher
    from agentkit.backend.control_plane.execution_contract_assembly import (
        ExecutionContractDigestOutcome,
    )
    from agentkit.backend.control_plane.models import (
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord
    from agentkit.backend.state_backend.store.freeze_repository import (
        FreezeRepository,
        LocalFreezeJsonExport,
    )

logger = logging.getLogger(__name__)


class _AdmissionIdentityMixin:
    """DI, repository, and backend identity responsibilities for runtime admission."""

    def __init__(
        self,
        *,
        repository: ControlPlaneRuntimeRepository | None = None,
        object_claim_repository: ObjectMutationClaimRepository | None = None,
        edge_command_repository: EdgeCommandRepository | None = None,
        phase_dispatcher: PhaseDispatcher | None = None,
        now_fn: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        instance_identity: BackendInstanceIdentityRecord | None = None,
        execution_contract_digest_reader: (Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome] | None) = None,
        push_barrier_evidence: PushBarrierEvidencePort | None = None,
        push_barrier_evidence_factory: Callable[[], PushBarrierEvidencePort] | None = None,
        freeze_repository: FreezeRepository | None = None,
        local_freeze_export: LocalFreezeJsonExport | None = None,
    ) -> None:
        #: ERROR-3 fix (#3): whether this service uses the PRODUCTIVE default
        #: control-plane store (Postgres-only by design). When ``True`` every
        #: control-plane store entrypoint asserts the Postgres backend ONCE, early
        #: and CLEARLY (see :meth:`_require_postgres_backend_on_first_use`), so a
        #: SQLite/other backend fails fast with an explicit error instead of an
        #: opaque ``RuntimeError`` deep inside ``start_phase`` (the atomic claim).
        #: A DI-injected repository (tests / alternative wiring) owns its own
        #: backend and is exempt.
        self._uses_default_store = repository is None
        self._backend_checked = False
        self._repo = repository or ControlPlaneRuntimeRepository()
        #: AG3-141 (K5 Postgres-only): the object-mutation-claim persistence
        #: port ``object_claims.py`` orchestrates lock-sets over. Mirrors
        #: ``_instance_identity`` below: a DI-injected ``repository`` (test /
        #: alternative wiring, owns its own backend) that does not also inject
        #: an explicit ``object_claim_repository`` gets a self-contained
        #: in-memory fake (never the productive Postgres-backed default) --
        #: honoring the SAME cross-scope fairness contract -- so a DB-free unit
        #: test is never forced to also wire Postgres for the object claim.
        if object_claim_repository is not None:
            self._object_claim_repo = object_claim_repository
        elif repository is not None:
            self._object_claim_repo = _default_di_object_claim_repository()
        else:
            self._object_claim_repo = ObjectMutationClaimRepository()
        #: AG3-145 (K5 Postgres-only, FK-91 §91.1b): the Edge-Command-Queue DI
        #: seam -- see ``_resolve_edge_command_repository`` (mirrors
        #: ``object_claim_repository`` above; extracted to a module-level
        #: helper to keep this constructor's LOC budget, PY_CLASS_MAX_LOC_800).
        self._edge_command_repo = _resolve_edge_command_repository(edge_command_repository, repository)
        from agentkit.backend.state_backend.store.freeze_repository import (
            FreezeRepository,
            LocalFreezeJsonExport,
        )

        self._freeze_repository = freeze_repository or FreezeRepository()
        self._local_freeze_export = local_freeze_export or LocalFreezeJsonExport()
        #: AG3-147 (FK-10 §10.2.4b): the two-stage push-barrier evidence DI seam
        #: (Edge freshness ∧ server ref-read). An injected port wins; otherwise
        #: the composition root injects a factory for the PRODUCTIVE default store
        #: so the barrier lazily resolves the real Postgres+code-backend port
        #: without runtime importing bootstrap. A DI-injected ``repository`` (test
        #: / alternative wiring) without an explicit port/factory is UNWIRED for
        #: non-push-gated boundaries and a hard wiring error for push-gated ones.
        self._push_barrier_evidence = push_barrier_evidence
        self._push_barrier_evidence_factory = push_barrier_evidence_factory
        #: AG3-143 (K5 Postgres-only, FK-44 §44.3a): the execution-contract-
        #: digest reader for a genuinely fresh setup start. Mirrors
        #: ``object_claim_repository``: a DI-injected ``repository`` OR an
        #: injected ``phase_dispatcher`` (either one means this construction
        #: is a test / alternative wiring, never the fully productive default
        #: -- mirrors the existing pg-integration-test idiom of injecting a
        #: fake dispatcher while keeping the REAL Postgres-backed
        #: ``repository=None`` for the op/binding/ownership tables) that does
        #: not ALSO inject an explicit reader gets a trivial, always-
        #: succeeding in-memory reader (never the productive state-backend/
        #: filesystem gathering) -- so a DB-free/dispatcher-faked test
        #: exercising a fresh setup start is never forced to also wire a real
        #: project registration / story specification / skill-binding /
        #: prompt-bundle fixture. ``None`` on the FULLY productive default
        #: path (neither overridden) is lazily resolved to
        #: :meth:`_build_execution_contract_digest` on first use.
        self._execution_contract_digest_reader: Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome] | None
        if execution_contract_digest_reader is not None:
            self._execution_contract_digest_reader = execution_contract_digest_reader
        elif repository is not None or phase_dispatcher is not None:
            self._execution_contract_digest_reader = _default_di_execution_contract_digest_reader()
        else:
            self._execution_contract_digest_reader = None
        #: AG3-142 (K5 Postgres-only): the run-ownership persistence port the
        #: admission fence reads (and the setup-start finalize inserts into) is
        #: ``self._repo.load_active_ownership`` -- the SAME
        #: ``ControlPlaneRuntimeRepository`` port every other regime mutation
        #: uses (op/binding/lock CRUD). ONE repository, ONE DI seam: a test
        #: injecting only ``repository=`` (the common case) gets ownership reads
        #: wired to the SAME fake state as everything else, never a second,
        #: silently-disconnected ownership store.
        #: AG3-054: the deterministic single-phase dispatcher (FK-45 §45.1.2). DI:
        #: the engine/registry + pre-start guard are injected, never self-built by
        #: this service. ``None`` is lazily resolved to the productive composition
        #: on first ``start_phase`` (so non-dispatch flows pay no wiring cost).
        self._phase_dispatcher = phase_dispatcher
        #: AG3-054 claim timestamp seams (deterministic-injectable). ``now_fn``
        #: stamps claim/audit instants (``claimed_at``, operation-record
        #: timestamps) and ``token_factory`` mints the per-call owner token; both
        #: default to the productive UTC clock / uuid but are injectable so the
        #: claim protocol is deterministically testable. AG3-139: ``now_fn`` is no
        #: longer consulted for any wall-clock expiry decision -- a claim's age is
        #: never interpreted to end it.
        self._now_fn: Callable[[], datetime] = now_fn or (lambda: datetime.now(tz=UTC))
        self._token_factory: Callable[[], str] = token_factory or (lambda: f"owner-{uuid.uuid4().hex}")
        #: AG3-138 (IMPL-003/IMPL-004): THIS boot's resolved instance identity.
        #: For the PRODUCTIVE default store it stays ``None`` until the pre-serve
        #: startup hook resolves and binds it (fail-closed via
        #: :meth:`_current_instance_identity`): the listener never accepts a
        #: claim-acquiring request before the hook has run
        #: (``control_plane_http.app.serve_control_plane``). A DI-injected
        #: repository is the test / alternative-wiring seam (it owns its own
        #: backend, mirroring ``_uses_default_store``): when such a caller does
        #: not inject an explicit identity, a deterministic default is bound so
        #: the claim stamp stays well-formed -- this is NOT a production
        #: fallback (production uses the default store and the startup hook).
        self._instance_identity = instance_identity
        if self._instance_identity is None and repository is not None:
            self._instance_identity = _default_di_instance_identity()

    @property
    def repository(self) -> ControlPlaneRuntimeRepository:
        """The control-plane runtime persistence port (AG3-138 startup hook wiring)."""
        return self._repo

    @property
    def object_claim_repository(self) -> ObjectMutationClaimRepository:
        """The object-mutation-claim persistence port (AG3-141 startup hook wiring)."""
        return self._object_claim_repo

    def bind_instance_identity(self, identity: BackendInstanceIdentityRecord) -> None:
        """Bind THIS boot's resolved instance identity (AG3-138 startup hook).

        Called exactly once by the pre-serve startup hook after
        :func:`~agentkit.backend.control_plane.instance_identity.resolve_backend_instance_identity`
        and :func:`~agentkit.backend.control_plane.startup_reconcile.run_startup_reconciliation`
        both succeed -- before the listener accepts its first request.
        """
        self._instance_identity = identity

    def _current_instance_identity(self) -> BackendInstanceIdentityRecord:
        """Return THIS boot's instance identity, resolving it once when needed.

        Every newly-acquired claim is stamped with the backend instance identity
        (AG3-138 AC3, FK-91 §91.1a rule 16). The identity is never invented and
        never a foreign one -- it is resolved from the authoritative persistent
        store (``backend_instance_identity``, Postgres-only, K5):

        * The **serving path** binds it up front: ``serve_control_plane`` runs the
          pre-serve startup hook (identity resolution + orphan reconciliation)
          BEFORE the listener accepts its first request (AC1/AC9), then
          :meth:`bind_instance_identity` binds it onto the service the listener
          uses -- so this method returns the already-bound value and the lazy
          branch below is never reached on the serving path.
        * A **DI-injected** repository binds a deterministic identity in
          ``__init__`` (the test / alternative-wiring seam).
        * For a **directly-constructed default-store** service the identity is
          resolved here lazily on first claim and memoized -- mirroring
          :meth:`_require_postgres_backend_on_first_use`, the default store is
          self-sufficient to resolve its OWN identity from the store. It never
          fabricates or guesses an identity (trap: own vs foreign); when the
          Postgres store is unavailable it fails CLOSED (K5) rather than stamping
          a fabricated identity onto a claim.
        """
        if self._instance_identity is not None:
            return self._instance_identity
        if self._uses_default_store:
            from agentkit.backend.control_plane.instance_identity import (
                resolve_backend_instance_identity,
            )
            from agentkit.backend.control_plane.repository import (
                BackendInstanceIdentityRepository,
            )

            self._instance_identity = resolve_backend_instance_identity(
                BackendInstanceIdentityRepository(),
            )
            return self._instance_identity
        # A DI repository without an explicit identity has one bound in __init__;
        # reaching here would be a wiring error -- fail closed rather than stamp
        # an unresolved claim.
        from agentkit.backend.exceptions import ConfigError

        raise ConfigError(
            "control-plane claim acquisition requires a resolved backend "
            "instance identity (AG3-138 IMPL-003/IMPL-004, fail-closed): no "
            "identity is bound and no default-store resolution seam is available.",
        )

    def _require_postgres_backend_on_first_use(self) -> None:
        """Assert the Postgres backend before the first default-store use (#3).

        The control-plane runtime store (operation/claim, session-binding and lock
        records) is part of the canonical central PostgreSQL runtime persistence
        (FK-22 §22.9) and has NO SQLite implementation. When this service uses the
        PRODUCTIVE default store, every store entrypoint calls this once: it fails
        CLOSED and CLEARLY with an explicit error if the active backend is not
        Postgres, instead of an opaque ``RuntimeError`` deep inside the atomic
        claim. A DI-injected repository (tests / alternative wiring) is exempt.
        """
        if not self._uses_default_store or self._backend_checked:
            return
        _require_postgres_control_plane_backend()
        self._backend_checked = True

    def _sync_local_freeze_projection(self, story_id: str) -> None:
        """Publish one active family member, or remove the empty projection."""

        records = self._freeze_repository.read_freezes(story_id)
        if records:
            contested = next(
                (record for record in records if record.kind.value == "contested_local_writes"),
                records[0],
            )
            self._local_freeze_export.write_record(contested)
            return
        self._local_freeze_export.remove()


__all__ = ["_AdmissionIdentityMixin"]
