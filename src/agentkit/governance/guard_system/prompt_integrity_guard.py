"""PromptIntegrityGuard — mode-specific spawn integrity (FK-31 §31.7).

PreToolUse hook intercepting EVERY ``Agent`` tool call (sub-agent spawn) before
execution to prevent unauthorized spawning, prompt injection, governance bypass
and template manipulation. The guard is PERMANENTLY active (both ``ai_augmented``
and ``story_execution``), but NOT permanently equally strict (FK-31 §31.7.1
Modusgrenze). Three check stages (FK-31 §31.7.2):

- Stage 1 — governance-escape detection (regex, NO LLM): adversarial /
  prompt-injection patterns. Active in BOTH modes (permanent).
- Stage 2 — spawn-schema validation of the ``AGENTKIT-SUBAGENT-V1`` header
  (CONSUMED from the existing SKILL.md resource contract, NOT reinvented):
    * ``ai_augmented``  (freestyle): lightweight schema — ``role=general`` with
      ``skill_proof=null`` is admissible; a missing / structurally invalid header
      is a block.
    * ``story_execution``: full schema — a valid ``skill_proof`` token (from the
      installed manifest), ``mode=story_execution`` and a non-empty ``story_id``.
- Stage 3 — template integrity (digest compare): ONLY in ``story_execution``.
  The ACTUAL prompt the agent receives (the ``prompt_file`` CONTENT when a
  ``prompt_file`` is given -- PROD-A -- otherwise the inline ``prompt`` --
  PROD-B) must hash to one of the INSTALLED/PINNED prompt-audit ``output_sha256``
  digests for the run (FK-31 §31.7.4 / FK-44 §44.6). That baseline is the digest
  of the exact bytes the pipeline materialized from a manifest-pinned bundle
  template (the template digests are folded into the bundle manifest hash at
  install) -- it is NOT the spawn-supplied ``prompt_file`` path, so a worker can
  neither author the baseline nor point ``prompt_file`` at a self-made file to
  satisfy it. QA agents are EXEMPT (dynamic prompts). Stage 3 does NOT run in
  ``ai_augmented``.

Opaque failure (FK-31 §31.7.3): the OUTBOUND block message is exactly
``"Operation not permitted."`` with NO stage / diff. The failing stage is
recorded ONLY in the telemetry ``integrity_violation`` event
(``guard="prompt_integrity_guard"``, ``stage ∈ {escape_detection,
schema_validation, template_integrity}`` — FK-61 §61.12.2 / FK-68 §68.2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.telemetry.events import (
    INTEGRITY_VIOLATION_PROMPT_GUARD,
    Event,
    EventType,
)

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter

#: Guard identifier (FK-30 §30.5.1 / FK-61 §61.12.2 wortgleich).
GUARD_NAME = INTEGRITY_VIOLATION_PROMPT_GUARD

#: Opaque outbound block message (FK-31 §31.7.3 — Exit 2, no detail).
OPAQUE_MESSAGE = "Operation not permitted."

#: Spawn-schema header token (SKILL.md resource contract).
HEADER_TOKEN = "AGENTKIT-SUBAGENT-V1"

#: Freestyle role admissible with ``skill_proof=null`` (SKILL.md / FK-31 §31.7.2).
_FREESTYLE_ROLE = "general"

#: Roles that are QA agents -> Stage 3 template integrity is EXEMPT (dynamic
#: prompts, FK-31 §31.7.2). The SKILL.md header role vocabulary uses these.
_QA_AGENT_ROLES: frozenset[str] = frozenset({"story-qa", "story-adversarial"})

#: Governance-escape patterns (FK-31 §31.7.2 Stage 1, regex, no LLM). Compiled
#: case-insensitively; the list is the typed adversarial vocabulary, not an
#: ad-hoc string scan.
_ESCAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"bypass\s+governance", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous)\s+", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+free", re.IGNORECASE),
    re.compile(r"ignore\s+the\s+(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"override\s+(the\s+)?guard", re.IGNORECASE),
)


class PromptIntegrityStage(StrEnum):
    """The three FK-31 §31.7.2 check stages (telemetry ``stage`` values)."""

    ESCAPE_DETECTION = "escape_detection"
    SCHEMA_VALIDATION = "schema_validation"
    TEMPLATE_INTEGRITY = "template_integrity"


class SpawnMode(StrEnum):
    """The two prompt-integrity-relevant spawn modes (FK-31 §31.7.1)."""

    AI_AUGMENTED = "ai_augmented"
    STORY_EXECUTION = "story_execution"


@dataclass(frozen=True)
class SpawnHeader:
    """Parsed ``AGENTKIT-SUBAGENT-V1`` header (SKILL.md resource contract).

    Attributes:
        mode: The declared spawn mode (``freestyle`` / ``story_execution``).
        role: The declared agent role (e.g. ``general``, ``story-qa``).
        story_id: The declared story id, or ``None``/``"null"`` when absent.
        skill_proof: The declared skill-proof token, or ``None`` when ``null``.
    """

    mode: str
    role: str
    story_id: str | None
    skill_proof: str | None


@dataclass(frozen=True)
class SpawnObservation:
    """Typed harness-neutral input for :meth:`PromptIntegrityGuard.evaluate`.

    Attributes:
        story_id: Active story identifier (audit correlation).
        run_id: Active run identifier (audit correlation).
        project_key: Owning project key (audit correlation).
        mode: The operating mode the spawn happens in (FK-31 §31.7.1).
        description: The raw ``Agent`` ``description`` carrying the header.
        prompt: The inline spawn ``prompt`` text (PROD-B). Always scanned in
            Stage 1; it is the Stage-3 comparison target only when no
            ``prompt_file_content`` is supplied.
        prompt_file_content: The CONTENT of the authorised ``prompt_file`` when
            the spawn passes one (PROD-A), already resolved from disk by the
            dispatch. ``None`` when the spawn carries no ``prompt_file``. When
            present it is the actual prompt the agent receives and is the Stage-3
            comparison target (and is also scanned in Stage 1).
        expected_skill_proof: The skill-proof token from the installed manifest
            (the AUTHORITATIVE value; Stage 2 story_execution). Empty when none
            installed (a story_execution spawn then fails Stage 2 fail-closed).
        pinned_output_hashes: The INSTALLED/PINNED prompt-audit ``output_sha256``
            digests for the run (FK-31 §31.7.4 / FK-44 §44.6) -- the manifest-hashed
            baseline Stage 3 compares against. Empty when none materialized; a
            story_execution spawn then has no pinned baseline and is fail-closed
            blocked at Stage 3.
        phase: Pipeline phase name, when known (carried onto the audit event).
    """

    story_id: str
    run_id: str
    project_key: str
    mode: SpawnMode
    description: str = ""
    prompt: str = ""
    prompt_file_content: str | None = None
    expected_skill_proof: str = ""
    pinned_output_hashes: frozenset[str] = field(default_factory=frozenset)
    phase: str | None = None


@dataclass(frozen=True)
class PromptIntegrityDecision:
    """Outcome of a :meth:`PromptIntegrityGuard.evaluate` call.

    Attributes:
        verdict: The blocking / allowing :class:`GuardVerdict`. A block carries
            the OPAQUE outbound message (FK-31 §31.7.3) — never the failing stage.
        audit_events: The ``integrity_violation`` audit events to persist (empty
            on allow). The failing ``stage`` lives ONLY here.
        stage: The failing :class:`PromptIntegrityStage` (``None`` on allow).
    """

    verdict: GuardVerdict
    audit_events: tuple[Event, ...] = ()
    stage: PromptIntegrityStage | None = None


class PromptIntegrityGuard:
    """Mode-specific spawn-integrity guard (FK-31 §31.7).

    Args:
        emitter: Telemetry emitter used to persist the ``integrity_violation``
            block audit (FK-68 §68.2 / §68.3.1). The audit carries the per-stage
            ``stage`` field; the outbound block message stays opaque.
    """

    name = GUARD_NAME

    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter

    def evaluate(self, observation: SpawnObservation) -> PromptIntegrityDecision:
        """Run the three FK-31 §31.7.2 stages mode-specific.

        Args:
            observation: The harness-neutral spawn observation.

        Returns:
            A :class:`PromptIntegrityDecision`. On a block the verdict carries the
            opaque message and one ``integrity_violation`` audit event names the
            failing stage; on allow the verdict allows and no event is produced.
        """
        # Stage 1 — governance-escape detection (BOTH modes, permanent). Scans
        # the description, the inline prompt AND the prompt_file content (the
        # actual prompt the agent receives in PROD-A), so an injection hidden in
        # a prompt_file cannot slip past escape detection.
        scan_text = (
            f"{observation.description}\n{observation.prompt}\n"
            f"{observation.prompt_file_content or ''}"
        )
        if _has_escape_pattern(scan_text):
            return self._block(observation, PromptIntegrityStage.ESCAPE_DETECTION)

        # Stage 2 — spawn-schema validation (mode-specific).
        header = parse_spawn_header(observation.description)
        schema_ok = (
            self._story_execution_schema_ok(header, observation)
            if observation.mode is SpawnMode.STORY_EXECUTION
            else self._freestyle_schema_ok(header)
        )
        if not schema_ok:
            return self._block(observation, PromptIntegrityStage.SCHEMA_VALIDATION)

        # Stage 3 — template integrity (ONLY story_execution; QA agents exempt).
        if observation.mode is SpawnMode.STORY_EXECUTION:
            if header is not None and header.role in _QA_AGENT_ROLES:
                return PromptIntegrityDecision(verdict=GuardVerdict.allow(self.name))
            if not self._template_ok(observation):
                return self._block(
                    observation, PromptIntegrityStage.TEMPLATE_INTEGRITY
                )

        return PromptIntegrityDecision(verdict=GuardVerdict.allow(self.name))

    def evaluate_and_emit(
        self, observation: SpawnObservation
    ) -> PromptIntegrityDecision:
        """Evaluate and persist any ``integrity_violation`` audit events.

        Args:
            observation: The harness-neutral spawn observation.

        Returns:
            The :class:`PromptIntegrityDecision`; its ``audit_events`` have already
            been emitted through the canonical telemetry emitter.
        """
        decision = self.evaluate(observation)
        for event in decision.audit_events:
            self._emitter.emit(event)
        return decision

    @staticmethod
    def _freestyle_schema_ok(header: SpawnHeader | None) -> bool:
        """Lightweight freestyle schema (FK-31 §31.7.2 ``ai_augmented``).

        FK-31 §31.7.2 verbatim: "Im Freestyle-Modus: nur ``role=general`` mit
        ``skill_proof=null``." The freestyle schema therefore admits EXACTLY one
        shape — a structurally valid header whose ``role`` is ``general`` AND whose
        ``skill_proof`` is ``null`` (parsed to ``None``). A missing /
        structurally invalid header, any non-``general`` role, or a non-null
        ``skill_proof`` is a block (fail-closed). Admitting a non-``general`` role
        here would contradict the concept and let a spawn impersonate a
        privileged role without the story_execution proof obligation.
        """
        if header is None:
            return False
        return header.role == _FREESTYLE_ROLE and header.skill_proof is None

    @staticmethod
    def _story_execution_schema_ok(
        header: SpawnHeader | None, observation: SpawnObservation
    ) -> bool:
        """Full story_execution schema (FK-31 §31.7.2 ``story_execution``).

        Requires ``mode=story_execution``, a non-empty ``story_id`` and a valid
        ``skill_proof`` token matching the installed manifest (fail-closed when no
        proof is installed).
        """
        if header is None:
            return False
        if header.mode != SpawnMode.STORY_EXECUTION.value:
            return False
        if not header.story_id:
            return False
        if not observation.expected_skill_proof:
            # No authoritative proof installed -> cannot validate -> fail-closed.
            return False
        return header.skill_proof == observation.expected_skill_proof

    @staticmethod
    def _template_ok(observation: SpawnObservation) -> bool:
        """Pinned-baseline integrity check (FK-31 §31.7.4 / FK-44 §44.6).

        The ACTUAL prompt the agent receives -- the ``prompt_file`` CONTENT when
        a ``prompt_file`` was passed (PROD-A), otherwise the inline ``prompt``
        (PROD-B) -- must hash to one of the INSTALLED/PINNED prompt-audit
        ``output_sha256`` digests for the run. That baseline is the digest of the
        exact bytes the pipeline materialized from a manifest-pinned bundle
        template; it is NOT the spawn-supplied path, closing the self-referential
        hole (a self-authored ``prompt_file`` the pipeline never materialized has
        no matching pinned digest).

        Fail-closed: with no pinned baseline installed for the run there is
        nothing authoritative to verify against, so a story_execution spawn
        blocks. An empty actual prompt also blocks (nothing to verify).
        """
        if not observation.pinned_output_hashes:
            # No authoritative pinned baseline for the run -> cannot verify.
            return False
        actual_prompt = (
            observation.prompt_file_content
            if observation.prompt_file_content is not None
            else observation.prompt
        )
        if not actual_prompt:
            return False
        actual_digest = hashlib.sha256(actual_prompt.encode("utf-8")).hexdigest()
        return actual_digest in observation.pinned_output_hashes

    def _block(
        self, observation: SpawnObservation, stage: PromptIntegrityStage
    ) -> PromptIntegrityDecision:
        """Build an opaque block verdict + the per-stage ``integrity_violation``."""
        verdict = GuardVerdict.block(
            self.name,
            ViolationType.INTEGRITY_FAILURE,
            OPAQUE_MESSAGE,
            # The detail dict is for the audit trail only; the outbound MESSAGE
            # stays opaque (FK-31 §31.7.3). The stage is NOT leaked in the message.
            detail={"guard": self.name, "stage": stage.value},
        )
        event = Event(
            story_id=observation.story_id,
            event_type=EventType.INTEGRITY_VIOLATION,
            project_key=observation.project_key,
            run_id=observation.run_id,
            phase=observation.phase,
            source_component=self.name,
            severity="error",
            payload={
                "guard": self.name,
                "detail": f"prompt_integrity_block: {stage.value}",
                "stage": stage.value,
            },
        )
        return PromptIntegrityDecision(
            verdict=verdict, audit_events=(event,), stage=stage
        )


def parse_spawn_header(description: str) -> SpawnHeader | None:
    """Parse the ``AGENTKIT-SUBAGENT-V1`` header from a spawn ``description``.

    CONSUMES the existing SKILL.md resource contract
    (``AGENTKIT-SUBAGENT-V1 mode=X role=Y story_id=Z skill_proof=W``); the format
    is NOT reinvented here. Returns ``None`` when no structurally valid header
    line is present (a missing / malformed header is a Stage-2 block upstream).

    Args:
        description: The raw ``Agent`` ``description`` whose first line carries
            the header.

    Returns:
        The parsed :class:`SpawnHeader`, or ``None`` when absent / malformed.
    """
    if HEADER_TOKEN not in description:
        return None
    # The header is the line that begins with the token (SKILL.md §"Mandatory
    # Agent Spawn Header" — the description STARTS with this exact schema header).
    line = next(
        (
            ln
            for ln in description.splitlines()
            if ln.strip().startswith(HEADER_TOKEN)
        ),
        "",
    )
    if not line:
        return None
    fields = _parse_header_fields(line)
    if "mode" not in fields or "role" not in fields:
        return None
    return SpawnHeader(
        mode=fields.get("mode", ""),
        role=fields.get("role", ""),
        story_id=_none_if_null(fields.get("story_id")),
        skill_proof=_none_if_null(fields.get("skill_proof")),
    )


def _parse_header_fields(line: str) -> dict[str, str]:
    """Parse ``key=value`` tokens after the header token (typed, no cascade)."""
    fields: dict[str, str] = {}
    remainder = line.strip()[len(HEADER_TOKEN):].strip() if line.strip().startswith(
        HEADER_TOKEN
    ) else line
    for token in remainder.split():
        key, sep, value = token.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def _none_if_null(value: str | None) -> str | None:
    """Map the literal ``"null"`` (and empty) header value to ``None``."""
    if value is None or value == "" or value.lower() == "null":
        return None
    return value


def _has_escape_pattern(text: str) -> bool:
    """Whether ``text`` contains a governance-escape pattern (Stage 1)."""
    return any(pattern.search(text) for pattern in _ESCAPE_PATTERNS)


__all__ = [
    "GUARD_NAME",
    "HEADER_TOKEN",
    "OPAQUE_MESSAGE",
    "PromptIntegrityDecision",
    "PromptIntegrityGuard",
    "PromptIntegrityStage",
    "SpawnHeader",
    "SpawnMode",
    "SpawnObservation",
    "parse_spawn_header",
]
