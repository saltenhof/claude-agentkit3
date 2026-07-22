"""Strict YAML frontmatter parsing (FK-13 §13.9.6, AG3-174 R02/R08/AC 10).

YAML/UTF-8/fence/duplicate-key failures are hard in ALL profiles.
An inventory profile may accept additional document classes AFTER a successful
parse — it never invents IDs, enums, or empty frontmatter.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Final

import yaml
from yaml.loader import SafeLoader
from yaml.nodes import MappingNode

from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError

_FRONTMATTER_RE = re.compile(rb"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_MAX_YAML_DEPTH: Final[int] = 16

ALLOWED_STATUS: Final[frozenset[str]] = frozenset({"active", "draft", "archived"})
ALLOWED_DOC_KIND_FK13: Final[frozenset[str]] = frozenset({"core", "appendix"})
#: Inventory profile (AK3 tool): additional classes after successful parse only.
ALLOWED_DOC_KIND_INVENTORY: Final[frozenset[str]] = frozenset(
    {
        "core",
        "appendix",
        "decision-record",
        "policy",
        "methodology",
        "spec",
        "context",
        "glossary",
        "index",
    }
)
REQUIRED_FIELDS: Final[tuple[str, ...]] = ("concept_id", "title", "status", "doc_kind")


class _StrictLoader(SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (fail-closed)."""


def _construct_mapping_no_duplicates(
    loader: yaml.Loader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise yaml.constructor.ConstructorError(
            None, None, f"expected a mapping node, got {node.id}", node.start_mark
        )
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


@dataclass(frozen=True)
class DeferralRef:
    target: str
    scope: str
    reason: str


@dataclass(frozen=True)
class AuthorityClaim:
    scope: str


@dataclass(frozen=True)
class ConceptFrontmatter:
    concept_id: str
    title: str
    status: str
    doc_kind: str
    module: str
    parent_concept_id: str | None
    authority_over: tuple[AuthorityClaim, ...]
    defers_to: tuple[DeferralRef, ...]
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]
    tags: tuple[str, ...]
    raw: dict[str, Any]


def split_frontmatter_bytes(data: bytes, *, path: str | None = None) -> tuple[bytes, bytes]:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConceptParseError(
            "E-SCHEMA-001",
            f"file is not valid UTF-8: {exc}",
            path=path,
        ) from exc
    match = _FRONTMATTER_RE.match(data)
    if match is None:
        raise ConceptParseError(
            "E-SCHEMA-001",
            "frontmatter missing or not parseable (expected --- ... --- block)",
            path=path,
        )
    return match.group(1), data[match.end() :]


def parse_frontmatter_yaml(yaml_bytes: bytes, *, path: str | None = None) -> dict[str, Any]:
    try:
        text = yaml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConceptParseError(
            "E-SCHEMA-001",
            f"frontmatter is not valid UTF-8: {exc}",
            path=path,
        ) from exc
    if any("\ud800" <= ch <= "\udfff" for ch in text):
        raise ConceptParseError(
            "E-SCHEMA-001",
            "frontmatter contains lone Unicode surrogates",
            path=path,
        )
    try:
        loaded = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ConceptParseError(
            "E-SCHEMA-001",
            f"YAML not parseable: {exc}",
            path=path,
        ) from exc
    if loaded is None:
        raise ConceptParseError("E-SCHEMA-001", "frontmatter is empty", path=path)
    if not isinstance(loaded, dict):
        raise ConceptParseError(
            "E-SCHEMA-001",
            f"frontmatter must be a mapping, got {type(loaded).__name__}",
            path=path,
        )
    _reject_nonfinite_and_depth(loaded, depth=0, path=path)
    return loaded


