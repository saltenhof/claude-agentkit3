"""Pydantic v2 models for AgentKit project configuration.

These models represent the structure of a target project's
``project.yaml`` (located at ``.agentkit/config/project.yaml``).
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agentkit.backend.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.backend.config.worker_health import WorkerHealthConfig

#: The single supported ``config_version`` value for ``project.yaml``.
#: FK-03 §3.2.1 / §3.3.4: pipeline-config versioning area (separate from
#: artefact-envelope ``schema_version`` which is owned by ``ArtifactEnvelope``
#: and ``ChangeFrame`` in their respective BCs).
SUPPORTED_CONFIG_VERSION: str = "3.0"

#: Required LLM roles when ``features.multi_llm`` is ``True`` (FK-03 §3.2.1).
REQUIRED_LLM_ROLES: frozenset[str] = frozenset(
    {
        "qa_review",
        "semantic_review",
        "adversarial_sparring",
        "doc_fidelity",
        "governance_adjudication",
    }
)


def _validate_project_relative_dir(value: str, field_name: str) -> str:
    """Validate a project-relative directory setting from ``project.yaml``."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(
            f"{field_name} must be a non-empty project-relative path "
            "(FK-03 §3.1, fail-closed)"
        )
    candidate = PurePosixPath(stripped.replace("\\", "/"))
    windows = PureWindowsPath(stripped)
    if candidate.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(
            f"{field_name} must be project-relative, not absolute or "
            f"drive-anchored: {value!r} (FK-03 §3.1, fail-closed)"
        )
    if ".." in candidate.parts:
        raise ValueError(
            f"{field_name} must not contain a '..' traversal segment: "
            f"{value!r} (FK-03 §3.1, fail-closed)"
        )
    return stripped


class Features(BaseModel):
    """Feature flags for a target project (FK-03 §3.1).

    Carries all six feature flags as well as the optional ARE flag.
    Cross-field invariant: ``e2e_assertions`` requires ``db``.

    Attributes:
        are: Whether the Agent Requirements Engine (ARE) integration
            is enabled. When ``False`` (default), all
            ``RequirementsCoverage`` top-surface methods are no-ops
            that return ``SKIPPED`` results (FK-40 §40.2).
        multi_repo: Whether multi-repository support is enabled.
        vectordb: Whether VectorDB integration is enabled.
        multi_llm: Whether multi-LLM role assignment is enabled.
            Default ``True`` (FK-01 §1.3 P5 / FK-03 §3.1 mandate: multi-LLM
            is the expected production mode).  When ``True`` a populated
            ``llm_roles`` stanza is required on ``PipelineConfig``.
        telemetry: Whether telemetry collection is enabled.
        db: Whether the database backend is enabled.
        e2e_assertions: Whether end-to-end assertion checks are enabled.
            Requires ``db=True`` (fail-closed cross-field rule).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    are: bool = False
    multi_repo: bool = False
    vectordb: bool = False
    multi_llm: bool = True
    telemetry: bool = True
    db: bool = False
    e2e_assertions: bool = False

    @model_validator(mode="after")
    def _validate_e2e_assertions_requires_db(self) -> Features:
        """FK-03 §3.2.1: ``e2e_assertions`` requires ``db`` (fail-closed)."""
        if self.e2e_assertions and not self.db:
            raise ValueError(
                "features.e2e_assertions=True requires features.db=True "
                "(FK-03 §3.2.1, fail-closed cross-field rule)"
            )
        return self


class AreConfig(BaseModel):
    """Configuration section for the Agent Requirements Engine (ARE).

    Required when ``pipeline.features.are`` is ``True`` (FK-03 §3.2.1).

    Attributes:
        mcp_server: MCP server endpoint for the ARE integration.
        rest_base_url: Optional REST base URL for ``AreClient`` (FK-40 §40.4).
        token_env: Optional backend environment-variable reference for ARE API
            authentication. Secret values never belong in project config.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mcp_server: str
    rest_base_url: str | None = None
    token_env: str | None = None


_SEMVER_RE = re.compile(r"^\d+(\.\d+)*$")


def _validate_semver(value: str, *, field: str) -> str:
    """FK-03 §3: ``min_version`` strings must be parsable dotted SemVer."""
    if not _SEMVER_RE.fullmatch(value):
        msg = f"sonarqube.{field} must be a parsable SemVer string (FK-03 §3); got {value!r}"
        raise ValueError(msg)
    return value


class SonarQubeBranchPluginConfig(BaseModel):
    """Community Branch Plugin requirement (FK-03 §3, FK-33 §33.6.3).

    Attributes:
        min_version: Minimum Community Branch Plugin version (SemVer).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_version: str = "1.23.0"

    @field_validator("min_version")
    @classmethod
    def _check_min_version(cls, value: str) -> str:
        """FK-03 §3: plugin ``min_version`` must be parsable SemVer."""
        return _validate_semver(value, field="plugins.community_branch.min_version")


class SonarQubePluginsConfig(BaseModel):
    """SonarQube plugin requirements (FK-03 §3).

    Attributes:
        community_branch: Community Branch Plugin requirement.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    community_branch: SonarQubeBranchPluginConfig = SonarQubeBranchPluginConfig()


