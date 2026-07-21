"""Fail-closed loaders for incubation-run artifacts (FK-78 sections 78.3-78.14).

Covers RUN.json, LEASE.json, ROUND.json, coverage-plan.json,
promotion-manifest.json, projection receipts, declassification receipts,
scope-lock blobs, the corpus-wide projection manifest, semantic request
packs/receipts, and every TSV register (header contract exactly as the
bundled ``templates/tsv-headers.md``).

Fail-closed: unknown fields, missing required fields, enum violations,
ID-grammar violations (section 78.3), non-UTC-``Z`` timestamps, and
malformed sha256 digests are validation issues. JSON loaders return
``(model, issues)`` with ``model=None`` when any issue was found; TSV
loaders additionally return the structurally parseable rows so callers can
continue cross-checks while still reporting every issue.

Canonical TSV subset digests (register pins): the ``*_input`` and
``derived_claims`` entries of ``RUN.json.register_digests`` are SHA-256
digests over the canonical serialization of a row subset: the header
line followed by the selected data rows sorted lexicographically, joined
with LF and terminated with a trailing LF, encoded UTF-8. For a
contract-conform register that still contains exactly the selected rows
(the state at freeze time) this equals the raw file digest, so a pin
taken at freeze time stays materially verifiable after later appends:

- ``source_register_input``: rows with ``source_phase == input``.
- ``source_units_input``: rows whose ``source_id`` is an input source.
- ``claims_inventory_input``: rows whose ``source_id`` is an input source.
- ``derived_claims``: rows whose ``source_id`` is a derived source.

The two intake pins are chain heads (see :func:`intake_entry_digest`),
pinned outside ``source-intake.tsv`` so intake and register cannot be
pruned together unnoticed:

- ``source_intake_input_head``: head at the input freeze, immutable
  afterwards. Every later chain state must still contain exactly this
  prefix (:func:`intake_prefix_head_index`), which makes removing or
  reordering an input entry provable.
- ``source_intake_final_head``: head before entering PROMOTING,
  immutable afterwards.

:func:`derive_register_digests` recomputes the current chain head for
both, but the checker only accepts a pin when the prefix proof holds;
recomputing the chain after a prune therefore cannot repair the pins.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*-[0-9a-f]{8}$")
PARTICIPANT_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PRINCIPAL_ID_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
UNIT_ID_RE = re.compile(r"^SU-[0-9a-f]{8}-\d{4,}$")
CLAIM_ID_RE = re.compile(r"^CLM-[0-9a-f]{8}-\d{4,}$")
ATOM_ID_RE = re.compile(r"^ATM-[0-9a-f]{8}-\d{4,}$")
RECEIPT_ID_RE = re.compile(r"^RCP-[0-9a-f]{8}-\d{4,}$")
PACKAGE_ID_RE = re.compile(r"^PKG-[0-9a-f]{8}-\d{2,}$")
FINDING_ID_RE = re.compile(r"^FND-[0-9a-f]{8}-\d{4,}$")
SOURCE_ID_RE = re.compile(r"^SRC-[0-9a-f]{8}-\d{4,}$")
ACTION_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

RUN_STATES = (
    "FRAMING",
    "STAFFING",
    "PROPOSING",
    "CONVERGING",
    "SYNTHESIZING",
    "DECIDING",
    "PROMOTING",
    "PROMOTION_FAILED",
    "BLOCKED",
    "RECHECK",
    "CLOSED",
    "ABORTED",
)
#: Rank of the linear main path; BLOCKED/RECHECK/PROMOTION_FAILED map via context.
LINEAR_STATE_RANK = {
    "FRAMING": 0,
    "STAFFING": 1,
    "PROPOSING": 2,
    "CONVERGING": 3,
    "SYNTHESIZING": 4,
    "DECIDING": 5,
    "PROMOTING": 6,
    "CLOSED": 7,
}
RUN_PROFILES = ("LIGHT_INCUBATION", "FULL_ATOM")
DATA_CLASSES = ("open", "internal", "sensitive")
SPAWN_MODES = ("harness-bridge", "llm-hub", "subagent", "cli-resume")
PARTICIPANT_STATUSES = ("active", "failed", "replaced", "withdrawn")
ROUND_OUTCOMES = ("received", "timeout", "failed", "excluded")
BASE_REVISION_KINDS = ("git", "digest")
REGISTER_DIGEST_KEYS = (
    "corpus_baseline",
    "source_intake_input_head",
    "source_intake_final_head",
    "source_register_input",
    "source_units_input",
    "claims_inventory_input",
    "derived_claims",
    "disposition_ledger",
    "source_register_final",
    "source_units_final",
    "atom_register",
)
SOURCE_PHASES = ("input", "derived")
SOURCE_ROLES = ("BRIEFING", "PROPOSAL", "SYNTHESIS", "DISSENT_MAP", "PO_DECISION", "NORMATIVE_BASELINE", "EVIDENCE")
REVIEW_STATUSES = ("PASS", "PASS_WITH_GAPS", "FAIL", "N_A")
CHANGE_KINDS = ("unchanged", "modified", "added", "removed")
ARTIFACT_KINDS = (
    "briefing",
    "proposal",
    "synthesis",
    "dissent_map",
    "inventory",
    "ledger",
    "atom_register",
    "manifest",
    "receipt",
    "round_state",
    "coverage",
    "finding",
    "journal",
    "other",
)
VCS_DISPOSITIONS = ("versioned", "local")
FINDING_SEVERITIES = ("P0", "P1", "P2")
FINDING_STATUSES = ("open", "resolved", "accepted_by_po")
SYNTHESIS_DISPOSITIONS = ("ADOPTED", "MERGED", "SUPERSEDED_BY_CLAIM", "REJECTED_WITH_REASON", "OPEN_QUESTION")
ATOM_TYPES = (
    "REQUIREMENT",
    "DOMAIN_FACT",
    "DECISION",
    "RATIONALE",
    "EVIDENCE",
    "PARAMETER_CANDIDATE",
    "REJECTION",
    "OPEN_QUESTION",
)
NORMATIVE_STATUSES = ("proposal", "accepted", "evidence", "rejected", "open")
ATOM_DISPOSITIONS = (
    "COVERED_EXACT",
    "COVERED_SPLIT",
    "REJECTED",
    "OPEN_MISSING",
    "DEFERRED_BACKLOG",
    "EVIDENCE_ONLY",
    "OUT_OF_AUDIT",
    "SUPERSEDED",
)
COVERED_DISPOSITIONS = ("COVERED_EXACT", "COVERED_SPLIT")
PROMOTION_DISPOSITIONS = ("promoted", "rejected", "deferred")
SEMANTIC_GATES = ("authority-prose", "scope-consistency")
SEMANTIC_GATE_KEYS = {"w2": "authority-prose", "w3": "scope-consistency"}
SEMANTIC_GATE_STATUSES = ("passed", "blocked", "not_run")
SEMANTIC_RECEIPT_STATUSES = ("passed", "failed")
RECEIPT_VERDICTS = ("equivalent", "disagrees")
LOCK_BACKENDS = ("filesystem", "git-remote")
LIFECYCLES = ("current", "draft", "deprecated", "superseded")
ASSERTION_STATUSES = ("draft", "active", "blocked_projection", "deprecated", "superseded")
EQUIVALENCE_STATUSES = ("unreviewed", "equivalent", "disagrees", "stale", "blocked_missing_target")
PROJECTION_KINDS = ("formal", "prose", "registry", "support", "test-oracle")
DECISION_STATUSES = ("proposed", "accepted", "rejected", "superseded")

_SCOPE_NORMALIZE_RE = re.compile(r"[._-]+")


@dataclass(frozen=True)
class Issue:
    """One fail-closed validation issue inside an artifact."""

    locator: str
    message: str


class _Ctx:
    """Issue accumulator shared by all field validators."""

    __slots__ = ("issues",)

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, locator: str, message: str) -> None:
        self.issues.append(Issue(locator=locator, message=message))


# --------------------------------------------------------------------------
# Generic field validators
# --------------------------------------------------------------------------


def _read_json_object(path: Path) -> tuple[dict[str, object] | None, list[Issue]]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [Issue(locator="file", message=f"not readable as JSON: {exc}")]
    if not isinstance(raw, dict):
        return None, [Issue(locator="file", message="top level must be a JSON object")]
    return raw, []


def _keys(ctx: _Ctx, obj: Mapping[str, object], where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    unknown = sorted(set(obj) - set(required) - set(optional))
    missing = sorted(set(required) - set(obj))
    for key in unknown:
        ctx.error(where, f"unknown field {key!r}")
    for key in missing:
        ctx.error(where, f"missing required field {key!r}")


def _str(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str, *, allow_empty: bool = False) -> str:
    if key not in obj:
        return ""
    value = obj[key]
    if not isinstance(value, str) or (value == "" and not allow_empty):
        ctx.error(f"{where}.{key}", "must be a non-empty string")
        return ""
    return value


def _opt_str(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> str | None:
    if key not in obj:
        return None
    value = obj[key]
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        ctx.error(f"{where}.{key}", "must be a non-empty string or null")
        return None
    return value


def _int(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str, *, minimum: int = 0) -> int:
    if key not in obj:
        return minimum
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        ctx.error(f"{where}.{key}", f"must be an integer >= {minimum}")
        return minimum
    return value


def _bool(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> bool:
    if key not in obj:
        return False
    value = obj[key]
    if not isinstance(value, bool):
        ctx.error(f"{where}.{key}", "must be a boolean")
        return False
    return value


def _enum(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str, allowed: tuple[str, ...]) -> str:
    value = _str(ctx, obj, where, key)
    if value and value not in allowed:
        ctx.error(f"{where}.{key}", f"must be one of {', '.join(allowed)}, got {value!r}")
        return ""
    return value


def _matched(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str, pattern: re.Pattern[str], what: str) -> str:
    value = _str(ctx, obj, where, key)
    if value and pattern.fullmatch(value) is None:
        ctx.error(f"{where}.{key}", f"must be a {what}, got {value!r}")
    return value


def _sha(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> str:
    return _matched(ctx, obj, where, key, SHA256_RE, "sha256 lowercase-hex digest")


def _sha_or_null(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> str | None:
    value = _opt_str(ctx, obj, where, key)
    if value is not None and SHA256_RE.fullmatch(value) is None:
        ctx.error(f"{where}.{key}", f"must be a sha256 lowercase-hex digest or null, got {value!r}")
        return None
    return value


def _time(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> str:
    return _matched(ctx, obj, where, key, TIMESTAMP_RE, "UTC ISO-8601 timestamp with Z suffix")


def _semver(ctx: _Ctx, obj: Mapping[str, object], where: str) -> str:
    value = _str(ctx, obj, where, "schema_version")
    if value and re.fullmatch(r"1\.\d+\.\d+", value) is None:
        ctx.error(f"{where}.schema_version", f"must be SemVer with major 1, got {value!r}")
    return value


def _str_list(
    ctx: _Ctx,
    obj: Mapping[str, object],
    where: str,
    key: str,
    pattern: re.Pattern[str] | None = None,
    what: str = "value",
) -> tuple[str, ...]:
    if key not in obj:
        return ()
    value = obj[key]
    if not isinstance(value, list):
        ctx.error(f"{where}.{key}", "must be an array")
        return ()
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item == "":
            ctx.error(f"{where}.{key}[{index}]", "must be a non-empty string")
            continue
        if pattern is not None and pattern.fullmatch(item) is None:
            ctx.error(f"{where}.{key}[{index}]", f"must be a {what}, got {item!r}")
            continue
        items.append(item)
    return tuple(items)


def _obj_items(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> list[tuple[str, dict[str, object]]]:
    if key not in obj:
        return []
    value = obj[key]
    if not isinstance(value, list):
        ctx.error(f"{where}.{key}", "must be an array")
        return []
    items: list[tuple[str, dict[str, object]]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            ctx.error(f"{where}.{key}[{index}]", "must be an object")
            continue
        items.append((f"{where}.{key}[{index}]", item))
    return items


def _sub_obj(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> dict[str, object] | None:
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, dict):
        ctx.error(f"{where}.{key}", "must be an object")
        return None
    return value


def _nullable_obj(ctx: _Ctx, obj: Mapping[str, object], where: str, key: str) -> dict[str, object] | None:
    if key not in obj or obj[key] is None:
        return None
    return _sub_obj(ctx, obj, where, key)


# --------------------------------------------------------------------------
# Canonical digests and scope-lock naming
# --------------------------------------------------------------------------


def canonical_request_digest(payload: Mapping[str, object]) -> str:
    """Compute the semantic request-pack digest over the canonical pack.

    The digest covers the canonically serialized pack (sorted keys, compact
    separators, UTF-8) without the ``request_digest`` field itself.
    """
    reduced = {key: value for key, value in payload.items() if key != "request_digest"}
    canonical = json.dumps(reduced, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_projection_entry_digest(raw_entry: Mapping[str, object], self_target: str) -> str:
    """Compute the canonical entry digest for manifest self-projection.

    Per FK-78 section 78.12 the digest covers the canonically serialized
    entry without derived status fields (``assertion_status``, each
    projection's ``equivalence_status``) and without the self-referencing
    projection's own ``target_digest`` field.
    """
    reduced: dict[str, object] = {key: value for key, value in raw_entry.items() if key != "assertion_status"}
    raw_projections = reduced.get("required_projections")
    if isinstance(raw_projections, list):
        slim_projections: list[object] = []
        for item in raw_projections:
            if isinstance(item, dict):
                slim = {key: value for key, value in item.items() if key != "equivalence_status"}
                if slim.get("target") == self_target:
                    slim.pop("target_digest", None)
                slim_projections.append(slim)
            else:
                slim_projections.append(item)
        reduced["required_projections"] = slim_projections
    canonical = json.dumps(reduced, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_scope_id(scope_id: str) -> str:
    """Normalize a scope id for lock naming: lowercase, ``[._-]+`` to ``-``."""
    return _SCOPE_NORMALIZE_RE.sub("-", scope_id.lower())


def scope_hash(scope_id: str) -> str:
    """Return the full scope hash used for lock naming and remote refs."""
    return hashlib.sha256(scope_id.encode("utf-8")).hexdigest()


def scope_lock_filename(scope_id: str) -> str:
    """Return the filesystem lock filename for a scope (FK-78 section 78.11)."""
    return f"{normalize_scope_id(scope_id)}.{scope_hash(scope_id)[:8]}.lock.json"


def scope_lock_ref(scope_id: str) -> str:
    """Return the git-remote lock ref of a scope (FK-78 section 78.11)."""
    return f"refs/concept-locks/{scope_hash(scope_id)}"


def canonical_lock_blob_digest(
    scope_id: str, locked_by_run: str, fencing_token: int, backend: str, ttl_seconds: int, acquired_at: str
) -> str:
    """Digest the canonical, identity-bearing part of a scope-lock blob.

    Covers the fields that bind ownership and validity: scope, owning
    run, fencing token, backend, TTL and acquisition time. Binding both
    ``ttl_seconds`` and ``acquired_at`` makes the attested lock's
    lifetime — not just the age of the attestation — verifiable.
    """
    payload = {
        "scope_id": scope_id,
        "locked_by_run": locked_by_run,
        "fencing_token": fencing_token,
        "backend": backend,
        "ttl_seconds": ttl_seconds,
        "acquired_at": acquired_at,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decode_tsv_field(value: str) -> str:
    """Decode the TSV field convention of literal ``\\n`` as line breaks."""
    return value.replace("\\n", "\n")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 lowercase-hex digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp_expired(acquired_at: str, ttl_seconds: int) -> bool:
    """Return whether a UTC-``Z`` timestamp plus TTL lies in the past."""
    acquired = datetime.datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.UTC) > acquired + datetime.timedelta(seconds=ttl_seconds)


def canonical_tsv_subset_digest(header: str, rows: Sequence[str]) -> str:
    """Compute the canonical digest of a TSV row subset (module docstring)."""
    canonical = "\n".join([header, *sorted(rows)]) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


SOURCE_REGISTER_HEADER = (
    "source_id\tsource_phase\trole\tpath\tsha256\tround\tparticipant_id\tauthor_principal_id\tgenealogy_parents"
)
SOURCE_UNITS_HEADER = "unit_id\tsource_id\tunit_locator\tunit_digest\tclaim_refs\tempty_reason"
CLAIMS_INVENTORY_HEADER = "claim_id\tsource_id\tunit_refs\tsource_locator\tstatement\tqualifiers\tgenealogy_parents"


def _tsv_data_lines(path: Path, expected_header: str) -> tuple[list[str] | None, str | None]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"not readable as UTF-8 text: {exc}"
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != expected_header:
        return None, f"header must be exactly {expected_header!r}"
    return lines[1:], None


def _subset_pins(
    run_dir: Path, expected: dict[str, str | None], issues: list[Issue]
) -> None:
    register_rel = "baseline/source-register.tsv"
    register_path = run_dir / "baseline" / "source-register.tsv"
    if not register_path.is_file():
        return
    register_lines, register_error = _tsv_data_lines(register_path, SOURCE_REGISTER_HEADER)
    if register_lines is None:
        issues.append(Issue(locator=register_rel, message=register_error or "unreadable"))
        return
    expected["source_register_final"] = file_sha256(register_path)
    input_ids: set[str] = set()
    derived_ids: set[str] = set()
    input_rows: list[str] = []
    for line in register_lines:
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        if fields[1] == "input":
            input_ids.add(fields[0])
            input_rows.append(line)
        else:
            derived_ids.add(fields[0])
    expected["source_register_input"] = canonical_tsv_subset_digest(SOURCE_REGISTER_HEADER, input_rows)
    _units_pin(run_dir, expected, issues, input_ids)
    _claims_pins(run_dir, expected, issues, input_ids, derived_ids)


def _units_pin(run_dir: Path, expected: dict[str, str | None], issues: list[Issue], input_ids: set[str]) -> None:
    units_path = run_dir / "baseline" / "source-units.tsv"
    if not units_path.is_file():
        return
    unit_lines, unit_error = _tsv_data_lines(units_path, SOURCE_UNITS_HEADER)
    if unit_lines is None:
        issues.append(Issue(locator="baseline/source-units.tsv", message=unit_error or "unreadable"))
        return
    expected["source_units_final"] = file_sha256(units_path)
    selected = [line for line in unit_lines if len(line.split("\t")) > 1 and line.split("\t")[1] in input_ids]
    expected["source_units_input"] = canonical_tsv_subset_digest(SOURCE_UNITS_HEADER, selected)


def _claims_pins(
    run_dir: Path, expected: dict[str, str | None], issues: list[Issue], input_ids: set[str], derived_ids: set[str]
) -> None:
    claims_path = run_dir / "synthesis" / "claims-inventory.tsv"
    if not claims_path.is_file():
        return
    claim_lines, claim_error = _tsv_data_lines(claims_path, CLAIMS_INVENTORY_HEADER)
    if claim_lines is None:
        issues.append(Issue(locator="synthesis/claims-inventory.tsv", message=claim_error or "unreadable"))
        return
    input_rows = [line for line in claim_lines if len(line.split("\t")) > 1 and line.split("\t")[1] in input_ids]
    derived_rows = [line for line in claim_lines if len(line.split("\t")) > 1 and line.split("\t")[1] in derived_ids]
    expected["claims_inventory_input"] = canonical_tsv_subset_digest(CLAIMS_INVENTORY_HEADER, input_rows)
    expected["derived_claims"] = canonical_tsv_subset_digest(CLAIMS_INVENTORY_HEADER, derived_rows)


def derive_register_digests(run_dir: Path) -> tuple[dict[str, str | None], list[Issue]]:
    """Recompute the expected ``register_digests`` values from the run files.

    Whole-register pins (``corpus_baseline``, ``disposition_ledger``,
    ``source_register_final``, ``source_units_final``, ``atom_register``)
    are raw file digests; input/derived pins are canonical subset digests
    (module docstring). Keys whose backing files are absent stay ``None``;
    unreadable registers are reported as issues (locator = register path
    relative to the run directory).
    """
    expected: dict[str, str | None] = dict.fromkeys(REGISTER_DIGEST_KEYS)
    issues: list[Issue] = []
    for key, parts in (
        ("corpus_baseline", ("baseline", "corpus-baseline.tsv")),
        ("disposition_ledger", ("synthesis", "disposition-ledger.tsv")),
        ("atom_register", ("promotion", "atom-register.tsv")),
    ):
        file_path = run_dir.joinpath(*parts)
        if file_path.is_file():
            expected[key] = file_sha256(file_path)
    intake_path = run_dir / "baseline" / "source-intake.tsv"
    if intake_path.is_file():
        intake_rows, intake_issues = load_source_intake(intake_path)
        if intake_issues:
            issues.append(Issue(locator="baseline/source-intake.tsv", message="intake manifest is not contract-conform"))
        else:
            expected["source_intake_final_head"] = intake_head_digest(intake_rows)
            input_rows = [row for row in intake_rows if row["source_phase"] == "input"]
            expected["source_intake_input_head"] = intake_head_digest(input_rows)
    _subset_pins(run_dir, expected, issues)
    return expected, issues


# --------------------------------------------------------------------------
# JSON artifact models and loaders
# --------------------------------------------------------------------------


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


RUN_KEYS = (
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


def _parse_base_revision(ctx: _Ctx, obj: Mapping[str, object], where: str) -> BaseRevision:
    sub = _sub_obj(ctx, obj, where, "base_revision")
    if sub is None:
        return BaseRevision(kind="", value="")
    sub_where = f"{where}.base_revision"
    _keys(ctx, sub, sub_where, ("kind", "value"))
    return BaseRevision(kind=_enum(ctx, sub, sub_where, "kind", BASE_REVISION_KINDS), value=_str(ctx, sub, sub_where, "value"))


def _parse_actor(ctx: _Ctx, obj: Mapping[str, object], where: str) -> RunActor:
    sub = _sub_obj(ctx, obj, where, "actor")
    if sub is None:
        return RunActor(role="", harness="", model="", principal_id="", session_ref="")
    sub_where = f"{where}.actor"
    _keys(ctx, sub, sub_where, ("role", "harness", "model", "principal_id", "session_ref"))
    return RunActor(
        role=_str(ctx, sub, sub_where, "role"),
        harness=_str(ctx, sub, sub_where, "harness"),
        model=_str(ctx, sub, sub_where, "model"),
        principal_id=_matched(ctx, sub, sub_where, "principal_id", PRINCIPAL_ID_RE, "principal id"),
        session_ref=_str(ctx, sub, sub_where, "session_ref"),
    )


def _parse_data_release(ctx: _Ctx, obj: Mapping[str, object], where: str) -> DataRelease:
    sub = _sub_obj(ctx, obj, where, "data_release")
    if sub is None:
        return DataRelease(max_data_class="", source_ids=(), package_ids=(), approved_by_user=False)
    sub_where = f"{where}.data_release"
    _keys(ctx, sub, sub_where, ("max_data_class", "source_ids", "package_ids", "approved_by_user"))
    return DataRelease(
        max_data_class=_enum(ctx, sub, sub_where, "max_data_class", DATA_CLASSES),
        source_ids=_str_list(ctx, sub, sub_where, "source_ids", SOURCE_ID_RE, "source id"),
        package_ids=_str_list(ctx, sub, sub_where, "package_ids", PACKAGE_ID_RE, "package id"),
        approved_by_user=_bool(ctx, sub, sub_where, "approved_by_user"),
    )


def _parse_participants(ctx: _Ctx, obj: Mapping[str, object], where: str) -> tuple[Participant, ...]:
    participants: list[Participant] = []
    for item_where, item in _obj_items(ctx, obj, where, "participants"):
        expected = ("participant_id", "model", "backend", "spawn_mode", "principal_id", "session_ref", "data_release", "status")
        _keys(ctx, item, item_where, expected)
        participants.append(
            Participant(
                participant_id=_matched(ctx, item, item_where, "participant_id", PARTICIPANT_ID_RE, "participant id"),
                model=_str(ctx, item, item_where, "model"),
                backend=_str(ctx, item, item_where, "backend"),
                spawn_mode=_enum(ctx, item, item_where, "spawn_mode", SPAWN_MODES),
                principal_id=_matched(ctx, item, item_where, "principal_id", PRINCIPAL_ID_RE, "principal id"),
                session_ref=_opt_str(ctx, item, item_where, "session_ref"),
                data_release=_parse_data_release(ctx, item, item_where),
                status=_enum(ctx, item, item_where, "status", PARTICIPANT_STATUSES),
            )
        )
    return tuple(participants)


def _parse_register_digests(ctx: _Ctx, obj: Mapping[str, object], where: str) -> Mapping[str, str | None]:
    sub = _sub_obj(ctx, obj, where, "register_digests")
    if sub is None:
        return dict.fromkeys(REGISTER_DIGEST_KEYS)
    sub_where = f"{where}.register_digests"
    _keys(ctx, sub, sub_where, REGISTER_DIGEST_KEYS)
    return {key: _sha_or_null(ctx, sub, sub_where, key) for key in REGISTER_DIGEST_KEYS if key in sub}


def _parse_blocked(ctx: _Ctx, obj: Mapping[str, object], where: str) -> BlockedInfo | None:
    sub = _nullable_obj(ctx, obj, where, "blocked")
    if sub is None:
        return None
    sub_where = f"{where}.blocked"
    _keys(ctx, sub, sub_where, ("reason", "since_state"))
    return BlockedInfo(
        reason=_str(ctx, sub, sub_where, "reason"),
        since_state=_enum(ctx, sub, sub_where, "since_state", RUN_STATES),
    )


def _parse_recheck(ctx: _Ctx, obj: Mapping[str, object], where: str) -> RecheckInfo | None:
    sub = _nullable_obj(ctx, obj, where, "recheck")
    if sub is None:
        return None
    sub_where = f"{where}.recheck"
    _keys(ctx, sub, sub_where, ("drifted_paths", "detected_in_state"))
    return RecheckInfo(
        drifted_paths=_str_list(ctx, sub, sub_where, "drifted_paths"),
        detected_in_state=_enum(ctx, sub, sub_where, "detected_in_state", RUN_STATES),
    )


def load_run_state(path: Path) -> tuple[RunState | None, list[Issue]]:
    """Load and validate ``RUN.json`` fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "run", RUN_KEYS)
    run = RunState(
        schema_version=_semver(ctx, raw, "run"),
        run_id=_matched(ctx, raw, "run", "run_id", RUN_ID_RE, "run id"),
        title=_str(ctx, raw, "run", "title"),
        profile=_enum(ctx, raw, "run", "profile", RUN_PROFILES),
        state=_enum(ctx, raw, "run", "state", RUN_STATES),
        state_revision=_int(ctx, raw, "run", "state_revision", minimum=1),
        lease_fencing_token=_int(ctx, raw, "run", "lease_fencing_token", minimum=1),
        current_round=_int(ctx, raw, "run", "current_round", minimum=0),
        base_revision=_parse_base_revision(ctx, raw, "run"),
        data_class=_enum(ctx, raw, "run", "data_class", DATA_CLASSES),
        actor=_parse_actor(ctx, raw, "run"),
        participants=_parse_participants(ctx, raw, "run"),
        register_digests=_parse_register_digests(ctx, raw, "run"),
        blocked=_parse_blocked(ctx, raw, "run"),
        recheck=_parse_recheck(ctx, raw, "run"),
        last_completed_action=_matched(ctx, raw, "run", "last_completed_action", ACTION_ID_RE, "stable action id"),
        next_action=_matched(ctx, raw, "run", "next_action", ACTION_ID_RE, "stable action id"),
        updated_at=_time(ctx, raw, "run", "updated_at"),
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
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "lease", LEASE_KEYS)
    owner_obj = _sub_obj(ctx, raw, "lease", "owner")
    owner = LeaseOwner(principal_id="", harness="", session_ref="")
    if owner_obj is not None:
        _keys(ctx, owner_obj, "lease.owner", ("principal_id", "harness", "session_ref"))
        owner = LeaseOwner(
            principal_id=_matched(ctx, owner_obj, "lease.owner", "principal_id", PRINCIPAL_ID_RE, "principal id"),
            harness=_str(ctx, owner_obj, "lease.owner", "harness"),
            session_ref=_str(ctx, owner_obj, "lease.owner", "session_ref"),
        )
    lease = Lease(
        schema_version=_semver(ctx, raw, "lease"),
        run_id=_matched(ctx, raw, "lease", "run_id", RUN_ID_RE, "run id"),
        owner=owner,
        fencing_token=_int(ctx, raw, "lease", "fencing_token", minimum=1),
        acquired_at=_time(ctx, raw, "lease", "acquired_at"),
        ttl_seconds=_int(ctx, raw, "lease", "ttl_seconds", minimum=1),
        released=_bool(ctx, raw, "lease", "released"),
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


def _parse_round_participant(ctx: _Ctx, item_where: str, item: Mapping[str, object]) -> RoundParticipant:
    _keys(ctx, item, item_where, ("participant_id", "dispatch", "receipt", "outcome", "outcome_reason"))
    dispatch_obj = _sub_obj(ctx, item, item_where, "dispatch")
    dispatch = RoundDispatch(sent_at="", prompt_digest="", input_digests=())
    if dispatch_obj is not None:
        dispatch_where = f"{item_where}.dispatch"
        _keys(ctx, dispatch_obj, dispatch_where, ("sent_at", "prompt_digest", "input_digests"))
        dispatch = RoundDispatch(
            sent_at=_time(ctx, dispatch_obj, dispatch_where, "sent_at"),
            prompt_digest=_sha(ctx, dispatch_obj, dispatch_where, "prompt_digest"),
            input_digests=_str_list(ctx, dispatch_obj, dispatch_where, "input_digests", SHA256_RE, "sha256 digest"),
        )
    receipt_obj = _nullable_obj(ctx, item, item_where, "receipt")
    receipt: RoundReceipt | None = None
    if receipt_obj is not None:
        receipt_where = f"{item_where}.receipt"
        _keys(ctx, receipt_obj, receipt_where, ("received_at", "proposal_digest"))
        receipt = RoundReceipt(
            received_at=_time(ctx, receipt_obj, receipt_where, "received_at"),
            proposal_digest=_sha(ctx, receipt_obj, receipt_where, "proposal_digest"),
        )
    outcome = _enum(ctx, item, item_where, "outcome", ROUND_OUTCOMES)
    outcome_reason = _str(ctx, item, item_where, "outcome_reason", allow_empty=True)
    if outcome and outcome != "received" and not outcome_reason:
        ctx.error(f"{item_where}.outcome_reason", f"required for outcome {outcome!r}")
    if outcome == "received" and receipt is None:
        ctx.error(f"{item_where}.receipt", "required for outcome 'received'")
    return RoundParticipant(
        participant_id=_matched(ctx, item, item_where, "participant_id", PARTICIPANT_ID_RE, "participant id"),
        dispatch=dispatch,
        receipt=receipt,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )


def _parse_round_seal(ctx: _Ctx, raw: Mapping[str, object], sealed: bool) -> RoundSeal | None:
    seal_obj = _nullable_obj(ctx, raw, "round", "seal")
    if seal_obj is None:
        if sealed:
            ctx.error("round.seal", "required when sealed is true")
        return None
    if not sealed:
        ctx.error("round.seal", "must be null when sealed is false")
    _keys(ctx, seal_obj, "round.seal", ("sealed_at", "sealed_proposal_digests"))
    digests_obj = _sub_obj(ctx, seal_obj, "round.seal", "sealed_proposal_digests")
    digests: dict[str, str] = {}
    if digests_obj is not None:
        for participant_id, digest in digests_obj.items():
            where = f"round.seal.sealed_proposal_digests.{participant_id}"
            if PARTICIPANT_ID_RE.fullmatch(participant_id) is None:
                ctx.error(where, "key must be a participant id")
            if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
                ctx.error(where, "must be a sha256 lowercase-hex digest")
                continue
            digests[participant_id] = digest
    return RoundSeal(sealed_at=_time(ctx, seal_obj, "round.seal", "sealed_at"), sealed_proposal_digests=digests)


def load_round_state(path: Path) -> tuple[RoundState | None, list[Issue]]:
    """Load and validate one ``ROUND.json`` fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "round", ROUND_KEYS)
    sealed = _bool(ctx, raw, "round", "sealed")
    round_state = RoundState(
        schema_version=_semver(ctx, raw, "round"),
        run_id=_matched(ctx, raw, "round", "run_id", RUN_ID_RE, "run id"),
        round=_int(ctx, raw, "round", "round", minimum=1),
        participants=tuple(
            _parse_round_participant(ctx, where, item) for where, item in _obj_items(ctx, raw, "round", "participants")
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
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "plan", COVERAGE_PLAN_KEYS)
    packages: list[CoveragePackage] = []
    for item_where, item in _obj_items(ctx, raw, "plan", "packages"):
        _keys(ctx, item, item_where, ("package_id", "description", "paths", "assigned_participants", "redundancy"))
        packages.append(
            CoveragePackage(
                package_id=_matched(ctx, item, item_where, "package_id", PACKAGE_ID_RE, "package id"),
                description=_str(ctx, item, item_where, "description"),
                paths=_str_list(ctx, item, item_where, "paths"),
                assigned_participants=_str_list(
                    ctx, item, item_where, "assigned_participants", PARTICIPANT_ID_RE, "participant id"
                ),
                redundancy=_int(ctx, item, item_where, "redundancy", minimum=1),
            )
        )
    plan = CoveragePlan(
        schema_version=_semver(ctx, raw, "plan"),
        run_id=_matched(ctx, raw, "plan", "run_id", RUN_ID_RE, "run id"),
        packages=tuple(packages),
        integration_package_id=_matched(ctx, raw, "plan", "integration_package_id", PACKAGE_ID_RE, "package id"),
    )
    if ctx.issues:
        return None, ctx.issues
    return plan, []


@dataclass(frozen=True)
class ScopeBlocker:
    """One blocker entry of a promotion scope."""

    reason: str
    atom_ids: tuple[str, ...]
    owner: str
    visible_anchor: str


@dataclass(frozen=True)
class PromotionScope:
    """One scope entry of the promotion manifest."""

    scope_id: str
    promotion_disposition: str
    blockers: tuple[ScopeBlocker, ...]


@dataclass(frozen=True)
class RegistryEdge:
    """One required registry edge in object form.

    ``required_registry_edges`` entries come in two normalized forms: the
    structural object ``{from, to, kind}`` or a plain ``<path>#<anchor>``
    string that must resolve against the working tree.
    """

    from_ref: str
    to_ref: str
    kind: str


@dataclass(frozen=True)
class TestOracle:
    """One required test oracle (structural validation only)."""

    oracle_id: str
    kind: str
    locator: str


@dataclass(frozen=True)
class PromotionTarget:
    """One target file with before/after digest binding."""

    path: str
    before_sha256: str | None
    after_sha256: str


@dataclass(frozen=True)
class ScopeLockEntry:
    """One scope-lock claim recorded in the promotion manifest."""

    scope_id: str
    locked_by_run: str
    fencing_token: int
    backend: str


@dataclass(frozen=True)
class SemanticGateEntry:
    """Recorded state of one semantic gate (W2/W3)."""

    gate: str
    status: str
    receipt_path: str | None
    blocking_scope_ids: tuple[str, ...]


@dataclass(frozen=True)
class PromotionManifest:
    """Validated ``promotion/promotion-manifest.json`` (FK-78 section 78.11)."""

    schema_version: str
    run_id: str
    base_revision: BaseRevision
    scopes: tuple[PromotionScope, ...]
    required_decision_ids: tuple[str, ...]
    required_concept_ids: tuple[str, ...]
    required_formal_ids: tuple[str, ...]
    required_registry_edges: tuple[RegistryEdge | str, ...]
    required_support_paths: tuple[str, ...]
    required_test_oracles: tuple[TestOracle, ...]
    targets: tuple[PromotionTarget, ...]
    receipts_dir: str
    scope_locks: tuple[ScopeLockEntry, ...]
    semantic_gates: tuple[SemanticGateEntry, ...]


MANIFEST_KEYS = (
    "schema_version",
    "run_id",
    "base_revision",
    "scopes",
    "required_decision_ids",
    "required_concept_ids",
    "required_formal_ids",
    "required_registry_edges",
    "required_support_paths",
    "required_test_oracles",
    "targets",
    "receipts_dir",
    "scope_locks",
    "semantic_gates",
)


def _parse_scopes(ctx: _Ctx, raw: Mapping[str, object]) -> tuple[PromotionScope, ...]:
    scopes: list[PromotionScope] = []
    for item_where, item in _obj_items(ctx, raw, "manifest", "scopes"):
        _keys(ctx, item, item_where, ("scope_id", "promotion_disposition", "blockers"))
        blockers: list[ScopeBlocker] = []
        for blocker_where, blocker in _obj_items(ctx, item, item_where, "blockers"):
            _keys(ctx, blocker, blocker_where, ("reason", "atom_ids", "owner", "visible_anchor"))
            blockers.append(
                ScopeBlocker(
                    reason=_str(ctx, blocker, blocker_where, "reason"),
                    atom_ids=_str_list(ctx, blocker, blocker_where, "atom_ids", ATOM_ID_RE, "atom id"),
                    owner=_str(ctx, blocker, blocker_where, "owner"),
                    visible_anchor=_str(ctx, blocker, blocker_where, "visible_anchor"),
                )
            )
        scopes.append(
            PromotionScope(
                scope_id=_str(ctx, item, item_where, "scope_id"),
                promotion_disposition=_enum(ctx, item, item_where, "promotion_disposition", PROMOTION_DISPOSITIONS),
                blockers=tuple(blockers),
            )
        )
    return tuple(scopes)


def _parse_registry_edges(ctx: _Ctx, raw: Mapping[str, object]) -> tuple[RegistryEdge | str, ...]:
    if "required_registry_edges" not in raw:
        return ()
    value = raw["required_registry_edges"]
    if not isinstance(value, list):
        ctx.error("manifest.required_registry_edges", "must be an array")
        return ()
    edges: list[RegistryEdge | str] = []
    for index, item in enumerate(value):
        item_where = f"manifest.required_registry_edges[{index}]"
        if isinstance(item, str):
            if "#" not in item or item.startswith("#") or item.endswith("#"):
                ctx.error(item_where, f"string form must be <path>#<anchor>, got {item!r}")
                continue
            edges.append(item)
            continue
        if not isinstance(item, dict):
            ctx.error(item_where, "must be a <path>#<anchor> string or a {from, to, kind} object")
            continue
        _keys(ctx, item, item_where, ("from", "to", "kind"))
        edges.append(
            RegistryEdge(
                from_ref=_str(ctx, item, item_where, "from"),
                to_ref=_str(ctx, item, item_where, "to"),
                kind=_str(ctx, item, item_where, "kind"),
            )
        )
    return tuple(edges)


def _parse_manifest_collections(
    ctx: _Ctx, raw: Mapping[str, object]
) -> tuple[tuple[RegistryEdge | str, ...], tuple[TestOracle, ...], tuple[PromotionTarget, ...], tuple[ScopeLockEntry, ...]]:
    edges = _parse_registry_edges(ctx, raw)
    oracles: list[TestOracle] = []
    for item_where, item in _obj_items(ctx, raw, "manifest", "required_test_oracles"):
        _keys(ctx, item, item_where, ("oracle_id", "kind", "locator"))
        oracles.append(
            TestOracle(
                oracle_id=_str(ctx, item, item_where, "oracle_id"),
                kind=_str(ctx, item, item_where, "kind"),
                locator=_str(ctx, item, item_where, "locator"),
            )
        )
    targets: list[PromotionTarget] = []
    for item_where, item in _obj_items(ctx, raw, "manifest", "targets"):
        _keys(ctx, item, item_where, ("path", "before_sha256", "after_sha256"))
        before = _sha_or_null(ctx, item, item_where, "before_sha256")
        targets.append(
            PromotionTarget(
                path=_str(ctx, item, item_where, "path"),
                before_sha256=before,
                after_sha256=_sha(ctx, item, item_where, "after_sha256"),
            )
        )
    locks: list[ScopeLockEntry] = []
    for item_where, item in _obj_items(ctx, raw, "manifest", "scope_locks"):
        _keys(ctx, item, item_where, ("scope_id", "locked_by_run", "fencing_token", "backend"))
        locks.append(
            ScopeLockEntry(
                scope_id=_str(ctx, item, item_where, "scope_id"),
                locked_by_run=_matched(ctx, item, item_where, "locked_by_run", RUN_ID_RE, "run id"),
                fencing_token=_int(ctx, item, item_where, "fencing_token", minimum=1),
                backend=_enum(ctx, item, item_where, "backend", LOCK_BACKENDS),
            )
        )
    return tuple(edges), tuple(oracles), tuple(targets), tuple(locks)


def _parse_semantic_gates(ctx: _Ctx, raw: Mapping[str, object]) -> tuple[SemanticGateEntry, ...]:
    gates: list[SemanticGateEntry] = []
    for item_where, item in _obj_items(ctx, raw, "manifest", "semantic_gates"):
        _keys(ctx, item, item_where, ("gate", "status", "receipt_path", "blocking_scope_ids"))
        gates.append(
            SemanticGateEntry(
                gate=_enum(ctx, item, item_where, "gate", SEMANTIC_GATES),
                status=_enum(ctx, item, item_where, "status", SEMANTIC_GATE_STATUSES),
                receipt_path=_opt_str(ctx, item, item_where, "receipt_path"),
                blocking_scope_ids=_str_list(ctx, item, item_where, "blocking_scope_ids"),
            )
        )
    return tuple(gates)


def load_promotion_manifest(path: Path) -> tuple[PromotionManifest | None, list[Issue]]:
    """Load and validate the promotion manifest fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "manifest", MANIFEST_KEYS)
    edges, oracles, targets, locks = _parse_manifest_collections(ctx, raw)
    manifest = PromotionManifest(
        schema_version=_semver(ctx, raw, "manifest"),
        run_id=_matched(ctx, raw, "manifest", "run_id", RUN_ID_RE, "run id"),
        base_revision=_parse_base_revision(ctx, raw, "manifest"),
        scopes=_parse_scopes(ctx, raw),
        required_decision_ids=_str_list(ctx, raw, "manifest", "required_decision_ids"),
        required_concept_ids=_str_list(ctx, raw, "manifest", "required_concept_ids"),
        required_formal_ids=_str_list(ctx, raw, "manifest", "required_formal_ids"),
        required_registry_edges=edges,
        required_support_paths=_str_list(ctx, raw, "manifest", "required_support_paths"),
        required_test_oracles=oracles,
        targets=targets,
        receipts_dir=_str(ctx, raw, "manifest", "receipts_dir"),
        scope_locks=locks,
        semantic_gates=_parse_semantic_gates(ctx, raw),
    )
    if ctx.issues:
        return None, ctx.issues
    return manifest, []


