"""Deterministic reference-integrity check for the concept corpus (FK-78).

Checks per FK-78 section 78.14:

* concept-id mentions in document bodies (grammars from the governance
  configuration) must resolve to existing documents,
* backticked repo-relative paths must be versionable repository content
  (tracked by git or untracked but unignored) AND present in the working
  tree; the two conditions are conjunctive and the finding names the one
  that failed. Git is a prerequisite: when it cannot be consulted the
  check declares itself INCOMPLETE rather than measuring something else,
* ``formal.`` object ids must exist in the formal corpus,
* ``<path>#<anchor>`` references must resolve to an anchor in the target
  document,
* document-level ``defers_to`` cycles must carry a justified baseline entry.

Baseline support: an optional ``reference-integrity-baseline.yaml`` below
the meta root turns exactly matching findings into non-blocking reports;
stale baseline entries are ERROR findings.

Line and region exclusions use ``REF-INTEGRITY:IGNORE-LINE <reason>`` and
``REF-INTEGRITY:IGNORE-BEGIN <reason>`` / ``REF-INTEGRITY:IGNORE-END``
comments; a directive without a reason is an ERROR.
"""

from __future__ import annotations

import os.path
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .docmodel import ConceptDocument, anchor_slugs, body_lines, scan_documents, split_frontmatter
from .findings import CheckResult, Finding
from .smy import SmyError, parse_smy

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "references"
BASELINE_FILENAME = "reference-integrity-baseline.yaml"

_BACKTICK_RE = re.compile(r"`([^`\r\n]+)`")
_LINE_ANCHOR_RE = re.compile(r"^L\d+(?:-L\d+)?$")


@dataclass(frozen=True, order=True)
class _RefFinding:
    path: str
    line: int
    code: str
    reference: str
    message: str


@dataclass(frozen=True)
class _Baseline:
    unresolved: frozenset[tuple[str, str, int, str]]
    document_cycles: frozenset[tuple[str, ...]]


class _RepoPathDiscoveryError(Exception):
    """Raised when git cannot enumerate the versionable repository content."""


@dataclass(frozen=True)
class _ScanContext:
    known_ids: frozenset[str]
    formal_ids: frozenset[str]
    mention_patterns: tuple[re.Pattern[str], ...]
    formal_pattern: re.Pattern[str]
    top_level: frozenset[str]
    known_paths: frozenset[str]

    def repo_path_message(self, project_root: Path, candidate: str) -> str | None:
        """Return why ``candidate`` does not resolve, or ``None`` when it does.

        ``known_paths`` is the case-sensitive, platform-independent universe
        of versionable repository content; the working-tree probe decides
        whether a member of that universe is actually present right now.

        The probe is ``os.path.lexists`` and not ``Path.exists``: a symlink
        is itself repository content, and ``exists`` follows it, so a link
        whose target is missing would be reported as "absent from the
        working tree" although the entry is demonstrably there. ``exists``
        also answers ``False`` for a permission or I/O error -- a third
        thing again, and the message would name none of them.
        """
        if candidate not in self.known_paths:
            return "repo-relative path is neither tracked by git nor an unignored working-tree file"
        if not os.path.lexists(project_root / candidate):
            return "repo-relative path is known to git but absent from the working tree"
        return None


@dataclass
class _ProseState:
    in_region: bool = False
    region_start: int = 0
    skip_next: bool = False


