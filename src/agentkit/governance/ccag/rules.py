"""CCAG rule model, YAML loader and evaluation engine.

Adapted from AK2 (T:/codebase/claude-agentkit/agentkit/governance/ccag_rules.py)
to AK3 conventions: Pydantic v2 models, strict typing, AK3 path layout.

The config path is ``.agentkit/ccag/rules/`` per FK-42 §42.7.  AK2 used
``.claude/ccag/rules/`` — AK3 changes the root dir from ``.claude/`` to
``.agentkit/`` to stay consistent with the AK3 deployt-asset convention.

Evaluation order (FK-42 §42.2.1 / F-42-015):
    1. Block rules (highest priority — deny first)
    2. Allow rules (match → permit)
    3. No match → caller decides per operating mode (F-42-016)

Rule files loaded (FK-42 §42.7):
    - ``approved.yaml``   — session-persistent auto-learned rules (schema: F-42-024)
    - ``global.yaml``     — all agents
    - ``subagents.yaml``  — sub-agents only (narrower rights)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decision constants
# ---------------------------------------------------------------------------

#: CCAG decision: tool call is permitted.
DECISION_ALLOW: str = "allow"

#: CCAG decision: tool call is blocked by an explicit deny rule.
DECISION_BLOCK: str = "block_by_rule"

#: CCAG decision: no rule matches — mode-specific escalation.
DECISION_UNKNOWN: str = "unknown_permission"

#: Opaque block message shown to the agent (FK-42 / F-42-018 equivalent).
OPAQUE_MESSAGE: str = "Operation not permitted."

# ---------------------------------------------------------------------------
# Rule file names (FK-42 §42.7)
# ---------------------------------------------------------------------------

RULE_FILE_APPROVED: str = "approved.yaml"
RULE_FILE_GLOBAL: str = "global.yaml"
RULE_FILE_SUBAGENTS: str = "subagents.yaml"

# ---------------------------------------------------------------------------
# Scope constants
# ---------------------------------------------------------------------------

SCOPE_ALL: str = "all"
SCOPE_MAIN: str = "main"
SCOPE_SUB: str = "sub"
SCOPE_MAIN_AGENT: str = "main-agent"
SCOPE_SUBAGENT: str = "subagent"

# ReDoS protection: max input length for regex matching.
_REGEX_MAX_INPUT_LEN: int = 4096


def _scan_flat_group(pattern: str, start: int) -> tuple[int, bool] | None:
    """Scan the body of a flat group starting at ``pattern[start]`` (after ``"("``).

    Returns ``(close_idx, has_inner_quantifier)`` if a matching ``)`` is
    reached without seeing a nested ``(``.  Returns ``None`` when the
    body opens a nested group (this candidate cannot match the flat
    shape) or runs off the end without closing.

    Args:
        pattern: The full regex pattern.
        start: Index immediately after the opening ``(``.
    """
    inner_has_quantifier = False
    j = start
    n = len(pattern)
    while j < n and pattern[j] != ")":
        if pattern[j] == "(":
            return None
        if pattern[j] in "+*":
            inner_has_quantifier = True
        j += 1
    if j >= n:
        return None
    return j, inner_has_quantifier


def _has_nested_quantifier(pattern: str) -> bool:
    """Return ``True`` when *pattern* contains a flat ``(... [+*] ...)[+*]`` group.

    Detects the classic nested-quantifier shape that yields polynomial
    backtracking (e.g. ``(a+)+``).  Implemented as a single linear pass
    over the input so the detector itself cannot fall victim to ReDoS —
    a regex-based detector here would re-introduce the very risk we want
    to flag.

    Args:
        pattern: The user-supplied regex to inspect.

    Returns:
        ``True`` iff a group with an inner ``+``/``*`` is followed by an
        outer ``+``/``*``.
    """
    n = len(pattern)
    i = 0
    while i < n:
        if pattern[i] != "(":
            i += 1
            continue
        scan = _scan_flat_group(pattern, i + 1)
        if scan is None:
            # Nested ``(`` or unclosed — skip this opening paren.
            i += 1
            continue
        close_idx, inner_has_quantifier = scan
        if inner_has_quantifier and close_idx + 1 < n and pattern[close_idx + 1] in "+*":
            return True
        i = close_idx + 1
    return False


# ---------------------------------------------------------------------------
# CcagRule — Pydantic v2 model
# ---------------------------------------------------------------------------


class CcagRule(BaseModel):
    """A single CCAG permission rule (FK-42 §42.2.2).

    Rules match on tool name AND parameters using ``allow_pattern`` or
    ``block_pattern`` (regex).  Exactly one of these should be non-empty;
    if both are set ``block_pattern`` takes precedence (F-42-015).

    Attributes:
        rule_id: Unique rule identifier.
        tool: Tool name or pipe-delimited list (e.g. ``"Bash"`` or ``"Write|Edit"``).
        allow_pattern: Regex matched against serialised tool input — match → allow.
        block_pattern: Regex matched against serialised tool input — match → block.
        scope: One of ``all``, ``main``, ``sub``, ``main-agent``, ``subagent``.
        description: Human-readable description shown in logs.
        learned_from: Original tool invocation that triggered rule creation (F-42-024).
        learned_at: ISO-8601 timestamp of rule creation (F-42-024).
        priority: Lower = higher priority within same rule type.
        conditions: Structured condition list for parameter-based rules (FK-42 §42.2.2).
        decision: Explicit ``allow`` / ``deny`` decision from YAML (overrides patterns).
        applies_to: ``all`` / ``main`` / ``sub`` from bundle YAML format.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    tool: str
    allow_pattern: str = ""
    block_pattern: str = ""
    scope: str = SCOPE_ALL
    description: str = ""
    learned_from: str = ""
    learned_at: str = ""
    priority: int = 100
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    decision: str = ""
    applies_to: str = SCOPE_ALL

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, value: object) -> int:
        try:
            if isinstance(value, (int, float, str, bytes)):
                return int(value)
            return 100
        except (ValueError, TypeError):
            return 100

    @property
    def is_block_rule(self) -> bool:
        """Return True when this rule can produce a block decision."""
        if self.decision in ("deny", "block", "block_by_rule"):
            return True
        return bool(self.block_pattern)

    @property
    def is_allow_rule(self) -> bool:
        """Return True when this rule can produce an allow decision."""
        if self.decision == "allow":
            return True
        return bool(self.allow_pattern) and not self.block_pattern

    @property
    def effective_scope(self) -> str:
        """Return the normalised scope string (prefers ``applies_to`` when set)."""
        at = self.applies_to.strip().lower()
        if at and at != SCOPE_ALL:
            return at
        sc = self.scope.strip().lower()
        return sc if sc else SCOPE_ALL


# ---------------------------------------------------------------------------
# CcagRuleSet
# ---------------------------------------------------------------------------


class CcagRuleSet(BaseModel):
    """Collection of block and allow rules for a given agent scope.

    Attributes:
        blocks: Rules that can produce a ``block_by_rule`` decision (evaluated first).
        allows: Rules that can produce an ``allow`` decision.
    """

    model_config = ConfigDict(frozen=True)

    blocks: tuple[CcagRule, ...] = ()
    allows: tuple[CcagRule, ...] = ()


# ---------------------------------------------------------------------------
# YAML parsing helpers
# ---------------------------------------------------------------------------


def _parse_rule_entry(entry: dict[str, Any], source_file: str = "") -> CcagRule | None:
    """Parse one YAML rule entry dict into a :class:`CcagRule`.

    Supports both the bundle YAML format (``rule_id``, ``conditions``,
    ``decision``, ``applies_to``) and the simpler approved.yaml format
    (``id``, ``allow_pattern``/``block_pattern``, ``scope``).

    Returns ``None`` when the entry is missing a required ``tool`` field or
    the priority value is invalid.

    Args:
        entry: Raw YAML dict for a single rule.
        source_file: Source filename for log context.

    Returns:
        A parsed :class:`CcagRule`, or ``None`` on failure.
    """
    tool = str(entry.get("tool", "")).strip()
    if not tool:
        return None

    rule_id = str(entry.get("rule_id") or entry.get("id") or "").strip()
    if not rule_id:
        rule_id = f"{source_file}:{tool}"

    raw_priority = entry.get("priority", 100)
    try:
        priority = int(str(raw_priority))
    except (ValueError, TypeError):
        _logger.warning(
            "Invalid priority %r in rule %r (source: %s) — skipping",
            raw_priority,
            rule_id,
            source_file,
        )
        return None

    conditions_raw = entry.get("conditions")
    conditions: list[dict[str, Any]] = list(conditions_raw) if conditions_raw else []

    try:
        return CcagRule(
            rule_id=rule_id,
            tool=tool,
            allow_pattern=str(entry.get("allow_pattern", "")).strip(),
            block_pattern=str(entry.get("block_pattern", "")).strip(),
            decision=str(entry.get("decision", "")).strip().lower(),
            applies_to=str(entry.get("applies_to", SCOPE_ALL)).strip().lower(),
            scope=str(entry.get("scope", SCOPE_ALL)).strip().lower(),
            description=str(
                entry.get("description", entry.get("reason", ""))
            ).strip(),
            priority=priority,
            conditions=conditions,
            learned_from=str(entry.get("learned_from", "")).strip(),
            learned_at=str(entry.get("learned_at", "")).strip(),
        )
    except Exception:  # noqa: BLE001
        _logger.warning("Failed to parse rule %r in %s", rule_id, source_file)
        return None


def _load_yaml_rules(path: Path) -> list[CcagRule]:
    """Load rules from a YAML file.

    Supports both top-level ``rules:`` key (bundle format) and a bare
    top-level list (approved.yaml format).

    Returns an empty list when the file does not exist or cannot be parsed.

    Args:
        path: Path to the YAML rule file.

    Returns:
        List of parsed :class:`CcagRule` instances.
    """
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _logger.warning("Failed to parse YAML rule file %s", path)
        return []

    if raw is None:
        return []

    if isinstance(raw, dict) and "rules" in raw:
        entries = raw["rules"]
    elif isinstance(raw, list):
        entries = raw
    else:
        return []

    rules: list[CcagRule] = []
    for entry in entries or []:
        rule = _parse_rule_entry(entry, source_file=path.name)
        if rule is not None:
            rules.append(rule)
    return rules


# ---------------------------------------------------------------------------
# Rule loading — composite view for a given agent scope
# ---------------------------------------------------------------------------

#: Default rules directory relative to the project root (FK-42 §42.7).
DEFAULT_RULES_SUBDIR = ".agentkit/ccag/rules"


def _default_rules_dir() -> Path:
    return Path.cwd() / DEFAULT_RULES_SUBDIR


def load_rules(is_subagent: bool, rules_dir: Path | str | None = None) -> CcagRuleSet:
    """Load and partition CCAG rules for the given agent scope.

    Loads rules from the canonical rule files and filters by scope:

    * ``approved.yaml``  — auto-learned rules (loaded first)
    * ``global.yaml``    — all agents
    * ``subagents.yaml`` — sub-agents only (omitted for main agent)

    The returned :class:`CcagRuleSet` partitions rules into ``blocks`` and
    ``allows``, sorted ascending by priority within each partition.

    **Immediate-propagation design**: reads YAML files from disk on every call
    (no in-process cache) so that rules added by one session take effect for
    all sessions on the next hook invocation.

    Args:
        is_subagent: ``True`` when the caller is a sub-agent.
        rules_dir: Path to the ``ccag/rules/`` directory.
            Defaults to ``.agentkit/ccag/rules/`` relative to CWD.

    Returns:
        :class:`CcagRuleSet` with pre-partitioned block and allow lists.
    """
    rules_dir_path = (
        Path(rules_dir) if rules_dir is not None else _default_rules_dir()
    )

    raw: list[CcagRule] = []
    raw.extend(_load_yaml_rules(rules_dir_path / RULE_FILE_APPROVED))
    raw.extend(_load_yaml_rules(rules_dir_path / RULE_FILE_GLOBAL))
    if is_subagent:
        raw.extend(_load_yaml_rules(rules_dir_path / RULE_FILE_SUBAGENTS))

    blocks: list[CcagRule] = []
    allows: list[CcagRule] = []

    for rule in raw:
        scope = rule.effective_scope
        if is_subagent and scope in (SCOPE_MAIN, SCOPE_MAIN_AGENT):
            continue
        if not is_subagent and scope in (SCOPE_SUB, SCOPE_SUBAGENT):
            continue

        if rule.is_block_rule:
            blocks.append(rule)
        elif rule.is_allow_rule:
            allows.append(rule)

    blocks.sort(key=lambda r: r.priority)
    allows.sort(key=lambda r: r.priority)

    return CcagRuleSet(blocks=tuple(blocks), allows=tuple(allows))


# ---------------------------------------------------------------------------
# Rule matching (FK-42 §42.2.2)
# ---------------------------------------------------------------------------


def _tool_matches(rule_tool: str, tool_name: str) -> bool:
    """Return True when ``tool_name`` matches the rule's tool spec.

    Rule tool can be:
    - Exact name: ``"Bash"``
    - Pipe-delimited alternatives: ``"Write|Edit"``
    - Wildcard suffix: ``"mcp__*"`` (star matches suffix)

    Args:
        rule_tool: The tool spec from the rule.
        tool_name: The actual tool name from the hook event.

    Returns:
        True when the tool matches.
    """
    if "|" in rule_tool:
        return tool_name in {t.strip() for t in rule_tool.split("|")}
    if "*" in rule_tool:
        if rule_tool.startswith("*"):
            return tool_name.endswith(rule_tool[1:])
        if rule_tool.endswith("*"):
            return tool_name.startswith(rule_tool[:-1])
    return rule_tool.strip() == tool_name


def _safe_regex_search(pattern: str, text: str) -> re.Match[str] | None:
    """Run ``re.search`` with ReDoS protection.

    Two layers of defence:
    1. Reject patterns with nested quantifiers (catastrophic backtracking).
    2. Truncate input to ``_REGEX_MAX_INPUT_LEN`` chars to bound worst-case time.

    Args:
        pattern: Regex pattern to evaluate.
        text: Input text to search.

    Returns:
        The match object if found, else ``None``.
    """
    if _has_nested_quantifier(pattern):
        _logger.warning(
            "Rejected regex %r — nested quantifiers (potential ReDoS); treating as no-match",
            pattern[:80],
        )
        return None
    truncated = text[:_REGEX_MAX_INPUT_LEN]
    return re.search(pattern, truncated)


def _serialise_input(tool_input: dict[str, Any]) -> str:
    """Produce a flat string representation of tool_input for regex matching.

    All key-value pairs are concatenated as ``key:value`` pairs joined by
    spaces.  This lets rules use simple regex patterns without needing to
    know the exact JSON structure (FK-42 §42.2.2).

    Args:
        tool_input: The tool input dict from the hook event.

    Returns:
        Serialised string for regex matching.
    """
    return " ".join(f"{k}:{v}" for k, v in tool_input.items())


def _condition_matches(
    condition: dict[str, Any],
    tool_input: dict[str, Any],
) -> bool:
    """Evaluate one parameter-based condition dict against tool_input (FK-42 §42.2.2).

    Condition dict fields:
        ``param``:       Tool input parameter name to test.
        ``matches``:     Regex that must match the param value.
        ``not_matches``: Regex that must NOT match the param value.

    Args:
        condition: The condition dict from the rule.
        tool_input: The tool input dict from the hook event.

    Returns:
        True when the condition is satisfied.
    """
    param = str(condition.get("param", ""))
    value = str(tool_input.get(param, ""))

    matches_pattern = condition.get("matches")
    not_matches_pattern = condition.get("not_matches")

    try:
        if matches_pattern is not None and not _safe_regex_search(
            str(matches_pattern), value
        ):
            return False
    except re.error as exc:
        _logger.warning(
            "Invalid regex in condition 'matches' pattern %r: %s — treating as no-match",
            matches_pattern,
            exc,
        )
        return False

    try:
        if not_matches_pattern is not None and _safe_regex_search(
            str(not_matches_pattern), value
        ):
            return False
    except re.error as exc:
        _logger.warning(
            "Invalid regex in condition 'not_matches' pattern %r: %s — fail-closed",
            not_matches_pattern,
            exc,
        )
        return False  # fail-closed: broken exclusion constraint must not pass

    return True


def rule_matches(rule: CcagRule, tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Return True when *rule* matches the given tool invocation (FK-42 §42.2.2).

    Matching algorithm:
    1. Tool name must match the rule's ``tool`` field.
    2. If the rule has structured ``conditions``, all conditions must pass.
    3. If the rule has ``allow_pattern`` or ``block_pattern``, the regex is
       matched against the serialised tool input string.
    4. If the rule has an explicit ``decision`` but no pattern/conditions,
       the rule matches solely on the tool name (unconditional rule).

    Args:
        rule: The :class:`CcagRule` to evaluate.
        tool_name: Tool name from the hook event.
        tool_input: Tool input dict from the hook event.

    Returns:
        True when the rule fires for this invocation.
    """
    if not _tool_matches(rule.tool, tool_name):
        return False

    if rule.conditions:
        return all(_condition_matches(c, tool_input) for c in rule.conditions)

    active_pattern = rule.block_pattern or rule.allow_pattern
    if active_pattern:
        try:
            # Special handling for file_path anchor patterns (G19 FIX from AK2)
            if active_pattern.startswith("^file_path:"):
                file_path_value = str(tool_input.get("file_path", ""))
                value_pattern = "^" + active_pattern[len("^file_path:"):]
                return bool(_safe_regex_search(value_pattern, file_path_value))

            serialised = _serialise_input(tool_input)
            if _safe_regex_search(active_pattern, serialised):
                return True
            # Also match against individual parameter values for backwards compat
            return any(
                _safe_regex_search(active_pattern, str(v))
                for v in tool_input.values()
            )
        except re.error as exc:
            _logger.warning(
                "Invalid regex in rule %r pattern %r: %s — treating as no-match",
                rule.rule_id,
                active_pattern,
                exc,
            )
            return False

    # Unconditional rule (explicit decision, no pattern, no conditions)
    return bool(rule.decision)


# ---------------------------------------------------------------------------
# approved.yaml persistence (FK-42 §42.7 / F-42-024)
# ---------------------------------------------------------------------------


def append_approved_rule(rule: CcagRule, rules_dir: Path | str) -> None:
    """Append *rule* to ``approved.yaml`` in the given rules directory.

    Creates the file and parent directories if they do not exist.
    Existing rules are preserved (append-only).

    Args:
        rule: The :class:`CcagRule` to persist.
        rules_dir: Path to the ``ccag/rules/`` directory.
    """
    rules_dir_path = Path(rules_dir)
    rules_dir_path.mkdir(parents=True, exist_ok=True)
    approved_path = rules_dir_path / RULE_FILE_APPROVED

    existing: list[dict[str, Any]] = []
    if approved_path.is_file():
        try:
            raw = yaml.safe_load(approved_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                existing = raw
        except Exception:  # noqa: BLE001
            pass

    entry: dict[str, Any] = {
        "id": rule.rule_id,
        "tool": rule.tool,
        "allow_pattern": rule.allow_pattern,
        "learned_from": rule.learned_from,
        "learned_at": rule.learned_at,
        "scope": rule.scope if rule.scope else SCOPE_MAIN_AGENT,
    }
    if rule.block_pattern:
        entry["block_pattern"] = rule.block_pattern
    if rule.decision:
        entry["decision"] = rule.decision

    existing.append(entry)

    header = (
        "# approved.yaml — session-persistent CCAG rules (FK-42 §42.7)\n"
        "# Fields: id, tool, allow_pattern, learned_from, learned_at, scope\n\n"
    )
    approved_path.write_text(
        header + yaml.dump(existing, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


__all__ = [
    "DECISION_ALLOW",
    "DECISION_BLOCK",
    "DECISION_UNKNOWN",
    "DEFAULT_RULES_SUBDIR",
    "OPAQUE_MESSAGE",
    "RULE_FILE_APPROVED",
    "RULE_FILE_GLOBAL",
    "RULE_FILE_SUBAGENTS",
    "SCOPE_ALL",
    "SCOPE_MAIN",
    "SCOPE_MAIN_AGENT",
    "SCOPE_SUB",
    "SCOPE_SUBAGENT",
    "CcagRule",
    "CcagRuleSet",
    "append_approved_rule",
    "load_rules",
    "rule_matches",
]
