"""``concept_validate`` suite (FK-13 §13.9.7).

Exit codes: 0=valid, 1=warnings only, 2=errors, 3=internal failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.discovery import ConceptDocument, discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptDomainError, ConceptParseError
from agentkit.backend.concept_catalog.corpus.hashing import corpus_revision
from agentkit.backend.concept_catalog.corpus.parser import PARSER_VERSION
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile


@dataclass(frozen=True)
class ValidationFinding:
    """One validation finding."""

    code: str
    message: str
    path: str = ""
    concept_id: str = ""
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "concept_id": self.concept_id,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    """Full validation outcome."""

    status: str
    exit_code: int
    corpus_revision: str
    errors: list[ValidationFinding] = field(default_factory=list)
    warnings: list[ValidationFinding] = field(default_factory=list)
    documents: tuple[ConceptDocument, ...] = ()
    graph: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "corpus_revision": self.corpus_revision,
            "errors": [e.as_dict() for e in self.errors],
            "warnings": [w.as_dict() for w in self.warnings],
            "graph": self.graph,
        }

    @property
    def ok_for_sync(self) -> bool:
        return self.exit_code in (0, 1) and not self.errors


def validate_corpus(
    concept_root: Path | str,
    *,
    strict: bool = False,
    candidate_overlays: dict[str, bytes] | None = None,
    use_head_for_unmodified: bool = False,
    project_root: Path | None = None,
    baseline_documents: tuple[ConceptDocument, ...] | None = None,
    ignore_rules: Any | None = None,
) -> ValidationResult:
    """Run the full validation suite against a concept corpus."""
    root = Path(concept_root)
    try:
        content_loader = None
        if use_head_for_unmodified:
            if project_root is None:
                raise RuntimeError(
                    "use_head_for_unmodified requires project_root (R13)."
                )
            from agentkit.backend.concept_catalog.corpus.discovery import (
                head_content_loader,
            )

            content_loader = head_content_loader(project_root, root)
        documents, errors = _discover_collecting_errors(
            root,
            candidate_overlays=candidate_overlays,
            content_loader=content_loader,
            ignore_rules=ignore_rules,
        )
        # R11: Candidate/restructuring path — build baseline from Git HEAD when
        # not injected so E-AUTH-002 is productively reachable.
        if baseline_documents is None and use_head_for_unmodified and project_root is not None:
            baseline_documents = _load_head_baseline(
                root, project_root=project_root
            )
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(
            status="internal_failure",
            exit_code=3,
            corpus_revision="",
            errors=[
                ValidationFinding(code="E-INTERNAL-001", message=str(exc), severity="error")
            ],
        )

    errors = list(errors)
    warnings: list[ValidationFinding] = []
    errors.extend(_check_ids(documents))
    errors.extend(_check_refs(documents))
    errors.extend(_check_authority(documents))
    errors.extend(_check_authority_disappeared(documents, baseline_documents))
    errors.extend(_check_cycles(documents))
    errors.extend(_check_chunk_limits(documents))
    warnings.extend(_check_warnings(documents))
    warnings.extend(_check_content_graph_warnings(documents))
    # R11: W-SCOPE-001 warnings vs FundamentalScopesError/E-INTERNAL-001 errors
    # must be split — errors must block ok_for_sync / concept_sync.
    for finding in _check_scope_owners(documents, concept_root=root):
        if finding.severity == "error":
            errors.append(finding)
        else:
            warnings.append(finding)

    if strict:
        errors.extend(
            [
                ValidationFinding(
                    code=w.code,
                    message=w.message,
                    path=w.path,
                    concept_id=w.concept_id,
                    severity="error",
                )
                for w in warnings
            ]
        )
        warnings = []

    rev = corpus_revision([d.file_hash for d in documents], parser_version=PARSER_VERSION)
    active = [d for d in documents if d.effective_status == "active"]
    if errors:
        status, code = "errors", 2
    elif warnings:
        status, code = "warnings", 1
    else:
        status, code = "valid", 0
    return ValidationResult(
        status=status,
        exit_code=code,
        corpus_revision=rev,
        errors=errors,
        warnings=warnings,
        documents=documents,
        graph={
            "concept_count": len(documents),
            "active_count": len(active),
            "acyclic": not any(e.code.startswith("E-CYCLE") for e in errors),
        },
    )


def _check_ids(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    by_id: dict[str, list[ConceptDocument]] = {}
    for doc in documents:
        by_id.setdefault(doc.concept_id, []).append(doc)
    for cid, docs in by_id.items():
        active_docs = [d for d in docs if d.effective_status == "active"]
        if len(active_docs) > 1:
            findings.append(
                ValidationFinding(
                    code="E-ID-001",
                    message=f"duplicate concept_id {cid!r} in active corpus",
                    concept_id=cid,
                    path=active_docs[0].rel_path,
                )
            )
    for doc in documents:
        stem = Path(doc.rel_path).name
        stem_norm = stem.lower().replace("_", "-")
        if (
            doc.concept_id
            and doc.concept_id.lower() not in stem_norm
            and stem[:1].isdigit()
        ):
            findings.append(
                ValidationFinding(
                    code="E-ID-002",
                    message=(
                        f"concept_id {doc.concept_id!r} does not match "
                        f"filename convention of {stem!r}"
                    ),
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )
    return findings


def _check_refs(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    known_ids = {d.concept_id for d in documents}
    core_ids = {d.concept_id for d in documents if d.frontmatter.doc_kind == "core"}
    for doc in documents:
        fm = doc.frontmatter
        for defer in fm.defers_to:
            if defer.target not in known_ids:
                findings.append(
                    ValidationFinding(
                        code="E-REF-001",
                        message=f"defers_to.target {defer.target!r} does not exist",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )
        if fm.doc_kind == "appendix":
            parent = fm.parent_concept_id or ""
            if parent not in known_ids or parent not in core_ids:
                findings.append(
                    ValidationFinding(
                        code="E-REF-002",
                        message=(
                            f"parent_concept_id {parent!r} missing or not a core document"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )
        for sid in fm.superseded_by:
            if sid not in known_ids:
                findings.append(
                    ValidationFinding(
                        code="E-REF-003",
                        message=f"superseded_by {sid!r} does not exist",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                    )
                )
    return findings


def _check_authority(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    scope_owners: dict[str, list[str]] = {}
    for doc in documents:
        if doc.effective_status != "active":
            continue
        for claim in doc.frontmatter.authority_over:
            scope_owners.setdefault(claim.scope, []).append(doc.concept_id)
    for scope, owners in scope_owners.items():
        uniq = sorted(set(owners))
        if len(uniq) > 1:
            findings.append(
                ValidationFinding(
                    code="E-AUTH-001",
                    message=(
                        f"multiple active concepts claim authority_over {scope!r}: {uniq}"
                    ),
                    concept_id=uniq[0],
                )
            )
    return findings


def _check_cycles(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for cycle in _find_defer_cycles(documents):
        findings.append(
            ValidationFinding(
                code="E-CYCLE-001",
                message=f"cycle in defers_to graph: {' -> '.join(cycle)}",
                concept_id=cycle[0] if cycle else "",
            )
        )
    for cycle in _find_supersede_cycles(documents):
        findings.append(
            ValidationFinding(
                code="E-CYCLE-002",
                message=f"cycle in superseded_by chain: {' -> '.join(cycle)}",
                concept_id=cycle[0] if cycle else "",
            )
        )
    return findings


def _check_chunk_limits(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    profile = get_profile(IngestProfileId.FK13_CONCEPT)
    for doc in documents:
        _, overflows = chunk_markdown(doc.body, profile=profile, title=doc.frontmatter.title)
        for finding in overflows:
            findings.append(
                ValidationFinding(
                    code="E-CHUNK-001",
                    message=(
                        f"section {finding.section_heading!r} has "
                        f"{finding.token_count} tokens > max {finding.max_tokens}"
                    ),
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                )
            )
    return findings


def _check_warnings(documents: tuple[ConceptDocument, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    by_id: dict[str, list[ConceptDocument]] = {}
    for doc in documents:
        by_id.setdefault(doc.concept_id, []).append(doc)
    for doc in documents:
        for defer in doc.frontmatter.defers_to:
            targets = by_id.get(defer.target, [])
            if not targets:
                continue
            scopes = {a.scope for a in targets[0].frontmatter.authority_over}
            if defer.scope and defer.scope not in scopes:
                findings.append(
                    ValidationFinding(
                        code="W-BIDIR-001",
                        message=(
                            f"{doc.concept_id} defers_to {defer.target} for "
                            f"{defer.scope!r} but target has no matching authority_over"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                        severity="warning",
                    )
                )
        h1 = _first_h1(doc.body)
        if h1 and h1.strip() != doc.frontmatter.title.strip():
            findings.append(
                ValidationFinding(
                    code="W-CONTENT-001",
                    message=f"H1 {h1!r} differs from frontmatter title",
                    concept_id=doc.concept_id,
                    path=doc.rel_path,
                    severity="warning",
                )
            )
        if doc.effective_status == "active" and doc.frontmatter.doc_kind == "core":
            has_out = bool(doc.frontmatter.defers_to) or bool(doc.frontmatter.authority_over)
            has_in = any(
                d.concept_id != doc.concept_id
                and (
                    any(x.target == doc.concept_id for x in d.frontmatter.defers_to)
                    or d.frontmatter.parent_concept_id == doc.concept_id
                )
                for d in documents
            )
            if not has_out and not has_in:
                findings.append(
                    ValidationFinding(
                        code="W-ORPHAN-001",
                        message=f"active concept {doc.concept_id} has no relationships",
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                        severity="warning",
                    )
                )
    return findings


def _discover_collecting_errors(
    root: Path,
    *,
    candidate_overlays: dict[str, bytes] | None,
    content_loader: Any | None = None,
    ignore_rules: Any | None = None,
) -> tuple[tuple[ConceptDocument, ...], list[ValidationFinding]]:
    errors: list[ValidationFinding] = []
    try:
        result = discover_concept_files(
            root,
            strict=True,
            candidate_overlays=candidate_overlays,
            content_loader=content_loader,
            ignore_rules=ignore_rules,
        )
        return result.documents, errors
    except ConceptParseError as exc:
        return _soft_discover(
            root,
            candidate_overlays=candidate_overlays,
            seed_error=exc,
            content_loader=content_loader,
            ignore_rules=ignore_rules,
        )
    except ConceptDomainError as exc:
        errors.append(
            ValidationFinding(code="E-SCHEMA-001", message=str(exc), severity="error")
        )
        return (), errors


def _check_authority_disappeared(
    documents: tuple[ConceptDocument, ...],
    baseline: tuple[ConceptDocument, ...] | None,
) -> list[ValidationFinding]:
    """E-AUTH-002: authority_over scope disappears without successor."""
    if baseline is None:
        return []
    findings: list[ValidationFinding] = []
    old_scopes: set[str] = set()
    for doc in baseline:
        if doc.effective_status != "active":
            continue
        for claim in doc.frontmatter.authority_over:
            old_scopes.add(claim.scope)
    new_scopes: set[str] = set()
    for doc in documents:
        if doc.effective_status != "active":
            continue
        for claim in doc.frontmatter.authority_over:
            new_scopes.add(claim.scope)
    for scope in sorted(old_scopes - new_scopes):
        findings.append(
            ValidationFinding(
                code="E-AUTH-002",
                message=(
                    f"authority_over scope {scope!r} disappeared without a successor"
                ),
                severity="error",
            )
        )
    return findings


def _check_content_graph_warnings(
    documents: tuple[ConceptDocument, ...]
) -> list[ValidationFinding]:
    """W-CONTENT-002/003 content-graph consistency warnings."""
    import re

    findings: list[ValidationFinding] = []
    known = {d.concept_id for d in documents}
    id_re = re.compile(r"\b(?:FK|DK|TK|AF)-\d+[A-Za-z0-9-]*\b")
    for doc in documents:
        body_ids = set(id_re.findall(doc.body))
        fm_ids = (
            {d.target for d in doc.frontmatter.defers_to}
            | set(doc.frontmatter.supersedes)
            | set(doc.frontmatter.superseded_by)
            | ({doc.frontmatter.parent_concept_id} if doc.frontmatter.parent_concept_id else set())
        )
        for cid in sorted(body_ids - fm_ids - {doc.concept_id}):
            if cid in known or cid.startswith(("FK-", "DK-", "TK-", "AF-")):
                findings.append(
                    ValidationFinding(
                        code="W-CONTENT-002",
                        message=(
                            f"body mentions {cid!r} not present in frontmatter graph"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                        severity="warning",
                    )
                )
        for defer in doc.frontmatter.defers_to:
            if defer.target and defer.target not in doc.body:
                findings.append(
                    ValidationFinding(
                        code="W-CONTENT-003",
                        message=(
                            f"frontmatter defers_to {defer.target!r} but body "
                            "does not mention the target"
                        ),
                        concept_id=doc.concept_id,
                        path=doc.rel_path,
                        severity="warning",
                    )
                )
    return findings


class FundamentalScopesError(Exception):
    """Raised when a present fundamental_scopes.yaml is unreadable/malformed (R11)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _load_fundamental_scopes(concept_root: Path) -> frozenset[str] | None:
    """Load fundamental scopes from an explicit corpus meta file only (R11).

    Absence → None (check inert). Presence with UTF-8/YAML/shape errors raises
    :class:`FundamentalScopesError` — never silently treated as absence.
    """
    import yaml
    from yaml.loader import SafeLoader
    from yaml.nodes import MappingNode

    meta = concept_root / "_meta" / "fundamental_scopes.yaml"
    if not meta.is_file():
        return None

    class _StrictLoader(SafeLoader):
        pass

    def _no_dup(
        loader: yaml.Loader, node: MappingNode, deep: bool = False
    ) -> dict[object, object]:
        if not isinstance(node, MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, f"expected mapping, got {node.id}", node.start_mark
            )
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup
    )

    try:
        text = meta.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FundamentalScopesError(
            "E-INTERNAL-001",
            f"fundamental_scopes.yaml unreadable: {exc}",
        ) from exc
    try:
        data = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise FundamentalScopesError(
            "E-INTERNAL-001",
            f"fundamental_scopes.yaml YAML error: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise FundamentalScopesError(
            "E-INTERNAL-001",
            "fundamental_scopes.yaml must be a mapping with scopes: [...] (R11).",
        )
    scopes = data.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise FundamentalScopesError(
            "E-INTERNAL-001",
            "fundamental_scopes.yaml scopes must be a non-empty list (R11).",
        )
    out = {str(s).strip() for s in scopes if isinstance(s, str) and str(s).strip()}
    if not out:
        raise FundamentalScopesError(
            "E-INTERNAL-001",
            "fundamental_scopes.yaml scopes has no non-empty string entries (R11).",
        )
    return frozenset(out)


