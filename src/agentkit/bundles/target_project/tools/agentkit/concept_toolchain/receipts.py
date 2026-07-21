"""Shared target-mode digest engine and receipt verification (FK-78 78.10/78.12).

Single implementation used by both the promotion checker and the
projection checker, so a receipt is digested exactly once per contract.

Target modes and their canonical digest rules:

``markdown-section``
    ``<path>#<anchor>``: SHA-256 over the LF-normalized section text of
    the smallest heading section carrying that anchor (unit partition of
    :mod:`units`).
``whole-file``
    SHA-256 over the file's raw bytes (JSON/YAML/registries/plain files).
``structured-selector``
    SHA-256 over the canonically serialized subtree selected by
    ``selector`` inside a JSON or SMY/YAML document: ``json.dumps`` with
    sorted keys, compact separators, UTF-8, no ASCII escaping. Supported
    selector grammar: ``<key>`` and ``<key>[<idfield>=<value>]``,
    chainable with ``.`` (e.g. ``domains[id=concept-incubation].member_docs``).
``directory-tree``
    SHA-256 over the sorted listing ``<relpath>\\t<sha256>`` (one line per
    non-ignored file below the directory, LF-joined, trailing LF).
    Ignored: dotted path segments and ``__pycache__``.

Every mode yields a non-null digest, so ``target_digest`` is verifiable
for every declared projection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .docmodel import file_digest_sha256
from .smy import SmyError, parse_smy
from .units import section_index, text_digest

if TYPE_CHECKING:
    from pathlib import Path

    from .runmodel import ProjectionReceipt, TsvRow

TARGET_MODES = ("markdown-section", "whole-file", "structured-selector", "directory-tree")

_SELECTOR_STEP_RE = re.compile(r"^(?P<key>[A-Za-z0-9_-]+)(?:\[(?P<field>[A-Za-z0-9_-]+)=(?P<value>[^\]]+)\])?$")
_IGNORED_DIR_NAMES = ("__pycache__",)


@dataclass(frozen=True)
class DigestResult:
    """Outcome of one target digest computation.

    Attributes:
        digest: The computed digest, or ``None`` when the target could not
            be resolved.
        missing: ``True`` when the target itself does not exist (maps onto
            ``blocked_missing_target``).
        problem: Human-readable reason when the digest could not be
            computed for a reason other than a missing target (malformed
            selector, unparseable document, …).
    """

    digest: str | None
    missing: bool = False
    problem: str | None = None


def compute_target_digest(project_root: Path, target: str, mode: str, selector: str | None) -> DigestResult:
    """Compute the canonical digest of one projection target.

    Args:
        project_root: Target-project root.
        target: ``<path>`` or ``<path>#<anchor>`` reference.
        mode: One of :data:`TARGET_MODES`.
        selector: Selector expression for ``structured-selector`` mode.

    Returns:
        The digest result (see :class:`DigestResult`).
    """
    path, _, anchor = target.partition("#")
    absolute = project_root / path
    if mode == "markdown-section":
        return _markdown_section_digest(absolute, path, anchor)
    if mode == "whole-file":
        if not absolute.is_file():
            return DigestResult(digest=None, missing=True)
        return DigestResult(digest=file_digest_sha256(absolute))
    if mode == "structured-selector":
        return _structured_selector_digest(absolute, selector)
    if mode == "directory-tree":
        if not absolute.is_dir():
            return DigestResult(digest=None, missing=True)
        return DigestResult(digest=directory_tree_digest(absolute))
    return DigestResult(digest=None, problem=f"unknown target_mode {mode!r}")


def _markdown_section_digest(absolute: Path, path: str, anchor: str) -> DigestResult:
    if not absolute.is_file():
        return DigestResult(digest=None, missing=True)
    if not anchor:
        return DigestResult(digest=None, problem="markdown-section target requires a '#<anchor>' fragment")
    sections = section_index(path, absolute.read_text(encoding="utf-8"))
    unit = sections.get(anchor)
    if unit is None:
        return DigestResult(digest=None, missing=True, problem=f"anchor does not resolve: {path}#{anchor}")
    return DigestResult(digest=unit.digest)


def _structured_selector_digest(absolute: Path, selector: str | None) -> DigestResult:
    if not absolute.is_file():
        return DigestResult(digest=None, missing=True)
    if not selector:
        return DigestResult(digest=None, problem="structured-selector target requires a selector")
    document = _load_structured(absolute)
    if document is None:
        return DigestResult(digest=None, problem=f"target is not parseable as JSON or SMY: {absolute.name}")
    node, problem = resolve_selector(document, selector)
    if problem is not None:
        return DigestResult(digest=None, problem=problem)
    return DigestResult(digest=canonical_json_digest(node))


def _load_structured(path: Path) -> object | None:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed
    try:
        return parse_smy(_strip_yaml_document_marker(text))
    except SmyError:
        return None


def _strip_yaml_document_marker(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        return "\n".join(lines[1:])
    return text


def resolve_selector(document: object, selector: str) -> tuple[object, str | None]:
    """Resolve a selector expression against a parsed document.

    Returns:
        A tuple of the selected subtree and an error message (``None`` on
        success). The subtree is ``None`` when an error is reported.
    """
    node: object = document
    for step in selector.split("."):
        match = _SELECTOR_STEP_RE.match(step)
        if match is None:
            return None, f"malformed selector step {step!r} in {selector!r}"
        if not isinstance(node, dict):
            return None, f"selector step {step!r} does not apply to a non-mapping node in {selector!r}"
        key = match.group("key")
        if key not in node:
            return None, f"selector key {key!r} not found in {selector!r}"
        node = node[key]
        field, value = match.group("field"), match.group("value")
        if field is None:
            continue
        if not isinstance(node, list):
            return None, f"selector filter [{field}={value}] requires a sequence in {selector!r}"
        matches = [item for item in node if isinstance(item, dict) and item.get(field) == value]
        if len(matches) != 1:
            return None, f"selector filter [{field}={value}] matched {len(matches)} entries in {selector!r}"
        node = matches[0]
    return node, None


def canonical_json_digest(node: object) -> str:
    """Digest a parsed subtree via canonical JSON serialization."""
    canonical = json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def directory_tree_digest(directory: Path) -> str:
    """Digest a directory as the sorted ``<relpath>\\t<sha256>`` listing."""
    lines: list[str] = []
    for entry in sorted(directory.rglob("*")):
        if not entry.is_file():
            continue
        relative = entry.relative_to(directory)
        parts = relative.parts
        if any(part.startswith(".") for part in parts) or any(part in _IGNORED_DIR_NAMES for part in parts):
            continue
        lines.append(f"{relative.as_posix()}\t{file_digest_sha256(entry)}")
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def atom_statement_digest(statement_field: str) -> str:
    """Digest one atom statement exactly as a receipt's ``source_digest``."""
    return text_digest(statement_field.replace("\\n", "\n"))


