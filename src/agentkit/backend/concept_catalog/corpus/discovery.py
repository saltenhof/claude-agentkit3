"""Concept file discovery SSOT (FK-13 §13.9.13, R02/R13).

Parse failures are hard in all profiles. Inventory mode only changes which
doc_kind values are accepted after a successful strict YAML parse.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentkit.backend.concept_catalog.corpus.conceptignore import (
    ConceptIgnoreRules,
    is_under_archiv,
    load_conceptignore,
    load_conceptignore_from_bytes,
)
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError
from agentkit.backend.concept_catalog.corpus.frontmatter import (
    ConceptFrontmatter,
    parse_frontmatter_yaml,
    split_frontmatter_bytes,
    validate_concept_frontmatter,
)
from agentkit.backend.concept_catalog.corpus.hashing import sha256_bytes

ContentLoader = Callable[[str], bytes | None]
DELETED_PREFIX = "__deleted__:"
IGNORE_OVERLAY_KEY = "__conceptignore__"


@dataclass(frozen=True)
class ConceptDocument:
    path: Path
    rel_path: str
    file_hash: str
    frontmatter: ConceptFrontmatter
    body: str
    is_archived_path: bool

    @property
    def concept_id(self) -> str:
        return self.frontmatter.concept_id

    @property
    def effective_status(self) -> str:
        if self.is_archived_path:
            return "archived"
        return self.frontmatter.status


@dataclass(frozen=True)
class DiscoveryResult:
    concept_root: Path
    documents: tuple[ConceptDocument, ...]
    excluded: tuple[str, ...]


def discover_concept_files(  # noqa: C901
    concept_root: Path | str,
    *,
    strict: bool = True,
    candidate_overlays: dict[str, bytes] | None = None,
    content_loader: ContentLoader | None = None,
    frontmatter_mode: str = "fk13",
    ignore_rules: ConceptIgnoreRules | None = None,
) -> DiscoveryResult:
    """Discover concept markdown files under ``concept_root``.

    ``strict`` only controls whether I/O errors abort; YAML/UTF-8/frontmatter
    parse errors always raise (R02). ``frontmatter_mode="inventory"`` allows
    additional doc_kind values after successful parse — never repairs.
    """
    root = Path(concept_root)
    if not root.is_dir() and content_loader is None:
        raise FileNotFoundError(f"concept root does not exist: {root}")

    overlays = dict(candidate_overlays or {})
    deleted: set[str] = set()
    clean_overlays: dict[str, bytes] = {}
    ignore_bytes: bytes | None = None
    for key, value in overlays.items():
        if key.startswith(DELETED_PREFIX):
            deleted.add(key[len(DELETED_PREFIX) :])
        elif key == IGNORE_OVERLAY_KEY:
            ignore_bytes = value
        else:
            clean_overlays[key.replace("\\", "/")] = value

    if ignore_rules is not None:
        ignore = ignore_rules
    elif ignore_bytes is not None:
        ignore = load_conceptignore_from_bytes(ignore_bytes, path=str(root / ".conceptignore"))
    elif root.is_dir():
        ignore = load_conceptignore(root)
    else:
        ignore = ConceptIgnoreRules(patterns=(), _compiled=())

    rel_paths: set[str] = set()
    if root.is_dir():
        for path in sorted(root.rglob("*.md")):
            if path.is_file():
                rel_paths.add(path.relative_to(root).as_posix())
    rel_paths.update(clean_overlays)
    rel_paths -= deleted

    documents: list[ConceptDocument] = []
    excluded: list[str] = []
    for rel in sorted(rel_paths):
        if ignore.matches(rel):
            excluded.append(rel)
            continue
        if rel in clean_overlays:
            data = clean_overlays[rel]
            path = root / rel
        elif content_loader is not None:
            loaded = content_loader(rel)
            if loaded is None:
                # Missing from HEAD is not a parse repair — file not in candidate.
                continue
            data = loaded
            path = root / rel
        else:
            path = root / rel
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise ConceptParseError(
                    "E-SCHEMA-001",
                    f"cannot read file: {exc}",
                    path=rel,
                ) from exc
        # Parse is ALWAYS hard (R02) — no raw={} / body-as-yaml fallback.
        yaml_bytes, body_bytes = split_frontmatter_bytes(data, path=rel)
        raw = parse_frontmatter_yaml(yaml_bytes, path=rel)
        fm = validate_concept_frontmatter(raw, path=rel, mode=frontmatter_mode)
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConceptParseError(
                "E-SCHEMA-001",
                f"body is not valid UTF-8: {exc}",
                path=rel,
            ) from exc
        documents.append(
            ConceptDocument(
                path=path,
                rel_path=rel,
                file_hash=sha256_bytes(data),
                frontmatter=fm,
                body=body,
                is_archived_path=is_under_archiv(rel),
            )
        )
    return DiscoveryResult(
        concept_root=root.resolve() if root.exists() else root,
        documents=tuple(documents),
        excluded=tuple(excluded),
    )


def head_content_loader(project_root: Path, concepts_dir: Path) -> ContentLoader:
    root = concepts_dir.resolve()
    proj = project_root.resolve()

    def _load(rel: str) -> bytes | None:
        abs_path = (root / rel).resolve()
        try:
            repo_rel = abs_path.relative_to(proj).as_posix()
        except ValueError:
            return None
        proc = subprocess.run(
            ["git", "show", f"HEAD:{repo_rel}"],
            check=False,
            capture_output=True,
            cwd=str(proj),
        )
        if proc.returncode != 0:
            return None
        return proc.stdout

    return _load


__all__ = [
    "DELETED_PREFIX",
    "IGNORE_OVERLAY_KEY",
    "ConceptDocument",
    "DiscoveryResult",
    "discover_concept_files",
    "head_content_loader",
]