def _check_scope_owners(
    documents: tuple[ConceptDocument, ...],
    *,
    concept_root: Path,
) -> list[ValidationFinding]:
    """W-SCOPE-001: fundamental scope without active authority owner.

    Only evaluates when the corpus provides an authoritative fundamental-scope
    list. Never invents scopes (R11). Malformed present file → error finding.
    """
    try:
        fundamental = _load_fundamental_scopes(concept_root)
    except FundamentalScopesError as exc:
        return [
            ValidationFinding(
                code=exc.code,
                message=exc.message,
                path="_meta/fundamental_scopes.yaml",
                severity="error",
            )
        ]
    if fundamental is None:
        return []
    owned: set[str] = set()
    for doc in documents:
        if doc.effective_status != "active":
            continue
        for claim in doc.frontmatter.authority_over:
            owned.add(claim.scope)
    findings: list[ValidationFinding] = []
    for scope in sorted(fundamental - owned):
        findings.append(
            ValidationFinding(
                code="W-SCOPE-001",
                message=f"fundamental scope {scope!r} has no active authority owner",
                severity="warning",
            )
        )
    return findings


def _load_head_baseline(
    concept_root: Path, *, project_root: Path
) -> tuple[ConceptDocument, ...]:
    """Discover baseline documents strictly from Git HEAD (R11 E-AUTH-002)."""
    from agentkit.backend.concept_catalog.corpus.discovery import (
        discover_concept_files,
        head_content_loader,
    )

    loader = head_content_loader(project_root, concept_root)
    # Enumerate concept paths known at HEAD via git ls-tree.
    import subprocess

    try:
        rel = concept_root.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return ()
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", rel],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if proc.returncode != 0:
        return ()
    head_md = {
        Path(line.strip()).relative_to(rel).as_posix()
        for line in proc.stdout.splitlines()
        if line.strip().endswith(".md") and line.strip().startswith(rel)
    }
    # Feed HEAD blobs as overlays so discovery does not read working tree.
    overlays: dict[str, bytes] = {}
    for md_rel in sorted(head_md):
        blob = loader(md_rel)
        if blob is not None:
            overlays[md_rel] = blob
    if not overlays:
        return ()
    try:
        result = discover_concept_files(
            concept_root,
            strict=True,
            candidate_overlays=overlays,
            content_loader=lambda _r: None,  # only overlays
        )
    except Exception:  # noqa: BLE001
        return ()
    return result.documents