@dataclass(frozen=True)
class ReceiptTarget:
    """Target passage of a projection receipt.

    ``anchor`` is empty for whole-file and directory targets; markdown
    section receipts always carry the section anchor.
    """

    path: str
    anchor: str


@dataclass(frozen=True)
class ProjectionReceipt:
    """Validated ``promotion/receipts/<receipt_id>.json`` (FK-78 78.10)."""

    schema_version: str
    receipt_id: str
    atom_id: str
    target: ReceiptTarget
    target_mode: str
    selector: str | None
    source_digest: str
    target_section_digest: str
    writer_principal_id: str
    writer_session_ref: str
    reviewer_principal_id: str
    reviewer_session_ref: str
    verdict: str
    reviewed_at: str


RECEIPT_KEYS = (
    "schema_version",
    "receipt_id",
    "atom_id",
    "target",
    "target_mode",
    "selector",
    "source_digest",
    "target_section_digest",
    "writer_principal_id",
    "writer_session_ref",
    "reviewer_principal_id",
    "reviewer_session_ref",
    "verdict",
    "reviewed_at",
)


def load_projection_receipt(path: Path) -> tuple[ProjectionReceipt | None, list[Issue]]:
    """Load and validate one projection receipt fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "receipt", RECEIPT_KEYS)
    target_obj = _sub_obj(ctx, raw, "receipt", "target")
    target = ReceiptTarget(path="", anchor="")
    if target_obj is not None:
        _keys(ctx, target_obj, "receipt.target", ("path", "anchor"))
        target = ReceiptTarget(
            path=_str(ctx, target_obj, "receipt.target", "path"),
            anchor=_str(ctx, target_obj, "receipt.target", "anchor", allow_empty=True),
        )
    mode = _enum(ctx, raw, "receipt", "target_mode", TARGET_MODES)
    selector = _opt_str(ctx, raw, "receipt", "selector")
    if mode == "structured-selector" and not selector:
        ctx.error("receipt.selector", "required for target_mode 'structured-selector'")
    if mode and mode != "structured-selector" and selector:
        ctx.error("receipt.selector", f"only allowed for target_mode 'structured-selector', not {mode!r}")
    if mode == "markdown-section" and not target.anchor:
        ctx.error("receipt.target.anchor", "required for target_mode 'markdown-section'")
    if mode in ("whole-file", "directory-tree") and target.anchor:
        ctx.error("receipt.target.anchor", f"must be empty for target_mode {mode!r}")
    receipt = ProjectionReceipt(
        schema_version=_semver(ctx, raw, "receipt"),
        receipt_id=_matched(ctx, raw, "receipt", "receipt_id", RECEIPT_ID_RE, "receipt id"),
        atom_id=_matched(ctx, raw, "receipt", "atom_id", ATOM_ID_RE, "atom id"),
        target=target,
        target_mode=mode,
        selector=selector,
        source_digest=_sha(ctx, raw, "receipt", "source_digest"),
        target_section_digest=_sha(ctx, raw, "receipt", "target_section_digest"),
        writer_principal_id=_matched(ctx, raw, "receipt", "writer_principal_id", PRINCIPAL_ID_RE, "principal id"),
        writer_session_ref=_str(ctx, raw, "receipt", "writer_session_ref"),
        reviewer_principal_id=_matched(ctx, raw, "receipt", "reviewer_principal_id", PRINCIPAL_ID_RE, "principal id"),
        reviewer_session_ref=_str(ctx, raw, "receipt", "reviewer_session_ref"),
        verdict=_enum(ctx, raw, "receipt", "verdict", RECEIPT_VERDICTS),
        reviewed_at=_time(ctx, raw, "receipt", "reviewed_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []


@dataclass(frozen=True)
class DeclassificationReceipt:
    """Validated ``declassification/<receipt_id>.json`` (FK-78 78.13)."""

    schema_version: str
    receipt_id: str
    source_path: str
    source_digest: str
    output_path: str
    output_digest: str
    rules_applied: tuple[str, ...]
    target_class: str
    approved_by_principal: str
    approved_at: str


DECLASSIFICATION_KEYS = (
    "schema_version",
    "receipt_id",
    "source_path",
    "source_digest",
    "output_path",
    "output_digest",
    "rules_applied",
    "target_class",
    "approved_by_principal",
    "approved_at",
)


def load_declassification_receipt(path: Path) -> tuple[DeclassificationReceipt | None, list[Issue]]:
    """Load and validate one declassification receipt fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "receipt", DECLASSIFICATION_KEYS)
    receipt = DeclassificationReceipt(
        schema_version=_semver(ctx, raw, "receipt"),
        receipt_id=_matched(ctx, raw, "receipt", "receipt_id", RECEIPT_ID_RE, "receipt id"),
        source_path=_str(ctx, raw, "receipt", "source_path"),
        source_digest=_sha(ctx, raw, "receipt", "source_digest"),
        output_path=_str(ctx, raw, "receipt", "output_path"),
        output_digest=_sha(ctx, raw, "receipt", "output_digest"),
        rules_applied=_str_list(ctx, raw, "receipt", "rules_applied"),
        target_class=_enum(ctx, raw, "receipt", "target_class", ("open", "internal")),
        approved_by_principal=_matched(ctx, raw, "receipt", "approved_by_principal", PRINCIPAL_ID_RE, "principal id"),
        approved_at=_time(ctx, raw, "receipt", "approved_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []


MUTEX_KEYS = ("owner_principal", "owner_session", "nonce", "acquired_at", "heartbeat_at", "ttl_seconds")

INTENT_KEYS = ("holder_principal", "holder_session", "intent_nonce", "acquired_at", "ttl_seconds")


@dataclass(frozen=True)
class IntentState:
    """Validated ``RUN.mutex.intent`` payload (coordination intent, FK-78 78.4).

    One single intent serializes EVERY mutex change and effect (acquire,
    takeover, heartbeat, write, release). It carries its own nonce so it
    can only be released by its holder (compare-before-delete).
    """

    holder_principal: str
    holder_session: str
    intent_nonce: str
    acquired_at: str
    ttl_seconds: int


def load_intent_state(path: Path) -> tuple[IntentState | None, list[Issue]]:
    """Load and validate the coordination-intent payload fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "intent", INTENT_KEYS)
    state = IntentState(
        holder_principal=_matched(ctx, raw, "intent", "holder_principal", PRINCIPAL_ID_RE, "principal id"),
        holder_session=_str(ctx, raw, "intent", "holder_session"),
        intent_nonce=_str(ctx, raw, "intent", "intent_nonce"),
        acquired_at=_time(ctx, raw, "intent", "acquired_at"),
        ttl_seconds=_int(ctx, raw, "intent", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return state, []


def parse_timestamp(value: str) -> datetime.datetime:
    """Parse a UTC-``Z`` timestamp into an aware datetime."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def now_utc() -> datetime.datetime:
    """Return the current UTC time (single seam for time-ordering checks)."""
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class MutexState:
    """Validated ``RUN.mutex`` payload (mutation mutex, FK-78 section 78.4).

    Liveness is measured against ``heartbeat_at``, which long operations
    refresh before every write step, so a legitimate long run is never
    taken over as if it had crashed.
    """

    owner_principal: str
    owner_session: str
    nonce: str
    acquired_at: str
    heartbeat_at: str
    ttl_seconds: int


def load_mutex_state(path: Path) -> tuple[MutexState | None, list[Issue]]:
    """Load and validate the mutation-mutex payload fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "mutex", MUTEX_KEYS)
    state = MutexState(
        owner_principal=_matched(ctx, raw, "mutex", "owner_principal", PRINCIPAL_ID_RE, "principal id"),
        owner_session=_str(ctx, raw, "mutex", "owner_session"),
        nonce=_str(ctx, raw, "mutex", "nonce"),
        acquired_at=_time(ctx, raw, "mutex", "acquired_at"),
        heartbeat_at=_time(ctx, raw, "mutex", "heartbeat_at"),
        ttl_seconds=_int(ctx, raw, "mutex", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return state, []


SCOPE_LOCK_KEYS = ("schema_version", "scope_id", "locked_by_run", "fencing_token", "backend", "acquired_at", "ttl_seconds")


@dataclass(frozen=True)
class ScopeLock:
    """Validated filesystem scope-lock blob (FK-78 section 78.11).

    FK-78 fixes the lock semantics (owner run, fencing token, TTL); this
    catalog is the toolchain's normative JSON materialization of it.
    """

    schema_version: str
    scope_id: str
    locked_by_run: str
    fencing_token: int
    backend: str
    acquired_at: str
    ttl_seconds: int


def load_scope_lock(path: Path) -> tuple[ScopeLock | None, list[Issue]]:
    """Load and validate one scope-lock blob fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "lock", SCOPE_LOCK_KEYS)
    lock = ScopeLock(
        schema_version=_semver(ctx, raw, "lock"),
        scope_id=_str(ctx, raw, "lock", "scope_id"),
        locked_by_run=_matched(ctx, raw, "lock", "locked_by_run", RUN_ID_RE, "run id"),
        fencing_token=_int(ctx, raw, "lock", "fencing_token", minimum=1),
        backend=_enum(ctx, raw, "lock", "backend", LOCK_BACKENDS),
        acquired_at=_time(ctx, raw, "lock", "acquired_at"),
        ttl_seconds=_int(ctx, raw, "lock", "ttl_seconds", minimum=1),
    )
    if ctx.issues:
        return None, ctx.issues
    return lock, []


LOCK_EVIDENCE_KEYS = ("schema_version", "backend", "remote", "refs")

LOCK_EVIDENCE_REF_KEYS = (
    "scope_id",
    "ref",
    "expected_ref",
    "old_oid",
    "new_oid",
    "observed_oid",
    "lock_blob_digest",
    "fencing_token",
    "ttl_seconds",
    "acquired_at",
    "attested_by_principal",
    "attested_by_session",
    "verified_at",
)

_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


@dataclass(frozen=True)
class LockEvidenceRef:
    """One verified git-remote lock ref (orchestrator-side CAS evidence)."""

    scope_id: str
    ref: str
    expected_ref: str
    old_oid: str
    new_oid: str
    observed_oid: str
    lock_blob_digest: str
    fencing_token: int
    ttl_seconds: int
    acquired_at: str
    attested_by_principal: str
    attested_by_session: str
    verified_at: str


@dataclass(frozen=True)
class LockEvidence:
    """Validated ``promotion/lock-evidence.json`` for the git-remote backend.

    The toolchain performs no network operations; the orchestrator records
    its ref-CAS verification here (one entry per locked scope), which the
    promotion check accepts as completing evidence.
    """

    schema_version: str
    backend: str
    remote: str
    refs: tuple[LockEvidenceRef, ...]


def load_lock_evidence(path: Path) -> tuple[LockEvidence | None, list[Issue]]:
    """Load and validate one git-remote lock-evidence file fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "evidence", LOCK_EVIDENCE_KEYS)
    refs: list[LockEvidenceRef] = []
    for item_where, item in _obj_items(ctx, raw, "evidence", "refs"):
        _keys(ctx, item, item_where, LOCK_EVIDENCE_REF_KEYS)
        ref_name = _str(ctx, item, item_where, "ref")
        if ref_name and not ref_name.startswith("refs/"):
            ctx.error(f"{item_where}.ref", f"must be a fully qualified ref name, got {ref_name!r}")
        expected_ref = _str(ctx, item, item_where, "expected_ref")
        if expected_ref and not expected_ref.startswith("refs/"):
            ctx.error(f"{item_where}.expected_ref", f"must be a fully qualified ref name, got {expected_ref!r}")
        refs.append(
            LockEvidenceRef(
                scope_id=_str(ctx, item, item_where, "scope_id"),
                ref=ref_name,
                expected_ref=expected_ref,
                old_oid=_matched(ctx, item, item_where, "old_oid", _GIT_OID_RE, "git object id"),
                new_oid=_matched(ctx, item, item_where, "new_oid", _GIT_OID_RE, "git object id"),
                observed_oid=_matched(ctx, item, item_where, "observed_oid", _GIT_OID_RE, "git object id"),
                lock_blob_digest=_sha(ctx, item, item_where, "lock_blob_digest"),
                fencing_token=_int(ctx, item, item_where, "fencing_token", minimum=1),
                ttl_seconds=_int(ctx, item, item_where, "ttl_seconds", minimum=1),
                acquired_at=_time(ctx, item, item_where, "acquired_at"),
                attested_by_principal=_matched(
                    ctx, item, item_where, "attested_by_principal", PRINCIPAL_ID_RE, "principal id"
                ),
                attested_by_session=_str(ctx, item, item_where, "attested_by_session"),
                verified_at=_time(ctx, item, item_where, "verified_at"),
            )
        )
    evidence = LockEvidence(
        schema_version=_semver(ctx, raw, "evidence"),
        backend=_enum(ctx, raw, "evidence", "backend", ("git-remote",)),
        remote=_str(ctx, raw, "evidence", "remote"),
        refs=tuple(refs),
    )
    if ctx.issues:
        return None, ctx.issues
    return evidence, []


@dataclass(frozen=True)
class LifecycleSource:
    """Decision-record binding of a projection-manifest entry."""

    decision_id: str
    path: str
    digest: str
    status: str


@dataclass(frozen=True)
class AssertionSource:
    """Assertion source document with digest binding."""

    path: str
    digest: str | None


@dataclass(frozen=True)
class RequiredProjection:
    """One declared mandatory projection of a scope.

    ``target_mode`` selects the canonical digest rule (see
    :mod:`receipts`); ``selector`` is required for and only allowed with
    ``structured-selector``.
    """

    kind: str
    target: str
    target_mode: str
    selector: str | None
    target_digest: str | None
    receipt_ref: str | None
    equivalence_status: str


@dataclass(frozen=True)
class ProjectionBlocker:
    """One visible blocker of a projection-manifest entry."""

    reason: str
    owner: str
    visible_anchor: str


@dataclass(frozen=True)
class ManifestRef:
    """Digest-bound reference to a promotion manifest."""

    path: str
    digest: str


@dataclass(frozen=True)
class ProjectionEntry:
    """One scope entry of the corpus-wide projection manifest (FK-78 78.12)."""

    scope_id: str
    covered_scope_ids: tuple[str, ...]
    lifecycle: str
    lifecycle_source: LifecycleSource
    assertion_source: AssertionSource
    assertion_status: str
    required_projections: tuple[RequiredProjection, ...]
    blockers: tuple[ProjectionBlocker, ...]
    last_run_id: str | None
    last_promotion_manifest: ManifestRef | None
    raw: Mapping[str, object] = field(repr=False)


@dataclass(frozen=True)
class ProjectionManifest:
    """Validated ``concept/_meta/projection-manifest.json``."""

    schema_version: str
    entries: tuple[ProjectionEntry, ...]


PROJECTION_MANIFEST_KEYS = ("schema_version", "entries")

REQUIRED_PROJECTION_KEYS = ("kind", "target", "target_mode", "target_digest", "receipt_ref", "equivalence_status")

#: Canonical digest rules for projection targets (see :mod:`receipts`).
TARGET_MODES = ("markdown-section", "whole-file", "structured-selector", "directory-tree")

#: Declared relation kinds of structured ``required_registry_edges``.
REGISTRY_EDGE_KINDS = ("owns", "defers_to", "contract", "member", "producer", "consumer")

PROJECTION_ENTRY_KEYS = (
    "scope_id",
    "lifecycle",
    "lifecycle_source",
    "assertion_source",
    "assertion_status",
    "required_projections",
    "blockers",
    "last_run_id",
    "last_promotion_manifest",
)


def _parse_lifecycle_source(ctx: _Ctx, entry: Mapping[str, object], where: str) -> LifecycleSource:
    sub = _sub_obj(ctx, entry, where, "lifecycle_source")
    if sub is None:
        return LifecycleSource(decision_id="", path="", digest="", status="")
    sub_where = f"{where}.lifecycle_source"
    _keys(ctx, sub, sub_where, ("decision_id", "path", "digest", "status"))
    return LifecycleSource(
        decision_id=_str(ctx, sub, sub_where, "decision_id"),
        path=_str(ctx, sub, sub_where, "path"),
        digest=_sha(ctx, sub, sub_where, "digest"),
        status=_enum(ctx, sub, sub_where, "status", DECISION_STATUSES),
    )


def _parse_projection_entry(ctx: _Ctx, item_where: str, item: dict[str, object]) -> ProjectionEntry:
    _keys(ctx, item, item_where, PROJECTION_ENTRY_KEYS, optional=("covered_scope_ids",))
    source_obj = _sub_obj(ctx, item, item_where, "assertion_source")
    assertion_source = AssertionSource(path="", digest=None)
    if source_obj is not None:
        source_where = f"{item_where}.assertion_source"
        _keys(ctx, source_obj, source_where, ("path", "digest"))
        assertion_source = AssertionSource(
            path=_str(ctx, source_obj, source_where, "path"),
            digest=_sha_or_null(ctx, source_obj, source_where, "digest"),
        )
    projections: list[RequiredProjection] = []
    for proj_where, proj in _obj_items(ctx, item, item_where, "required_projections"):
        _keys(ctx, proj, proj_where, REQUIRED_PROJECTION_KEYS, optional=("selector",))
        mode = _enum(ctx, proj, proj_where, "target_mode", TARGET_MODES)
        selector = _opt_str(ctx, proj, proj_where, "selector")
        if mode == "structured-selector" and not selector:
            ctx.error(f"{proj_where}.selector", "required for target_mode 'structured-selector'")
        if mode and mode != "structured-selector" and selector:
            ctx.error(f"{proj_where}.selector", f"only allowed for target_mode 'structured-selector', not {mode!r}")
        projections.append(
            RequiredProjection(
                kind=_enum(ctx, proj, proj_where, "kind", PROJECTION_KINDS),
                target=_str(ctx, proj, proj_where, "target"),
                target_mode=mode,
                selector=selector,
                target_digest=_sha_or_null(ctx, proj, proj_where, "target_digest"),
                receipt_ref=_opt_str(ctx, proj, proj_where, "receipt_ref"),
                equivalence_status=_enum(ctx, proj, proj_where, "equivalence_status", EQUIVALENCE_STATUSES),
            )
        )
    blockers: list[ProjectionBlocker] = []
    for blocker_where, blocker in _obj_items(ctx, item, item_where, "blockers"):
        _keys(ctx, blocker, blocker_where, ("reason", "owner", "visible_anchor"))
        blockers.append(
            ProjectionBlocker(
                reason=_str(ctx, blocker, blocker_where, "reason"),
                owner=_str(ctx, blocker, blocker_where, "owner"),
                visible_anchor=_str(ctx, blocker, blocker_where, "visible_anchor"),
            )
        )
    manifest_ref_obj = _nullable_obj(ctx, item, item_where, "last_promotion_manifest")
    manifest_ref: ManifestRef | None = None
    if manifest_ref_obj is not None:
        ref_where = f"{item_where}.last_promotion_manifest"
        _keys(ctx, manifest_ref_obj, ref_where, ("path", "digest"))
        manifest_ref = ManifestRef(
            path=_str(ctx, manifest_ref_obj, ref_where, "path"),
            digest=_sha(ctx, manifest_ref_obj, ref_where, "digest"),
        )
    last_run_id = _opt_str(ctx, item, item_where, "last_run_id")
    if last_run_id is not None and RUN_ID_RE.fullmatch(last_run_id) is None:
        ctx.error(f"{item_where}.last_run_id", f"must be a run id or null, got {last_run_id!r}")
    return ProjectionEntry(
        scope_id=_str(ctx, item, item_where, "scope_id"),
        covered_scope_ids=_str_list(ctx, item, item_where, "covered_scope_ids"),
        lifecycle=_enum(ctx, item, item_where, "lifecycle", LIFECYCLES),
        lifecycle_source=_parse_lifecycle_source(ctx, item, item_where),
        assertion_source=assertion_source,
        assertion_status=_enum(ctx, item, item_where, "assertion_status", ASSERTION_STATUSES),
        required_projections=tuple(projections),
        blockers=tuple(blockers),
        last_run_id=last_run_id,
        last_promotion_manifest=manifest_ref,
        raw=item,
    )


def load_projection_manifest(path: Path) -> tuple[ProjectionManifest | None, list[Issue]]:
    """Load and validate the corpus-wide projection manifest fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "manifest", PROJECTION_MANIFEST_KEYS)
    entries = tuple(_parse_projection_entry(ctx, where, item) for where, item in _obj_items(ctx, raw, "manifest", "entries"))
    manifest = ProjectionManifest(schema_version=_semver(ctx, raw, "manifest"), entries=entries)
    if ctx.issues:
        return None, ctx.issues
    return manifest, []


