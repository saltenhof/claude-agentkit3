"""Read-only Markdown index for the repository concept corpus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from agentkit.concept_catalog.entities import (
    ConceptBacklinks,
    ConceptLayer,
    ConceptRef,
    ConceptSearchHit,
)
from agentkit.concept_catalog.errors import (
    ConceptCatalogParseError,
    ConceptRefNotFoundError,
)

if TYPE_CHECKING:
    import builtins
    from pathlib import Path


class ConceptIndex:
    """In-memory read index over ``concept/**/*.md`` documents."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._refs: dict[str, ConceptRef] = {}
        self._content: dict[str, str] = {}
        self._search_text: dict[str, str] = {}

    def load(self) -> None:
        """Load all concept documents with parseable frontmatter."""

        refs: dict[str, ConceptRef] = {}
        content: dict[str, str] = {}
        search_text: dict[str, str] = {}

        for path in sorted(self._root.rglob("*.md")):
            parsed = _split_frontmatter(path)
            if parsed is None:
                continue
            frontmatter, body = parsed
            concept_id = _concept_id(frontmatter)
            if concept_id is None:
                continue
            layer = _layer_for_path(path, self._root)
            if layer is None:
                continue
            if concept_id in refs:
                raise ConceptCatalogParseError(
                    f"Duplicate concept reference {concept_id}: {path}",
                    detail={"concept_ref": concept_id, "path": str(path)},
                )
            ref = _concept_ref(path, concept_id, layer, frontmatter)
            refs[concept_id] = ref
            content[concept_id] = body
            search_text[concept_id] = f"{ref.title}\n{body}".lower()

        self._refs = refs
        self._content = content
        self._search_text = search_text

    def get(self, concept_ref: str) -> ConceptRef | None:
        """Resolve a concept reference by id."""

        return self._refs.get(concept_ref)

    def list(
        self,
        *,
        layer: str | None = None,
        status: str | None = None,
        domain: str | None = None,
    ) -> list[ConceptRef]:
        """List concept references with optional metadata filters."""

        refs = list(self._refs.values())
        if layer is not None:
            refs = [ref for ref in refs if ref.layer == layer]
        if status is not None:
            refs = [ref for ref in refs if ref.status == status]
        if domain is not None:
            refs = [ref for ref in refs if ref.domain == domain]
        return sorted(refs, key=lambda ref: (ref.layer, ref.concept_id, str(ref.path)))

    def backlinks(self, concept_ref: str) -> ConceptBacklinks:
        """Return incoming ``defers_to`` and ``formal_refs`` references."""

        self._require_ref(concept_ref)
        incoming_defers_to: list[str] = []
        incoming_formal_refs: list[str] = []
        for ref in self._refs.values():
            if concept_ref in ref.defers_to:
                incoming_defers_to.append(ref.concept_id)
            if concept_ref in ref.formal_refs:
                incoming_formal_refs.append(ref.concept_id)
        return ConceptBacklinks(
            ref=concept_ref,
            incoming_defers_to=sorted(incoming_defers_to),
            incoming_formal_refs=sorted(incoming_formal_refs),
        )

    def search(self, query: str, *, limit: int = 20) -> builtins.list[ConceptSearchHit]:
        """Run a deterministic lowercase substring search over title and body."""

        normalized = query.strip().lower()
        if normalized == "" or limit <= 0:
            return []

        hits: builtins.list[ConceptSearchHit] = []
        for concept_id, haystack in self._search_text.items():
            first_index = haystack.find(normalized)
            if first_index < 0:
                continue
            ref = self._refs[concept_id]
            score = _search_score(normalized, ref, haystack, first_index)
            hits.append(
                ConceptSearchHit(
                    ref=concept_id,
                    title=ref.title,
                    snippet=_snippet(haystack, first_index, len(normalized)),
                    score=score,
                ),
            )

        return sorted(hits, key=lambda hit: (-hit.score, hit.ref, hit.title))[:limit]

    def content(self, concept_ref: str) -> str:
        """Return the Markdown body without YAML frontmatter."""

        self._require_ref(concept_ref)
        return self._content[concept_ref]

    def _require_ref(self, concept_ref: str) -> None:
        if concept_ref not in self._refs:
            raise ConceptRefNotFoundError(
                f"Concept reference not found: {concept_ref}",
                detail={"concept_ref": concept_ref},
            )


def _split_frontmatter(path: Path) -> tuple[dict[str, Any], str] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None

    lines = text.splitlines()
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ConceptCatalogParseError(
            f"Concept frontmatter is not closed: {path}",
            detail={"path": str(path)},
        )

    payload = "\n".join(lines[1:end_index])
    try:
        parsed = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ConceptCatalogParseError(
            f"Invalid concept frontmatter YAML: {path}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ConceptCatalogParseError(
            f"Concept frontmatter must be a mapping: {path}",
            detail={"path": str(path)},
        )
    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return parsed, body


def _concept_id(frontmatter: dict[str, Any]) -> str | None:
    for key in ("concept_id", "id"):
        value = frontmatter.get(key)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    return None


def _concept_ref(
    path: Path,
    concept_id: str,
    layer: ConceptLayer,
    frontmatter: dict[str, Any],
) -> ConceptRef:
    return ConceptRef(
        concept_id=concept_id,
        path=path,
        layer=layer,
        title=_required_string(frontmatter, "title", path),
        status=_required_string(frontmatter, "status", path),
        domain=_optional_string(frontmatter.get("domain")) or _optional_string(frontmatter.get("context")),
        tags=_string_list(frontmatter.get("tags")),
        cross_cutting=bool(frontmatter.get("cross_cutting", False)),
        defers_to=_defers_to_refs(frontmatter.get("defers_to")),
        formal_refs=_string_list(frontmatter.get("formal_refs")),
    )


def _layer_for_path(path: Path, root: Path) -> ConceptLayer | None:
    relative = path.relative_to(root)
    first_part = relative.parts[0] if relative.parts else ""
    if first_part == "domain-design":
        return "domain"
    if first_part == "technical-design":
        return "technical"
    if first_part == "formal-spec":
        return "formal"
    return None


def _required_string(frontmatter: dict[str, Any], key: str, path: Path) -> str:
    value = frontmatter.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise ConceptCatalogParseError(
            f"Concept frontmatter field '{key}' must be a non-empty string: {path}",
            detail={"path": str(path), "field": key},
        )
    return value.strip()


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip() != ""]


def _defers_to_refs(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() != "":
            refs.append(item.strip())
        elif isinstance(item, dict):
            target = item.get("target")
            if isinstance(target, str) and target.strip() != "":
                refs.append(target.strip())
    return refs


def _search_score(query: str, ref: ConceptRef, haystack: str, first_index: int) -> float:
    title = ref.title.lower()
    title_hits = title.count(query)
    body_hits = haystack.count(query) - title_hits
    early_bonus = 1.0 / float(first_index + 1)
    return float((title_hits * 10) + body_hits) + early_bonus


def _snippet(haystack: str, first_index: int, query_length: int) -> str:
    start = max(first_index - 60, 0)
    end = min(first_index + query_length + 120, len(haystack))
    return " ".join(haystack[start:end].split())
