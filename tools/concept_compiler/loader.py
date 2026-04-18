"""Parsing helpers for structured formal concept specifications."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentkit.exceptions import AgentKitError

FORMAL_SPEC_BEGIN = "<!-- FORMAL-SPEC:BEGIN -->"
FORMAL_SPEC_END = "<!-- FORMAL-SPEC:END -->"
REQUIRED_FRONTMATTER_FIELDS = (
    "id",
    "title",
    "status",
    "doc_kind",
    "context",
    "spec_kind",
    "version",
)


class FormalSpecError(AgentKitError):
    """Raised when a formal specification file is invalid."""


@dataclass(frozen=True)
class FormalSpecDocument:
    """Parsed formal specification document."""

    path: Path
    frontmatter: dict[str, Any]
    spec: dict[str, Any]

    @property
    def doc_id(self) -> str:
        return _require_string(self.frontmatter, "id", self.path)

    @property
    def context(self) -> str:
        return _require_string(self.frontmatter, "context", self.path)

    @property
    def spec_kind(self) -> str:
        return _require_string(self.frontmatter, "spec_kind", self.path)


def try_load_frontmatter(path: Path) -> dict[str, Any] | None:
    """Best-effort frontmatter loading for arbitrary markdown files."""
    return _try_parse_frontmatter(path.read_text(encoding="utf-8"))


def discover_formal_spec_files(root: Path) -> tuple[Path, ...]:
    """Return compileable markdown spec files.

    Only files with frontmatter ``doc_kind: spec`` are considered part
    of the machine-compiled formal spec set. Meta and README documents
    under ``concept/formal-spec/`` may mention marker strings in prose
    examples and are therefore excluded here on purpose.
    """
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter = _try_parse_frontmatter(text)
        if frontmatter is None:
            continue
        if frontmatter.get("doc_kind") != "spec":
            continue
        has_begin = FORMAL_SPEC_BEGIN in text
        has_end = FORMAL_SPEC_END in text
        if has_begin != has_end:
            raise FormalSpecError(
                f"Formal spec markers are unbalanced in {path}",
                detail={"path": str(path)},
            )
        if has_begin:
            files.append(path)
    return tuple(files)


def load_formal_spec(path: Path) -> FormalSpecDocument:
    """Load frontmatter plus YAML spec zone from a formal spec markdown file."""
    raw_text = path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(raw_text, path)
    _validate_frontmatter(frontmatter, path)
    spec = _parse_spec_zone(raw_text, path)
    _validate_spec_header(frontmatter, spec, path)
    return FormalSpecDocument(path=path, frontmatter=frontmatter, spec=spec)


def _parse_frontmatter(raw_text: str, path: Path) -> dict[str, Any]:
    parsed = _try_parse_frontmatter(raw_text)
    if parsed is None:
        raise FormalSpecError(
            f"Formal spec file must start with YAML frontmatter: {path}",
            detail={"path": str(path)},
        )
    return parsed


def _try_parse_frontmatter(raw_text: str) -> dict[str, Any] | None:
    if not raw_text.startswith("---\n") and not raw_text.startswith("---\r\n"):
        return None

    lines = raw_text.splitlines()
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return None

    payload = "\n".join(lines[1:end_index])
    try:
        parsed: Any = yaml.safe_load(payload)
    except yaml.YAMLError:
        return None

    if not isinstance(parsed, dict):
        return None
    return parsed


def _validate_frontmatter(frontmatter: dict[str, Any], path: Path) -> None:
    missing = [field for field in REQUIRED_FRONTMATTER_FIELDS if field not in frontmatter]
    if missing:
        raise FormalSpecError(
            f"Formal spec frontmatter is missing required fields in {path}: {', '.join(missing)}",
            detail={"path": str(path), "missing": missing},
        )
    for field in REQUIRED_FRONTMATTER_FIELDS:
        if field == "version":
            continue
        _require_string(frontmatter, field, path)
    _require_version(frontmatter.get("version"), path)


def _parse_spec_zone(raw_text: str, path: Path) -> dict[str, Any]:
    begin_count = raw_text.count(FORMAL_SPEC_BEGIN)
    end_count = raw_text.count(FORMAL_SPEC_END)
    if begin_count != 1 or end_count != 1:
        raise FormalSpecError(
            f"Formal spec file must contain exactly one FORMAL-SPEC block: {path}",
            detail={"path": str(path), "begin_count": begin_count, "end_count": end_count},
        )

    begin_index = raw_text.index(FORMAL_SPEC_BEGIN) + len(FORMAL_SPEC_BEGIN)
    end_index = raw_text.index(FORMAL_SPEC_END)
    block = raw_text[begin_index:end_index].strip()

    if not block.startswith("```yaml") or not block.endswith("```"):
        raise FormalSpecError(
            f"Formal spec block in {path} must be fenced as ```yaml",
            detail={"path": str(path)},
        )

    yaml_body = block.removeprefix("```yaml").removesuffix("```").strip()
    try:
        parsed: Any = yaml.safe_load(yaml_body)
    except yaml.YAMLError as exc:
        raise FormalSpecError(
            f"Invalid FORMAL-SPEC YAML in {path}: {exc}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc

    if not isinstance(parsed, dict):
        raise FormalSpecError(
            f"FORMAL-SPEC block in {path} must be a YAML mapping",
            detail={"path": str(path), "type": type(parsed).__name__},
        )
    return parsed


def _validate_spec_header(frontmatter: dict[str, Any], spec: dict[str, Any], path: Path) -> None:
    for key in ("object", "schema_version", "kind", "context"):
        if key not in spec:
            raise FormalSpecError(
                f"FORMAL-SPEC block in {path} is missing required key '{key}'",
                detail={"path": str(path), "missing": key},
            )

    object_id = _require_string(spec, "object", path)
    kind = _require_string(spec, "kind", path)
    context = _require_string(spec, "context", path)

    if object_id != _require_string(frontmatter, "id", path):
        raise FormalSpecError(
            f"Frontmatter id and FORMAL-SPEC object differ in {path}",
            detail={"path": str(path), "frontmatter_id": frontmatter["id"], "object": object_id},
        )
    if kind != _require_string(frontmatter, "spec_kind", path):
        raise FormalSpecError(
            f"Frontmatter spec_kind and FORMAL-SPEC kind differ in {path}",
            detail={"path": str(path), "spec_kind": frontmatter["spec_kind"], "kind": kind},
        )
    if context != _require_string(frontmatter, "context", path):
        raise FormalSpecError(
            f"Frontmatter context and FORMAL-SPEC context differ in {path}",
            detail={"path": str(path), "frontmatter_context": frontmatter["context"], "context": context},
        )


def _require_string(mapping: dict[str, Any], key: str, path: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise FormalSpecError(
            f"Field '{key}' in {path} must be a non-empty string",
            detail={"path": str(path), "field": key, "type": type(value).__name__},
        )
    return value


def _require_version(value: Any, path: Path) -> None:
    if not isinstance(value, (int, str)) or value == "":
        raise FormalSpecError(
            f"Field 'version' in {path} must be a non-empty string or integer",
            detail={"path": str(path), "field": "version", "type": type(value).__name__},
        )
