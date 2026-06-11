"""SkillUsageCheck guard — enforces normative skill usage (F-43-030).

FK-43 §43.6.2 / F-43-030 (FK-12-030): agents MUST use a shipped skill for a
standardized task instead of ad-hoc methodology. The enforcement owner is
``governance.guard_system`` (FK-30 §30.5.1): the ``skill_usage_check`` hook
detects, at runtime BEFORE the tool call, whether an agent uses ad-hoc
methodology while a MATCHING skill exists AND its precondition is met. On
detection it BLOCKS the tool call and points at the skill.

Detection model (typed, no String-Map cascade): a :class:`SkillUsageRule` maps a
recognised ad-hoc tool-call SIGNAL (operation + structured arg pattern) to a
required ``skill_name`` and a typed :class:`SkillPrecondition`. The guard blocks
iff ALL of:

1. a rule's signal matches the observed tool call (ad-hoc methodology detected);
2. the matching skill EXISTS (a project binding is resolvable via the Skills
   surface — consumed, NOT rebuilt: FK-43 §43.1 ``resolve_binding``);
3. the skill's precondition is MET (e.g. ``features.are`` for the ARE skills);
4. the agent did NOT invoke the skill (no ``--via-skill=<skill>`` structural
   marker — read ONLY from ``cli_args``, never prompt/command text, FK-55 §55.3a).

On a block the guard emits an ``integrity_violation`` block audit
(``guard="skill_usage_check"``, ``detail``, NO ``stage`` — the ``stage`` field is
prompt-integrity-specific, FK-61 §61.12.2 / FK-68 §68.2; FK-68 §68.3.1 lists
``SkillUsageCheck`` explicitly as an ``integrity_violation`` emitter; FK-30
§30.7.3).

Story-creation bypass detection is owned by ``story_creation_guard`` (FK-31
§31.5); this guard deliberately does NOT duplicate it (no second mechanism).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter

#: Guard identifier (matches the FK-30 §30.5.1 hook id ``skill_usage_check``).
GUARD_NAME = "skill_usage_check"

#: FK-43 §43.6.2 / F-43-030 rule id surfaced on a block.
RULE_ID = "F-43-030"

#: Structural CLI marker flag the skills emit (``--via-skill=<skill-name>``). Read
#: ONLY from ``cli_args`` (a structural channel), never prompt/command text
#: (FK-55 §55.3a). A convention, not an attestation — the fail-closed teeth are
#: that an ad-hoc call simply carries no such marker.
_CLI_SKILL_FLAG = "--via-skill"


class SkillPrecondition(StrEnum):
    """Typed precondition gating a normative skill (FK-43 §43.3.2).

    Attributes:
        ALWAYS: The skill applies unconditionally (shipped mandatory skills).
        FEATURE_ARE: The skill applies only when ``features.are`` is enabled
            (e.g. ``manage-requirements`` — FK-43 §43.3.2 ``features.are: true``).
    """

    ALWAYS = "always"
    FEATURE_ARE = "feature_are"


@dataclass(frozen=True)
class SkillUsageSignal:
    """Typed ad-hoc tool-call signal a :class:`SkillUsageRule` matches on.

    A signal matches when the observed tool name equals :attr:`tool` AND every
    token in :attr:`command_tokens` appears (case-insensitively, contiguous) in
    the observed command. An empty :attr:`command_tokens` matches on the tool
    name alone. This is a cheap structural pattern (FK-55 §55.10.2: no expensive
    semantic shell interpretation).

    Attributes:
        tool: The tool name the ad-hoc call uses (e.g. ``"Bash"``).
        command_tokens: Ordered command tokens that must appear contiguously
            (lower-cased) in the observed command, or empty for a tool-only match.
    """

    tool: str
    command_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillUsageRule:
    """Maps an ad-hoc tool-call signal to the required skill (F-43-030).

    Attributes:
        signal: The structural signal that flags ad-hoc methodology.
        skill_name: The skill the agent MUST use instead.
        precondition: The typed precondition gating the skill.
    """

    signal: SkillUsageSignal
    skill_name: str
    precondition: SkillPrecondition = SkillPrecondition.ALWAYS


#: Default normative rule registry (FK-43 §43.3 shipped skills). Seeded with the
#: documented standardized tasks whose ad-hoc shape is cheaply recognisable:
#:
#: - a ``semantic-review`` performed ad-hoc (FK-43 §43.3.2 / F-43-029) instead of
#:   the shipped ``semantic-review`` skill;
#: - an ARE requirements mutation performed ad-hoc instead of the
#:   ``manage-requirements`` skill (precondition ``features.are``, FK-43 §43.3.2).
#:
#: Story creation is deliberately ABSENT — it is owned by ``story_creation_guard``
#: (FK-31 §31.5); duplicating it here would be a second mechanism.
DEFAULT_SKILL_USAGE_RULES: tuple[SkillUsageRule, ...] = (
    SkillUsageRule(
        signal=SkillUsageSignal(tool="Bash", command_tokens=("agentkit", "semantic-review")),
        skill_name="semantic-review",
        precondition=SkillPrecondition.ALWAYS,
    ),
    SkillUsageRule(
        signal=SkillUsageSignal(tool="Bash", command_tokens=("agentkit", "requirements")),
        skill_name="manage-requirements",
        precondition=SkillPrecondition.FEATURE_ARE,
    ),
)


@dataclass(frozen=True)
class SkillUsageObservation:
    """Typed harness-neutral input for :meth:`SkillUsageCheckGuard.evaluate`.

    Attributes:
        story_id: Active story identifier (audit correlation).
        run_id: Active run identifier (audit correlation).
        project_key: Owning project key (audit correlation + binding lookup).
        tool: The observed tool name (e.g. ``"Bash"``).
        command: The observed command string for ``Bash`` (empty otherwise).
        cli_args: Structural CLI args (the ONLY place the ``--via-skill`` marker
            is read from; never the command body — FK-55 §55.3a).
        feature_are: Whether ``features.are`` is enabled (FEATURE_ARE gating).
        phase: Pipeline phase name, when known (carried onto the audit event).
    """

    story_id: str
    run_id: str
    project_key: str
    tool: str
    command: str = ""
    cli_args: tuple[str, ...] = ()
    feature_are: bool = False
    phase: str | None = None


class SkillBindingLookup(Protocol):
    """Read port for "does a matching skill binding exist?" (consume, not rebuild).

    Satisfied by :meth:`agentkit.skills.top.Skills.resolve_binding`-style lookups.
    The guard only needs a boolean existence check keyed by ``(project_key,
    skill_name)``; it never imports the Skills BC implementation.
    """

    def is_bound(self, project_key: str, skill_name: str) -> bool:
        """Return ``True`` when a project binding for ``skill_name`` exists."""
        ...


@dataclass(frozen=True)
class SkillUsageDecision:
    """Outcome of a :meth:`SkillUsageCheckGuard.evaluate` call.

    Attributes:
        verdict: The blocking / allowing :class:`GuardVerdict`.
        audit_events: The ``integrity_violation`` audit events to persist (empty
            on allow).
        matched_skill: The skill the agent should have used (``None`` on allow).
    """

    verdict: GuardVerdict
    audit_events: tuple[Event, ...] = ()
    matched_skill: str | None = None


class SkillUsageCheckGuard:
    """Blocks ad-hoc methodology when a matching skill exists (F-43-030).

    Args:
        binding_lookup: Read port answering "is a matching skill bound?" — the
            Skills surface is CONSUMED, never re-implemented (FK-43 §43.1).
        emitter: Telemetry emitter used to persist the ``integrity_violation``
            block audit (FK-68 §68.3.1 / FK-30 §30.7.3).
        rules: The typed normative rule registry. Defaults to
            :data:`DEFAULT_SKILL_USAGE_RULES`.
    """

    name = GUARD_NAME

    def __init__(
        self,
        binding_lookup: SkillBindingLookup,
        emitter: EventEmitter,
        *,
        rules: tuple[SkillUsageRule, ...] = DEFAULT_SKILL_USAGE_RULES,
    ) -> None:
        self._binding_lookup = binding_lookup
        self._emitter = emitter
        self._rules = rules

    def evaluate(self, observation: SkillUsageObservation) -> SkillUsageDecision:
        """Decide whether an ad-hoc tool call must be blocked (F-43-030).

        Args:
            observation: The harness-neutral observation.

        Returns:
            A :class:`SkillUsageDecision`. A block carries one
            ``integrity_violation`` audit event and the matched skill name.
        """
        rule = self._first_matching_rule(observation)
        if rule is None:
            return SkillUsageDecision(verdict=GuardVerdict.allow(self.name))

        # The agent already invoked the skill (structural marker) -> allow.
        if self._has_skill_marker(observation, rule.skill_name):
            return SkillUsageDecision(verdict=GuardVerdict.allow(self.name))

        # The skill's precondition must be met for the norm to apply (F-43-030
        # "sofern deren Voraussetzung erfuellt ist").
        if not self._precondition_met(rule.precondition, observation):
            return SkillUsageDecision(verdict=GuardVerdict.allow(self.name))

        # A MATCHING skill must EXIST (be bound) for the block to fire — we cannot
        # force usage of a skill the project has not bound.
        if not self._binding_lookup.is_bound(observation.project_key, rule.skill_name):
            return SkillUsageDecision(verdict=GuardVerdict.allow(self.name))

        detail = (
            f"ad_hoc_tool_use_blocked: use the {rule.skill_name!r} skill for this "
            f"standardized task (F-43-030)"
        )
        verdict = GuardVerdict.block(
            self.name,
            ViolationType.POLICY_VIOLATION,
            detail,
            detail={
                "rule_id": RULE_ID,
                "skill_name": rule.skill_name,
                "tool": observation.tool,
            },
        )
        return SkillUsageDecision(
            verdict=verdict,
            audit_events=(self._integrity_violation(observation, detail),),
            matched_skill=rule.skill_name,
        )

    def evaluate_and_emit(
        self, observation: SkillUsageObservation
    ) -> SkillUsageDecision:
        """Evaluate and persist any ``integrity_violation`` audit events.

        Args:
            observation: The harness-neutral observation.

        Returns:
            The :class:`SkillUsageDecision`; its ``audit_events`` have already
            been emitted through the canonical telemetry emitter.
        """
        decision = self.evaluate(observation)
        for event in decision.audit_events:
            self._emitter.emit(event)
        return decision

    def _first_matching_rule(
        self, observation: SkillUsageObservation
    ) -> SkillUsageRule | None:
        for rule in self._rules:
            if _signal_matches(rule.signal, observation.tool, observation.command):
                return rule
        return None

    @staticmethod
    def _precondition_met(
        precondition: SkillPrecondition, observation: SkillUsageObservation
    ) -> bool:
        if precondition is SkillPrecondition.ALWAYS:
            return True
        if precondition is SkillPrecondition.FEATURE_ARE:
            return observation.feature_are
        return False  # pragma: no cover - exhaustive StrEnum

    @staticmethod
    def _has_skill_marker(
        observation: SkillUsageObservation, skill_name: str
    ) -> bool:
        """Whether the structural ``--via-skill=<skill_name>`` marker is present.

        Read ONLY from ``cli_args`` (a structural channel) — never the command
        body (FK-55 §55.3a).
        """
        for token in observation.cli_args:
            flag, _, value = token.partition("=")
            if flag == _CLI_SKILL_FLAG and value == skill_name:
                return True
        return False

    def _integrity_violation(
        self, observation: SkillUsageObservation, detail: str
    ) -> Event:
        """Build the ``integrity_violation`` block audit (FK-68 §68.3.1).

        Carries ``guard``/``detail`` (mandatory for every ``integrity_violation``)
        and NO ``stage`` (prompt-integrity-specific, FK-61 §61.12.2).
        """
        return Event(
            story_id=observation.story_id,
            event_type=EventType.INTEGRITY_VIOLATION,
            project_key=observation.project_key,
            run_id=observation.run_id,
            phase=observation.phase,
            source_component=self.name,
            severity="error",
            payload={"guard": self.name, "detail": detail},
        )


def _signal_matches(signal: SkillUsageSignal, tool: str, command: str) -> bool:
    """Whether ``signal`` matches the observed ``tool`` / ``command`` (cheap scan)."""
    if signal.tool != tool:
        return False
    if not signal.command_tokens:
        return True
    tokens = [tok.lower() for tok in command.split()]
    width = len(signal.command_tokens)
    wanted = tuple(t.lower() for t in signal.command_tokens)
    return any(
        tuple(tokens[start : start + width]) == wanted
        for start in range(len(tokens) - width + 1)
    )


__all__ = [
    "DEFAULT_SKILL_USAGE_RULES",
    "GUARD_NAME",
    "RULE_ID",
    "SkillBindingLookup",
    "SkillPrecondition",
    "SkillUsageCheckGuard",
    "SkillUsageDecision",
    "SkillUsageObservation",
    "SkillUsageRule",
    "SkillUsageSignal",
]