@dataclass(frozen=True)
class SemanticChunk:
    """One ordered content chunk of a semantic request pack."""

    path: str
    locator: str
    digest: str


REQUEST_PACK_KEYS = (
    "schema_version",
    "gate",
    "scope_id",
    "base_revision",
    "template_id",
    "template_digest",
    "chunks",
    "request_digest",
)


@dataclass(frozen=True)
class SemanticRequestPack:
    """Validated semantic request pack (FK-78 section 78.14)."""

    schema_version: str
    gate: str
    scope_id: str
    base_revision: BaseRevision
    template_id: str
    template_digest: str
    chunks: tuple[SemanticChunk, ...]
    request_digest: str


def load_semantic_request_pack(path: Path) -> tuple[SemanticRequestPack | None, list[Issue]]:
    """Load and validate one semantic request pack fail-closed.

    Also recomputes the canonical ``request_digest`` and fails on mismatch.
    """
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "pack", REQUEST_PACK_KEYS)
    chunks: list[SemanticChunk] = []
    for item_where, item in _obj_items(ctx, raw, "pack", "chunks"):
        _keys(ctx, item, item_where, ("path", "locator", "digest"))
        chunks.append(
            SemanticChunk(
                path=_str(ctx, item, item_where, "path"),
                locator=_str(ctx, item, item_where, "locator"),
                digest=_sha(ctx, item, item_where, "digest"),
            )
        )
    pack = SemanticRequestPack(
        schema_version=_semver(ctx, raw, "pack"),
        gate=_enum(ctx, raw, "pack", "gate", SEMANTIC_GATES),
        scope_id=_str(ctx, raw, "pack", "scope_id"),
        base_revision=_parse_base_revision(ctx, raw, "pack"),
        template_id=_str(ctx, raw, "pack", "template_id"),
        template_digest=_sha(ctx, raw, "pack", "template_digest"),
        chunks=tuple(chunks),
        request_digest=_sha(ctx, raw, "pack", "request_digest"),
    )
    if not ctx.issues and pack.request_digest != canonical_request_digest(raw):
        ctx.error("pack.request_digest", "does not match the canonical digest of the pack")
    if ctx.issues:
        return None, ctx.issues
    return pack, []


