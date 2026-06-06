"""Harness-specific settings-file materialisation for governance hooks.

FK-30 §30.3.1: ``Governance.register_hooks`` writes the harness-specific
settings file **directly**, via ``governance.guard_system`` + harness-specific
adapter.

This module owns the write path for both harness adapters:

- ``ClaudeCodeSettingsWriter``: writes ``.claude/settings.json``
- ``CodexSettingsWriter``: writes ``.codex/hooks.json`` (Codex-equivalent;
  FK-76 §76.5.2 — three-level shape verified against
  ``developers.openai.com/codex/hooks``)

Fail-closed (FK-30 §30.3.1 Z.339): a broken settings file (invalid JSON,
permission error) raises an exception — no silent continuation.

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E2).
AG3-049 2026-06-01: ``CodexSettingsWriter`` made productive (FK-76 §76.5.2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.errors import HookRegistrationError
from agentkit.utils.io import read_json_object

if TYPE_CHECKING:
    from agentkit.governance.hook_registration import HookDefinition


# ---------------------------------------------------------------------------
# Claude Code settings writer
# ---------------------------------------------------------------------------


class ClaudeCodeSettingsWriter:
    """Write hook definitions to ``.claude/settings.json``.

    The JSON schema follows FK-30 §30.3.1:

    .. code-block:: json

        {
          "hooks": {
            "PreToolUse": [
              {"matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard"}
            ],
            "PostToolUse": [
              {"matcher": "Agent|Bash|*_send", "command": "agentkit-hook-claude post telemetry"}
            ]
          }
        }

    Idempotent / UPSERT semantics: an entry is replaced only when both its
    ``matcher`` and ``command`` match under the same event key (idempotent
    re-registration); a distinct ``command`` under the same matcher is kept as
    a separate entry, because FK-30 §30.3.1 registers several hooks that share a
    matcher (e.g. ``Bash``).  The file is written atomically (write to tmp + rename is
    impractical on all OSes; write-in-place is sufficient for settings files).

    Fail-closed: if the existing settings file contains invalid JSON, raises
    ``ValueError`` rather than silently overwriting.

    Args:
        project_root: Root directory of the project.  ``.claude/settings.json``
            is resolved relative to this directory.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()

    @property
    def settings_path(self) -> Path:
        """Resolved path to ``.claude/settings.json``."""
        return self._project_root / ".claude" / "settings.json"

    def write(self, hook_definitions: list[HookDefinition]) -> Path:
        """Materialise ``hook_definitions`` into ``.claude/settings.json``.

        Reads the existing file (if any), merges the hook definitions, and
        writes the result back.  An entry is overwritten only when both its
        ``matcher`` and ``command`` match (UPSERT); distinct commands under the
        same matcher are preserved as separate entries (FK-30 §30.3.1).

        Args:
            hook_definitions: Hook definitions to materialise.

        Returns:
            The path to the written settings file.

        Raises:
            ValueError: If the existing settings file contains invalid JSON.
            OSError: If the file cannot be written.
        """
        settings = self._load_existing()
        raw_hooks = settings.get("hooks")
        if isinstance(raw_hooks, dict):
            hooks_section: dict[str, list[dict[str, str]]] = {}
            for k, v in raw_hooks.items():
                if isinstance(v, list):
                    hooks_section[str(k)] = [
                        {str(ek): str(ev) for ek, ev in e.items()}
                        for e in v
                        if isinstance(e, dict)
                    ]
        else:
            hooks_section = {}

        for defn in hook_definitions:
            event_key = defn.hook_event_name.value  # "PreToolUse" or "PostToolUse"
            entries: list[dict[str, str]] = list(hooks_section.get(event_key, []))
            # UPSERT keyed on (matcher, command): FK-30 §30.3.1 registers
            # multiple distinct hooks under the same matcher (e.g. "Bash" hosts
            # both branch_guard and story_creation_guard). Keying the UPSERT on
            # matcher alone silently collapsed those into one, dropping guards.
            # Identity is therefore (matcher, command) -- re-registering an
            # identical pair is idempotent; a different command under the same
            # matcher is preserved as a separate entry.
            idx = next(
                (
                    i
                    for i, e in enumerate(entries)
                    if e.get("matcher") == defn.matcher
                    and e.get("command") == defn.command
                ),
                None,
            )
            entry: dict[str, str] = {"matcher": defn.matcher, "command": defn.command}
            if idx is not None:
                entries[idx] = entry
            else:
                entries.append(entry)
            hooks_section[event_key] = entries

        settings["hooks"] = hooks_section
        self._write(settings)
        return self.settings_path

    def _load_existing(self) -> dict[str, object]:
        """Load the existing settings file or return an empty dict.

        Delegates JSON parsing to ``utils.io.read_json_object`` so this
        protected governance module stays on the safe side of the truth
        boundary (FK-30 §30.3.1 fail-closed semantics are preserved there).
        """
        return read_json_object(self.settings_path)

    def _write(self, settings: dict[str, object]) -> None:
        """Write ``settings`` to ``.claude/settings.json``."""
        path = self.settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Codex settings writer (productive — harness-specific equivalent)
