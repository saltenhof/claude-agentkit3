"""Evidence assembly CLI command handlers (FK-28 §28.7.1, FK-91 §91.1).

The human operator-recovery surface for the evidence assembly. FK-91 §91.1 fixes
what such a surface is -- "ein menschlicher Adapterpfad auf diese API; fachlich
autoritativ ist der API-Vertrag" -- and since AG3-241 this command is one: it
reads the edge-exported evidence checkpoint, ships it to
``POST /v1/projects/{project_key}/verify-evidence-assemblies`` and writes the
manifest the core returned.

It no longer assembles anything. The assembly decides which evidence a reviewer
sees and stamps the manifest hash the reviewers are held to; running it on the
developer machine put a QA-artefact producer inside the process being reviewed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit_wire.verify_system import (
    EvidenceFile,
    EvidenceRepository,
    VerifyEvidenceAssemblyRequest,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

    #: Seam returning the Project-Edge client bound to a target-project root.
    ClientFactory = Callable[[Path], ProjectEdgeClient]


def add_evidence_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register evidence assembly commands."""
    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Evidence assembly commands",
    )
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command")
    evidence_assemble_parser = evidence_subparsers.add_parser(
        "assemble",
        help="Assemble the review evidence bundle",
    )
    evidence_assemble_parser.add_argument("--story-id", required=True)
    evidence_assemble_parser.add_argument("--story-dir", required=True)
    evidence_assemble_parser.add_argument("--output-dir", required=True)
    evidence_assemble_parser.add_argument("--project-key", required=True)
    evidence_assemble_parser.add_argument("--project-root", required=True)
    evidence_assemble_parser.add_argument("--config")


def _cmd_evidence_assemble(
    args: argparse.Namespace,
    *,
    client_factory: ClientFactory | None = None,
) -> int:
    """Handle ``agentkit evidence assemble`` command.

    Args:
        args: The parsed CLI namespace.
        client_factory: Optional seam returning the Project-Edge client for a
            project root; defaults to the official builder.

    Returns:
        ``0`` on success, ``1`` on any fail-closed outcome.
    """
    from agentkit.backend.utils.io import atomic_write_text

    story_dir = Path(args.story_dir)
    output_dir = Path(args.output_dir)
    config_path = (
        Path(args.config) if args.config is not None else story_dir / "context.json"
    )
    try:
        cli_config = _load_evidence_cli_config(config_path)
        request = _request_from_cli_config(cli_config, story_id=args.story_id)
        client = _build_client(Path(args.project_root), client_factory)
        response = client.assemble_verify_evidence(
            project_key=args.project_key, request=request
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            output_dir / "bundle_manifest.json", response.bundle_manifest_json
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Evidence assembly failed [{args.story_id}]: {exc}", file=sys.stderr)
        return 1

    print(response.bundle_manifest_json.rstrip("\n"))
    print(
        json.dumps(
            {"merge_paths": list(response.merge_paths)}, indent=2, sort_keys=True
        )
    )
    return 0


def _build_client(
    project_root: Path, client_factory: ClientFactory | None
) -> ProjectEdgeClient:
    """Return the Project-Edge client for ``project_root``.

    Args:
        project_root: The target-project root carrying base URL and credential.
        client_factory: Optional seam; ``None`` uses the official builder.

    Returns:
        The bound client.
    """
    if client_factory is not None:
        return client_factory(project_root)
    from agentkit.harness_client.projectedge.runtime import build_project_edge_client

    return build_project_edge_client(project_root)


def _load_evidence_cli_config(path: Path) -> dict[str, object]:
    """Load the CLI evidence config from JSON.

    Args:
        path: Explicit ``--config`` path or ``story_dir/context.json``.

    Returns:
        Parsed JSON mapping.

    Raises:
        ValueError: If the file is missing or is not a JSON object.
    """
    if not path.is_file():
        msg = (
            "evidence assemble requires explicit repo and changed-file evidence "
            f"in --config or story_dir/context.json; missing {path}"
        )
        raise ValueError(msg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"invalid evidence config JSON in {path}: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = f"evidence config must be a JSON object: {path}"
        raise ValueError(msg)
    return data


def _request_from_cli_config(
    config: dict[str, object], *, story_id: str
) -> VerifyEvidenceAssemblyRequest:
    """Project the edge-exported checkpoint onto the wire request.

    Args:
        config: The parsed evidence checkpoint.
        story_id: The story the checkpoint belongs to.

    Returns:
        The validated wire request.

    Raises:
        ValueError: When the checkpoint is structurally unusable (pydantic
            raises ``ValidationError``, a ``ValueError`` subclass).
    """
    changed_files = _changed_files_from_cli_config(config)
    repositories = tuple(
        EvidenceRepository.model_validate(
            {**item, "changed_files": changed_files.get(str(item.get("repo_id")), ())}
        )
        for item in _repository_items(config)
    )
    raw_files = config.get("collected_files")
    if not isinstance(raw_files, list):
        raise ValueError("evidence config requires collected_files from Project Edge")
    return VerifyEvidenceAssemblyRequest(
        story_id=story_id,
        repositories=repositories,
        collected_files=tuple(EvidenceFile.model_validate(item) for item in raw_files),
    )


def _repository_items(config: dict[str, object]) -> list[dict[str, object]]:
    """Return the logical repository entries, rejecting physical paths.

    Args:
        config: The parsed evidence checkpoint.

    Returns:
        The repository entries.

    Raises:
        ValueError: When the list is missing, empty, malformed, or carries a
            physical ``repo_path``.
    """
    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        msg = "evidence config must contain a non-empty repositories list"
        raise ValueError(msg)
    items: list[dict[str, object]] = []
    for item in repositories:
        if not isinstance(item, dict):
            msg = "each evidence repository config must be an object"
            raise ValueError(msg)
        repo_id = item.get("repo_id")
        if not isinstance(repo_id, str) or not repo_id.strip():
            msg = "each evidence repository config requires repo_id"
            raise ValueError(msg)
        if "repo_path" in item:
            raise ValueError("physical repo_path is forbidden in evidence config")
        items.append(item)
    return items


def _changed_files_from_cli_config(
    config: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    """Read the per-repository change inventory of the checkpoint.

    Args:
        config: The parsed evidence checkpoint.

    Returns:
        Mapping of ``repo_id`` to its reported changed files.

    Raises:
        ValueError: When the inventory is missing or malformed.
    """
    raw_evidence = config.get("change_evidence")
    if not isinstance(raw_evidence, dict) or not raw_evidence:
        msg = "evidence config must contain non-empty change_evidence"
        raise ValueError(msg)
    inventory: dict[str, tuple[str, ...]] = {}
    for repo_id, item in raw_evidence.items():
        if not isinstance(repo_id, str) or not isinstance(item, dict):
            msg = "each change_evidence entry must map a repo_id to an object"
            raise ValueError(msg)
        changed_files = item.get("changed_files")
        if not isinstance(changed_files, list) or not all(
            isinstance(path, str) for path in changed_files
        ):
            msg = f"change_evidence for {repo_id} requires changed_files string list"
            raise ValueError(msg)
        inventory[repo_id] = tuple(changed_files)
    return inventory
