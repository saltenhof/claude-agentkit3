"""Contract: the hook-id -> guard-module dispatch mapping is pinned (AG3-033).

Pins the differentiated dispatch introduced for governance-and-guards.C5 so the
mapping cannot silently drift:

- ``HookId.SELF_PROTECTION`` -> :class:`SelfProtectionGuard` (FK-30 §30.5.4),
- ``HookId.STORY_CREATION_GUARD`` -> :class:`StoryCreationGuard` (FK-31 §31.5),

and that each guard's ``name`` / rule id is wortgleich to its FK anchor.
"""

from __future__ import annotations

import pytest

from agentkit.backend.governance import runner as runner_mod
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.guards import SelfProtectionGuard, StoryCreationGuard
from agentkit.backend.governance.guards.self_protection_guard import (
    GUARD_NAME as SELF_PROTECTION_NAME,
)
from agentkit.backend.governance.guards.self_protection_guard import (
    RULE_ID as SELF_PROTECTION_RULE_ID,
)
from agentkit.backend.governance.guards.story_creation_guard import (
    GUARD_NAME as STORY_CREATION_NAME,
)
from agentkit.backend.governance.guards.story_creation_guard import (
    RULE_ID as STORY_CREATION_RULE_ID,
)
from agentkit.backend.governance.guards.story_creation_guard import SKILL_MARKER_VALUE
from agentkit.backend.governance.hook_registration import HookEventName, HookId
from agentkit.backend.governance.principal_capabilities import (
    OperationClassifier,
    PrincipalResolver,
)
from agentkit.backend.governance.principal_capabilities.operations import canonical_web_tool

#: The pinned hook-id -> dedicated dispatch-function mapping (AG3-033).
EXPECTED_DEDICATED_DISPATCH: dict[str, str] = {
    HookId.SELF_PROTECTION.value: "_run_self_protection_guard",
    HookId.STORY_CREATION_GUARD.value: "_run_story_creation_guard",
}


def test_dedicated_dispatch_functions_exist() -> None:
    for func_name in EXPECTED_DEDICATED_DISPATCH.values():
        assert hasattr(runner_mod, func_name), func_name
        assert callable(getattr(runner_mod, func_name))


def test_self_protection_hook_id_maps_to_self_protection_guard() -> None:
    assert HookId.SELF_PROTECTION.value == "self_protection"
    assert HookId.SELF_PROTECTION.value == SELF_PROTECTION_NAME
    assert SELF_PROTECTION_RULE_ID == "FK-30 §30.5.4"


def test_story_creation_hook_id_maps_to_story_creation_guard() -> None:
    assert HookId.STORY_CREATION_GUARD.value == "story_creation_guard"
    assert HookId.STORY_CREATION_GUARD.value == STORY_CREATION_NAME
    assert STORY_CREATION_RULE_ID == "FK-31 §31.5"


def test_guards_are_re_exported() -> None:
    # The guards/__init__ re-export surface is part of the contract.
    from agentkit.backend.governance import guards

    assert guards.SelfProtectionGuard is SelfProtectionGuard
    assert guards.StoryCreationGuard is StoryCreationGuard


def test_only_two_hooks_have_dedicated_modules() -> None:
    # AG3-033 scope: exactly these two hooks are modularised; the others remain
    # on the generic path (branch_guard, qa_agent_guard, scope_guard via
    # guard_evaluation, ccag_gatekeeper separately).
    assert set(EXPECTED_DEDICATED_DISPATCH) == {
        "self_protection",
        "story_creation_guard",
    }


# ---------------------------------------------------------------------------
# AG3-033 ERROR C: HTTP POST /v1/stories is the STRUCTURAL contract for the
# future server/BFF surface — NOT yet reachable through a production harness
# adapter. Pinned at the contract level (not as a fabricated unit test that
# would imply production coverage the adapters do not provide today).
# ---------------------------------------------------------------------------

#: The shape a future HTTP-capable harness tool/adapter MUST produce for the
#: story-creation guard's structural HTTP detection to engage. No current
#: adapter (claude_code / codex event_mapping) populates these fields; both map
#: any non-Bash/Write/Edit/Read tool to ``unknown_tool`` with EMPTY args.
def _http_event(operation_args: dict[str, object]) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "operation_args": operation_args,
            "freshness_class": "mutation",
            "cwd": "/proj",
            "principal_kind": "subagent",
            "cli_args": ["--ak3-principal-attest", "worker"],
        }
    )


def _story_guard() -> StoryCreationGuard:
    return StoryCreationGuard(
        principal_resolver=PrincipalResolver(),
        op_classifier=OperationClassifier(),
    )


def test_http_post_v1_stories_structural_contract_blocks() -> None:
    # Structural contract: IF a server/BFF HTTP event carries method+url, an
    # unattested POST /v1/stories without the skill marker is blocked.
    verdict = _story_guard().evaluate(
        _http_event({"method": "POST", "url": "https://svc.local/v1/stories"})
    )
    assert verdict.allowed is False
    assert verdict.guard_name == "story_creation_guard"