@dataclass(frozen=True)
class ReceiptProblem:
    """One receipt-verification problem with a stable locator suffix."""

    locator: str
    message: str


@dataclass(frozen=True)
class TargetSpec:
    """Canonical addressing of one projection target.

    ``anchor`` is set only for ``markdown-section``; ``selector`` only for
    ``structured-selector``.
    """

    path: str
    anchor: str | None
    target_mode: str
    selector: str | None

    @property
    def reference(self) -> str:
        """Return the ``<path>`` / ``<path>#<anchor>`` target reference."""
        return f"{self.path}#{self.anchor}" if self.anchor else self.path

    @classmethod
    def from_receipt(cls, receipt: ProjectionReceipt) -> TargetSpec:
        """Build the spec a receipt declares for itself."""
        return cls(
            path=receipt.target.path,
            anchor=receipt.target.anchor or None,
            target_mode=receipt.target_mode,
            selector=receipt.selector,
        )


def verify_receipt_against_atom(
    project_root: Path,
    receipt: ProjectionReceipt,
    atom: TsvRow,
    *,
    target_mode: str,
    selector: str | None,
) -> list[ReceiptProblem]:
    """Verify one receipt against its atom row (shared closure engine).

    Checks writer/reviewer independence (principal AND session), atom
    binding, declared-target coverage, the atom-statement source digest,
    and the current target digest. ``target_mode`` is mandatory: callers
    pass the mode the *consumer* requires, and a receipt declaring a
    different mode is rejected — there is no implicit default.
    """
    problems: list[ReceiptProblem] = []
    if receipt.target_mode != target_mode:
        problems.append(
            ReceiptProblem(
                "target_mode",
                f"receipt declares target_mode {receipt.target_mode!r} but {target_mode!r} is required here",
            )
        )
        return problems
    if receipt.selector != selector:
        problems.append(
            ReceiptProblem("selector", f"receipt selector {receipt.selector!r} does not match the required {selector!r}")
        )
        return problems
    if receipt.writer_principal_id == receipt.reviewer_principal_id:
        problems.append(ReceiptProblem("independence", "reviewer principal must differ from the writer principal"))
    if receipt.writer_session_ref == receipt.reviewer_session_ref:
        problems.append(ReceiptProblem("independence", "reviewer session must differ from the writer session"))
    if receipt.atom_id != atom["atom_id"]:
        problems.append(ReceiptProblem("atom", f"receipt is bound to atom {receipt.atom_id}, not {atom['atom_id']}"))
        return problems
    spec = TargetSpec.from_receipt(receipt)
    target_ref = spec.reference
    declared = {ref for ref in atom["target_refs"].split(";") if ref}
    if target_ref not in declared:
        problems.append(ReceiptProblem("target", f"receipt covers undeclared target {target_ref}"))
    expected_source = atom_statement_digest(atom["statement"])
    if receipt.source_digest != expected_source:
        problems.append(ReceiptProblem("source_digest", "source_digest does not match the atom statement"))
    result = compute_target_digest(project_root, target_ref, spec.target_mode, spec.selector)
    if result.missing:
        problems.append(ReceiptProblem("target", f"receipt target does not resolve: {target_ref}"))
    elif result.problem is not None:
        problems.append(ReceiptProblem("target", result.problem))
    elif result.digest != receipt.target_section_digest:
        problems.append(
            ReceiptProblem("target_section_digest", f"target_section_digest does not match the current target {target_ref}")
        )
    return problems