# ---------------------------------------------------------------------------

# Command-form contract (Auflage 5, §2.1.1): hooks arrive in the
# harness-neutral Claude form and are remapped to the Codex wrapper.  Any
# deviation is a typed error, never a silent passthrough.
_CLAUDE_COMMAND_RE = re.compile(r"^agentkit-hook-claude (?P<phase>\S+) (?P<hook_id>\S+)$")

# Tool-matcher classification (Auflage 2+3, §2.1.2, FK-76 §76.5.2).
# Verified 2026-06-01 against ``developers.openai.com/codex/hooks``:
#   - PreToolUse/PostToolUse matchers accept ``Bash``, ``apply_patch``
#     (which covers Edit/Write), and MCP tool names (matcher is a regex,
#     so ``mcp__.*_send`` is valid).
#   - Codex does NOT intercept Read/Grep/Glob/WebSearch/WebFetch, and has
#     no Agent/sub-agent-spawn matcher token; those are known-not-
#     representable and drop token-wise with a visible diagnostic.
#
# ``*_send`` decision (Codex-Plan-Segen WARNING, §2.1.2 row): FK-30 §30.3.2
# defines ``*_send`` as "Alle MCP-Pool-Send-Tools (chatgpt_send, gemini_send,
# ...)".  These ARE MCP tools, and the live Codex doc confirms MCP tools are
# matchable via regex (canonical name ``mcp__server__tool``).  The regex is
# **anchored** (``^mcp__.*_send$``) so it only matches MCP tool names that end
# in ``_send`` — an unanchored ``mcp__.*_send`` could match foreign tools that
# merely contain ``_send`` as a substring (Codex-r1 WARNING). Pinned by a test.
_MATCHER_MAPPABLE: dict[str, str] = {
    "Bash": "Bash",
    "Write": "apply_patch",
    "Edit": "apply_patch",
    "*_send": "^mcp__.*_send$",
}
# Web-tool tokens with NO Codex tool surface (FK-76 §76.5.2, verified against
# ``developers.openai.com/codex/hooks``): Codex does not expose WebSearch /
# WebFetch at all, so there is nothing to intercept and no matcher can be
# registered. Tracked SEPARATELY from the merely-non-interceptable tokens so the
# omission of the ``budget_event_emitter`` enforcement surface is an EXPLICIT,
# named, guarded decision — not a silent drop bucketed with ordinary tools
# (AG3-036 FIX-2 / FK-68 §68.6.1). The fail-closed backstop, should a web call
# ever reach the Codex governance runner regardless, lives in the Codex event
# mapping (``codex.event_mapping``: it preserves the tool name so
# ``budget_event_emitter`` still DENIES an over-budget / unresolved research
# web call).
_MATCHER_NO_CODEX_WEB_SURFACE: frozenset[str] = frozenset({"WebSearch", "WebFetch"})
# Known §30.3.1 tokens with no Codex matcher equivalent — drop token-wise.
_MATCHER_NOT_REPRESENTABLE: frozenset[str] = (
    frozenset({"Read", "Grep", "Glob", "Agent"}) | _MATCHER_NO_CODEX_WEB_SURFACE
)
# Full known §30.3.1 token universe (FK-30 §30.3.1 / §30.3.2 table).  Any
# token outside this set is unclassified → FAIL CLOSED.
_KNOWN_MATCHER_TOKENS: frozenset[str] = (
    frozenset(_MATCHER_MAPPABLE) | _MATCHER_NOT_REPRESENTABLE
)

