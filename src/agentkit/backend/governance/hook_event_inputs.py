"""Hook-event input extraction helpers for governance guards."""


from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.governance.principal_capabilities.operations import (
    canonical_web_tool,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.guard_evaluation import HookEvent


@dataclass(frozen=True)
class HookWrapperArgs:
    """Validated hook-wrapper command-line selector."""

    phase: str
    hook_id: str


class _SkillBindingLookupAdapter:
    """Adapts ``Skills.resolve_binding`` to the guard's ``SkillBindingLookup`` port.

    Consumes the Skills BC surface (FK-43 §43.1) — the guard never re-implements
    skill-binding storage. A lookup fault fails CLOSED to "not bound" so a broken
    Skills backend never lets the guard fabricate a block for an unverifiable
    skill (the guard only blocks when a binding is positively resolvable).
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def is_bound(self, project_key: str, skill_name: str) -> bool:
        """Return ``True`` when a project binding for ``skill_name`` resolves."""
        _ = project_key  # the Skills surface keys on project_root.stem
        try:
            # Consume the agent-skills BC through its composition-root factory
            # (the wiring of the bundle store / binding repository is owned there,
            # not by governance — FK-43 §BC 11 / composition_root.build_skills).
            from agentkit.backend.bootstrap.composition_root import build_skills

            skills = build_skills(self._project_root)
            return skills.resolve_binding(self._project_root, skill_name) is not None
        except Exception:  # noqa: BLE001 -- missing wiring / backend fault -> not-bound
            return False


def _feature_are_enabled(project_root: Path) -> bool:
    """Whether ``features.are`` is enabled in the project config (FK-43 §43.3.2).

    A config fault falls back to ``False`` (the FEATURE_ARE-gated skills then do
    not apply) — a broken config never fabricates a block for an ARE skill.
    """
    try:
        from agentkit.backend.config.loader import load_project_config

        return load_project_config(project_root).pipeline.features.are
    except Exception:  # noqa: BLE001 -- config fault -> ARE precondition not met
        return False


_AGENT_TOOL = "Agent"


_MANIFEST_SKILL_PROOF_KEY = "agent_spawn_skill_proof"


def _event_str_arg(event: HookEvent, key: str) -> str:
    """Read a string ``operation_args[key]`` (empty when absent / non-string)."""
    value = event.operation_args.get(key)
    return value if isinstance(value, str) else ""


def _installed_skill_proof(project_root: Path) -> str:
    """Resolve the authoritative spawn skill-proof token (FK-31 §31.7.4).

    Reads ``.installed-manifest.json`` for the
    ``agent_spawn_skill_proof`` token the Installer writes. Returns ``""`` when no
    manifest / token is installed — a story_execution spawn then fails Stage 2
    fail-closed (no proof = no valid spawn; FAIL-CLOSED). The JSON read goes
    through the ``utils.io`` truth-boundary helper (governance modules must not
    call ``json.load*`` directly — formal.truth-boundary-checker.invariants).
    """
    from agentkit.backend.utils.io import read_json_object

    manifest_path = project_root / ".installed-manifest.json"
    try:
        data = read_json_object(manifest_path)
    except (OSError, ValueError):
        return ""
    token = data.get(_MANIFEST_SKILL_PROOF_KEY)
    return token if isinstance(token, str) else ""


def _resolve_prompt_file_content(
    event: HookEvent, project_root: Path
) -> str | None:
    """Resolve the CONTENT of the spawn's ``prompt_file`` (PROD-A), if any.

    PROD-A spawns (the authoritative SKILL.md worker-spawn shape) pass the prompt
    body via ``prompt_file`` and carry NO inline ``prompt``. The actual prompt the
    agent receives is the FILE CONTENT, so the guard's Stage-3 (and Stage-1)
    comparison target is the file's bytes. Returns ``None`` when the spawn carries
    no ``prompt_file`` (PROD-B: the inline ``prompt`` is then the target).

    The file must live under the project root (no path-traversal escape). A
    ``prompt_file`` that cannot be read returns the empty string, NOT ``None``, so
    a story_execution spawn naming an unreadable file does not silently fall back
    to the inline ``prompt`` -- it is treated as an empty actual prompt and
    fails Stage 3 fail-closed (no pinned digest matches the empty digest unless
    the pipeline genuinely materialized an empty prompt, which it never does).
    """
    prompt_file = _event_str_arg(event, "prompt_file")
    if not prompt_file:
        return None
    candidate = (project_root / prompt_file).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return ""
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return ""


def _pinned_prompt_output_hashes(
    story_dir: Path, *, story_id: str, run_id: str
) -> frozenset[str]:
    """Resolve the install-pinned Stage-3 baseline (FK-31 §31.7.4 / FK-44 §44.6).

    Returns the set of prompt-audit ``output_sha256`` digests the prompt-runtime
    persisted for the run -- the digests of the exact prompt bytes the pipeline
    materialized from a manifest-pinned bundle template. This baseline is NOT
    spawn-controlled, so a worker can neither author it nor satisfy Stage 3 with a
    self-made ``prompt_file``. Returns an empty set when the scope is
    unresolvable or nothing has been materialized -- a story_execution spawn then
    fails Stage 3 fail-closed.
    """
    from agentkit.backend.state_backend.scope import RuntimeStateScope
    from agentkit.backend.state_backend.store.facade import (
        find_prompt_audit_output_hashes,
    )

    if not story_id or not run_id:
        return frozenset()
    scope = RuntimeStateScope(
        project_key="",
        story_id=story_id,
        story_dir=story_dir,
        run_id=run_id,
    )
    try:
        return find_prompt_audit_output_hashes(story_dir, scope)
    except Exception:  # noqa: BLE001 — fail-closed: any read error -> no baseline.
        return frozenset()


def _event_command(event: HookEvent) -> str:
    """Extract the bash command string from the event operation args.

    Args:
        event: Harness-neutral hook event.

    Returns:
        The command string, or an empty string when absent.
    """
    command = event.operation_args.get("command")
    return command if isinstance(command, str) else ""


_OPERATION_TO_TOOL: dict[str, str] = {
    "bash_command": "Bash",
    "file_write": "Write",
    "file_edit": "Edit",
    "file_read": "Read",
}


def _event_tool(event: HookEvent) -> str:
    """Derive the canonical tool name from the harness-neutral event.

    Prefers an explicit ``operation_args["tool_name"]`` (how WebFetch/WebSearch
    arrive, since the HookEvent ``operation`` is ``unknown_tool`` for them);
    otherwise maps the ``operation`` back to the canonical tool name. Mirrors
    ``CcagPermissionRuntime._tool_name_from_event`` (single convention).

    AG3-036 FIX-2: a web-tool name is canonicalized (``web_fetch`` /
    ``web-search`` / ``WEBFETCH`` / ... → ``WebFetch`` / ``WebSearch``) BEFORE it
    is returned, so EVERY alias / casing form resolves to the canonical value the
    ``_WEB_TOOLS`` gate and the BudgetEventEmitter compare against. A
    casing/alias gap here would let an over-budget / unresolved research web call
    slip past the budget guard (fail-open) — the exact hole FIX-2 closes.

    Args:
        event: Harness-neutral hook event.

    Returns:
        The canonical tool name string (e.g. ``"WebFetch"``).
    """
    explicit = event.operation_args.get("tool_name")
    if isinstance(explicit, str) and explicit:
        return canonical_web_tool(explicit) or explicit
    canonical = _OPERATION_TO_TOOL.get(event.operation, event.operation)
    return canonical_web_tool(canonical) or canonical
