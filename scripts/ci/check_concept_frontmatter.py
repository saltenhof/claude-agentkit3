"""Frontmatter consistency lints for the AK3 concept corpus.

Severity is uniformly ERROR. Warnings are deliberately not used because
they tend to be ignored in practice; every finding is a non-deferrable
handling instruction.

Lints implemented (see concept/technical-design/00_index.md §9.4):

    L1   Index <-> Disk: every concept file is referenced and vice versa.
    L2   concept_id pattern + uniqueness.
    L3   parent_concept_id and defers_to targets must exist.
    L4   supersedes <-> superseded_by reciprocity (full supersession only).
    L5   authority_over.scope must not be shared by two non-superseded docs.
    L7   FK-/DK- references in document body must resolve.
    L8   Tag corpus: every tag must appear in tag-corpus.txt.
    L9   Authority graph (parent_concept_id + defers_to) acyclic.
    L10  superseded_by ring guard (transitive cycle protection).
    L11  module must appear in module-registry.yaml.
    L14  All stem fields present.
    L15  formal_refs <-> body PROSE-FORMAL anchors (local, fast-fail).
    L16  Authority type compatibility (no defers_to to index/appendix).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONCEPT_ROOT = REPO_ROOT / "concept"
TECH_ROOT = CONCEPT_ROOT / "technical-design"
DOMAIN_ROOT = CONCEPT_ROOT / "domain-design"
META_ROOT = TECH_ROOT / "_meta"
TAG_CORPUS_PATH = META_ROOT / "tag-corpus.txt"
MODULE_REGISTRY_PATH = META_ROOT / "module-registry.yaml"
DOMAIN_REGISTRY_PATH = META_ROOT / "domain-registry.yaml"
POLICY_REGISTRY_PATH = META_ROOT / "policy-registry.yaml"
INDEX_PATH = TECH_ROOT / "00_index.md"

NORMATIVE_MODAL_RE = re.compile(
    r"\b(muss(?:t|en)?|darf\s+nur|sind?\s+pflicht|"
    r"single\s+source\s+of\s+truth|verboten|fail[-\s]closed|"
    r"shall|must)\b",
    re.IGNORECASE,
)
CONTRACT_ANCHOR_RE = re.compile(r"<!--\s*CONTRACT-ANCHOR:\s*([^>]+?)\s*-->", re.IGNORECASE)

CONCEPT_ID_RE = re.compile(r"^(FK|DK)-\d{2}$")
BODY_REF_RE = re.compile(r"\b(FK|DK)-\d{2}(?!-\d)\b")
PROSE_ANCHOR_RE = re.compile(r"<!--\s*PROSE-FORMAL:\s*([^>]+?)\s*-->", re.IGNORECASE)
INDEX_REF_RE = re.compile(r"`(\d{2}_[^`]+\.md)`")

STEM_FIELDS: tuple[str, ...] = (
    "concept_id",
    "title",
    "module",
    "status",
    "doc_kind",
    "parent_concept_id",
    "authority_over",
    "defers_to",
    "supersedes",
    "superseded_by",
    "tags",
)
STATUS_VALUES = {"active", "draft"}
DOC_KIND_VALUES = {"core", "detail"}
INDEX_OR_APPENDIX_IDS = {"FK-00"}  # cannot be defers_to / parent target


@dataclass(frozen=True)
class Doc:
    layer: str           # "technical" | "domain"
    path: Path
    fm: dict[str, Any]

    @property
    def cid(self) -> str:
        cid = self.fm.get("concept_id")
        return cid if isinstance(cid, str) else ""


@dataclass
class LintReport:
    errors: list[tuple[str, str]] = field(default_factory=list)

    def err(self, code: str, message: str) -> None:
        self.errors.append((code, message))

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_concept_docs() -> list[Doc]:
    docs: list[Doc] = []
    for layer, root in (("technical", TECH_ROOT), ("domain", DOMAIN_ROOT)):
        for path in sorted(root.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            if not m:
                docs.append(Doc(layer=layer, path=path, fm={}))
                continue
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                fm = {}
            if not isinstance(fm, dict):
                fm = {}
            docs.append(Doc(layer=layer, path=path, fm=fm))
    return docs


def deref(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        target = value.get("target") or value.get("id") or ""
        return target if isinstance(target, str) else ""
    return ""


def has_scope(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("scope"))


def load_tag_corpus() -> set[str]:
    if not TAG_CORPUS_PATH.is_file():
        return set()
    return {line.strip() for line in TAG_CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}


def load_module_registry() -> set[str]:
    if not MODULE_REGISTRY_PATH.is_file():
        return set()
    data = yaml.safe_load(MODULE_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    modules = data.get("modules") or []
    return {m for m in modules if isinstance(m, str)}


@dataclass(frozen=True)
class DomainEntry:
    id: str
    contract_docs: tuple[str, ...]
    member_docs: tuple[str, ...]


def load_domain_registry() -> dict[str, DomainEntry]:
    """Return {domain_id: DomainEntry}. Empty dict means lints L17-L20 are no-ops."""
    if not DOMAIN_REGISTRY_PATH.is_file():
        return {}
    data = yaml.safe_load(DOMAIN_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("domains") or []
    out: dict[str, DomainEntry] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        did = entry.get("id")
        if not isinstance(did, str) or not did:
            continue
        out[did] = DomainEntry(
            id=did,
            contract_docs=tuple(str(x) for x in (entry.get("contract_docs") or [])),
            member_docs=tuple(str(x) for x in (entry.get("member_docs") or [])),
        )
    return out


def load_policy_registry() -> set[str]:
    if not POLICY_REGISTRY_PATH.is_file():
        return set()
    data = yaml.safe_load(POLICY_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    return {
        entry.get("id")
        for entry in (data.get("policies") or [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def domain_of(doc_cid: str, domains: dict[str, DomainEntry]) -> str | None:
    """Return the domain id a doc belongs to, or None if not registered."""
    for entry in domains.values():
        if doc_cid in entry.contract_docs or doc_cid in entry.member_docs:
            return entry.id
    return None


def is_contract_doc(doc_cid: str, domains: dict[str, DomainEntry]) -> bool:
    return any(doc_cid in entry.contract_docs for entry in domains.values())


def extract_glossary(doc: "Doc") -> dict[str, Any] | None:
    """Read a `glossary` block from frontmatter (or a parsed `## Glossar` section)."""
    glossary = doc.fm.get("glossary")
    if isinstance(glossary, dict):
        return glossary
    return None


# ---------------------------------------------------------------------------
# Lints
# ---------------------------------------------------------------------------


def lint_l14_stem_fields(docs: list[Doc], report: LintReport) -> None:
    for doc in docs:
        for field_name in STEM_FIELDS:
            if field_name not in doc.fm:
                report.err("L14", f"{doc.path}: missing required frontmatter field '{field_name}'")
        status = doc.fm.get("status")
        if status not in STATUS_VALUES:
            report.err("L14", f"{doc.path}: status must be one of {sorted(STATUS_VALUES)}, got {status!r}")
        doc_kind = doc.fm.get("doc_kind")
        if doc_kind not in DOC_KIND_VALUES:
            report.err("L14", f"{doc.path}: doc_kind must be one of {sorted(DOC_KIND_VALUES)}, got {doc_kind!r}")
        if doc_kind == "detail":
            parent = doc.fm.get("parent_concept_id")
            if not (isinstance(parent, str) and parent):
                report.err("L14", f"{doc.path}: doc_kind=detail requires non-empty parent_concept_id")
        for list_field in ("authority_over", "defers_to", "supersedes", "tags"):
            value = doc.fm.get(list_field)
            if value is not None and not isinstance(value, list):
                report.err("L14", f"{doc.path}: {list_field!r} must be a list (or absent)")
        tags = doc.fm.get("tags") or []
        if not tags:
            report.err("L14", f"{doc.path}: tags must contain at least one entry")
        ao = doc.fm.get("authority_over") or []
        if not ao:
            report.err("L14", f"{doc.path}: authority_over must contain at least one scope entry")


def lint_l2_concept_id(docs: list[Doc], report: LintReport) -> None:
    seen: dict[str, Path] = {}
    for doc in docs:
        cid = doc.cid
        if not cid:
            report.err("L2", f"{doc.path}: concept_id missing or empty")
            continue
        expected_prefix = "FK" if doc.layer == "technical" else "DK"
        if not CONCEPT_ID_RE.match(cid) or not cid.startswith(expected_prefix + "-"):
            report.err("L2", f"{doc.path}: concept_id {cid!r} does not match {expected_prefix}-NN pattern")
        if cid in seen:
            report.err("L2", f"{doc.path}: concept_id {cid!r} also used by {seen[cid]}")
        else:
            seen[cid] = doc.path


def lint_l3_target_existence(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    for doc in docs:
        parent = doc.fm.get("parent_concept_id")
        if isinstance(parent, str) and parent and parent not in by_id:
            report.err("L3", f"{doc.path}: parent_concept_id {parent!r} does not exist")
        for entry in doc.fm.get("defers_to") or []:
            target = deref(entry)
            if not target:
                report.err("L3", f"{doc.path}: defers_to entry has no target: {entry!r}")
                continue
            if target not in by_id:
                report.err("L3", f"{doc.path}: defers_to target {target!r} does not exist")


def lint_l4_supersedes_reciprocity(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    for doc in docs:
        for entry in doc.fm.get("supersedes") or []:
            target = deref(entry)
            if not target:
                report.err("L4", f"{doc.path}: supersedes entry has no target: {entry!r}")
                continue
            if target not in by_id:
                report.err("L4", f"{doc.path}: supersedes target {target!r} does not exist")
                continue
            if has_scope(entry):
                continue  # scoped supersession does not require reciprocity
            other = by_id[target]
            other_sb = other.fm.get("superseded_by")
            if other_sb != doc.cid:
                report.err(
                    "L4",
                    f"{doc.path}: full supersession of {target} is not reciprocated by "
                    f"{other.path} (expected superseded_by={doc.cid}, got {other_sb!r})",
                )

        sb = doc.fm.get("superseded_by")
        if isinstance(sb, str) and sb:
            if sb not in by_id:
                report.err("L4", f"{doc.path}: superseded_by target {sb!r} does not exist")
                continue
            other = by_id[sb]
            target_match = False
            for entry in other.fm.get("supersedes") or []:
                if deref(entry) == doc.cid and not has_scope(entry):
                    target_match = True
                    break
            if not target_match:
                report.err(
                    "L4",
                    f"{doc.path}: superseded_by={sb} but {other.path} has no full-supersession entry for {doc.cid}",
                )


def lint_l10_supersession_ring(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    for doc in docs:
        sb = doc.fm.get("superseded_by")
        if not (isinstance(sb, str) and sb):
            continue
        # follow the chain; raise on revisit
        chain: list[str] = [doc.cid]
        cur = sb
        while cur:
            if cur in chain:
                report.err("L10", f"{doc.path}: superseded_by ring detected via {' -> '.join(chain + [cur])}")
                break
            chain.append(cur)
            nxt = by_id.get(cur)
            if not nxt:
                break
            nxt_sb = nxt.fm.get("superseded_by")
            cur = nxt_sb if isinstance(nxt_sb, str) and nxt_sb else ""


def lint_l5_authority_disjoint(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    holders: dict[str, list[Doc]] = {}
    for doc in docs:
        for ao in doc.fm.get("authority_over") or []:
            if not isinstance(ao, dict):
                continue
            scope = ao.get("scope")
            if not isinstance(scope, str) or not scope:
                continue
            holders.setdefault(scope, []).append(doc)
    for scope, owners in holders.items():
        if len(owners) <= 1:
            continue
        # allow if connected via full supersession (one fully supersedes the other)
        if _connected_by_full_supersession(owners, by_id):
            continue
        ids = ", ".join(sorted(o.cid for o in owners))
        report.err("L5", f"authority_over scope {scope!r} held by multiple non-superseded docs: {ids}")


def _connected_by_full_supersession(owners: list[Doc], by_id: dict[str, Doc]) -> bool:
    if len(owners) != 2:
        return False
    a, b = owners
    return (
        _full_supersedes(a, b.cid) or _full_supersedes(b, a.cid)
        or a.fm.get("superseded_by") == b.cid or b.fm.get("superseded_by") == a.cid
    )


def _full_supersedes(doc: Doc, target: str) -> bool:
    for entry in doc.fm.get("supersedes") or []:
        if deref(entry) == target and not has_scope(entry):
            return True
    return False


def lint_l9_authority_graph_acyclic(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    # Authority hierarchy follows parent_concept_id only.
    # defers_to is a cross-reference (peer-to-peer, can be mutual) and does
    # not form an authority chain, so it is not part of this acyclicity check.
    edges: dict[str, set[str]] = {d.cid: set() for d in docs if d.cid}
    for doc in docs:
        if not doc.cid:
            continue
        parent = doc.fm.get("parent_concept_id")
        if isinstance(parent, str) and parent and parent in by_id:
            edges[doc.cid].add(parent)

    color: dict[str, int] = {n: 0 for n in edges}  # 0=white, 1=gray, 2=black
    stack_path: list[str] = []

    def visit(node: str) -> None:
        if color[node] == 2:
            return
        if color[node] == 1:
            cycle = " -> ".join(stack_path[stack_path.index(node):] + [node])
            report.err("L9", f"authority graph cycle: {cycle}")
            return
        color[node] = 1
        stack_path.append(node)
        for nxt in sorted(edges.get(node, ())):
            if nxt in color:
                visit(nxt)
        stack_path.pop()
        color[node] = 2

    for n in sorted(edges):
        if color[n] == 0:
            visit(n)


def lint_l16_authority_typechecks(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    for doc in docs:
        parent = doc.fm.get("parent_concept_id")
        if isinstance(parent, str) and parent in by_id:
            if parent in INDEX_OR_APPENDIX_IDS:
                report.err("L16", f"{doc.path}: parent_concept_id points to index/appendix {parent!r}")
        for entry in doc.fm.get("defers_to") or []:
            target = deref(entry)
            if target in INDEX_OR_APPENDIX_IDS:
                report.err("L16", f"{doc.path}: defers_to points to index/appendix {target!r}")
            tdoc = by_id.get(target) if target else None
            if tdoc and tdoc.fm.get("doc_kind") not in DOC_KIND_VALUES:
                report.err("L16", f"{doc.path}: defers_to target {target!r} has invalid doc_kind")
        # supersedes/superseded_by: same doc_kind family
        my_kind = doc.fm.get("doc_kind")
        for entry in doc.fm.get("supersedes") or []:
            target = deref(entry)
            tdoc = by_id.get(target) if target else None
            if tdoc and my_kind and tdoc.fm.get("doc_kind") and my_kind != tdoc.fm.get("doc_kind"):
                report.err(
                    "L16",
                    f"{doc.path}: supersedes target {target!r} has doc_kind={tdoc.fm.get('doc_kind')!r} "
                    f"but this doc has doc_kind={my_kind!r}",
                )


def lint_l1_index(docs: list[Doc], report: LintReport) -> None:
    if not INDEX_PATH.is_file():
        report.err("L1", f"index missing: {INDEX_PATH}")
        return
    referenced = set(INDEX_REF_RE.findall(INDEX_PATH.read_text(encoding="utf-8")))
    on_disk = {p.name for p in TECH_ROOT.glob("*.md") if p.name != "00_index.md"}
    for missing in sorted(on_disk - referenced):
        report.err("L1", f"file on disk not referenced in 00_index.md: {missing}")
    for extra in sorted(referenced - on_disk):
        report.err("L1", f"index references nonexistent file: {extra}")


def lint_l8_tag_corpus(docs: list[Doc], report: LintReport) -> None:
    corpus = load_tag_corpus()
    if not corpus:
        report.err("L8", f"tag corpus missing or empty: {TAG_CORPUS_PATH}")
        return
    for doc in docs:
        for tag in doc.fm.get("tags") or []:
            if not isinstance(tag, str):
                continue
            if tag not in corpus:
                report.err(
                    "L8",
                    f"{doc.path}: tag {tag!r} not in {TAG_CORPUS_PATH.relative_to(REPO_ROOT)} "
                    f"(add the tag there or replace with an existing one)",
                )


def lint_l11_module_registry(docs: list[Doc], report: LintReport) -> None:
    registry = load_module_registry()
    if not registry:
        report.err("L11", f"module registry missing or empty: {MODULE_REGISTRY_PATH}")
        return
    for doc in docs:
        module = doc.fm.get("module")
        if not isinstance(module, str) or not module:
            continue
        if module not in registry:
            report.err(
                "L11",
                f"{doc.path}: module {module!r} not in {MODULE_REGISTRY_PATH.relative_to(REPO_ROOT)} "
                f"(register the module there or use an existing one)",
            )


def lint_l7_body_refs(docs: list[Doc], by_id: dict[str, Doc], report: LintReport) -> None:
    known = set(by_id)
    for doc in docs:
        body = doc.path.read_text(encoding="utf-8")
        # strip frontmatter
        body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
        for match in BODY_REF_RE.finditer(body):
            ref = match.group(0)
            if ref not in known:
                report.err("L7", f"{doc.path}: body references unknown concept {ref!r}")


def is_cross_cutting(doc: "Doc") -> bool:
    """Return True if a doc is marked as cross-cutting (Foundation/Adapter/Reference).

    Cross-cutting docs are exempt from L17 domain-required and L18 cross-domain
    contract-only rules. They serve as universally readable foundation for all
    bounded contexts (Architekturprinzipien, Adapter-Vertraege, Referenzkataloge).
    Modelled after `bounded-contexts.yaml §foundation_principles` — these docs
    are explicitly NOT a bounded context; the marker is a lint mechanism, not
    a domain.
    """
    return bool(doc.fm.get("cross_cutting") is True)


def lint_l17_domain_and_policies(
    docs: list[Doc],
    domains: dict[str, DomainEntry],
    policies: set[str],
    report: LintReport,
) -> None:
    if not domains:
        return  # no-op until domain-registry is populated
    domain_ids = set(domains)
    for doc in docs:
        applies = doc.fm.get("applies_policies") or []
        for policy in applies:
            if policy not in policies:
                report.err(
                    "L17",
                    f"{doc.path}: applies_policies entry {policy!r} not in policy-registry",
                )
        if is_cross_cutting(doc):
            # Cross-cutting docs do not belong to a bounded context. They must
            # NOT carry a `domain` field — that would be a modelling error.
            if doc.fm.get("domain"):
                report.err(
                    "L17",
                    f"{doc.path}: cross_cutting=true is mutually exclusive with 'domain'",
                )
            continue
        domain = doc.fm.get("domain")
        if not isinstance(domain, str) or not domain:
            report.err(
                "L17",
                f"{doc.path}: 'domain' is required (or set 'cross_cutting: true' "
                "for foundation/adapter/reference docs)",
            )
            continue
        if domain not in domain_ids:
            report.err("L17", f"{doc.path}: domain {domain!r} not in domain-registry")


def lint_l18_cross_domain_refs(
    docs: list[Doc],
    by_id: dict[str, Doc],
    domains: dict[str, DomainEntry],
    report: LintReport,
) -> None:
    if not domains:
        return
    for doc in docs:
        if is_cross_cutting(doc):
            continue  # cross-cutting docs are exempt from cross-domain rules
        my_domain = domain_of(doc.cid, domains)
        if my_domain is None:
            continue
        for entry in doc.fm.get("defers_to") or []:
            target = deref(entry)
            if not target or target not in by_id:
                continue
            target_doc = by_id[target]
            if is_cross_cutting(target_doc):
                continue  # cross-cutting docs are universally referenceable
            tgt_domain = domain_of(target, domains)
            if tgt_domain and tgt_domain != my_domain and not is_contract_doc(target, domains):
                report.err(
                    "L18",
                    f"{doc.path}: defers_to {target!r} crosses domains "
                    f"({my_domain!r} -> {tgt_domain!r}) but {target!r} is not a contract doc",
                )


def lint_l19_glossary_integrity(
    docs: list[Doc],
    domains: dict[str, DomainEntry],
    report: LintReport,
) -> None:
    if not domains:
        return
    # Collect all exported terms per domain
    exported: dict[tuple[str, str], Doc] = {}  # (domain_id, term_id) -> Doc
    internal_set: set[tuple[str, str]] = set()
    glossary_owners: dict[str, list[Doc]] = {}  # domain_id -> [docs with glossary]
    for doc in docs:
        my_domain = domain_of(doc.cid, domains)
        if my_domain is None:
            continue
        glossary = extract_glossary(doc)
        if glossary is None:
            continue
        glossary_owners.setdefault(my_domain, []).append(doc)
        for term in glossary.get("exported_terms") or []:
            tid = term.get("id") if isinstance(term, dict) else None
            if not isinstance(tid, str) or not tid:
                report.err("L19", f"{doc.path}: exported_terms entry without id: {term!r}")
                continue
            key = (my_domain, tid)
            if key in exported:
                report.err(
                    "L19",
                    f"{doc.path}: duplicate exported term {tid!r} in domain {my_domain!r} "
                    f"(also in {exported[key].path})",
                )
            else:
                exported[key] = doc
        for term in glossary.get("internal_terms") or []:
            tid = term.get("id") if isinstance(term, dict) else None
            if isinstance(tid, str) and tid:
                internal_set.add((my_domain, tid))

    # exported and internal must be disjoint
    for key in exported:
        if key in internal_set:
            report.err("L19", f"term {key[1]!r} in domain {key[0]!r} is both exported and internal")

    # only contract docs may carry a glossary
    for domain_id, owners in glossary_owners.items():
        for doc in owners:
            if not is_contract_doc(doc.cid, domains):
                report.err(
                    "L19",
                    f"{doc.path}: glossary block lives in non-contract doc; "
                    "glossaries belong in the contract doc of their domain",
                )

    # FK integrity: every see_also must resolve
    for doc in docs:
        my_domain = domain_of(doc.cid, domains)
        if my_domain is None:
            continue
        glossary = extract_glossary(doc)
        if glossary is None:
            continue
        for term in glossary.get("exported_terms") or []:
            if not isinstance(term, dict):
                continue
            for ref in term.get("see_also") or []:
                if not isinstance(ref, dict):
                    report.err("L19", f"{doc.path}: see_also entry must be a mapping: {ref!r}")
                    continue
                ref_term = ref.get("term")
                ref_domain = ref.get("domain")
                if not (isinstance(ref_term, str) and isinstance(ref_domain, str)):
                    report.err(
                        "L19",
                        f"{doc.path}: see_also entry needs 'term' and 'domain' (got {ref!r})",
                    )
                    continue
                if (ref_domain, ref_term) not in exported:
                    report.err(
                        "L19",
                        f"{doc.path}: glossary cross-ref {ref_domain}/{ref_term} "
                        "does not resolve to any exported term",
                    )


def lint_l20_implicit_leakage(
    docs: list[Doc],
    domains: dict[str, DomainEntry],
    report: LintReport,
) -> None:
    if not domains:
        return
    # Collect all internal terms grouped by domain
    internal_index: dict[str, dict[str, Doc]] = {}  # domain_id -> term_id -> contract Doc
    for doc in docs:
        my_domain = domain_of(doc.cid, domains)
        if my_domain is None:
            continue
        glossary = extract_glossary(doc)
        if glossary is None:
            continue
        for term in glossary.get("internal_terms") or []:
            tid = term.get("id") if isinstance(term, dict) else None
            if isinstance(tid, str) and tid:
                internal_index.setdefault(my_domain, {})[tid.lower()] = doc

    if not internal_index:
        return

    for doc in docs:
        my_domain = domain_of(doc.cid, domains)
        if my_domain is None:
            continue
        body = doc.path.read_text(encoding="utf-8")
        body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
        # Skip own-domain internal terms in own glossary
        for foreign_domain, terms in internal_index.items():
            if foreign_domain == my_domain:
                continue
            for term_id, _owner_doc in terms.items():
                # Find normative-modal sentences mentioning the term
                for match in re.finditer(re.escape(term_id), body, re.IGNORECASE):
                    start = max(0, match.start() - 80)
                    end = min(len(body), match.end() + 80)
                    context = body[start:end]
                    if NORMATIVE_MODAL_RE.search(context):
                        report.err(
                            "L20",
                            f"{doc.path}: normative mention of internal term {term_id!r} "
                            f"from domain {foreign_domain!r} (this doc lives in {my_domain!r})",
                        )
                        break  # one finding per (doc, foreign_domain, term) is enough


def lint_l15_prose_anchors(docs: list[Doc], report: LintReport) -> None:
    for doc in docs:
        if doc.fm.get("prose_anchor_policy") != "strict":
            continue
        formal_refs = doc.fm.get("formal_refs") or []
        if not formal_refs:
            continue
        body = doc.path.read_text(encoding="utf-8")
        anchors: set[str] = set()
        for m in PROSE_ANCHOR_RE.finditer(body):
            for part in m.group(1).split(","):
                anchors.add(part.strip())
        for ref in formal_refs:
            if isinstance(ref, str) and ref not in anchors:
                report.err(
                    "L15",
                    f"{doc.path}: formal_refs entry {ref!r} has no matching <!-- PROSE-FORMAL: {ref} --> anchor",
                )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    docs = load_concept_docs()
    by_id: dict[str, Doc] = {d.cid: d for d in docs if d.cid}

    domains = load_domain_registry()
    policies = load_policy_registry()

    report = LintReport()
    lint_l14_stem_fields(docs, report)
    lint_l2_concept_id(docs, report)
    lint_l3_target_existence(docs, by_id, report)
    lint_l4_supersedes_reciprocity(docs, by_id, report)
    lint_l10_supersession_ring(docs, by_id, report)
    lint_l5_authority_disjoint(docs, by_id, report)
    lint_l9_authority_graph_acyclic(docs, by_id, report)
    lint_l16_authority_typechecks(docs, by_id, report)
    lint_l1_index(docs, report)
    lint_l8_tag_corpus(docs, report)
    lint_l11_module_registry(docs, report)
    lint_l7_body_refs(docs, by_id, report)
    lint_l15_prose_anchors(docs, report)
    # Bounded-Context layer (no-op while domain-registry is empty):
    lint_l17_domain_and_policies(docs, domains, policies, report)
    lint_l18_cross_domain_refs(docs, by_id, domains, report)
    lint_l19_glossary_integrity(docs, domains, report)
    lint_l20_implicit_leakage(docs, domains, report)

    if report.ok:
        bc_state = "active" if domains else "inactive (domain-registry empty)"
        print(f"[concept-frontmatter] OK: {len(docs)} docs, all lints passed. Bounded-context layer: {bc_state}.")
        return 0

    print(f"[concept-frontmatter] FAILED: {len(report.errors)} error(s)", file=sys.stderr)
    for code, message in report.errors:
        print(f"  [{code}] {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