def run_reference_check(project_root: Path, config: GovernanceConfig) -> CheckResult:
    """Run reference integrity across all configured concept roots."""
    result = CheckResult(check_id=CHECK_ID)
    try:
        known_paths, top_level = _known_repo_paths(project_root)
    except _RepoPathDiscoveryError as exc:
        result.complete = False
        result.incomplete_reason = f"versionable repository paths could not be discovered: {exc}"
        return result
    documents = scan_documents(project_root, config.concept_roots)
    known_ids = frozenset(doc.concept_id for doc in documents if doc.concept_id)
    formal_ids = _collect_formal_object_ids(documents, config)
    scan_context = _ScanContext(
        known_ids=known_ids,
        formal_ids=formal_ids,
        mention_patterns=_mention_patterns(config),
        formal_pattern=_debounded(config.id_grammars["formal_object"].pattern),
        top_level=top_level,
        known_paths=known_paths,
    )
    raw: list[_RefFinding] = []
    for doc in documents:
        raw.extend(_scan_document(project_root, doc, scan_context))
    edges = _collect_defers_edges(documents)
    baseline, baseline_findings = _load_baseline(project_root, config)
    raw.extend(baseline_findings)
    cycle_findings, cycle_reports, active_cycles = _document_cycle_findings(edges, baseline)
    raw.extend(cycle_findings)
    raw.extend(_stale_baseline_findings(raw, active_cycles, baseline, config))
    errors, reports = _apply_baseline(raw, baseline)
    result.findings.extend(_to_finding(item) for item in sorted(errors))
    result.reports.extend(
        f"[REPORT] {item.code} {item.path}:L{item.line} {item.reference} - {item.message}"
        for item in sorted([*reports, *cycle_reports])
    )
    result.summary = f"{len(documents)} documents scanned, {len(result.reports)} baselined report(s)"
    return result


def _to_finding(item: _RefFinding) -> Finding:
    return Finding(
        check_id=item.code,
        severity="ERROR",
        path=item.path,
        locator=f"L{item.line}",
        message=f"{item.reference} - {item.message}",
    )


def _mention_patterns(config: GovernanceConfig) -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for grammar_key in ("domain_doc", "technical_doc"):
        patterns.append(_debounded(config.id_grammars[grammar_key].pattern))
    return tuple(patterns)


def _debounded(pattern: str) -> re.Pattern[str]:
    core = pattern.removeprefix("^").removesuffix("$")
    return re.compile(rf"(?<![A-Za-z0-9_.-])(?:{core})(?![A-Za-z0-9_.-])")


def _collect_formal_object_ids(documents: Sequence[ConceptDocument], config: GovernanceConfig) -> frozenset[str]:
    from .formal_check import extract_spec_zone

    ids: set[str] = set()
    formal_root = config.concept_roots["formal"]
    for doc in documents:
        below_formal_root = doc.rel_path.removeprefix(formal_root).split("/")
        if doc.layer != "formal" or doc.path.name == "README.md" or "00_meta" in below_formal_root:
            continue
        zone = extract_spec_zone(doc.text)
        if zone is None:
            continue
        try:
            spec = parse_smy(zone.payload)
        except SmyError:
            continue
        object_id = spec.get("object")
        if isinstance(object_id, str) and object_id:
            ids.add(object_id)
    return frozenset(ids)


def _prose_lines(doc: ConceptDocument) -> tuple[list[tuple[int, str]], list[_RefFinding]]:
    lines: list[tuple[int, str]] = []
    findings: list[_RefFinding] = []
    state = _ProseState()
    for number, line in body_lines(doc.text):
        included = _process_prose_line(doc.rel_path, number, line, state, findings)
        if included is not None:
            lines.append((number, included))
    if state.in_region:
        _directive_error(
            findings,
            doc.rel_path,
            state.region_start,
            "REF-INTEGRITY:IGNORE-BEGIN",
            "ignore region has no matching end",
        )
    return lines, findings


def _process_prose_line(
    path: str,
    number: int,
    line: str,
    state: _ProseState,
    findings: list[_RefFinding],
) -> str | None:
    directive = _ignore_directive_kind(line)
    if directive == "begin":
        if state.in_region:
            _directive_error(findings, path, number, line.strip(), "ignore regions may not be nested")
        state.in_region = True
        state.region_start = number
        return None
    if directive == "end":
        if not state.in_region:
            _directive_error(findings, path, number, line.strip(), "ignore end has no matching begin")
        state.in_region = False
        return None
    if directive == "line":
        state.skip_next = True
        return None
    if "REF-INTEGRITY:" in line and not state.in_region:
        _directive_error(findings, path, number, line.strip(), "ignore directive is malformed or lacks a reason")
        return None
    if state.in_region:
        return None
    if state.skip_next:
        state.skip_next = False
        return None
    return None if line.startswith(("    ", "\t")) else line


