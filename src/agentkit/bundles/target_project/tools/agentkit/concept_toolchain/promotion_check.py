"""Promotion-closure validation — ``check.py promotion <run-dir>`` (FK-78 78.11).

Implements closure rules 1-7 completely: atom disposition totality with
per-disposition mandatory fields; receipt existence, digest match
(atom-statement source digest and LF-canonical target-section digest) and
writer/reviewer independence (principal AND session); ``targets[]`` digest
binding against the corpus baseline and the working tree; the diff-hunk
reverse trace against the git baseline (skipped with an INCOMPLETE
marker — never a silent PASS — when git or a git base revision is
unavailable); resolution of every ``required_*`` entry; scope-lock
verification for the filesystem backend (structural-only plus INCOMPLETE
marker for git-remote); and the ``promotion_disposition`` rules including
final coverage registers, open findings, and RUN register digests.

Partial runs exit ``2`` with an ``INCOMPLETE_CHECK_SET`` reason listing
the executed checks; they never produce a clean receipt.

git-remote scope locks: the toolchain performs no network operations.
With ``lock_backend: git-remote`` the checker validates the local
manifest/token consistency and requires the orchestrator-side CAS
evidence file ``promotion/lock-evidence.json`` (``{schema_version,
backend: "git-remote", refs[]: {scope_id, remote, ref, expected_ref,
old_oid, new_oid, observed_oid, lock_blob_digest, fencing_token,
attested_by_principal, attested_by_session, verified_at}}``, one entry
per locked scope). Each attestation is bound: ``expected_ref`` must equal
``refs/concept-locks/<sha256(scope_id)>`` and the attested ``ref``;
``observed_oid`` must equal ``new_oid``; ``lock_blob_digest`` must equal
the canonical lock blob of the manifest entry (scope, owning run,
fencing token, backend); ``fencing_token`` must match the manifest; and
``verified_at`` must be fresher than the lock TTL. Without valid evidence
the check stays INCOMPLETE: "git-remote lock verification requires the
orchestrator-side CAS evidence".
"""

from __future__ import annotations

import datetime
import difflib
import shutil
import subprocess
import unicodedata
from typing import TYPE_CHECKING

from . import runmodel
from .docmodel import anchor_slugs, file_digest_sha256, scan_documents
from .findings import CheckResult, error
from .receipts import TargetSpec, compute_target_digest, resolve_selector, verify_receipt_against_atom
from .smy import SmyError, parse_smy
from .units import AnchoredHeading, anchored_outline, lf_normalize

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from .config import GovernanceConfig
    from .docmodel import ConceptDocument
    from .runmodel import Issue, TsvRow

CHECK_ID = "promotion"

#: Tolerated clock skew between the attesting host and this checker.
#: Attestations are produced on another machine, so a small forward drift
#: must be accepted; without an upper bound the expiry checks would be
#: fail-open (any far-future timestamp would look "not yet expired").
#: 300s matches the usual NTP-synchronised fleet tolerance.
CLOCK_SKEW_SECONDS = 300


def run_promotion_check(project_root: Path, config: GovernanceConfig, run_dir: Path) -> CheckResult:
    """Run the promotion-closure check for one run directory."""
    return _PromotionCheck(project_root, config, run_dir).execute()



def _attestation_time_problems(ref: runmodel.LockEvidenceRef) -> list[str]:
    """Enforce the full time ordering of one CAS attestation.

    Required: ``acquired_at <= verified_at <= now + CLOCK_SKEW_SECONDS``
    and ``verified_at <= acquired_at + ttl_seconds``, plus lock liveness
    (``acquired_at + ttl_seconds`` in the future). Checking only "not yet
    expired" would be fail-open: a timestamp arbitrarily far in the future
    would pass every expiry test.
    """
    acquired = runmodel.parse_timestamp(ref.acquired_at)
    verified = runmodel.parse_timestamp(ref.verified_at)
    now = runmodel.now_utc()
    horizon = now + datetime.timedelta(seconds=CLOCK_SKEW_SECONDS)
    expiry = acquired + datetime.timedelta(seconds=ref.ttl_seconds)
    problems: list[str] = []
    if acquired > horizon:
        problems.append(f"acquired_at {ref.acquired_at} lies in the future (beyond {CLOCK_SKEW_SECONDS}s clock skew)")
    if verified > horizon:
        problems.append(f"verified_at {ref.verified_at} lies in the future (beyond {CLOCK_SKEW_SECONDS}s clock skew)")
    if verified < acquired:
        problems.append(f"verified_at {ref.verified_at} precedes acquired_at {ref.acquired_at}")
    if verified > expiry:
        problems.append(f"verified_at {ref.verified_at} lies beyond acquired_at + ttl_seconds ({ref.ttl_seconds}s)")
    if expiry <= now:
        problems.append(f"attested lock has expired (acquired_at {ref.acquired_at}, TTL {ref.ttl_seconds}s)")
    if verified + datetime.timedelta(seconds=ref.ttl_seconds) <= now:
        problems.append(f"CAS attestation is stale (verified_at {ref.verified_at}, attested TTL {ref.ttl_seconds}s)")
    return problems


