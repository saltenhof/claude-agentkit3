"""Story-creation guard (FK-31 §31.5 / FK-21 §21.13).

The :class:`StoryCreationGuard` blocks direct AK3-story-service mutations that
bypass the ``create-userstory`` skill (FK-31 §31.5.1 / FK-21 §21.13.1). Stories
MUST be created through that skill (VectorDB reconciliation, goal-fidelity check,
structured field population). **Always active** (FK-31 §31.5.2).

Detected story-service mutations:

1. ``agentkit story create`` — a shell command invoking the CLI story-create
   verb (reachable today via the Bash tool).
2. a direct story-DB INSERT — a write/mutation whose target is the story-backend
   SQLite file (``.sqlite`` / ``.sqlite3`` under ``.agentkit``).
3. HTTP POST ``/v1/stories`` — a structural contract for the future AK3 story
   server / BFF (FK-21 §21.13 / FK-31 §31.5). NOT yet reachable through a
   production harness adapter (the Claude Code / Codex adapters map any
   non-Bash/Write/Edit/Read tool to ``unknown_tool`` with empty args), so it is
   pinned by a contract test, not a fabricated unit test. A real HTTP tool must
   populate ``method``/``url``/``headers`` and gain an adapter integration test.

Whitelist (FK-31 §31.5.3/§31.5.4 / FK-21 §21.13.2): the structural skill marker,
or a direct-create principal grounded in FK-31 §31.5.4 —
:attr:`Principal.PIPELINE_DETERMINISTIC` (Zone-2 scripts, Kap. 41) and
:attr:`Principal.ADMIN_SERVICE` (official StorySplit/StoryReset, Kap. 54 / FK-30
§30.3.3 pt. 4). ``human_cli`` is deliberately EXCLUDED: a human creates stories
through the skill (FK-21 §21.1 "primär skill-gesteuert"), never via a raw
principal bypass.

Skill-marker convention (read ONLY from structural channels, never agent
prompt/command text — FK-55 §55.3a): the CLI arg ``--via-skill=create-userstory``
in ``HookEvent.cli_args`` or the HTTP header ``X-Skill: create-userstory``.

.. warning:: THE MARKER IS A CONVENTION, NOT AN ATTESTATION (FK-55 §55.1a). A
   malicious agent CAN spoof ``--via-skill`` / ``X-Skill`` — that is Stufe-3
   evasion, OUT OF SCOPE by design. The fail-closed teeth against an unattested
   agent are the principal whitelist (a worker / sub-agent is never a
   direct-create principal), not the spoofable marker.

Runtime dispatch is wired in
:func:`agentkit.governance.runner._run_story_creation_guard` for the
``story_creation_guard`` hook id; the install-time PreToolUse matcher (``Bash``,
plus an HTTP matcher once the server/BFF tool exists) is owned by the Installer /
harness adapters (FK-30 §30.3.1 / FK-76 §76.5) and pinned by the
guard-registration contract test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.guard_system.protected_paths import (
    STORY_DB_DIR_SEGMENT,
    STORY_DB_SUFFIXES,
)
from agentkit.governance.principal_capabilities.operations import (
    OperationClass,
    bash_mutation_targets,
)
from agentkit.governance.principal_capabilities.principals import Principal
from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.governance.guard_evaluation import HookEvent
    from agentkit.governance.principal_capabilities.operations import (
        OperationClassifier,
    )
    from agentkit.governance.principal_capabilities.principals import PrincipalResolver

#: FK-31 §31.5 rule id surfaced on a story-creation block.
RULE_ID = "FK-31 §31.5"

#: Guard identifier (matches the FK-30 §30.5.1 hook id ``story_creation_guard``).
GUARD_NAME = "story_creation_guard"

#: Opaque block reason (FK-31 §31.5.3 "blockiert sie mit opaker Fehlermeldung").
BLOCK_REASON = "story_creation_must_go_through_create_userstory_skill"

#: Canonical skill id of the official story-creation skill (FK-21 §21.13.2).
SKILL_MARKER_VALUE = "create-userstory"


class StoryCreationGuard:
    """Blocks direct story-service mutations that bypass the create-userstory skill.

    FK-31 §31.5 / FK-21 §21.13: always active. A detected story-service mutation
    (``agentkit story create``, a direct story-DB INSERT, or — structural
    contract for the future server/BFF — an HTTP POST ``/v1/stories``) is a hard
    DENY unless the structural skill marker is present or the resolved principal
    is a direct-create principal (FK-31 §31.5.4: Zone-2 pipeline / admin service;
    NOT ``human_cli``).
    """

    #: Structural CLI marker flag the skill emits (``--via-skill=create-userstory``).
    _CLI_SKILL_FLAG = "--via-skill"

    #: Structural HTTP header the skill emits (``X-Skill: create-userstory``).
    _HTTP_SKILL_HEADER = "x-skill"

    #: Story-service HTTP endpoint path (FK-21 §21.13 / FK-31 §31.5). POST to this
    #: collection path is a direct story-creation mutation.
    _STORY_ENDPOINT = "/v1/stories"

    #: CLI verb tokens that create a story (``agentkit story create``).
    _STORY_CREATE_CLI = ("agentkit", "story", "create")

    #: Direct-create principals (FK-31 §31.5.4). ONLY Zone-2 pipeline scripts
    #: (Failure-Corpus, Kap. 41) and the official admin StorySplit/StoryReset
    #: service (Kap. 54, FK-30 §30.3.3 pt. 4) may create a story directly at the
    #: AK3-Story-Service. ``human_cli`` is deliberately EXCLUDED (FK-21 §21.1
    #: "primär skill-gesteuert" — a human passes through the skill marker only).
    _DIRECT_CREATE_PRINCIPALS: frozenset[Principal] = frozenset(
        {
            Principal.PIPELINE_DETERMINISTIC,
            Principal.ADMIN_SERVICE,
        }
    )

    def __init__(
        self,
        principal_resolver: PrincipalResolver,
        op_classifier: OperationClassifier,
    ) -> None:
        """Create the guard.

        Args:
            principal_resolver: Resolves the technical principal from the
                harness/event context (FK-55 §55.3a).
            op_classifier: Normalizes the tool call to an
                :class:`OperationClass`.
        """
        self._principal_resolver = principal_resolver
        self._op_classifier = op_classifier

    @property
    def name(self) -> str:
        """Short identifier for this guard (FK-30 §30.5.1 hook id)."""
        return GUARD_NAME

    def evaluate(self, event: HookEvent) -> GuardVerdict:
        """Evaluate ``event`` against the story-creation rules.

        Args:
            event: Harness-neutral hook event.

        Returns:
            A blocking :class:`GuardVerdict` when a story-service mutation
            bypasses the skill / an official principal; otherwise an allow
            verdict.
        """
        if not self._is_story_service_mutation(event):
            return GuardVerdict.allow(self.name)

        if self._has_skill_marker(event):
            return GuardVerdict.allow(self.name)

        principal = self._principal_resolver.resolve(event)
        if principal in self._DIRECT_CREATE_PRINCIPALS:
            return GuardVerdict.allow(self.name)

        return GuardVerdict.block(
            self.name,
            ViolationType.UNAUTHORIZED_OPERATION,
            BLOCK_REASON,
            detail={
                "rule_id": RULE_ID,
                "principal": principal.value,
            },
        )

    def _is_story_service_mutation(self, event: HookEvent) -> bool:
        """Whether ``event`` is one of the three story-service mutations."""
        return self._is_http_story_post(event) or self._is_cli_story_create(event) or self._is_story_db_insert(event)

    @staticmethod
    def _is_http_story_post(event: HookEvent) -> bool:
        """Whether the event is an HTTP POST to the story collection endpoint."""
        args = event.operation_args
        method = args.get("method")
        url = args.get("url")
        if url is None:
            url = args.get("target")
        if not isinstance(method, str) or method.strip().upper() != "POST":
            return False
        return isinstance(url, str) and StoryCreationGuard._STORY_ENDPOINT in url

    @staticmethod
    def _is_cli_story_create(event: HookEvent) -> bool:
        """Whether the event is an ``agentkit story create`` shell command."""
        command = event.operation_args.get("command")
        if command is None:
            command = event.operation_args.get("cmd")
        if not isinstance(command, str) or not command:
            return False
        tokens = [tok.lower() for tok in command.split()]
        create_cli = StoryCreationGuard._STORY_CREATE_CLI
        width = len(create_cli)
        return any(tuple(tokens[start : start + width]) == create_cli for start in range(len(tokens) - width + 1))

    def _is_story_db_insert(self, event: HookEvent) -> bool:
        """Whether the event mutates the story-backend SQLite database directly."""
        op_class = self._op_classifier.classify(event.operation, event.operation_args)
        if op_class not in (
            OperationClass.WRITE,
            OperationClass.GIT_MUTATION,
            OperationClass.CURATE,
            OperationClass.ADMIN_TRANSITION,
        ):
            return False
        return any(_is_story_db_path(target) for target in self._candidate_targets(event))

    @staticmethod
    def _candidate_targets(event: HookEvent) -> list[str]:
        """Extract cheap candidate target paths from the event args."""
        args = event.operation_args
        candidates: list[str] = []
        for key in ("file_path", "path", "notebook_path"):
            value = args.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
        command = args.get("command")
        if command is None:
            command = args.get("cmd")
        if isinstance(command, str) and command:
            candidates.extend(bash_mutation_targets(command))
        return candidates

    @staticmethod
    def _has_skill_marker(event: HookEvent) -> bool:
        """Whether the structural create-userstory skill marker is present.

        Reads ONLY the structural channels (``cli_args`` and the HTTP
        ``headers`` arg) — never the prompt / command body (FK-55 §55.3a).
        """
        for token in event.cli_args or ():
            flag, _, value = token.partition("=")
            if flag == StoryCreationGuard._CLI_SKILL_FLAG and value == SKILL_MARKER_VALUE:
                return True
        headers = event.operation_args.get("headers")
        if isinstance(headers, dict):
            for key, value in headers.items():
                if (
                    isinstance(key, str)
                    and key.lower() == StoryCreationGuard._HTTP_SKILL_HEADER
                    and isinstance(value, str)
                    and value.strip() == SKILL_MARKER_VALUE
                ):
                    return True
        return False


def _is_story_db_path(target: str) -> bool:
    """Whether ``target`` is a story-backend SQLite file under ``.agentkit``."""
    raw = target.replace("\\", "/")
    segments = [seg for seg in raw.split("/") if seg not in ("", ".")]
    if STORY_DB_DIR_SEGMENT not in segments:
        return False
    basename = segments[-1].lower()
    return basename.endswith(STORY_DB_SUFFIXES)


__all__ = [
    "BLOCK_REASON",
    "GUARD_NAME",
    "RULE_ID",
    "SKILL_MARKER_VALUE",
    "StoryCreationGuard",
]