@dataclass(frozen=True)
class SemanticFinding:
    """One ERROR finding reported by a semantic receipt."""

    finding_id: str
    chunk_path: str
    chunk_locator: str
    scope_id: str
    statement: str
    severity: str


@dataclass(frozen=True)
class SemanticReceipt:
    """Validated semantic receipt (FK-78 section 78.14)."""

    schema_version: str
    gate: str
    request_digest: str
    model: str
    principal_id: str
    session_ref: str
    status: str
    findings: tuple[SemanticFinding, ...]
    chunk_digests: tuple[str, ...]
    completed_at: str


SEMANTIC_RECEIPT_KEYS = (
    "schema_version",
    "gate",
    "request_digest",
    "model",
    "principal_id",
    "session_ref",
    "status",
    "findings",
    "chunk_digests",
    "completed_at",
)


def load_semantic_receipt(path: Path) -> tuple[SemanticReceipt | None, list[Issue]]:
    """Load and validate one semantic receipt fail-closed."""
    raw, issues = _read_json_object(path)
    if raw is None:
        return None, issues
    ctx = _Ctx()
    _keys(ctx, raw, "receipt", SEMANTIC_RECEIPT_KEYS)
    findings: list[SemanticFinding] = []
    for item_where, item in _obj_items(ctx, raw, "receipt", "findings"):
        _keys(ctx, item, item_where, ("finding_id", "chunk_path", "chunk_locator", "scope_id", "statement", "severity"))
        findings.append(
            SemanticFinding(
                finding_id=_str(ctx, item, item_where, "finding_id"),
                chunk_path=_str(ctx, item, item_where, "chunk_path"),
                chunk_locator=_str(ctx, item, item_where, "chunk_locator"),
                scope_id=_str(ctx, item, item_where, "scope_id"),
                statement=_str(ctx, item, item_where, "statement"),
                severity=_enum(ctx, item, item_where, "severity", ("ERROR",)),
            )
        )
    receipt = SemanticReceipt(
        schema_version=_semver(ctx, raw, "receipt"),
        gate=_enum(ctx, raw, "receipt", "gate", SEMANTIC_GATES),
        request_digest=_sha(ctx, raw, "receipt", "request_digest"),
        model=_str(ctx, raw, "receipt", "model"),
        principal_id=_matched(ctx, raw, "receipt", "principal_id", PRINCIPAL_ID_RE, "principal id"),
        session_ref=_str(ctx, raw, "receipt", "session_ref"),
        status=_enum(ctx, raw, "receipt", "status", SEMANTIC_RECEIPT_STATUSES),
        findings=tuple(findings),
        chunk_digests=_str_list(ctx, raw, "receipt", "chunk_digests", SHA256_RE, "sha256 digest"),
        completed_at=_time(ctx, raw, "receipt", "completed_at"),
    )
    if ctx.issues:
        return None, ctx.issues
    return receipt, []


