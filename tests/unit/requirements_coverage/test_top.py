"""Unit tests for RequirementsCoverage top-surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.artifacts import ArtifactReference
from agentkit.backend.config.models import SUPPORTED_CONFIG_VERSION, Features, PipelineConfig
from agentkit.backend.core_types import StoryMode
from agentkit.backend.requirements_coverage.contract import (
    AreContext,
    AreDockpointStatus,
    AreEvidence,
    AreRequirement,
    AreRequirementType,
    CoverageVerdict,
    EvidenceCoverage,
    EvidenceProducer,
    EvidenceSubmitResult,
    EvidenceType,
)
from agentkit.backend.requirements_coverage.errors import StoryAreLinkConflictError
from agentkit.backend.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.backend.requirements_coverage.scope_mapping import ScopeMapping
from agentkit.backend.requirements_coverage.top import RequirementsCoverage
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryType


def _config(are_enabled: bool) -> PipelineConfig:
    return PipelineConfig(  # type: ignore[call-arg]
        config_version=SUPPORTED_CONFIG_VERSION,
        features=Features(are=are_enabled, multi_llm=False),
    )


def _requirement(requirement_id: str, *, recurring: bool = False) -> AreRequirement:
    return AreRequirement(
        requirement_id=requirement_id,
        requirement_type=AreRequirementType.SYSTEM,
        summary=f"{requirement_id} summary",
        description=None,
        must_cover=True,
        acceptance_criteria=[],
        recurring=recurring,
    )


def _evidence(
    requirement_id: str = "REQ-1",
    *,
    coverage: EvidenceCoverage = EvidenceCoverage.FULL,
) -> AreEvidence:
    return AreEvidence(
        requirement_id=requirement_id,
        evidence_type=EvidenceType.TEST_REPORT,
        evidence_ref="tests/test_x.py::test_y",
        produced_by=EvidenceProducer.WORKER,
        coverage=coverage,
    )


class FakeRepo:
    def __init__(self, links: list[StoryAreLink] | None = None) -> None:
        self.links = links or []
        self.add_calls: list[StoryAreLink] = []
        self.update_calls: list[tuple[str, str, StoryAreLinkKind, StoryAreLinkKind]] = []
        self.remove_calls: list[tuple[str, str, StoryAreLinkKind]] = []
        self.list_calls = 0

    def add(self, link: StoryAreLink) -> None:
        self.add_calls.append(link)
        if any(
            existing.story_id == link.story_id
            and existing.are_item_id == link.are_item_id
            and existing.kind is link.kind
            for existing in self.links
        ):
            raise StoryAreLinkConflictError("duplicate")
        self.links.append(link)

    def update_kind(
        self,
        story_id: str,
        are_item_id: str,
        old_kind: StoryAreLinkKind,
        new_kind: StoryAreLinkKind,
    ) -> StoryAreLink:
        self.update_calls.append((story_id, are_item_id, old_kind, new_kind))
        for index, link in enumerate(self.links):
            if (
                link.story_id == story_id
                and link.are_item_id == are_item_id
                and link.kind is old_kind
            ):
                updated = StoryAreLink(
                    story_id=story_id,
                    are_item_id=are_item_id,
                    kind=new_kind,
                )
                self.links[index] = updated
                return updated
        raise AssertionError("old link not found")

    def remove(
        self,
        story_id: str,
        are_item_id: str,
        kind: StoryAreLinkKind,
    ) -> None:
        self.remove_calls.append((story_id, are_item_id, kind))

    def list_by_story(self, story_id: str) -> list[StoryAreLink]:
        self.list_calls += 1
        return [link for link in self.links if link.story_id == story_id]


class FakeContextProvider:
    def get_story_context(self, story_id: str, project_key: str) -> StoryContext:
        return StoryContext(
            project_key=project_key,
            story_id=story_id,
            story_number=77,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            participating_repos=["backend"],
        )


class FakeArtifactManager:
    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    def write(self, envelope: Any) -> ArtifactReference:
        self.envelopes.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"{envelope.stage}:{envelope.producer.name}",
        )


class FakeClient:
    def __init__(self) -> None:
        self.evidence_calls: list[tuple[str, str, EvidenceType, str]] = []
        self.gate = CoverageVerdict(status=AreDockpointStatus.PASS, verdict="PASS")

    def get_recurring(self, scope: str, story_type: str) -> list[AreRequirement]:
        assert scope == "backend"
        assert story_type == "implementation"
        return [_requirement("REQ-R", recurring=True)]

    def list_requirements(self, story_id: str, scope: str) -> list[AreRequirement]:
        assert story_id == "AG3-077"
        assert scope == "backend"
        return [_requirement("REQ-S")]

    def load_context(self, story_id: str) -> AreContext:
        assert story_id == "AG3-077"
        return AreContext(
            requirements=[_requirement("REQ-1"), _requirement("REQ-OTHER")],
            loaded_at=datetime.now(UTC),
        )

    def submit_evidence(
        self,
        story_id: str,
        requirement_id: str,
        evidence_type: EvidenceType,
        evidence_ref: str,
    ) -> EvidenceSubmitResult:
        self.evidence_calls.append(
            (story_id, requirement_id, evidence_type, evidence_ref)
        )
        return EvidenceSubmitResult(status=AreDockpointStatus.PASS)

    def check_gate(self, story_id: str) -> CoverageVerdict:
        assert story_id == "AG3-077"
        return self.gate


def test_disabled_paths_skip_without_writes() -> None:
    repo = FakeRepo()
    coverage = RequirementsCoverage(None, _config(False), link_repository=repo)

    assert coverage.link_requirements("AG3-077", "ak3").status is AreDockpointStatus.SKIPPED
    assert coverage.load_context("AG3-077", "run").status is AreDockpointStatus.SKIPPED
    assert coverage.submit_evidence("AG3-077", _evidence()).status is AreDockpointStatus.SKIPPED
    assert coverage.check_gate("AG3-077", "ak3").status is AreDockpointStatus.SKIPPED
    assert repo.add_calls == []
    assert repo.update_calls == []


def test_link_requirements_inserts_recurring_and_addresses_idempotently() -> None:
    repo = FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-R", kind=StoryAreLinkKind.RECURRING)])
    coverage = RequirementsCoverage(
        FakeClient(),  # type: ignore[arg-type]
        _config(True),
        link_repository=repo,
        story_context_provider=FakeContextProvider(),
    )

    result = coverage.link_requirements("AG3-077", "ak3")

    assert result.status is AreDockpointStatus.PASS
    assert result.linked_count == 1
    assert StoryAreLink(
        story_id="AG3-077",
        are_item_id="REQ-S",
        kind=StoryAreLinkKind.ADDRESSES,
    ) in repo.links


def test_scope_mapping_uses_participating_repos_then_project_key() -> None:
    context = FakeContextProvider().get_story_context("AG3-077", "ak3")
    resolved = ScopeMapping().resolve(context, "ak3")
    assert resolved.scope == "backend"
    assert resolved.story_type == "implementation"

    fallback = context.model_copy(update={"participating_repos": []})
    assert ScopeMapping().resolve(fallback, "ak3").scope == "ak3"


def test_load_context_persists_bundle_via_artifact_manager_and_reads_links() -> None:
    repo = FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-1", kind=StoryAreLinkKind.ADDRESSES)])
    artifacts = FakeArtifactManager()
    coverage = RequirementsCoverage(
        FakeClient(),  # type: ignore[arg-type]
        _config(True),
        link_repository=repo,
        artifact_manager=artifacts,  # type: ignore[arg-type]
    )

    result = coverage.load_context("AG3-077", "run-1")

    assert result.status is AreDockpointStatus.PASS
    assert result.requirement_count == 1
    assert repo.list_calls == 1
    envelope = artifacts.envelopes[0]
    assert envelope.artifact_class.value == "qa"
    assert envelope.producer.name == "qa-are-context-loader"
    assert envelope.payload["filename"] == "are_bundle.json"
    assert [item["requirement_id"] for item in envelope.payload["must_cover"]] == ["REQ-1"]


def test_submit_evidence_rejects_unlinked_requirement() -> None:
    client = FakeClient()
    coverage = RequirementsCoverage(
        client,  # type: ignore[arg-type]
        _config(True),
        link_repository=FakeRepo(),
    )

    result = coverage.submit_evidence("AG3-077", _evidence("REQ-X"))

    assert result.status is AreDockpointStatus.FAIL
    assert result.reason == "requirement_not_linked"
    assert client.evidence_calls == []


def test_submit_evidence_partial_updates_addresses_to_partial() -> None:
    repo = FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-1", kind=StoryAreLinkKind.ADDRESSES)])
    coverage = RequirementsCoverage(
        FakeClient(),  # type: ignore[arg-type]
        _config(True),
        link_repository=repo,
    )

    result = coverage.submit_evidence(
        "AG3-077",
        _evidence(coverage=EvidenceCoverage.PARTIAL),
    )

    assert result.status is AreDockpointStatus.PASS
    assert repo.update_calls == [
        ("AG3-077", "REQ-1", StoryAreLinkKind.ADDRESSES, StoryAreLinkKind.PARTIAL)
    ]


def test_submit_evidence_full_leaves_kind_unchanged() -> None:
    repo = FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-1", kind=StoryAreLinkKind.ADDRESSES)])
    coverage = RequirementsCoverage(
        FakeClient(),  # type: ignore[arg-type]
        _config(True),
        link_repository=repo,
    )

    result = coverage.submit_evidence("AG3-077", _evidence())

    assert result.status is AreDockpointStatus.PASS
    assert repo.update_calls == []


def test_check_gate_pass_fail_unavailable_and_audit_write(tmp_path: Path) -> None:
    artifacts = FakeArtifactManager()
    client = FakeClient()
    client.gate = CoverageVerdict(
        status=AreDockpointStatus.FAIL,
        verdict="FAIL",
        uncovered_requirements=(_requirement("REQ-1"),),
    )
    coverage = RequirementsCoverage(
        client,  # type: ignore[arg-type]
        _config(True),
        link_repository=FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-1", kind=StoryAreLinkKind.ADDRESSES)]),
        artifact_manager=artifacts,  # type: ignore[arg-type]
        audit_root=tmp_path,
    )

    verdict = coverage.check_gate("AG3-077", "ak3")

    assert verdict.status is AreDockpointStatus.FAIL
    assert [req.requirement_id for req in verdict.uncovered_requirements] == ["REQ-1"]
    assert artifacts.envelopes[0].producer.name == "qa-are-gate"
    assert artifacts.envelopes[0].payload["filename"] == "are_gate.json"
    assert (tmp_path / "_temp" / "qa" / "AG3-077" / "are_gate.json").exists()

    unavailable = RequirementsCoverage(None, _config(True)).check_gate("AG3-077", "ak3")
    assert unavailable.status is AreDockpointStatus.FAIL
    assert unavailable.reason == "are_gate_unavailable"


def test_load_and_check_are_read_only_for_story_are_link() -> None:
    repo = FakeRepo([StoryAreLink(story_id="AG3-077", are_item_id="REQ-1", kind=StoryAreLinkKind.ADDRESSES)])
    coverage = RequirementsCoverage(
        FakeClient(),  # type: ignore[arg-type]
        _config(True),
        link_repository=repo,
    )

    coverage.load_context("AG3-077", "run-1")
    coverage.check_gate("AG3-077", "ak3")

    assert repo.add_calls == []
    assert repo.update_calls == []
    assert repo.remove_calls == []