# Codex hook-handler shape (§2.1.3, FK-76 §76.5.2): three-level
# ``hooks`` -> event -> matcher-group -> handler ``{type: "command", command}``.
_CODEX_HANDLER_TYPE = "command"


class CodexMatcherMapping:
    """Result of mapping one Claude matcher to its Codex equivalent.

    Attributes:
        codex_matcher: The emitted Codex matcher string (pipe-joined,
            order-preserving, deduplicated), or ``None`` when every token of
            the source matcher is known-not-representable (the hook is then
            not applicable to Codex and no entry is written).
        dropped_tokens: Known §30.3.1 tokens that have no Codex equivalent and
            were dropped token-wise (visible diagnostic, never silent).
    """

    __slots__ = ("codex_matcher", "dropped_tokens")

    def __init__(self, codex_matcher: str | None, dropped_tokens: list[str]) -> None:
        self.codex_matcher = codex_matcher
        self.dropped_tokens = dropped_tokens


def map_claude_matcher(matcher: str) -> CodexMatcherMapping:
    """Map a Claude matcher string to its Codex equivalent, token-wise.

    Implements Auflage 2+3 (§2.1.2): each pipe-delimited token is mapped
    independently.  Mappable tokens contribute their Codex target (deduped,
    order-preserving — ``Write|Edit`` collapses to a single ``apply_patch``);
    known-not-representable tokens drop with a diagnostic; a token outside the
    known §30.3.1 universe is a fail-closed error.

    Args:
        matcher: Claude matcher, e.g. ``"Bash|Write|Edit|Read|Grep|Glob|Agent"``.

    Returns:
        A :class:`CodexMatcherMapping`.  ``codex_matcher`` is ``None`` when all
        tokens dropped (documented non-applicability).

    Raises:
        HookRegistrationError: If a token is not part of the known §30.3.1
            token set (FAIL CLOSED — no silent passthrough, no over-reaction).
    """
    codex_targets: list[str] = []
    dropped: list[str] = []
    for raw_token in matcher.split("|"):
        token = raw_token.strip()
        if not token:
            continue
        if token in _MATCHER_MAPPABLE:
            target = _MATCHER_MAPPABLE[token]
            if target not in codex_targets:  # dedupe (Write+Edit -> one apply_patch)
                codex_targets.append(target)
        elif token in _MATCHER_NOT_REPRESENTABLE:
            dropped.append(token)
        else:
            raise HookRegistrationError(
                f"Unknown matcher token {token!r} in matcher {matcher!r}: "
                "not part of the FK-30 §30.3.1 token set "
                f"({sorted(_KNOWN_MATCHER_TOKENS)}). Fail-closed: refusing to "
                "emit a Codex hook for an unclassified tool token.",
            )
    codex_matcher = "|".join(codex_targets) if codex_targets else None
    return CodexMatcherMapping(codex_matcher=codex_matcher, dropped_tokens=dropped)