# --------------------------------------------------------------------------
# TSV registers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TsvColumn:
    """Column contract of one TSV register column."""

    name: str
    allow_empty: bool = False
    check: Callable[[str], str | None] | None = None


TsvRow = dict[str, str]


def _check_pattern(pattern: re.Pattern[str], what: str) -> Callable[[str], str | None]:
    def check(value: str) -> str | None:
        return None if pattern.fullmatch(value) else f"must be a {what}, got {value!r}"

    return check


def _check_int_value(value: str) -> str | None:
    return None if re.fullmatch(r"\d+", value) else f"must be a non-negative integer, got {value!r}"


def _check_rel_path(value: str) -> str | None:
    if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/") or ":" in value.split("/", 1)[0]:
        return f"must be a project-relative '/'-path, got {value!r}"
    return None


def check_semicolon_list(pattern: re.Pattern[str], what: str) -> Callable[[str], str | None]:
    """Build a checker for a semicolon-separated list of grammar-bound IDs."""

    def check(value: str) -> str | None:
        for item in value.split(";"):
            if item == "" or pattern.fullmatch(item) is None:
                return f"must be a semicolon list of {what}s, got {value!r}"
        return None

    return check


def split_refs(value: str) -> tuple[str, ...]:
    """Split a semicolon-list field into its items (empty field: no items)."""
    return tuple(item for item in value.split(";") if item) if value else ()


