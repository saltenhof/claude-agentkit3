"""Immutable intake pins and the input-prefix proof (FK-78 78.4/78.7, R9-2).

The intake log is an append-only hash chain with two immutable pins:
``source_intake_input_head`` (input freeze) and
``source_intake_final_head`` (before PROMOTING). The checker proves the
pinned input head is still an unchanged PREFIX of the current chain —
only input rows inside it, only derived rows after it — so removing,
reordering or splicing an input entry stays detectable even when the log
itself is re-chained into a self-consistent state.

Documented boundary: the pins live in ``RUN.json``. An actor who rewrites
that file too can make any chain self-consistent; the anchor against that
is the committed ``RUN.json`` in VCS history, not a file-local compare.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel
from concept_toolchain.config import load_governance_config
from concept_toolchain.incubator_check import run_incubator_check
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.runfixtures import RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

pytestmark = pytest.mark.requires_git

COLUMNS = runmodel.SOURCE_INTAKE_HEADER.split("\t")


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=True)


def run_check(fixture: RunFixture) -> CheckResult:
    config = load_governance_config(fixture.project_root)
    return run_incubator_check(fixture.project_root, config, fixture.run_dir)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.locator}: {finding.message}" for finding in result.findings)


def intake_lines(fixture: RunFixture) -> list[str]:
    text = (fixture.run_dir / "baseline" / "source-intake.tsv").read_text(encoding="utf-8")
    return text.rstrip("\n").split("\n")


def write_intake_lines(fixture: RunFixture, lines: list[str]) -> None:
    path = fixture.run_dir / "baseline" / "source-intake.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def rechain(rows: list[str]) -> list[str]:
    """Recompute a valid hash chain over the given data rows (attacker move)."""
    out: list[str] = []
    previous = runmodel.INTAKE_GENESIS_DIGEST
    for line in rows:
        row = dict(zip(COLUMNS, line.split("\t"), strict=True))
        row["prev_digest"] = previous
        row["entry_digest"] = runmodel.intake_entry_digest(row)
        out.append("\t".join(row[column] for column in COLUMNS))
        previous = row["entry_digest"]
    return out


def drop_register_row(fixture: RunFixture, needle: str) -> None:
    path = fixture.run_dir / "baseline" / "source-register.tsv"
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    path.write_text("\n".join(line for line in lines if needle not in line) + "\n", encoding="utf-8", newline="\n")


def test_green_run_satisfies_both_pins(fixture: RunFixture) -> None:
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_missing_intake_head_pins_are_errors(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["source_intake_input_head"] = None
    digests["source_intake_final_head"] = None
    fixture.write_run(payload)
    combined = finding_messages(run_check(fixture))
    assert "must pin the intake chain head at the input freeze" in combined
    assert "must pin the intake chain head before entering PROMOTING" in combined


def test_removing_an_input_entry_breaks_the_prefix_proof(fixture: RunFixture) -> None:
    lines = intake_lines(fixture)
    write_intake_lines(fixture, [lines[0], *[line for line in lines[1:] if "worker-one.md" not in line]])
    assert "pinned input intake head is not a prefix of the current chain" in finding_messages(run_check(fixture))


def test_joint_pruning_with_rechaining_is_detected(fixture: RunFixture) -> None:
    """Prune intake + register and re-chain the log: the frozen pin still catches it.

    Boundary (documented, not a gap in this check): the input pin lives in
    ``RUN.json``, so an actor who can also rewrite that file can make any
    chain self-consistent. The external anchor against that is the
    committed ``RUN.json`` (``base_revision``/VCS history), not a
    file-local comparison — no local check can beat an attacker who owns
    every local file.
    """
    lines = intake_lines(fixture)
    kept = [line for line in lines[1:] if "worker-one.md" not in line]
    write_intake_lines(fixture, [lines[0], *rechain(kept)])
    drop_register_row(fixture, "worker-one.md")
    fixture.repin_registers()  # honest writer: the frozen input pin stays put
    assert "pinned input intake head is not a prefix of the current chain" in finding_messages(run_check(fixture))


def test_reordering_intake_entries_breaks_the_chain(fixture: RunFixture) -> None:
    lines = intake_lines(fixture)
    write_intake_lines(fixture, [lines[0], lines[2], lines[1], *lines[3:]])
    assert "broken append-only chain" in finding_messages(run_check(fixture))


def test_reordering_with_rechaining_still_breaks_the_prefix_proof(fixture: RunFixture) -> None:
    lines = intake_lines(fixture)
    swapped = [lines[2], lines[1], *lines[3:]]
    write_intake_lines(fixture, [lines[0], *rechain(swapped)])
    assert "pinned input intake head is not a prefix of the current chain" in finding_messages(run_check(fixture))


def test_input_entry_appended_after_the_freeze_is_error(fixture: RunFixture) -> None:
    extra = fixture.run_dir / "late-input.md"
    extra.write_text("# Late\n\nSmuggled input.\n", encoding="utf-8", newline="\n")
    runfixtures.append_intake_entry(
        fixture,
        intake_id=f"INT-{fixture.uuid8}-8",
        source_phase="input",
        role="PO_DECISION",
        path=f"{fixture.run_rel}/late-input.md",
        sha256=runfixtures.sha_file(extra),
    )
    assert "input sources must not be appended after the input freeze" in finding_messages(run_check(fixture))


def test_input_entry_inserted_between_derived_entries_is_detected(fixture: RunFixture) -> None:
    """Splicing an input row behind the freeze cannot be re-chained away."""
    lines = intake_lines(fixture)
    forged = dict(zip(COLUMNS, lines[1].split("\t"), strict=True))
    forged["intake_id"] = f"INT-{fixture.uuid8}-7"
    forged["path"] = f"{fixture.run_rel}/briefing.md"
    spliced = [*lines[1:], "\t".join(forged[column] for column in COLUMNS)]
    write_intake_lines(fixture, [lines[0], *rechain(spliced)])
    combined = finding_messages(run_check(fixture))
    assert "input sources must not be appended after the input freeze" in combined


def test_appending_derived_entries_keeps_the_input_pin_valid(fixture: RunFixture) -> None:
    """Legitimate derived growth must NOT invalidate the immutable input pin."""
    extra = fixture.run_dir / "synthesis" / "po-decision-late.md"
    extra.write_text("# PO Decision\n\nLater decision.\n", encoding="utf-8", newline="\n")
    runfixtures.append_intake_entry(
        fixture,
        intake_id=f"INT-{fixture.uuid8}-6",
        source_phase="derived",
        role="PO_DECISION",
        path=f"{fixture.run_rel}/synthesis/po-decision-late.md",
        sha256=runfixtures.sha_file(extra),
    )
    combined = finding_messages(run_check(fixture))
    assert "not a prefix of the current chain" not in combined
    assert "must not be appended after the input freeze" not in combined
    # Only the (expected) set-equality gap against the register remains.
    assert "intake entry has no source-register row" in combined


def test_final_head_must_track_the_current_chain(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["source_intake_final_head"] = "0" * 64
    fixture.write_run(payload)
    assert "does not match RUN.json register_digests.source_intake_final_head" in finding_messages(run_check(fixture))
