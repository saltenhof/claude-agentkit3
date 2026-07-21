"""Fail-closed loader for ``concept/_meta/concept-governance.json`` (FK-78 section 78.2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

#: Blueprint-fixed location of the governance configuration.
CONFIG_RELATIVE_PATH = "concept/_meta/concept-governance.json"

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_ROOT_KEYS = ("domain", "technical", "formal", "meta", "guardrails")
_GRAMMAR_KEYS = ("domain_doc", "technical_doc", "formal_object", "decision_record", "scope", "source")
_DATA_CLASSES = ("open", "internal", "sensitive")
_TOP_LEVEL_KEYS = (
    "schema_version",
    "concept_roots",
    "incubator_root",
    "lock_backend",
    "id_grammars",
    "frontmatter_contract",
    "vcs_policy",
    "data_class_default",
)
_OPTIONAL_TOP_LEVEL_KEYS = ("lock_remote",)


class GovernanceConfigError(Exception):
    """Raised when the governance configuration is invalid (exit 3 territory)."""


class GovernanceConfigMissingError(Exception):
    """Raised when the governance configuration file is absent (exit 2 territory)."""


@dataclass(frozen=True)
class FrontmatterContract:
    """Frontmatter contract switches from the governance configuration."""

    required_fields: tuple[str, ...]
    classification: str
    detail_requires_parent: bool
    full_supersession_reciprocity: bool


@dataclass(frozen=True)
class VcsPolicy:
    """Class-based VCS policy from the governance configuration."""

    mode: str
    sensitive_disposition: str
    unclassified_class: str


@dataclass(frozen=True)
class GovernanceConfig:
    """Validated, project-neutral toolchain configuration."""

    schema_version: str
    concept_roots: Mapping[str, str]
    incubator_root: str
    lock_backend: str
    id_grammars: Mapping[str, re.Pattern[str]]
    frontmatter_contract: FrontmatterContract
    vcs_policy: VcsPolicy
    data_class_default: str
    lock_remote: str | None

    def root_path(self, project_root: Path, root_key: str) -> Path:
        """Return the absolute path of one configured concept root."""
        return project_root / self.concept_roots[root_key]

    def meta_path(self, project_root: Path, *parts: str) -> Path:
        """Return an absolute path below the configured meta root."""
        return self.root_path(project_root, "meta").joinpath(*parts)


def load_governance_config(project_root: Path) -> GovernanceConfig:
    """Load and validate the governance configuration fail-closed.

    Args:
        project_root: Target-project root directory.

    Returns:
        The validated configuration.

    Raises:
        GovernanceConfigMissingError: If the configuration file is absent.
        GovernanceConfigError: If the configuration is structurally invalid.
    """
    config_path = project_root / CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        raise GovernanceConfigMissingError(f"governance configuration not found: {CONFIG_RELATIVE_PATH}")
    try:
        raw: object = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: not readable as JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: top level must be a JSON object")
    _require_exact_keys(raw, _TOP_LEVEL_KEYS + _OPTIONAL_TOP_LEVEL_KEYS, "top level", required=_TOP_LEVEL_KEYS)
    return GovernanceConfig(
        schema_version=_parse_schema_version(raw["schema_version"]),
        concept_roots=_parse_concept_roots(raw["concept_roots"]),
        incubator_root=_require_string(raw["incubator_root"], "incubator_root"),
        lock_backend=_require_enum(raw["lock_backend"], "lock_backend", ("filesystem", "git-remote")),
        id_grammars=_parse_id_grammars(raw["id_grammars"]),
        frontmatter_contract=_parse_frontmatter_contract(raw["frontmatter_contract"]),
        vcs_policy=_parse_vcs_policy(raw["vcs_policy"]),
        data_class_default=_require_enum(raw["data_class_default"], "data_class_default", _DATA_CLASSES),
        lock_remote=_parse_lock_remote(raw),
    )


def _parse_lock_remote(raw: dict[str, object]) -> str | None:
    """Read the optional git-remote name; mandatory for the git-remote backend."""
    value = raw.get("lock_remote")
    if value is None:
        if raw.get("lock_backend") == "git-remote":
            raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: lock_backend 'git-remote' requires 'lock_remote'")
        return None
    return _require_string(value, "lock_remote")


def _require_exact_keys(
    mapping: dict[str, object], expected: tuple[str, ...], context: str, required: tuple[str, ...] | None = None
) -> None:
    unknown = sorted(set(mapping) - set(expected))
    missing = sorted(set(required if required is not None else expected) - set(mapping))
    if unknown:
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: unknown {context} field(s): {', '.join(unknown)}")
    if missing:
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: missing required {context} field(s): {', '.join(missing)}")


def _parse_schema_version(value: object) -> str:
    version = _require_string(value, "schema_version")
    match = _SEMVER_RE.match(version)
    if match is None:
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: schema_version must be SemVer, got {version!r}")
    if match.group(1) != "1":
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: unsupported schema_version major {match.group(1)!r} (need 1)")
    return version


def _parse_concept_roots(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: concept_roots must be an object")
    _require_exact_keys(value, _ROOT_KEYS, "concept_roots")
    roots: dict[str, str] = {}
    for key in _ROOT_KEYS:
        root = _require_string(value[key], f"concept_roots.{key}")
        if root.startswith(("/", "\\")) or "\\" in root or ".." in root.split("/"):
            raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: concept_roots.{key} must be a relative '/'-path, got {root!r}")
        roots[key] = root.rstrip("/")
    return roots


def _parse_id_grammars(value: object) -> dict[str, re.Pattern[str]]:
    if not isinstance(value, dict):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: id_grammars must be an object")
    _require_exact_keys(value, _GRAMMAR_KEYS, "id_grammars")
    grammars: dict[str, re.Pattern[str]] = {}
    for key in _GRAMMAR_KEYS:
        pattern = _require_string(value[key], f"id_grammars.{key}")
        try:
            grammars[key] = re.compile(pattern)
        except re.error as exc:
            raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: id_grammars.{key} is not a valid regex: {exc}") from exc
    return grammars


def _parse_frontmatter_contract(value: object) -> FrontmatterContract:
    if not isinstance(value, dict):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: frontmatter_contract must be an object")
    expected = ("required_fields", "classification", "detail_requires_parent", "full_supersession_reciprocity")
    _require_exact_keys(value, expected, "frontmatter_contract")
    required_fields = value["required_fields"]
    if (
        not isinstance(required_fields, list)
        or not required_fields
        or not all(isinstance(item, str) and item for item in required_fields)
    ):
        raise GovernanceConfigError(
            f"{CONFIG_RELATIVE_PATH}: frontmatter_contract.required_fields must be a non-empty list of non-empty strings"
        )
    return FrontmatterContract(
        required_fields=tuple(required_fields),
        classification=_require_enum(
            value["classification"], "frontmatter_contract.classification", ("formal_refs_xor_prose_only",)
        ),
        detail_requires_parent=_require_bool(value["detail_requires_parent"], "frontmatter_contract.detail_requires_parent"),
        full_supersession_reciprocity=_require_bool(
            value["full_supersession_reciprocity"], "frontmatter_contract.full_supersession_reciprocity"
        ),
    )


def _parse_vcs_policy(value: object) -> VcsPolicy:
    if not isinstance(value, dict):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: vcs_policy must be an object")
    _require_exact_keys(value, ("mode", "sensitive_disposition", "unclassified_class"), "vcs_policy")
    return VcsPolicy(
        mode=_require_enum(value["mode"], "vcs_policy.mode", ("class_based",)),
        sensitive_disposition=_require_enum(value["sensitive_disposition"], "vcs_policy.sensitive_disposition", ("local",)),
        unclassified_class=_require_enum(value["unclassified_class"], "vcs_policy.unclassified_class", _DATA_CLASSES),
    )


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: {field_name} must be a non-empty string")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: {field_name} must be a boolean")
    return value


def _require_enum(value: object, field_name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GovernanceConfigError(f"{CONFIG_RELATIVE_PATH}: {field_name} must be one of {', '.join(allowed)}, got {value!r}")
    return value
