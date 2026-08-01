"""FK-78 register contracts, row rules, and intake-chain integrity."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_tsv import (
    CHECK_SHA,
    CHECK_SHA_OR_GENESIS,
    TsvColumn,
    TsvRow,
    check_deferral,
    check_empty_reason,
    check_enum_value,
    check_input_refs,
    check_int_value,
    check_pattern,
    check_rel_path,
    check_residual_edge,
    check_semicolon_list,
    check_target_refs,
    load_tsv,
    split_refs,
)
from .runmodel_validation import Issue

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

def load_corpus_baseline(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/corpus-baseline.tsv``."""

    def check_package(value: str) -> str | None:
        if value == "EXEMPT" or Vocab.PACKAGE_ID_RE.fullmatch(value):
            return None
        return f"must be a package id or EXEMPT, got {value!r}"

    columns = (
        TsvColumn("path", check=check_rel_path),
        TsvColumn("bytes", check=check_int_value),
        TsvColumn("sha256", check=CHECK_SHA),
        TsvColumn("layer"),
        TsvColumn("package_id", allow_empty=True, check=check_package),
    )
    return load_tsv(path, columns)


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
            issues.append(Issue(locator=f"line {number}:entry_digest", message="entry_digest does not match the row content"))
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
        TsvColumn("intake_id", check=check_pattern(INTAKE_ID_RE, "intake id")),
        TsvColumn("source_phase", check=check_enum_value(Vocab.SOURCE_PHASES)),
        TsvColumn("role", check=check_enum_value(Vocab.SOURCE_ROLES)),
        TsvColumn("path", check=check_rel_path),
        TsvColumn("sha256", check=CHECK_SHA),
        TsvColumn("registered_at", check=check_pattern(Vocab.TIMESTAMP_RE, "UTC ISO-8601 timestamp with Z suffix")),
        TsvColumn("prev_digest", check=CHECK_SHA_OR_GENESIS),
        TsvColumn("entry_digest", check=CHECK_SHA),
    )
    return load_tsv(path, columns)