def _load_structured_document(path: Path) -> object | None:
    """Parse one SMY/YAML registry document (structured-selector inputs)."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        text = "\n".join(lines[1:])
    try:
        return parse_smy(text)
    except SmyError:
        return None


def _formal_zone_mapping(text: str) -> dict[str, object]:
    """Parse the FORMAL-SPEC zone body of one spec document."""
    begin = text.find("<!-- FORMAL-SPEC:BEGIN -->")
    end = text.find("<!-- FORMAL-SPEC:END -->")
    if begin < 0 or end < 0:
        return {}
    body = text[begin:end]
    fence = body.find("```yaml")
    if fence < 0:
        return {}
    body = body[fence + len("```yaml") :]
    closing = body.rfind("```")
    if closing >= 0:
        body = body[:closing]
    try:
        return parse_smy(body)
    except SmyError:
        return {}


def _is_ignorable_line(text: str) -> bool:
    characters = [character for character in text if not character.isspace()]
    return all(unicodedata.category(character).startswith("P") for character in characters)


def _covering_anchors(outline: Sequence[AnchoredHeading], line: int) -> set[str]:
    innermost_index = -1
    for index, heading in enumerate(outline):
        if heading.line <= line:
            innermost_index = index
        else:
            break
    if innermost_index < 0:
        return set()
    anchors = {outline[innermost_index].anchor}
    level = outline[innermost_index].level
    for index in range(innermost_index - 1, -1, -1):
        if outline[index].level < level:
            anchors.add(outline[index].anchor)
            level = outline[index].level
    return anchors


class _PromotionCheck:
    """Stateful executor for one promotion-closure invocation."""

    def __init__(self, project_root: Path, config: GovernanceConfig, run_dir: Path) -> None:
        self.project_root = project_root
        self.config = config
        self.run_dir = run_dir
        self.result = CheckResult(check_id=CHECK_ID)
        try:
            self.rel = run_dir.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            self.rel = run_dir.as_posix()
        self.executed: list[str] = []
        self.skipped: list[str] = []
        self.run: runmodel.RunState | None = None
        self.manifest: runmodel.PromotionManifest | None = None
        self.atom_rows: tuple[TsvRow, ...] = ()
        self.baseline_index: dict[str, str] = {}
        self.receipts: dict[str, runmodel.ProjectionReceipt] = {}
        self._event_producers: dict[str, str] = {}
        self._event_objects: dict[str, str] = {}

    def _rel_path(self, *parts: str) -> str:
        return f"{self.rel}/{'/'.join(parts)}"

    def _error(self, rel_path: str, locator: str, message: str) -> None:
        self.result.findings.append(error(CHECK_ID, rel_path, locator, message))

    def _report(self, rel_path: str, issues: Sequence[Issue]) -> None:
        for issue in issues:
            self._error(rel_path, issue.locator, issue.message)

    def _skip(self, name: str, reason: str) -> None:
        self.skipped.append(f"{name}: {reason}")

    # -- entry point --------------------------------------------------------

    def execute(self) -> CheckResult:
        missing = [
            self._rel_path(*parts)
            for parts in (
                ("RUN.json",),
                ("promotion", "promotion-manifest.json"),
                ("promotion", "atom-register.tsv"),
                ("baseline", "corpus-baseline.tsv"),
            )
            if not self.run_dir.joinpath(*parts).is_file()
        ]
        if not self.run_dir.is_dir() or missing:
            self.result.complete = False
            detail = ", ".join(missing) if missing else f"run directory does not exist: {self.rel}"
            self.result.incomplete_reason = f"INCOMPLETE_CHECK_SET: prerequisites missing ({detail})"
            return self.result
        if not self._load_inputs():
            self.result.complete = False
            self.result.incomplete_reason = f"INCOMPLETE_CHECK_SET: executed=[{', '.join(self.executed)}] (input schemas invalid)"
            return self.result
        self._check_atom_closure()
        self._check_receipt_independence()
        self._check_targets()
        self._check_reverse_trace()
        self._check_required_refs()
        self._check_scope_locks()
        self._check_dispositions()
        if self.skipped:
            self.result.complete = False
            executed = ", ".join(self.executed)
            self.result.incomplete_reason = f"INCOMPLETE_CHECK_SET: executed=[{executed}]; skipped=[{'; '.join(self.skipped)}]"
        self.result.summary = f"{len(self.executed)} closure check(s) executed"
        return self.result

    def _load_inputs(self) -> bool:
        run, run_issues = runmodel.load_run_state(self.run_dir / "RUN.json")
        self._report(self._rel_path("RUN.json"), run_issues)
        self.run = run
        manifest, manifest_issues = runmodel.load_promotion_manifest(self.run_dir / "promotion" / "promotion-manifest.json")
        self._report(self._rel_path("promotion", "promotion-manifest.json"), manifest_issues)
        self.manifest = manifest
        atom_rows, atom_issues = runmodel.load_atom_register(self.run_dir / "promotion" / "atom-register.tsv")
        self._report(self._rel_path("promotion", "atom-register.tsv"), atom_issues)
        self.atom_rows = atom_rows
        baseline_rows, baseline_issues = runmodel.load_corpus_baseline(self.run_dir / "baseline" / "corpus-baseline.tsv")
        self._report(self._rel_path("baseline", "corpus-baseline.tsv"), baseline_issues)
        self.baseline_index = {row["path"]: row["sha256"] for row in baseline_rows}
        if manifest is None or run is None:
            return False
        if manifest.run_id != run.run_id:
            self._error(
                self._rel_path("promotion", "promotion-manifest.json"),
                "manifest.run_id",
                "run_id does not match RUN.json",
            )
        self._load_receipts(manifest)
        return True

    def _load_receipts(self, manifest: runmodel.PromotionManifest) -> None:
        receipts_dir = self.run_dir / manifest.receipts_dir
        if not receipts_dir.is_dir():
            return
        for entry in sorted(receipts_dir.glob("*.json")):
            rel = self._rel_path(manifest.receipts_dir, entry.name)
            receipt, issues = runmodel.load_projection_receipt(entry)
            self._report(rel, issues)
            if receipt is not None:
                self.receipts[receipt.receipt_id] = receipt

    # -- rule 1: atoms and receipts -----------------------------------------

    def _check_atom_closure(self) -> None:
        self.executed.append("atom-closure")
        rel = self._rel_path("promotion", "atom-register.tsv")
        scope_grammar = self.config.id_grammars["scope"]
        for number, row in enumerate(self.atom_rows, start=2):
            if scope_grammar.fullmatch(row["expected_authority"]) is None:
                self._error(
                    rel,
                    f"line {number}:expected_authority",
                    f"scope id violates the configured grammar: {row['expected_authority']!r}",
                )
            if row["disposition"] in runmodel.COVERED_DISPOSITIONS:
                self._check_covered_atom(rel, number, row)

    def _check_covered_atom(self, rel: str, number: int, row: TsvRow) -> None:
        target_refs = set(runmodel.split_refs(row["target_refs"]))
        covered: set[str] = set()
        for receipt_id in runmodel.split_refs(row["receipt_refs"]):
            receipt = self.receipts.get(receipt_id)
            if receipt is None:
                self._error(rel, f"line {number}:receipt_refs", f"receipt {receipt_id} does not exist or failed validation")
                continue
            if receipt.atom_id != row["atom_id"]:
                self._error(
                    rel,
                    f"line {number}:receipt_refs",
                    f"receipt {receipt_id} is bound to atom {receipt.atom_id}, not {row['atom_id']}",
                )
                continue
            target_ref = TargetSpec.from_receipt(receipt).reference
            if target_ref not in target_refs:
                self._error(rel, f"line {number}:receipt_refs", f"receipt {receipt_id} covers undeclared target {target_ref}")
            if receipt.verdict != "equivalent":
                self._error(
                    rel,
                    f"line {number}:disposition",
                    f"COVERED atom relies on receipt {receipt_id} with verdict {receipt.verdict!r}",
                )
                continue
            self._check_receipt_digests(rel, number, row, receipt)
            covered.add(target_ref)
        for target_ref in sorted(target_refs - covered):
            self._error(rel, f"line {number}:target_refs", f"target {target_ref} has no covering equivalent receipt")

    def _check_receipt_digests(self, rel: str, number: int, row: TsvRow, receipt: runmodel.ProjectionReceipt) -> None:
        """Delegate to the shared receipt engine (same rules as the projection check)."""
        for problem in verify_receipt_against_atom(
            self.project_root, receipt, row, target_mode=receipt.target_mode, selector=receipt.selector
        ):
            self._error(rel, f"line {number}:{problem.locator}", f"receipt {receipt.receipt_id}: {problem.message}")

    def _check_receipt_independence(self) -> None:
        self.executed.append("receipt-independence")
        assert self.manifest is not None
        atoms_by_id = {row["atom_id"]: row for row in self.atom_rows}
        scopes_by_id = {scope.scope_id: scope for scope in self.manifest.scopes}
        for receipt_id, receipt in sorted(self.receipts.items()):
            rel = self._rel_path(self.manifest.receipts_dir, f"{receipt_id}.json")
            if receipt.writer_principal_id == receipt.reviewer_principal_id:
                self._error(rel, "receipt.reviewer_principal_id", "reviewer principal must differ from the writer principal")
            if receipt.writer_session_ref == receipt.reviewer_session_ref:
                self._error(rel, "receipt.reviewer_session_ref", "reviewer session must differ from the writer session")
            if receipt.verdict == "disagrees":
                self._check_disagreement_blocker(rel, receipt, atoms_by_id, scopes_by_id)

    def _check_disagreement_blocker(
        self,
        rel: str,
        receipt: runmodel.ProjectionReceipt,
        atoms_by_id: dict[str, TsvRow],
        scopes_by_id: dict[str, runmodel.PromotionScope],
    ) -> None:
        atom = atoms_by_id.get(receipt.atom_id)
        scope = scopes_by_id.get(atom["expected_authority"]) if atom is not None else None
        blocked = scope is not None and any(receipt.atom_id in blocker.atom_ids for blocker in scope.blockers)
        if not blocked:
            self._error(rel, "receipt.verdict", f"disagreeing receipt requires a scope blocker listing atom {receipt.atom_id}")

    # -- rule 2: targets ----------------------------------------------------

    def _check_targets(self) -> None:
        self.executed.append("targets")
        assert self.manifest is not None
        rel = self._rel_path("promotion", "promotion-manifest.json")
        for target in self.manifest.targets:
            current = self.project_root / target.path
            if not current.is_file():
                self._error(rel, f"targets.{target.path}", "target file does not exist in the working tree")
            elif file_digest_sha256(current) != target.after_sha256:
                self._error(rel, f"targets.{target.path}", "after_sha256 does not match the working tree")
            baseline_digest = self.baseline_index.get(target.path)
            if baseline_digest is None:
                if target.before_sha256 is not None:
                    self._error(
                        rel,
                        f"targets.{target.path}",
                        "before_sha256 must be null for a file absent from the corpus baseline",
                    )
            elif target.before_sha256 is None:
                self._error(rel, f"targets.{target.path}", "before_sha256 must not be null for a baselined file")
            elif target.before_sha256 != baseline_digest:
                self._error(rel, f"targets.{target.path}", "before_sha256 does not match the corpus baseline")

    # -- rule 3: diff-hunk reverse trace ------------------------------------

    def _check_reverse_trace(self) -> None:
        assert self.manifest is not None
        base = self.manifest.base_revision
        if base.kind != "git":
            self._skip("reverse-trace", f"base_revision kind {base.kind!r} provides no diffable baseline")
            return
        if shutil.which("git") is None or not self._git_ok("rev-parse", "--verify", f"{base.value}^{{commit}}"):
            self._skip("reverse-trace", "git or the base revision is unavailable")
            return
        self.executed.append("reverse-trace")
        refs_by_path = self._anchor_refs_by_path()
        for target in self.manifest.targets:
            current = self.project_root / target.path
            if not current.is_file():
                continue
            old_text = self._git_show(base.value, target.path)
            if old_text is None:
                if target.path in self.baseline_index:
                    self._skip("reverse-trace", f"baseline blob unavailable for {target.path}")
                    continue
                old_text = ""
            self._check_hunks(target.path, old_text, current.read_text(encoding="utf-8"), refs_by_path.get(target.path, set()))

    def _anchor_refs_by_path(self) -> dict[str, set[str]]:
        refs: dict[str, set[str]] = {}
        for receipt in self.receipts.values():
            refs.setdefault(receipt.target.path, set()).add(receipt.target.anchor)
        for row in self.atom_rows:
            for target_ref in runmodel.split_refs(row["target_refs"]):
                path, _, anchor = target_ref.partition("#")
                refs.setdefault(path, set()).add(anchor)
        return refs

    def _check_hunks(self, path: str, old_text: str, new_text: str, refs: set[str]) -> None:
        old_lines = lf_normalize(old_text).split("\n")
        new_lines = lf_normalize(new_text).split("\n")
        outline = anchored_outline(new_text)
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            positions = [j1 + offset + 1 for offset, line in enumerate(new_lines[j1:j2]) if not _is_ignorable_line(line)]
            if any(not _is_ignorable_line(line) for line in old_lines[i1:i2]) and not positions:
                positions.append(j1)
            for position in positions:
                if not (_covering_anchors(outline, position) & refs):
                    self._error(path, f"L{max(position, 1)}", "diff hunk is not covered by any receipt or atom target anchor")
                    break

    def _git_ok(self, *args: str) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(self.project_root), *args], check=False, capture_output=True, encoding="utf-8", errors="replace"
        )
        return completed.returncode == 0

    def _git_show(self, revision: str, path: str) -> str | None:
        completed = subprocess.run(
            ["git", "-C", str(self.project_root), "show", f"{revision}:{path}"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed.stdout if completed.returncode == 0 else None

    # -- rule 4: required references ----------------------------------------

    def _check_required_refs(self) -> None:
        self.executed.append("required-refs")
        assert self.manifest is not None
        rel = self._rel_path("promotion", "promotion-manifest.json")
        documents = scan_documents(self.project_root, self.config.concept_roots)
        concept_ids = {document.concept_id for document in documents if document.concept_id}
        formal_ids = {
            value
            for document in documents
            if document.layer == "formal" and document.frontmatter is not None
            for value in (document.frontmatter.get("id"),)
            if isinstance(value, str)
        }
        self._check_required_decisions(rel)
        for concept_id in self.manifest.required_concept_ids:
            if concept_id not in concept_ids:
                self._error(rel, "manifest.required_concept_ids", f"concept id does not resolve in the corpus: {concept_id!r}")
        for formal_id in self.manifest.required_formal_ids:
            if formal_id not in formal_ids:
                self._error(
                    rel,
                    "manifest.required_formal_ids",
                    f"formal id does not resolve in the formal corpus: {formal_id!r}",
                )
        for support_path in self.manifest.required_support_paths:
            if not (self.project_root / support_path).exists():
                self._error(rel, "manifest.required_support_paths", f"support path does not exist: {support_path}")
        for index, oracle in enumerate(self.manifest.required_test_oracles):
            problem = self._resolve_anchor_ref(oracle.locator)
            if problem is not None:
                self._error(rel, f"manifest.required_test_oracles[{index}]", f"oracle {oracle.oracle_id!r}: {problem}")
        self._check_registry_edges(rel, documents, concept_ids, formal_ids)

    def _check_required_decisions(self, rel: str) -> None:
        assert self.manifest is not None
        grammar = self.config.id_grammars["decision_record"]
        decisions_dir = f"{self.config.concept_roots['meta']}/decisions"
        for decision_id in self.manifest.required_decision_ids:
            if grammar.fullmatch(decision_id) is None:
                self._error(
                    rel,
                    "manifest.required_decision_ids",
                    f"decision id violates the configured grammar: {decision_id!r}",
                )
            elif not (self.project_root / decisions_dir / f"{decision_id}.md").is_file():
                self._error(
                    rel,
                    "manifest.required_decision_ids",
                    f"decision record does not exist: {decisions_dir}/{decision_id}.md",
                )

    def _check_registry_edges(
        self, rel: str, documents: Sequence[ConceptDocument], concept_ids: set[str], formal_ids: set[str]
    ) -> None:
        """Resolve both edge forms: anchored strings and structured triples."""
        assert self.manifest is not None
        known_scopes = self._corpus_scopes(documents)
        for index, edge in enumerate(self.manifest.required_registry_edges):
            where = f"manifest.required_registry_edges[{index}]"
            if isinstance(edge, str):
                problem = self._resolve_anchor_ref(edge)
                if problem is not None:
                    self._error(rel, where, problem)
                continue
            if edge.kind not in runmodel.REGISTRY_EDGE_KINDS:
                self._error(rel, where, f"kind {edge.kind!r} is not one of {', '.join(runmodel.REGISTRY_EDGE_KINDS)}")
                continue
            unresolved = [
                side
                for side, node in (("from", edge.from_ref), ("to", edge.to_ref))
                if not self._registry_node_resolves(node, concept_ids, formal_ids, known_scopes)
            ]
            for side in unresolved:
                node = edge.from_ref if side == "from" else edge.to_ref
                self._error(rel, where, f"{side} node {node!r} does not resolve as doc id, scope id or registry entry")
            if unresolved:
                continue
            problem = self._edge_relation_problem(edge, documents)
            if problem is not None:
                self._error(rel, where, problem)

    def _edge_relation_problem(self, edge: runmodel.RegistryEdge, documents: Sequence[ConceptDocument]) -> str | None:
        """Verify the CONCRETE relation, not just endpoint existence.

        ``owns``: the ``from`` document declares ``to`` in ``authority_over``.
        ``defers_to``: the ``from`` document declares a ``defers_to`` edge to ``to``.
        ``contract``/``member``: the domain registry lists ``to`` under the
        matching document list of domain ``from``.
        ``producer``: the formal event ``to`` declares ``producer: <from>``.
        ``consumer``: the formal event ``from`` is produced elsewhere and the
        document ``to`` binds its object id via ``formal_refs``.
        """
        by_id = {document.concept_id: document for document in documents if document.concept_id}
        handlers = {
            "owns": lambda: self._frontmatter_scope_edge(by_id.get(edge.from_ref), edge),
            "defers_to": lambda: self._frontmatter_defers_edge(by_id.get(edge.from_ref), edge),
            "contract": lambda: self._domain_registry_edge(edge, "contract_docs"),
            "member": lambda: self._domain_registry_edge(edge, "member_docs"),
            "producer": lambda: self._producer_edge(edge),
            "consumer": lambda: self._consumer_edge(edge, by_id.get(edge.to_ref)),
        }
        return handlers[edge.kind]()

    def _frontmatter_scope_edge(self, document: ConceptDocument | None, edge: runmodel.RegistryEdge) -> str | None:
        if document is None or document.frontmatter is None:
            return f"'owns' requires {edge.from_ref!r} to be a concept document with frontmatter"
        authority = document.frontmatter.get("authority_over")
        scopes = {
            item.get("scope") for item in authority if isinstance(item, dict) } if isinstance(authority, list) else set()
        if edge.to_ref not in scopes:
            return f"{edge.from_ref} does not declare authority_over scope {edge.to_ref!r}"
        return None

    def _frontmatter_defers_edge(self, document: ConceptDocument | None, edge: runmodel.RegistryEdge) -> str | None:
        if document is None or document.frontmatter is None:
            return f"'defers_to' requires {edge.from_ref!r} to be a concept document with frontmatter"
        defers = document.frontmatter.get("defers_to")
        targets = {item.get("target") for item in defers if isinstance(item, dict)} if isinstance(defers, list) else set()
        if edge.to_ref not in targets:
            return f"{edge.from_ref} does not declare a defers_to edge to {edge.to_ref!r}"
        return None

    def _domain_registry_edge(self, edge: runmodel.RegistryEdge, field: str) -> str | None:
        selector = f"domains[id={edge.from_ref}].{field}"
        registry = f"{self.config.concept_roots['technical']}/_meta/domain-registry.yaml"
        result = compute_target_digest(self.project_root, registry, "structured-selector", selector)
        if result.problem is not None or result.missing:
            return f"domain-registry does not resolve {selector}: {result.problem or 'registry missing'}"
        document = _load_structured_document(self.project_root / registry)
        node, problem = resolve_selector(document, selector) if document is not None else (None, "registry unreadable")
        if problem is not None:
            return f"domain-registry does not resolve {selector}: {problem}"
        if not isinstance(node, list) or edge.to_ref not in node:
            return f"domain {edge.from_ref!r} does not list {edge.to_ref!r} in {field}"
        return None

    def _producer_edge(self, edge: runmodel.RegistryEdge) -> str | None:
        producer = self._formal_event_producers().get(edge.to_ref)
        if producer is None:
            return f"'producer' requires {edge.to_ref!r} to be a declared formal event"
        if producer != edge.from_ref:
            return f"formal event {edge.to_ref} declares producer {producer!r}, not {edge.from_ref!r}"
        return None

    def _consumer_edge(self, edge: runmodel.RegistryEdge, consumer: ConceptDocument | None) -> str | None:
        """Normed v1 semantics of a ``consumer`` edge (FK-78 section 78.11).

        An edge ``{from: <event_id>, to: <concept_id>, kind: consumer}`` is
        satisfied exactly when ``<event_id>`` exists in a formal event set
        ``<object_id>``, ``<concept_id>`` denotes a concept document, and
        that document's ``formal_refs`` contain ``<object_id>``.

        The edge proves ONLY the contractual binding to the event SET, not
        the processing of the individual event. Event-specific consumption
        requires an explicit ``consumes_events`` relation and must not be
        inferred from ``formal_refs``.
        """
        if edge.from_ref not in self._formal_event_producers():
            return f"'consumer' requires {edge.from_ref!r} to be a declared formal event"
        if consumer is None or consumer.frontmatter is None:
            return f"'consumer' requires {edge.to_ref!r} to be a concept document with frontmatter"
        refs = consumer.frontmatter.get("formal_refs")
        bound = set(refs) if isinstance(refs, list) else set()
        object_id = self._formal_event_objects().get(edge.from_ref, "")
        if object_id not in bound:
            return f"{edge.to_ref} does not bind {object_id or 'the producing formal object'} via formal_refs"
        return None

    def _formal_event_producers(self) -> dict[str, str]:
        self._load_formal_events()
        return self._event_producers

    def _formal_event_objects(self) -> dict[str, str]:
        self._load_formal_events()
        return self._event_objects

    def _load_formal_events(self) -> None:
        if self._event_producers or self._event_objects:
            return
        for document in scan_documents(self.project_root, {"formal": self.config.concept_roots["formal"]}):
            spec = _formal_zone_mapping(document.text)
            events = spec.get("events") if isinstance(spec, dict) else None
            object_id = spec.get("object") if isinstance(spec, dict) else None
            if not isinstance(events, list) or not isinstance(object_id, str):
                continue
            for item in events:
                if not isinstance(item, dict):
                    continue
                event_id, producer = item.get("id"), item.get("producer")
                if isinstance(event_id, str) and isinstance(producer, str):
                    self._event_producers[event_id] = producer
                    self._event_objects[event_id] = object_id

    def _corpus_scopes(self, documents: Sequence[ConceptDocument]) -> set[str]:
        scopes: set[str] = set()
        for document in documents:
            authority = document.frontmatter.get("authority_over") if document.frontmatter is not None else None
            if not isinstance(authority, list):
                continue
            for item in authority:
                if isinstance(item, dict):
                    scope = item.get("scope")
                    if isinstance(scope, str) and scope:
                        scopes.add(scope)
        return scopes

    def _registry_node_resolves(
        self, node: str, concept_ids: set[str], formal_ids: set[str], known_scopes: set[str]
    ) -> bool:
        if node in concept_ids or node in formal_ids or node in known_scopes:
            return True
        if node in self._formal_event_producers() or node in set(self._formal_event_producers().values()):
            return True
        if "#" in node or "/" in node:
            return self._resolve_anchor_ref(node) is None
        return False

    def _resolve_anchor_ref(self, reference: str) -> str | None:
        """Resolve a ``<path>`` or ``<path>#<anchor>`` reference against the tree.

        Markdown anchors resolve via the heading/anchor index; for other
        file types the anchor token must occur literally in the file (e.g.
        a YAML registry key).
        """
        path, _, anchor = reference.partition("#")
        target = self.project_root / path
        if not target.exists():
            return f"reference path does not exist: {path}"
        if not anchor:
            return None
        if not target.is_file():
            return f"anchored reference must point to a file: {reference}"
        text = target.read_text(encoding="utf-8")
        if path.lower().endswith((".md", ".markdown")):
            return None if anchor in anchor_slugs(text) else f"anchor does not resolve: {reference}"
        return None if anchor in text else f"anchor token not found in non-markdown file: {reference}"

    # -- rule 5 helper: scope locks -----------------------------------------

    def _check_scope_locks(self) -> None:
        assert self.manifest is not None
        rel = self._rel_path("promotion", "promotion-manifest.json")
        locks_by_scope: dict[str, runmodel.ScopeLockEntry] = {}
        for entry in self.manifest.scope_locks:
            if entry.scope_id in locks_by_scope:
                self._error(rel, "manifest.scope_locks", f"duplicate scope lock entry for {entry.scope_id!r}")
            locks_by_scope[entry.scope_id] = entry
        for scope in self.manifest.scopes:
            if scope.promotion_disposition == "promoted" and scope.scope_id not in locks_by_scope:
                self._error(rel, "manifest.scope_locks", f"promoted scope {scope.scope_id!r} has no scope lock entry")
        for scope_id, entry in sorted(locks_by_scope.items()):
            if entry.backend != self.config.lock_backend:
                self._error(
                    rel,
                    "manifest.scope_locks",
                    f"lock backend {entry.backend!r} does not match configured {self.config.lock_backend!r}",
                )
            if entry.locked_by_run != self.manifest.run_id:
                self._error(rel, "manifest.scope_locks", f"scope {scope_id!r} is locked by {entry.locked_by_run!r}, not this run")
        if self.config.lock_backend == "git-remote":
            self._check_lock_evidence(locks_by_scope)
            return
        self.executed.append("scope-locks")
        for scope_id, entry in sorted(locks_by_scope.items()):
            self._check_filesystem_lock(rel, scope_id, entry)

    def _check_lock_evidence(self, locks_by_scope: dict[str, runmodel.ScopeLockEntry]) -> None:
        """Accept orchestrator-side CAS evidence for git-remote locks (module docstring)."""
        evidence_rel = self._rel_path("promotion", "lock-evidence.json")
        evidence_path = self.run_dir / "promotion" / "lock-evidence.json"
        if not evidence_path.is_file():
            self._skip("scope-locks", "git-remote lock verification requires the orchestrator-side CAS evidence")
            return
        evidence, issues = runmodel.load_lock_evidence(evidence_path)
        self._report(evidence_rel, issues)
        if evidence is None:
            self._skip("scope-locks", "git-remote lock verification requires the orchestrator-side CAS evidence")
            return
        self.executed.append("scope-locks")
        evidence_scopes = {ref.scope_id for ref in evidence.refs}
        for scope_id in sorted(set(locks_by_scope) - evidence_scopes):
            self._error(evidence_rel, "evidence.refs", f"no CAS evidence for locked scope {scope_id!r}")
        for scope_id in sorted(evidence_scopes - set(locks_by_scope)):
            self._error(evidence_rel, "evidence.refs", f"CAS evidence for unlocked scope {scope_id!r}")
        expected_remote = self.config.lock_remote
        if expected_remote is None:
            self._error(
                evidence_rel,
                "evidence.remote",
                "lock_backend 'git-remote' requires 'lock_remote' in concept-governance.json",
            )
        elif evidence.remote != expected_remote:
            self._error(
                evidence_rel,
                "evidence.remote",
                f"remote {evidence.remote!r} does not match the configured lock_remote {expected_remote!r}",
            )
        for ref in evidence.refs:
            entry = locks_by_scope.get(ref.scope_id)
            if entry is not None:
                self._check_evidence_ref(evidence_rel, ref, entry)

    def _check_evidence_ref(self, rel: str, ref: runmodel.LockEvidenceRef, entry: runmodel.ScopeLockEntry) -> None:
        """Bind one CAS attestation to ref name, OID, lock blob, token and freshness.

        Two independent time checks: the attested LOCK must still be live
        (``acquired_at + ttl_seconds`` in the future) and the ATTESTATION
        must be recent (``now - verified_at <= ttl_seconds``).
        """
        where = f"evidence.refs.{ref.scope_id}"
        expected_ref = runmodel.scope_lock_ref(ref.scope_id)
        if ref.expected_ref != expected_ref:
            self._error(rel, where, f"expected_ref must be {expected_ref}, got {ref.expected_ref}")
        if ref.ref != ref.expected_ref:
            self._error(rel, where, f"attested ref {ref.ref} does not equal expected_ref {ref.expected_ref}")
        if ref.observed_oid != ref.new_oid:
            self._error(rel, where, f"observed_oid {ref.observed_oid} does not equal the attested new_oid {ref.new_oid}")
        expected_blob = runmodel.canonical_lock_blob_digest(
            ref.scope_id, entry.locked_by_run, entry.fencing_token, entry.backend, ref.ttl_seconds, ref.acquired_at
        )
        if ref.lock_blob_digest != expected_blob:
            self._error(rel, where, "lock_blob_digest does not match the canonical lock blob of the manifest entry")
        if ref.fencing_token != entry.fencing_token:
            self._error(rel, where, f"fencing_token {ref.fencing_token} does not match the manifest entry {entry.fencing_token}")
        for problem in _attestation_time_problems(ref):
            self._error(rel, where, problem)

    def _check_filesystem_lock(self, rel: str, scope_id: str, entry: runmodel.ScopeLockEntry) -> None:
        assert self.manifest is not None
        lock_rel = f"{self.config.incubator_root}/locks/{runmodel.scope_lock_filename(scope_id)}"
        lock_path = self.project_root / lock_rel
        if not lock_path.is_file():
            self._error(lock_rel, "file", f"scope lock file for {scope_id!r} does not exist")
            return
        lock, issues = runmodel.load_scope_lock(lock_path)
        self._report(lock_rel, issues)
        if lock is None:
            return
        if lock.scope_id != scope_id:
            self._error(lock_rel, "lock.scope_id", f"lock is bound to scope {lock.scope_id!r}, not {scope_id!r}")
        if lock.locked_by_run != self.manifest.run_id:
            self._error(lock_rel, "lock.locked_by_run", f"lock is held by {lock.locked_by_run!r}, not this run")
        if lock.fencing_token != entry.fencing_token:
            self._error(
                lock_rel,
                "lock.fencing_token",
                f"lock fencing_token {lock.fencing_token} does not match the manifest entry {entry.fencing_token}",
            )
        if lock.backend != self.config.lock_backend:
            self._error(
                lock_rel,
                "lock.backend",
                f"lock backend {lock.backend!r} does not match configured {self.config.lock_backend!r}",
            )
        if runmodel.timestamp_expired(lock.acquired_at, lock.ttl_seconds):
            self._error(lock_rel, "lock.ttl_seconds", "scope lock TTL has expired (lock is not live)")

    # -- rules 5-6: dispositions --------------------------------------------

    def _check_dispositions(self) -> None:
        self.executed.append("dispositions")
        assert self.manifest is not None
        rel = self._rel_path("promotion", "promotion-manifest.json")
        for gate_name in runmodel.SEMANTIC_GATES:
            count = sum(1 for gate in self.manifest.semantic_gates if gate.gate == gate_name)
            if count != 1:
                self._error(rel, "manifest.semantic_gates", f"exactly one {gate_name!r} entry is required, found {count}")
        finding_rows, finding_issues = self._load_optional_register(("findings.tsv",), runmodel.load_findings_register)
        self._report(self._rel_path("findings.tsv"), finding_issues)
        open_findings = [row["finding_id"] for row in finding_rows if row["status"] == "open"]
        atoms_by_scope: dict[str, list[TsvRow]] = {}
        for row in self.atom_rows:
            atoms_by_scope.setdefault(row["expected_authority"], []).append(row)
        any_promoted = any(scope.promotion_disposition == "promoted" for scope in self.manifest.scopes)
        for scope in self.manifest.scopes:
            handler = {
                "promoted": self._check_promoted_scope,
                "deferred": self._check_deferred_scope,
                "rejected": self._check_rejected_scope,
            }[scope.promotion_disposition]
            handler(rel, scope, atoms_by_scope.get(scope.scope_id, []), open_findings)
        if any_promoted:
            self._check_run_register_digests(rel)
            self._check_final_coverage()

    def _load_optional_register(
        self,
        parts: tuple[str, ...],
        loader: Callable[[Path], tuple[tuple[TsvRow, ...], list[Issue]]],
    ) -> tuple[tuple[TsvRow, ...], list[Issue]]:
        path = self.run_dir.joinpath(*parts)
        if not path.is_file():
            return (), []
        return loader(path)

    def _check_promoted_scope(
        self, rel: str, scope: runmodel.PromotionScope, atoms: list[TsvRow], open_findings: list[str]
    ) -> None:
        where = f"manifest.scopes.{scope.scope_id}"
        if scope.blockers:
            self._error(rel, where, "promoted scope must not carry blockers")
        for row in atoms:
            if row["disposition"] in ("OPEN_MISSING", "DEFERRED_BACKLOG"):
                self._error(rel, where, f"promoted scope carries atom {row['atom_id']} with disposition {row['disposition']}")
        assert self.manifest is not None
        for gate in self.manifest.semantic_gates:
            if gate.status == "passed":
                continue
            if gate.status == "not_run" or not gate.blocking_scope_ids or scope.scope_id in gate.blocking_scope_ids:
                self._error(rel, where, f"semantic gate {gate.gate!r} is {gate.status!r} for a promoted scope")
        if open_findings:
            self._error(
                rel,
                where,
                f"promoted scope with {len(open_findings)} open finding(s): {', '.join(sorted(open_findings))}",
            )

    def _check_deferred_scope(
        self, rel: str, scope: runmodel.PromotionScope, atoms: list[TsvRow], open_findings: list[str]
    ) -> None:
        where = f"manifest.scopes.{scope.scope_id}"
        if not scope.blockers:
            self._error(rel, where, "deferred scope requires at least one blocker with owner and visible anchor")
        for blocker in scope.blockers:
            self._check_visible_anchor(rel, where, blocker.visible_anchor)

    def _check_rejected_scope(
        self, rel: str, scope: runmodel.PromotionScope, atoms: list[TsvRow], open_findings: list[str]
    ) -> None:
        rejected_atoms = [row for row in atoms if row["disposition"] == "REJECTED"]
        if not scope.blockers and not rejected_atoms:
            self._error(
                rel,
                f"manifest.scopes.{scope.scope_id}",
                "rejected scope must document the discarded alternative (blocker or REJECTED atom)",
            )

    def _check_visible_anchor(self, rel: str, where: str, visible_anchor: str) -> None:
        path, separator, anchor = visible_anchor.partition("#")
        if not separator or not path or not anchor:
            self._error(rel, where, f"visible_anchor must be <path>#<anchor>, got {visible_anchor!r}")
            return
        target = self.project_root / path
        if not target.is_file():
            self._error(rel, where, f"visible_anchor file does not exist: {path}")
            return
        if not path.lower().endswith((".md", ".markdown")) or anchor not in anchor_slugs(target.read_text(encoding="utf-8")):
            self._error(rel, where, f"visible_anchor does not resolve: {visible_anchor}")

    def _check_run_register_digests(self, rel: str) -> None:
        """Verify all nine register_digests pins against the canonical re-derivation."""
        if self.run is None:
            return
        run_rel = self._rel_path("RUN.json")
        derived, derive_issues = runmodel.derive_register_digests(self.run_dir)
        for issue in derive_issues:
            self._error(self._rel_path(issue.locator), "file", issue.message)
        for key in runmodel.REGISTER_DIGEST_KEYS:
            digest = self.run.register_digests.get(key)
            if digest is None:
                self._error(run_rel, f"run.register_digests.{key}", "must be pinned before any scope is promoted")
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

    # -- final coverage ------------------------------------------------------

    def _check_final_coverage(self) -> None:
        self.executed.append("final-coverage")
        self._check_final_source_coverage()
        self._check_final_normative_coverage()

    def _check_final_source_coverage(self) -> None:
        rel = self._rel_path("baseline", "source-coverage.tsv")
        path = self.run_dir / "baseline" / "source-coverage.tsv"
        if not path.is_file():
            self._error(rel, "file", "final source coverage register is missing for a promoted scope")
            return
        rows, issues = runmodel.load_source_coverage(path)
        self._report(rel, issues)
        register_rows, register_issues = self._load_optional_register(
            ("baseline", "source-register.tsv"),
            runmodel.load_source_register,
        )
        self._report(self._rel_path("baseline", "source-register.tsv"), register_issues)
        authors = {row["source_id"]: row["author_principal_id"] for row in register_rows}
        source_paths = {row["source_id"]: row["path"] for row in register_rows}
        covered = {row["source_id"] for row in rows}
        for source_id in sorted(set(authors) - covered):
            self._error(rel, "file", f"source {source_id} has no final coverage row")
        for number, row in enumerate(rows, start=2):
            if register_rows and row["source_id"] not in authors:
                self._error(rel, f"line {number}:source_id", f"coverage row for unknown source {row['source_id']!r}")
            author = authors.get(row["source_id"], "")
            if author and row["reviewer_principal_id"] == author:
                self._error(rel, f"line {number}:reviewer_principal_id", "reviewer must not be the source author")
            source_path = source_paths.get(row["source_id"])
            if source_path is not None:
                source_file = self.project_root / source_path
                if not source_file.is_file() or file_digest_sha256(source_file) != row["sha256"]:
                    self._error(rel, f"line {number}:sha256", f"coverage digest does not match the current source {source_path}")
            if not row["review_artifact"].startswith("N_A:") and not (self.project_root / row["review_artifact"]).exists():
                self._error(rel, f"line {number}:review_artifact", f"review artifact does not exist: {row['review_artifact']}")

    def _check_final_normative_coverage(self) -> None:
        rel = self._rel_path("baseline", "normative-coverage.tsv")
        path = self.run_dir / "baseline" / "normative-coverage.tsv"
        if not path.is_file():
            self._error(rel, "file", "final normative coverage register is missing for a promoted scope")
            return
        rows, issues = runmodel.load_normative_coverage(path)
        self._report(rel, issues)
        current_files = self._current_concept_files()
        universe = set(self.baseline_index) | current_files
        covered = {row["path"] for row in rows}
        changed = {
            file_path
            for file_path in universe
            if self.baseline_index.get(file_path)
            != (file_digest_sha256(self.project_root / file_path) if file_path in current_files else None)
        }
        required = universe if (self.run is not None and self.run.profile == "FULL_ATOM") else changed
        for file_path in sorted(required - covered):
            self._error(rel, "file", f"normative coverage row missing for {file_path}")
        for file_path in sorted(covered - universe):
            self._error(rel, "file", f"normative coverage row outside baseline and current corpus: {file_path}")
        for number, row in enumerate(rows, start=2):
            self._check_normative_row(rel, number, row, current_files)

    def _check_normative_row(self, rel: str, number: int, row: TsvRow, current_files: set[str]) -> None:
        baseline_digest = self.baseline_index.get(row["path"])
        current_digest = file_digest_sha256(self.project_root / row["path"]) if row["path"] in current_files else None
        if baseline_digest is None:
            expected = "added" if current_digest is not None else "removed"
        elif current_digest is None:
            expected = "removed"
        else:
            expected = "unchanged" if baseline_digest == current_digest else "modified"
        if row["change_kind"] != expected:
            self._error(rel, f"line {number}:change_kind", f"change_kind must be {expected!r} for {row['path']}")
        if baseline_digest is not None and row["baseline_sha256"] and row["baseline_sha256"] != baseline_digest:
            self._error(rel, f"line {number}:baseline_sha256", "does not match the corpus baseline")
        if current_digest is not None and row["current_sha256"] and row["current_sha256"] != current_digest:
            self._error(rel, f"line {number}:current_sha256", "does not match the working tree")

    def _current_concept_files(self) -> set[str]:
        files: set[str] = set()
        for relative_root in self.config.concept_roots.values():
            root = self.project_root / relative_root
            if not root.is_dir():
                continue
            files.update(entry.relative_to(self.project_root).as_posix() for entry in root.rglob("*") if entry.is_file())
        return files
