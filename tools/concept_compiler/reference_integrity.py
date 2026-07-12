"""Deterministic reference-integrity checks for the concept corpus.

The scanner ignores YAML frontmatter, fenced and indented code, and references
covered by explicit ``REF-INTEGRITY`` directives. ``IGNORE-LINE`` ignores the
next physical line and requires a reason; ``IGNORE-BEGIN``/``IGNORE-END``
delimit an ignored region and the begin directive requires a reason.

``defers_to`` accepts scalar document-level edges and scope-qualified mapping
edges. A strongly connected component within one scope is an error.
Document-level components are reports only when their exact membership has a
justified baseline entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from .drift import PROSE_ANCHOR_RE
from .loader import try_load_frontmatter

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from .compiler import CompiledFormalSpec

DOC_ID_RE = re.compile(r"(?<![A-Z0-9-])(?:FK-\d+|DK-\d+|META-[A-Z0-9]+(?:-[A-Z0-9]+)*)(?![A-Za-z0-9-])")
ANCHOR_RE = re.compile(r"(?P<doc>FK-\d+)\s+§(?P<section>\d+(?:\.\d+)+(?:\.x)?)")
FORMAL_ITEM_RE = re.compile(r"(?<![A-Za-z0-9_.-])formal\.[a-z0-9_-]+(?:\.[a-z0-9_-]+)+(?![A-Za-z0-9_.-])")
HEADING_RE = re.compile(r"^#{1,6}\s+(?:§\s*)?(?P<section>\d+(?:\.\d+)+)\b")
BACKTICK_RE = re.compile(r"`([^`\r\n]+)`")
IGNORE_LINE_RE = re.compile(r"^\s*<!--\s*REF-INTEGRITY:IGNORE-LINE\s+(.+?)\s*-->\s*$")
IGNORE_BEGIN_RE = re.compile(r"^\s*<!--\s*REF-INTEGRITY:IGNORE-BEGIN\s+(.+?)\s*-->\s*$")
IGNORE_END_RE = re.compile(r"^\s*<!--\s*REF-INTEGRITY:IGNORE-END\s*-->\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
@dataclass(frozen=True, order=True)
class ReferenceFinding:
    """One deterministic reference-integrity finding."""

    path: str
    line: int
    code: str
    reference: str
    message: str
    severity: str = "ERROR"


@dataclass(frozen=True)
class DefersEdge:
    """One document-level or scope-qualified frontmatter deferral edge."""

    source: str
    target: str
    scope: str | None
    reason: str
    path: str


@dataclass(frozen=True)
class ReferenceIntegrityResult:
    """Stable findings and informational reports produced by an audit."""

    findings: tuple[ReferenceFinding, ...]
    reports: tuple[ReferenceFinding, ...]

    @property
    def ok(self) -> bool:
        """Return whether the audit has no blocking findings."""
        return not self.findings


@dataclass(frozen=True)
class _Baseline:
    unresolved: frozenset[tuple[str, str, int, str]]
    document_cycles: frozenset[tuple[str, ...]]


def audit_reference_integrity(
    repo_root: Path,
    concept_root: Path,
    compiled: CompiledFormalSpec,
    baseline_path: Path,
) -> ReferenceIntegrityResult:
    """Audit all concept references and scope-qualified delegation cycles."""
    paths = tuple(sorted(concept_root.rglob("*.md")))
    tracked_paths, tracked_top_level, tracked_findings = _tracked_repo_paths(repo_root)
    documents, headings, edges, load_findings = _load_documents(repo_root, paths)
    baseline, baseline_findings = _load_baseline(repo_root, baseline_path)
    raw_findings: list[ReferenceFinding] = [*tracked_findings, *load_findings, *baseline_findings]
    for path in paths:
        raw_findings.extend(
            _scan_document(
                repo_root,
                path,
                documents,
                headings,
                compiled.declared_ids,
                frozenset(document.doc_id for document in compiled.documents),
                tracked_paths,
                tracked_top_level,
            )
        )
    raw_findings.extend(_scope_cycle_findings(edges))
    cycle_findings, cycle_reports = _document_cycle_findings(edges, baseline)
    raw_findings.extend(cycle_findings)
    raw_findings.extend(_stale_baseline_findings(raw_findings, edges, baseline, baseline_path, repo_root))
    findings, reports = _apply_unresolved_baseline(raw_findings, baseline)
    reports.extend(cycle_reports)
    return ReferenceIntegrityResult(
        findings=tuple(sorted(findings)),
        reports=tuple(sorted(reports)),
    )


def render_reference_integrity(result: ReferenceIntegrityResult) -> str:
    """Render byte-stable gate output."""
    lines = [
        f"[{item.severity}] {item.code} {item.path}:{item.line} {item.reference} - {item.message}"
        for item in (*result.findings, *result.reports)
    ]
    status = "PASS" if result.ok else "ERROR"
    lines.append(f"[{status}] concept-reference-integrity: {len(result.findings)} error(s), {len(result.reports)} report(s)")
    return "\n".join(lines)


def _load_documents(
    repo_root: Path, paths: tuple[Path, ...]
) -> tuple[dict[str, Path], dict[str, frozenset[str]], tuple[DefersEdge, ...], list[ReferenceFinding]]:
    documents: dict[str, Path] = {}
    headings: dict[str, frozenset[str]] = {}
    edges: list[DefersEdge] = []
    findings: list[ReferenceFinding] = []
    for path in paths:
        frontmatter = try_load_frontmatter(path)
        if frontmatter is None:
            continue
        concept_id = frontmatter.get("concept_id")
        if not isinstance(concept_id, str) or not DOC_ID_RE.fullmatch(concept_id):
            continue
        relative = path.relative_to(repo_root).as_posix()
        if concept_id in documents:
            findings.append(_finding(relative, 1, "DUPLICATE_DOCUMENT_ID", concept_id, "document id is declared more than once"))
            continue
        documents[concept_id] = path
        headings[concept_id] = _extract_headings(path.read_text(encoding="utf-8"))
        loaded_edges, edge_findings = _load_defers_edges(frontmatter, concept_id, relative)
        edges.extend(loaded_edges)
        findings.extend(edge_findings)
    return (
        documents,
        headings,
        tuple(sorted(edges, key=lambda edge: (edge.scope or "", edge.source, edge.target, edge.reason))),
        findings,
    )


def _load_defers_edges(
    frontmatter: dict[str, Any], concept_id: str, relative: str
) -> tuple[tuple[DefersEdge, ...], tuple[ReferenceFinding, ...]]:
    raw_edges = frontmatter.get("defers_to", [])
    if raw_edges is None:
        return (), ()
    if not isinstance(raw_edges, list):
        return (), (_invalid_defers_finding(relative, raw_edges),)
    edges: list[DefersEdge] = []
    findings: list[ReferenceFinding] = []
    for raw_edge in raw_edges:
        if isinstance(raw_edge, str) and raw_edge.strip():
            edges.append(DefersEdge(concept_id, raw_edge.strip(), None, "scalar document-level deferral", relative))
            continue
        if not isinstance(raw_edge, dict):
            findings.append(_invalid_defers_finding(relative, raw_edge))
            continue
        target = raw_edge.get("target")
        scope = raw_edge.get("scope")
        if not isinstance(target, str) or not target.strip() or not isinstance(scope, str) or not scope.strip():
            findings.append(_invalid_defers_finding(relative, raw_edge))
            continue
        raw_reason = raw_edge.get("reason")
        reason = raw_reason.strip() if isinstance(raw_reason, str) and raw_reason.strip() else "reason missing or non-string"
        edges.append(DefersEdge(concept_id, target.strip(), scope.strip(), reason, relative))
    return tuple(edges), tuple(findings)


def _invalid_defers_finding(relative: str, raw_edge: Any) -> ReferenceFinding:
    return _finding(
        relative,
        1,
        "INVALID_DEFERS_TO_EDGE",
        repr(raw_edge),
        "defers_to entry must be a scalar string or a mapping with non-empty string target and scope",
    )


def _scan_document(
    repo_root: Path,
    path: Path,
    documents: dict[str, Path],
    headings: dict[str, frozenset[str]],
    declared_ids: frozenset[str],
    formal_document_ids: frozenset[str],
    tracked_paths: frozenset[str],
    tracked_top_level: frozenset[str],
) -> tuple[ReferenceFinding, ...]:
    relative = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    findings: list[ReferenceFinding] = list(_exclusion_findings(text, relative))
    for line_number, raw_line in _prose_lines(text):
        line = PROSE_ANCHOR_RE.sub("", raw_line)
        anchors = tuple(ANCHOR_RE.finditer(line))
        anchor_spans = tuple(match.span("doc") for match in anchors)
        for match in anchors:
            target, section = match.group("doc"), match.group("section")
            if target not in documents:
                findings.append(
                    _finding(relative, line_number, "UNRESOLVED_DOCUMENT", target, "anchor target document does not exist")
                )
            elif _canonical_section(section) not in headings.get(target, frozenset()):
                findings.append(
                    _finding(
                        relative,
                        line_number,
                        "UNRESOLVED_SECTION",
                        match.group(),
                        f"target heading {section} does not exist in {target}",
                    )
                )
        for match in DOC_ID_RE.finditer(line):
            if any(start <= match.start() < end for start, end in anchor_spans):
                continue
            if match.group() not in documents:
                findings.append(
                    _finding(relative, line_number, "UNRESOLVED_DOCUMENT", match.group(), "target document does not exist")
                )
        for match in FORMAL_ITEM_RE.finditer(line):
            item_id = match.group().removeprefix("formal.")
            if match.group() not in formal_document_ids and item_id not in declared_ids:
                findings.append(
                    _finding(relative, line_number, "UNRESOLVED_FORMAL_ID", match.group(), "formal item id is not declared")
                )
        for match in BACKTICK_RE.finditer(line):
            candidate = _repo_path_candidate(match.group(1), tracked_top_level)
            if candidate is not None and candidate not in tracked_paths:
                findings.append(
                    _finding(relative, line_number, "UNRESOLVED_REPO_PATH", candidate, "repo-relative path does not exist")
                )
    return tuple(findings)


def _prose_lines(text: str) -> tuple[tuple[int, str], ...]:
    lines = text.splitlines()
    frontmatter_end = _frontmatter_end(lines)
    output: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    ignored_region = False
    ignore_next = False
    for index, line in enumerate(lines, start=1):
        if index <= frontmatter_end:
            continue
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker[0]
            elif marker[0] == fence_marker:
                in_fence = False
            continue
        if in_fence or line.startswith(("    ", "\t")):
            continue
        if IGNORE_BEGIN_RE.match(line):
            ignored_region = True
            continue
        if IGNORE_END_RE.match(line):
            ignored_region = False
            continue
        if IGNORE_LINE_RE.match(line):
            ignore_next = True
            continue
        if ignored_region:
            continue
        if ignore_next:
            ignore_next = False
            continue
        output.append((index, line))
    return tuple(output)


def _exclusion_findings(text: str, relative: str) -> tuple[ReferenceFinding, ...]:
    findings: list[ReferenceFinding] = []
    region_start: int | None = None
    fence_start: int | None = None
    fence_marker = ""
    ignore_line_start: int | None = None
    for index, line in enumerate(text.splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_start is None:
                fence_start, fence_marker = index, marker[0]
            elif marker[0] == fence_marker:
                fence_start = None
            continue
        if fence_start is not None or line.startswith(("    ", "\t")):
            continue
        if IGNORE_BEGIN_RE.match(line):
            if region_start is not None:
                findings.append(
                    _finding(
                        relative,
                        index,
                        "INVALID_IGNORE_DIRECTIVE",
                        line.strip(),
                        "ignore regions may not be nested",
                    )
                )
            else:
                region_start = index
            continue
        if IGNORE_END_RE.match(line):
            if region_start is None:
                findings.append(
                    _finding(
                        relative,
                        index,
                        "INVALID_IGNORE_DIRECTIVE",
                        line.strip(),
                        "ignore end has no matching begin",
                    )
                )
            region_start = None
            continue
        if IGNORE_LINE_RE.match(line):
            ignore_line_start = index
            continue
        if "REF-INTEGRITY:" in line:
            findings.append(
                _finding(
                    relative,
                    index,
                    "INVALID_IGNORE_DIRECTIVE",
                    line.strip(),
                    "ignore directive is malformed or lacks a reason",
                )
            )
    line_count = len(text.splitlines())
    if ignore_line_start == line_count:
        findings.append(
            _finding(
                relative,
                ignore_line_start,
                "INVALID_IGNORE_DIRECTIVE",
                "REF-INTEGRITY:IGNORE-LINE",
                "ignore-line directive has no following physical line",
            )
        )
    if region_start is not None:
        findings.append(
            _finding(
                relative,
                region_start,
                "INVALID_IGNORE_DIRECTIVE",
                "REF-INTEGRITY:IGNORE-BEGIN",
                "ignore region has no matching end",
            )
        )
    if fence_start is not None:
        findings.append(
            _finding(
                relative,
                fence_start,
                "INVALID_CODE_FENCE",
                "fenced code block",
                "code fence has no matching close",
            )
        )
    return tuple(findings)


def _frontmatter_end(lines: list[str]) -> int:
    if not lines or lines[0].strip() != "---":
        return 0
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return index
    return 0


def _extract_headings(text: str) -> frozenset[str]:
    return frozenset(
        _canonical_section(match.group("section"))
        for _, line in _prose_lines(text)
        if (match := HEADING_RE.match(line)) is not None
    )


def _canonical_section(section: str) -> str:
    return ".".join(str(int(part)) if part.isdigit() else part for part in section.split("."))


def _repo_path_candidate(token: str, tracked_top_level: frozenset[str]) -> str | None:
    candidate = token.strip().replace("\\", "/")
    candidate = re.sub(r":\d+(?:-\d+)?$", "", candidate)
    if not candidate or any(character.isspace() for character in candidate) or candidate.startswith(("/", "http://", "https://")):
        return None
    if any(character in candidate for character in "*{}<>"):
        return None
    first = candidate.split("/", 1)[0]
    if first not in tracked_top_level:
        return None
    if any(part in {"", ".", ".."} for part in candidate.rstrip("/").split("/")):
        return None
    return candidate.rstrip("/")


def _tracked_repo_paths(
    repo_root: Path,
) -> tuple[frozenset[str], frozenset[str], tuple[ReferenceFinding, ...]]:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        finding = _finding(
            "concept",
            0,
            "TRACKED_PATH_DISCOVERY_FAILED",
            "git ls-files",
            "tracked repository paths could not be discovered",
        )
        return frozenset(), frozenset(), (finding,)
    tracked: set[str] = set()
    top_level: set[str] = set()
    for raw_path in completed.stdout.decode("utf-8").split("\0"):
        if not raw_path:
            continue
        normalized = raw_path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        tracked.add(normalized)
        tracked.update("/".join(parts[:index]) for index in range(1, len(parts)))
        top_level.add(parts[0])
    return frozenset(tracked), frozenset(top_level), ()


def _load_baseline(repo_root: Path, path: Path) -> tuple[_Baseline, list[ReferenceFinding]]:
    if not path.is_file():
        return _Baseline(frozenset(), frozenset()), [
            _finding(path.relative_to(repo_root).as_posix(), 1, "MISSING_BASELINE", str(path), "baseline file does not exist")
        ]
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return _Baseline(frozenset(), frozenset()), [
            _finding(path.relative_to(repo_root).as_posix(), 1, "INVALID_BASELINE", str(path), f"baseline YAML is invalid: {exc}")
        ]
    findings: list[ReferenceFinding] = []
    if not isinstance(raw, dict) or raw.get("version") != 1:
        findings.append(
            _finding(
                path.relative_to(repo_root).as_posix(), 1, "INVALID_BASELINE", str(path), "baseline must be a version 1 mapping"
            )
        )
        return _Baseline(frozenset(), frozenset()), findings
    unresolved = _parse_unresolved_baseline(raw.get("unresolved_references", []), path, repo_root, findings)
    cycles = _parse_cycle_baseline(raw.get("document_cycles", []), path, repo_root, findings)
    return _Baseline(frozenset(unresolved), frozenset(cycles)), findings


def _parse_unresolved_baseline(
    raw: Any, path: Path, repo_root: Path, findings: list[ReferenceFinding]
) -> set[tuple[str, str, int, str]]:
    parsed: set[tuple[str, str, int, str]] = set()
    if not isinstance(raw, list):
        findings.append(
            _finding(
                path.relative_to(repo_root).as_posix(),
                1,
                "INVALID_BASELINE",
                "unresolved_references",
                "baseline field must be a list",
            )
        )
        return parsed
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            findings.append(
                _finding(
                    path.relative_to(repo_root).as_posix(),
                    1,
                    "UNJUSTIFIED_BASELINE",
                    "unresolved_references",
                    "every baseline entry requires a non-empty reason",
                )
            )
            continue
        values = (item.get("code"), item.get("path"), item.get("line"), item.get("reference"))
        if not (
            isinstance(values[0], str)
            and isinstance(values[1], str)
            and isinstance(values[2], int)
            and isinstance(values[3], str)
        ):
            findings.append(
                _finding(
                    path.relative_to(repo_root).as_posix(),
                    1,
                    "INVALID_BASELINE",
                    "unresolved_references",
                    "entry requires code, path, integer line, reference, and reason",
                )
            )
            continue
        parsed.add((values[0], values[1], values[2], values[3]))
    return parsed


def _parse_cycle_baseline(raw: Any, path: Path, repo_root: Path, findings: list[ReferenceFinding]) -> set[tuple[str, ...]]:
    parsed: set[tuple[str, ...]] = set()
    if not isinstance(raw, list):
        findings.append(
            _finding(
                path.relative_to(repo_root).as_posix(), 1, "INVALID_BASELINE", "document_cycles", "baseline field must be a list"
            )
        )
        return parsed
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            findings.append(
                _finding(
                    path.relative_to(repo_root).as_posix(),
                    1,
                    "UNJUSTIFIED_BASELINE",
                    "document_cycles",
                    "every document cycle requires a non-empty reason",
                )
            )
            continue
        documents = item.get("documents")
        if not isinstance(documents, list) or len(documents) < 2 or not all(isinstance(document, str) for document in documents):
            findings.append(
                _finding(
                    path.relative_to(repo_root).as_posix(),
                    1,
                    "INVALID_BASELINE",
                    "document_cycles",
                    "cycle documents must be a list of at least two ids",
                )
            )
            continue
        canonical = tuple(sorted(documents))
        if list(documents) != list(canonical) or len(set(documents)) != len(documents):
            findings.append(
                _finding(
                    path.relative_to(repo_root).as_posix(),
                    1,
                    "INVALID_BASELINE",
                    "document_cycles",
                    "cycle documents must be unique and sorted",
                )
            )
            continue
        parsed.add(canonical)
    return parsed


def _scope_cycle_findings(edges: tuple[DefersEdge, ...]) -> tuple[ReferenceFinding, ...]:
    findings: list[ReferenceFinding] = []
    for scope in sorted({edge.scope for edge in edges if edge.scope is not None}):
        scoped = tuple(edge for edge in edges if edge.scope == scope)
        for component in _strong_components(scoped):
            details = "; ".join(
                f"{edge.source}->{edge.target}: {edge.reason}"
                for edge in scoped
                if edge.source in component and edge.target in component
            )
            findings.append(
                _finding("concept", 0, "SCOPE_DEFERS_TO_CYCLE", scope, f"scope cycle among {', '.join(component)}; {details}")
            )
    return tuple(findings)


def _document_cycle_findings(
    edges: tuple[DefersEdge, ...], baseline: _Baseline
) -> tuple[list[ReferenceFinding], list[ReferenceFinding]]:
    findings: list[ReferenceFinding] = []
    reports: list[ReferenceFinding] = []
    for component in _strong_components(edges):
        item = _finding(
            "concept", 0, "DOCUMENT_DEFERS_TO_CYCLE", ",".join(component), "document-level cycle is scope-disjoint", "REPORT"
        )
        if component in baseline.document_cycles:
            reports.append(item)
        else:
            findings.append(
                _finding(
                    item.path,
                    item.line,
                    "UNBASELINED_DOCUMENT_CYCLE",
                    item.reference,
                    "document-level cycle lacks a justified baseline",
                )
            )
    return findings, reports


def _strong_components(edges: Iterable[DefersEdge]) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
        adjacency.setdefault(edge.target, [])
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency[node]):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        canonical = tuple(sorted(component))
        if len(canonical) > 1 or node in adjacency[node]:
            components.append(canonical)

    for node in sorted(adjacency):
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def _apply_unresolved_baseline(
    findings: list[ReferenceFinding], baseline: _Baseline
) -> tuple[list[ReferenceFinding], list[ReferenceFinding]]:
    errors: list[ReferenceFinding] = []
    reports: list[ReferenceFinding] = []
    for finding in findings:
        key = (finding.code, finding.path, finding.line, finding.reference)
        if key in baseline.unresolved:
            reports.append(
                ReferenceFinding(finding.path, finding.line, finding.code, finding.reference, finding.message, "REPORT")
            )
        else:
            errors.append(finding)
    return errors, reports


def _stale_baseline_findings(
    findings: list[ReferenceFinding],
    edges: tuple[DefersEdge, ...],
    baseline: _Baseline,
    baseline_path: Path,
    repo_root: Path,
) -> tuple[ReferenceFinding, ...]:
    active = {(item.code, item.path, item.line, item.reference) for item in findings}
    stale_unresolved = sorted(baseline.unresolved - active)
    active_cycles = frozenset(_strong_components(edges))
    stale_cycles = sorted(baseline.document_cycles - active_cycles)
    relative = baseline_path.relative_to(repo_root).as_posix()
    output = [
        _finding(
            relative,
            1,
            "STALE_BASELINE",
            "|".join(map(str, item)),
            "unresolved-reference baseline entry no longer matches a finding",
        )
        for item in stale_unresolved
    ]
    output.extend(
        _finding(
            relative,
            1,
            "STALE_BASELINE",
            ",".join(component),
            "document-cycle baseline entry no longer matches a cycle",
        )
        for component in stale_cycles
    )
    return tuple(output)


def _finding(path: str, line: int, code: str, reference: str, message: str, severity: str = "ERROR") -> ReferenceFinding:
    return ReferenceFinding(path=path, line=line, code=code, reference=reference, message=message, severity=severity)