def remap_command(command: str) -> str:
    """Remap a Claude hook command to the Codex wrapper command (Auflage 5).

    Parses the command as exactly ``agentkit-hook-claude {phase} {hook_id}``
    and re-emits it as ``agentkit-hook-codex {phase} {hook_id}``.

    Args:
        command: The Claude hook command string.

    Returns:
        The Codex hook command string.

    Raises:
        HookRegistrationError: If the command does not match the expected
            ``agentkit-hook-claude {phase} {hook_id}`` form (FAIL CLOSED — no
            silent passthrough of an unrecognised command).
    """
    match = _CLAUDE_COMMAND_RE.match(command)
    if match is None:
        raise HookRegistrationError(
            f"Unexpected hook command form {command!r}: expected exactly "
            "'agentkit-hook-claude {phase} {hook_id}'. Fail-closed: refusing to "
            "pass an unrecognised command through to the Codex settings file.",
        )
    phase, hook_id = match["phase"], match["hook_id"]
    # Not just the SHAPE (regex) but the SEMANTICS: an unknown phase or hook_id
    # would be remapped to a Codex command the wrapper later rejects fail-closed
    # (runner.validate_hook_selector). Validate at the REGISTRATION boundary so
    # we never write a hook that cannot run (Codex-r1 ERROR 3, Auflage 5).
    # Lazy import avoids a governance import cycle (runner imports adapters).
    from agentkit.governance.runner import validate_hook_selector

    verdict = validate_hook_selector(phase=phase, hook_id=hook_id)
    if verdict is not None:
        raise HookRegistrationError(
            f"Invalid hook selector in command {command!r}: "
            f"{verdict.message or 'unknown phase/hook_id'}. Fail-closed: refusing "
            "to emit a Codex hook for an unregistered phase/hook_id.",
        )
    return f"agentkit-hook-codex {phase} {hook_id}"