def validate_concept_frontmatter(
    raw: dict[str, Any],
    *,
    path: str | None = None,
    mode: str = "fk13",
) -> ConceptFrontmatter:
    """Validate frontmatter after a successful strict YAML parse.

    ``mode="fk13"``: doc_kind in {core, appendix}.
    ``mode="inventory"``: additional document classes allowed; still requires
    concept_id/title/status/doc_kind without repair (R02).
    """
    if mode not in {"fk13", "inventory"}:
        raise ConceptParseError(
            "E-SCHEMA-003",
            f"unknown frontmatter mode {mode!r}",
            path=path,
        )
    allowed_kinds = ALLOWED_DOC_KIND_FK13 if mode == "fk13" else ALLOWED_DOC_KIND_INVENTORY

    missing = [k for k in REQUIRED_FIELDS if k not in raw or raw[k] in (None, "")]
    if missing:
        raise ConceptParseError(
            "E-SCHEMA-002",
            f"required fields missing: {missing}",
            path=path,
        )
    concept_id = _require_str(raw, "concept_id", path=path)
    title = _require_str(raw, "title", path=path)
    status = _require_str(raw, "status", path=path)
    doc_kind = _require_str(raw, "doc_kind", path=path)
    if status not in ALLOWED_STATUS:
        raise ConceptParseError(
            "E-SCHEMA-003",
            f"status must be one of {sorted(ALLOWED_STATUS)}, got {status!r}",
            path=path,
        )
    if doc_kind not in allowed_kinds:
        raise ConceptParseError(
            "E-SCHEMA-003",
            f"doc_kind must be one of {sorted(allowed_kinds)}, got {doc_kind!r}",
            path=path,
        )
    parent: str | None
    if doc_kind == "appendix":
        parent_raw = raw.get("parent_concept_id")
        if not isinstance(parent_raw, str) or not parent_raw.strip():
            raise ConceptParseError(
                "E-SCHEMA-004",
                "doc_kind=appendix requires non-empty parent_concept_id",
                path=path,
            )
        parent = parent_raw.strip()
    else:
        parent_raw = raw.get("parent_concept_id")
        if parent_raw in (None, "", []):
            parent = None
        elif isinstance(parent_raw, str):
            parent = parent_raw.strip() or None
        else:
            raise ConceptParseError(
                "E-SCHEMA-003",
                "parent_concept_id must be a string when set",
                path=path,
            )

    module_raw = raw.get("module", "")
    if module_raw in (None, ""):
        module = ""
    elif isinstance(module_raw, str):
        module = module_raw.strip()
    else:
        raise ConceptParseError(
            "E-SCHEMA-003",
            "module must be a string",
            path=path,
        )

    return ConceptFrontmatter(
        concept_id=concept_id,
        title=title,
        status=status,
        doc_kind=doc_kind,
        module=module,
        parent_concept_id=parent,
        authority_over=_parse_authority(raw.get("authority_over"), path=path),
        defers_to=_parse_defers(raw.get("defers_to"), path=path),
        supersedes=_parse_id_list(raw.get("supersedes"), field="supersedes", path=path),
        superseded_by=_parse_superseded_by(raw.get("superseded_by"), path=path),
        tags=_parse_id_list(raw.get("tags"), field="tags", path=path),
        raw=dict(raw),
    )


def _require_str(raw: dict[str, Any], key: str, *, path: str | None) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ConceptParseError(
            "E-SCHEMA-003",
            f"{key} must be a string, got {type(value).__name__}",
            path=path,
        )
    stripped = value.strip()
    if not stripped:
        raise ConceptParseError(
            "E-SCHEMA-002",
            f"{key} must be non-empty",
            path=path,
        )
    return stripped


def _parse_authority(raw: Any, *, path: str | None) -> tuple[AuthorityClaim, ...]:
    if raw in (None, []):
        return ()
    if not isinstance(raw, list):
        raise ConceptParseError(
            "E-SCHEMA-003",
            "authority_over must be a list",
            path=path,
        )
    out: list[AuthorityClaim] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(AuthorityClaim(scope=item.strip()))
        elif isinstance(item, dict):
            scope = item.get("scope")
            if not isinstance(scope, str) or not scope.strip():
                raise ConceptParseError(
                    "E-SCHEMA-003",
                    "authority_over entry requires string scope",
                    path=path,
                )
            out.append(AuthorityClaim(scope=scope.strip()))
        else:
            raise ConceptParseError(
                "E-SCHEMA-003",
                "authority_over entries must be strings or {scope: ...} maps",
                path=path,
            )
    return tuple(out)


