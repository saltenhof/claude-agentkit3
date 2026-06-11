"""CustomizationFootprint — the read-aggregate of project customizations (FK-51 §51.8).

The ``CustomizationFootprint`` is a READ-ONLY aggregate owned by BC
``installation-and-bootstrap`` that detects which AgentKit-managed surfaces a
project has deliberately customised. It combines FOUR owner-BC sources, each
read ONLY through the owner's canonical top/read surface — never through a
direct filesystem reach into a foreign BC's internal structures (FK-51 §51.8,
story §5 / §6):

1. Pipeline-config thresholds (BC ``pipeline-framework``, FK-03): detected by
   comparing the on-disk ``project.yaml`` digest against the registered
   ``config_digest`` (``ProjectRegistration.config_digest``). The config is read
   through ``load_project_config`` (the model is the owner surface; the digest is
   the customization key). A digest mismatch means the user edited the config.
2. CCAG rules (BC ``governance-and-guards``): read through ``load_rules`` — any
   project-local rule beyond the empty baseline is a customization.
3. Prompt bundle binding (BC ``prompt-runtime``): read through
   ``resolve_project_prompt_binding`` -> ``PromptBundleBinding``. A binding pinned
   to a non-default bundle/version is a deliberate customization.
4. Skill binding (BC ``agent-skills``): read through ``Skills.resolve_binding`` —
   a skill pinned to a non-default bundle/version is a deliberate customization.

**Invariant F-51-023 (never silently overwrite):** a write path in CLEANUP or a
BINDING change that would touch a customization the footprint detected MUST
block/report and MUST NOT mutate (story AC8). The §51.3.2 config migration is
EXEMPT — there ``.bak`` + write is the FK-prescribed path (story §6); the
invariant guards the non-migrating write paths (cleanup / binding / git-hook).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.exceptions import InstallationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from agentkit.installer.repository import ProjectRegistrationRepository
    from agentkit.skills import Skills


class CustomizationKind(StrEnum):
    """The four FK-51 §51.8 customization sources (typed, not strings).

    Attributes:
        PIPELINE_CONFIG: A pipeline-config threshold edit (digest mismatch).
        CCAG_RULE: A project-specific CCAG rule.
        PROMPT_BINDING: A deliberate prompt-bundle binding.
        SKILL_BINDING: A deliberate skill binding.
    """

    PIPELINE_CONFIG = "pipeline_config"
    CCAG_RULE = "ccag_rule"
    PROMPT_BINDING = "prompt_binding"
    SKILL_BINDING = "skill_binding"


@dataclass(frozen=True)
class CustomizationPoint:
    """A single detected customization (FK-51 §51.8).

    Attributes:
        kind: The :class:`CustomizationKind` source this point came from.
        identifier: A stable, human-readable identity of the customised surface
            (e.g. the config path, a rule id, a ``bundle_id@version`` binding, or
            ``skill_name@version``). Lets a write path tell whether the artefact
            it is about to touch is a detected customization.
        detail: Human-readable description of what was detected.
    """

    kind: CustomizationKind
    identifier: str
    detail: str


class CustomizationPreservationError(InstallationError):
    """A write path tried to overwrite a detected customization (F-51-023).

    Raised by :meth:`CustomizationFootprint.guard_write` when a CLEANUP or
    BINDING write path would touch a customization the footprint detected. The
    write is blocked and NOTHING is mutated (story AC8). It is an
    :class:`InstallationError` so the upgrade flow surfaces it fail-closed.
    """


@dataclass(frozen=True)
class CustomizationFootprint:
    """Read-aggregate of detected project customizations (FK-51 §51.8).

    Built by :meth:`detect`; never writes to any BC. Carries the detected
    :class:`CustomizationPoint` entries and enforces the never-silently-overwrite
    invariant F-51-023 for the non-migrating write paths.

    Attributes:
        points: The detected customization points (possibly empty).
    """

    points: tuple[CustomizationPoint, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """Return whether no customization was detected."""
        return not self.points

    def points_of(self, kind: CustomizationKind) -> tuple[CustomizationPoint, ...]:
        """Return the detected points of a given :class:`CustomizationKind`."""
        return tuple(point for point in self.points if point.kind is kind)

    def covers(self, identifier: str) -> bool:
        """Return whether a customization with ``identifier`` was detected."""
        return any(point.identifier == identifier for point in self.points)

    def guard_write(self, identifier: str, *, write_path: str) -> None:
        """Enforce F-51-023 for a single non-migrating write (story AC8).

        A CLEANUP or BINDING write path calls this BEFORE mutating the artefact
        named ``identifier``. When the footprint detected a customization at that
        identifier the write is blocked fail-closed
        (:class:`CustomizationPreservationError`) and the caller MUST NOT mutate.

        Args:
            identifier: The stable identity of the artefact about to be written.
            write_path: A short label of the calling write path (``cleanup`` /
                ``binding`` / ``git_hook``) for the error/report message.

        Raises:
            CustomizationPreservationError: When ``identifier`` is a detected
                customization (F-51-023 — never silently overwrite).
        """
        if self.covers(identifier):
            raise CustomizationPreservationError(
                f"Write path {write_path!r} would overwrite a detected "
                f"customization {identifier!r}; blocked by F-51-023 (FK-51 §51.8 — "
                "detected customizations are never silently overwritten). Mirror "
                "this to the operator (WARNING/ESCALATE) before any change.",
                detail={
                    "identifier": identifier,
                    "write_path": write_path,
                    "invariant": "F-51-023",
                },
            )

    @classmethod
    def detect(
        cls,
        project_root: Path,
        *,
        registration_repo: ProjectRegistrationRepository,
        project_key: str,
        is_subagent: bool = False,
        skills: Skills | None = None,
    ) -> CustomizationFootprint:
        """Detect customizations across the four owner surfaces (FK-51 §51.8).

        Each source is read ONLY through its owner-BC top/read surface; a source
        whose surface is absent/unconfigured contributes no point (it is simply
        "not customised here") rather than failing the detection — detection is a
        read aggregate, not a precondition gate.

        Args:
            project_root: The target-project root.
            registration_repo: The CP 7 registration read surface (the registered
                ``config_digest`` is the pipeline-config customization key).
            project_key: The project key used to look up the registration.
            is_subagent: Scope flag forwarded to ``load_rules`` (CCAG source).
            skills: The agent-skills top surface to read skill bindings through
                (DI). When ``None`` the default productive surface is built
                (``Skills.resolve_binding`` is still the only access path — this
                is composition, not a second truth).

        Returns:
            The assembled :class:`CustomizationFootprint`.
        """
        points: list[CustomizationPoint] = []
        points.extend(
            _detect_pipeline_config(project_root, registration_repo, project_key)
        )
        points.extend(_detect_ccag_rules(project_root, is_subagent=is_subagent))
        points.extend(_detect_prompt_binding(project_root))
        points.extend(_detect_skill_bindings(project_root, project_key, skills=skills))
        return cls(points=tuple(points))


def _detect_pipeline_config(
    project_root: Path,
    registration_repo: ProjectRegistrationRepository,
    project_key: str,
) -> Iterable[CustomizationPoint]:
    """Detect a pipeline-config threshold edit via digest mismatch (FK-03 source).

    FK-51 §51.8 table: the pipeline-config source is read through the OWNER read
    surface ``load_project_config`` / ``PipelineConfig`` (BC ``pipeline-framework``,
    FK-03) — consistent with the other three owner-surface reads (``load_rules``,
    ``resolve_project_prompt_binding``, ``Skills.resolve_binding``), never a raw
    filesystem reach. ``load_project_config`` validates the config against the
    owner schema; only a config the owner accepts is compared. The customization
    SIGNAL is then the DIGEST comparison (FK-51 §51.8): the
    on-disk ``project.yaml`` digest versus the registered ``config_digest``. A
    mismatch means the user edited the config after registration. No registration,
    no on-disk config, or a config the owner surface rejects -> no point (a read
    aggregate, not a precondition gate; the upgrade flow's migration handles a
    not-yet-current/malformed config).
    """
    from agentkit.config.loader import load_project_config
    from agentkit.exceptions import ConfigError
    from agentkit.installer.paths import project_config_path
    from agentkit.installer.upgrade._digest import config_file_digest

    registration = registration_repo.get(project_key)
    if registration is None:
        return ()
    config_path = project_config_path(project_root)
    if not config_path.is_file():
        return ()
    try:
        # Read through the owner BC read surface (FK-51 §51.8 table): the config
        # must be a valid ``PipelineConfig`` the owner accepts before the digest
        # signal is compared. A config the owner rejects contributes no point.
        load_project_config(project_root)
        on_disk_digest = config_file_digest(config_path)
    except (ConfigError, OSError):
        return ()
    if on_disk_digest == registration.config_digest:
        return ()
    return (
        CustomizationPoint(
            kind=CustomizationKind.PIPELINE_CONFIG,
            identifier=str(config_path),
            detail=(
                "project.yaml digest differs from the registered config_digest "
                f"({registration.config_digest[:12]} != {on_disk_digest[:12]}); "
                "the user edited the pipeline config."
            ),
        ),
    )


def _detect_ccag_rules(
    project_root: Path, *, is_subagent: bool
) -> Iterable[CustomizationPoint]:
    """Detect project-specific CCAG rules via ``load_rules`` (owner surface).

    Reads the project's CCAG rule set through the runtime read surface
    ``load_rules`` (BC ``governance-and-guards``). Any block/allow rule present is
    a project-specific customization (the baseline ships no project rules).
    """
    from agentkit.governance.ccag.rules import DEFAULT_RULES_SUBDIR, load_rules

    rules_dir = project_root / DEFAULT_RULES_SUBDIR
    if not rules_dir.is_dir():
        return ()
    rule_set = load_rules(is_subagent, rules_dir=rules_dir)
    rules = (*rule_set.blocks, *rule_set.allows)
    return tuple(
        CustomizationPoint(
            kind=CustomizationKind.CCAG_RULE,
            identifier=f"ccag:{rule.rule_id}",
            detail=f"Project-specific CCAG rule {rule.rule_id!r} present.",
        )
        for rule in rules
    )


def _detect_prompt_binding(project_root: Path) -> Iterable[CustomizationPoint]:
    """Detect a deliberate prompt-bundle binding via the prompt-runtime surface.

    Reads the project binding through ``resolve_project_prompt_binding`` ->
    ``PromptBundleBinding`` (BC ``prompt-runtime``). A present project binding
    (a pinned bundle lock) is a deliberate binding customization. A project with
    no lock (``ProjectError``) contributes no point.
    """
    from agentkit.exceptions import ProjectError
    from agentkit.prompt_runtime.resources import resolve_project_prompt_binding

    try:
        binding = resolve_project_prompt_binding(project_root)
    except ProjectError:
        return ()
    return (
        CustomizationPoint(
            kind=CustomizationKind.PROMPT_BINDING,
            identifier=f"prompt:{binding.bundle_id}@{binding.bundle_version}",
            detail=(
                f"Project prompt binding pinned to {binding.bundle_id}@"
                f"{binding.bundle_version}."
            ),
        ),
    )


def _detect_skill_bindings(
    project_root: Path, project_key: str, *, skills: Skills | None
) -> Iterable[CustomizationPoint]:
    """Detect deliberate skill bindings via ``Skills.resolve_binding`` (FK-43).

    Reads each known skill binding through the agent-skills top surface
    ``Skills.resolve_binding(project_root, skill_name)``. A bound skill is a
    deliberate binding customization. A surface that cannot be built (no skills
    component) contributes no point.
    """
    from agentkit.installer.runner import MANDATORY_SKILLS
    from agentkit.installer.upgrade._skills_surface import build_skills_surface

    surface = skills if skills is not None else build_skills_surface(project_root)
    if surface is None:
        return ()
    points: list[CustomizationPoint] = []
    for skill_name in MANDATORY_SKILLS:
        binding = surface.resolve_binding(project_root, skill_name)
        if binding is None:
            continue
        points.append(
            CustomizationPoint(
                kind=CustomizationKind.SKILL_BINDING,
                identifier=f"skill:{binding.skill_name}@{binding.bundle_version}",
                detail=(
                    f"Skill {binding.skill_name!r} bound to "
                    f"{binding.bundle_id}@{binding.bundle_version}."
                ),
            )
        )
    return tuple(points)


__all__ = [
    "CustomizationFootprint",
    "CustomizationKind",
    "CustomizationPoint",
    "CustomizationPreservationError",
]
