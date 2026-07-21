"""Corpus-wide projection-manifest validation — ``check.py projection``.

Validates ``concept/_meta/projection-manifest.json`` (FK-78 section 78.12)
against the current corpus: schema (fail-closed), disjoint
``covered_scope_ids`` groups, the ``lifecycle_source`` binding (path
exists, digest matches, and the referenced decision record carries the
machine-readable frontmatter field ``decision_status`` matching the
recorded status — ``accepted`` for ``current`` entries), the
``assertion_source`` digest binding (mismatch is the ``stale-source``
finding), authority coverage (the union of ``scope_id`` +
``covered_scope_ids`` over all entries must equal the union of the
``authority_over`` scopes re-derived from the assertion-source
frontmatter), the deterministic per-projection ``equivalence_status``
derivation compared against the recorded values, the lifecycle-first
``assertion_status`` derivation, and blocker anchors that must resolve to
a real ``<file>#<anchor>``.

Receipt binding (activation hardening): a ``receipt_ref`` only counts
when it is registered in the promotion manifest of the run named in
``last_run_id`` (receipt lives under that run's ``receipts_dir`` and is
referenced by an atom of the run's atom register whose ``target_refs``
cover the receipt target, whose scope is claimed by the entry, and whose
target path is the resolved projection target); writer/reviewer
independence (principal AND session) is re-checked here. ``active``
additionally requires a non-null, matching ``target_digest`` for every
required projection.

Self-projection entries referencing the manifest itself are digest-bound
to the canonical entry digest (section 78.12), never to the whole file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import runmodel
from .docmodel import anchor_slugs, file_digest_sha256, load_document, scan_documents
from .findings import CheckResult, error
from .promotion_check import run_promotion_check
from .receipts import compute_target_digest, verify_receipt_against_atom

if TYPE_CHECKING:
    from pathlib import Path

    from .config import GovernanceConfig
    from .runmodel import ProjectionEntry, RequiredProjection

CHECK_ID = "projection"

MANIFEST_RELATIVE = "projection-manifest.json"


def run_projection_check(project_root: Path, config: GovernanceConfig) -> CheckResult:
    """Run the corpus-wide projection-manifest check."""
    result = CheckResult(check_id=CHECK_ID)
    manifest_rel = f"{config.concept_roots['meta']}/{MANIFEST_RELATIVE}"
    manifest_path = project_root / manifest_rel
    if not manifest_path.is_file():
        result.complete = False
        result.incomplete_reason = f"projection manifest not found: {manifest_rel}"
        return result
    manifest, issues = runmodel.load_projection_manifest(manifest_path)
    for issue in issues:
        result.findings.append(error(CHECK_ID, manifest_rel, issue.locator, issue.message))
    if manifest is None:
        return result
    checker = _ProjectionCheck(project_root, config, manifest_rel, result)
    checker.check(manifest)
    result.summary = f"{len(manifest.entries)} manifest entr(y/ies) validated"
    return result


class _ProjectionCheck:
    """Stateful executor for one projection-manifest validation."""

    def __init__(self, project_root: Path, config: GovernanceConfig, manifest_rel: str, result: CheckResult) -> None:
        self.project_root = project_root
        self.config = config
        self.manifest_rel = manifest_rel
        self.result = result
        self._formal_paths: dict[str, str] | None = None
        self._run_manifests: dict[str, runmodel.PromotionManifest | None] = {}
        self._run_atoms: dict[str, dict[str, runmodel.TsvRow]] = {}
        self._atom_pin_ok: dict[str, bool] = {}
        self._closure_ok: dict[str, bool] = {}

    def _error(self, locator: str, message: str) -> None:
        self.result.findings.append(error(CHECK_ID, self.manifest_rel, locator, message))

    def check(self, manifest: runmodel.ProjectionManifest) -> None:
        self._check_scope_disjointness(manifest)
        self._check_authority_coverage(manifest)
        for index, entry in enumerate(manifest.entries):
            self._check_entry(f"entries[{index}]", entry)

    def _check_scope_disjointness(self, manifest: runmodel.ProjectionManifest) -> None:
        seen: dict[str, str] = {}
        for index, entry in enumerate(manifest.entries):
            where = f"entries[{index}]"
            for scope_id in (entry.scope_id, *entry.covered_scope_ids):
                if scope_id in seen:
                    self._error(
                        where,
                        f"scope {scope_id!r} already claimed by {seen[scope_id]} (covered_scope_ids must be disjoint)",
                    )
                else:
                    seen[scope_id] = where

    def _check_authority_coverage(self, manifest: runmodel.ProjectionManifest) -> None:
        """Claimed scopes must equal the authority_over scopes of the assertion sources."""
        claimed: set[str] = set()
        derived: set[str] = set()
        for entry in manifest.entries:
            claimed.update((entry.scope_id, *entry.covered_scope_ids))
            derived.update(self._authority_scopes(entry.assertion_source.path))
        for scope_id in sorted(derived - claimed):
            self._error("entries", f"authority scope {scope_id!r} of an assertion source is not covered by any manifest entry")
        for scope_id in sorted(claimed - derived):
            self._error("entries", f"claimed scope {scope_id!r} is not derived from any assertion source's authority_over")

    def _authority_scopes(self, rel_path: str) -> set[str]:
        source_path = self.project_root / rel_path
        if not source_path.is_file() or not rel_path.lower().endswith((".md", ".markdown")):
            return set()
        document = load_document(self.project_root, "meta", source_path)
        if document.frontmatter is None:
            return set()
        authority = document.frontmatter.get("authority_over")
        if not isinstance(authority, list):
            return set()
        scopes: set[str] = set()
        for item in authority:
            if isinstance(item, dict):
                scope = item.get("scope")
                if isinstance(scope, str) and scope:
                    scopes.add(scope)
        return scopes

    def _check_entry(self, where: str, entry: ProjectionEntry) -> None:
        self._check_assertion_source(where, entry)
        self._check_lifecycle_source(where, entry)
        derived_statuses: list[str] = []
        for proj_index, projection in enumerate(entry.required_projections):
            proj_where = f"{where}.required_projections[{proj_index}]"
            derived = self._derive_equivalence(proj_where, entry, projection)
            derived_statuses.append(derived)
            if derived != projection.equivalence_status:
                self._error(
                    proj_where,
                    f"derived status mismatch: recorded {projection.equivalence_status!r}, "
                    f"derived {derived!r} for target {projection.target!r}",
                )
        self._check_assertion_status(where, entry, derived_statuses)
        for blocker_index, blocker in enumerate(entry.blockers):
            self._check_blocker_anchor(f"{where}.blockers[{blocker_index}]", blocker.visible_anchor)

    def _check_assertion_source(self, where: str, entry: ProjectionEntry) -> None:
        source = entry.assertion_source
        source_path = self.project_root / source.path
        if not source_path.is_file():
            self._error(f"{where}.assertion_source", f"assertion source does not exist: {source.path}")
            return
        if source.digest is None:
            if entry.lifecycle == "current":
                self._error(
                    f"{where}.assertion_source",
                    "digest must be non-null for a current assertion (non-null before every landing)",
                )
            return
        if file_digest_sha256(source_path) != source.digest:
            self._error(f"{where}.assertion_source", f"stale-source: digest does not match the current {source.path}")

    def _check_lifecycle_source(self, where: str, entry: ProjectionEntry) -> None:
        lifecycle_where = f"{where}.lifecycle_source"
        source = entry.lifecycle_source
        record_path = self.project_root / source.path
        if not record_path.is_file():
            self._error(lifecycle_where, f"decision record does not exist: {source.path}")
            return
        if file_digest_sha256(record_path) != source.digest:
            self._error(lifecycle_where, f"decision record digest does not match {source.path}")
        document = load_document(self.project_root, "meta", record_path)
        decision_status = document.frontmatter.get("decision_status") if document.frontmatter is not None else None
        if not isinstance(decision_status, str) or decision_status not in runmodel.DECISION_STATUSES:
            self._error(
                lifecycle_where,
                f"decision record frontmatter must carry a machine-readable decision_status "
                f"({', '.join(runmodel.DECISION_STATUSES)}): {source.path}",
            )
            return
        if decision_status != source.status:
            self._error(
                lifecycle_where,
                f"recorded status {source.status!r} does not match the decision record's decision_status {decision_status!r}",
            )
        if entry.lifecycle == "current" and decision_status != "accepted":
            self._error(lifecycle_where, f"current lifecycle requires an accepted decision record, got {decision_status!r}")

    # -- equivalence derivation ---------------------------------------------

    def _derive_equivalence(self, where: str, entry: ProjectionEntry, projection: RequiredProjection) -> str:
        actual_digest, target_exists, target_path = self._resolve_target(where, entry, projection)
        if not target_exists:
            return "blocked_missing_target"
        if projection.target_digest is not None and projection.target_digest != actual_digest:
            return "stale"
        if projection.receipt_ref is None:
            return "unreviewed"
        receipt_path = self.project_root / projection.receipt_ref
        if not receipt_path.is_file():
            return "unreviewed"
        receipt, issues = runmodel.load_projection_receipt(receipt_path)
        for issue in issues:
            self.result.findings.append(error(CHECK_ID, projection.receipt_ref, issue.locator, issue.message))
        if receipt is None:
            return "unreviewed"
        if not self._receipt_bound(where, entry, projection, receipt, target_path):
            return "unreviewed"
        if receipt.verdict == "disagrees":
            return "disagrees"
        return "equivalent"

    def _receipt_bound(
        self,
        where: str,
        entry: ProjectionEntry,
        projection: RequiredProjection,
        receipt: runmodel.ProjectionReceipt,
        target_path: str | None,
    ) -> bool:
        """Re-verify the promotion closure that would justify this activation.

        Beyond binding the receipt to the promoting run, its atom, scope
        and target, this re-runs the shared receipt engine (statement and
        target digests, independence) and requires the scope to actually
        carry ``promotion_disposition = promoted`` in that run's manifest,
        with the atom register pinned by ``RUN.register_digests``.
        """
        if entry.last_run_id is None:
            self._error(where, "receipt_ref requires last_run_id to bind the promoting run")
            return False
        if entry.last_promotion_manifest is None:
            self._error(where, "receipt_ref requires a last_promotion_manifest pointer (path + digest)")
            return False
        manifest = self._promotion_manifest(where, entry)
        if manifest is None:
            return False
        run_dir_rel = f"{self.config.incubator_root}/runs/{entry.last_run_id}"
        receipts_prefix = f"{run_dir_rel}/{manifest.receipts_dir}/"
        assert projection.receipt_ref is not None
        if not projection.receipt_ref.startswith(receipts_prefix):
            self._error(
                where,
                f"receipt {projection.receipt_ref} is not registered under the run's receipts_dir {receipts_prefix}",
            )
            return False
        if not self._atom_register_pinned(where, run_dir_rel):
            return False
        atom = self._run_atom_register(run_dir_rel).get(receipt.atom_id)
        if atom is None:
            self._error(
                where,
                f"receipt {receipt.receipt_id} references atom {receipt.atom_id} absent from the run's atom register",
            )
            return False
        bound = self._atom_binding_holds(where, entry, receipt, atom, target_path)
        bound = self._scope_promoted(where, manifest, atom["expected_authority"]) and bound
        bound = self._promotion_closure_holds(entry.last_run_id) and bound
        for problem in verify_receipt_against_atom(
            self.project_root, receipt, atom, target_mode=projection.target_mode, selector=projection.selector
        ):
            self._error(where, f"receipt {receipt.receipt_id}: {problem.message}")
            bound = False
        return bound

    def _atom_binding_holds(
        self,
        where: str,
        entry: ProjectionEntry,
        receipt: runmodel.ProjectionReceipt,
        atom: runmodel.TsvRow,
        target_path: str | None,
    ) -> bool:
        bound = True
        if receipt.receipt_id not in runmodel.split_refs(atom["receipt_refs"]):
            self._error(where, f"atom {receipt.atom_id} does not register receipt {receipt.receipt_id} in receipt_refs")
            bound = False
        if atom["expected_authority"] not in {entry.scope_id, *entry.covered_scope_ids}:
            self._error(
                where,
                f"atom {receipt.atom_id} belongs to scope {atom['expected_authority']!r}, which this entry does not claim",
            )
            bound = False
        if target_path is not None and receipt.target.path != target_path:
            self._error(where, f"receipt covers {receipt.target.path!r}, not the resolved projection target {target_path!r}")
            bound = False
        return bound

    def _scope_promoted(self, where: str, manifest: runmodel.PromotionManifest, scope_id: str) -> bool:
        for scope in manifest.scopes:
            if scope.scope_id != scope_id:
                continue
            if scope.promotion_disposition != "promoted":
                self._error(
                    where,
                    f"scope {scope_id!r} carries promotion_disposition "
                    f"{scope.promotion_disposition!r} in the promoting run, not 'promoted'",
                )
                return False
            return True
        self._error(where, f"scope {scope_id!r} is not present in the promotion manifest of the promoting run")
        return False

    def _promotion_closure_holds(self, run_id: str) -> bool:
        """Re-run the FULL promotion check for the promoting run.

        A self-consistent manifest is not enough: required sets, coverage
        registers, findings, semantic gates, reverse trace and lock
        closure are revalidated here, so a run that never passed
        ``check.py promotion`` can never activate a scope.
        """
        if run_id in self._closure_ok:
            return self._closure_ok[run_id]
        run_dir = self.project_root / self.config.incubator_root / "runs" / run_id
        result = run_promotion_check(self.project_root, self.config, run_dir)
        prefix = f"promotion closure for run {run_id}: "
        for finding in result.findings:
            self.result.findings.append(error(CHECK_ID, finding.path, finding.locator, prefix + finding.message))
        ok = not result.findings and result.complete
        if not result.complete:
            self.result.findings.append(
                error(CHECK_ID, self.manifest_rel, "entries", prefix + f"INCOMPLETE ({result.incomplete_reason})")
            )
        self._closure_ok[run_id] = ok
        return ok

    def _atom_register_pinned(self, where: str, run_dir_rel: str) -> bool:
        """The run's atom register must equal RUN.register_digests.atom_register."""
        if run_dir_rel in self._atom_pin_ok:
            return self._atom_pin_ok[run_dir_rel]
        run_path = self.project_root / run_dir_rel / "RUN.json"
        register_path = self.project_root / run_dir_rel / "promotion" / "atom-register.tsv"
        ok = False
        if not run_path.is_file():
            self._error(where, f"promoting run has no RUN.json: {run_dir_rel}/RUN.json")
        elif not register_path.is_file():
            self._error(where, f"promoting run has no atom register: {run_dir_rel}/promotion/atom-register.tsv")
        else:
            run, issues = runmodel.load_run_state(run_path)
            for issue in issues:
                self.result.findings.append(error(CHECK_ID, f"{run_dir_rel}/RUN.json", issue.locator, issue.message))
            pinned = run.register_digests.get("atom_register") if run is not None else None
            if pinned is None:
                self._error(where, "promoting run does not pin register_digests.atom_register")
            elif pinned != file_digest_sha256(register_path):
                self._error(where, "atom register of the promoting run does not match its pinned register_digests digest")
            else:
                ok = True
        self._atom_pin_ok[run_dir_rel] = ok
        return ok

    def _promotion_manifest(self, where: str, entry: ProjectionEntry) -> runmodel.PromotionManifest | None:
        run_id = entry.last_run_id
        assert run_id is not None
        if run_id not in self._run_manifests:
            run_dir_rel = f"{self.config.incubator_root}/runs/{run_id}"
            if entry.last_promotion_manifest is not None:
                manifest_rel = entry.last_promotion_manifest.path
            else:
                manifest_rel = f"{run_dir_rel}/promotion/promotion-manifest.json"
            manifest_path = self.project_root / manifest_rel
            manifest: runmodel.PromotionManifest | None = None
            if not manifest_path.is_file():
                self._error(where, f"promotion manifest of run {run_id} not found: {manifest_rel}")
            else:
                pointer = entry.last_promotion_manifest
                if pointer is not None and file_digest_sha256(manifest_path) != pointer.digest:
                    self._error(where, f"last_promotion_manifest digest does not match {manifest_rel}")
                manifest, issues = runmodel.load_promotion_manifest(manifest_path)
                for issue in issues:
                    self.result.findings.append(error(CHECK_ID, manifest_rel, issue.locator, issue.message))
                if manifest is not None and manifest.run_id != run_id:
                    self._error(where, f"promotion manifest {manifest_rel} belongs to run {manifest.run_id!r}, not {run_id!r}")
                    manifest = None
            self._run_manifests[run_id] = manifest
        return self._run_manifests[run_id]

    def _run_atom_register(self, run_dir_rel: str) -> dict[str, runmodel.TsvRow]:
        if run_dir_rel not in self._run_atoms:
            register_path = self.project_root / run_dir_rel / "promotion" / "atom-register.tsv"
            atoms: dict[str, runmodel.TsvRow] = {}
            if register_path.is_file():
                rows, issues = runmodel.load_atom_register(register_path)
                for issue in issues:
                    self.result.findings.append(
                        error(CHECK_ID, f"{run_dir_rel}/promotion/atom-register.tsv", issue.locator, issue.message)
                    )
                atoms = {row["atom_id"]: row for row in rows}
            self._run_atoms[run_dir_rel] = atoms
        return self._run_atoms[run_dir_rel]

    def _resolve_target(
        self, where: str, entry: ProjectionEntry, projection: RequiredProjection
    ) -> tuple[str | None, bool, str | None]:
        """Resolve target existence, its current digest, and its file path.

        The digest rule follows ``target_mode`` (see :mod:`receipts`), so
        every mode yields a verifiable digest — including JSON/YAML
        selectors and directory trees.
        """
        target = projection.target
        if projection.kind == "formal":
            formal_path = self._formal_index().get(target)
            if formal_path is None:
                return None, False, None
            target = formal_path
        path = target.partition("#")[0]
        if path == self.manifest_rel and projection.target_mode != "markdown-section":
            return runmodel.canonical_projection_entry_digest(entry.raw, projection.target), True, path
        result = compute_target_digest(self.project_root, target, projection.target_mode, projection.selector)
        if result.missing:
            return None, False, path
        if result.problem is not None:
            self._error(where, result.problem)
            return None, True, path
        return result.digest, True, path

    def _formal_index(self) -> dict[str, str]:
        if self._formal_paths is None:
            self._formal_paths = {}
            for document in scan_documents(self.project_root, {"formal": self.config.concept_roots["formal"]}):
                if document.frontmatter is None:
                    continue
                object_id = document.frontmatter.get("id")
                if isinstance(object_id, str) and object_id:
                    self._formal_paths[object_id] = document.rel_path
        return self._formal_paths

    # -- assertion status ---------------------------------------------------

    def _check_assertion_status(self, where: str, entry: ProjectionEntry, derived_statuses: list[str]) -> None:
        if entry.lifecycle != "current":
            return
        all_equivalent = all(status == "equivalent" for status in derived_statuses)
        digests_bound = all(projection.target_digest is not None for projection in entry.required_projections)
        derived = "active" if all_equivalent and digests_bound and not entry.blockers else "blocked_projection"
        if entry.assertion_status != derived:
            self._error(
                f"{where}.assertion_status",
                f"derived status mismatch: recorded {entry.assertion_status!r}, "
                f"derived {derived!r} (lifecycle-first for current)",
            )

    def _check_blocker_anchor(self, where: str, visible_anchor: str) -> None:
        path, separator, anchor = visible_anchor.partition("#")
        if not separator or not path or not anchor:
            self._error(where, f"visible_anchor must be <file>#<anchor>, got {visible_anchor!r}")
            return
        target_path = self.project_root / path
        if not target_path.is_file():
            self._error(where, f"visible_anchor file does not exist: {path}")
            return
        if not path.lower().endswith((".md", ".markdown")) or anchor not in anchor_slugs(target_path.read_text(encoding="utf-8")):
            self._error(where, f"visible_anchor does not resolve: {visible_anchor}")