def _check_empty_reason(value: str) -> str | None:
    if value == "NO_MATERIAL_CONTENT":
        return None
    if value.startswith("DUPLICATE_OF:"):
        suffix = value.removeprefix("DUPLICATE_OF:")
        return None if UNIT_ID_RE.fullmatch(suffix) else f"DUPLICATE_OF must reference a unit id, got {suffix!r}"
    if value.startswith("OUT_OF_SCOPE:"):
        return None if value.removeprefix("OUT_OF_SCOPE:") else "OUT_OF_SCOPE requires a reason"
    return f"must be NO_MATERIAL_CONTENT, DUPLICATE_OF:<unit_id> or OUT_OF_SCOPE:<reason>, got {value!r}"


def _check_residual_edge(value: str) -> str | None:
    if value in ("CHECKED_AGAINST_CURRENT", "ESCALATED_TO_PO"):
        return None
    if value.startswith("NONE_REQUIRED:"):
        return None if value.removeprefix("NONE_REQUIRED:") else "NONE_REQUIRED requires a class"
    return f"must be CHECKED_AGAINST_CURRENT, ESCALATED_TO_PO or NONE_REQUIRED:<class>, got {value!r}"


def _check_target_refs(value: str) -> str | None:
    """Validate a semicolon list of target references.

    ``<path>#<anchor>`` addresses a markdown section; a bare ``<path>``
    addresses a whole file or directory target (FK-78 target modes).
    """
    for item in value.split(";"):
        if item == "" or item.startswith("#") or item.endswith("#"):
            return f"must be a semicolon list of <path> or <path>#<anchor> references, got {value!r}"
    return None