def _ignore_directive_kind(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("<!--") or not stripped.endswith("-->"):
        return None
    content = stripped[4:-3].strip()
    if content == "REF-INTEGRITY:IGNORE-END":
        return "end"
    for marker, kind in (
        ("REF-INTEGRITY:IGNORE-BEGIN", "begin"),
        ("REF-INTEGRITY:IGNORE-LINE", "line"),
    ):
        if content.startswith(marker):
            reason = content[len(marker) :].strip()
            return kind if reason else None
    return None


def _directive_error(
    findings: list[_RefFinding],
    path: str,
    number: int,
    reference: str,
    message: str,
) -> None:
    findings.append(_RefFinding(path, number, "INVALID_IGNORE_DIRECTIVE", reference, message))


def _scan_document(project_root: Path, doc: ConceptDocument, context: _ScanContext) -> list[_RefFinding]:
    lines, findings = _prose_lines(doc)
    for number, line in lines:
        for pattern in context.mention_patterns:
            for match in pattern.finditer(line):
                if match.group() not in context.known_ids:
                    findings.append(
                        _RefFinding(doc.rel_path, number, "UNRESOLVED_DOCUMENT", match.group(), "target document does not exist")
                    )
        for match in context.formal_pattern.finditer(line):
            if match.group() not in context.formal_ids:
                findings.append(
                    _RefFinding(doc.rel_path, number, "UNRESOLVED_FORMAL_ID", match.group(), "formal object id is not declared")
                )
        findings.extend(_scan_backticks(project_root, doc, number, line, context))
    return findings


def _scan_backticks(project_root: Path, doc: ConceptDocument, number: int, line: str, context: _ScanContext) -> list[_RefFinding]:
    findings: list[_RefFinding] = []
    for match in _BACKTICK_RE.finditer(line):
        token = match.group(1)
        path_part, _, anchor = token.partition("#")
        candidate = _repo_path_candidate(path_part, context)
        if candidate is None:
            continue
        unresolved = context.repo_path_message(project_root, candidate)
        if unresolved is not None:
            findings.append(_RefFinding(doc.rel_path, number, "UNRESOLVED_REPO_PATH", candidate, unresolved))
            continue
        target = project_root / candidate
        if anchor and not _LINE_ANCHOR_RE.match(anchor) and candidate.endswith(".md") and target.is_file():
            slugs = anchor_slugs(target.read_text(encoding="utf-8"))
            if anchor not in slugs:
                findings.append(
                    _RefFinding(
                        doc.rel_path,
                        number,
                        "UNRESOLVED_ANCHOR",
                        f"{candidate}#{anchor}",
                        "anchor does not resolve in the target document",
                    )
                )
    return findings


def _repo_path_candidate(token: str, context: _ScanContext) -> str | None:
    candidate = token.strip().replace("\\", "/")
    candidate = re.sub(r":\d+(?:-\d+)?$", "", candidate)
    if not candidate or "/" not in candidate:
        return None
    if any(char.isspace() for char in candidate) or candidate.startswith("/") or _is_web_url(candidate):
        return None
    if any(char in candidate for char in "*{}<>`"):
        return None
    first = candidate.split("/", 1)[0]
    if first.casefold() not in context.top_level:
        return None
    forbidden_parts = ("", ".", "..")
    if any(part in forbidden_parts for part in candidate.rstrip("/").split("/")):
        return None
    return candidate.rstrip("/")


def _is_web_url(value: str) -> bool:
    scheme, separator, _remainder = value.partition("://")
    return bool(separator) and scheme.casefold() in {"http", "https"}


def _known_repo_paths(project_root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Collect every repo-relative path that git regards as versionable content.

    The universe is the union of the index (``git ls-files``) and the
    untracked but unignored working-tree files (``git ls-files --others
    --exclude-standard``). Two properties follow from that union and neither
    is obtainable from the working tree alone:

    * ``.gitignore`` stays the filter that keeps generated artefacts out of
      the resolvable universe, so a reference to build output is never a
      valid repository path.
    * Membership is case-sensitive and free of platform path quirks, so a
      case variant or a Windows-collapsing token is rejected on every
      operating system.

    What the union deliberately does *not* decide is presence; that is
    probed separately against the working tree by
    :meth:`_ScanContext.repo_path_message`.

    Raises:
        _RepoPathDiscoveryError: When git could not be consulted. There is
            no filesystem fallback: a fallback would keep the wording of
            the finding while silently changing its meaning, so the same
            message would state two different predicates depending on the
            environment.
    """
    index = _git_ls_files(project_root, ())
    others = _git_ls_files(project_root, ("--others", "--exclude-standard"))
    known: set[str] = set()
    top_names: set[str] = set()
    for raw_path in (*index.split("\0"), *others.split("\0")):
        if not raw_path:
            continue
        normalized = raw_path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        known.add(normalized)
        known.update("/".join(parts[:index_end]) for index_end in range(1, len(parts)))
        top_names.add(parts[0].casefold())
    return frozenset(known), frozenset(top_names)


def _git_ls_files(project_root: Path, options: tuple[str, ...]) -> str:
    import subprocess

    # ``--full-name`` pins the output to repository-root-relative paths, which
    # is the base the backticked references in the corpus are written in.
    argv = ["git", "-C", str(project_root), "ls-files", "--full-name", "-z", *options]
    completed = subprocess.run(argv, check=False, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        command = " ".join(("git", "ls-files", *options))
        raise _RepoPathDiscoveryError(detail or f"{command} exited {completed.returncode}")
    return completed.stdout.decode("utf-8", errors="replace")


def _collect_defers_edges(documents: Sequence[ConceptDocument]) -> dict[str, tuple[str, ...]]:
    edges: dict[str, tuple[str, ...]] = {}
    for doc in documents:
        if not doc.concept_id or doc.frontmatter is None:
            continue
        raw_edges = doc.frontmatter.get("defers_to")
        if not isinstance(raw_edges, list):
            continue
        targets = [target for entry in raw_edges if (target := _deferral_target(entry)) is not None]
        edges[doc.concept_id] = tuple(targets)
    return edges


def _deferral_target(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry.strip() or None
    if not isinstance(entry, dict):
        return None
    target = entry.get("target")
    return target.strip() if isinstance(target, str) and target.strip() else None


def _document_cycle_findings(
    edges: dict[str, tuple[str, ...]], baseline: _Baseline
) -> tuple[list[_RefFinding], list[_RefFinding], frozenset[tuple[str, ...]]]:
    from .frontmatter_check import strong_components

    findings: list[_RefFinding] = []
    reports: list[_RefFinding] = []
    components = strong_components(edges)
    for component in components:
        reference = ",".join(component)
        if component in baseline.document_cycles:
            reports.append(_RefFinding("concept", 0, "DOCUMENT_DEFERS_TO_CYCLE", reference, "document-level cycle is baselined"))
        else:
            findings.append(
                _RefFinding(
                    "concept",
                    0,
                    "UNBASELINED_DOCUMENT_CYCLE",
                    reference,
                    "document-level defers_to cycle lacks a justified baseline entry",
                )
            )
    return findings, reports, frozenset(components)


def _load_baseline(project_root: Path, config: GovernanceConfig) -> tuple[_Baseline, list[_RefFinding]]:
    path = config.meta_path(project_root, BASELINE_FILENAME)
    rel_path = f"{config.concept_roots['meta']}/{BASELINE_FILENAME}"
    empty = _Baseline(frozenset(), frozenset())
    if not path.is_file():
        return empty, []
    text = path.read_text(encoding="utf-8")
    payload, _ = split_frontmatter(text)
    try:
        raw = parse_smy(payload if payload is not None else text)
    except SmyError as exc:
        message = f"baseline is not parseable SMY: {exc.message}"
        return empty, [_RefFinding(rel_path, exc.line, "INVALID_BASELINE", BASELINE_FILENAME, message)]
    if raw.get("version") != 1:
        return empty, [_RefFinding(rel_path, 1, "INVALID_BASELINE", BASELINE_FILENAME, "baseline must declare version: 1")]
    findings: list[_RefFinding] = []
    unresolved = _parse_unresolved(raw.get("unresolved_references"), rel_path, findings)
    cycles = _parse_cycles(raw.get("document_cycles"), rel_path, findings)
    return _Baseline(frozenset(unresolved), frozenset(cycles)), findings


def _parse_unresolved(raw: object, rel_path: str, findings: list[_RefFinding]) -> set[tuple[str, str, int, str]]:
    parsed: set[tuple[str, str, int, str]] = set()
    if raw is None:
        return parsed
    if not isinstance(raw, list):
        findings.append(_RefFinding(rel_path, 1, "INVALID_BASELINE", "unresolved_references", "baseline field must be a list"))
        return parsed
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            message = "every baseline entry requires a non-empty reason"
            findings.append(_RefFinding(rel_path, 1, "UNJUSTIFIED_BASELINE", "unresolved_references", message))
            continue
        code, path, line, reference = (item.get("code"), item.get("path"), item.get("line"), item.get("reference"))
        if not (isinstance(code, str) and isinstance(path, str) and isinstance(line, int) and isinstance(reference, str)):
            message = "entry requires code, path, integer line, reference, and reason"
            findings.append(_RefFinding(rel_path, 1, "INVALID_BASELINE", "unresolved_references", message))
            continue
        parsed.add((code, path, line, reference))
    return parsed


def _parse_cycles(raw: object, rel_path: str, findings: list[_RefFinding]) -> set[tuple[str, ...]]:
    parsed: set[tuple[str, ...]] = set()
    if raw is None:
        return parsed
    if not isinstance(raw, list):
        findings.append(_RefFinding(rel_path, 1, "INVALID_BASELINE", "document_cycles", "baseline field must be a list"))
        return parsed
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("reason"), str) or not item["reason"].strip():
            message = "every document cycle requires a non-empty reason"
            findings.append(_RefFinding(rel_path, 1, "UNJUSTIFIED_BASELINE", "document_cycles", message))
            continue
        documents = item.get("documents")
        if (
            not isinstance(documents, list)
            or len(documents) < 2
            or not all(isinstance(document, str) for document in documents)
            or sorted(documents) != list(documents)
            or len(set(documents)) != len(documents)
        ):
            message = "cycle documents must be a unique, sorted list of at least two ids"
            findings.append(_RefFinding(rel_path, 1, "INVALID_BASELINE", "document_cycles", message))
            continue
        parsed.add(tuple(documents))
    return parsed


def _apply_baseline(raw: Iterable[_RefFinding], baseline: _Baseline) -> tuple[list[_RefFinding], list[_RefFinding]]:
    errors: list[_RefFinding] = []
    reports: list[_RefFinding] = []
    for item in raw:
        if (item.code, item.path, item.line, item.reference) in baseline.unresolved:
            reports.append(item)
        else:
            errors.append(item)
    return errors, reports


def _stale_baseline_findings(
    raw: Sequence[_RefFinding],
    active_cycles: frozenset[tuple[str, ...]],
    baseline: _Baseline,
    config: GovernanceConfig,
) -> list[_RefFinding]:
    rel_path = f"{config.concept_roots['meta']}/{BASELINE_FILENAME}"
    active = {(item.code, item.path, item.line, item.reference) for item in raw}
    findings = [
        _RefFinding(rel_path, 1, "STALE_BASELINE", "|".join(map(str, entry)), "baseline entry no longer matches a finding")
        for entry in sorted(baseline.unresolved - active)
    ]
    findings.extend(
        _RefFinding(rel_path, 1, "STALE_BASELINE", ",".join(component), "document-cycle baseline entry no longer matches a cycle")
        for component in sorted(baseline.document_cycles - active_cycles)
    )
    return findings
