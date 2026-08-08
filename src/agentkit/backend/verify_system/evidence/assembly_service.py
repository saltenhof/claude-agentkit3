"""Assemble one review bundle from an edge-exported evidence checkpoint.

FK-28 §28.7.1 keeps a human operator-recovery CLI for the evidence assembly, and
FK-91 §91.1a fixes what such a CLI is: an adapter on the Service API, never a
second implementation. Until AG3-241 it was the second implementation -- the
command instantiated :class:`EvidenceAssembler` in the developer-machine process
and wrote a QA artefact there. The assembly is a verify-system act: it decides
which evidence a reviewer sees and stamps the manifest hash the reviewers are
held to. This module is that act on the core side of the boundary.

What crosses the boundary is exactly what the developer machine is the only one
able to observe -- the logical repositories, their changed-file inventory and the
content-bound file snapshot. The physical worktree path deliberately does not:
:class:`RepoContext` needs a repo handle, not a location, and the assembler never
opens it (it reads the snapshot, not the disk). The story working directory is
resolved on the core host, because ``story.md`` and the worker hand-over files
are core-owned story artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit.backend.verify_system.evidence.assembler import EvidenceAssembler
from agentkit.backend.verify_system.evidence.import_resolver import ImportResolver
from agentkit.backend.verify_system.evidence.repo_context import RepoContext
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from agentkit_wire.verify_system import VerifyEvidenceAssemblyRequest

from agentkit_wire.verify_system import VerifyEvidenceAssemblyResponse


@dataclass(frozen=True)
class _CheckpointChangeEvidencePort:
    """Serve the pre-collected change inventory of one evidence checkpoint.

    This runs no git. The assembler calls the port with a repository handle and
    receives the inventory the developer machine reported for it; a repository the
    checkpoint does not mention answers ``available=False`` rather than an empty
    inventory, so "nothing changed" and "nothing was observed" stay distinct.
    """

    changed_files_by_repo: dict[str, tuple[str, ...]]

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Return the reported inventory of the repository handle.

        Args:
            story_dir: The repository handle the assembler passes in -- it uses
                ``RepoContext.repo_path``, which this service sets to the
                ``repo_id`` (no physical path crosses the boundary).

        Returns:
            The reported :class:`ChangeEvidence`, or an unavailable one.
        """
        changed = self.changed_files_by_repo.get(str(story_dir))
        if changed is None:
            return ChangeEvidence(available=False)
        return ChangeEvidence(available=True, changed_files=changed)


def assemble_evidence_bundle(
    request: VerifyEvidenceAssemblyRequest,
    *,
    story_dir: Path,
) -> VerifyEvidenceAssemblyResponse:
    """Assemble the review bundle of one evidence checkpoint.

    Args:
        request: The edge-exported checkpoint: logical repositories with their
            changed-file inventory, and the content-bound file snapshot.
        story_dir: The story working directory ON THE CORE HOST, resolved by the
            caller from canonical level-1 state. It is never a request field:
            ``story.md`` and the worker hand-over files are core-owned artefacts.

    Returns:
        The manifest hash, the merge paths and the canonical manifest document.

    Raises:
        EvidenceAssemblyError: When the checkpoint cannot produce a bundle --
            missing story specification, no affected repository, no entries,
            content/digest mismatch. Fail-closed; the caller maps it to the
            stable HTTP error contract.
        ValueError: When a checkpoint field violates its own model (pydantic
            raises ``ValidationError``, a ``ValueError`` subclass).
    """
    repos = {
        repository.repo_id: RepoContext(
            repo_id=repository.repo_id,
            # The handle, not a location: the assembler passes this value to the
            # change-evidence port and otherwise discards it.
            repo_path=Path(repository.repo_id),
            git_base_branch=repository.git_base_branch,
            role=repository.role,
            affected=repository.affected,
        )
        for repository in request.repositories
    }
    collected_files = tuple(
        VerifyEvidenceFile(
            repo_id=observation.repo_id,
            path=observation.path,
            content=observation.content,
            size=observation.size,
            sha256=observation.sha256,
        )
        for observation in request.collected_files
    )
    change_port = _CheckpointChangeEvidencePort(
        changed_files_by_repo={
            repository.repo_id: repository.changed_files
            for repository in request.repositories
        }
    )
    assembler = EvidenceAssembler(
        repos,
        collected_files=collected_files,
        change_evidence_port=change_port,
        import_evidence_provider=ImportResolver.from_collected_files(collected_files),
    )
    result = assembler.assemble(story_dir=story_dir)
    return VerifyEvidenceAssemblyResponse(
        manifest_hash=result.manifest.manifest_hash,
        merge_paths=tuple(result.merge_paths),
        bundle_manifest_json=result.manifest.model_dump_json(indent=2) + "\n",
    )


__all__ = ["assemble_evidence_bundle"]