def _check_deferral(value: str) -> str | None:
    parts = value.split(";")
    prefixes = ("owner=", "trigger=", "anchor=")
    malformed = any(not part.startswith(prefix) or part == prefix for part, prefix in zip(parts, prefixes, strict=False))
    if len(parts) != 3 or malformed:
        return f"must be 'owner=<x>;trigger=<y>;anchor=<path#anchor>', got {value!r}"
    if "#" not in parts[2].removeprefix("anchor="):
        return f"deferral anchor must be <path>#<anchor>, got {value!r}"
    return None


def _check_input_refs(value: str) -> str | None:
    for item in value.split(";"):
        if item.startswith("source:"):
            if SOURCE_ID_RE.fullmatch(item.removeprefix("source:")) is None:
                return f"source ref must carry a source id, got {item!r}"
        elif item.startswith("artifact:"):
            if item.removeprefix("artifact:") == "":
                return f"artifact ref must carry a path, got {item!r}"
        else:
            return f"input refs must be typed as source:<source_id> or artifact:<path>, got {item!r}"
    return None


def _check_enum_value(allowed: tuple[str, ...]) -> Callable[[str], str | None]:
    def check(value: str) -> str | None:
        return None if value in allowed else f"must be one of {', '.join(allowed)}, got {value!r}"

    return check


def _load_tsv(
    path: Path,
    columns: tuple[TsvColumn, ...],
    row_rule: Callable[[TsvRow], list[tuple[str, str]]] | None = None,
) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (), [Issue(locator="file", message=f"not readable as UTF-8 text: {exc}")]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    header = "\t".join(column.name for column in columns)
    if not lines or lines[0] != header:
        return (), [Issue(locator="line 1", message=f"header must be exactly {header!r}")]
    issues: list[Issue] = []
    rows: list[TsvRow] = []
    previous_id: str | None = None
    for number, line in enumerate(lines[1:], start=2):
        row = _parse_tsv_row(line, number, columns, issues)
        if row is None:
            continue
        previous_id = _check_row_order(row, columns[0].name, previous_id, number, issues)
        issues.extend(
            Issue(locator=f"line {number}:{column}", message=message) for column, message in (row_rule(row) if row_rule else [])
        )
        rows.append(row)
    return tuple(rows), issues


def _parse_tsv_row(line: str, number: int, columns: tuple[TsvColumn, ...], issues: list[Issue]) -> TsvRow | None:
    if line == "":
        issues.append(Issue(locator=f"line {number}", message="empty line is not allowed"))
        return None
    if "\r" in line:
        issues.append(Issue(locator=f"line {number}", message="carriage return inside a row is not allowed (LF-only TSV)"))
        return None
    fields = line.split("\t")
    if len(fields) != len(columns):
        issues.append(Issue(locator=f"line {number}", message=f"expected {len(columns)} tab-separated fields, got {len(fields)}"))
        return None
    row: TsvRow = {}
    for column, value in zip(columns, fields, strict=True):
        if value == "":
            if not column.allow_empty:
                issues.append(Issue(locator=f"line {number}:{column.name}", message="must not be empty"))
        elif column.check is not None:
            message = column.check(value)
            if message is not None:
                issues.append(Issue(locator=f"line {number}:{column.name}", message=message))
        row[column.name] = value
    return row


def _check_row_order(row: TsvRow, id_column: str, previous_id: str | None, number: int, issues: list[Issue]) -> str:
    current = row[id_column]
    if previous_id is not None and current <= previous_id:
        issues.append(
            Issue(
                locator=f"line {number}:{id_column}",
                message=f"rows must be strictly sorted by {id_column} ascending, {current!r} after {previous_id!r}",
            )
        )
    return current


_CHECK_SHA = _check_pattern(SHA256_RE, "sha256 lowercase-hex digest")
_CHECK_SHA_OR_GENESIS = _check_pattern(SHA256_RE, "sha256 lowercase-hex digest (or the all-zero genesis digest)")


