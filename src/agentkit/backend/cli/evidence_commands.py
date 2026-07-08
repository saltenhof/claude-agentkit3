"""Evidence assembly CLI command handlers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from agentkit.backend.verify_system.evidence import RepoContext
    from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence


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
    evidence_assemble_parser.add_argument("--config")


def _cmd_evidence_assemble(args: argparse.Namespace) -> int:
    """Handle ``agentkit evidence assemble`` command."""
    from pathlib import Path

    from agentkit.backend.utils.io import atomic_write_text
    from agentkit.backend.verify_system.evidence import (
        EvidenceAssembler,
        EvidenceAssemblyError,
        ImportResolver,
    )

    story_dir = Path(args.story_dir)
    output_dir = Path(args.output_dir)
    config_path = Path(args.config) if args.config is not None else story_dir / "context.json"
    try:
        cli_config = _load_evidence_cli_config(config_path)
        repos = {
            repo.repo_id: repo
            for repo in _repo_contexts_from_cli_config(cli_config, story_dir)
        }
        evidence_by_repo = _change_evidence_from_cli_config(cli_config)
        assembler = EvidenceAssembler(
            repos,
            change_evidence_port=_StaticChangeEvidencePort(
                evidence_by_repo=evidence_by_repo,
                repo_paths={repo_id: repo.repo_path for repo_id, repo in repos.items()},
            ),
            import_evidence_provider=ImportResolver.from_repo_contexts(repos),
        )
        result = assembler.assemble(story_dir=story_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "bundle_manifest.json"
        atomic_write_text(
            manifest_path,
            result.manifest.model_dump_json(indent=2) + "\n",
        )
    except (EvidenceAssemblyError, ValueError, OSError) as exc:
        print(f"Evidence assembly failed [{args.story_id}]: {exc}", file=sys.stderr)
        return 1

    print(result.manifest.model_dump_json(indent=2))
    print(json.dumps({"merge_paths": list(result.merge_paths)}, indent=2, sort_keys=True))
    return 0


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


def _repo_contexts_from_cli_config(
    config: dict[str, object],
    story_dir: Path,
) -> list[RepoContext]:
    """Build repo contexts from CLI config data."""
    from agentkit.backend.verify_system.evidence import RepoContext

    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        msg = "evidence config must contain a non-empty repositories list"
        raise ValueError(msg)
    repos: list[RepoContext] = []
    for item in repositories:
        if not isinstance(item, dict):
            msg = "each evidence repository config must be an object"
            raise ValueError(msg)
        repo_path_raw = item.get("repo_path")
        if not isinstance(repo_path_raw, str) or not repo_path_raw.strip():
            msg = "each evidence repository config requires repo_path"
            raise ValueError(msg)
        repo_path = Path(repo_path_raw)
        if not repo_path.is_absolute():
            repo_path = (story_dir / repo_path).resolve()
        repos.append(RepoContext.model_validate({**item, "repo_path": repo_path}))
    return repos


def _change_evidence_from_cli_config(
    config: dict[str, object],
) -> dict[str, ChangeEvidence]:
    """Build static change evidence from CLI config data."""
    from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

    raw_evidence = config.get("change_evidence")
    if not isinstance(raw_evidence, dict) or not raw_evidence:
        msg = "evidence config must contain non-empty change_evidence"
        raise ValueError(msg)
    evidence: dict[str, ChangeEvidence] = {}
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
        evidence[repo_id] = ChangeEvidence(
            available=True,
            changed_files=tuple(changed_files),
        )
    return evidence


@dataclass(frozen=True)
class _StaticChangeEvidencePort:
    """CLI adapter for pre-collected change evidence.

    This does not run git; it only passes operator-supplied/system-exported
    ``ChangeEvidence`` into the assembler's existing read-port shape.
    """

    evidence_by_repo: dict[str, ChangeEvidence]
    repo_paths: dict[str, Path]

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Return the configured evidence matching ``story_dir``."""
        resolved_story_dir = story_dir.resolve()
        for repo_id, repo_path in self.repo_paths.items():
            if repo_path.resolve() == resolved_story_dir:
                evidence = self.evidence_by_repo.get(repo_id)
                if evidence is not None:
                    return evidence
        from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

        return ChangeEvidence(available=False)


# ---------------------------------------------------------------------------
# AG3-076: operator/recovery command registration + handlers
# ---------------------------------------------------------------------------

_VALID_PHASES = frozenset({"setup", "exploration", "implementation", "closure"})


class _ConfigResolutionError(Exception):
    """Raised when ``--config`` is provided but fails to yield a project_key.

    Signals that the caller must fail-closed (non-zero) rather than falling
    through to the environment variable.  Never raised when ``--config`` is
    absent (the fallthrough path is intentional in that case).
    """

