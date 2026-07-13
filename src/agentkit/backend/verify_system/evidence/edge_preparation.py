"""Two-yield verify-evidence preparation over the Edge command queue."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from agentkit.backend.control_plane.edge_commands import verify_evidence_command_id
from agentkit.backend.control_plane.records import EdgeCommandRecord
from agentkit.backend.core_types.verify_evidence import (
    CollectVerifyEvidenceCommandPayload,
    VerifyEvidenceCanonicalRequest,
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
    VerifyEvidenceReport,
    VerifyEvidenceRepository,
    VerifyEvidenceRequest,
    VerifyEvidenceStage,
)
from agentkit.backend.pipeline_engine.phase_executor import VerifyEvidenceWaitCursor
from agentkit.backend.verify_system.evidence.assembler import EvidenceAssembler
from agentkit.backend.verify_system.evidence.authority import AuthorityClass, BundleEntry
from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.backend.verify_system.evidence.import_resolver import ImportResolver
from agentkit.backend.verify_system.evidence.preflight_turn import (
    PREFLIGHT_TEMPLATE_VERSION,
    render_preflight_prompt,
)
from agentkit.backend.verify_system.evidence.repo_context import RepoContext
from agentkit.backend.verify_system.evidence.request_resolver import (
    RequestResolver,
    parse_preflight_response,
)
from agentkit.backend.verify_system.evidence.request_types import (
    RequestResult,
    RequestResultStatus,
    RequestType,
    ReviewerRequest,
    parse_test_command,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.repository import EdgeCommandRepository
    from agentkit.backend.verify_system.evidence.preflight_sender import PreflightReviewSender
    from agentkit.backend.verify_system.structural.system_evidence import (
        ChangeEvidence,
        ChangeEvidencePort,
    )

_OPEN_STATUSES = frozenset({"created", "delivered"})
_REQUEST_TYPES = {
    RequestType.NEED_FILE,
    RequestType.NEED_SCHEMA,
    RequestType.NEED_CALLSITE,
    RequestType.NEED_RUNTIME_BINDING,
    RequestType.NEED_TEST_EVIDENCE,
}
_EdgeRequestType = Literal[
    "NEED_FILE",
    "NEED_SCHEMA",
    "NEED_CALLSITE",
    "NEED_RUNTIME_BINDING",
    "NEED_TEST_EVIDENCE",
]


@dataclass(frozen=True)
class EvidencePreparationInput:
    """Coordinates and immutable candidate description for one phase attempt."""

    project_key: str
    story_id: str
    run_id: str
    implementation_attempt: int
    owner_session_id: str
    ownership_epoch: int
    repositories: tuple[VerifyEvidenceRepository, ...]
    spawn_worktree_repo: str
    story_dir: Path
    repository_paths: dict[str, Path] = field(default_factory=dict)
    worker_hint_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidencePreparationOutcome:
    """Either a persisted wait cursor or a ready bundle."""

    cursor: VerifyEvidenceWaitCursor | None = None
    manifest: BundleManifest | None = None
    request_results: tuple[RequestResult, ...] = ()

    @property
    def waiting(self) -> bool:
        """Return whether the phase must yield and release its claim."""
        return self.cursor is not None


@dataclass(frozen=True)
class _ReportedChangeEvidencePort:
    """Adapt the candidate-bound AG3-147 inventory to the assembler port."""

    repositories: tuple[VerifyEvidenceRepository, ...]

    def collect(self, story_dir: Path) -> ChangeEvidence:
        """Return the checkpointed inventory without touching a worktree."""
        from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

        repo_id = story_dir.as_posix()
        repository = next(
            (item for item in self.repositories if item.repo_id == repo_id), None
        )
        if repository is None:
            return ChangeEvidence(available=False)
        return ChangeEvidence(
            available=repository.change_evidence_available,
            changed_files=repository.changed_paths,
        )


class VerifyEvidencePreparationCoordinator:
    """Advance exactly one non-blocking step of the frozen two-stage protocol."""

    def __init__(
        self,
        *,
        edge_commands: EdgeCommandRepository,
        sender: PreflightReviewSender,
        change_evidence_port: ChangeEvidencePort | None = None,
        now: Callable[[], datetime] | None = None,
        wait_timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self._edge_commands = edge_commands
        self._sender = sender
        self._change_evidence_port = change_evidence_port
        self._now = now or (lambda: datetime.now(UTC))
        self._wait_timeout = wait_timeout

    def advance(
        self,
        inputs: EvidencePreparationInput,
        cursor: VerifyEvidenceWaitCursor | None,
    ) -> EvidencePreparationOutcome:
        """Commission, poll, or apply one checkpoint without sleeping."""
        bound_inputs = self._bind_change_evidence(inputs)
        candidate_digest = _candidate_digest(
            bound_inputs.repositories, bound_inputs.worker_hint_paths
        )
        if not _cursor_matches(cursor, bound_inputs, candidate_digest):
            return self._commission_base(bound_inputs, candidate_digest, cursor)
        assert cursor is not None  # narrowed by _cursor_matches
        record = self._edge_commands.load_command(cursor.command_id)
        if record is None:
            return self._commission_base(bound_inputs, candidate_digest, cursor)
        payload = CollectVerifyEvidenceCommandPayload.model_validate(record.payload)
        if payload.stage is VerifyEvidenceStage.BASE_COLLECTION:
            return self._advance_base(bound_inputs, cursor, record, payload)
        return self._advance_dynamic(bound_inputs, cursor, record, payload)

    def _bind_change_evidence(
        self, inputs: EvidencePreparationInput
    ) -> EvidencePreparationInput:
        """Bind the sanctioned AG3-147 inventory before edge collection."""
        if self._change_evidence_port is None:
            return replace(
                inputs,
                worker_hint_paths=_worker_hints(inputs),
            )
        contexts = {
            repository.repo_id: RepoContext(
                repo_id=repository.repo_id,
                repo_path=inputs.repository_paths.get(
                    repository.repo_id, Path(repository.repo_id)
                ),
                affected=repository.affected,
            )
            for repository in inputs.repositories
        }
        inventory = EvidenceAssembler.collect_change_inventory(
            contexts, self._change_evidence_port
        )
        repositories: list[VerifyEvidenceRepository] = []
        for repository in inputs.repositories:
            evidence = inventory.get(repository.repo_id)
            if evidence is None:
                repositories.append(repository)
                continue
            repositories.append(
                repository.model_copy(
                    update={
                        "change_evidence_available": evidence.available,
                        "changed_paths": evidence.changed_files if evidence.available else (),
                    }
                )
            )
        return replace(
            inputs,
            repositories=tuple(repositories),
            worker_hint_paths=_worker_hints(inputs),
        )

    def _commission_base(
        self,
        inputs: EvidencePreparationInput,
        candidate_digest: str,
        old_cursor: VerifyEvidenceWaitCursor | None,
    ) -> EvidencePreparationOutcome:
        payload = _payload(
            inputs,
            stage=VerifyEvidenceStage.BASE_COLLECTION,
            candidate_digest=candidate_digest,
            request_digest=_digest([]),
            generation_seed=f"{inputs.owner_session_id}:{inputs.ownership_epoch}:base",
            deadline_at=self._now() + self._wait_timeout,
        )
        record = _command_record(inputs, payload)
        self._edge_commands.reconcile_verify_evidence_generation(
            record=record,
            obsolete_command_id=old_cursor.command_id if old_cursor else None,
            completed_at=self._now(),
            result_payload={"reason": "verify_evidence_generation_drift"},
            expected_ownership_epoch=inputs.ownership_epoch,
        )
        return _waiting(inputs, payload, record.command_id)

    def _advance_base(
        self,
        inputs: EvidencePreparationInput,
        cursor: VerifyEvidenceWaitCursor,
        record: EdgeCommandRecord,
        payload: CollectVerifyEvidenceCommandPayload,
    ) -> EvidencePreparationOutcome:
        report: VerifyEvidenceReport | None
        if record.status in _OPEN_STATUSES:
            if self._now() < payload.deadline_at:
                return EvidencePreparationOutcome(cursor=cursor)
            self._timeout(inputs, record.command_id, payload)
            report = None
        elif record.status == "completed":
            report = VerifyEvidenceReport.model_validate(record.result_payload)
        else:
            report = None
        files = report.files if report is not None else ()
        repos = {
            item.repo_id: RepoContext(repo_id=item.repo_id, repo_path=Path(item.repo_id))
            for item in inputs.repositories
        }
        assembly = EvidenceAssembler(
            repos,
            collected_files=files,
            change_evidence_port=_ReportedChangeEvidencePort(payload.repositories),
            import_evidence_provider=ImportResolver.from_collected_files(files),
            collection_finding=(
                report.finding_code
                if report is not None and report.finding_code is not None
                else (
                    None
                    if report is not None
                    else "EDGE_EVIDENCE_TIMEOUT: base collection"
                )
            ),
        ).assemble(story_dir=inputs.story_dir, evidence_epoch=self._now())
        return self._checkpoint_preflight(inputs, payload.candidate_digest, assembly.manifest)

    def _checkpoint_preflight(
        self,
        inputs: EvidencePreparationInput,
        candidate_digest: str,
        manifest: BundleManifest,
    ) -> EvidencePreparationOutcome:
        prompt = render_preflight_prompt(manifest.render_prompt_header(), inputs.story_id)
        prompt = f"{prompt}\n\n{_render_manifest_content(manifest)}"
        request_hash = _digest(prompt)
        attempt_id = f"preflight:{uuid4().hex}"
        started = _payload(
            inputs,
            stage=VerifyEvidenceStage.DYNAMIC_REQUESTS,
            candidate_digest=candidate_digest,
            request_digest=_digest([]),
            generation_seed=f"{attempt_id}:started",
            deadline_at=self._now(),
            preflight_attempt_id=attempt_id,
            preflight_checkpoint_state="started",
            preflight_request_hash=request_hash,
        )
        self._edge_commands.reconcile_verify_evidence_generation(
            record=_command_record(inputs, started, terminal_audit=True),
            obsolete_command_id=None,
            completed_at=self._now(),
            result_payload={"reason": "preflight_attempt_started"},
            expected_ownership_epoch=inputs.ownership_epoch,
        )
        raw = self._sender.send(
            prompt=prompt,
            merge_paths=tuple(Path(path) for path in manifest.file_paths),
            attempt_id=attempt_id,
            request_hash=request_hash,
        )
        requests = tuple(parse_preflight_response(raw))
        edge_requests, _ = _edge_requests(requests, manifest)
        request_digest = _request_digest(requests)
        ready = _payload(
            inputs,
            stage=VerifyEvidenceStage.DYNAMIC_REQUESTS,
            candidate_digest=candidate_digest,
            request_digest=request_digest,
            generation_seed=f"{attempt_id}:ready",
            deadline_at=self._now() + self._wait_timeout,
            requests=edge_requests,
            preflight_requests=tuple(_checkpoint_request(item) for item in requests),
            preflight_attempt_id=attempt_id,
            preflight_checkpoint_state="ready",
            preflight_request_hash=request_hash,
            raw_preflight_response=raw,
            base_manifest=manifest.model_dump(mode="json"),
        )
        record = _command_record(inputs, ready)
        self._edge_commands.reconcile_verify_evidence_generation(
            record=record,
            obsolete_command_id=None,
            completed_at=self._now(),
            result_payload={"reason": "preflight_checkpoint_ready"},
            expected_ownership_epoch=inputs.ownership_epoch,
        )
        return _waiting(inputs, ready, record.command_id)

    def _advance_dynamic(
        self,
        inputs: EvidencePreparationInput,
        cursor: VerifyEvidenceWaitCursor,
        record: EdgeCommandRecord,
        payload: CollectVerifyEvidenceCommandPayload,
    ) -> EvidencePreparationOutcome:
        requests = tuple(
            ReviewerRequest(
                type=RequestType(item.request_type),
                target=item.target,
                region=item.region,
                reason=item.reason,
            )
            for item in payload.preflight_requests
        )
        base_manifest = BundleManifest.model_validate(payload.base_manifest)
        local_observations = _edge_requests(requests, base_manifest)[1]
        observations: tuple[VerifyEvidenceObservation, ...]
        if record.status in _OPEN_STATUSES:
            if self._now() < payload.deadline_at:
                return EvidencePreparationOutcome(cursor=cursor)
            self._timeout(inputs, record.command_id, payload)
            observations = tuple(
                VerifyEvidenceObservation(
                    request_index=index,
                    status=VerifyEvidenceObservationStatus.TIMEOUT,
                    finding_code="EDGE_EVIDENCE_TIMEOUT",
                )
                for index, request in enumerate(requests)
                if request.type in _REQUEST_TYPES
            )
        elif record.status == "completed":
            observations = VerifyEvidenceReport.model_validate(
                record.result_payload
            ).observations
        else:
            observations = ()
        all_observations = (*observations, *local_observations)
        results = tuple(
            RequestResolver(story_dir=inputs.story_dir).resolve_all(
                requests, all_observations
            )
        )
        return EvidencePreparationOutcome(
            manifest=_extend_manifest(base_manifest, results, all_observations),
            request_results=results,
        )

    def _timeout(
        self,
        inputs: EvidencePreparationInput,
        command_id: str,
        payload: CollectVerifyEvidenceCommandPayload,
    ) -> None:
        self._edge_commands.supersede_verify_evidence(
            command_id=command_id,
            project_key=inputs.project_key,
            story_id=inputs.story_id,
            run_id=inputs.run_id,
            session_id=inputs.owner_session_id,
            completed_at=self._now(),
            result_payload={"reason": "verify_evidence_deadline_elapsed", "batch_id": payload.batch_id},
            expected_ownership_epoch=inputs.ownership_epoch,
        )


def _payload(
    inputs: EvidencePreparationInput,
    *,
    stage: VerifyEvidenceStage,
    candidate_digest: str,
    request_digest: str,
    generation_seed: str,
    deadline_at: datetime,
    requests: tuple[VerifyEvidenceRequest, ...] = (),
    preflight_requests: tuple[VerifyEvidenceCanonicalRequest, ...] = (),
    preflight_attempt_id: str | None = None,
    preflight_checkpoint_state: Literal["started", "ready"] | None = None,
    preflight_request_hash: str | None = None,
    raw_preflight_response: str | None = None,
    base_manifest: dict[str, object] | None = None,
) -> CollectVerifyEvidenceCommandPayload:
    batch_id = _digest(
        [
            inputs.run_id,
            inputs.implementation_attempt,
            candidate_digest,
            stage.value,
            PREFLIGHT_TEMPLATE_VERSION,
        ]
    )
    generation = _digest([batch_id, generation_seed])
    return CollectVerifyEvidenceCommandPayload(
        stage=stage,
        story_id=inputs.story_id,
        project_key=inputs.project_key,
        run_id=inputs.run_id,
        implementation_attempt=inputs.implementation_attempt,
        batch_id=batch_id,
        generation=generation,
        candidate_digest=candidate_digest,
        request_digest=request_digest,
        preflight_template_version=PREFLIGHT_TEMPLATE_VERSION,
        deadline_at=deadline_at,
        repositories=inputs.repositories,
        spawn_worktree_repo=inputs.spawn_worktree_repo,
        worker_hint_paths=inputs.worker_hint_paths,
        requests=requests,
        preflight_requests=preflight_requests,
        preflight_attempt_id=preflight_attempt_id,
        preflight_checkpoint_state=preflight_checkpoint_state,
        preflight_request_hash=preflight_request_hash,
        raw_preflight_response=raw_preflight_response,
        base_manifest=base_manifest,
    )


def _command_record(
    inputs: EvidencePreparationInput,
    payload: CollectVerifyEvidenceCommandPayload,
    *,
    terminal_audit: bool = False,
) -> EdgeCommandRecord:
    now = datetime.now(UTC)
    return EdgeCommandRecord(
        command_id=verify_evidence_command_id(
            inputs.run_id, stage=payload.stage.value, generation=payload.generation
        ),
        project_key=inputs.project_key,
        story_id=inputs.story_id,
        run_id=inputs.run_id,
        session_id=inputs.owner_session_id,
        command_kind="collect_verify_evidence",
        payload=payload.model_dump(mode="json"),
        status="superseded" if terminal_audit else "created",
        ownership_epoch=inputs.ownership_epoch,
        created_at=now,
        completed_at=now if terminal_audit else None,
        result_type="command_superseded" if terminal_audit else None,
        result_payload={"reason": "preflight_attempt_started"} if terminal_audit else None,
    )


def _waiting(
    inputs: EvidencePreparationInput,
    payload: CollectVerifyEvidenceCommandPayload,
    command_id: str,
) -> EvidencePreparationOutcome:
    return EvidencePreparationOutcome(
        cursor=VerifyEvidenceWaitCursor(
            stage=payload.stage.value,
            command_id=command_id,
            candidate_digest=payload.candidate_digest,
            implementation_attempt=inputs.implementation_attempt,
            owner_session_id=inputs.owner_session_id,
            ownership_epoch=inputs.ownership_epoch,
        )
    )


def _cursor_matches(
    cursor: VerifyEvidenceWaitCursor | None,
    inputs: EvidencePreparationInput,
    candidate_digest: str,
) -> bool:
    return cursor is not None and (
        cursor.candidate_digest == candidate_digest
        and cursor.implementation_attempt == inputs.implementation_attempt
        and cursor.owner_session_id == inputs.owner_session_id
        and cursor.ownership_epoch == inputs.ownership_epoch
    )


def _candidate_digest(
    repositories: tuple[VerifyEvidenceRepository, ...],
    worker_hint_paths: tuple[str, ...],
) -> str:
    return _digest(
        {
            "repositories": [
                item.model_dump(mode="json")
                for item in sorted(repositories, key=lambda item: item.repo_id)
            ],
            "worker_hint_paths": worker_hint_paths,
        }
    )


def _worker_hints(inputs: EvidencePreparationInput) -> tuple[str, ...]:
    discovered = EvidenceAssembler.collect_worker_hint_paths(inputs.story_dir)
    return tuple(sorted({*inputs.worker_hint_paths, *discovered}))


def _request_digest(requests: tuple[ReviewerRequest, ...]) -> str:
    return _digest([item.model_dump(mode="json") for item in requests])


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _edge_requests(
    requests: tuple[ReviewerRequest, ...],
    manifest: BundleManifest | None = None,
) -> tuple[tuple[VerifyEvidenceRequest, ...], tuple[VerifyEvidenceObservation, ...]]:
    edge: list[VerifyEvidenceRequest] = []
    local: list[VerifyEvidenceObservation] = []
    for index, request in enumerate(requests):
        if request.type is RequestType.NEED_DIFF_EXPANSION:
            local.append(_diff_expansion_observation(index, request, manifest))
            continue
        if request.type not in _REQUEST_TYPES:
            continue
        test_command = None
        if request.type is RequestType.NEED_TEST_EVIDENCE:
            try:
                test_command = parse_test_command(request.target)
            except ValueError as exc:
                local.append(
                    VerifyEvidenceObservation(
                        request_index=index,
                        status=VerifyEvidenceObservationStatus.REJECTED,
                        content=str(exc),
                        finding_code="TEST_COMMAND_REJECTED",
                    )
                )
                continue
        edge.append(
            VerifyEvidenceRequest(
                request_index=index,
                request_type=cast("_EdgeRequestType", request.type.value),
                target=request.target,
                region=request.region,
                test_command=test_command,
            )
        )
    return tuple(edge), tuple(local)


def _diff_expansion_observation(
    index: int,
    request: ReviewerRequest,
    manifest: BundleManifest | None,
) -> VerifyEvidenceObservation:
    """Resolve AG3-147 content already present in the Stage-A snapshot."""
    candidates: list[VerifyEvidenceFile] = []
    if manifest is not None:
        for entry in manifest.entries:
            if entry.repo_id.startswith("_") or entry.path.as_posix() != request.target:
                continue
            content = _extract_region(entry.content, request.region) or entry.content
            candidates.append(
                VerifyEvidenceFile.from_content(
                    repo_id=entry.repo_id,
                    path=entry.path.as_posix(),
                    content=content,
                )
            )
    return VerifyEvidenceObservation(
        request_index=index,
        status=(
            VerifyEvidenceObservationStatus.COLLECTED
            if candidates
            else VerifyEvidenceObservationStatus.UNRESOLVED
        ),
        candidates=tuple(candidates),
        finding_code=None if candidates else "DIFF_EXPANSION_UNAVAILABLE",
    )


def _extract_region(content: str, region: str | None) -> str | None:
    if not region:
        return None
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if region in line:
            return "\n".join(lines[max(0, index - 30) : index + 31])
    return None


def _checkpoint_request(request: ReviewerRequest) -> VerifyEvidenceCanonicalRequest:
    """Convert one parsed request to its wire-stable checkpoint form."""
    return VerifyEvidenceCanonicalRequest(
        request_type=request.type.value,
        target=request.target,
        region=request.region,
        reason=request.reason,
    )


def _extend_manifest(
    manifest: BundleManifest,
    results: tuple[RequestResult, ...],
    observations: tuple[VerifyEvidenceObservation, ...],
) -> BundleManifest:
    entries = list(manifest.entries)
    by_index = {item.request_index: item for item in observations}
    warnings = list(manifest.warnings)
    for index, result in enumerate(results):
        warnings.append(
            f"PREFLIGHT_{result.status.value}: {result.request.type.value} {result.request.target}"
        )
        observation = by_index.get(index)
        if (
            result.status is RequestResultStatus.RESOLVED
            and observation is not None
            and len(observation.candidates) == 1
        ):
            candidate = observation.candidates[0]
            entries.append(
                BundleEntry(
                    repo_id=candidate.repo_id,
                    path=Path(candidate.path),
                    authority=AuthorityClass.SECONDARY_CONTEXT,
                    confidence="EXACT",
                    reason=f"Resolved reviewer request {result.request.type.value}",
                    size=candidate.size,
                    content=candidate.content,
                )
            )
        elif (
            result.status is RequestResultStatus.RESOLVED
            and observation is not None
            and observation.content is not None
        ):
            entries.append(
                BundleEntry(
                    repo_id="_edge",
                    path=Path(f"verify-evidence/request-{index}.txt"),
                    authority=AuthorityClass.SECONDARY_CONTEXT,
                    confidence="EXACT",
                    reason=f"Collected reviewer request {result.request.type.value}",
                    size=len(observation.content.encode("utf-8")),
                    content=observation.content,
                )
            )
    deduplicated: dict[tuple[str, str], BundleEntry] = {}
    for item in entries:
        key = (item.repo_id, item.path.as_posix())
        current = deduplicated.get(key)
        if current is None:
            deduplicated[key] = item
            continue
        if item.content != current.content:
            warnings.append(
                f"EDGE_EVIDENCE_CONFLICT: conflicting content ignored for {item.repo_id}:{item.path.as_posix()}"
            )
            continue
        if item.authority > current.authority:
            deduplicated[key] = item
    return BundleManifest.from_entries(
        list(deduplicated.values()),
        truncated=manifest.truncated,
        warnings=warnings,
        evidence_epoch=manifest.evidence_epoch,
    )


def _render_manifest_content(manifest: BundleManifest) -> str:
    """Render bounded edge-collected content into the backend LLM request."""
    parts = ["## Edge-collected evidence content"]
    for entry in manifest.entries:
        parts.extend(
            [
                f"### {entry.repo_id}:{entry.path.as_posix()}",
                "```text",
                entry.content,
                "```",
            ]
        )
    return "\n".join(parts)


__all__ = [
    "EvidencePreparationInput",
    "EvidencePreparationOutcome",
    "VerifyEvidencePreparationCoordinator",
]