def _parse_defers(raw: Any, *, path: str | None) -> tuple[DeferralRef, ...]:
    if raw in (None, []):
        return ()
    if not isinstance(raw, list):
        raise ConceptParseError(
            "E-SCHEMA-003",
            "defers_to must be a list",
            path=path,
        )
    out: list[DeferralRef] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(DeferralRef(target=item.strip(), scope="", reason=""))
        elif isinstance(item, dict):
            target = item.get("target")
            if not isinstance(target, str) or not target.strip():
                raise ConceptParseError(
                    "E-SCHEMA-003",
                    "defers_to entry requires string target",
                    path=path,
                )
            scope = item.get("scope", "")
            reason = item.get("reason", "")
            if scope is None:
                scope = ""
            if reason is None:
                reason = ""
            if not isinstance(scope, str) or not isinstance(reason, str):
                raise ConceptParseError(
                    "E-SCHEMA-003",
                    "defers_to scope/reason must be strings",
                    path=path,
                )
            out.append(
                DeferralRef(
                    target=target.strip(),
                    scope=scope.strip(),
                    reason=reason.strip(),
                )
            )
        else:
            raise ConceptParseError(
                "E-SCHEMA-003",
                "defers_to entries must be strings or maps",
                path=path,
            )
    return tuple(out)


def _parse_id_list(raw: Any, *, field: str, path: str | None) -> tuple[str, ...]:
    if raw in (None, [], ""):
        return ()
    if not isinstance(raw, list):
        raise ConceptParseError(
            "E-SCHEMA-003",
            f"{field} must be a list",
            path=path,
        )
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict) and "target" in item:
            target = item.get("target")
            if isinstance(target, str) and target.strip():
                out.append(target.strip())
            else:
                raise ConceptParseError(
                    "E-SCHEMA-003",
                    f"{field} map entry requires string target",
                    path=path,
                )
        else:
            raise ConceptParseError(
                "E-SCHEMA-003",
                f"{field} entries must be non-empty strings",
                path=path,
            )
    return tuple(out)


def _parse_superseded_by(raw: Any, *, path: str | None) -> tuple[str, ...]:
    if raw in (None, "", []):
        return ()
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    if isinstance(raw, list):
        return _parse_id_list(raw, field="superseded_by", path=path)
    raise ConceptParseError(
        "E-SCHEMA-003",
        "superseded_by must be a string or list of strings",
        path=path,
    )


def _reject_nonfinite_and_depth(value: Any, *, depth: int, path: str | None) -> None:
    if depth > _MAX_YAML_DEPTH:
        raise ConceptParseError(
            "E-SCHEMA-001",
            f"YAML exceeds max depth {_MAX_YAML_DEPTH}",
            path=path,
        )
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ConceptParseError(
            "E-SCHEMA-001",
            "non-finite numbers are not allowed in frontmatter",
            path=path,
        )
    if isinstance(value, dict):
        for v in value.values():
            _reject_nonfinite_and_depth(v, depth=depth + 1, path=path)
    elif isinstance(value, list):
        for v in value:
            _reject_nonfinite_and_depth(v, depth=depth + 1, path=path)


# Back-compat alias used by older imports.
ALLOWED_DOC_KIND = ALLOWED_DOC_KIND_FK13

__all__ = [
    "ALLOWED_DOC_KIND",
    "ALLOWED_DOC_KIND_FK13",
    "ALLOWED_DOC_KIND_INVENTORY",
    "ALLOWED_STATUS",
    "AuthorityClaim",
    "ConceptFrontmatter",
    "DeferralRef",
    "REQUIRED_FIELDS",
    "parse_frontmatter_yaml",
    "split_frontmatter_bytes",
    "validate_concept_frontmatter",
]
