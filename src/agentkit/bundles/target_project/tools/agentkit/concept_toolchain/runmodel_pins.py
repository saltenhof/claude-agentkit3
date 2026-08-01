"""Derive the register pins that bind frozen FK-78 run inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runmodel_constants import RunModelConstants as Vocab
from .runmodel_digests import canonical_tsv_subset_digest, file_sha256
from .runmodel_registers import intake_head_digest, load_source_intake
from .runmodel_validation import Issue

if TYPE_CHECKING:
    from pathlib import Path

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


def _subset_pins(run_dir: Path, expected: dict[str, str | None], issues: list[Issue]) -> None:
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
    expected: dict[str, str | None] = dict.fromkeys(Vocab.REGISTER_DIGEST_KEYS)
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