def load_corpus_baseline(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/corpus-baseline.tsv``."""

    def check_package(value: str) -> str | None:
        if value == "EXEMPT" or PACKAGE_ID_RE.fullmatch(value):
            return None
        return f"must be a package id or EXEMPT, got {value!r}"

    columns = (
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("bytes", check=_check_int_value),
        TsvColumn("sha256", check=_CHECK_SHA),
        TsvColumn("layer"),
        TsvColumn("package_id", allow_empty=True, check=check_package),
    )
    return _load_tsv(path, columns)


INTAKE_ID_RE = re.compile(r"^INT-[0-9a-f]{8}-\d+$")

SOURCE_INTAKE_HEADER = "intake_id\tsource_phase\trole\tpath\tsha256\tregistered_at\tprev_digest\tentry_digest"

#: ``prev_digest`` of the very first intake entry.
INTAKE_GENESIS_DIGEST = "0" * 64

#: Fields covered by ``entry_digest`` (in this order, ``prev_digest`` last).
INTAKE_DIGESTED_FIELDS = ("intake_id", "source_phase", "role", "path", "sha256", "registered_at", "prev_digest")


def intake_entry_digest(row: Mapping[str, str]) -> str:
    """Compute the chain digest of one intake row.

    SHA-256 over the canonically serialized field values (JSON object of
    :data:`INTAKE_DIGESTED_FIELDS`, sorted keys, compact separators),
    including ``prev_digest`` — so the log is a hash chain and a removed
    or edited entry breaks every successor and the head.
    """
    payload = {field: row.get(field, "") for field in INTAKE_DIGESTED_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def intake_chain_problems(rows: Sequence[TsvRow]) -> list[Issue]:
    """Verify the intake hash chain and return one issue per broken link."""
    issues: list[Issue] = []
    expected_prev = INTAKE_GENESIS_DIGEST
    for number, row in enumerate(rows, start=2):
        if row["prev_digest"] != expected_prev:
            issues.append(
                Issue(
                    locator=f"line {number}:prev_digest",
                    message=f"broken append-only chain: expected {expected_prev}, got {row['prev_digest']}",
                )
            )
        computed = intake_entry_digest(row)
        if row["entry_digest"] != computed:
            issues.append(
                Issue(locator=f"line {number}:entry_digest", message="entry_digest does not match the row content")
            )
        expected_prev = row["entry_digest"]
    return issues


def intake_head_digest(rows: Sequence[TsvRow]) -> str:
    """Return the current head of the intake chain (genesis when empty)."""
    return rows[-1]["entry_digest"] if rows else INTAKE_GENESIS_DIGEST


def intake_prefix_head_index(rows: Sequence[TsvRow], head: str) -> int | None:
    """Return ``k`` such that the first ``k`` rows hash exactly to ``head``.

    ``head`` equal to the genesis digest yields ``0``. ``None`` means the
    pinned head is not a prefix of the current chain, i.e. an entry was
    removed, reordered or inserted before it.
    """
    if head == INTAKE_GENESIS_DIGEST:
        return 0
    for index, row in enumerate(rows, start=1):
        if row["entry_digest"] == head:
            return index
    return None


def load_source_intake(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load the append-only, hash-chained ``baseline/source-intake.tsv``.

    Every source is recorded here on arrival. Each row carries
    ``prev_digest``/``entry_digest`` forming a hash chain whose head is
    pinned outside this file in
    ``RUN.json.register_digests.source_intake_head``, so intake and
    register cannot be tidied up together without breaking the head.
    """
    columns = (
        TsvColumn("intake_id", check=_check_pattern(INTAKE_ID_RE, "intake id")),
        TsvColumn("source_phase", check=_check_enum_value(SOURCE_PHASES)),
        TsvColumn("role", check=_check_enum_value(SOURCE_ROLES)),
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("sha256", check=_CHECK_SHA),
        TsvColumn("registered_at", check=_check_pattern(TIMESTAMP_RE, "UTC ISO-8601 timestamp with Z suffix")),
        TsvColumn("prev_digest", check=_CHECK_SHA_OR_GENESIS),
        TsvColumn("entry_digest", check=_CHECK_SHA),
    )
    return _load_tsv(path, columns)


def load_source_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/source-register.tsv``."""
    columns = (
        TsvColumn("source_id", check=_check_pattern(SOURCE_ID_RE, "source id")),
        TsvColumn("source_phase", check=_check_enum_value(SOURCE_PHASES)),
        TsvColumn("role", check=_check_enum_value(SOURCE_ROLES)),
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("sha256", check=_CHECK_SHA),
        TsvColumn("round", allow_empty=True, check=_check_int_value),
        TsvColumn("participant_id", allow_empty=True, check=_check_pattern(PARTICIPANT_ID_RE, "participant id")),
        TsvColumn("author_principal_id", allow_empty=True, check=_check_pattern(PRINCIPAL_ID_RE, "principal id")),
        TsvColumn("genealogy_parents", allow_empty=True, check=check_semicolon_list(SOURCE_ID_RE, "source id")),
    )
    return _load_tsv(path, columns)


def load_source_units(path: Path, *, require_disposition: bool = True) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/source-units.tsv``.

    Args:
        path: Register path.
        require_disposition: When ``True`` (checker mode) every unit must
            carry ``claim_refs`` or ``empty_reason``. The mutating
            ``semantic_gate.py units`` derivation loads with ``False``
            because freshly derived units are legitimately undecided.
    """

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        has_claims = row["claim_refs"] != ""
        has_reason = row["empty_reason"] != ""
        if has_claims and has_reason:
            return [("empty_reason", "must be empty when claim_refs is set")]
        if not has_claims and not has_reason and require_disposition:
            return [("claim_refs", "unit must carry claim_refs or an empty_reason")]
        return []

    columns = (
        TsvColumn("unit_id", check=_check_pattern(UNIT_ID_RE, "unit id")),
        TsvColumn("source_id", check=_check_pattern(SOURCE_ID_RE, "source id")),
        TsvColumn("unit_locator", check=_check_target_refs),
        TsvColumn("unit_digest", check=_CHECK_SHA),
        TsvColumn("claim_refs", allow_empty=True, check=check_semicolon_list(CLAIM_ID_RE, "claim id")),
        TsvColumn("empty_reason", allow_empty=True, check=_check_empty_reason),
    )
    return _load_tsv(path, columns, rule)


def _coverage_rule(row: TsvRow) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    status = row["review_status"]
    artifact = row["review_artifact"]
    if status == "N_A":
        if not artifact.startswith("N_A:") or artifact == "N_A:":
            problems.append(("review_artifact", "N_A requires 'N_A:<reason>' with a non-empty reason"))
    elif artifact.startswith("N_A:"):
        problems.append(("review_artifact", "'N_A:<reason>' is only allowed for review_status N_A"))
    if status in ("PASS_WITH_GAPS", "FAIL") and row["finding_refs"] == "":
        problems.append(("finding_refs", f"required for review_status {status}"))
    return problems


def load_source_coverage(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/source-coverage.tsv``."""
    columns = (
        TsvColumn("source_id", check=_check_pattern(SOURCE_ID_RE, "source id")),
        TsvColumn("sha256", check=_CHECK_SHA),
        TsvColumn("review_status", check=_check_enum_value(REVIEW_STATUSES)),
        TsvColumn("review_artifact"),
        TsvColumn("reviewer_principal_id", check=_check_pattern(PRINCIPAL_ID_RE, "principal id")),
        TsvColumn("finding_refs", allow_empty=True, check=check_semicolon_list(FINDING_ID_RE, "finding id")),
    )
    return _load_tsv(path, columns, _coverage_rule)


def load_normative_coverage(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/normative-coverage.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        problems = _coverage_rule(row)
        kind = row["change_kind"]
        if kind == "added" and row["baseline_sha256"] != "":
            problems.append(("baseline_sha256", "must be empty for change_kind added"))
        if kind != "added" and row["baseline_sha256"] == "":
            problems.append(("baseline_sha256", f"required for change_kind {kind}"))
        if kind == "removed" and row["current_sha256"] != "":
            problems.append(("current_sha256", "must be empty for change_kind removed"))
        if kind != "removed" and row["current_sha256"] == "":
            problems.append(("current_sha256", f"required for change_kind {kind}"))
        return problems

    columns = (
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("baseline_sha256", allow_empty=True, check=_CHECK_SHA),
        TsvColumn("current_sha256", allow_empty=True, check=_CHECK_SHA),
        TsvColumn("change_kind", check=_check_enum_value(CHANGE_KINDS)),
        TsvColumn("review_status", check=_check_enum_value(REVIEW_STATUSES)),
        TsvColumn("review_artifact"),
        TsvColumn("reviewer_principal_id", check=_check_pattern(PRINCIPAL_ID_RE, "principal id")),
        TsvColumn("finding_refs", allow_empty=True, check=check_semicolon_list(FINDING_ID_RE, "finding id")),
    )
    return _load_tsv(path, columns, rule)


def load_artifact_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``artifact-register.tsv`` (or its ``.local`` overlay)."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        if row["effective_class"] == "sensitive" and row["vcs_disposition"] != "local":
            return [("vcs_disposition", "effective_class sensitive requires vcs_disposition local (commit gate)")]
        return []

    columns = (
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("sha256", check=_CHECK_SHA),
        TsvColumn("artifact_kind", check=_check_enum_value(ARTIFACT_KINDS)),
        TsvColumn("input_refs", allow_empty=True, check=_check_input_refs),
        TsvColumn("declared_class", check=_check_enum_value(DATA_CLASSES)),
        TsvColumn("effective_class", check=_check_enum_value(DATA_CLASSES)),
        TsvColumn("vcs_disposition", check=_check_enum_value(VCS_DISPOSITIONS)),
        TsvColumn("declassification_receipt", allow_empty=True, check=_check_rel_path),
    )
    return _load_tsv(path, columns, rule)


def load_findings_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``findings.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        if row["status"] in ("resolved", "accepted_by_po") and row["resolution"] == "":
            return [("resolution", f"required for status {row['status']}")]
        return []

    columns = (
        TsvColumn("finding_id", check=_check_pattern(FINDING_ID_RE, "finding id")),
        TsvColumn("severity", check=_check_enum_value(FINDING_SEVERITIES)),
        TsvColumn("status", check=_check_enum_value(FINDING_STATUSES)),
        TsvColumn("claim_refs", allow_empty=True, check=check_semicolon_list(CLAIM_ID_RE, "claim id")),
        TsvColumn("atom_refs", allow_empty=True, check=check_semicolon_list(ATOM_ID_RE, "atom id")),
        TsvColumn("path", check=_check_rel_path),
        TsvColumn("locator"),
        TsvColumn("statement"),
        TsvColumn("resolution", allow_empty=True),
    )
    return _load_tsv(path, columns, rule)


def load_claims_inventory(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``synthesis/claims-inventory.tsv``."""
    columns = (
        TsvColumn("claim_id", check=_check_pattern(CLAIM_ID_RE, "claim id")),
        TsvColumn("source_id", check=_check_pattern(SOURCE_ID_RE, "source id")),
        TsvColumn("unit_refs", check=check_semicolon_list(UNIT_ID_RE, "unit id")),
        TsvColumn("source_locator", check=_check_target_refs),
        TsvColumn("statement"),
        TsvColumn("qualifiers", allow_empty=True),
        TsvColumn("genealogy_parents", allow_empty=True, check=check_semicolon_list(CLAIM_ID_RE, "claim id")),
    )
    return _load_tsv(path, columns)


def load_disposition_ledger(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``synthesis/disposition-ledger.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        problems: list[tuple[str, str]] = []
        disposition = row["synthesis_disposition"]
        if disposition != "ADOPTED" and row["disposition_reason"] == "":
            problems.append(("disposition_reason", f"required for synthesis_disposition {disposition}"))
        if disposition not in ("ADOPTED", "MERGED") and row["residual_edge"] == "":
            problems.append(("residual_edge", f"required for synthesis_disposition {disposition}"))
        if disposition in ("ADOPTED", "MERGED") and row["atom_refs"] == "":
            problems.append(("atom_refs", f"required for synthesis_disposition {disposition}"))
        return problems

    columns = (
        TsvColumn("claim_id", check=_check_pattern(CLAIM_ID_RE, "claim id")),
        TsvColumn("synthesis_disposition", check=_check_enum_value(SYNTHESIS_DISPOSITIONS)),
        TsvColumn("disposition_reason", allow_empty=True),
        TsvColumn("residual_edge", allow_empty=True, check=_check_residual_edge),
        TsvColumn("atom_refs", allow_empty=True, check=check_semicolon_list(ATOM_ID_RE, "atom id")),
        TsvColumn("finding_refs", allow_empty=True, check=check_semicolon_list(FINDING_ID_RE, "finding id")),
    )
    return _load_tsv(path, columns, rule)


def load_atom_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``promotion/atom-register.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        problems: list[tuple[str, str]] = []
        disposition = row["disposition"]
        if disposition in COVERED_DISPOSITIONS:
            if row["receipt_refs"] == "":
                problems.append(("receipt_refs", f"required for disposition {disposition}"))
            if row["target_refs"] == "":
                problems.append(("target_refs", f"required for disposition {disposition}"))
        if disposition == "COVERED_SPLIT" and len(split_refs(row["target_refs"])) < 2:
            problems.append(("target_refs", "COVERED_SPLIT requires at least two target refs"))
        if disposition == "DEFERRED_BACKLOG" and row["deferral"] == "":
            problems.append(("deferral", "required for disposition DEFERRED_BACKLOG"))
        return problems

    columns = (
        TsvColumn("atom_id", check=_check_pattern(ATOM_ID_RE, "atom id")),
        TsvColumn("statement"),
        TsvColumn("atom_type", check=_check_enum_value(ATOM_TYPES)),
        TsvColumn("qualifiers", allow_empty=True),
        TsvColumn("normative_status", check=_check_enum_value(NORMATIVE_STATUSES)),
        TsvColumn("expected_authority"),
        TsvColumn("target_refs", allow_empty=True, check=_check_target_refs),
        TsvColumn("disposition", check=_check_enum_value(ATOM_DISPOSITIONS)),
        TsvColumn("deferral", allow_empty=True, check=_check_deferral),
        TsvColumn("claim_refs", check=check_semicolon_list(CLAIM_ID_RE, "claim id")),
        TsvColumn("receipt_refs", allow_empty=True, check=check_semicolon_list(RECEIPT_ID_RE, "receipt id")),
    )
    return _load_tsv(path, columns, rule)
