"""Harness-specific settings-file materialisation for governance hooks.

FK-30 §30.3.1: ``Governance.register_hooks`` writes the harness-specific
settings file **directly**, via ``governance.guard_system`` + harness-specific
adapter.

This module owns the write path for both harness adapters:

- ``ClaudeCodeSettingsWriter``: writes ``.claude/settings.json``
- ``CodexSettingsWriter``: writes ``.codex/config.toml`` (Codex-equivalent)

Fail-closed (FK-30 §30.3.1 Z.339): a broken settings file (invalid JSON,
permission error) raises an exception — no silent continuation.

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

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

    Idempotent / UPSERT semantics: existing entries with matching ``matcher``
    under the same event key are replaced by the new ``command``; new matchers
    are appended.  The file is written atomically (write to tmp + rename is
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
        writes the result back.  Entries with the same ``matcher`` under the
        same event name are overwritten (UPSERT); new matchers are appended.

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
            # UPSERT: replace existing entry with same matcher, or append
            idx = next(
                (i for i, e in enumerate(entries) if e.get("matcher") == defn.matcher),
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
        """Load the existing settings file or return an empty dict."""
        path = self.settings_path
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in {path}: {exc}. "
                "Fail-closed: refusing to overwrite a broken settings file "
                "(FK-30 §30.3.1)."
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"Settings file {path} must contain a JSON object, "
                f"got {type(data).__name__}."
            )
        return data

    def _write(self, settings: dict[str, object]) -> None:
        """Write ``settings`` to ``.claude/settings.json``."""
        path = self.settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Codex settings writer (stub — harness-specific equivalent)
# ---------------------------------------------------------------------------


class CodexSettingsWriter:
    """Write hook definitions to the Codex-harness settings file.

    FK-30 §30.11: Codex has its own harness-specific settings format.
    This writer materialises hooks into ``.codex/config.toml`` (or the
    Codex-equivalent configuration path).

    Currently a stub implementation that writes a minimal TOML-like
    representation.  Full Codex adapter implementation is deferred to
    the Codex-adapter story (AG3-031 scope boundary).

    Args:
        project_root: Root directory of the project.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()

    @property
    def settings_path(self) -> Path:
        """Resolved path to the Codex settings file."""
        return self._project_root / ".codex" / "config.toml"

    def write(self, hook_definitions: list[HookDefinition]) -> Path:
        """Materialise ``hook_definitions`` into the Codex settings file.

        Writes a TOML-structured hook configuration analogous to the
        Claude Code ``.claude/settings.json`` format, mapped to Codex
        tool-name conventions.

        Args:
            hook_definitions: Hook definitions to materialise.

        Returns:
            The path to the written settings file.

        Raises:
            OSError: If the file cannot be written.
        """
        lines: list[str] = ["# AgentKit governance hooks (generated by register_hooks)", ""]
        for defn in hook_definitions:
            event = defn.hook_event_name.value.lower()  # pretooluse / posttooluse
            lines.append(f"[[hooks.{event}]]")
            lines.append(f'matcher = "{defn.matcher}"')
            lines.append(f'command = "{defn.command}"')
            lines.append("")

        content = "\n".join(lines)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(content, encoding="utf-8")
        return self.settings_path


__all__ = [
    "ClaudeCodeSettingsWriter",
    "CodexSettingsWriter",
]