def _soft_discover(
    root: Path,
    *,
    candidate_overlays: dict[str, bytes] | None,
    seed_error: ConceptParseError,
    content_loader: Any | None = None,
    ignore_rules: Any | None = None,
) -> tuple[tuple[ConceptDocument, ...], list[ValidationFinding]]:
    from agentkit.backend.concept_catalog.corpus.conceptignore import (
        ConceptIgnoreRules,
        is_under_archiv,
        load_conceptignore,
        load_conceptignore_from_bytes,
    )
    from agentkit.backend.concept_catalog.corpus.discovery import (
        DELETED_PREFIX,
        IGNORE_OVERLAY_KEY,
    )
    from agentkit.backend.concept_catalog.corpus.frontmatter import (
        parse_frontmatter_yaml,
        split_frontmatter_bytes,
        validate_concept_frontmatter,
    )
    from agentkit.backend.concept_catalog.corpus.hashing import sha256_bytes

    errors: list[ValidationFinding] = []
    docs: list[ConceptDocument] = []
    overlays_raw = dict(candidate_overlays or {})
    deleted = {
        k[len(DELETED_PREFIX) :]
        for k in overlays_raw
        if k.startswith(DELETED_PREFIX)
    }
    ignore_bytes = overlays_raw.get(IGNORE_OVERLAY_KEY)
    overlays = {
        k.replace("\\", "/"): v
        for k, v in overlays_raw.items()
        if not k.startswith(DELETED_PREFIX) and k != IGNORE_OVERLAY_KEY
    }
    if ignore_rules is not None:
        ignore = ignore_rules
    elif ignore_bytes is not None:
        ignore = load_conceptignore_from_bytes(
            ignore_bytes, path=str(root / ".conceptignore")
        )
    elif root.is_dir():
        ignore = load_conceptignore(root)
    else:
        ignore = ConceptIgnoreRules(patterns=(), _compiled=())
    rels: set[str] = set()
    if root.is_dir():
        for path in root.rglob("*.md"):
            if path.is_file():
                rels.add(path.relative_to(root).as_posix())
    rels.update(overlays)
    rels -= deleted
    for rel in sorted(rels):
        if ignore.matches(rel):
            continue
        try:
            if rel in overlays:
                data = overlays[rel]
            elif content_loader is not None:
                data = content_loader(rel)
                if data is None:
                    continue
            else:
                data = (root / rel).read_bytes()
            yaml_b, body_b = split_frontmatter_bytes(data, path=rel)
            raw = parse_frontmatter_yaml(yaml_b, path=rel)
            fm = validate_concept_frontmatter(raw, path=rel)
            docs.append(
                ConceptDocument(
                    path=root / rel,
                    rel_path=rel,
                    file_hash=sha256_bytes(data),
                    frontmatter=fm,
                    body=body_b.decode("utf-8"),
                    is_archived_path=is_under_archiv(rel),
                )
            )
        except ConceptParseError as pe:
            errors.append(
                ValidationFinding(
                    code=pe.code, message=str(pe), path=rel, severity="error"
                )
            )
        except (OSError, UnicodeError) as oe:
            errors.append(
                ValidationFinding(
                    code="E-SCHEMA-001", message=str(oe), path=rel, severity="error"
                )
            )
    if not errors:
        errors.append(
            ValidationFinding(
                code=seed_error.code,
                message=str(seed_error),
                path=seed_error.path or "",
                severity="error",
            )
        )
    return tuple(docs), errors


