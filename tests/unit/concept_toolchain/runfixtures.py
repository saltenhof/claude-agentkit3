"""Builders for realistic incubation-run fixtures (real artifacts, no mocks).

Constructs a complete LIGHT_INCUBATION run in PROMOTING state on top of the
``green_corpus`` project layout: sealed round, source/unit/claim/ledger
registers derived with the production partition code, atom register,
projection receipt, promotion manifest, scope lock, and coverage
registers — everything digest-consistent so the incubator and promotion
checks pass, and tests can tamper with exactly one aspect at a time.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from concept_toolchain import runmodel
from concept_toolchain.receipts import compute_target_digest
from concept_toolchain.units import derive_units, section_index, text_digest

if TYPE_CHECKING:
    from pathlib import Path

TAB = chr(9)
LF = chr(10)

RUN_UUID8 = "ab12cd34"
RUN_ID = f"2026-07-19-mini-{RUN_UUID8}"
NOW = "2026-07-19T10:00:00Z"
SCOPE_ID = "sample-scope"
ATOM_STATEMENT = "The sample component must log every rejection."
TARGET_REL = "concept/technical-design/10_sample.md"

#: CLI identity of the fixture's lease owner (semantic_gate writer gate).
WRITER_ARGS = ("--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "1")

SRC_BRIEFING = f"SRC-{RUN_UUID8}-0001"
SRC_PROPOSAL = f"SRC-{RUN_UUID8}-0002"
SRC_SYNTHESIS = f"SRC-{RUN_UUID8}-0003"
SRC_DISSENT = f"SRC-{RUN_UUID8}-0004"
CLAIM_ID = f"CLM-{RUN_UUID8}-0001"
ATOM_ID = f"ATM-{RUN_UUID8}-0001"
RECEIPT_ID = f"RCP-{RUN_UUID8}-0001"

_LAYER_BY_ROOT = {
    "concept/domain-design": "domain",
    "concept/technical-design": "technical",
    "concept/formal-spec": "formal",
    "concept/_meta": "meta",
    "guardrails": "guardrails",
}


def sha_file(path: Path) -> str:
    """Return the sha256 of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_utc() -> str:
    """Return the current UTC timestamp in the toolchain's ``Z`` format."""
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: object) -> None:
    """Write a JSON artifact with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_tsv(path: Path, header: str, rows: list[list[str]]) -> None:
    """Write a TSV register (rows must already be sorted by their ID column)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header, *("\t".join(row) for row in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def git(project_root: Path, *args: str) -> str:
    """Run git in the fixture repository (byte-exact blobs, no CRLF smudging)."""
    completed = subprocess.run(
        ["git", "-C", str(project_root), "-c", "user.name=fixture", "-c", "user.email=fixture@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


@dataclass
class RunFixture:
    """Handles into one generated promotion-ready run."""

    project_root: Path
    run_dir: Path
    run_id: str = RUN_ID
    uuid8: str = RUN_UUID8
    scope_id: str = SCOPE_ID
    target_rel: str = TARGET_REL
    base_revision: dict[str, str] = field(default_factory=dict)
    baseline_digests: dict[str, str] = field(default_factory=dict)
    baseline_sizes: dict[str, int] = field(default_factory=dict)

    @property
    def run_rel(self) -> str:
        return self.run_dir.relative_to(self.project_root).as_posix()

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "promotion" / "promotion-manifest.json"

    @property
    def receipt_path(self) -> Path:
        return self.run_dir / "promotion" / "receipts" / f"{RECEIPT_ID}.json"

    @property
    def atom_register_path(self) -> Path:
        return self.run_dir / "promotion" / "atom-register.tsv"

    @property
    def units_path(self) -> Path:
        return self.run_dir / "baseline" / "source-units.tsv"

    @property
    def lock_path(self) -> Path:
        return self.project_root / "concept-incubator" / "locks" / runmodel.scope_lock_filename(self.scope_id)

    def read_manifest(self) -> dict[str, object]:
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        return payload

    def write_manifest(self, payload: dict[str, object]) -> None:
        write_json(self.manifest_path, payload)

    def read_run(self) -> dict[str, object]:
        payload = json.loads((self.run_dir / "RUN.json").read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        return payload

    def write_run(self, payload: dict[str, object]) -> None:
        write_json(self.run_dir / "RUN.json", payload)

    def repin_registers(self, *, repin_input_head: bool = False) -> None:
        """Re-pin the register digests in RUN.json after touching registers.

        ``source_intake_input_head`` is immutable once set, so a correct
        writer never moves it; pass ``repin_input_head=True`` to emulate an
        attacker who also recomputes the frozen pin.
        """
        payload = self.read_run()
        digests = payload["register_digests"]
        assert isinstance(digests, dict)
        derived, issues = runmodel.derive_register_digests(self.run_dir)
        assert issues == [], issues
        frozen = None if repin_input_head else digests.get("source_intake_input_head")
        for key, value in derived.items():
            if value is not None:
                digests[key] = value
        if frozen is not None:
            digests["source_intake_input_head"] = frozen
        self.write_run(payload)


def refresh_normative_coverage(fixture: RunFixture) -> None:
    """Re-derive the final normative coverage register over baseline union current."""
    current: dict[str, str] = {}
    for root_rel in _LAYER_BY_ROOT:
        root = fixture.project_root / root_rel
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("*")):
            if entry.is_file():
                current[entry.relative_to(fixture.project_root).as_posix()] = sha_file(entry)
    rows: list[list[str]] = []
    for path in sorted(set(fixture.baseline_digests) | set(current)):
        baseline = fixture.baseline_digests.get(path)
        now = current.get(path)
        if baseline is None:
            kind = "added"
        elif now is None:
            kind = "removed"
        else:
            kind = "unchanged" if baseline == now else "modified"
        if kind == "unchanged":
            continue
        rows.append(
            [
                path,
                baseline or "",
                now or "",
                kind,
                "PASS",
                f"{fixture.run_rel}/synthesis/synthesis-r1.md",
                "rev.bob",
                "",
            ]
        )
    write_tsv(
        fixture.run_dir / "baseline" / "normative-coverage.tsv",
        "path	baseline_sha256	current_sha256	change_kind	review_status	review_artifact	reviewer_principal_id	finding_refs",
        rows,
    )


def refresh_target_bindings(fixture: RunFixture) -> None:
    """Re-bind manifest, receipt and coverage digests after editing the target."""
    target = fixture.project_root / fixture.target_rel
    current_digest = sha_file(target)
    manifest = fixture.read_manifest()
    targets = manifest["targets"]
    assert isinstance(targets, list)
    for entry in targets:
        if isinstance(entry, dict) and entry.get("path") == fixture.target_rel:
            entry["after_sha256"] = current_digest
    fixture.write_manifest(manifest)
    receipt = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    sections = section_index(fixture.target_rel, target.read_text(encoding="utf-8"))
    receipt["target_section_digest"] = sections["promoted-addition"].digest
    write_json(fixture.receipt_path, receipt)
    coverage = fixture.run_dir / "baseline" / "normative-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    for index, line in enumerate(lines[1:], start=1):
        fields = line.split("\t")
        if fields[0] == fixture.target_rel:
            fields[2] = current_digest
            lines[index] = "\t".join(fields)
    coverage.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_promotion_run(project_root: Path, *, use_git: bool = True) -> RunFixture:
    """Build a digest-consistent PROMOTING run on top of a green corpus."""
    _write_projection_manifest(project_root)
    baseline_digests, baseline_sizes = _collect_baseline(project_root)
    if use_git:
        git(project_root, "init", "-q")
        git(project_root, "add", "-A")
        git(project_root, "commit", "-q", "-m", "baseline")
        base_revision = {"kind": "git", "value": git(project_root, "rev-parse", "HEAD")}
    else:
        base_revision = {"kind": "digest", "value": hashlib.sha256(b"baseline").hexdigest()}
    target = project_root / TARGET_REL
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n## Promoted Addition\n\n{ATOM_STATEMENT}\n",
        encoding="utf-8",
        newline="\n",
    )
    run_dir = project_root / "concept-incubator" / "runs" / RUN_ID
    fixture = RunFixture(
        project_root=project_root,
        run_dir=run_dir,
        base_revision=base_revision,
        baseline_digests=baseline_digests,
        baseline_sizes=baseline_sizes,
    )
    _write_run_sources(fixture)
    _write_round(fixture)
    _write_registers(fixture)
    _write_promotion(fixture)
    _write_lock(fixture)
    _write_run_state(fixture)
    _write_lease(fixture)
    return fixture


def _write_projection_manifest(project_root: Path) -> None:
    manifest_path = project_root / "concept" / "_meta" / "projection-manifest.json"
    if not manifest_path.is_file():
        write_json(manifest_path, {"schema_version": "1.0.0", "entries": []})


def _collect_baseline(project_root: Path) -> tuple[dict[str, str], dict[str, int]]:
    digests: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for root_rel in _LAYER_BY_ROOT:
        root = project_root / root_rel
        if not root.is_dir():
            continue
        for entry in sorted(root.rglob("*")):
            if entry.is_file():
                rel = entry.relative_to(project_root).as_posix()
                digests[rel] = sha_file(entry)
                sizes[rel] = len(entry.read_bytes())
    return digests, sizes


def _write_run_sources(fixture: RunFixture) -> None:
    run_dir = fixture.run_dir
    (run_dir / "rounds" / "r1").mkdir(parents=True, exist_ok=True)
    (run_dir / "synthesis").mkdir(parents=True, exist_ok=True)
    (run_dir / "briefing.md").write_text("# Briefing\n\nAnalyze the sample corpus.\n", encoding="utf-8", newline="\n")
    (run_dir / "rounds" / "r1" / "worker-one.md").write_text(
        f"# Proposal\n\n{ATOM_STATEMENT}\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "synthesis" / "synthesis-r1.md").write_text(
        f"# Synthesis\n\n{ATOM_STATEMENT}\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "synthesis" / "dissent-map.md").write_text(
        "# Dissent Map\n\nNo open dissent in this run.\n", encoding="utf-8", newline="\n"
    )


def _write_round(fixture: RunFixture) -> None:
    proposal_digest = sha_file(fixture.run_dir / "rounds" / "r1" / "worker-one.md")
    write_json(
        fixture.run_dir / "rounds" / "r1" / "ROUND.json",
        {
            "schema_version": "1.0.0",
            "run_id": fixture.run_id,
            "round": 1,
            "participants": [
                {
                    "participant_id": "worker-one",
                    "dispatch": {
                        "sent_at": NOW,
                        "prompt_digest": hashlib.sha256(b"prompt").hexdigest(),
                        "input_digests": [],
                    },
                    "receipt": {"received_at": NOW, "proposal_digest": proposal_digest},
                    "outcome": "received",
                    "outcome_reason": "",
                }
            ],
            "sealed": True,
            "seal": {"sealed_at": NOW, "sealed_proposal_digests": {"worker-one": proposal_digest}},
        },
    )


def _source_specs(fixture: RunFixture) -> list[tuple[str, str, str, str, str, str, str]]:
    rel = fixture.run_rel
    return [
        (SRC_BRIEFING, "input", "BRIEFING", f"{rel}/briefing.md", "", "", "orch.alice"),
        (SRC_PROPOSAL, "input", "PROPOSAL", f"{rel}/rounds/r1/worker-one.md", "1", "worker-one", "p.worker"),
        (SRC_SYNTHESIS, "derived", "SYNTHESIS", f"{rel}/synthesis/synthesis-r1.md", "", "", "orch.alice"),
        (SRC_DISSENT, "derived", "DISSENT_MAP", f"{rel}/synthesis/dissent-map.md", "", "", "orch.alice"),
    ]


def write_intake(fixture: RunFixture, register_rows: list[list[str]]) -> None:
    """Write the append-only, hash-chained intake manifest for the register rows."""
    rows: list[list[str]] = []
    prev = runmodel.INTAKE_GENESIS_DIGEST
    for index, row in enumerate(register_rows, start=1):
        fields = {
            "intake_id": f"INT-{fixture.uuid8}-{index}",
            "source_phase": row[1],
            "role": row[2],
            "path": row[3],
            "sha256": row[4],
            "registered_at": NOW,
            "prev_digest": prev,
        }
        entry = runmodel.intake_entry_digest(fields)
        rows.append([*fields.values(), entry])
        prev = entry
    write_tsv(fixture.run_dir / "baseline" / "source-intake.tsv", runmodel.SOURCE_INTAKE_HEADER, rows)


def add_mode_atoms(fixture: RunFixture) -> None:
    """Add one COVERED_EXACT atom + receipt for each non-markdown target mode."""
    specs = [
        ("0002", "whole-file", "concept/_meta/concept-governance.json", None, "Governance config must exist."),
        ("0003", "directory-tree", "concept/formal-spec/sample", None, "The sample formal context must exist."),
        (
            "0004",
            "structured-selector",
            "concept/_meta/concept-governance.json",
            "concept_roots",
            "Concept roots must be declared.",
        ),
    ]
    rows: list[str] = []
    atom_ids: list[str] = []
    for suffix, mode, target_rel, selector, statement in specs:
        atom_id = "ATM-" + fixture.uuid8 + "-" + suffix
        receipt_id = "RCP-" + fixture.uuid8 + "-" + suffix
        atom_ids.append(atom_id)
        rows.append(
            TAB.join(
                [
                    atom_id,
                    statement,
                    "REQUIREMENT",
                    "",
                    "accepted",
                    fixture.scope_id,
                    target_rel,
                    "COVERED_EXACT",
                    "",
                    CLAIM_ID,
                    receipt_id,
                ]
            )
        )
        result = compute_target_digest(fixture.project_root, target_rel, mode, selector)
        assert result.digest is not None, (target_rel, mode, selector, result)
        write_json(
            fixture.run_dir / "promotion" / "receipts" / (receipt_id + ".json"),
            {
                "schema_version": "1.0.0",
                "receipt_id": receipt_id,
                "atom_id": atom_id,
                "target": {"path": target_rel, "anchor": ""},
                "target_mode": mode,
                "selector": selector,
                "source_digest": text_digest(statement),
                "target_section_digest": result.digest,
                "writer_principal_id": "p.writer",
                "writer_session_ref": "sess-writer",
                "reviewer_principal_id": "p.reviewer",
                "reviewer_session_ref": "sess-reviewer",
                "verdict": "equivalent",
                "reviewed_at": NOW,
            },
        )
    register = fixture.atom_register_path
    register.write_text(register.read_text(encoding="utf-8") + LF.join(rows) + LF, encoding="utf-8", newline=LF)
    ledger = fixture.run_dir / "synthesis" / "disposition-ledger.tsv"
    lines = ledger.read_text(encoding="utf-8").rstrip(LF).split(LF)
    fields = lines[1].split(TAB)
    fields[4] = ";".join(sorted({*fields[4].split(";"), *atom_ids}))
    lines[1] = TAB.join(fields)
    ledger.write_text(LF.join(lines) + LF, encoding="utf-8", newline=LF)
    fixture.repin_registers()


def add_whole_file_atom(
    fixture: RunFixture, *, atom_id: str, receipt_id: str, statement: str, target_rel: str
) -> None:
    """Add a second COVERED_EXACT atom + receipt addressing a whole file."""
    register = fixture.atom_register_path
    row = TAB.join(
        [
            atom_id,
            statement,
            "REQUIREMENT",
            "",
            "accepted",
            fixture.scope_id,
            target_rel,
            "COVERED_EXACT",
            "",
            CLAIM_ID,
            receipt_id,
        ]
    )
    register.write_text(register.read_text(encoding="utf-8") + row + LF, encoding="utf-8", newline=LF)
    ledger = fixture.run_dir / "synthesis" / "disposition-ledger.tsv"
    lines = ledger.read_text(encoding="utf-8").rstrip(LF).split(LF)
    fields = lines[1].split(TAB)
    fields[4] = ";".join(sorted({*fields[4].split(";"), atom_id}))
    lines[1] = TAB.join(fields)
    ledger.write_text(LF.join(lines) + LF, encoding="utf-8", newline=LF)
    write_json(
        fixture.run_dir / "promotion" / "receipts" / (receipt_id + ".json"),
        {
            "schema_version": "1.0.0",
            "receipt_id": receipt_id,
            "atom_id": atom_id,
            "target": {"path": target_rel, "anchor": ""},
            "target_mode": "whole-file",
            "selector": None,
            "source_digest": text_digest(statement),
            "target_section_digest": sha_file(fixture.project_root / target_rel),
            "writer_principal_id": "p.writer",
            "writer_session_ref": "sess-writer",
            "reviewer_principal_id": "p.reviewer",
            "reviewer_session_ref": "sess-reviewer",
            "verdict": "equivalent",
            "reviewed_at": NOW,
        },
    )
    manifest = fixture.read_manifest()
    targets = manifest["targets"]
    assert isinstance(targets, list)
    targets.append(
        {
            "path": target_rel,
            "before_sha256": fixture.baseline_digests.get(target_rel),
            "after_sha256": sha_file(fixture.project_root / target_rel),
        }
    )
    fixture.write_manifest(manifest)
    fixture.repin_registers()


def append_intake_entry(
    fixture: RunFixture, *, intake_id: str, source_phase: str, role: str, path: str, sha256: str
) -> None:
    """Append one properly chained intake entry and re-pin the head."""
    intake_path = fixture.run_dir / "baseline" / "source-intake.tsv"
    rows, _ = runmodel.load_source_intake(intake_path)
    fields = {
        "intake_id": intake_id,
        "source_phase": source_phase,
        "role": role,
        "path": path,
        "sha256": sha256,
        "registered_at": NOW,
        "prev_digest": runmodel.intake_head_digest(rows),
    }
    entry = runmodel.intake_entry_digest(fields)
    line = "	".join([*fields.values(), entry])
    intake_path.write_text(intake_path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8", newline="\n")
    fixture.repin_registers()


def _write_registers(fixture: RunFixture) -> None:
    project_root, run_dir = fixture.project_root, fixture.run_dir
    baseline_rows = [
        [path, str(fixture.baseline_sizes[path]), digest, _layer_for(path), ""]
        for path, digest in sorted(fixture.baseline_digests.items())
    ]
    write_tsv(run_dir / "baseline" / "corpus-baseline.tsv", "path\tbytes\tsha256\tlayer\tpackage_id", baseline_rows)
    specs = _source_specs(fixture)
    register_rows = []
    for index, (source_id, phase, role, path, round_no, participant, author) in enumerate(specs):
        genealogy = "" if index == 0 else specs[index - 1][0]
        register_rows.append(
            [source_id, phase, role, path, sha_file(project_root / path), round_no, participant, author, genealogy]
        )
    write_tsv(
        run_dir / "baseline" / "source-register.tsv",
        "source_id\tsource_phase\trole\tpath\tsha256\tround\tparticipant_id\tauthor_principal_id\tgenealogy_parents",
        register_rows,
    )
    write_intake(fixture, register_rows)
    unit_rows = _build_unit_rows(fixture, specs)
    write_tsv(
        run_dir / "baseline" / "source-units.tsv",
        "unit_id\tsource_id\tunit_locator\tunit_digest\tclaim_refs\tempty_reason",
        unit_rows,
    )
    claim_units = sorted(row[0] for row in unit_rows if row[4] == CLAIM_ID)
    proposal_locator = next(row[2] for row in unit_rows if row[1] == SRC_PROPOSAL)
    write_tsv(
        run_dir / "synthesis" / "claims-inventory.tsv",
        "claim_id\tsource_id\tunit_refs\tsource_locator\tstatement\tqualifiers\tgenealogy_parents",
        [[CLAIM_ID, SRC_PROPOSAL, ";".join(claim_units), proposal_locator, ATOM_STATEMENT, "", ""]],
    )
    write_tsv(
        run_dir / "synthesis" / "disposition-ledger.tsv",
        "claim_id\tsynthesis_disposition\tdisposition_reason\tresidual_edge\tatom_refs\tfinding_refs",
        [[CLAIM_ID, "ADOPTED", "", "", ATOM_ID, ""]],
    )
    write_tsv(
        run_dir / "findings.tsv",
        "finding_id\tseverity\tstatus\tclaim_refs\tatom_refs\tpath\tlocator\tstatement\tresolution",
        [],
    )
    _write_artifact_register(fixture)
    _write_coverage_registers(fixture, register_rows)


def _build_unit_rows(fixture: RunFixture, specs: list[tuple[str, str, str, str, str, str, str]]) -> list[list[str]]:
    rows: list[list[str]] = []
    counter = 0
    for source_id, _phase, _role, path, _round, _participant, _author in specs:
        text = (fixture.project_root / path).read_text(encoding="utf-8")
        for unit in derive_units(path, text):
            counter += 1
            material = ATOM_STATEMENT in unit.text
            rows.append(
                [
                    f"SU-{fixture.uuid8}-{counter:04d}",
                    source_id,
                    unit.locator,
                    unit.digest,
                    CLAIM_ID if material else "",
                    "" if material else "NO_MATERIAL_CONTENT",
                ]
            )
    return rows


def _write_artifact_register(fixture: RunFixture) -> None:
    rel = fixture.run_rel
    rows = sorted(
        [
            [
                f"{rel}/briefing.md",
                sha_file(fixture.run_dir / "briefing.md"),
                "briefing",
                "",
                "internal",
                "internal",
                "versioned",
                "",
            ],
            [
                f"{rel}/rounds/r1/worker-one.md",
                sha_file(fixture.run_dir / "rounds" / "r1" / "worker-one.md"),
                "proposal",
                f"source:{SRC_BRIEFING}",
                "internal",
                "internal",
                "versioned",
                "",
            ],
            [
                f"{rel}/synthesis/synthesis-r1.md",
                sha_file(fixture.run_dir / "synthesis" / "synthesis-r1.md"),
                "synthesis",
                f"artifact:{rel}/rounds/r1/worker-one.md",
                "internal",
                "internal",
                "versioned",
                "",
            ],
            [
                f"{rel}/synthesis/dissent-map.md",
                sha_file(fixture.run_dir / "synthesis" / "dissent-map.md"),
                "dissent_map",
                f"artifact:{rel}/synthesis/synthesis-r1.md",
                "internal",
                "internal",
                "versioned",
                "",
            ],
        ]
    )
    write_tsv(
        fixture.run_dir / "artifact-register.tsv",
        "path\tsha256\tartifact_kind\tinput_refs\tdeclared_class\teffective_class\tvcs_disposition\tdeclassification_receipt",
        rows,
    )


def _write_coverage_registers(fixture: RunFixture, register_rows: list[list[str]]) -> None:
    source_cov = [
        [row[0], row[4], "PASS", f"{fixture.run_rel}/synthesis/synthesis-r1.md", "rev.bob", ""] for row in register_rows
    ]
    write_tsv(
        fixture.run_dir / "baseline" / "source-coverage.tsv",
        "source_id\tsha256\treview_status\treview_artifact\treviewer_principal_id\tfinding_refs",
        source_cov,
    )
    target = fixture.project_root / fixture.target_rel
    write_tsv(
        fixture.run_dir / "baseline" / "normative-coverage.tsv",
        "path\tbaseline_sha256\tcurrent_sha256\tchange_kind\treview_status\treview_artifact\treviewer_principal_id\tfinding_refs",
        [
            [
                fixture.target_rel,
                fixture.baseline_digests[fixture.target_rel],
                sha_file(target),
                "modified",
                "PASS",
                f"{fixture.run_rel}/synthesis/synthesis-r1.md",
                "rev.bob",
                "",
            ]
        ],
    )


def _write_promotion(fixture: RunFixture) -> None:
    target = fixture.project_root / fixture.target_rel
    write_tsv(
        fixture.atom_register_path,
        "atom_id\tstatement\tatom_type\tqualifiers\tnormative_status\texpected_authority\ttarget_refs\tdisposition\tdeferral\tclaim_refs\treceipt_refs",
        [
            [
                ATOM_ID,
                ATOM_STATEMENT,
                "REQUIREMENT",
                "",
                "accepted",
                fixture.scope_id,
                f"{fixture.target_rel}#promoted-addition",
                "COVERED_EXACT",
                "",
                CLAIM_ID,
                RECEIPT_ID,
            ]
        ],
    )
    sections = section_index(fixture.target_rel, target.read_text(encoding="utf-8"))
    write_json(
        fixture.receipt_path,
        {
            "schema_version": "1.0.0",
            "receipt_id": RECEIPT_ID,
            "atom_id": ATOM_ID,
            "target": {"path": fixture.target_rel, "anchor": "promoted-addition"},
            "target_mode": "markdown-section",
            "selector": None,
            "source_digest": text_digest(ATOM_STATEMENT),
            "target_section_digest": sections["promoted-addition"].digest,
            "writer_principal_id": "p.writer",
            "writer_session_ref": "sess-writer",
            "reviewer_principal_id": "p.reviewer",
            "reviewer_session_ref": "sess-reviewer",
            "verdict": "equivalent",
            "reviewed_at": NOW,
        },
    )
    fixture.write_manifest(
        {
            "schema_version": "1.0.0",
            "run_id": fixture.run_id,
            "base_revision": dict(fixture.base_revision),
            "scopes": [{"scope_id": fixture.scope_id, "promotion_disposition": "promoted", "blockers": []}],
            "required_decision_ids": [],
            "required_concept_ids": ["FK-10"],
            "required_formal_ids": [],
            "required_registry_edges": [],
            "required_support_paths": [],
            "required_test_oracles": [],
            "targets": [
                {
                    "path": fixture.target_rel,
                    "before_sha256": fixture.baseline_digests[fixture.target_rel],
                    "after_sha256": sha_file(target),
                }
            ],
            "receipts_dir": "promotion/receipts",
            "scope_locks": [
                {"scope_id": fixture.scope_id, "locked_by_run": fixture.run_id, "fencing_token": 7, "backend": "filesystem"}
            ],
            "semantic_gates": [
                {"gate": "authority-prose", "status": "passed", "receipt_path": None, "blocking_scope_ids": []},
                {"gate": "scope-consistency", "status": "passed", "receipt_path": None, "blocking_scope_ids": []},
            ],
        }
    )


def _write_lock(fixture: RunFixture) -> None:
    acquired = _dt.datetime.now(_dt.UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(
        fixture.lock_path,
        {
            "schema_version": "1.0.0",
            "scope_id": fixture.scope_id,
            "locked_by_run": fixture.run_id,
            "fencing_token": 7,
            "backend": "filesystem",
            "acquired_at": acquired,
            "ttl_seconds": 3600,
        },
    )


def _write_run_state(fixture: RunFixture) -> None:
    run_dir = fixture.run_dir
    derived_digests, derive_issues = runmodel.derive_register_digests(run_dir)
    assert derive_issues == [], derive_issues
    fixture.write_run(
        {
            "schema_version": "1.0.0",
            "run_id": fixture.run_id,
            "title": "Mini incubation run",
            "profile": "LIGHT_INCUBATION",
            "state": "PROMOTING",
            "state_revision": 9,
            "lease_fencing_token": 1,
            "current_round": 1,
            "base_revision": dict(fixture.base_revision),
            "data_class": "internal",
            "actor": {
                "role": "council-orchestrator",
                "harness": "claude-code",
                "model": "test-model",
                "principal_id": "orch.alice",
                "session_ref": "sess-orch",
            },
            "participants": [
                {
                    "participant_id": "worker-one",
                    "model": "test-model",
                    "backend": "test-backend",
                    "spawn_mode": "subagent",
                    "principal_id": "p.worker",
                    "session_ref": "sess-worker",
                    "data_release": {
                        "max_data_class": "internal",
                        "source_ids": [],
                        "package_ids": [],
                        "approved_by_user": True,
                    },
                    "status": "active",
                }
            ],
            "register_digests": dict(derived_digests),
            "blocked": None,
            "recheck": None,
            "last_completed_action": "promotion-prepared",
            "next_action": "verify-closure",
            "updated_at": NOW,
        }
    )


def _write_lease(fixture: RunFixture) -> None:
    acquired = _dt.datetime.now(_dt.UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(
        fixture.run_dir / "LEASE.json",
        {
            "schema_version": "1.0.0",
            "run_id": fixture.run_id,
            "owner": {"principal_id": "orch.alice", "harness": "claude-code", "session_ref": "sess-orch"},
            "fencing_token": 1,
            "acquired_at": acquired,
            "ttl_seconds": 3600,
            "released": False,
        },
    )


def _layer_for(path: str) -> str:
    for root, layer in _LAYER_BY_ROOT.items():
        if path.startswith(f"{root}/"):
            return layer
    return "other"
