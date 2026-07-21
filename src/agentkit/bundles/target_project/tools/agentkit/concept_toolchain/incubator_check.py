"""Incubator run validation — ``check.py incubator <run-dir>`` (FK-78).

Validates the layout and schemas of every present run artifact
(sections 78.3/78.4/78.6), lifecycle consistency rules (blocked/recheck
nullability, state-dependent ``register_digests`` gates and material
digest verification of all nine pins via canonical re-derivation), the
loss-free input set closure (briefing + all sealed proposals + PO inputs
== input sources), the full corpus-baseline re-derivation against the git
tree of ``base_revision`` (without git: INCOMPLETE, never a silent PASS),
round consistency (ROUND.json against the sealed files, seal digest
bindings, outcome reasons), the deterministic unit re-derivation against
``source-units.tsv`` (section 78.7), the claim-inventory and
disposition-ledger closure rules including bidirectional
ledger.atom_refs / atom.claim_refs edges (section 78.8), a live writer
lease in every non-terminal state, the artifact register with typed
provenance, file-digest binding, acyclicity, effective-class flow across
``artifact:`` AND ``source:`` edges, main-register/overlay disposition
split and declassification source binding (section 78.13), and the
findings register (section 78.9).

``state_revision`` monotonicity is a write-protocol property and not
statically checkable; the checker verifies the reachable consistency
rules instead.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from . import runmodel
from .docmodel import file_digest_sha256
from .findings import CheckResult, error
from .units import derive_units

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from .config import GovernanceConfig
    from .runmodel import Issue, TsvRow

CHECK_ID = "incubator"

_ROUND_DIR_RE = re.compile(r"^r([1-9]\d*)$")
_CLASS_RANK = {"open": 0, "internal": 1, "sensitive": 2}
_TERMINAL_STATES = ("CLOSED", "ABORTED")
_DERIVABLE_INPUT_ROLES = ("BRIEFING", "PROPOSAL", "PO_DECISION")

#: Canonical derived-source path conventions of a run and their mandatory
#: roles (FK-78 section 78.7). Synthesis rounds
#: ``synthesis/synthesis-r<N>.md``, the dissent map
#: ``synthesis/dissent-map.md`` and PO decisions
#: ``synthesis/po-decision-<slug>.md`` are the complete derived universe;
#: every such file on disk must be registered with the matching role and
#: vice versa.
_DERIVED_GLOBS = (
    ("synthesis/synthesis-r*.md", "SYNTHESIS"),
    ("synthesis/dissent-map.md", "DISSENT_MAP"),
    ("synthesis/po-decision*.md", "PO_DECISION"),
)

#: register_digests presence gates: (key, minimum linear rank).
_DIGEST_GATES: tuple[tuple[str, int], ...] = (
    ("corpus_baseline", 1),
    ("source_register_input", 4),
    ("source_units_input", 4),
    ("claims_inventory_input", 4),
    ("derived_claims", 6),
    ("disposition_ledger", 6),
    ("source_register_final", 6),
    ("source_units_final", 6),
    ("atom_register", 6),
)


def run_incubator_check(project_root: Path, config: GovernanceConfig, run_dir: Path) -> CheckResult:
    """Run the incubator check for one run directory."""
    return _IncubatorCheck(project_root, config, run_dir).execute()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def effective_state_rank(run: runmodel.RunState) -> int | None:
    """Map the run state onto the linear main-path rank for digest gating."""
    state = run.state
    if state == "BLOCKED" and run.blocked is not None:
        state = run.blocked.since_state
    elif state == "RECHECK" and run.recheck is not None:
        state = run.recheck.detected_in_state
    if state == "PROMOTION_FAILED":
        state = "PROMOTING"
    return runmodel.LINEAR_STATE_RANK.get(state)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a coverage-plan glob (``**``, ``*``, ``?``) to a regex."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index : index + 3] == "**/":
                out.append("(?:[^/]+/)*")
                index += 3
                continue
            if pattern[index : index + 2] == "**":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + "$")


class _IncubatorCheck:
    """Stateful executor for one incubator-check invocation."""

    def __init__(self, project_root: Path, config: GovernanceConfig, run_dir: Path) -> None:
        self.project_root = project_root
        self.config = config
        self.run_dir = run_dir
        self.result = CheckResult(check_id=CHECK_ID)
        try:
            self.rel = run_dir.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            self.rel = run_dir.as_posix()
        self.run: runmodel.RunState | None = None
        self.source_rows: tuple[TsvRow, ...] | None = None
        self.unit_rows: tuple[TsvRow, ...] | None = None
        self.claim_rows: tuple[TsvRow, ...] | None = None
        self.ledger_rows: tuple[TsvRow, ...] | None = None
        self.atom_rows: tuple[TsvRow, ...] | None = None
        self.finding_rows: tuple[TsvRow, ...] | None = None
        self.baseline_rows: tuple[TsvRow, ...] | None = None
        self.artifact_rows: tuple[TsvRow, ...] = ()
        self.verified_sources: dict[str, str] = {}
        self.sealed_proposals: dict[str, str] = {}
        self.skipped: list[str] = []

    # -- infrastructure -----------------------------------------------------

    def _path(self, *parts: str) -> Path:
        return self.run_dir.joinpath(*parts)

    def _rel_path(self, *parts: str) -> str:
        return f"{self.rel}/{'/'.join(parts)}" if parts else self.rel

    def _error(self, rel_path: str, locator: str, message: str) -> None:
        self.result.findings.append(error(CHECK_ID, rel_path, locator, message))

    def _report(self, rel_path: str, issues: Sequence[Issue]) -> None:
        for issue in issues:
            self._error(rel_path, issue.locator, issue.message)

    def _load_register(
        self,
        parts: tuple[str, ...],
        loader: Callable[[Path], tuple[tuple[TsvRow, ...], list[Issue]]],
    ) -> tuple[TsvRow, ...] | None:
        path = self._path(*parts)
        if not path.is_file():
            return None
        rows, issues = loader(path)
        self._report(self._rel_path(*parts), issues)
        return rows

    # -- entry point --------------------------------------------------------

    def execute(self) -> CheckResult:
        if not self.run_dir.is_dir():
            self.result.complete = False
            self.result.incomplete_reason = f"run directory does not exist: {self.rel}"
            return self.result
        run_json = self._path("RUN.json")
        if not run_json.is_file():
            self.result.complete = False
            self.result.incomplete_reason = f"RUN.json not found in {self.rel}"
            return self.result
        run, issues = runmodel.load_run_state(run_json)
        self._report(self._rel_path("RUN.json"), issues)
        self.run = run
        self._load_all_registers()
        self._check_layout()
        self._check_lease()
        if run is not None:
            self._check_lifecycle(run)
            self._check_coverage_plan(run)
            self._check_baseline_rederivation(run)
        self._check_rounds()
        self._check_sources()
        self._check_intake_closure()
        self._check_input_set_closure()
        self._check_derived_set_closure()
        self._check_units()
        self._check_claims()
        self._check_ledger()
        self._check_ledger_atom_edges()
        self._check_findings_register()
        self._check_artifact_register()
        self._check_coverage_registers()
        self._check_promotion_artifacts()
        self._check_declassification_receipts()
        self._check_id_namespace()
        if self.skipped:
            self.result.complete = False
            self.result.incomplete_reason = f"INCOMPLETE_CHECK_SET: skipped=[{'; '.join(self.skipped)}]"
        self.result.summary = f"run {self.run.run_id} validated" if self.run else "run artifacts validated"
        return self.result

    def _load_all_registers(self) -> None:
        self.baseline_rows = self._load_register(("baseline", "corpus-baseline.tsv"), runmodel.load_corpus_baseline)
        self.source_rows = self._load_register(("baseline", "source-register.tsv"), runmodel.load_source_register)
        self.unit_rows = self._load_register(("baseline", "source-units.tsv"), runmodel.load_source_units)
        self.claim_rows = self._load_register(("synthesis", "claims-inventory.tsv"), runmodel.load_claims_inventory)
        self.ledger_rows = self._load_register(("synthesis", "disposition-ledger.tsv"), runmodel.load_disposition_ledger)
        self.atom_rows = self._load_register(("promotion", "atom-register.tsv"), runmodel.load_atom_register)
        self.finding_rows = self._load_register(("findings.tsv",), runmodel.load_findings_register)

    # -- layout and lease ---------------------------------------------------

    def _check_layout(self) -> None:
        if not self._path("briefing.md").is_file():
            self._error(self._rel_path("briefing.md"), "file", "briefing.md is missing from the run layout")

    def _check_lease(self) -> None:
        lease_path = self._path("LEASE.json")
        lease_rel = self._rel_path("LEASE.json")
        active = self.run is not None and self.run.state not in _TERMINAL_STATES
        if not lease_path.is_file():
            if active:
                self._error(lease_rel, "file", "active run without LEASE.json (no live writer lease)")
            return
        lease, issues = runmodel.load_lease(lease_path)
        self._report(lease_rel, issues)
        if lease is None:
            return
        if active:
            if lease.released:
                self._error(lease_rel, "lease.released", "active run with a released writer lease")
            elif runmodel.timestamp_expired(lease.acquired_at, lease.ttl_seconds):
                self._error(lease_rel, "lease.ttl_seconds", "active run with an expired writer lease (TTL elapsed)")
        if self.run is None:
            return
        if lease.run_id != self.run.run_id:
            self._error(
                lease_rel,
                "lease.run_id",
                f"lease run_id {lease.run_id!r} does not match RUN.json {self.run.run_id!r}",
            )
        if self.run.lease_fencing_token != lease.fencing_token:
            message = (
                f"RUN.json lease_fencing_token {self.run.lease_fencing_token} "
                f"does not equal lease fencing_token {lease.fencing_token}"
            )
            self._error(self._rel_path("RUN.json"), "run.lease_fencing_token", message)

    # -- lifecycle ----------------------------------------------------------

    def _check_lifecycle(self, run: runmodel.RunState) -> None:
        run_rel = self._rel_path("RUN.json")
        if run.state == "BLOCKED" and run.blocked is None:
            self._error(run_rel, "run.blocked", "must be non-null in state BLOCKED")
        if run.state != "BLOCKED" and run.blocked is not None:
            self._error(run_rel, "run.blocked", f"must be null outside state BLOCKED (state {run.state})")
        if run.state == "RECHECK" and run.recheck is None:
            self._error(run_rel, "run.recheck", "must be non-null in state RECHECK")
        if run.state != "RECHECK" and run.recheck is not None:
            self._error(run_rel, "run.recheck", f"must be null outside state RECHECK (state {run.state})")
        self._check_digest_gates(run, run_rel)

    def _check_digest_gates(self, run: runmodel.RunState, run_rel: str) -> None:
        rank = effective_state_rank(run)
        derived, derive_issues = runmodel.derive_register_digests(self.run_dir)
        for issue in derive_issues:
            self._error(self._rel_path(issue.locator), "file", issue.message)
        for key, minimum_rank in _DIGEST_GATES:
            digest = run.register_digests.get(key)
            if digest is None:
                if rank is not None and rank >= minimum_rank:
                    self._error(run_rel, f"run.register_digests.{key}", f"must be non-null in or after state rank of {run.state}")
                continue
            expected = derived.get(key)
            if expected is None:
                self._error(
                    run_rel,
                    f"run.register_digests.{key}",
                    "pinned register digest cannot be re-derived (backing register missing or unreadable)",
                )
            elif expected != digest:
                self._error(
                    run_rel,
                    f"run.register_digests.{key}",
                    "pinned digest does not match the canonical re-derivation from the register files",
                )

    # -- rounds -------------------------------------------------------------

    def _check_rounds(self) -> None:
        rounds_dir = self._path("rounds")
        numbers: dict[int, Path] = {}
        if rounds_dir.is_dir():
            for entry in sorted(rounds_dir.iterdir()):
                match = _ROUND_DIR_RE.match(entry.name)
                if match is None or not entry.is_dir():
                    self._error(
                        self._rel_path("rounds", entry.name),
                        "file",
                        "unexpected entry in rounds/ (expected r<N> directories)",
                    )
                    continue
                numbers[int(match.group(1))] = entry
        if self.run is not None:
            for expected in range(1, self.run.current_round + 1):
                if expected not in numbers:
                    self._error(
                        self._rel_path("rounds"),
                        f"r{expected}",
                        f"round directory rounds/r{expected} is missing (current_round {self.run.current_round})",
                    )
            for number in sorted(numbers):
                if number > self.run.current_round:
                    self._error(
                        self._rel_path("rounds", f"r{number}"),
                        "dir",
                        f"round beyond RUN.json current_round {self.run.current_round}",
                    )
        for number, entry in sorted(numbers.items()):
            self._check_one_round(number, entry)

    def _check_one_round(self, number: int, round_dir: Path) -> None:
        rel = self._rel_path("rounds", round_dir.name, "ROUND.json")
        round_json = round_dir / "ROUND.json"
        if not round_json.is_file():
            self._error(rel, "file", "ROUND.json is missing")
            return
        state, issues = runmodel.load_round_state(round_json)
        self._report(rel, issues)
        if state is None:
            return
        if state.round != number:
            self._error(rel, "round.round", f"round number {state.round} does not match directory r{number}")
        if self.run is not None and state.run_id != self.run.run_id:
            self._error(rel, "round.run_id", f"run_id {state.run_id!r} does not match RUN.json {self.run.run_id!r}")
        participant_ids = {participant.participant_id for participant in state.participants}
        if self.run is not None:
            known = {participant.participant_id for participant in self.run.participants}
            for participant_id in sorted(participant_ids - known):
                self._error(rel, "round.participants", f"participant {participant_id!r} is not registered in RUN.json")
        for entry in sorted(round_dir.iterdir()):
            if entry.name == "ROUND.json":
                continue
            if not (entry.name.endswith(".md") and entry.name.removesuffix(".md") in participant_ids):
                self._error(
                    self._rel_path("rounds", round_dir.name, entry.name),
                    "file",
                    "unexpected file in a sealed round directory",
                )
        self._check_round_seal(state, number, round_dir, rel)

    def _check_round_seal(self, state: runmodel.RoundState, number: int, round_dir: Path, rel: str) -> None:
        if not state.sealed or state.seal is None:
            if self.run is not None and number < self.run.current_round:
                self._error(rel, "round.sealed", "past rounds must be sealed before later rounds are dispatched")
            return
        seal = state.seal
        received = {participant.participant_id for participant in state.participants if participant.outcome == "received"}
        for participant_id in sorted(received - set(seal.sealed_proposal_digests)):
            self._error(rel, "round.seal.sealed_proposal_digests", f"received proposal of {participant_id!r} is not sealed")
        for participant_id, digest in sorted(seal.sealed_proposal_digests.items()):
            proposal = round_dir / f"{participant_id}.md"
            proposal_rel = self._rel_path("rounds", round_dir.name, f"{participant_id}.md")
            self.sealed_proposals[proposal_rel] = digest
            if not proposal.is_file():
                self._error(proposal_rel, "file", "sealed proposal file is missing")
            elif file_digest_sha256(proposal) != digest:
                self._error(proposal_rel, "file", "sealed proposal digest does not match the file")
        for participant in state.participants:
            sealed_digest = seal.sealed_proposal_digests.get(participant.participant_id)
            receipt = participant.receipt
            if receipt is not None and sealed_digest is not None and receipt.proposal_digest != sealed_digest:
                self._error(
                    rel,
                    f"round.participants.{participant.participant_id}",
                    "receipt proposal_digest does not match the seal digest",
                )

    # -- sources and units --------------------------------------------------

    def _check_sources(self) -> None:
        if self.source_rows is None:
            return
        rel = self._rel_path("baseline", "source-register.tsv")
        source_ids = {row["source_id"] for row in self.source_rows}
        participant_ids = {participant.participant_id for participant in self.run.participants} if self.run else None
        for number, row in enumerate(self.source_rows, start=2):
            source_path = self.project_root / row["path"]
            if not source_path.is_file():
                self._error(rel, f"line {number}:path", f"source file does not exist: {row['path']}")
            elif file_digest_sha256(source_path) != row["sha256"]:
                self._error(rel, f"line {number}:sha256", f"source file digest drifted from the register: {row['path']}")
            else:
                self.verified_sources[row["source_id"]] = row["path"]
            for parent in runmodel.split_refs(row["genealogy_parents"]):
                if parent not in source_ids:
                    self._error(rel, f"line {number}:genealogy_parents", f"unknown genealogy parent {parent!r}")
            if participant_ids is not None and row["participant_id"] and row["participant_id"] not in participant_ids:
                self._error(
                    rel,
                    f"line {number}:participant_id",
                    f"participant {row['participant_id']!r} is not registered in RUN.json",
                )

    def _check_intake_closure(self) -> None:
        """Enforce set equality between the append-only intake manifest and the register."""
        if self.source_rows is None:
            return
        intake_rel = self._rel_path("baseline", "source-intake.tsv")
        intake_path = self._path("baseline", "source-intake.tsv")
        if not intake_path.is_file():
            self._error(intake_rel, "file", "append-only source intake manifest is missing (source universe unprovable)")
            return
        intake_rows, issues = runmodel.load_source_intake(intake_path)
        self._report(intake_rel, issues)
        self._report(intake_rel, runmodel.intake_chain_problems(intake_rows))
        self._check_intake_head(intake_rel, intake_rows)
        register_rel = self._rel_path("baseline", "source-register.tsv")
        intake_keys = {(row["path"], row["sha256"]): row for row in intake_rows}
        register_keys = {(row["path"], row["sha256"]): row for row in self.source_rows}
        for key in sorted(set(intake_keys) - set(register_keys)):
            self._error(register_rel, "file", f"intake entry has no source-register row: {key[0]}")
        for key in sorted(set(register_keys) - set(intake_keys)):
            self._error(intake_rel, "file", f"source-register row has no intake entry: {key[0]}")
        uuid8 = self.run.run_uuid8 if self.run is not None else None
        for number, row in enumerate(intake_rows, start=2):
            register_row = register_keys.get((row["path"], row["sha256"]))
            if register_row is not None and (row["source_phase"], row["role"]) != (
                register_row["source_phase"],
                register_row["role"],
            ):
                self._error(intake_rel, f"line {number}", f"intake phase/role disagrees with the register for {row['path']}")
            parts = row["intake_id"].split("-")
            if uuid8 is not None and len(parts) >= 3 and parts[1] != uuid8:
                self._error(intake_rel, f"line {number}:intake_id", f"id uuid8 {parts[1]!r} does not match run_uuid8 {uuid8!r}")

    def _check_intake_head(self, intake_rel: str, intake_rows: tuple[TsvRow, ...]) -> None:
        """Prove both immutable intake pins against the current chain.

        ``source_intake_input_head`` must still be an unchanged PREFIX of
        the chain (all rows up to it identical, everything after it
        ``derived``), and ``source_intake_final_head`` must be the current
        head. Pruning intake + register + recomputing the chain therefore
        cannot repair the pins.
        """
        if self.run is None:
            return
        run_rel = self._rel_path("RUN.json")
        rank = effective_state_rank(self.run)
        self._check_input_head_prefix(intake_rel, run_rel, intake_rows, rank)
        final_pin = self.run.register_digests.get("source_intake_final_head")
        if final_pin is None:
            if rank is not None and rank >= runmodel.LINEAR_STATE_RANK["PROMOTING"]:
                self._error(
                    run_rel,
                    "run.register_digests.source_intake_final_head",
                    "must pin the intake chain head before entering PROMOTING",
                )
            return
        if final_pin != runmodel.intake_head_digest(intake_rows):
            self._error(
                intake_rel,
                "file",
                "intake chain head does not match RUN.json register_digests.source_intake_final_head "
                "(entries were removed or rewritten)",
            )

    def _check_input_head_prefix(
        self, intake_rel: str, run_rel: str, intake_rows: tuple[TsvRow, ...], rank: int | None
    ) -> None:
        assert self.run is not None
        input_pin = self.run.register_digests.get("source_intake_input_head")
        if input_pin is None:
            if rank is not None and rank >= runmodel.LINEAR_STATE_RANK["SYNTHESIZING"]:
                self._error(
                    run_rel,
                    "run.register_digests.source_intake_input_head",
                    "must pin the intake chain head at the input freeze",
                )
            return
        index = runmodel.intake_prefix_head_index(intake_rows, input_pin)
        if index is None:
            self._error(
                intake_rel,
                "file",
                "pinned input intake head is not a prefix of the current chain "
                "(an input entry was removed, reordered or inserted)",
            )
            return
        # The frozen prefix must be exactly the input universe: only input
        # rows inside it, and no input row after it.
        for number, row in enumerate(intake_rows[:index], start=2):
            if row["source_phase"] != "input":
                self._error(
                    intake_rel,
                    f"line {number}:source_phase",
                    "the frozen input prefix must contain input sources only",
                )
        for number, row in enumerate(intake_rows[index:], start=index + 2):
            if row["source_phase"] != "derived":
                self._error(
                    intake_rel,
                    f"line {number}:source_phase",
                    "input sources must not be appended after the input freeze",
                )

    def _check_derived_set_closure(self) -> None:
        """Enforce set equality between canonical derived paths and derived sources."""
        if self.source_rows is None:
            return
        rel = self._rel_path("baseline", "source-register.tsv")
        on_disk: dict[str, str] = {}
        for pattern, role in _DERIVED_GLOBS:
            for entry in sorted(self.run_dir.glob(pattern)):
                if entry.is_file():
                    on_disk[f"{self.rel}/{entry.relative_to(self.run_dir).as_posix()}"] = role
        registered = {row["path"]: row for row in self.source_rows if row["source_phase"] == "derived"}
        for path in sorted(set(on_disk) - set(registered)):
            self._error(rel, "file", f"canonical derived source is not registered (omitted from the run record): {path}")
        for path in sorted(set(registered) - set(on_disk)):
            self._error(rel, "file", f"derived source is not a canonical derived path of the run: {path}")
        for path in sorted(set(on_disk) & set(registered)):
            expected_role = on_disk[path]
            if registered[path]["role"] != expected_role:
                self._error(
                    rel,
                    "file",
                    f"canonical derived path {path} must carry role {expected_role}, got {registered[path]['role']}",
                )

    def _check_input_set_closure(self) -> None:
        """Enforce input == briefing + all sealed proposals + PO inputs (loss-free)."""
        if self.source_rows is None:
            return
        rel = self._rel_path("baseline", "source-register.tsv")
        input_rows = [row for row in self.source_rows if row["source_phase"] == "input"]
        briefing_rel = self._rel_path("briefing.md")
        briefing_rows = [row for row in input_rows if row["role"] == "BRIEFING"]
        if len(briefing_rows) != 1:
            self._error(rel, "file", f"exactly one BRIEFING input source is required, found {len(briefing_rows)}")
        for row in briefing_rows:
            if row["path"] != briefing_rel:
                self._error(rel, "file", f"BRIEFING input source must be {briefing_rel}, got {row['path']}")
        proposal_rows = {row["path"]: row for row in input_rows if row["role"] == "PROPOSAL"}
        for path in sorted(set(self.sealed_proposals) - set(proposal_rows)):
            self._error(rel, "file", f"sealed proposal is missing from the input source register: {path}")
        for path, row in sorted(proposal_rows.items()):
            sealed_digest = self.sealed_proposals.get(path)
            if sealed_digest is None:
                self._error(rel, "file", f"input PROPOSAL source is not a sealed round proposal: {path}")
            elif row["sha256"] != sealed_digest:
                self._error(rel, "file", f"input PROPOSAL source digest does not match the round seal: {path}")
        for row in input_rows:
            if row["role"] not in _DERIVABLE_INPUT_ROLES:
                self._error(
                    rel,
                    "file",
                    f"input source {row['source_id']} carries role {row['role']!r}; "
                    "input sources must be the briefing, sealed proposals, or PO inputs",
                )

    def _check_baseline_rederivation(self, run: runmodel.RunState) -> None:
        """Re-derive corpus-baseline.tsv completely from the git base revision."""
        if self.baseline_rows is None:
            return
        rel = self._rel_path("baseline", "corpus-baseline.tsv")
        if run.base_revision.kind != "git":
            self.skipped.append(f"baseline-rederivation: base_revision kind {run.base_revision.kind!r} is not diffable")
            return
        revision = run.base_revision.value
        if shutil.which("git") is None or not self._git_ok("rev-parse", "--verify", f"{revision}^{{commit}}"):
            self.skipped.append("baseline-rederivation: git or the base revision is unavailable")
            return
        expected_paths: set[str] = set()
        for root in sorted(self.config.concept_roots.values()):
            listing = self._git_stdout("ls-tree", "-r", "--name-only", revision, "--", root)
            if listing is None:
                self.skipped.append(f"baseline-rederivation: git ls-tree failed for {root}")
                return
            expected_paths.update(line.replace("\\", "/") for line in listing.decode("utf-8").splitlines() if line)
        register_rows = {row["path"]: row for row in self.baseline_rows}
        for path in sorted(expected_paths - set(register_rows)):
            self._error(rel, path, "committed corpus file is missing from the baseline register (thinned)")
        for path in sorted(set(register_rows) - expected_paths):
            self._error(rel, path, "baseline row has no counterpart in the git tree of base_revision")
        for path in sorted(expected_paths & set(register_rows)):
            blob = self._git_stdout("show", f"{revision}:{path}")
            if blob is None:
                self.skipped.append(f"baseline-rederivation: git show failed for {path}")
                return
            row = register_rows[path]
            if runmodel.SHA256_RE.fullmatch(row["sha256"]) and _sha256_bytes(blob) != row["sha256"]:
                self._error(rel, path, "baseline digest does not match the committed blob of base_revision")
            if row["bytes"].isdigit() and int(row["bytes"]) != len(blob):
                self._error(rel, path, "baseline byte count does not match the committed blob of base_revision")

    def _git_ok(self, *args: str) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(self.project_root), *args], check=False, capture_output=True
        )
        return completed.returncode == 0

    def _git_stdout(self, *args: str) -> bytes | None:
        completed = subprocess.run(
            ["git", "-C", str(self.project_root), *args], check=False, capture_output=True
        )
        return completed.stdout if completed.returncode == 0 else None

    def _check_units(self) -> None:
        if self.unit_rows is None or self.source_rows is None:
            return
        rel = self._rel_path("baseline", "source-units.tsv")
        unit_ids = {row["unit_id"] for row in self.unit_rows}
        claim_ids = {row["claim_id"] for row in self.claim_rows} if self.claim_rows is not None else None
        registered: dict[str, dict[str, tuple[int, str]]] = {}
        for number, row in enumerate(self.unit_rows, start=2):
            per_source = registered.setdefault(row["source_id"], {})
            if row["unit_locator"] in per_source:
                self._error(rel, f"line {number}:unit_locator", f"duplicate unit locator {row['unit_locator']!r}")
            per_source[row["unit_locator"]] = (number, row["unit_digest"])
            self._check_unit_refs(rel, number, row, unit_ids, claim_ids)
        source_ids = {row["source_id"] for row in self.source_rows}
        for source_id in sorted(set(registered) - source_ids):
            self._error(rel, "file", f"units reference unknown source {source_id!r}")
        self._check_unit_rederivation(rel, registered)

    def _check_unit_refs(self, rel: str, number: int, row: TsvRow, unit_ids: set[str], claim_ids: set[str] | None) -> None:
        reason = row["empty_reason"]
        if reason.startswith("DUPLICATE_OF:") and reason.removeprefix("DUPLICATE_OF:") not in unit_ids:
            self._error(
                rel,
                f"line {number}:empty_reason",
                f"DUPLICATE_OF references unknown unit {reason.removeprefix('DUPLICATE_OF:')!r}",
            )
        if claim_ids is None:
            return
        for claim in runmodel.split_refs(row["claim_refs"]):
            if claim not in claim_ids:
                self._error(rel, f"line {number}:claim_refs", f"unknown claim {claim!r}")

    def _check_unit_rederivation(self, rel: str, registered: dict[str, dict[str, tuple[int, str]]]) -> None:
        for source_id, source_path in sorted(self.verified_sources.items()):
            text = (self.project_root / source_path).read_text(encoding="utf-8")
            derived = {unit.locator: unit.digest for unit in derive_units(source_path, text)}
            rows = registered.get(source_id, {})
            for locator in sorted(set(derived) - set(rows)):
                self._error(rel, "file", f"derived unit of {source_id} missing from the register (thinned): {locator}")
            for locator in sorted(set(rows) - set(derived)):
                number, _ = rows[locator]
                self._error(rel, f"line {number}:unit_locator", f"registered unit does not derive from the source: {locator}")
            for locator in sorted(set(rows) & set(derived)):
                number, digest = rows[locator]
                if digest != derived[locator]:
                    self._error(
                        rel,
                        f"line {number}:unit_digest",
                        f"unit digest does not match the re-derived partition: {locator}",
                    )

    # -- claims and ledger --------------------------------------------------

    def _check_claims(self) -> None:
        if self.claim_rows is None:
            return
        rel = self._rel_path("synthesis", "claims-inventory.tsv")
        claim_ids = {row["claim_id"] for row in self.claim_rows}
        source_ids = {row["source_id"] for row in self.source_rows} if self.source_rows is not None else None
        unit_index = {row["unit_id"] for row in self.unit_rows} if self.unit_rows is not None else None
        for number, row in enumerate(self.claim_rows, start=2):
            if source_ids is not None and row["source_id"] not in source_ids:
                self._error(rel, f"line {number}:source_id", f"unknown source {row['source_id']!r}")
            for parent in runmodel.split_refs(row["genealogy_parents"]):
                if parent not in claim_ids:
                    self._error(rel, f"line {number}:genealogy_parents", f"unknown genealogy parent {parent!r}")
            if unit_index is not None:
                for unit in runmodel.split_refs(row["unit_refs"]):
                    if unit not in unit_index:
                        self._error(rel, f"line {number}:unit_refs", f"unknown unit {unit!r}")
        self._check_claim_unit_edges(rel)

    def _check_claim_unit_edges(self, rel: str) -> None:
        if self.claim_rows is None or self.unit_rows is None:
            return
        edges_from_units = {
            (unit_row["unit_id"], claim) for unit_row in self.unit_rows for claim in runmodel.split_refs(unit_row["claim_refs"])
        }
        edges_from_claims = {
            (unit, claim_row["claim_id"]) for claim_row in self.claim_rows for unit in runmodel.split_refs(claim_row["unit_refs"])
        }
        for unit_id, claim_id in sorted(edges_from_units - edges_from_claims):
            self._error(rel, "file", f"claim {claim_id} does not list referencing unit {unit_id} in unit_refs")
        for unit_id, claim_id in sorted(edges_from_claims - edges_from_units):
            self._error(rel, "file", f"unit {unit_id} does not carry claim {claim_id} in claim_refs")

    def _check_ledger(self) -> None:
        if self.ledger_rows is None:
            return
        rel = self._rel_path("synthesis", "disposition-ledger.tsv")
        ledger_ids = {row["claim_id"] for row in self.ledger_rows}
        if self.claim_rows is not None:
            claim_ids = {row["claim_id"] for row in self.claim_rows}
            for claim_id in sorted(claim_ids - ledger_ids):
                self._error(rel, "file", f"inventory claim {claim_id} has no disposition-ledger row")
            for claim_id in sorted(ledger_ids - claim_ids):
                self._error(rel, "file", f"ledger row references unknown claim {claim_id}")
        atom_ids = {row["atom_id"] for row in self.atom_rows} if self.atom_rows is not None else None
        finding_ids = {row["finding_id"] for row in self.finding_rows} if self.finding_rows is not None else set()
        for number, row in enumerate(self.ledger_rows, start=2):
            if atom_ids is not None:
                for atom in runmodel.split_refs(row["atom_refs"]):
                    if atom not in atom_ids:
                        self._error(rel, f"line {number}:atom_refs", f"unknown atom {atom!r}")
            for finding_id in runmodel.split_refs(row["finding_refs"]):
                if finding_id not in finding_ids:
                    self._error(rel, f"line {number}:finding_refs", f"unknown finding {finding_id!r}")

    def _check_ledger_atom_edges(self) -> None:
        """Close the ledger.atom_refs / atom.claim_refs edges bidirectionally."""
        if self.ledger_rows is None or self.atom_rows is None:
            return
        ledger_rel = self._rel_path("synthesis", "disposition-ledger.tsv")
        atom_rel = self._rel_path("promotion", "atom-register.tsv")
        claim_ids = {row["claim_id"] for row in self.claim_rows} if self.claim_rows is not None else None
        atom_claims = {row["atom_id"]: set(runmodel.split_refs(row["claim_refs"])) for row in self.atom_rows}
        ledger_atoms = {row["claim_id"]: set(runmodel.split_refs(row["atom_refs"])) for row in self.ledger_rows}
        for number, row in enumerate(self.ledger_rows, start=2):
            for atom_id in sorted(runmodel.split_refs(row["atom_refs"])):
                claims_of_atom = atom_claims.get(atom_id)
                if claims_of_atom is not None and row["claim_id"] not in claims_of_atom:
                    self._error(
                        ledger_rel,
                        f"line {number}:atom_refs",
                        f"atom {atom_id} does not list claim {row['claim_id']} in claim_refs (edge not closed)",
                    )
        for number, row in enumerate(self.atom_rows, start=2):
            for claim_id in sorted(runmodel.split_refs(row["claim_refs"])):
                if claim_ids is not None and claim_id not in claim_ids:
                    self._error(atom_rel, f"line {number}:claim_refs", f"unknown claim {claim_id!r}")
                    continue
                atoms_of_claim = ledger_atoms.get(claim_id)
                if atoms_of_claim is None:
                    self._error(atom_rel, f"line {number}:claim_refs", f"claim {claim_id} has no disposition-ledger row")
                elif row["atom_id"] not in atoms_of_claim:
                    self._error(
                        atom_rel,
                        f"line {number}:claim_refs",
                        f"ledger row of claim {claim_id} does not list atom {row['atom_id']} (edge not closed)",
                    )

    def _check_findings_register(self) -> None:
        rel = self._rel_path("findings.tsv")
        if self.finding_rows is None:
            rank = effective_state_rank(self.run) if self.run is not None else None
            if rank is not None and rank >= runmodel.LINEAR_STATE_RANK["PROMOTING"]:
                self._error(rel, "file", "findings.tsv is mandatory from PROMOTING onwards (empty with header is allowed)")
            return
        claim_ids = {row["claim_id"] for row in self.claim_rows} if self.claim_rows is not None else None
        atom_ids = {row["atom_id"] for row in self.atom_rows} if self.atom_rows is not None else None
        for number, row in enumerate(self.finding_rows, start=2):
            if claim_ids is not None:
                for claim in runmodel.split_refs(row["claim_refs"]):
                    if claim not in claim_ids:
                        self._error(rel, f"line {number}:claim_refs", f"unknown claim {claim!r}")
            if atom_ids is not None:
                for atom in runmodel.split_refs(row["atom_refs"]):
                    if atom not in atom_ids:
                        self._error(rel, f"line {number}:atom_refs", f"unknown atom {atom!r}")

    # -- artifact register --------------------------------------------------

    def _check_artifact_register(self) -> None:
        main_rows = self._load_register(("artifact-register.tsv",), runmodel.load_artifact_register)
        local_rows = self._load_register(("artifact-register.local.tsv",), runmodel.load_artifact_register)
        rel = self._rel_path("artifact-register.tsv")
        if main_rows is None:
            self._error(rel, "file", "artifact-register.tsv is mandatory from FRAMING onwards (classification gate)")
        if main_rows is None and local_rows is None:
            return
        local_rel = self._rel_path("artifact-register.local.tsv")
        for row in main_rows or ():
            if row["vcs_disposition"] != "versioned":
                self._error(rel, row["path"], "the versioned main register permits only vcs_disposition versioned")
        for row in local_rows or ():
            if row["vcs_disposition"] != "local":
                self._error(local_rel, row["path"], "the local overlay permits only vcs_disposition local")
        by_path: dict[str, TsvRow] = {}
        for row in (main_rows or ()) + (local_rows or ()):
            if row["path"] in by_path:
                self._error(rel, "file", f"artifact registered twice across register and local overlay: {row['path']}")
                continue
            by_path[row["path"]] = row
        self.artifact_rows = tuple(by_path.values())
        source_paths = {row["source_id"]: row["path"] for row in self.source_rows} if self.source_rows is not None else None
        for row in self.artifact_rows:
            file_path = self.project_root / row["path"]
            if not file_path.is_file():
                self._error(rel, row["path"], "registered artifact file does not exist")
            elif file_digest_sha256(file_path) != row["sha256"]:
                self._error(rel, row["path"], "registered artifact digest does not match the file")
            for ref in runmodel.split_refs(row["input_refs"]):
                self._check_input_ref(rel, row, ref, by_path, source_paths)
        cyclic = self._check_artifact_cycles(rel, by_path)
        self._check_effective_classes(rel, by_path, cyclic, source_paths)

    def _check_input_ref(
        self, rel: str, row: TsvRow, ref: str, by_path: dict[str, TsvRow], source_paths: dict[str, str] | None
    ) -> None:
        if ref.startswith("artifact:"):
            target = ref.removeprefix("artifact:")
            if target not in by_path:
                self._error(rel, row["path"], f"input artifact is not registered: {target}")
        elif source_paths is not None and ref.removeprefix("source:") not in source_paths:
            self._error(rel, row["path"], f"input source is not registered: {ref.removeprefix('source:')}")

    def _check_artifact_cycles(self, rel: str, by_path: dict[str, TsvRow]) -> set[str]:
        colors: dict[str, int] = {}
        cyclic: set[str] = set()

        def visit(path: str, stack: tuple[str, ...]) -> None:
            colors[path] = 1
            row = by_path.get(path)
            for ref in runmodel.split_refs(row["input_refs"]) if row else ():
                if not ref.startswith("artifact:"):
                    continue
                target = ref.removeprefix("artifact:")
                if colors.get(target) == 1:
                    cycle = (*stack[stack.index(target) :], path) if target in stack else (target, path)
                    self._error(rel, path, f"provenance cycle detected: {' -> '.join((*cycle, target))}")
                    cyclic.update(cycle)
                elif colors.get(target, 0) == 0 and target in by_path:
                    visit(target, (*stack, target))
            colors[path] = 2

        for path in sorted(by_path):
            if colors.get(path, 0) == 0:
                visit(path, (path,))
        return cyclic

    def _input_class_rank(
        self, ref: str, by_path: dict[str, TsvRow], source_paths: dict[str, str] | None, effective: Callable[[str], int]
    ) -> int:
        """Rank contribution of one typed input ref (unregistered inputs count as sensitive)."""
        if ref.startswith("artifact:"):
            target = ref.removeprefix("artifact:")
            return effective(target) if target in by_path else _CLASS_RANK["sensitive"]
        source_path = (source_paths or {}).get(ref.removeprefix("source:"))
        if source_path is not None and source_path in by_path:
            return effective(source_path)
        return _CLASS_RANK["sensitive"]

    def _check_effective_classes(
        self, rel: str, by_path: dict[str, TsvRow], cyclic: set[str], source_paths: dict[str, str] | None
    ) -> None:
        memo: dict[str, int] = {}

        def effective(path: str) -> int:
            if path in memo:
                return memo[path]
            row = by_path[path]
            memo[path] = _CLASS_RANK[row["effective_class"]]
            return memo[path]

        for path in sorted(by_path):
            row = by_path[path]
            if path in cyclic:
                continue
            if row["declassification_receipt"]:
                self._check_declassified_row(rel, row, by_path, source_paths)
                continue
            rank = _CLASS_RANK[row["declared_class"]]
            for ref in runmodel.split_refs(row["input_refs"]):
                rank = max(rank, self._input_class_rank(ref, by_path, source_paths, effective))
            if _CLASS_RANK[row["effective_class"]] != rank:
                expected = next(name for name, value in _CLASS_RANK.items() if value == rank)
                self._error(rel, path, f"effective_class must be the maximum of declared and input classes ({expected})")

    def _resolve_input_paths(self, row: TsvRow, source_paths: dict[str, str] | None) -> set[str]:
        paths: set[str] = set()
        for ref in runmodel.split_refs(row["input_refs"]):
            if ref.startswith("artifact:"):
                paths.add(ref.removeprefix("artifact:"))
            else:
                source_path = (source_paths or {}).get(ref.removeprefix("source:"))
                if source_path is not None:
                    paths.add(source_path)
        return paths

    def _check_declassified_row(
        self, rel: str, row: TsvRow, by_path: dict[str, TsvRow], source_paths: dict[str, str] | None
    ) -> None:
        receipt_path = self.project_root / row["declassification_receipt"]
        if not receipt_path.is_file():
            self._error(rel, row["path"], f"declassification receipt does not exist: {row['declassification_receipt']}")
            return
        receipt, issues = runmodel.load_declassification_receipt(receipt_path)
        self._report(row["declassification_receipt"], issues)
        if receipt is None:
            return
        if receipt.output_path != row["path"]:
            self._error(rel, row["path"], f"declassification receipt is bound to {receipt.output_path!r}, not this artifact")
        if receipt.output_digest != row["sha256"]:
            self._error(rel, row["path"], "declassification receipt output digest does not match the registered artifact")
        if receipt.target_class != row["effective_class"]:
            self._error(
                rel,
                row["path"],
                f"effective_class must equal the declassification target class {receipt.target_class!r}",
            )
        input_paths = self._resolve_input_paths(row, source_paths)
        if receipt.source_path not in input_paths:
            self._error(
                rel,
                row["path"],
                f"declassification source_path {receipt.source_path!r} is not an input of this artifact",
            )
            return
        source_row = by_path.get(receipt.source_path)
        expected_digest = source_row["sha256"] if source_row is not None else None
        if expected_digest is None:
            source_file = self.project_root / receipt.source_path
            expected_digest = file_digest_sha256(source_file) if source_file.is_file() else None
        if expected_digest is None:
            self._error(rel, row["path"], f"declassification source {receipt.source_path!r} cannot be digest-verified")
        elif receipt.source_digest != expected_digest:
            self._error(rel, row["path"], "declassification source_digest does not match the input source")

    # -- coverage plan and registers ----------------------------------------

    def _check_coverage_plan(self, run: runmodel.RunState) -> None:
        plan_path = self._path("baseline", "coverage-plan.json")
        rel = self._rel_path("baseline", "coverage-plan.json")
        rank = effective_state_rank(run)
        if not plan_path.is_file():
            if run.profile == "FULL_ATOM" and rank is not None and rank >= 1:
                self._error(rel, "file", "FULL_ATOM requires a frozen coverage-plan.json before STAFFING")
            return
        plan, issues = runmodel.load_coverage_plan(plan_path)
        self._report(rel, issues)
        if plan is None:
            return
        if plan.run_id != run.run_id:
            self._error(rel, "plan.run_id", f"run_id {plan.run_id!r} does not match RUN.json {run.run_id!r}")
        package_ids = {package.package_id for package in plan.packages}
        if plan.integration_package_id not in package_ids:
            self._error(
                rel,
                "plan.integration_package_id",
                f"integration package {plan.integration_package_id!r} is not declared",
            )
        known_participants = {participant.participant_id for participant in run.participants}
        for package in plan.packages:
            for participant_id in package.assigned_participants:
                if participant_id not in known_participants:
                    self._error(
                        rel,
                        f"plan.packages.{package.package_id}",
                        f"assigned participant {participant_id!r} is not registered",
                    )
            if len(package.assigned_participants) < package.redundancy:
                self._error(
                    rel,
                    f"plan.packages.{package.package_id}",
                    f"declared redundancy {package.redundancy} is not staffed",
                )
        self._check_coverage_matrix(rel, plan, package_ids)

    def _check_coverage_matrix(self, rel: str, plan: runmodel.CoveragePlan, package_ids: set[str]) -> None:
        if self.baseline_rows is None:
            return
        matchers = [glob_to_regex(pattern) for package in plan.packages for pattern in package.paths]
        baseline_rel = self._rel_path("baseline", "corpus-baseline.tsv")
        for number, row in enumerate(self.baseline_rows, start=2):
            package_id = row["package_id"]
            if package_id and package_id != "EXEMPT" and package_id not in package_ids:
                self._error(baseline_rel, f"line {number}:package_id", f"unknown coverage package {package_id!r}")
            if package_id == "EXEMPT":
                continue
            if not any(matcher.match(row["path"]) for matcher in matchers):
                self._error(rel, "plan.packages", f"baseline path is not covered by any package and not EXEMPT: {row['path']}")

    def _check_coverage_registers(self) -> None:
        source_cov = self._load_register(("baseline", "source-coverage.tsv"), runmodel.load_source_coverage)
        finding_ids = {row["finding_id"] for row in self.finding_rows} if self.finding_rows is not None else set()
        if source_cov is not None:
            rel = self._rel_path("baseline", "source-coverage.tsv")
            authors = {row["source_id"]: row["author_principal_id"] for row in self.source_rows or ()}
            source_ids = set(authors) if self.source_rows is not None else None
            for number, row in enumerate(source_cov, start=2):
                if source_ids is not None and row["source_id"] not in source_ids:
                    self._error(rel, f"line {number}:source_id", f"unknown source {row['source_id']!r}")
                author = authors.get(row["source_id"], "")
                if author and row["reviewer_principal_id"] == author:
                    self._error(rel, f"line {number}:reviewer_principal_id", "reviewer must not be the source author")
                for finding_id in runmodel.split_refs(row["finding_refs"]):
                    if finding_id not in finding_ids:
                        self._error(rel, f"line {number}:finding_refs", f"unknown finding {finding_id!r}")
        normative_cov = self._load_register(("baseline", "normative-coverage.tsv"), runmodel.load_normative_coverage)
        if normative_cov is not None:
            rel = self._rel_path("baseline", "normative-coverage.tsv")
            for number, row in enumerate(normative_cov, start=2):
                for finding_id in runmodel.split_refs(row["finding_refs"]):
                    if finding_id not in finding_ids:
                        self._error(rel, f"line {number}:finding_refs", f"unknown finding {finding_id!r}")

    # -- promotion-side schemas ---------------------------------------------

    def _check_promotion_artifacts(self) -> None:
        manifest_path = self._path("promotion", "promotion-manifest.json")
        if manifest_path.is_file():
            manifest, issues = runmodel.load_promotion_manifest(manifest_path)
            self._report(self._rel_path("promotion", "promotion-manifest.json"), issues)
            if manifest is not None and self.run is not None and manifest.run_id != self.run.run_id:
                self._error(
                    self._rel_path("promotion", "promotion-manifest.json"),
                    "manifest.run_id",
                    f"run_id {manifest.run_id!r} does not match RUN.json {self.run.run_id!r}",
                )
        receipts_dir = self._path("promotion", "receipts")
        if receipts_dir.is_dir():
            for entry in sorted(receipts_dir.glob("*.json")):
                rel = self._rel_path("promotion", "receipts", entry.name)
                receipt, issues = runmodel.load_projection_receipt(entry)
                self._report(rel, issues)
                if receipt is not None and entry.name != f"{receipt.receipt_id}.json":
                    self._error(rel, "receipt.receipt_id", f"filename must be <receipt_id>.json for {receipt.receipt_id}")

    def _check_declassification_receipts(self) -> None:
        declass_dir = self._path("declassification")
        if not declass_dir.is_dir():
            return
        for entry in sorted(declass_dir.glob("*.json")):
            rel = self._rel_path("declassification", entry.name)
            receipt, issues = runmodel.load_declassification_receipt(entry)
            self._report(rel, issues)
            if receipt is not None and entry.name != f"{receipt.receipt_id}.json":
                self._error(rel, "receipt.receipt_id", f"filename must be <receipt_id>.json for {receipt.receipt_id}")

    # -- run-scoped id namespace --------------------------------------------

    def _check_id_namespace(self) -> None:
        if self.run is None:
            return
        uuid8 = self.run.run_uuid8
        registers: tuple[tuple[str, tuple[TsvRow, ...] | None, str], ...] = (
            ("baseline/source-register.tsv", self.source_rows, "source_id"),
            ("baseline/source-units.tsv", self.unit_rows, "unit_id"),
            ("synthesis/claims-inventory.tsv", self.claim_rows, "claim_id"),
            ("promotion/atom-register.tsv", self.atom_rows, "atom_id"),
            ("findings.tsv", self.finding_rows, "finding_id"),
        )
        for register_rel, rows, column in registers:
            for number, row in enumerate(rows or (), start=2):
                parts = row[column].split("-")
                if len(parts) >= 3 and parts[1] != uuid8:
                    self._error(
                        f"{self.rel}/{register_rel}",
                        f"line {number}:{column}",
                        f"id uuid8 {parts[1]!r} does not match run_uuid8 {uuid8!r}",
                    )