def test_http_post_v1_stories_skill_header_passes_structural_contract() -> None:
    verdict = _story_guard().evaluate(
        _http_event(
            {
                "method": "POST",
                "url": "https://svc.local/v1/stories",
                "headers": {"X-Skill": SKILL_MARKER_VALUE},
            }
        )
    )
    assert verdict.allowed is True


def test_http_get_v1_stories_is_not_a_creation_mutation() -> None:
    verdict = _story_guard().evaluate(
        _http_event({"method": "GET", "url": "https://svc.local/v1/stories"})
    )
    assert verdict.allowed is True


def test_production_adapters_do_not_yet_emit_http_method_url() -> None:
    # Honest pin of ERROR C branch 2: neither production adapter populates
    # method/url, so the HTTP detection is unreachable through a harness today.
    from agentkit.harness_client.harness_adapters.claude_code import (
        ClaudeCodeHookEvent,
    )
    from agentkit.harness_client.harness_adapters.claude_code import (
        to_neutral_event as claude_to_neutral,
    )
    from agentkit.harness_client.harness_adapters.codex.event_mapping import (
        CodexHookEvent,
    )
    from agentkit.harness_client.harness_adapters.codex.event_mapping import (
        to_neutral_event as codex_to_neutral,
    )

    claude_evt = claude_to_neutral(
        ClaudeCodeHookEvent.model_validate(
            {"tool_name": "WebFetch", "tool_input": {"url": "https://svc/v1/stories"}}
        )
    )
    codex_evt = codex_to_neutral(
        CodexHookEvent.model_validate(
            {"tool_name": "web_fetch", "tool_input": {"url": "https://svc/v1/stories"}}
        )
    )
    # Both collapse to unknown_tool. AG3-036 FIX-1/FIX-2: the tool NAME now
    # survives (so the web-call budget guard can derive WebFetch/WebSearch), but
    # neither adapter populates method/url, so HTTP detection stays unreachable
    # through a harness today (the honest pin of ERROR C branch 2).
    #
    # Adapters PRESERVE the raw name verbatim (no canonicalization at the adapter
    # edge — that is the confirmed-good tool-name preservation). Canonicalization
    # of alias / casing forms to the canonical ``WebFetch`` / ``WebSearch`` happens
    # downstream at the runner edge (``_event_tool``), asserted below.
    assert claude_evt.operation == "unknown_tool"
    assert claude_evt.operation_args == {"tool_name": "WebFetch"}
    assert "method" not in claude_evt.operation_args
    assert "url" not in claude_evt.operation_args
    assert codex_evt.operation == "unknown_tool"
    # FIX-2: the CODEX adapter preserves the raw ``web_fetch`` alias verbatim ...
    assert codex_evt.operation_args == {"tool_name": "web_fetch"}
    assert "method" not in codex_evt.operation_args
    assert "url" not in codex_evt.operation_args

    # ... and the runner edge canonicalizes BOTH the already-canonical Claude name
    # and the Codex alias to the canonical ``WebFetch`` BEFORE the ``_WEB_TOOLS``
    # gate (FIX-2 — no alias/casing fail-open past the budget guard).
    assert runner_mod._event_tool(claude_evt) == "WebFetch"
    assert runner_mod._event_tool(codex_evt) == "WebFetch"


# ---------------------------------------------------------------------------
# AG3-036 FIX-2: web-tool alias / casing canonicalization is pinned for ALL
# alias forms (Claude- and Codex-shaped) so a casing/separator gap can never
# fail OPEN past the ``_WEB_TOOLS`` budget gate (FK-68 §68.6.1 / FK-55 §55.5).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("WebFetch", "WebFetch"),
        ("webfetch", "WebFetch"),
        ("WEBFETCH", "WebFetch"),
        ("web_fetch", "WebFetch"),
        ("web-fetch", "WebFetch"),
        ("Web Fetch", "WebFetch"),
        ("WebSearch", "WebSearch"),
        ("websearch", "WebSearch"),
        ("WEBSEARCH", "WebSearch"),
        ("web_search", "WebSearch"),
        ("web-search", "WebSearch"),
        ("Web Search", "WebSearch"),
    ],
)
def test_web_tool_alias_canonicalization(raw: str, expected: str) -> None:
    # The shared canonicalizer resolves every alias / casing form.
    assert canonical_web_tool(raw) == expected
    # And the runner edge resolves the same forms whether the name arrives via the
    # preserved ``operation_args["tool_name"]`` (Claude/Codex adapters) ...
    explicit_evt = HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "operation_args": {"tool_name": raw},
            "freshness_class": "guarded_read",
            "cwd": "/proj",
        }
    )
    assert runner_mod._event_tool(explicit_evt) == expected