class CodexSettingsWriter:
    """Write hook definitions to ``.codex/hooks.json`` (Codex harness).

    FK-76 §76.5.2 owns the Codex settings format.  The Codex shape is
    **three-level** (verified against ``developers.openai.com/codex/hooks``):

    .. code-block:: json

        {
          "hooks": {
            "PreToolUse": [
              {
                "matcher": "Bash",
                "hooks": [
                  {"type": "command", "command": "agentkit-hook-codex pre branch_guard"}
                ]
              }
            ]
          }
        }

    Each :class:`HookDefinition` is transformed (FK-76 §76.5.2):

    - **Command** (Auflage 5): ``agentkit-hook-claude {phase} {hook_id}`` ->
      ``agentkit-hook-codex {phase} {hook_id}``; deviating form raises.
    - **Matcher** (Auflage 2+3): mapped token-wise to real Codex matchers
      (``Bash`` -> ``Bash``; ``Write``/``Edit`` -> one ``apply_patch``;
      ``*_send`` -> ``^mcp__.*_send$``; ``Read``/``Grep``/``Glob``/``Agent``/
      ``WebSearch``/``WebFetch`` drop with a diagnostic; unknown token ->
      error).  A matcher that is empty after dropping yields no Codex hook
      (documented non-applicability, recorded in :attr:`diagnostics`).

    Merge / idempotency (Auflage 4, §2.1.4) mirrors
    :class:`ClaudeCodeSettingsWriter` exactly: identity is
    **event + matcher + command**.  A handler is appended to its matcher group
    only when no handler with the same command already exists there; multiple
    handlers may share a matcher group; foreign hooks (matcher groups or
    handlers AK3 did not write) are preserved untouched.

    Codex trust-layer boundary (Auflage 6, AK6, FK-76 §76.5.3): repo-local
    Codex hooks only run in **trusted** ``.codex`` layers; non-managed hooks
    are skipped until trusted.  This writer only materialises the file; the
    actual trust activation is installer work (FK-50/FK-51) and out of scope.

    Fail-closed: a broken existing ``.codex/hooks.json`` raises ``ValueError``
    rather than being overwritten — invalid JSON / non-object top level (via
    ``read_json_object``) AND a present-but-malformed ``hooks`` structure (event
    value not a list, group not an object, nested ``hooks`` not a list, handler
    not an object; Codex-r1 ERROR 2). Existing/foreign groups are preserved
    verbatim (no ``matcher`` synthesis; Codex-r1 ERROR 1).

    Args:
        project_root: Root directory of the project.  ``.codex/hooks.json`` is
            resolved relative to this directory.

    Attributes:
        diagnostics: Human-readable diagnostics for token-wise drops and
            non-applicable (empty-after-drop) matchers, accumulated by the most
            recent :meth:`write`.  Visible, never silent (§2.1.2 / AC3).
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()
        self.diagnostics: list[str] = []

    @property
    def settings_path(self) -> Path:
        """Resolved path to ``.codex/hooks.json``."""
        return self._project_root / ".codex" / "hooks.json"

    def write(self, hook_definitions: list[HookDefinition]) -> Path:
        """Materialise ``hook_definitions`` into ``.codex/hooks.json``.

        Reads the existing file (if any), merges the remapped hook
        definitions into the three-level Codex shape, and writes the result
        back.  Identity is (event, matcher, command): an identical handler is
        idempotent; a distinct command under the same matcher is preserved as
        a separate handler; foreign content is kept.

        Args:
            hook_definitions: Hook definitions to materialise.

        Returns:
            The path to the written settings file.

        Raises:
            HookRegistrationError: On an unmappable matcher token or a command
                that does not match the expected Claude form (FAIL CLOSED).
            ValueError: If the existing settings file contains invalid JSON.
            OSError: If the file cannot be written.
        """
        self.diagnostics = []
        settings = self._load_existing()
        hooks_section = _coerce_hooks_section(settings.get("hooks"))

        for defn in hook_definitions:
            event_key = defn.hook_event_name.value  # "PreToolUse" / "PostToolUse"
            mapping = map_claude_matcher(defn.matcher)
            if mapping.dropped_tokens:
                self.diagnostics.append(
                    f"{event_key} matcher {defn.matcher!r}: dropped "
                    f"non-representable token(s) {mapping.dropped_tokens} "
                    "(no Codex matcher equivalent).",
                )
                # Web tokens are not merely non-interceptable — Codex has NO web
                # tool surface (FK-76 §76.5.2). Emit an EXPLICIT, named guard
                # diagnostic so the budget_event_emitter enforcement surface is
                # documented as deliberately absent on Codex, never a silent gap
                # (AG3-036 FIX-2 / FK-68 §68.6.1).
                dropped_web = [
                    t for t in mapping.dropped_tokens
                    if t in _MATCHER_NO_CODEX_WEB_SURFACE
                ]
                if dropped_web:
                    self.diagnostics.append(
                        f"{event_key} matcher {defn.matcher!r}: web tool(s) "
                        f"{dropped_web} have NO Codex tool surface "
                        "(FK-76 §76.5.2) — budget_event_emitter is intentionally "
                        "not registered for Codex. Fail-closed backstop: if a web "
                        "call ever reaches the Codex runner, the Codex event "
                        "mapping preserves the tool name so budget_event_emitter "
                        "still denies an over-budget/unresolved research web call.",
                    )
            if mapping.codex_matcher is None:
                self.diagnostics.append(
                    f"{event_key} matcher {defn.matcher!r}: not applicable to "
                    "Codex (all tokens non-representable) — no hook written.",
                )
                continue
            codex_command = remap_command(defn.command)
            self._merge_handler(
                hooks_section,
                event_key,
                mapping.codex_matcher,
                codex_command,
            )

        settings["hooks"] = hooks_section
        self._write(settings)
        return self.settings_path

    @staticmethod
    def _merge_handler(
        hooks_section: dict[str, list[dict[str, object]]],
        event_key: str,
        matcher: str,
        command: str,
    ) -> None:
        """Merge one handler into its matcher group (Auflage 4, identity 3-tuple).

        Mirrors :class:`ClaudeCodeSettingsWriter` exactly: identity is
        (event, matcher, command).  Reuses the existing matcher group for
        ``matcher`` under ``event_key`` (preserving its other handlers and any
        foreign groups), and only appends the handler when no handler with the
        same command exists yet.
        """
        groups = hooks_section.setdefault(event_key, [])
        group = next((g for g in groups if g.get("matcher") == matcher), None)
        if group is None:
            group = {"matcher": matcher, "hooks": []}
            groups.append(group)
        handlers = group["hooks"]
        if not isinstance(handlers, list):
            handlers = []
            group["hooks"] = handlers
        handler = {"type": _CODEX_HANDLER_TYPE, "command": command}
        existing = next(
            (h for h in handlers if isinstance(h, dict) and h.get("command") == command),
            None,
        )
        if existing is not None:
            existing.update(handler)
        else:
            handlers.append(handler)

    def _load_existing(self) -> dict[str, object]:
        """Load the existing ``.codex/hooks.json`` or return an empty dict.

        Delegates JSON parsing to ``utils.io.read_json_object`` (fail-closed:
        a broken file raises ``ValueError`` instead of being silently treated
        as empty), keeping this protected governance module on the safe side
        of the truth boundary.
        """
        return read_json_object(self.settings_path)

    def _write(self, settings: dict[str, object]) -> None:
        """Write ``settings`` to ``.codex/hooks.json``."""
        path = self.settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _coerce_hooks_section(
    raw_hooks: object,
) -> dict[str, list[dict[str, object]]]:
    """Validate the existing ``hooks`` section, fail-closed; preserve it verbatim.

    A MISSING ``hooks`` key (``None``) starts empty. A PRESENT-but-malformed
    structure raises ``ValueError`` instead of being silently coerced to
    empty/partial — silent coercion would delete existing governance/foreign
    hooks on the next write (FAIL CLOSED, AK5; Codex-r1 ERROR 2). Malformed =
    ``hooks`` not an object; an event value that is not a list; a matcher group
    that is not an object; a group ``hooks`` present but not a list; a handler
    that is not an object.

    Existing (including FOREIGN) groups and handlers are returned **verbatim** —
    no ``matcher`` synthesis, no key stripping (Codex-r1 ERROR 1). Foreign groups
    without a ``matcher`` (e.g. ``Stop``/``UserPromptSubmit``) stay untouched; the
    merge never matches them because AK3 groups always carry a ``matcher``.
    """
    if raw_hooks is None:
        return {}
    if not isinstance(raw_hooks, dict):
        raise ValueError(
            "Existing .codex/hooks.json 'hooks' must be an object, got "
            f"{type(raw_hooks).__name__}; refusing to overwrite (fail-closed).",
        )
    section: dict[str, list[dict[str, object]]] = {}
    for event_key, groups in raw_hooks.items():
        if not isinstance(groups, list):
            raise ValueError(
                f"Existing .codex/hooks.json event {event_key!r} must map to a "
                f"list of matcher groups, got {type(groups).__name__} (fail-closed).",
            )
        for group in groups:
            _validate_group_shape(event_key, group)
        section[str(event_key)] = groups
    return section


def _validate_group_shape(event_key: str, group: object) -> None:
    """Fail-closed validation of one matcher group (helper of _coerce_hooks_section).

    Extracted to keep ``_coerce_hooks_section`` under the cognitive-complexity
    limit (python:S3776). A group must be an object with a ``hooks`` handler
    LIST (the Codex shape requires it even for matcher-less Stop/UserPromptSubmit
    groups; Codex-r2), and every handler must be an object. The group is NOT
    mutated — only validated; the caller preserves it verbatim (Codex-r1 ERROR 1).
    """
    if not isinstance(group, dict):
        raise ValueError(
            f"Existing .codex/hooks.json group under {event_key!r} must be "
            f"an object, got {type(group).__name__} (fail-closed).",
        )
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        raise ValueError(
            f"Existing .codex/hooks.json group {group!r} must have a "
            f"'hooks' list, got {type(handlers).__name__} (fail-closed).",
        )
    for handler in handlers:
        if not isinstance(handler, dict):
            raise ValueError(
                "Existing .codex/hooks.json handler must be an object, "
                f"got {type(handler).__name__} (fail-closed).",
            )


__all__ = [
    "ClaudeCodeSettingsWriter",
    "CodexMatcherMapping",
    "CodexSettingsWriter",
    "map_claude_matcher",
    "remap_command",
]