class SonarQubeQualityGateConfig(BaseModel):
    """Quality-gate / default-profile reference (FK-03 §3, FK-33 §33.6.3).

    Attributes:
        default_profile: Repo-relative path to the shipped default
            quality-gate profile artefact (SSOT under
            ``bundles/target_project/``). Carries BOTH New-Code AND
            Overall-Code conditions (FK-33 §33.6.3 Overall-Code invariant).
        overrides_allowed: Whether the project owner may replace the
            default profile with its own rule set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_profile: str = "bundles/target_project/sonar/ak3-default-gate.json"
    overrides_allowed: bool = True


class SonarQubeConfig(BaseModel):
    """SonarQube-Green-Gate environment/profile requirement (FK-03 §3).

    Config-owner slice of the SonarQube-Green-Gate requirement; the gate
    semantics live in FK-33 §33.6.3 (capability ``sonarqube_gate``).
    Checked as an installer precondition (FK-50 CP 10d) and carried as a
    mandatory runtime dependency (FK-10 §10.2.2).

    The ``available``/``enabled`` split (FK-33 §33.6.5) is normative:

    * ``available`` -- whether SonarQube is declared present for this
      project/host. The CORE DEFAULT is ``true`` (FK-03 §3: the green-gate
      is the default for code-producing projects; ``available == false`` is
      only ever a CONSCIOUS, EXPLICIT opt-out). This makes a present-but-
      empty ``sonarqube: {}`` stanza fail closed (it defaults
      ``available/enabled == true`` and the missing endpoint then raises)
      rather than becoming a SILENT opt-out. ``available == false`` makes
      the gate not applicable (a deliberate absence, not a failure) and is
      permitted even for code-producing projects.
    * ``enabled`` -- whether the gate is switched on. Default ``true`` (a
      declared-present gate is on by default). For a code-producing project
      ``available == true AND enabled == false`` is illegal (cross-field
      rule below); pure concept/research projects may set both ``false``.

    Attributes:
        available: SonarQube declared present (FK-33 §33.6.5 applicability).
            Core default ``true`` (FK-03 §3): the gate is on by default for
            code-producing projects; ``false`` is an explicit opt-out only.
        enabled: Gate switched on (FK-03 §3 cross-field rule). Core default
            ``true``.
        base_url: SonarQube server endpoint (default port 9901, FK-10
            §10.7.2). Required when ``available and enabled``.
        token_env: Name of the ENV/secret-store key holding the Sonar
            token (never an inline token, FK-33 §33.3.2). Required when
            ``available and enabled``.
        min_version: Minimum SonarQube Community Build version (SemVer).
        plugins: Plugin requirements (Community Branch Plugin).
        quality_gate: Quality-gate / default-profile reference.
        scanner_version: Expected SonarScanner version for produced
            attestations. FK-33 §33.6.3 names the scanner version as an
            attestation binding. In the implementation QA-subflow's local
            report-task adapter this config value is the authoritative scanner
            version placed on the produced attestation; in Closure pre-merge
            scans the Jenkins run contributes the measured
            ``SONAR_SCANNER_VERSION`` and Dim 9 compares it to this configured
            pin. Required when ``available and enabled`` so a produced
            attestation never carries an empty scanner version (fail-closed).
        accept_frequency_fc_threshold: Fraction of stories (measured across
            ALL stories, never per individual story) at or above which a
            repeatedly accepted Sonar rule becomes a Failure-Corpus signal
            (FK-27 §27.6b, FK-41 §41.10). Must be in the range [0.0, 1.0].
            Default ``0.25`` (FK-03 §3.1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool = True
    enabled: bool = True
    base_url: str | None = None
    token_env: str | None = None
    min_version: str = "26.4"
    plugins: SonarQubePluginsConfig = SonarQubePluginsConfig()
    quality_gate: SonarQubeQualityGateConfig = SonarQubeQualityGateConfig()
    scanner_version: str | None = None
    accept_frequency_fc_threshold: float = 0.25

    @field_validator("accept_frequency_fc_threshold")
    @classmethod
    def _check_accept_frequency_fc_threshold(cls, value: float) -> float:
        """FK-03 §3.1: ``accept_frequency_fc_threshold`` must be in [0.0, 1.0]."""
        if value < 0.0 or value > 1.0:
            msg = (
                "sonarqube.accept_frequency_fc_threshold must be in [0.0, 1.0]; "
                f"got {value!r} (FK-03 §3.1, FK-27 §27.6b)"
            )
            raise ValueError(msg)
        return value

    @field_validator("min_version")
    @classmethod
    def _check_min_version(cls, value: str) -> str:
        """FK-03 §3: ``min_version`` must be parsable SemVer."""
        return _validate_semver(value, field="min_version")

    @field_validator("scanner_version")
    @classmethod
    def _check_scanner_version(cls, value: str | None) -> str | None:
        """FK-03 §3: the pinned scanner version must be parsable SemVer."""
        if value is None:
            return None
        return _validate_semver(value, field="scanner_version")

    @model_validator(mode="after")
    def _validate_active_requires_endpoint(self) -> SonarQubeConfig:
        """FK-03 §3: ``available and enabled`` requires base_url + token_env.

        No silent default to localhost without auth (fail-closed).
        """
        if self.available and self.enabled:
            missing = [
                name
                for name, value in (
                    ("base_url", self.base_url),
                    ("token_env", self.token_env),
                    ("scanner_version", self.scanner_version),
                )
                if not value
            ]
            if missing:
                msg = (
                    "sonarqube.available=true and sonarqube.enabled=true require "
                    f"{' and '.join(missing)} (FK-03 §3, fail-closed: no silent "
                    "localhost-without-auth default; scanner_version is an "
                    "attestation binding, FK-33 §33.6.3)"
                )
                raise ValueError(msg)
        return self


class JenkinsConfig(BaseModel):
    """CI (Jenkins) requirement for the pre-merge verification runner.

    Config-owner slice of the Pre-Merge-Verification-Runner requirement
    (AG3-056 §2.1.6); the runner semantics live in
    ``agentkit.backend.verify_system.pre_merge_runner`` (FK-29 §29.1a.3 / FK-33
    §33.6.3). Checked as an installer precondition and carried as the CI
    trigger configuration for the closure pre-merge barrier (AG3-053).

    The ``available``/``enabled`` split mirrors ``SonarQubeConfig`` and is
    normative:

    * ``available`` -- whether Jenkins is declared present for this
      project/host. Core default ``true``: the pre-merge runner triggers a
      real CI build/test + Sonar scan for code-producing projects;
      ``available == false`` is a CONSCIOUS, EXPLICIT opt-out (the runner is
      simply not applicable — a deliberate absence, NOT a failure). This
      makes a present-but-empty ``ci: {}`` stanza fail closed (it defaults
      ``available/enabled == true`` and the missing endpoint then raises)
      rather than becoming a SILENT opt-out.
    * ``enabled`` -- whether the runner is switched on. Default ``true``.

    Attributes:
        available: Jenkins declared present (applicability axis). Core
            default ``true``; ``false`` is an explicit opt-out only.
        enabled: Runner switched on. Core default ``true``.
        base_url: Jenkins server endpoint. Required when
            ``available and enabled``.
        token_env: Name of the ENV/secret-store key holding the Jenkins API
            token (never an inline token). Required when
            ``available and enabled``.
        user: Optional Jenkins user the token belongs to (HTTP Basic
            username). Empty for token-only setups.
        pipeline: Jenkins job/pipeline name to trigger for the integrated
            candidate. Required when ``available and enabled``.
        poll_timeout_seconds: Bounded wait for a triggered build to reach a
            terminal state before fail-closed timeout.
        poll_interval_seconds: Delay between build-status polls.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool = True
    enabled: bool = True
    base_url: str | None = None
    token_env: str | None = None
    user: str = ""
    pipeline: str | None = None
    poll_timeout_seconds: int = 1800
    poll_interval_seconds: int = 10

    @field_validator("poll_timeout_seconds", "poll_interval_seconds")
    @classmethod
    def _check_positive(cls, value: int, info: ValidationInfo) -> int:
        """Poll bounds must be positive (no zero/negative wait window)."""
        if value <= 0:
            msg = f"ci.{info.field_name} must be a positive integer; got {value}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_active_requires_endpoint(self) -> JenkinsConfig:
        """``available and enabled`` requires base_url + token_env + pipeline.

        No silent default to localhost without auth or without a target job
        (fail-closed; mirrors ``SonarQubeConfig`` discipline).
        """
        if self.available and self.enabled:
            missing = [
                name
                for name, value in (
                    ("base_url", self.base_url),
                    ("token_env", self.token_env),
                    ("pipeline", self.pipeline),
                )
                if not value
            ]
            if missing:
                msg = (
                    "ci.available=true and ci.enabled=true require "
                    f"{' and '.join(missing)} (AG3-056 §2.1.6, fail-closed: no "
                    "silent localhost/no-pipeline default)"
                )
                raise ValueError(msg)
        return self


class ReviewConfig(BaseModel):
    """Mandatory-reviewer-coverage configuration (FK-68 §68.3.1 / AG3-036 §2.1.5).

    Authoritative source for the reviewer roles that the double-role
    :class:`~agentkit.backend.telemetry.hooks.review_guard.ReviewGuard` enforces per
    worker increment (precondition for Integrity-Gate Dim 5). The runner /
    composition edge reads ``required_roles`` here and injects the plain
    string values into the hook, so the hook keeps its AC10 import boundary
    (no config import inside the telemetry-hook package) while the authority
    is NOT a forgeable harness payload.

    Attributes:
        required_roles: The reviewer roles that MUST each have a
            ``review_compliant`` event since the last increment commit before a
            commit is permitted. Empty (default) means no mandatory reviewer
            coverage is configured — but for a code-producing story the runner
            treats an empty / unavailable list as fail-closed (DENY), never a
            silent guard-skip (FK-68 §68.3.1 / CLAUDE.md FAIL-CLOSED).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_roles: list[str] = []


class LlmRolesConfig(BaseModel):
    """LLM provider assignments per pipeline role (FK-01 §1.3 P5 / FK-03 §3.1).

    Maps each pipeline role to the LLM provider name that fulfils it.
    Required when ``features.multi_llm=True``; the five roles
    ``qa_review``, ``semantic_review``, ``adversarial_sparring``,
    ``doc_fidelity``, and ``governance_adjudication`` are mandatory.

    This is the single source of truth for role-to-provider assignment.
    ``ReviewConfig.required_roles`` (reviewer coverage enforcement in the
    ReviewGuard) and ``LlmRolesConfig`` (LLM provider assignment per role)
    serve distinct purposes and are not parallel duplicates.

    Attributes:
        worker: Provider for the main implementation worker.
        qa_review: Provider for QA review (mandatory).
        semantic_review: Provider for semantic/guardrail review (mandatory).
        adversarial_sparring: Provider for adversarial edge-case testing
            (mandatory).
        doc_fidelity: Provider for documentation fidelity review (mandatory).
        governance_adjudication: Provider for governance adjudication
            (mandatory).
        story_creation_review: Optional provider for story creation review.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    worker: str | None = None
    qa_review: str
    semantic_review: str
    adversarial_sparring: str
    doc_fidelity: str
    governance_adjudication: str
    story_creation_review: str | None = None


class OrchestratorGuardConfig(BaseModel):
    """Orchestrator guard path/extension/file blocklist (FK-03 §3.1).

    Defines paths, extensions, and files that the orchestrator guard
    blocks from agent modification. An empty blocklist means the guard
    is effectively disabled (a warning-level condition at runtime).

    Attributes:
        blocked_paths: Path prefixes blocked from agent writes.
        blocked_extensions: File extensions blocked from agent writes.
        blocked_files: Specific filenames blocked from agent writes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocked_paths: list[str] = []
    blocked_extensions: list[str] = []
    blocked_files: list[str] = []


class StageOverride(BaseModel):
    """Per-stage policy override (FK-33 §33.2.4).

    Only ``blocking`` is overrideable. Layer, kind, applies_to and producer
    remain owned by the stage registry.

    Attributes:
        blocking: Whether the stage is blocking.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocking: bool


class PolicyConfig(BaseModel):
    """Top-level stage policy configuration (FK-33 §33.2.4).

    Attributes:
        stage_overrides: Per-stage blocking overrides keyed by stage ID.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_overrides: dict[str, StageOverride] = {}


StageOverrideConfig = StageOverride


class PipelinePolicyConfig(BaseModel):
    """Pipeline policy threshold configuration (FK-03 §3.1, FK-05-209).

    Attributes:
        major_threshold: Number of major QA findings above which the story
            is escalated (FK-05-209). Default ``3``.
        required_stages: Stage IDs that are always required regardless of
            story type. Empty list means use stage-registry defaults.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    major_threshold: int = 3
    required_stages: list[str] = []


class VectorDbConfig(BaseModel):
    """VectorDB connection and tuning configuration (FK-03 §3.1, FK-05-018/020).

    Attributes:
        similarity_threshold: Minimum cosine similarity score for a
            VectorDB candidate to be forwarded to LLM evaluation (FK-05-018).
            Default ``0.7``.
        max_llm_candidates: Maximum number of VectorDB candidates passed to
            LLM evaluation per query (FK-05-020). Default ``5``.
        host: VectorDB server hostname or IP.
        port: VectorDB server port.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    similarity_threshold: float = 0.7
    max_llm_candidates: int = 5
    host: str | None = None
    port: int | None = None


class TelemetryConfig(BaseModel):
    """Telemetry and web-call budget configuration (FK-03 §3.1, FK-08-019).

    Attributes:
        web_call_limit: Hard limit on outbound web calls per story run,
            applicable only for Research-type stories (FK-08-019). Default
            ``200``.
        web_call_warning: Soft warning threshold for outbound web calls
            per story run (FK-08-019). Default ``180``. Must be less than
            ``web_call_limit``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    web_call_limit: int = 200
    web_call_warning: int = 180

    @model_validator(mode="after")
    def _validate_warning_below_limit(self) -> TelemetryConfig:
        """``web_call_warning`` must be less than ``web_call_limit``."""
        if self.web_call_warning >= self.web_call_limit:
            raise ValueError(
                f"telemetry.web_call_warning ({self.web_call_warning}) must be "
                f"less than telemetry.web_call_limit ({self.web_call_limit}) "
                "(FK-08-019)"
            )
        return self


class PermissionsConfig(BaseModel):
    """CCAG permission-request configuration (FK-93 §93.5a, AG3-086).

    Owns the typed permission-request TTL. FK-93 §93.5a fixes the
    permission-request TTL default at 1800s; AG3-086 introduces this typed config
    key so the value is no longer the hard-coded ``DEFAULT_TTL_SECONDS = 600`` in
    ``ccag.requests``. The broader FK-93 defaults reconciliation is doc-only
    AG3-103; AG3-086 sets ONLY this one value to the FK-93-conformant default.

    Attributes:
        request_ttl_s: Seconds a CCAG ``permission_request`` stays open before TTL
            expiry escalates the run (FK-42 §42.4.2 step 5 / FK-93 §93.5a).
            Default ``1800`` (FK-93 §93.5a). Must be a positive integer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_ttl_s: int = 1800

    @field_validator("request_ttl_s")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        """FK-93 §93.5a: the permission-request TTL must be a positive integer."""
        if value <= 0:
            raise ValueError(
                "permissions.request_ttl_s must be a positive integer; "
                f"got {value} (FK-93 §93.5a)"
            )
        return value


class GovernanceConfig(BaseModel):
    """Governance observation configuration (FK-03 §3.1, FK-06-128).

    Attributes:
        risk_threshold: Risk score at or above which an event is considered
            an incident candidate. Default ``30``.
        window_size: Rolling window width in events for risk aggregation.
            Default ``50``.
        cooldown_s: Cooldown in seconds between LLM adjudications of the
            same governance type (FK-06-128). Default ``300``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    risk_threshold: int = 30
    window_size: int = 50
    cooldown_s: int = 300


class ConformanceConfig(BaseModel):
    """ConformanceService prompt-size thresholds (FK-32 §32.4b.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_upload_threshold: int = 50 * 1024
    hard_limit: int = 500 * 1024

    @model_validator(mode="after")
    def _validate_thresholds(self) -> ConformanceConfig:
        """Require positive, ordered conformance size thresholds."""
        if self.file_upload_threshold <= 0:
            raise ValueError("conformance.file_upload_threshold must be > 0")
        if self.hard_limit <= self.file_upload_threshold:
            raise ValueError(
                "conformance.hard_limit must be greater than "
                "conformance.file_upload_threshold"
            )
        return self


class Layer2Config(BaseModel):
    """Layer-2 review bundle configuration (FK-37 §37.3.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_token_limit: int = 32_000

    @field_validator("bundle_token_limit")
    @classmethod
    def _check_bundle_token_limit(cls, value: int) -> int:
        """Require a positive per-field bundle packing limit."""
        if value <= 0:
            raise ValueError("layer2.bundle_token_limit must be > 0")
        return value


class PipelineConfig(BaseModel):
    """Configuration for the 4-phase pipeline.

    Carries the mandatory ``config_version`` field for the ``project.yaml``
    config-versioning area (FK-03 §3.2.1 / §3.3.4). This is the single
    ``config_version`` owner for the Pipeline-Config versioning area.
    The DB-schema version (``state_backend.config.SCHEMA_VERSION``) is a
    separate, independent versioning area — the two must NOT be conflated.

    Attributes:
        config_version: Mandatory ``project.yaml`` format version.  Must be
            provided explicitly — there is no silent default (FK-03 §3.2.1,
            fail-closed).  Must equal ``"3.0"``; any other value raises
            ``ValueError`` at model-validation time, which
            ``load_project_config`` surfaces as a ``ConfigError``.
        max_feedback_rounds: Maximum QA feedback cycles before
            escalation.
        max_remediation_rounds: Maximum remediation attempts per
            feedback round.
        exploration_mode: Whether the optional Exploration phase
            (Phase 2) is enabled for implementation stories.
        verify_layers: Ordered list of QA layers to execute during
            the implementation QA-subflow.
        review: Mandatory-reviewer-coverage configuration (FK-68 §68.3.1 /
            AG3-036 §2.1.5). Authoritative source of ``review.required_roles``
            for the ReviewGuard pre-commit hook.
        features: Feature flags (FK-03 §3.1).
        llm_roles: LLM provider assignments per pipeline role (FK-01 §1.3
            P5 / FK-03 §3.1). Required when ``features.multi_llm=True``.
        orchestrator_guard: Orchestrator guard blocklist (FK-03 §3.1).
        policy: Pipeline threshold configuration (FK-03 §3.1).
        vectordb: VectorDB connection and tuning (FK-03 §3.1). Required when
            ``features.vectordb=True``.
        telemetry: Telemetry and web-call budget (FK-03 §3.1).
        governance: Governance observation configuration (FK-03 §3.1).
        permissions: CCAG permission-request configuration (FK-93 §93.5a /
            AG3-086). Owns the typed ``request_ttl_s`` (default 1800).
        conformance: ConformanceService size-threshold configuration
            (FK-32 §32.4b.3).
        layer2: Layer-2 review bundle packing configuration.
        sonarqube: SonarQube-Green-Gate environment/profile requirement
            (FK-03 §3 / FK-33 §33.6). ``None`` only for non-code-producing
            projects; a code-producing project (``story_types`` include
            ``implementation``/``bugfix``) MUST declare the stanza explicitly
            — an omitted stanza is rejected at config-load (AG3-052 E6,
            FAIL-CLOSED, see ``ProjectConfig._validate_sonarqube_codeproducing``).
            The installer ALWAYS writes an EXPLICIT stanza for a code-producing
            project (FK-03 §3 example: ``available: true``). The explicit
            ``available: false`` opt-out stays legal. The existing cross-field
            rule (``available: true`` + ``enabled: false`` on a code-producing
            project) is unchanged.
        ci: CI (Jenkins) requirement for the pre-merge verification runner
            (AG3-056 §2.1.6). ``None`` only for non-code-producing projects; a
            code-producing project MUST declare the stanza explicitly — an
            omitted stanza is rejected at config-load (FAIL-CLOSED, see
            ``ProjectConfig._validate_ci_codeproducing``). The pre-merge
            runner triggers a real, commit-bound CI build/test + Sonar scan,
            so its CI endpoint must be an EXPLICIT operator decision. The
            explicit ``available: false`` opt-out stays legal.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    config_version: str
    max_feedback_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS
    max_remediation_rounds: int = DEFAULT_MAX_REMEDIATION_ROUNDS
    exploration_mode: bool = True
    verify_layers: list[str] = list(DEFAULT_VERIFY_LAYERS)
    review: ReviewConfig = ReviewConfig()
    features: Features = Features()
    llm_roles: LlmRolesConfig | None = None
    orchestrator_guard: OrchestratorGuardConfig = OrchestratorGuardConfig()
    policy: PipelinePolicyConfig = PipelinePolicyConfig()
    vectordb: VectorDbConfig | None = None
    telemetry: TelemetryConfig = TelemetryConfig()
    governance: GovernanceConfig = GovernanceConfig()
    permissions: PermissionsConfig = PermissionsConfig()
    conformance: ConformanceConfig = ConformanceConfig()
    layer2: Layer2Config = Layer2Config()
    sonarqube: SonarQubeConfig | None = None
    ci: JenkinsConfig | None = None

    @field_validator("config_version")
    @classmethod
    def _check_config_version(cls, value: str) -> str:
        """FK-03 §3.2.1: reject unknown ``config_version`` fail-closed.

        The loader catches this ``ValueError`` and surfaces it as a
        ``ConfigError`` (``load_project_config``). No silent default to an
        unknown version is permitted (FAIL-CLOSED).
        """
        if value != SUPPORTED_CONFIG_VERSION:
            raise ValueError(
                f"Unsupported config_version: {value!r}. "
                f"Expected {SUPPORTED_CONFIG_VERSION!r} (FK-03 §3.2.1, "
                "fail-closed: unknown version is a hard error, not a warning). "
                "The installer handles migration between config versions "
                "(AG3-089)."
            )
        return value

    @model_validator(mode="after")
    def _validate_multi_llm_requires_llm_roles(self) -> PipelineConfig:
        """FK-03 §3.2.1: ``features.multi_llm=True`` requires ``llm_roles``."""
        if self.features.multi_llm and self.llm_roles is None:
            raise ValueError(
                "pipeline.features.multi_llm=True requires a 'llm_roles' "
                "stanza (FK-03 §3.2.1 / FK-01 §1.3 P5, fail-closed: no default "
                "role-to-provider assignment)"
            )
        return self


def _coerce_path(value: Any) -> Path:
    """Coerce string values to Path objects for YAML compatibility."""
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    msg = f"Expected str or Path, got {type(value).__name__}"
    raise TypeError(msg)


class RepositoryConfig(BaseModel):
    """A single repository in the target project.

    Attributes:
        name: Human-readable repository name.
        path: Filesystem path to the repository root.
        remote_url: Optional clone URL used by the installer for explicitly
            declared multi-repo code repositories.
        language: Primary programming language (e.g. ``"python"``).
        test_command: Shell command to run the test suite.
        build_command: Shell command to build the project.
    """

    model_config = ConfigDict(strict=True)

    name: str
    path: Annotated[Path, BeforeValidator(_coerce_path)]
    remote_url: str | None = None
    language: str | None = None
    test_command: str | None = None
    build_command: str | None = None


class ProjectConfig(BaseModel):
    """Root configuration for a target project using AgentKit.

    This is the top-level model parsed from
    ``.agentkit/config/project.yaml``.

    ``config_version`` is owned by ``PipelineConfig`` (FK-03 §3.2.1 /
    §3.3.4 Pipeline-Config versioning area). ``ProjectConfig`` reaches it
    via ``ProjectConfig.pipeline.config_version`` and carries no second
    version field (single owner, SSOT).

    Attributes:
        project_key: Stable technical key of the target project.
        project_name: Display name of the target project.
        project_prefix: Story-ID prefix (FK-03 §3.2 / FK-43 §43.4.2 placeholder
            ``{{project_prefix}}``). Defaults to ``project_key.upper()`` when
            not provided.
        repositories: List of repositories managed by this project.
        pipeline: Pipeline behaviour configuration (carries
            ``config_version``). Required — no silent default (FK-03 §3.2.1
            fail-closed: omitting the pipeline stanza / config_version is a
            hard error, not a warning).
        story_types: Allowed story types for this project.
        github_owner: GitHub organisation or user owning the repo.
        github_repo: GitHub repository name.
        wiki_stories_dir: Project-relative directory holding the wiki stories
            (FK-03 §3.1 / FK-43 §43.4.2 placeholder ``{{wiki_stories_dir}}``).
            Defaults to ``"stories"``. Used for filesystem operations (story
            directory creation, export), so it is validated fail-closed:
            non-empty, project-relative, no absolute path, no ``..`` segment.
        concepts_dir: Project-relative concept corpus directory. Defaults to
            ``"concepts"`` for target projects.
        codebase_dir: Project-relative container for optional separately
            versioned code repositories in the default scaffold.
        temp_dir: Project-relative scratch directory without persistence
            contract in the default scaffold.
        input_dir: Project-relative directory for external provided input.
        meetings_dir: Project-relative meeting input directory. Must live
            below ``input_dir``.
        guardrails_dir: Project-relative guardrail directory.
        guardrails_pattern: File glob for guardrail documents.
        policy: Top-level verify-stage overrides (FK-33 §33.2.4).
        worker_health: Mandatory worker-health monitor configuration (FK-49).
            There is no disable field; the monitor is part of the runtime.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    project_key: str
    project_name: str
    project_prefix: str | None = None
    repositories: list[RepositoryConfig]
    pipeline: PipelineConfig
    policy: PolicyConfig = PolicyConfig()
    story_types: list[str] = list(DEFAULT_STORY_TYPES)
    github_owner: str | None = None
    github_repo: str | None = None
    wiki_stories_dir: str = "stories"
    concepts_dir: str = "concepts"
    codebase_dir: str = "codebase"
    temp_dir: str = "temp"
    input_dir: str = "input"
    meetings_dir: str = "input/_meetings"
    guardrails_dir: str = "guardrails"
    guardrails_pattern: str = "*.md"
    are: AreConfig | None = None
    worker_health: WorkerHealthConfig = WorkerHealthConfig()

    @field_validator(
        "wiki_stories_dir",
        "concepts_dir",
        "codebase_dir",
        "temp_dir",
        "input_dir",
        "meetings_dir",
        "guardrails_dir",
    )
    @classmethod
    def _check_layout_dirs(cls, value: str, info: ValidationInfo) -> str:
        """FK-03 §3.1: validate project-relative layout directories."""
        return _validate_project_relative_dir(value, info.field_name or "layout_dir")

    @model_validator(mode="after")
    def _validate_meetings_under_input(self) -> ProjectConfig:
        """FK-03 §3.1: ``meetings_dir`` must be below ``input_dir``."""
        input_path = PurePosixPath(self.input_dir.replace("\\", "/"))
        meetings_path = PurePosixPath(self.meetings_dir.replace("\\", "/"))
        if meetings_path == input_path or input_path not in meetings_path.parents:
            raise ValueError(
                "meetings_dir must be below input_dir "
                f"(input_dir={self.input_dir!r}, meetings_dir={self.meetings_dir!r}; "
                "FK-03 §3.1, fail-closed)"
            )
        return self

    @model_validator(mode="after")
    def _validate_stage_overrides_known(self) -> ProjectConfig:
        """FK-33 §33.2.4: stage overrides must target known registry stages."""
        if not self.policy.stage_overrides:
            return self
        registry_mod = import_module("agentkit.backend.verify_system.stage_registry")
        registry = registry_mod.StageRegistry()
        unknown = [
            stage_id
            for stage_id in self.policy.stage_overrides
            if registry.stage_for_id(stage_id) is None
        ]
        if unknown:
            msg = (
                "policy.stage_overrides contains unknown stage ID(s): "
                f"{', '.join(sorted(unknown))} (FK-33 §33.2.4, fail-closed)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_are_section_when_enabled(self) -> ProjectConfig:
        """FK-03 §3.2.1: ``features.are=True`` requires an ``are`` section."""
        if self.pipeline.features.are and self.are is None:
            msg = (
                "pipeline.features.are=True requires an 'are' configuration "
                "section (FK-03 §3.2.1)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_sonarqube_codeproducing(self) -> ProjectConfig:
        """FK-03 §3: code-producing project must DECLARE the gate explicitly.

        A project whose ``story_types`` include ``implementation`` or
        ``bugfix`` is code-producing. Two fail-closed rules apply:

        1. **No silent disable by omission (AG3-052 E6, FAIL-CLOSED).** A
           code-producing project that omits the ``sonarqube`` stanza
           entirely (``self.pipeline.sonarqube is None``) is rejected. The
           green-gate is a mandatory runtime dependency (FK-10 §10.2.2) and
           the operator's intent must be EXPLICIT: either declare
           ``available: true`` (gate enforced) or ``available: false``
           (deliberate, declared opt-out — gate not applicable, FK-33
           §33.6.5). Disabling by leaving the stanza out is NOT the same as a
           conscious ``available: false`` decision and must not pass silently.

        2. **Cross-field rule (unchanged).** A declared-present but
           switched-off gate (``sonarqube.available == true`` and
           ``sonarqube.enabled == false``) is rejected: the Setup-Preflight
           (FK-22 §22.4c) and Closure gate (FK-29 §29.1a / FK-35 §35.2.4a)
           could not satisfy their precondition.

        Non-code-producing (concept/research-only) projects may omit the
        stanza or switch the gate off entirely.
        """
        codeproducing = bool(
            {"implementation", "bugfix"}.intersection(self.story_types)
        )
        sonar = self.pipeline.sonarqube
        if codeproducing and sonar is None:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) must DECLARE the 'sonarqube' stanza "
                "explicitly in pipeline (FK-03 §3, FAIL-CLOSED, AG3-052 E6): "
                "the green-gate is a mandatory runtime dependency (FK-10 "
                "§10.2.2) and must not be disabled by omission. Declare "
                "sonarqube.available=true to enforce the gate, or "
                "sonarqube.available=false to opt out explicitly (gate not "
                "applicable, FK-33 §33.6.5)."
            )
            raise ValueError(msg)
        if codeproducing and sonar is not None and sonar.available and not sonar.enabled:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) with sonarqube.available=true must not "
                "set sonarqube.enabled=false (FK-03 §3): the green-gate "
                "precondition cannot be satisfied. Set enabled=true, or declare "
                "sonarqube.available=false to opt out (gate not applicable)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_ci_codeproducing(self) -> ProjectConfig:
        """AG3-056 §2.1.6: code-producing project must DECLARE the CI stanza.

        A project whose ``story_types`` include ``implementation`` or
        ``bugfix`` is code-producing. Two fail-closed rules apply (mirroring
        the ``sonarqube`` discipline):

        1. **No silent disable by omission (FAIL-CLOSED).** A code-producing
           project that omits the ``ci`` stanza entirely
           (``self.pipeline.ci is None``) is rejected. The closure pre-merge
           barrier (AG3-053, FK-29 §29.1a.3) needs a real CI trigger to
           build/test + scan the integrated candidate; the operator's intent
           must be EXPLICIT: either declare ``available: true`` (runner
           enforced) or ``available: false`` (deliberate, declared opt-out —
           runner not applicable).

        2. **Cross-field rule.** A declared-present but switched-off runner
           (``ci.available == true`` and ``ci.enabled == false``) is rejected:
           the closure pre-merge barrier could not satisfy its precondition.

        Non-code-producing (concept/research-only) projects may omit the
        stanza or switch the runner off entirely.
        """
        codeproducing = bool(
            {"implementation", "bugfix"}.intersection(self.story_types)
        )
        ci = self.pipeline.ci
        if codeproducing and ci is None:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) must DECLARE the 'ci' stanza "
                "explicitly in pipeline (AG3-056 §2.1.6, FAIL-CLOSED): the "
                "closure pre-merge barrier (AG3-053, FK-29 §29.1a.3) triggers "
                "a real CI build/test + Sonar scan on the integrated candidate "
                "and must not be disabled by omission. Declare ci.available=true "
                "to enforce the runner, or ci.available=false to opt out "
                "explicitly (runner not applicable)."
            )
            raise ValueError(msg)
        if codeproducing and ci is not None and ci.available and not ci.enabled:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) with ci.available=true must not set "
                "ci.enabled=false (AG3-056 §2.1.6): the pre-merge runner "
                "precondition cannot be satisfied. Set enabled=true, or declare "
                "ci.available=false to opt out (runner not applicable)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_sonarqube_requires_ci(self) -> ProjectConfig:
        """FK-33/FK-29: APPLICABLE Sonar on code stories requires Jenkins CI."""
        codeproducing = bool(
            {"implementation", "bugfix"}.intersection(self.story_types)
        )
        sonar = self.pipeline.sonarqube
        ci = self.pipeline.ci
        if (
            codeproducing
            and sonar is not None
            and sonar.available
            and sonar.enabled
            and (ci is None or not ci.available or not ci.enabled)
        ):
            msg = (
                "A code-producing project with sonarqube.available=true and "
                "sonarqube.enabled=true requires ci.available=true and "
                "ci.enabled=true: the productive integrated-candidate Sonar "
                "scan is executed through the Jenkins pre-merge runner "
                "(FK-29 §29.1a / FK-33 §33.6.3). Declare CI/Jenkins available "
                "or set sonarqube.available=false for a conscious Sonar opt-out."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _default_project_prefix(self) -> ProjectConfig:
        """FK-03 §3.2 / FK-43 §43.4.2: derive ``project_prefix`` from ``project_key``
        when not explicitly set (story-id prefix convention)."""
        if self.project_prefix is None:
            # Pydantic v2 frozen models: rebuild via model_copy to set the default.
            object.__setattr__(self, "project_prefix", self.project_key.upper())
        return self
