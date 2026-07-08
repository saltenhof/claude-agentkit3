"""Concrete edge-provisioning coordinator adapter (AG3-145 sub-step C).

FK-10 §10.2.4a moves physical worktree operations onto the Project Edge. This
adapter is the composition-root wiring of
:class:`~agentkit.backend.governance.setup_preflight_gate.edge_provisioning.EdgeProvisioningCoordinator`:
it commissions ``preflight_probe`` / ``provision_worktree`` commands (via the
Postgres-only ``EdgeCommandRepository`` insert -- the A command-create surface)
with a DETERMINISTIC ``command_id`` (idempotent re-entry) and reads back the
reported results. The preflight decision context reads the active
``run_ownership_records`` row (session/epoch + own-session ownership), the
per-repo ``takeover_transfer_records.takeover_base_sha`` and the remote
story-branch head SHA via the provider-neutral ``git ls-remote`` ref-read
(AG3-146, FK-10 §10.2.4a(b): a network-protocol read, never a worktree git
subprocess). Postgres-only (K5): off Postgres the repository globals fail closed
with ``ConfigError`` on first use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    StoryRefWriteCredentialClass,
)
from agentkit.backend.control_plane.edge_commands import (
    OPEN_COMMAND_STATUSES,
    PreflightOwnershipContext,
    PreflightProbeEvidence,
    edge_command_id,
)
from agentkit.backend.control_plane.models import (
    PreflightProbeCommandPayload,
    PreflightProbeReport,
    ProvisionWorktreeCommandPayload,
    TeardownWorktreeCommandPayload,
    WorktreeReport,
)
from agentkit.backend.control_plane.push_sync import (
    assess_ref_protection_capability,
    authorize_story_ref_write,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.governance.setup_preflight_gate.edge_provisioning import (
    ProbeOutcome,
    ProvisioningOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.code_backend.provider_port import CodeBackendPort
    from agentkit.backend.control_plane.repository import (
        EdgeCommandRepository,
        RunOwnershipRepository,
        TakeoverTransferRepository,
    )

__all__ = [
    "SetupEdgeProvisioningCoordinator",
    "build_setup_edge_provisioning_coordinator",
    "commission_teardown_worktree",
]


def commission_teardown_worktree(
    edge_commands: EdgeCommandRepository,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    session_id: str,
    ownership_epoch: int,
    repos: tuple[str, ...],
    branch: str,
) -> None:
    """Commission a ``teardown_worktree`` edge command per repo (FK-91 §91.1b).

    The single truth for physical worktree teardown after AG3-145 sub-step D:
    the backend commissions, the Project Edge tears down dev-locally and reports
    (FK-10 §10.4.2). ATOMICALLY idempotent by the deterministic ``command_id``:
    the commission is an ``INSERT ... ON CONFLICT DO NOTHING`` (``commission_command``),
    so a CONCURRENT double-detach (a re-entered setup-failure cleanup or a double
    reset) is one visible command / no error, never a primary-key violation
    (FK-10 §10.5.3). Fire-and-forget: the caller does NOT block on the physical
    removal; the open command stays auditably visible (SOLL-165 / Rule 16).

    Args:
        edge_commands: The Edge-Command-Queue persistence port (commission).
        project_key: Owning project key.
        story_id: The story whose worktree(s) are torn down.
        run_id: The authoritative run id (scopes the deterministic command id).
        session_id: The owning session the command is scoped to.
        ownership_epoch: The active record's epoch stamped at commission time.
        repos: The participating repos to tear down (one command each).
        branch: The story branch name (``story/{id}``, deleted best-effort).
    """
    now = datetime.now(tz=UTC)
    for repo in repos:
        edge_commands.commission_command(
            EdgeCommandRecord(
                command_id=edge_command_id(run_id, "teardown_worktree", repo),
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                session_id=session_id,
                command_kind="teardown_worktree",
                payload=TeardownWorktreeCommandPayload(
                    story_id=story_id, repo_id=repo, branch=branch
                ).model_dump(mode="json"),
                status="created",
                ownership_epoch=ownership_epoch,
                created_at=now,
            )
        )


@dataclass(frozen=True)
class SetupEdgeProvisioningCoordinator:
    """Postgres-backed edge-provisioning coordinator (FK-91 §91.1b).

    Attributes:
        edge_commands: The Edge-Command-Queue persistence port (commission +
            read).
        ownership_repo: The run-ownership port (session/epoch + own-session).
        transfer_repo: The takeover-transfer port (per-repo ``takeover_base_sha``).
        remote_head_reader: ``(repo_id, branch) -> remote head SHA | None`` over
            the provider-neutral ``git ls-remote`` ref-read (AG3-146).
    """

    edge_commands: EdgeCommandRepository
    ownership_repo: RunOwnershipRepository
    transfer_repo: TakeoverTransferRepository
    remote_head_reader: Callable[[str, str], str | None]
    code_backend_port: Callable[[str], CodeBackendPort]

    def ensure_preflight_probes(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
    ) -> ProbeOutcome:
        """Commission (if absent) and read the ``preflight_probe`` commands."""
        session_id, epoch = self._active_session_epoch(project_key, story_id, run_id)
        self._ensure_ref_protection(
            project_key=project_key,
            story_id=story_id,
            session_id=session_id,
            ownership_epoch=epoch,
            repos=repos,
            ref_pattern="story/*",
        )
        payloads = {
            repo: PreflightProbeCommandPayload(
                story_id=story_id, repo_id=repo, branch=branch
            ).model_dump(mode="json")
            for repo in repos
        }
        pending, records = self._commission_and_load(
            "preflight_probe",
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            session_id=session_id,
            epoch=epoch,
            repos=repos,
            payloads=payloads,
        )
        if pending:
            return ProbeOutcome(pending=True)
        evidence: dict[str, PreflightProbeEvidence | None] = {
            repo: self._probe_evidence(
                records[repo],
                repo,
                branch,
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                epoch=epoch,
            )
            for repo in repos
        }
        return ProbeOutcome(
            pending=False,
            evidence=evidence,
            ownership=PreflightOwnershipContext(own_session_active_ownership=True),
        )

    def ensure_provisioning(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
        base_ref: str,
    ) -> ProvisioningOutcome:
        """Commission (if absent) and read the ``provision_worktree`` commands."""
        session_id, epoch = self._active_session_epoch(project_key, story_id, run_id)
        payloads = {
            repo: ProvisionWorktreeCommandPayload(
                story_id=story_id,
                project_key=project_key,
                run_id=run_id,
                repo_id=repo,
                branch=branch,
                base_ref=base_ref,
            ).model_dump(mode="json")
            for repo in repos
        }
        pending, records = self._commission_and_load(
            "provision_worktree",
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            session_id=session_id,
            epoch=epoch,
            repos=repos,
            payloads=payloads,
        )
        if pending:
            return ProvisioningOutcome(pending=True)
        worktree_map: dict[str, Path] = {}
        failed: list[str] = []
        for repo in repos:
            report = _worktree_report(records[repo])
            if (
                report is None
                or report.outcome != "provisioned"
                or report.worktree_root is None
            ):
                failed.append(repo)
                continue
            worktree_map[repo] = Path(report.worktree_root)
        return ProvisioningOutcome(
            pending=False, worktree_map=worktree_map, failed_repos=tuple(failed)
        )

    def ensure_teardown(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repos: tuple[str, ...],
        branch: str,
    ) -> None:
        """Commission ``teardown_worktree`` per repo (setup-failure cleanup, D).

        Fire-and-forget cleanup: commissions one idempotent ``teardown_worktree``
        command per participating repo so a setup that fails AFTER provisioning
        never silently leaks a worktree (closes the C->D teardown gap). The
        commissioning is scoped to the run's OWN active ownership record.
        """
        session_id, epoch = self._active_session_epoch(project_key, story_id, run_id)
        commission_teardown_worktree(
            self.edge_commands,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            session_id=session_id,
            ownership_epoch=epoch,
            repos=repos,
            branch=branch,
        )

    def _active_session_epoch(
        self, project_key: str, story_id: str, run_id: str
    ) -> tuple[str, int]:
        """Return ``(owner_session_id, ownership_epoch)`` of the OWN active record.

        Fail-closed: setup-start must have materialized the active
        ``run_ownership_records`` row for THIS run before the setup phase
        commissions any edge command (FK-56 §56.8a). A missing / foreign-run
        active record is a :class:`ConfigError`.
        """
        record = self.ownership_repo.load_active_ownership(project_key, story_id)
        if record is None or record.run_id != run_id:
            raise ConfigError(
                "edge_provisioning: no active run-ownership record for "
                f"(project={project_key!r}, story={story_id!r}, run={run_id!r}); "
                "setup-start must materialize it before commissioning "
                "(FK-56 §56.8a).",
            )
        return record.owner_session_id, record.ownership_epoch

    def _commission_and_load(
        self,
        command_kind: str,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        session_id: str,
        epoch: int,
        repos: tuple[str, ...],
        payloads: dict[str, dict[str, object]],
    ) -> tuple[bool, dict[str, EdgeCommandRecord]]:
        """Commission missing commands + load terminal ones. Idempotent by id.

        Design note (deliberate strict insert, NOT the atomic ``commission_command``):
        this ``provision_worktree`` / ``preflight_probe`` path uses strict
        load-then-``insert_command`` on purpose. The setup phase executes serially
        PER RUN (a single owning session, re-entered only via the PAUSE/resume
        loop), so it is NOT a concurrent-replay surface -- idempotent re-entry is
        already handled by the ``load_command`` guard. FK-10 §10.5.3 scopes
        idempotent (``ON CONFLICT DO NOTHING``) commissioning to the TEARDOWN
        path (``commission_teardown_worktree``), where a concurrent double-detach
        is legitimate. Here a genuine duplicate ``command_id`` is a real fault
        (two provisioners for one run) and MUST fail loudly (the strict insert's
        primary-key violation), never a silent no-op.
        """
        pending = False
        records: dict[str, EdgeCommandRecord] = {}
        for repo in repos:
            command_id = edge_command_id(run_id, command_kind, repo)
            existing = self.edge_commands.load_command(command_id)
            if existing is None:
                self.edge_commands.insert_command(
                    EdgeCommandRecord(
                        command_id=command_id,
                        project_key=project_key,
                        story_id=story_id,
                        run_id=run_id,
                        session_id=session_id,
                        command_kind=command_kind,
                        payload=payloads[repo],
                        status="created",
                        ownership_epoch=epoch,
                        created_at=datetime.now(tz=UTC),
                    )
                )
                pending = True
                continue
            if existing.status in OPEN_COMMAND_STATUSES:
                pending = True
                continue
            records[repo] = existing
        return pending, records

    def _ensure_ref_protection(
        self,
        *,
        project_key: str,
        story_id: str,
        session_id: str,
        ownership_epoch: int,
        repos: tuple[str, ...],
        ref_pattern: str,
    ) -> None:
        """Administer or visibly degrade ``story/*`` ref protection (AC9)."""
        from agentkit.backend.state_backend.story_closure_store import (
            upsert_ref_protection_degradation_finding_global,
        )

        for repo in repos:
            port = self.code_backend_port(repo)
            supported = port.capability_supported(
                CodeBackendCapability.REF_PROTECTION_ADMINISTRATION
            )
            finding = assess_ref_protection_capability(
                capability_supported=supported, provider_label=repo
            )
            if finding is not None:
                upsert_ref_protection_degradation_finding_global(
                    project_key=project_key,
                    story_id=story_id,
                    repo_id=repo,
                    finding=finding,
                    recorded_at=datetime.now(tz=UTC),
                )
                continue
            auth = authorize_story_ref_write(
                active_owner_session_id=session_id,
                active_ownership_epoch=ownership_epoch,
                requesting_session_id=session_id,
                requesting_ownership_epoch=ownership_epoch,
            )
            if not auth.granted:
                raise ConfigError(f"story ref write authorization refused: {auth.detail}")
            credential = port.resolve_story_ref_write_credential()
            if (
                not credential.resolved
                or credential.credential_class
                is not StoryRefWriteCredentialClass.SERVICE_IDENTITY
            ):
                raise ConfigError(
                    "story/* ref protection requires the backend-managed "
                    "service identity; personal developer tokens are never "
                    "accepted"
                )
            result = port.administer_ref_protection(ref_pattern)
            if (
                not result.administered
                or not result.blocks_direct_developer_push
                or not result.blocks_fast_forward
            ):
                raise ConfigError(
                    "ref protection administration failed for "
                    f"{repo!r}/{ref_pattern!r}: {result.detail}"
                )

    def _probe_evidence(
        self,
        record: EdgeCommandRecord,
        repo: str,
        branch: str,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        epoch: int,
    ) -> PreflightProbeEvidence | None:
        """Map a terminal probe command to the per-repo decision evidence.

        Returns ``None`` when the reported result is not a readable
        ``preflight_probe_report`` (a ``command_error`` or an unparsable
        payload) -- Checks 7/8 then FAIL fail-closed (``edge_probe_missing``).
        """
        if (
            record.result_type != "preflight_probe_report"
            or record.result_payload is None
        ):
            return None
        try:
            report = PreflightProbeReport.model_validate(record.result_payload)
        except ValidationError:
            return None
        transfer = self.transfer_repo.load_transfer(
            project_key, story_id, run_id, epoch, repo
        )
        return PreflightProbeEvidence(
            repo_id=repo,
            branch_present=report.branch_present,
            head_sha=report.head_sha,
            worktree_present=report.worktree_present,
            marker_present=report.marker_present,
            marker_story_id=report.marker_story_id,
            remote_head_sha=self.remote_head_reader(repo, branch),
            takeover_base_sha=(
                transfer.takeover_base_sha if transfer is not None else None
            ),
        )


def _worktree_report(record: EdgeCommandRecord) -> WorktreeReport | None:
    """Parse a terminal command's ``worktree_report`` (``None`` when absent/errored)."""
    if record.result_type != "worktree_report" or record.result_payload is None:
        return None
    try:
        return WorktreeReport.model_validate(record.result_payload)
    except ValidationError:
        return None


def build_setup_edge_provisioning_coordinator(
    project_root: Path,
) -> SetupEdgeProvisioningCoordinator:
    """Build the productive Postgres-backed edge-provisioning coordinator.

    The remote-head reader resolves each repo's remote from the project config
    (``remote_url`` when set, else the local repo path -- both accepted by
    ``git ls-remote``) and reads ``refs/heads/{branch}`` over the git wire
    protocol. An unresolvable/absent ref yields ``None`` (a fresh story branch is
    simply not on the remote yet) -- never a fabricated SHA.
    """
    from agentkit.backend.code_backend.git_protocol import GitLsRemoteReader
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.control_plane.repository import (
        EdgeCommandRepository,
        RunOwnershipRepository,
        TakeoverTransferRepository,
    )

    try:
        project_config = load_project_config(project_root)
        remotes: dict[str, str] = {
            repo.name: (
                repo.remote_url
                or str(
                    repo.path if repo.path.is_absolute() else project_root / repo.path
                )
            )
            for repo in project_config.repositories
        }
        repositories = {repo.name: repo for repo in project_config.repositories}
    except (ConfigError, OSError):
        remotes = {}
        repositories = {}

    ls_remote = GitLsRemoteReader()

    def _remote_head(repo_id: str, branch: str) -> str | None:
        remote = remotes.get(repo_id)
        if remote is None:
            return None
        result = ls_remote.read_head_sha(remote, f"refs/heads/{branch}")
        return result.head_sha if result.resolved else None

    def _code_backend(repo_id: str) -> CodeBackendPort:
        from agentkit.backend.installer.github_coordinates import (
            parse_github_remote_url,
        )
        from agentkit.integration_clients.github.adapter import (
            GitHubCodeBackendAdapter,
        )

        repo = repositories.get(repo_id)
        if repo is None:
            raise ConfigError(f"repository {repo_id!r} is not configured")
        remote = repo.remote_url or str(
            repo.path if repo.path.is_absolute() else project_root / repo.path
        )
        coordinates = parse_github_remote_url(repo.remote_url) if repo.remote_url else None
        owner, name = coordinates or (repo.name, repo.name)
        return GitHubCodeBackendAdapter(
            owner=owner, repo=name, remote_url_override=remote
        )

    return SetupEdgeProvisioningCoordinator(
        edge_commands=EdgeCommandRepository(),
        ownership_repo=RunOwnershipRepository(),
        transfer_repo=TakeoverTransferRepository(),
        remote_head_reader=_remote_head,
        code_backend_port=_code_backend,
    )