def _first_h1(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# ") and not line.startswith("##"):
            return line[2:].strip()
    return None


def _find_defer_cycles(documents: tuple[ConceptDocument, ...]) -> list[list[str]]:
    edges: dict[tuple[str, str], list[str]] = {}
    for doc in documents:
        for defer in doc.frontmatter.defers_to:
            edges.setdefault((doc.concept_id, defer.scope or ""), []).append(defer.target)
    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def dfs(
        node: str,
        scope: str,
        stack: list[str],
        visiting: set[str],
    ) -> None:
        if node in visiting:
            if node in stack:
                idx = stack.index(node)
                cycle = stack[idx:] + [node]
                key = tuple(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(cycle)
            return
        visiting.add(node)
        stack.append(node)
        for nxt in edges.get((node, scope), []):
            dfs(nxt, scope, stack, visiting)
        stack.pop()
        visiting.discard(node)

    for (src, scope), _targets in edges.items():
        dfs(src, scope, [], set())
    return cycles


def _find_supersede_cycles(documents: tuple[ConceptDocument, ...]) -> list[list[str]]:
    edges: dict[str, list[str]] = {}
    for doc in documents:
        for sid in doc.frontmatter.superseded_by:
            edges.setdefault(doc.concept_id, []).append(sid)
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def dfs(node: str, stack: list[str], visiting: set[str]) -> None:
        if node in visiting:
            if node in stack:
                idx = stack.index(node)
                cycle = stack[idx:] + [node]
                key = tuple(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            return
        visiting.add(node)
        stack.append(node)
        for nxt in edges.get(node, []):
            dfs(nxt, stack, visiting)
        stack.pop()
        visiting.discard(node)

    for cid in edges:
        dfs(cid, [], set())
    return cycles


__all__ = [
    "ValidationFinding",
    "ValidationResult",
    "validate_corpus",
]
