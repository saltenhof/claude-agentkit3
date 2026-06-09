"""RequirementsCoverage top-surface for the requirements-coverage BC."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.artifacts import ArtifactEnvelope, Producer, ProducerId, ProducerType
from agentkit.boundary.filesystem.atomic import atomic_write_json
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.requirements_coverage.contract import (
    AreContext,
    AreDockpointStatus,
    AreEvidence,
    AreRequirement,
    ContextLoadResult,
    CoverageVerdict,
    EvidenceCoverage,
    EvidenceSubmitResult,
    LinkResult,
)
from agentkit.requirements_coverage.errors import (
    AreClientError,
    AreConfigurationError,
    StoryAreLinkConflictError,
    StoryAreLinkNotFoundError,
)
from agentkit.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.requirements_coverage.register import (
    ARE_BUNDLE_STAGE,
    ARE_CONTEXT_LOADER_PRODUCER,
    ARE_GATE_PRODUCER,
    ARE_GATE_STAGE,
)
from agentkit.requirements_coverage.scope_mapping import ScopeMapping

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.config.models import PipelineConfig
    from agentkit.requirements_coverage.are_client import AreClient
    from agentkit.requirements_coverage.repository import StoryAreLinkRepository
    from agentkit.story_context_manager.models import StoryContext

_MSG_CLIENT_MISSING = "features.are=True but AreClient missing"
_GATE_UNAVAILABLE = "are_gate_unavailable"
_PASS_VERDICT = "PASS"
_FAIL_VERDICT = "FAIL"


class StoryContextProvider(Protocol):
    """Read port for resolving story context by story/project."""

    def get_story_context(self, story_id: str, project_key: str) -> StoryContext:
        """Return the authoritative story context."""


class RequirementsCoverage:
    """Top-surface for the requirements-and-scope-coverage BC (FK-40)."""

    def __init__(
        self,
        are_client: AreClient | None,
        pipeline_config: PipelineConfig,
        *,
        link_repository: StoryAreLinkRepository | None = None,
        story_context_provider: StoryContextProvider | None = None,
        artifact_manager: ArtifactManager | None = None,
        scope_mapping: ScopeMapping | None = None,
        audit_root: Path | None = None,
    ) -> None:
        self._are_client = are_client
        self._pipeline_config = pipeline_config
        self._link_repository = link_repository
        self._story_context_provider = story_context_provider
        self._artifact_manager = artifact_manager
        self._scope_mapping = scope_mapping or ScopeMapping()
        self._audit_root = audit_root

    @property
    def is_enabled(self) -> bool:
        """Return ``True`` when ARE is activated by configuration."""

        return self._pipeline_config.features.are is True

    def link_requirements(self, story_id: str, project_key: str) -> LinkResult:
        """Dock-point 1: link recurring and story-specific ARE requirements."""

        if not self.is_enabled:
            return LinkResult(status=AreDockpointStatus.SKIPPED, reason="feature_disabled")
        if self._are_client is None:
            return LinkResult(status=AreDockpointStatus.FAIL, reason=_GATE_UNAVAILABLE)
        client = self._are_client
        repository = self._require_link_repository()
        context_provider = self._require_context_provider()
        context = context_provider.get_story_context(story_id, project_key)
        scope = self._scope_mapping.resolve(context, project_key)

        try:
            recurring = client.get_recurring(scope.scope, scope.story_type)
            story_specific = client.list_requirements(story_id, scope.scope)
        except AreClientError as exc:
            return LinkResult(status=AreDockpointStatus.FAIL, reason=str(exc))

        linked_count = 0
        for requirement in recurring:
            linked_count += self._add_link_idempotent(
                repository,
                story_id=story_id,
                requirement=requirement,
                kind=StoryAreLinkKind.RECURRING,
            )
        for requirement in story_specific:
            linked_count += self._add_link_idempotent(
                repository,
                story_id=story_id,
                requirement=requirement,
                kind=StoryAreLinkKind.ADDRESSES,
            )
        return LinkResult(status=AreDockpointStatus.PASS, linked_count=linked_count)

    def load_context(self, story_id: str, project_key: str, run_id: str) -> ContextLoadResult:
        """Dock-point 2: load and persist the ARE context bundle."""

        if not self.is_enabled:
            return ContextLoadResult(
                status=AreDockpointStatus.SKIPPED,
                are_bundle_ref=None,
                reason="feature_disabled",
            )
        if self._are_client is None:
            return ContextLoadResult(
                status=AreDockpointStatus.FAIL,
                reason=_GATE_UNAVAILABLE,
            )
        client = self._are_client
        try:
            are_context = client.load_context(story_id)
        except AreClientError as exc:
            return ContextLoadResult(status=AreDockpointStatus.FAIL, reason=str(exc))

        requirements = self._requirements_linked_to_story(story_id, are_context)
        bundle = self._bundle_payload(story_id, requirements)
        reference = self._persist_artifact(
            story_id=story_id,
            run_id=run_id,
            stage=ARE_BUNDLE_STAGE,
            producer_name=ARE_CONTEXT_LOADER_PRODUCER,
            status=EnvelopeStatus.PASS,
            payload={
                "filename": "are_bundle.json",
                **bundle,
            },
        )
        return ContextLoadResult(
            status=AreDockpointStatus.PASS,
            are_bundle_ref=reference,
            requirement_count=len(requirements),
        )

    def submit_evidence(self, story_id: str, evidence: AreEvidence) -> EvidenceSubmitResult:
        """Dock-point 3: submit evidence for a linked ARE requirement."""

        if not self.is_enabled:
            return EvidenceSubmitResult(
                status=AreDockpointStatus.SKIPPED,
                reason="feature_disabled",
            )
        if self._are_client is None:
            return EvidenceSubmitResult(
                status=AreDockpointStatus.FAIL,
                reason=_GATE_UNAVAILABLE,
            )
        client = self._are_client
        repository = self._require_link_repository()
        links = repository.list_by_story(story_id)
        if evidence.requirement_id not in {link.are_item_id for link in links}:
            return EvidenceSubmitResult(
                status=AreDockpointStatus.FAIL,
                reason="requirement_not_linked",
            )
        try:
            result = client.submit_evidence(
                story_id,
                evidence.requirement_id,
                evidence.evidence_type,
                evidence.evidence_ref,
            )
        except AreClientError as exc:
            return EvidenceSubmitResult(status=AreDockpointStatus.FAIL, reason=str(exc))

        if result.status is AreDockpointStatus.PASS and evidence.coverage is EvidenceCoverage.PARTIAL:
            self._mark_partial(repository, story_id, evidence.requirement_id)
        return result

    def check_gate(self, story_id: str, project_key: str) -> CoverageVerdict:
        """Dock-point 4: check ARE coverage and write an audit artifact."""

        if not self.is_enabled:
            return CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        if self._are_client is None:
            return self._unavailable_verdict()

        linked_ids = self._linked_requirement_ids(story_id)
        try:
            verdict = self._are_client.check_gate(story_id)
        except AreClientError:
            verdict = self._unavailable_verdict()
        if linked_ids and verdict.uncovered_requirements:
            uncovered = tuple(
                req
                for req in verdict.uncovered_requirements
                if req.requirement_id in linked_ids or _is_stale_requirement(req)
            )
            verdict = verdict.model_copy(update={"uncovered_requirements": uncovered})
        if verdict.status is AreDockpointStatus.PASS and verdict.verdict == _PASS_VERDICT:
            self._persist_gate_audit(story_id, project_key, verdict)
            return verdict
        if verdict.status is AreDockpointStatus.SKIPPED:
            self._persist_gate_audit(story_id, project_key, verdict)
            return verdict
        if verdict.verdict is None:
            verdict = verdict.model_copy(update={"verdict": _FAIL_VERDICT})
        self._persist_gate_audit(story_id, project_key, verdict)
        return verdict

    def _require_client(self) -> AreClient:
        if self._are_client is None:
            raise AreConfigurationError(_MSG_CLIENT_MISSING)
        return self._are_client

    def _require_link_repository(self) -> StoryAreLinkRepository:
        if self._link_repository is None:
            raise AreConfigurationError("StoryAreLinkRepository missing")
        return self._link_repository

    def _require_context_provider(self) -> StoryContextProvider:
        if self._story_context_provider is None:
            raise AreConfigurationError("StoryContextProvider missing")
        return self._story_context_provider

    def _add_link_idempotent(
        self,
        repository: StoryAreLinkRepository,
        *,
        story_id: str,
        requirement: AreRequirement,
        kind: StoryAreLinkKind,
    ) -> int:
        try:
            repository.add(
                StoryAreLink(
                    story_id=story_id,
                    are_item_id=requirement.requirement_id,
                    kind=kind,
                )
            )
        except StoryAreLinkConflictError:
            return 0
        return 1

    def _requirements_linked_to_story(
        self, story_id: str, are_context: AreContext
    ) -> list[AreRequirement]:
        links = self._links_for_story(story_id)
        if not links:
            return list(are_context.requirements)
        linked_ids = {link.are_item_id for link in links}
        return [
            requirement
            for requirement in are_context.requirements
            if requirement.requirement_id in linked_ids
        ]

    def _links_for_story(self, story_id: str) -> list[StoryAreLink]:
        if self._link_repository is None:
            return []
        return self._link_repository.list_by_story(story_id)

    def _linked_requirement_ids(self, story_id: str) -> set[str]:
        return {link.are_item_id for link in self._links_for_story(story_id)}

    def _mark_partial(
        self,
        repository: StoryAreLinkRepository,
        story_id: str,
        requirement_id: str,
    ) -> None:
        try:
            repository.update_kind(
                story_id,
                requirement_id,
                StoryAreLinkKind.ADDRESSES,
                StoryAreLinkKind.PARTIAL,
            )
        except (StoryAreLinkConflictError, StoryAreLinkNotFoundError):
            return

    def _persist_gate_audit(
        self,
        story_id: str,
        project_key: str,
        verdict: CoverageVerdict,
    ) -> None:
        payload: dict[str, object] = {
            "filename": "are_gate.json",
            "schema_version": "1.0",
            "story_id": story_id,
            "project_key": project_key,
            "checked_at": datetime.now(UTC).isoformat(),
            "verdict": verdict.model_dump(mode="json"),
        }
        self._persist_artifact(
            story_id=story_id,
            run_id=f"{project_key}-are-gate",
            stage=ARE_GATE_STAGE,
            producer_name=ARE_GATE_PRODUCER,
            status=EnvelopeStatus.PASS
            if verdict.status is AreDockpointStatus.PASS
            else EnvelopeStatus.FAIL,
            payload=payload,
        )
        if self._audit_root is not None:
            atomic_write_json(
                self._audit_root / "_temp" / "qa" / story_id / "are_gate.json",
                payload,
            )

    def _persist_artifact(
        self,
        *,
        story_id: str,
        run_id: str,
        stage: str,
        producer_name: str,
        status: EnvelopeStatus,
        payload: dict[str, object],
    ) -> str | None:
        if self._artifact_manager is None:
            return None
        now = datetime.now(UTC)
        reference = self._artifact_manager.write(
            ArtifactEnvelope(
                schema_version="3.0",
                story_id=story_id,
                run_id=run_id,
                stage=stage,
                attempt=1,
                producer=Producer(
                    type=ProducerType.DETERMINISTIC,
                    name=producer_name,
                    id=ProducerId(f"{producer_name}:{story_id}"),
                ),
                started_at=now,
                finished_at=now,
                status=status,
                artifact_class=ArtifactClass.QA,
                payload=payload,
            )
        )
        return reference.record_key

    def _bundle_payload(
        self, story_id: str, requirements: list[AreRequirement]
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "story_id": story_id,
            "fetched_at": datetime.now(UTC).isoformat(),
            "must_cover": [
                requirement.model_dump(mode="json")
                for requirement in requirements
                if requirement.must_cover
            ],
        }

    def _unavailable_verdict(self) -> CoverageVerdict:
        return CoverageVerdict(
            status=AreDockpointStatus.FAIL,
            verdict=_FAIL_VERDICT,
            reason=_GATE_UNAVAILABLE,
        )


def _is_stale_requirement(requirement: AreRequirement) -> bool:
    return "stale" in requirement.summary.casefold()


__all__ = ["RequirementsCoverage", "StoryContextProvider"]
