"""MCP tool handlers for the five FK-13 tools (AG3-174 R06-R10/R16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agentkit.backend.concept_catalog.corpus.discovery import discover_concept_files
from agentkit.backend.vectordb.concept_corpus.resolver import ConceptGraphResolver
from agentkit.backend.vectordb.concept_corpus.sync import (
    ConceptSyncBlockedError,
    concept_sync_bounded_window,
)
from agentkit.backend.vectordb.ingest.builders import build_concept_chunks
from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestError
from agentkit.backend.vectordb.mcp.wire_models import parse_tool_args
from agentkit.backend.vectordb.runtime_binding import (
    RuntimeBinding,
    RuntimeBindingError,
    resolve_tool_project_id,
)
from agentkit.backend.vectordb.schema import STORY_COLLECTION
from agentkit.integration_clients.vectordb.errors import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Mapping


class ToolExecutionError(Exception):
    """Typed tool failure with envelope payload."""

    def __init__(self, code: str, message: str, **extra: object) -> None:
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(message)

    def as_envelope(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": False,
            "error_code": self.code,
            "error": self.message,
        }
        payload.update(self.extra)
        return payload


#: Required story hit fields without repair defaults (R07).
_STORY_HIT_REQUIRED: tuple[str, ...] = (
    "story_id",
    "title",
    "status",
    "story_type",
    "source_type",
    "module",
    "epic",
    "section_heading",
    "score",
    "snippet",
)

#: Required concept hit fields without repair defaults (R07).
_CONCEPT_HIT_REQUIRED: tuple[str, ...] = (
    "concept_id",
    "title",
    "module",
    "section_heading",
    "section_number",
    "is_appendix",
    "parent_concept_id",
    "defers_to",
    "authority_over",
    "normative_rules",
    "concept_status",
    "snippet",
)


class KnowledgeTools:
    """Bound tool surface for one MCP runtime binding."""

    def __init__(
        self,
        binding: RuntimeBinding,
        engine: IngestEngine,
        *,
        search_port: object,
        graph: Mapping[str, Any] | None = None,
    ) -> None:
        self._binding = binding
        self._engine = engine
        self._search = search_port
        # R09: graph is required for concept_search ranking; load fail-closed
        # unless an explicit validated graph is injected (tests).
        if graph is not None:
            self._graph = dict(graph)
        else:
            self._graph = self._load_graph_strict()
        self._resolver = ConceptGraphResolver(self._graph)

    def _load_graph_strict(self) -> dict[str, Any]:
        """Load concept_graph.json with shape + corpus_revision checks (R09)."""
        path = self._binding.project.concepts_dir / "concept_graph.json"
        if not path.is_file():
            raise ToolExecutionError(
                "graph_unavailable",
                f"concept_graph.json missing at {path} (fail-closed, R09).",
            )
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ToolExecutionError(
                "graph_unavailable",
                f"concept_graph.json unreadable/malformed: {exc} (fail-closed, R09).",
            ) from exc
        if not isinstance(data, dict):
            raise ToolExecutionError(
                "graph_unavailable",
                "concept_graph.json must be an object (fail-closed, R09).",
            )
        for key in ("nodes", "edges", "corpus_revision"):
            if key not in data:
                raise ToolExecutionError(
                    "graph_unavailable",
                    f"concept_graph.json missing required key {key!r} (R09).",
                )
        if not isinstance(data["nodes"], dict):
            raise ToolExecutionError(
                "graph_unavailable",
                "concept_graph.json nodes must be an object (R09).",
            )
        if not isinstance(data["edges"], list):
            raise ToolExecutionError(
                "graph_unavailable",
                "concept_graph.json edges must be a list (R09).",
            )
        revision = data["corpus_revision"]
        if not isinstance(revision, str) or not revision:
            raise ToolExecutionError(
                "graph_unavailable",
                "concept_graph.json corpus_revision must be a non-empty string (R09).",
            )
        # Compare against live corpus revision when discovery is available.
        try:
            from agentkit.backend.concept_catalog.corpus.hashing import corpus_revision
            from agentkit.backend.concept_catalog.corpus.parser import PARSER_VERSION

            disc = discover_concept_files(self._binding.project.concepts_dir, strict=True)
            live_rev = corpus_revision(
                [d.file_hash for d in disc.documents], parser_version=PARSER_VERSION
            )
            if revision != live_rev:
                raise ToolExecutionError(
                    "graph_stale",
                    f"concept_graph.json corpus_revision {revision!r} != live "
                    f"{live_rev!r} (fail-closed, R09).",
                )
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError(
                "graph_unavailable",
                f"cannot verify concept_graph corpus_revision: {exc} (R09).",
            ) from exc
        return data

    def handle_raw(self, name: str, raw_args: dict[str, object]) -> dict[str, object]:
        """Parse strict wire args then dispatch (R06)."""
        try:
            args = parse_tool_args(name, raw_args)
        except ValidationError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        except ValueError as exc:
            raise ToolExecutionError("unknown_tool", str(exc)) from exc
        handlers = {
            "story_search": self.story_search,
            "story_list_sources": self.story_list_sources,
            "story_sync": self.story_sync,
            "concept_search": self.concept_search,
            "concept_sync": self.concept_sync,
        }
        return handlers[name](args)

    def story_search(self, args: Mapping[str, Any]) -> dict[str, object]:
        try:
            project_id = resolve_tool_project_id(
                self._binding, args.get("project_id")
            )
        except RuntimeBindingError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        filters: dict[str, object] = {}
        if args.get("status"):
            filters["status"] = args["status"]
        if args.get("story_type"):
            filters["story_type"] = args["story_type"]
        try:
            hits = self._search.search(  # type: ignore[attr-defined]
                collection=STORY_COLLECTION,
                query=str(args["query"]),
                search_mode=str(args.get("search_mode") or "hybrid"),
                project_id=project_id,
                limit=int(args.get("limit") or 10),
                filters=filters or None,
                source_types=["story", "research"],
            )
        except VectorDbError as exc:
            raise ToolExecutionError("vectordb_unavailable", str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("vectordb_unavailable", str(exc)) from exc

        results = [_strict_story_hit(hit) for hit in hits]
        return {
            "ok": True,
            "project_id": project_id,
            "search_mode": args.get("search_mode") or "hybrid",
            "results": results,
        }

    def story_list_sources(self, args: Mapping[str, Any]) -> dict[str, object]:
        try:
            project_id = resolve_tool_project_id(
                self._binding, args.get("project_id")
            )
        except RuntimeBindingError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        sources = self._engine.list_sources(self._binding.project)
        return {"ok": True, "project_id": project_id, "sources": sources}

    def story_sync(self, args: Mapping[str, Any]) -> dict[str, object]:
        try:
            project_id = resolve_tool_project_id(
                self._binding, args.get("project_id")
            )
            full = bool(args.get("full_reindex") or False)
        except RuntimeBindingError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        try:
            report = self._engine.story_sync(
                self._binding.project, full_reindex=full
            )
        except (IngestError, Exception) as exc:  # noqa: BLE001
            raise ToolExecutionError("sync_failed", str(exc)) from exc
        return {"ok": True, "project_id": project_id, **report.as_dict()}

    def concept_search(self, args: Mapping[str, Any]) -> dict[str, object]:
        try:
            project_id = resolve_tool_project_id(
                self._binding, args.get("project_id")
            )
        except RuntimeBindingError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        # Lazy re-verify graph if constructor injected one without live check
        # (still required shape); productive start already loaded strict.
        if not self._graph:
            raise ToolExecutionError(
                "graph_unavailable",
                "concept_graph not loaded (fail-closed, R09).",
            )
        concept_status = str(args.get("concept_status") or "active")
        filters: dict[str, object] = {"concept_status": concept_status}
        if args.get("concept_id"):
            filters["concept_id"] = args["concept_id"]
        if args.get("module"):
            filters["module"] = args["module"]
        if args.get("is_appendix") is not None:
            filters["is_appendix"] = args["is_appendix"]
        query_scopes = list(args.get("query_scopes") or [])
        if not query_scopes:
            query_scopes = self._infer_scopes(str(args["query"]))
        limit = int(args.get("limit") or 10)
        try:
            hits = self._search.search(  # type: ignore[attr-defined]
                collection=STORY_COLLECTION,
                query=str(args["query"]),
                search_mode=str(args.get("search_mode") or "hybrid"),
                project_id=project_id,
                limit=max(limit * 3, limit),
                filters=filters,
                source_types=["concept"],
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("vectordb_unavailable", str(exc)) from exc

        prefer_appendix = bool(args.get("is_appendix")) or _query_wants_detail(
            str(args["query"])
        )
        ranked = self._resolver.rank(
            list(hits),
            query_scopes=query_scopes,
            query_module=str(args.get("module") or ""),
            prefer_appendix_detail=prefer_appendix,
        )
        results = []
        for item in ranked[:limit]:
            hit = item.hit
            shape = _strict_concept_hit(hit)
            shape["score"] = item.rank_score
            shape["rank_reasons"] = list(item.reasons)
            results.append(shape)
        return {
            "ok": True,
            "project_id": project_id,
            "search_mode": args.get("search_mode") or "hybrid",
            "concept_status": concept_status,
            "results": results,
        }

    def concept_sync(self, args: Mapping[str, Any]) -> dict[str, object]:
        try:
            project_id = resolve_tool_project_id(
                self._binding, args.get("project_id")
            )
            full = bool(args.get("full_reindex") or False)
        except RuntimeBindingError as exc:
            raise ToolExecutionError("invalid_argument", str(exc)) from exc
        concept_path = args.get("concept_path")
        source_file_filter: str | None = None
        records = None
        if concept_path:
            source_file_filter, records = self._resolve_concept_path(str(concept_path))
        try:
            if records is not None:
                result = concept_sync_bounded_window(
                    self._binding.project,
                    self._engine,
                    full_reindex=full,
                    records=records,
                    source_file_filter=source_file_filter,
                )
            else:
                result = concept_sync_bounded_window(
                    self._binding.project,
                    self._engine,
                    full_reindex=full,
                )
        except ConceptSyncBlockedError as exc:
            raise ToolExecutionError(
                "validation_blocked",
                "concept_validate blocked sync",
                validation=exc.validation.as_dict(),
            ) from exc
        except (IngestError, Exception) as exc:  # noqa: BLE001
            raise ToolExecutionError("sync_failed", str(exc)) from exc
        return {
            "ok": True,
            "project_id": project_id,
            "corpus_revision": result.receipt.corpus_revision,
            "generation_id": result.receipt.generation_id,
            "counters": result.ingest.counters.as_dict(),
            "receipt_digest": result.receipt.digest,
        }

    def _resolve_concept_path(
        self, concept_path: str
    ) -> tuple[str, list[Any]]:
        """Resolve concept_path with one canonical semantics (R10).

        Accepted forms (exactly one document):
        - relative to concepts_dir (``fk_test.md``)
        - project-relative under concepts_dir (``concepts/fk_test.md``)
        - absolute path inside concepts_dir

        Rejects: outside project, outside concepts_dir, missing, ambiguous.
        Empty record set is rejected before ingest.
        """
        binding = self._binding.project
        concepts = binding.concepts_dir.resolve(strict=False)
        raw = Path(concept_path)
        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            # Prefer concepts_dir-relative first (canonical).
            candidates.append(concepts / raw)
            # Also allow project-relative if it lands under concepts_dir.
            candidates.append(binding.project_root / raw)

        resolved: Path | None = None
        for cand in candidates:
            try:
                abs_cand = cand.resolve(strict=False)
            except OSError as exc:
                raise ToolExecutionError("invalid_argument", str(exc)) from exc
            try:
                abs_cand.relative_to(concepts)
            except ValueError:
                continue
            # Must be under concepts_dir AND under project_root.
            try:
                binding.resolve_contained(abs_cand)
            except Exception as exc:  # noqa: BLE001
                raise ToolExecutionError("invalid_argument", str(exc)) from exc
            if not abs_cand.is_file():
                continue
            if resolved is not None and resolved != abs_cand:
                raise ToolExecutionError(
                    "invalid_argument",
                    f"concept_path {concept_path!r} is ambiguous (R10).",
                )
            resolved = abs_cand

        if resolved is None:
            raise ToolExecutionError(
                "invalid_argument",
                f"concept_path {concept_path!r} not found under concepts_dir (R10).",
            )

        # Canonical source_file is project-relative POSIX of the chosen file.
        source_file = binding.relative_posix(resolved)
        disc = discover_concept_files(binding.concepts_dir, strict=True)
        docs = tuple(
            d
            for d in disc.documents
            if binding.relative_posix(d.path) == source_file
            or d.rel_path == resolved.relative_to(concepts).as_posix()
        )
        # Exact equality only — no endswith.
        if not docs:
            raise ToolExecutionError(
                "invalid_argument",
                f"concept_path {concept_path!r} not in discovery set (R10).",
            )
        if len(docs) > 1:
            raise ToolExecutionError(
                "invalid_argument",
                f"concept_path {concept_path!r} matches multiple documents (R10).",
            )
        records = build_concept_chunks(binding, documents=docs)
        # Filter to exact source_file from the record itself (canonical).
        records = [r for r in records if r.source_file == source_file]
        if not records:
            # Records may use concepts-relative paths; align filter from doc.
            doc_rel = docs[0].rel_path
            alt_source = binding.relative_posix(docs[0].path)
            records = build_concept_chunks(binding, documents=docs)
            records = [
                r
                for r in records
                if r.source_file in {source_file, alt_source, doc_rel}
                or r.source_file.endswith("/" + doc_rel)
            ]
            # Prefer the actual record source_file as the filter.
            if records:
                source_file = records[0].source_file
                records = [r for r in records if r.source_file == source_file]
        if not records:
            raise ToolExecutionError(
                "invalid_argument",
                f"concept_path {concept_path!r} produced empty record set "
                "(reject before ingest, R10).",
            )
        return source_file, records

    def _infer_scopes(self, query: str) -> list[str]:
        """Infer authority scopes from graph edges mentioned in the query."""
        scopes: set[str] = set()
        q = query.lower()
        for edge in self._graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            scope = str(edge.get("scope") or "")
            if scope and scope.lower() in q:
                scopes.add(scope)
        return sorted(scopes)


def _strict_story_hit(hit: Mapping[str, Any]) -> dict[str, object]:
    """Project a story hit with full shape and no repair defaults (R07)."""
    missing = [k for k in _STORY_HIT_REQUIRED if k not in hit]
    if missing:
        raise ToolExecutionError(
            "malformed_hit",
            f"story hit missing required fields {missing} (fail-closed, R07).",
        )
    out: dict[str, object] = {}
    str_keys = {
        "story_id",
        "title",
        "status",
        "story_type",
        "source_type",
        "module",
        "epic",
        "section_heading",
        "snippet",
    }
    for key in _STORY_HIT_REQUIRED:
        value = hit[key]
        if key in str_keys and not isinstance(value, str):
            raise ToolExecutionError(
                "malformed_hit",
                f"story hit field {key!r} must be str (R07).",
            )
        if key == "score":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ToolExecutionError(
                    "malformed_hit",
                    "story hit score must be numeric (R07).",
                )
            out[key] = float(value)
        else:
            out[key] = value
    return out


def _strict_concept_hit(hit: Mapping[str, Any]) -> dict[str, object]:
    """Project a concept hit with full shape and no repair defaults (R07)."""
    missing = [k for k in _CONCEPT_HIT_REQUIRED if k not in hit]
    if missing:
        raise ToolExecutionError(
            "malformed_hit",
            f"concept hit missing required fields {missing} (fail-closed, R07).",
        )
    out: dict[str, object] = {}
    str_keys = {
        "concept_id",
        "title",
        "module",
        "section_heading",
        "section_number",
        "parent_concept_id",
        "normative_rules",
        "concept_status",
        "snippet",
    }
    for key in _CONCEPT_HIT_REQUIRED:
        value = hit[key]
        if key in str_keys and not isinstance(value, str):
            raise ToolExecutionError(
                "malformed_hit",
                f"concept hit field {key!r} must be str (R07).",
            )
        if key == "is_appendix" and not isinstance(value, bool):
            raise ToolExecutionError(
                "malformed_hit",
                "concept hit is_appendix must be bool (R07).",
            )
        if key in {"defers_to", "authority_over"} and not isinstance(value, list):
            raise ToolExecutionError(
                "malformed_hit",
                f"concept hit field {key!r} must be list (R07).",
            )
        out[key] = value
    return out


def _query_wants_detail(query: str) -> bool:
    q = query.lower()
    return any(tok in q for tok in ("interface", "test", "appendix", "detail", "api"))


__all__ = [
    "KnowledgeTools",
    "ToolExecutionError",
]