def load_source_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``baseline/source-register.tsv``."""
    columns = (
        TsvColumn("source_id", check=check_pattern(Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL)),
        TsvColumn("source_phase", check=check_enum_value(Vocab.SOURCE_PHASES)),
        TsvColumn("role", check=check_enum_value(Vocab.SOURCE_ROLES)),
        TsvColumn("path", check=check_rel_path),
        TsvColumn("sha256", check=CHECK_SHA),
        TsvColumn("round", allow_empty=True, check=check_int_value),
        TsvColumn(
            "participant_id",
            allow_empty=True,
            check=check_pattern(Vocab.PARTICIPANT_ID_RE, Vocab.PARTICIPANT_ID_LABEL),
        ),
        TsvColumn(
            "author_principal_id",
            allow_empty=True,
            check=check_pattern(Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL),
        ),
        TsvColumn(
            "genealogy_parents",
            allow_empty=True,
            check=check_semicolon_list(Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL),
        ),
    )
    return load_tsv(path, columns)


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
        TsvColumn("unit_id", check=check_pattern(Vocab.UNIT_ID_RE, "unit id")),
        TsvColumn("source_id", check=check_pattern(Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL)),
        TsvColumn("unit_locator", check=check_target_refs),
        TsvColumn("unit_digest", check=CHECK_SHA),
        TsvColumn(
            "claim_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL),
        ),
        TsvColumn("empty_reason", allow_empty=True, check=check_empty_reason),
    )
    return load_tsv(path, columns, rule)


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
        TsvColumn("source_id", check=check_pattern(Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL)),
        TsvColumn("sha256", check=CHECK_SHA),
        TsvColumn("review_status", check=check_enum_value(Vocab.REVIEW_STATUSES)),
        TsvColumn("review_artifact"),
        TsvColumn(
            "reviewer_principal_id",
            check=check_pattern(Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL),
        ),
        TsvColumn(
            "finding_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.FINDING_ID_RE, Vocab.FINDING_ID_LABEL),
        ),
    )
    return load_tsv(path, columns, _coverage_rule)


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
        TsvColumn("path", check=check_rel_path),
        TsvColumn("baseline_sha256", allow_empty=True, check=CHECK_SHA),
        TsvColumn("current_sha256", allow_empty=True, check=CHECK_SHA),
        TsvColumn("change_kind", check=check_enum_value(Vocab.CHANGE_KINDS)),
        TsvColumn("review_status", check=check_enum_value(Vocab.REVIEW_STATUSES)),
        TsvColumn("review_artifact"),
        TsvColumn(
            "reviewer_principal_id",
            check=check_pattern(Vocab.PRINCIPAL_ID_RE, Vocab.PRINCIPAL_ID_LABEL),
        ),
        TsvColumn(
            "finding_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.FINDING_ID_RE, Vocab.FINDING_ID_LABEL),
        ),
    )
    return load_tsv(path, columns, rule)


def load_artifact_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``artifact-register.tsv`` (or its ``.local`` overlay)."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        if row["effective_class"] == "sensitive" and row["vcs_disposition"] != "local":
            return [("vcs_disposition", "effective_class sensitive requires vcs_disposition local (commit gate)")]
        return []

    columns = (
        TsvColumn("path", check=check_rel_path),
        TsvColumn("sha256", check=CHECK_SHA),
        TsvColumn("artifact_kind", check=check_enum_value(Vocab.ARTIFACT_KINDS)),
        TsvColumn("input_refs", allow_empty=True, check=check_input_refs),
        TsvColumn("declared_class", check=check_enum_value(Vocab.DATA_CLASSES)),
        TsvColumn("effective_class", check=check_enum_value(Vocab.DATA_CLASSES)),
        TsvColumn("vcs_disposition", check=check_enum_value(Vocab.VCS_DISPOSITIONS)),
        TsvColumn("declassification_receipt", allow_empty=True, check=check_rel_path),
    )
    return load_tsv(path, columns, rule)


def load_findings_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``findings.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        if row["status"] in ("resolved", "accepted_by_po") and row["resolution"] == "":
            return [("resolution", f"required for status {row['status']}")]
        return []

    columns = (
        TsvColumn("finding_id", check=check_pattern(Vocab.FINDING_ID_RE, Vocab.FINDING_ID_LABEL)),
        TsvColumn("severity", check=check_enum_value(Vocab.FINDING_SEVERITIES)),
        TsvColumn("status", check=check_enum_value(Vocab.FINDING_STATUSES)),
        TsvColumn(
            "claim_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL),
        ),
        TsvColumn(
            "atom_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.ATOM_ID_RE, Vocab.ATOM_ID_LABEL),
        ),
        TsvColumn("path", check=check_rel_path),
        TsvColumn("locator"),
        TsvColumn("statement"),
        TsvColumn("resolution", allow_empty=True),
    )
    return load_tsv(path, columns, rule)


def load_claims_inventory(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``synthesis/claims-inventory.tsv``."""
    columns = (
        TsvColumn("claim_id", check=check_pattern(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL)),
        TsvColumn("source_id", check=check_pattern(Vocab.SOURCE_ID_RE, Vocab.SOURCE_ID_LABEL)),
        TsvColumn("unit_refs", check=check_semicolon_list(Vocab.UNIT_ID_RE, "unit id")),
        TsvColumn("source_locator", check=check_target_refs),
        TsvColumn("statement"),
        TsvColumn("qualifiers", allow_empty=True),
        TsvColumn(
            "genealogy_parents",
            allow_empty=True,
            check=check_semicolon_list(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL),
        ),
    )
    return load_tsv(path, columns)


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
        TsvColumn("claim_id", check=check_pattern(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL)),
        TsvColumn("synthesis_disposition", check=check_enum_value(Vocab.SYNTHESIS_DISPOSITIONS)),
        TsvColumn("disposition_reason", allow_empty=True),
        TsvColumn("residual_edge", allow_empty=True, check=check_residual_edge),
        TsvColumn(
            "atom_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.ATOM_ID_RE, Vocab.ATOM_ID_LABEL),
        ),
        TsvColumn(
            "finding_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.FINDING_ID_RE, Vocab.FINDING_ID_LABEL),
        ),
    )
    return load_tsv(path, columns, rule)


def load_atom_register(path: Path) -> tuple[tuple[TsvRow, ...], list[Issue]]:
    """Load ``promotion/atom-register.tsv``."""

    def rule(row: TsvRow) -> list[tuple[str, str]]:
        problems: list[tuple[str, str]] = []
        disposition = row["disposition"]
        if disposition in Vocab.COVERED_DISPOSITIONS:
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
        TsvColumn("atom_id", check=check_pattern(Vocab.ATOM_ID_RE, Vocab.ATOM_ID_LABEL)),
        TsvColumn("statement"),
        TsvColumn("atom_type", check=check_enum_value(Vocab.ATOM_TYPES)),
        TsvColumn("qualifiers", allow_empty=True),
        TsvColumn("normative_status", check=check_enum_value(Vocab.NORMATIVE_STATUSES)),
        TsvColumn("expected_authority"),
        TsvColumn("target_refs", allow_empty=True, check=check_target_refs),
        TsvColumn("disposition", check=check_enum_value(Vocab.ATOM_DISPOSITIONS)),
        TsvColumn("deferral", allow_empty=True, check=check_deferral),
        TsvColumn("claim_refs", check=check_semicolon_list(Vocab.CLAIM_ID_RE, Vocab.CLAIM_ID_LABEL)),
        TsvColumn(
            "receipt_refs",
            allow_empty=True,
            check=check_semicolon_list(Vocab.RECEIPT_ID_RE, Vocab.RECEIPT_ID_LABEL),
        ),
    )
    return load_tsv(path, columns, rule)
