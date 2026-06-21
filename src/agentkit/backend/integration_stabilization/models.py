"""Typed domain models for the integration-stabilization contract.

FK-05 §5.5.2 defines the mandatory fieldset for ``IntegrationScopeManifest``.
FK-05 §5.5.4 defines the ``ManifestApprovalRecord`` binding contract.
FK-05 §5.9 defines the ``StabilizationBudget`` hard caps.

All models are frozen Pydantic v2 models (ARCH-29 immutability requirement).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentkit.backend.story_context_manager.types import ImplementationContract


class StabilizationBudgetCaps(BaseModel):
    """Hard budget caps for integration-stabilization (FK-05 §5.9).

    Attributes:
        max_loops: Maximum number of stabilization loops (stabilize -> verify
            cycles) before budget exhaustion blocks further work.
        max_new_surfaces: Maximum number of newly touched surfaces or path
            groups allowed beyond the declared initial manifest.
        max_contract_changes: Maximum number of allowed contract-change classes
            declared in the manifest (FK-05 §5.9).
        max_regressions_per_cycle: Maximum number of regressions allowed
            between two consecutive verify cycles. Exhaustion blocks live
            in the hook/capability layer (FK-05 §5.9).
    """

    model_config = ConfigDict(frozen=True)

    max_loops: int = Field(ge=1, description="Max stabilization loop count.")
    max_new_surfaces: int = Field(
        ge=0, description="Max newly touched surfaces/path-groups."
    )
    max_contract_changes: int = Field(
        ge=0, description="Max declared contract-change classes."
    )
    max_regressions_per_cycle: int = Field(
        ge=0, description="Max regressions between two verify cycles."
    )


class StabilizationBudget(BaseModel):
    """Live-tracked stabilization budget (FK-05 §5.9).

    Combines the static caps (declared in the manifest) with the runtime
    counters that accumulate as the campaign runs. Budget exhaustion is
    checked at the hook/capability layer *before* the next productive step.

    Attributes:
        caps: Hard caps declared in the approved manifest.
        loops_used: Number of stabilization loops consumed so far.
        new_surfaces_used: New surfaces touched beyond the initial manifest.
        contract_changes_used: Contract-change classes consumed.
        regressions_this_cycle: Regressions detected in the current
            verify cycle (resets to zero on cycle advance).
    """

    model_config = ConfigDict(frozen=True)

    caps: StabilizationBudgetCaps
    loops_used: int = Field(ge=0, default=0)
    new_surfaces_used: int = Field(ge=0, default=0)
    contract_changes_used: int = Field(ge=0, default=0)
    regressions_this_cycle: int = Field(ge=0, default=0)

    @property
    def loops_exhausted(self) -> bool:
        """Whether the loop cap has been reached."""
        return self.loops_used >= self.caps.max_loops

    @property
    def surfaces_exhausted(self) -> bool:
        """Whether the new-surfaces cap has been reached."""
        return self.new_surfaces_used >= self.caps.max_new_surfaces

    @property
    def contract_changes_exhausted(self) -> bool:
        """Whether the contract-changes cap has been reached."""
        return self.contract_changes_used >= self.caps.max_contract_changes

    @property
    def regressions_exhausted(self) -> bool:
        """Whether the regressions-per-cycle cap has been reached."""
        return self.regressions_this_cycle >= self.caps.max_regressions_per_cycle

    @property
    def any_cap_exhausted(self) -> bool:
        """Whether any budget cap has been exhausted (FK-05 §5.9)."""
        return (
            self.loops_exhausted
            or self.surfaces_exhausted
            or self.contract_changes_exhausted
            or self.regressions_exhausted
        )

    def exhausted_caps(self) -> list[str]:
        """Return the names of all exhausted caps."""
        result: list[str] = []
        if self.loops_exhausted:
            result.append("loops")
        if self.surfaces_exhausted:
            result.append("new_surfaces")
        if self.contract_changes_exhausted:
            result.append("contract_changes")
        if self.regressions_exhausted:
            result.append("regressions_per_cycle")
        return result


class IntegrationScopeManifest(BaseModel):
    """Approved integration scope manifest (FK-05 §5.5.2).

    Frozen aggregate-root artefact. Defines target seams, allowed paths,
    integration targets, and budget for the stabilization contract.

    The ``content_hash`` field is a deterministic SHA-256 over the canonical
    JSON serialization of all declarative fields (excluding version and the
    hash itself). It is computed automatically on model construction.

    ``implementation_contract`` is validated at construction time: any value
    other than ``"integration_stabilization"`` raises ``ValidationError``
    immediately (fail-closed, AC1 / FK-05 §5.5.2).

    Attributes:
        version: Manifest version (monotonically increasing integer).
        project_key: Owning project key.
        story_id: Story this manifest belongs to.
        implementation_contract: Must be ``"integration_stabilization"``.
            Validated at construction; invalid value rejects the model.
        target_seams: Declared integration seams — the concrete cross-component
            paths this campaign is allowed to touch.
        allowed_repos_paths: Allowed repository paths within the already-bound
            worktree set (FK-05 §5.5.5 repo-set boundary).
        integration_targets: Named integration targets that must all pass
            before closure is allowed (FK-05 §5.11).
        allowed_contract_changes: Declared contract-change classes allowed
            under this manifest.
        stabilization_budget: Hard caps for this campaign (FK-05 §5.9).
        out_of_contract_examples: Representative examples of what is NOT
            in scope for this manifest (for auditing / scope explosion).
        content_hash: Auto-computed deterministic SHA-256 of the declarative
            fields (excluding version and hash itself). Set by model validator.
    """

    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1, description="Manifest version.")
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    implementation_contract: ImplementationContract = Field(
        description="Must be ImplementationContract.INTEGRATION_STABILIZATION.",
    )
    target_seams: tuple[str, ...] = Field(
        description="Declared integration seam paths."
    )
    allowed_repos_paths: tuple[str, ...] = Field(
        description="Allowed repo/path roots within bound worktrees."
    )
    integration_targets: tuple[str, ...] = Field(
        description="Named integration targets that must pass for closure."
    )
    allowed_contract_changes: tuple[str, ...] = Field(
        description="Declared contract-change classes for this campaign."
    )
    stabilization_budget: StabilizationBudgetCaps = Field(
        description="Hard budget caps (FK-05 §5.9)."
    )
    out_of_contract_examples: tuple[str, ...] = Field(
        default=(),
        description="Examples of out-of-scope work (for audit).",
    )
    content_hash: str = Field(
        default="",
        description="SHA-256 over declarative fields (auto-computed).",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_and_validate_contract(cls, data: Any) -> Any:
        """Coerce list fields to tuples and validate implementation_contract.

        Enforces the contract at model construction time (fail-closed, AC1):
        any ``implementation_contract`` value other than
        ``'integration_stabilization'`` is rejected before the model is built.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # Validate contract field before any other processing. The field is the
        # ImplementationContract enum (AC1); any value other than
        # INTEGRATION_STABILIZATION is rejected fail-closed at construction. Both
        # the enum member and its wire string ("integration_stabilization") are
        # accepted as input and coerced to the enum.
        contract = data.get("implementation_contract")
        if contract is not None:
            try:
                coerced = ImplementationContract(contract)
            except ValueError as exc:
                raise ValueError(
                    "IntegrationScopeManifest.implementation_contract must be "
                    "ImplementationContract.INTEGRATION_STABILIZATION, got "
                    f"{contract!r} (FK-05 §5.5.2, AC1)."
                ) from exc
            if coerced is not ImplementationContract.INTEGRATION_STABILIZATION:
                raise ValueError(
                    "IntegrationScopeManifest.implementation_contract must be "
                    "ImplementationContract.INTEGRATION_STABILIZATION, got "
                    f"{contract!r}. This model only represents the "
                    "integration_stabilization contract (FK-05 §5.5.2, AC1)."
                )
            data["implementation_contract"] = coerced
        for key in (
            "target_seams",
            "allowed_repos_paths",
            "integration_targets",
            "allowed_contract_changes",
            "out_of_contract_examples",
        ):
            if key in data and isinstance(data[key], list):
                data[key] = tuple(data[key])
        return data

    @model_validator(mode="after")
    def _compute_and_verify_hash(self) -> IntegrationScopeManifest:
        """Compute the content hash over declarative fields.

        If ``content_hash`` was supplied by the caller, it is replaced by the
        freshly computed value so stale/wrong caller-supplied hashes are always
        overwritten (fail-closed: a wrong hash cannot pass silently).
        """
        payload: dict[str, object] = {
            "project_key": self.project_key,
            "story_id": self.story_id,
            "implementation_contract": self.implementation_contract.value,
            "target_seams": list(self.target_seams),
            "allowed_repos_paths": list(self.allowed_repos_paths),
            "integration_targets": list(self.integration_targets),
            "allowed_contract_changes": list(self.allowed_contract_changes),
            "stabilization_budget": self.stabilization_budget.model_dump(),
            "out_of_contract_examples": list(self.out_of_contract_examples),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        object.__setattr__(self, "content_hash", computed)
        return self

    def validate_contract_field(self) -> None:
        """Raise if ``implementation_contract`` is not INTEGRATION_STABILIZATION.

        This method is kept for explicit programmatic checks but the contract
        is also enforced at construction time by the ``_normalize_and_validate_contract``
        model validator (AC1).

        Raises:
            ValueError: When the contract field carries an unexpected value.
        """
        if (
            self.implementation_contract
            is not ImplementationContract.INTEGRATION_STABILIZATION
        ):
            raise ValueError(
                "IntegrationScopeManifest.implementation_contract must be "
                "ImplementationContract.INTEGRATION_STABILIZATION, got "
                f"{self.implementation_contract!r}"
            )


class ManifestApprovalRecord(BaseModel):
    """Attested approval record for an integration scope manifest (FK-05 §5.5.4).

    Frozen entity binding manifest identity to an explicit approval authority.
    Any mismatch between this record and the active manifest (hash, version,
    or run identity) causes a binding-integrity failure (fail-closed).

    Attributes:
        project_key: Owning project key.
        story_id: Story this approval is bound to.
        run_id: Run identifier this approval was granted for.
        manifest_version: The manifest version this record attests.
        manifest_hash: SHA-256 content hash of the attested manifest.
        approved_by: Identity of the approving authority (human or admin CLI).
    """

    model_config = ConfigDict(frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    manifest_hash: str = Field(min_length=1)
    approved_by: str = Field(
        default="human_cli",
        description="Identity of the approving authority.",
    )

    def binds_manifest(self, manifest: IntegrationScopeManifest) -> bool:
        """Return True iff this record binds the given manifest correctly.

        A binding is valid iff project_key, story_id, manifest_version and
        manifest_hash all match. The run_id is checked separately by the
        enforcement-point guards (which also have access to the current run_id).

        Args:
            manifest: The manifest to check binding against.

        Returns:
            True when all four fields match.
        """
        return (
            self.project_key == manifest.project_key
            and self.story_id == manifest.story_id
            and self.manifest_version == manifest.version
            and self.manifest_hash == manifest.content_hash
        )
