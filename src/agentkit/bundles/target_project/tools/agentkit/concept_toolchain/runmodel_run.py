"""Lifecycle, lease, round, and coverage state of an FK-78 incubation run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_validation import (
    Ctx,
    Issue,
    check_keys,
    read_bool,
    read_enum,
    read_int,
    read_json_object,
    read_matched,
    read_nullable_object,
    read_object_items,
    read_optional_str,
    read_semver,
    read_sha,
    read_sha_or_null,
    read_str,
    read_str_list,
    read_sub_object,
    read_time,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

@dataclass(frozen=True)
class BaseRevision:
    """Pinned corpus revision of the freeze (``git`` sha or content digest)."""

    kind: str
    value: str


@dataclass(frozen=True)
class RunActor:
    """Council-orchestrator identity of the run."""

    role: str
    harness: str
    model: str
    principal_id: str
    session_ref: str


@dataclass(frozen=True)
class DataRelease:
    """User-approved data release of one participant."""

    max_data_class: str
    source_ids: tuple[str, ...]
    package_ids: tuple[str, ...]
    approved_by_user: bool


@dataclass(frozen=True)
class Participant:
    """One council worker registered in RUN.json."""

    participant_id: str
    model: str
    backend: str
    spawn_mode: str
    principal_id: str
    session_ref: str | None
    data_release: DataRelease
    status: str


@dataclass(frozen=True)
class BlockedInfo:
    """Non-null only in state BLOCKED."""

    reason: str
    since_state: str


@dataclass(frozen=True)
class RecheckInfo:
    """Non-null only in state RECHECK."""

    drifted_paths: tuple[str, ...]
    detected_in_state: str


@dataclass(frozen=True)
class RunState:
    """Validated RUN.json — the only authoritative run state (FK-78 78.4)."""

    schema_version: str
    run_id: str
    title: str
    profile: str
    state: str
    state_revision: int
    lease_fencing_token: int
    current_round: int
    base_revision: BaseRevision
    data_class: str
    actor: RunActor
    participants: tuple[Participant, ...]
    register_digests: Mapping[str, str | None]
    blocked: BlockedInfo | None
    recheck: RecheckInfo | None
    last_completed_action: str
    next_action: str
    updated_at: str

    @property
    def run_uuid8(self) -> str:
        """Return the ``run_uuid8`` suffix shared by all run-scoped IDs."""
        return self.run_id[-8:]


def _run_keys() -> tuple[str, ...]:
    return (
        "schema_version",
        "run_id",
        "title",
        "profile",
        "state",
        "state_revision",
        "lease_fencing_token",
        "current_round",
        "base_revision",
        "data_class",
        "actor",
        "participants",
        "register_digests",
        "blocked",
        "recheck",
        "last_completed_action",
        "next_action",
        "updated_at",
    )


RUN_KEYS = _run_keys()


def parse_base_revision(ctx: Ctx, obj: Mapping[str, object], where: str) -> BaseRevision:
    sub = read_sub_object(ctx, obj, where, "base_revision")
    if sub is None:
        return BaseRevision(kind="", value="")
    sub_where = f"{where}.base_revision"
    check_keys(ctx, sub, sub_where, ("kind", "value"))
    return BaseRevision(
        kind=read_enum(ctx, sub, sub_where, "kind", Vocab.BASE_REVISION_KINDS), value=read_str(ctx, sub, sub_where, "value")
    )


def _parse_actor(ctx: Ctx, obj: Mapping[str, object], where: str) -> RunActor:
    sub = read_sub_object(ctx, obj, where, "actor")
    if sub is None:
        return RunActor(role="", harness="", model="", principal_id="", session_ref="")
    sub_where = f"{where}.actor"
    check_keys(ctx, sub, sub_where, ("role", "harness", "model", "principal_id", "session_ref"))
    return RunActor(
        role=read_str(ctx, sub, sub_where, "role"),
        harness=read_str(ctx, sub, sub_where, "harness"),
        model=read_str(ctx, sub, sub_where, "model"),
        principal_id=read_matched(
            ctx, sub, sub_where, "principal_id", Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL
        ),
        session_ref=read_str(ctx, sub, sub_where, "session_ref"),
    )


def _parse_data_release(ctx: Ctx, obj: Mapping[str, object], where: str) -> DataRelease:
    sub = read_sub_object(ctx, obj, where, "data_release")
    if sub is None:
        return DataRelease(max_data_class="", source_ids=(), package_ids=(), approved_by_user=False)
    sub_where = f"{where}.data_release"
    check_keys(ctx, sub, sub_where, ("max_data_class", "source_ids", "package_ids", "approved_by_user"))
    return DataRelease(
        max_data_class=read_enum(ctx, sub, sub_where, "max_data_class", Vocab.DATA_CLASSES),
        source_ids=read_str_list(
            ctx, sub, sub_where, "source_ids", Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL
        ),
        package_ids=read_str_list(
            ctx, sub, sub_where, "package_ids", Vocab.PACKAGE_ID_RE, Vocab.PACKAGE_ID_LABEL
        ),
        approved_by_user=read_bool(ctx, sub, sub_where, "approved_by_user"),
    )


def _parse_participants(ctx: Ctx, obj: Mapping[str, object], where: str) -> tuple[Participant, ...]:
    participants: list[Participant] = []
    for item_where, item in read_object_items(ctx, obj, where, "participants"):
        expected = ("participant_id", "model", "backend", "spawn_mode", "principal_id", "session_ref", "data_release", "status")
        check_keys(ctx, item, item_where, expected)
        participants.append(
            Participant(
                participant_id=read_matched(
                    ctx,
                    item,
                    item_where,
                    "participant_id",
                    Vocab.PARTICIPANT_ID_RE,
                    Vocab.PARTICIPANT_ID_LABEL,
                ),
                model=read_str(ctx, item, item_where, "model"),
                backend=read_str(ctx, item, item_where, "backend"),
                spawn_mode=read_enum(ctx, item, item_where, "spawn_mode", Vocab.SPAWN_MODES),
                principal_id=read_matched(
                    ctx,
                    item,
                    item_where,
                    "principal_id",
                    Vocab.PRINCIPAL_ID_RE,
                    Vocab.PRINCIPAL_ID_LABEL,
                ),
                session_ref=read_optional_str(ctx, item, item_where, "session_ref"),
                data_release=_parse_data_release(ctx, item, item_where),
                status=read_enum(ctx, item, item_where, "status", Vocab.PARTICIPANT_STATUSES),
            )
        )
    return tuple(participants)


def _parse_register_digests(ctx: Ctx, obj: Mapping[str, object], where: str) -> Mapping[str, str | None]:
    sub = read_sub_object(ctx, obj, where, "register_digests")
    if sub is None:
        return dict.fromkeys(Vocab.REGISTER_DIGEST_KEYS)
    sub_where = f"{where}.register_digests"
    check_keys(ctx, sub, sub_where, Vocab.REGISTER_DIGEST_KEYS)
    return {key: read_sha_or_null(ctx, sub, sub_where, key) for key in Vocab.REGISTER_DIGEST_KEYS if key in sub}


def _parse_blocked(ctx: Ctx, obj: Mapping[str, object], where: str) -> BlockedInfo | None:
    sub = read_nullable_object(ctx, obj, where, "blocked")
    if sub is None:
        return None
    sub_where = f"{where}.blocked"
    check_keys(ctx, sub, sub_where, ("reason", "since_state"))
    return BlockedInfo(
        reason=read_str(ctx, sub, sub_where, "reason"),
        since_state=read_enum(ctx, sub, sub_where, "since_state", Vocab.RUN_STATES),
    )


def _parse_recheck(ctx: Ctx, obj: Mapping[str, object], where: str) -> RecheckInfo | None:
    sub = read_nullable_object(ctx, obj, where, "recheck")
    if sub is None:
        return None
    sub_where = f"{where}.recheck"
    check_keys(ctx, sub, sub_where, ("drifted_paths", "detected_in_state"))
    return RecheckInfo(
        drifted_paths=read_str_list(ctx, sub, sub_where, "drifted_paths"),
        detected_in_state=read_enum(ctx, sub, sub_where, "detected_in_state", Vocab.RUN_STATES),
    )


def load_run_state(path: Path) -> tuple[RunState | None, list[Issue]]:
    """Load and validate ``RUN.json`` fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "run", RUN_KEYS)
    run = RunState(
        schema_version=read_semver(ctx, raw, "run"),
        run_id=read_matched(ctx, raw, "run", "run_id", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        title=read_str(ctx, raw, "run", "title"),
        profile=read_enum(ctx, raw, "run", "profile", Vocab.RUN_PROFILES),
        state=read_enum(ctx, raw, "run", "state", Vocab.RUN_STATES),
        state_revision=read_int(ctx, raw, "run", "state_revision", minimum=1),
        lease_fencing_token=read_int(ctx, raw, "run", "lease_fencing_token", minimum=1),
        current_round=read_int(ctx, raw, "run", "current_round", minimum=0),
        base_revision=parse_base_revision(ctx, raw, "run"),
        data_class=read_enum(ctx, raw, "run", "data_class", Vocab.DATA_CLASSES),
        actor=_parse_actor(ctx, raw, "run"),
        participants=_parse_participants(ctx, raw, "run"),
        register_digests=_parse_register_digests(ctx, raw, "run"),
        blocked=_parse_blocked(ctx, raw, "run"),
        recheck=_parse_recheck(ctx, raw, "run"),
        last_completed_action=read_matched(
            ctx, raw, "run", "last_completed_action", Vocab.ACTION_ID_RE, "stable action id"
        ),
        next_action=read_matched(ctx, raw, "run", "next_action", Vocab.ACTION_ID_RE, "stable action id"),
        updated_at=read_time(ctx, raw, "run", "updated_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return run, []


@dataclass(frozen=True)
class LeaseOwner:
    """Writer identity of the lease (opaque, non-secret handles only)."""

    principal_id: str
    harness: str
    session_ref: str


LEASE_KEYS = ("schema_version", "run_id", "owner", "fencing_token", "acquired_at", "ttl_seconds", "released")


@dataclass(frozen=True)
class Lease:
    """Validated LEASE.json (FK-78 section 78.4)."""

    schema_version: str
    run_id: str
    owner: LeaseOwner
    fencing_token: int
    acquired_at: str
    ttl_seconds: int
    released: bool


def load_lease(path: Path) -> tuple[Lease | None, list[Issue]]:
    """Load and validate ``LEASE.json`` fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "lease", LEASE_KEYS)
    owner_obj = read_sub_object(ctx, raw, "lease", "owner")
    owner = LeaseOwner(principal_id="", harness="", session_ref="")
    if owner_obj is not None:
        check_keys(ctx, owner_obj, Vocab.LEASE_OWNER_LOCATOR, ("principal_id", "harness", "session_ref"))
        owner = LeaseOwner(
            principal_id=read_matched(
                ctx,
                owner_obj,
                Vocab.LEASE_OWNER_LOCATOR,
                "principal_id",
                Vocab.PRINCIPAL_ID_RE,
                Vocab.PRINCIPAL_ID_LABEL,
            ),
            harness=read_str(ctx, owner_obj, Vocab.LEASE_OWNER_LOCATOR, "harness"),
            session_ref=read_str(ctx, owner_obj, Vocab.LEASE_OWNER_LOCATOR, "session_ref"),
        )
    lease = Lease(
        schema_version=read_semver(ctx, raw, "lease"),
        run_id=read_matched(ctx, raw, "lease", "run_id", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        owner=owner,
        fencing_token=read_int(ctx, raw, "lease", "fencing_token", minimum=1),
        acquired_at=read_time(ctx, raw, "lease", "acquired_at"),
        ttl_seconds=read_int(ctx, raw, "lease", "ttl_seconds", minimum=1),
        released=read_bool(ctx, raw, "lease", "released"),
    )
    if ctx.issues:
        return None, ctx.issues
    return lease, []


@dataclass(frozen=True)
class RoundDispatch:
    """Dispatch record of one participant in a round."""

    sent_at: str
    prompt_digest: str
    input_digests: tuple[str, ...]


@dataclass(frozen=True)
class RoundReceipt:
    """Receipt record of one participant in a round."""

    received_at: str
    proposal_digest: str


@dataclass(frozen=True)
class RoundParticipant:
    """One participant entry of ROUND.json."""

    participant_id: str
    dispatch: RoundDispatch
    receipt: RoundReceipt | None
    outcome: str
    outcome_reason: str


@dataclass(frozen=True)
class RoundSeal:
    """Round seal with digest bindings of the sealed proposals."""

    sealed_at: str
    sealed_proposal_digests: Mapping[str, str]


ROUND_KEYS = ("schema_version", "run_id", "round", "participants", "sealed", "seal")


@dataclass(frozen=True)
class RoundState:
    """Validated ``rounds/r<N>/ROUND.json`` (FK-78 section 78.6)."""

    schema_version: str
    run_id: str
    round: int
    participants: tuple[RoundParticipant, ...]
    sealed: bool
    seal: RoundSeal | None


def _parse_round_participant(ctx: Ctx, item_where: str, item: Mapping[str, object]) -> RoundParticipant:
    check_keys(ctx, item, item_where, ("participant_id", "dispatch", "receipt", "outcome", "outcome_reason"))
    dispatch_obj = read_sub_object(ctx, item, item_where, "dispatch")
    dispatch = RoundDispatch(sent_at="", prompt_digest="", input_digests=())
    if dispatch_obj is not None:
        dispatch_where = f"{item_where}.dispatch"
        check_keys(ctx, dispatch_obj, dispatch_where, ("sent_at", "prompt_digest", "input_digests"))
        dispatch = RoundDispatch(
            sent_at=read_time(ctx, dispatch_obj, dispatch_where, "sent_at"),
            prompt_digest=read_sha(ctx, dispatch_obj, dispatch_where, "prompt_digest"),
            input_digests=read_str_list(
                ctx, dispatch_obj, dispatch_where, "input_digests", Vocab.SHA256_RE, "sha256 digest"
            ),
        )
    receipt_obj = read_nullable_object(ctx, item, item_where, "receipt")
    receipt: RoundReceipt | None = None
    if receipt_obj is not None:
        receipt_where = f"{item_where}.receipt"
        check_keys(ctx, receipt_obj, receipt_where, ("received_at", "proposal_digest"))
        receipt = RoundReceipt(
            received_at=read_time(ctx, receipt_obj, receipt_where, "received_at"),
            proposal_digest=read_sha(ctx, receipt_obj, receipt_where, "proposal_digest"),
        )
    outcome = read_enum(ctx, item, item_where, "outcome", Vocab.ROUND_OUTCOMES)
    outcome_reason = read_str(ctx, item, item_where, "outcome_reason", allow_empty=True)
    if outcome and outcome != "received" and not outcome_reason:
        ctx.error(f"{item_where}.outcome_reason", f"required for outcome {outcome!r}")
    if outcome == "received" and receipt is None:
        ctx.error(f"{item_where}.receipt", "required for outcome 'received'")
    return RoundParticipant(
        participant_id=read_matched(
            ctx, item, item_where, "participant_id", Vocab.PARTICIPANT_ID_RE, Vocab.PARTICIPANT_ID_LABEL
        ),
        dispatch=dispatch,
        receipt=receipt,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )


def _parse_round_seal(ctx: Ctx, raw: Mapping[str, object], sealed: bool) -> RoundSeal | None:
    seal_obj = read_nullable_object(ctx, raw, "round", "seal")
    if seal_obj is None:
        if sealed:
            ctx.error(Vocab.ROUND_SEAL_LOCATOR, "required when sealed is true")
        return None
    if not sealed:
        ctx.error(Vocab.ROUND_SEAL_LOCATOR, "must be null when sealed is false")
    check_keys(ctx, seal_obj, Vocab.ROUND_SEAL_LOCATOR, ("sealed_at", "sealed_proposal_digests"))
    digests_obj = read_sub_object(ctx, seal_obj, Vocab.ROUND_SEAL_LOCATOR, "sealed_proposal_digests")
    digests: dict[str, str] = {}
    if digests_obj is not None:
        for participant_id, digest in digests_obj.items():
            where = f"round.seal.sealed_proposal_digests.{participant_id}"
            if Vocab.PARTICIPANT_ID_RE.fullmatch(participant_id) is None:
                ctx.error(where, "key must be a participant id")
            if not isinstance(digest, str) or Vocab.SHA256_RE.fullmatch(digest) is None:
                ctx.error(where, "must be a sha256 lowercase-hex digest")
                continue
            digests[participant_id] = digest
    return RoundSeal(
        sealed_at=read_time(ctx, seal_obj, Vocab.ROUND_SEAL_LOCATOR, "sealed_at"),
        sealed_proposal_digests=digests,
    )


def load_round_state(path: Path) -> tuple[RoundState | None, list[Issue]]:
    """Load and validate one ``ROUND.json`` fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "round", ROUND_KEYS)
    sealed = read_bool(ctx, raw, "round", "sealed")
    round_state = RoundState(
        schema_version=read_semver(ctx, raw, "round"),
        run_id=read_matched(ctx, raw, "round", "run_id", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        round=read_int(ctx, raw, "round", "round", minimum=1),
        participants=tuple(
            _parse_round_participant(ctx, where, item) for where, item in read_object_items(ctx, raw, "round", "participants")
        ),
        sealed=sealed,
        seal=_parse_round_seal(ctx, raw, sealed),
    )
    if ctx.issues:
        return None, ctx.issues
    return round_state, []


@dataclass(frozen=True)
class CoveragePackage:
    """One worker coverage package of coverage-plan.json."""

    package_id: str
    description: str
    paths: tuple[str, ...]
    assigned_participants: tuple[str, ...]
    redundancy: int


COVERAGE_PLAN_KEYS = ("schema_version", "run_id", "packages", "integration_package_id")


@dataclass(frozen=True)
class CoveragePlan:
    """Validated ``baseline/coverage-plan.json`` (FK-78 section 78.6)."""

    schema_version: str
    run_id: str
    packages: tuple[CoveragePackage, ...]
    integration_package_id: str


def load_coverage_plan(path: Path) -> tuple[CoveragePlan | None, list[Issue]]:
    """Load and validate ``coverage-plan.json`` fail-closed."""
    raw, issues = read_json_object(path)
    if raw is None:
        return None, issues
    ctx = Ctx()
    check_keys(ctx, raw, "plan", COVERAGE_PLAN_KEYS)
    packages: list[CoveragePackage] = []
    for item_where, item in read_object_items(ctx, raw, "plan", "packages"):
        check_keys(ctx, item, item_where, ("package_id", "description", "paths", "assigned_participants", "redundancy"))
        packages.append(
            CoveragePackage(
                package_id=read_matched(
                    ctx, item, item_where, "package_id", Vocab.PACKAGE_ID_RE, Vocab.PACKAGE_ID_LABEL
                ),
                description=read_str(ctx, item, item_where, "description"),
                paths=read_str_list(ctx, item, item_where, "paths"),
                assigned_participants=read_str_list(
                    ctx,
                    item,
                    item_where,
                    "assigned_participants",
                    Vocab.PARTICIPANT_ID_RE,
                    Vocab.PARTICIPANT_ID_LABEL,
                ),
                redundancy=read_int(ctx, item, item_where, "redundancy", minimum=1),
            )
        )
    plan = CoveragePlan(
        schema_version=read_semver(ctx, raw, "plan"),
        run_id=read_matched(ctx, raw, "plan", "run_id", Vocab.RUN_ID_RE, Vocab.RUN_ID_LABEL),
        packages=tuple(packages),
        integration_package_id=read_matched(
            ctx, raw, "plan", "integration_package_id", Vocab.PACKAGE_ID_RE, Vocab.PACKAGE_ID_LABEL
        ),
    )
    if ctx.issues:
        return None, ctx.issues
    return plan, []
