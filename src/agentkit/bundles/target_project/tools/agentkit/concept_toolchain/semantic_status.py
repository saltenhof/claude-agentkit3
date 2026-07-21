"""Semantic-gate status accounting — ``check.py semantic-status <run-dir>``.

Validates the request packs (``semantic/requests/*.json``) and semantic
receipts (``semantic/receipts/*.json``) against the FK-78 section 78.14
schemas, settles completeness per gate and scope (receipt present,
``request_digest`` match, full chunk-digest binding, receipt status,
chunk freshness against the working tree), reports missing/stale/failed
receipts as blocking findings, and reconciles the computed gate states
with ``promotion-manifest.semantic_gates``. Missing LLM access or an
incomplete sweep blocks the affected scopes — never a silent PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import runmodel
from .docmodel import file_digest_sha256
from .findings import CheckResult, error

if TYPE_CHECKING:
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "semantic-status"


@dataclass
class _GateState:
    """Computed status of one semantic gate."""

    packs: int = 0
    blocking_scope_ids: set[str] = field(default_factory=set)


def run_semantic_status(project_root: Path, config: GovernanceConfig, run_dir: Path) -> CheckResult:
    """Run the semantic-status check for one run directory."""
    result = CheckResult(check_id=CHECK_ID)
    try:
        rel = run_dir.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        rel = run_dir.as_posix()
    if not run_dir.is_dir():
        result.complete = False
        result.incomplete_reason = f"run directory does not exist: {rel}"
        return result
    checker = _SemanticStatus(project_root, run_dir, rel, result)
    checker.run()
    return result


class _SemanticStatus:
    """Stateful executor for one semantic-status invocation."""

    def __init__(self, project_root: Path, run_dir: Path, rel: str, result: CheckResult) -> None:
        self.project_root = project_root
        self.run_dir = run_dir
        self.rel = rel
        self.result = result
        self.packs: dict[str, tuple[runmodel.SemanticRequestPack, str]] = {}
        self.receipts: dict[str, runmodel.SemanticReceipt] = {}
        self.states: dict[str, _GateState] = {gate: _GateState() for gate in runmodel.SEMANTIC_GATES}

    def _error(self, rel_path: str, locator: str, message: str) -> None:
        self.result.findings.append(error(CHECK_ID, rel_path, locator, message))

    def run(self) -> None:
        self._load_packs()
        self._load_receipts()
        self._settle_packs()
        self._reconcile_manifest()
        pack_count = len(self.packs)
        self.result.summary = f"{pack_count} request pack(s), {len(self.receipts)} receipt(s) settled"

    def _load_packs(self) -> None:
        requests_dir = self.run_dir / "semantic" / "requests"
        if not requests_dir.is_dir():
            return
        seen_scopes: set[tuple[str, str]] = set()
        for entry in sorted(requests_dir.glob("*.json")):
            rel = f"{self.rel}/semantic/requests/{entry.name}"
            pack, issues = runmodel.load_semantic_request_pack(entry)
            for issue in issues:
                self._error(rel, issue.locator, issue.message)
            if pack is None:
                continue
            if (pack.gate, pack.scope_id) in seen_scopes:
                self._error(rel, "pack.scope_id", f"duplicate request pack for gate {pack.gate!r} and scope {pack.scope_id!r}")
                continue
            seen_scopes.add((pack.gate, pack.scope_id))
            self.packs[pack.request_digest] = (pack, rel)
            self.states[pack.gate].packs += 1

    def _load_receipts(self) -> None:
        receipts_dir = self.run_dir / "semantic" / "receipts"
        if not receipts_dir.is_dir():
            return
        for entry in sorted(receipts_dir.glob("*.json")):
            rel = f"{self.rel}/semantic/receipts/{entry.name}"
            receipt, issues = runmodel.load_semantic_receipt(entry)
            for issue in issues:
                self._error(rel, issue.locator, issue.message)
            if receipt is None:
                continue
            matched = self.packs.get(receipt.request_digest)
            if matched is None:
                self._error(
                    rel,
                    "receipt.request_digest",
                    "receipt does not match any request pack (stale or foreign request_digest)",
                )
                continue
            pack, _ = matched
            if receipt.gate != pack.gate:
                self._error(rel, "receipt.gate", f"receipt gate {receipt.gate!r} does not match the pack gate {pack.gate!r}")
                continue
            if receipt.chunk_digests != tuple(chunk.digest for chunk in pack.chunks):
                self._error(
                    rel,
                    "receipt.chunk_digests",
                    "chunk digests do not match the request pack (incomplete digest binding)",
                )
                continue
            self.receipts[receipt.request_digest] = receipt

    def _settle_packs(self) -> None:
        for request_digest, (pack, rel) in sorted(self.packs.items()):
            state = self.states[pack.gate]
            stale_chunks = [chunk.path for chunk in pack.chunks if self._chunk_digest(chunk.path) != chunk.digest]
            receipt = self.receipts.get(request_digest)
            if stale_chunks:
                state.blocking_scope_ids.add(pack.scope_id)
                message = f"request pack is stale (chunks drifted: {', '.join(stale_chunks)}); blocking scope {pack.scope_id!r}"
                self._error(rel, "pack.chunks", message)
                continue
            if receipt is None:
                state.blocking_scope_ids.add(pack.scope_id)
                self._error(
                    rel,
                    "pack.request_digest",
                    f"no valid receipt for gate {pack.gate!r}; blocking scope {pack.scope_id!r}",
                )
                continue
            if receipt.status != "passed":
                state.blocking_scope_ids.add(pack.scope_id)
                self._error(rel, "pack.request_digest", f"receipt status {receipt.status!r} blocks scope {pack.scope_id!r}")

    def _chunk_digest(self, path: str) -> str | None:
        file_path = self.project_root / path
        return file_digest_sha256(file_path) if file_path.is_file() else None

    def _reconcile_manifest(self) -> None:
        manifest_path = self.run_dir / "promotion" / "promotion-manifest.json"
        if not manifest_path.is_file():
            return
        rel = f"{self.rel}/promotion/promotion-manifest.json"
        manifest, issues = runmodel.load_promotion_manifest(manifest_path)
        for issue in issues:
            self._error(rel, issue.locator, issue.message)
        if manifest is None:
            return
        manifest_scopes = {scope.scope_id for scope in manifest.scopes}
        pack_scopes: dict[str, set[str]] = {gate: set() for gate in runmodel.SEMANTIC_GATES}
        for pack, _ in self.packs.values():
            pack_scopes[pack.gate].add(pack.scope_id)
        for entry in manifest.semantic_gates:
            state = self.states.get(entry.gate)
            if state is None:
                continue
            blocking = set(state.blocking_scope_ids)
            if state.packs:
                blocking |= manifest_scopes - pack_scopes[entry.gate]
            computed_status = "not_run" if state.packs == 0 else ("blocked" if blocking else "passed")
            where = f"manifest.semantic_gates.{entry.gate}"
            if entry.status != computed_status:
                self._error(rel, where, f"recorded status {entry.status!r} does not match computed {computed_status!r}")
            if set(entry.blocking_scope_ids) != blocking:
                recorded = ", ".join(sorted(entry.blocking_scope_ids)) or "-"
                computed = ", ".join(sorted(blocking)) or "-"
                self._error(rel, where, f"recorded blocking_scope_ids [{recorded}] do not match computed [{computed}]")