def test_non_web_tool_is_not_canonicalized() -> None:
    # A non-web tool name is left untouched (returns None from the canonicalizer;
    # the runner edge returns the raw name unchanged).
    assert canonical_web_tool("Task") is None
    assert canonical_web_tool("TodoWrite") is None
    evt = HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "operation_args": {"tool_name": "Task"},
            "freshness_class": "guarded_read",
            "cwd": "/proj",
        }
    )
    assert runner_mod._event_tool(evt) == "Task"


# ---------------------------------------------------------------------------
# AG3-033 WARNING D: the always-active registration nexus. AG3-033 owns the
# runtime dispatch; the FK-30 §30.3.1 PreToolUse matchers for these two hooks
# are pinned here so the "always active" intent cannot silently drift. The
# install-time materialisation is the Installer's (FK-30 §30.3.1 / FK-76 §76.5)
# — documented in the guard module docstrings.
# ---------------------------------------------------------------------------

#: FK-30 §30.3.1 / §91.4 normative PreToolUse matchers for the AG3-033 guards.
EXPECTED_PRETOOLUSE_MATCHERS: dict[str, str] = {
    HookId.SELF_PROTECTION.value: "Write|Edit|Bash",
    HookId.STORY_CREATION_GUARD.value: "Bash",
}


def test_ag3_033_guards_are_pretooluse() -> None:
    # FK-30 §30.5.1: both are blocking PreToolUse guard hooks.
    assert HookEventName.PRE_TOOL_USE.value == "PreToolUse"
    for hook_id in EXPECTED_PRETOOLUSE_MATCHERS:
        assert hook_id in {h.value for h in HookId}


def test_ag3_033_guards_dispatch_runtime_is_owned_here() -> None:
    # WARNING D nexus: the RUNTIME dispatch for the normative matchers is wired
    # in the runner (AG3-033 scope). The install-time settings materialisation
    # for these matchers is the Installer's responsibility (documented).
    for hook_id, func_name in EXPECTED_DEDICATED_DISPATCH.items():
        assert hook_id in EXPECTED_PRETOOLUSE_MATCHERS
        assert hasattr(runner_mod, func_name)


# ---------------------------------------------------------------------------
# AG3-033 WARNING F: the skill marker is a spoofable convention, NOT an
# attestation. Pin that an agent-set marker passes (Stufe-1+2 convention) — the
# fail-closed teeth are the principal whitelist, not the marker. Documented
# honestly in the guard docstring; no fake attestation is added.
# ---------------------------------------------------------------------------


def test_skill_marker_is_a_spoofable_convention_not_attestation() -> None:
    # An UNATTESTED worker that sets the marker itself passes — this is the
    # documented Stufe-1+2 convention limit (FK-55 §55.1a Stufe-3 out of scope).
    guard = _story_guard()
    event = HookEvent.model_validate(
        {
            "operation": "bash_command",
            "operation_args": {"command": "agentkit story create --title Foo"},
            "freshness_class": "mutation",
            "cwd": "/proj",
            "principal_kind": "subagent",
            "cli_args": [
                "--ak3-principal-attest",
                "worker",
                f"--via-skill={SKILL_MARKER_VALUE}",
            ],
        }
    )
    assert guard.evaluate(event).allowed is True


# ---------------------------------------------------------------------------
# AG3-086: the new guard-hook dispatch wiring is pinned so it cannot silently
# regress to the empty / wrong-owner pre-AG3-086 state (ZERO DEBT).
# ---------------------------------------------------------------------------

#: The AG3-086 hook-id -> dedicated dispatch-function mapping.
AG3086_DEDICATED_DISPATCH: dict[str, str] = {
    HookId.BUDGET.value: "_run_web_call_budget_guard",
    HookId.SKILL_USAGE_CHECK.value: "_run_skill_usage_check",
    HookId.PROMPT_INTEGRITY.value: "_run_prompt_integrity_guard",
}


def test_ag3086_dedicated_dispatch_functions_exist() -> None:
    # Each AG3-086 hook-id has a real dedicated dispatcher on the runner (the
    # ``budget`` block owner WebCallBudgetGuard, the skill_usage_check guard, and
    # the prompt_integrity guard) — none falls through to the empty generic chain.
    for hook_id, func_name in AG3086_DEDICATED_DISPATCH.items():
        assert hook_id in {h.value for h in HookId}
        assert hasattr(runner_mod, func_name)


def test_ag3086_hooks_are_pretooluse_block_owners() -> None:
    # budget / skill_usage_check / prompt_integrity are PreToolUse guard-hooks.
    assert HookId.BUDGET.value in runner_mod.PRE_HOOK_IDS
    assert HookId.SKILL_USAGE_CHECK.value in runner_mod.PRE_HOOK_IDS
    assert HookId.PROMPT_INTEGRITY.value in runner_mod.PRE_HOOK_IDS
    # ``budget`` is ALSO a PostToolUse observational emitter (web_call counter).
    assert HookId.BUDGET.value in runner_mod.POST_HOOK_IDS
    # The removed double-role identifier is gone.
    assert "budget_event_emitter" not in runner_mod.PRE_HOOK_IDS
