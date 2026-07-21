"""Structural compile of the formal-spec corpus (FK-78 section 78.14).

Every Markdown file below the formal root (except ``00_meta`` and
``README.md``) must carry frontmatter with ``id``/``context``/``spec_kind``/
``version``/``prose_refs`` and exactly one ``FORMAL-SPEC`` zone with a
```` ```yaml ```` fence that parses as SMY. The zone header must match the
frontmatter, the ``kind`` must be one of the six object kinds, kind-specific
mandatory keys must be present, and all internal id references must resolve
within the context. State machines need exactly one initial state per axis
(explicitly marked, or derivable as the unique zero-in-degree state) and at
least one terminal state on the status axis; scenarios must end terminal.
Reciprocity: every ``prose_refs`` file exists and, when it carries
``formal_refs``, lists the formal object id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .docmodel import load_document, split_frontmatter
from .findings import CheckResult, error
from .smy import SmyError, parse_smy

if TYPE_CHECKING:
    from pathlib import Path

    from .config import GovernanceConfig

CHECK_ID = "formal"
SPEC_BEGIN = "<!-- FORMAL-SPEC:BEGIN -->"
SPEC_END = "<!-- FORMAL-SPEC:END -->"
OBJECT_KINDS = ("state-machine", "command-set", "event-set", "invariant-set", "scenario-set", "entity-set")


@dataclass(frozen=True)
class SpecZone:
    """Extracted FORMAL-SPEC YAML zone with its 1-based payload start line."""

    payload: str
    payload_start_line: int


@dataclass
class _SpecDoc:
    rel_path: str
    object_id: str
    context: str
    kind: str
    spec: dict[str, object]
    prose_refs: tuple[str, ...]


@dataclass
class _Axis:
    name: str
    states: dict[str, dict[str, object]] = field(default_factory=dict)
    terminal: set[str] = field(default_factory=set)
    explicit_initial: list[str] = field(default_factory=list)
    incoming: dict[str, int] = field(default_factory=dict)


@dataclass
class _Context:
    name: str
    status_states: set[str] = field(default_factory=set)
    terminal_states: set[str] = field(default_factory=set)
    phase_states: set[str] = field(default_factory=set)
    has_machine: bool = False
    invariants: set[str] = field(default_factory=set)
    events: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _PendingRef:
    """One deferred id reference, resolved after all contexts are known."""

    spec: _SpecDoc
    locator: str
    kind: str
    reference: str


def extract_spec_zone(text: str) -> SpecZone | None:
    """Return the single well-formed FORMAL-SPEC zone of *text*, if any."""
    if text.count(SPEC_BEGIN) != 1 or text.count(SPEC_END) != 1:
        return None
    begin = text.index(SPEC_BEGIN) + len(SPEC_BEGIN)
    end = text.index(SPEC_END)
    if end < begin:
        return None
    block = text[begin:end].strip()
    if not block.startswith("```yaml") or not block.endswith("```"):
        return None
    payload = block.removeprefix("```yaml").removesuffix("```").strip("\n")
    prefix = text[: text.index(SPEC_BEGIN)]
    fence_offset = text[begin:end].index("```yaml")
    payload_start_line = prefix.count("\n") + text[begin : begin + fence_offset].count("\n") + 3
    return SpecZone(payload=payload, payload_start_line=payload_start_line)


def run_formal_check(project_root: Path, config: GovernanceConfig) -> CheckResult:
    """Run the formal structural compile against the formal corpus."""
    result = CheckResult(check_id=CHECK_ID)
    formal_root = config.root_path(project_root, "formal")
    if not formal_root.is_dir():
        result.complete = False
        result.incomplete_reason = f"missing formal root: {config.concept_roots['formal']}"
        return result
    specs: list[_SpecDoc] = []
    for path in sorted(formal_root.rglob("*.md")):
        relative_parts = path.relative_to(formal_root).parts
        if path.name == "README.md" or "00_meta" in relative_parts:
            continue
        spec = _load_spec(project_root, path, config, result)
        if spec is not None:
            specs.append(spec)
    declared_ids = _collect_declared_ids(specs, result)
    contexts, pending = _build_contexts(specs, result)
    for reference in pending:
        _resolve_reference(reference, contexts[reference.spec.context], declared_ids, result)
    _check_reciprocity(project_root, specs, result)
    result.summary = f"{len(specs)} spec documents, {len(contexts)} contexts"
    return result


def _load_spec(project_root: Path, path: Path, config: GovernanceConfig, result: CheckResult) -> _SpecDoc | None:
    doc = load_document(project_root, "formal", path)
    if doc.frontmatter_error is not None:
        message = f"frontmatter is not parseable SMY: {doc.frontmatter_error}"
        result.findings.append(error(f"{CHECK_ID}.frontmatter", doc.rel_path, f"L{doc.frontmatter_error_line}", message))
        return None
    if doc.frontmatter is None:
        result.findings.append(error(f"{CHECK_ID}.frontmatter", doc.rel_path, "L1", "formal spec file has no frontmatter"))
        return None
    header = _validate_frontmatter(doc.rel_path, doc.frontmatter, config, result)
    if header is None:
        return None
    object_id, context, spec_kind, prose_refs = header
    spec = _parse_zone(doc.rel_path, doc.text, result)
    if spec is None:
        return None
    if not _validate_zone_header(doc.rel_path, spec, object_id, context, spec_kind, result):
        return None
    return _SpecDoc(rel_path=doc.rel_path, object_id=object_id, context=context, kind=spec_kind, spec=spec, prose_refs=prose_refs)


def _validate_frontmatter(
    rel_path: str, frontmatter: dict[str, object], config: GovernanceConfig, result: CheckResult
) -> tuple[str, str, str, tuple[str, ...]] | None:
    ok = True
    for field_name in ("id", "context", "spec_kind", "version", "prose_refs"):
        if field_name not in frontmatter:
            result.findings.append(
                error(f"{CHECK_ID}.frontmatter", rel_path, field_name, f"required frontmatter field {field_name!r} is missing")
            )
            ok = False
    if not ok:
        return None
    object_id = frontmatter.get("id")
    context = frontmatter.get("context")
    spec_kind = frontmatter.get("spec_kind")
    version = frontmatter.get("version")
    prose_refs = frontmatter.get("prose_refs")
    for field_name, value in (("id", object_id), ("context", context), ("spec_kind", spec_kind)):
        if not isinstance(value, str) or not value:
            message = f"{field_name!r} must be a non-empty string"
            result.findings.append(error(f"{CHECK_ID}.frontmatter", rel_path, field_name, message))
            ok = False
    if not isinstance(version, (str, int)) or version == "":
        message = "'version' must be a non-empty string or integer"
        result.findings.append(error(f"{CHECK_ID}.frontmatter", rel_path, "version", message))
        ok = False
    if not isinstance(prose_refs, list) or not prose_refs or not all(isinstance(item, str) and item for item in prose_refs):
        result.findings.append(
            error(f"{CHECK_ID}.frontmatter", rel_path, "prose_refs", "'prose_refs' must be a non-empty list of non-empty strings")
        )
        ok = False
    if not ok:
        return None
    assert isinstance(object_id, str) and isinstance(context, str) and isinstance(spec_kind, str)
    assert isinstance(prose_refs, list)
    if config.id_grammars["formal_object"].fullmatch(object_id) is None:
        result.findings.append(
            error(f"{CHECK_ID}.frontmatter", rel_path, "id", f"id {object_id!r} does not match the formal_object grammar")
        )
    return object_id, context, spec_kind, tuple(ref for ref in prose_refs if isinstance(ref, str))


def _parse_zone(rel_path: str, text: str, result: CheckResult) -> dict[str, object] | None:
    begin_count = text.count(SPEC_BEGIN)
    end_count = text.count(SPEC_END)
    if begin_count != 1 or end_count != 1:
        message = f"file must contain exactly one FORMAL-SPEC zone (begin={begin_count}, end={end_count})"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "FORMAL-SPEC", message))
        return None
    zone = extract_spec_zone(text)
    if zone is None:
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "FORMAL-SPEC", "FORMAL-SPEC zone must be fenced as ```yaml"))
        return None
    try:
        return parse_smy(zone.payload)
    except SmyError as exc:
        message = f"FORMAL-SPEC zone is not parseable SMY: {exc.message}"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, f"L{zone.payload_start_line + exc.line - 1}", message))
        return None


def _validate_zone_header(
    rel_path: str, spec: dict[str, object], object_id: str, context: str, spec_kind: str, result: CheckResult
) -> bool:
    ok = True
    for key in ("object", "schema_version", "kind", "context"):
        if key not in spec:
            result.findings.append(error(f"{CHECK_ID}.zone", rel_path, key, f"FORMAL-SPEC zone is missing required key {key!r}"))
            ok = False
    if not ok:
        return False
    if spec.get("object") != object_id:
        message = f"zone object {spec.get('object')!r} differs from frontmatter id {object_id!r}"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "object", message))
        ok = False
    if spec.get("kind") not in OBJECT_KINDS:
        message = f"kind {spec.get('kind')!r} is not one of {', '.join(OBJECT_KINDS)}"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "kind", message))
        ok = False
    elif spec.get("kind") != spec_kind:
        message = f"zone kind {spec.get('kind')!r} differs from frontmatter spec_kind {spec_kind!r}"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "kind", message))
        ok = False
    if spec.get("context") != context:
        message = f"zone context {spec.get('context')!r} differs from frontmatter context {context!r}"
        result.findings.append(error(f"{CHECK_ID}.zone", rel_path, "context", message))
        ok = False
    return ok


def _collect_declared_ids(specs: list[_SpecDoc], result: CheckResult) -> frozenset[str]:
    declared: dict[str, str] = {}
    for spec in specs:
        if spec.object_id in declared:
            message = f"formal object id {spec.object_id!r} is declared more than once"
            result.findings.append(error(f"{CHECK_ID}.duplicate-id", spec.rel_path, "object", message))
        declared[spec.object_id] = spec.rel_path
        for item_id in _walk_ids(spec.spec):
            if item_id in declared:
                message = f"formal item id {item_id!r} is declared more than once"
                result.findings.append(error(f"{CHECK_ID}.duplicate-id", spec.rel_path, item_id, message))
            declared[item_id] = spec.rel_path
    return frozenset(declared)


def _walk_ids(node: object) -> list[str]:
    ids: list[str] = []
    if isinstance(node, dict):
        value = node.get("id")
        if isinstance(value, str) and value:
            ids.append(value)
        for child in node.values():
            ids.extend(_walk_ids(child))
    elif isinstance(node, list):
        for child in node:
            ids.extend(_walk_ids(child))
    return ids


def _items(spec: _SpecDoc, key: str, result: CheckResult) -> list[dict[str, object]]:
    raw = spec.spec.get(key)
    if not isinstance(raw, list):
        result.findings.append(error(f"{CHECK_ID}.kind-keys", spec.rel_path, key, f"{spec.kind} requires the list key {key!r}"))
        return []
    items: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry.get("id"):
            message = f"every {key} entry requires a non-empty string id"
            result.findings.append(error(f"{CHECK_ID}.kind-keys", spec.rel_path, key, message))
            continue
        items.append(entry)
    return items


def _build_contexts(specs: list[_SpecDoc], result: CheckResult) -> tuple[dict[str, _Context], list[_PendingRef]]:
    contexts: dict[str, _Context] = {}
    pending: list[_PendingRef] = []
    for spec in specs:
        context = contexts.setdefault(spec.context, _Context(name=spec.context))
        if spec.kind == "state-machine":
            _register_state_machine(spec, context, pending, result)
        elif spec.kind == "command-set":
            _register_commands(spec, context, pending, result)
        elif spec.kind == "event-set":
            context.events.update(
                item_id for item in _items(spec, "events", result) if isinstance(item_id := item.get("id"), str)
            )
        elif spec.kind == "invariant-set":
            _register_invariants(spec, context, pending, result)
        elif spec.kind == "scenario-set":
            _register_scenarios(spec, pending, result)
        elif spec.kind == "entity-set":
            _register_entities(spec, result)
    return contexts, pending


def _register_entities(spec: _SpecDoc, result: CheckResult) -> None:
    """Validate the entity-set body.

    The canonical mandatory key is ``entities``. Register-style entity
    sets without it are accepted when at least one non-header top-level
    key carries a list of id-bearing mappings (e.g. component registers);
    an entity-set without any such register is an ERROR.
    """
    if "entities" in spec.spec:
        _items(spec, "entities", result)
        return
    header_keys = ("object", "schema_version", "kind", "context")
    found_register = False
    for key, value in spec.spec.items():
        if key in header_keys or not isinstance(value, list) or not value:
            continue
        if not all(isinstance(entry, dict) for entry in value):
            continue
        for entry in value:
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                result.findings.append(
                    error(f"{CHECK_ID}.kind-keys", spec.rel_path, key, f"every {key} entry requires a non-empty string id")
                )
                break
        else:
            found_register = True
    if not found_register:
        result.findings.append(
            error(
                f"{CHECK_ID}.kind-keys",
                spec.rel_path,
                "entities",
                "entity-set requires the list key 'entities' or at least one id-bearing register list",
            )
        )


def _register_state_machine(spec: _SpecDoc, context: _Context, pending: list[_PendingRef], result: CheckResult) -> None:
    context.has_machine = True
    single = "states" in spec.spec or "transitions" in spec.spec
    dual = "status_axis" in spec.spec or "phase_axis" in spec.spec
    if single == dual:
        message = "state machine requires either states+transitions or status_axis+phase_axis"
        result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, "states", message))
        return
    if single:
        axis = _load_axis(spec, spec.spec, "states", pending, result)
        context.status_states = set(axis.states)
        context.terminal_states = axis.terminal
        _check_axis_rules(spec, axis, result, require_terminal=True)
        return
    for axis_name, is_status in (("status_axis", True), ("phase_axis", False)):
        axis_spec = spec.spec.get(axis_name)
        if not isinstance(axis_spec, dict):
            message = f"{axis_name} must be a mapping with states and transitions"
            result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis_name, message))
            continue
        axis = _load_axis(spec, axis_spec, axis_name, pending, result)
        if is_status:
            context.status_states = set(axis.states)
            context.terminal_states = axis.terminal
        else:
            context.phase_states = set(axis.states)
        _check_axis_rules(spec, axis, result, require_terminal=is_status)


def _load_axis(
    spec: _SpecDoc, axis_spec: dict[str, object], axis_name: str, pending: list[_PendingRef], result: CheckResult
) -> _Axis:
    axis = _Axis(name=axis_name)
    raw_states = axis_spec.get("states")
    raw_transitions = axis_spec.get("transitions")
    if not isinstance(raw_states, list) or not isinstance(raw_transitions, list):
        message = f"{axis_name} requires states and transitions lists"
        result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis_name, message))
        return axis
    for entry in raw_states:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry.get("id"):
            message = "every state requires a non-empty string id"
            result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis_name, message))
            continue
        state_id = entry["id"]
        assert isinstance(state_id, str)
        axis.states[state_id] = entry
        axis.incoming.setdefault(state_id, 0)
        if entry.get("terminal") is True:
            axis.terminal.add(state_id)
        if entry.get("initial") is True:
            axis.explicit_initial.append(state_id)
    for entry in raw_transitions:
        if not isinstance(entry, dict):
            message = "every transition must be a mapping"
            result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis_name, message))
            continue
        _register_transition(spec, axis, entry, pending, result)
    return axis


def _register_transition(
    spec: _SpecDoc, axis: _Axis, entry: dict[str, object], pending: list[_PendingRef], result: CheckResult
) -> None:
    transition_id = entry.get("id")
    locator = transition_id if isinstance(transition_id, str) and transition_id else axis.name
    for key in ("from", "to"):
        target = entry.get(key)
        if not isinstance(target, str) or not target:
            message = f"transition requires a non-empty {key!r} state"
            result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, locator, message))
            continue
        if target not in axis.states:
            message = f"transition {key} state {target!r} is not declared in {axis.name}"
            result.findings.append(error(f"{CHECK_ID}.reference", spec.rel_path, locator, message))
        elif key == "to":
            axis.incoming[target] = axis.incoming.get(target, 0) + 1
    guard = entry.get("guard")
    if guard is not None:
        if not isinstance(guard, str) or not guard:
            message = "guard must be a non-empty string when present"
            result.findings.append(error(f"{CHECK_ID}.reference", spec.rel_path, locator, message))
        else:
            pending.append(_PendingRef(spec, locator, "invariant", guard))


def _register_commands(spec: _SpecDoc, context: _Context, pending: list[_PendingRef], result: CheckResult) -> None:
    for item in _items(spec, "commands", result):
        command_id = item["id"]
        assert isinstance(command_id, str)
        context.commands.add(command_id)
        for kind, key in (("status", "allowed_statuses"), ("invariant", "requires"), ("event", "emits")):
            pending.extend(
                _PendingRef(spec, command_id, kind, reference) for reference in _string_list(spec, item, key, result)
            )


def _register_invariants(spec: _SpecDoc, context: _Context, pending: list[_PendingRef], result: CheckResult) -> None:
    for item in _items(spec, "invariants", result):
        invariant_id = item["id"]
        assert isinstance(invariant_id, str)
        context.invariants.add(invariant_id)
        pending.extend(
            _PendingRef(spec, invariant_id, "corpus", reference) for reference in _string_list(spec, item, "requires", result)
        )


def _register_scenarios(spec: _SpecDoc, pending: list[_PendingRef], result: CheckResult) -> None:
    for item in _items(spec, "scenarios", result):
        scenario_id = item["id"]
        assert isinstance(scenario_id, str)
        _register_scenario_states(spec, item, scenario_id, pending, result)
        trace = item.get("trace")
        if not isinstance(trace, list) or not trace:
            message = "scenario requires a non-empty trace list"
            result.findings.append(error(f"{CHECK_ID}.scenario", spec.rel_path, scenario_id, message))
        else:
            for step in trace:
                command = step.get("command") if isinstance(step, dict) else None
                if not isinstance(command, str) or not command:
                    result.findings.append(
                        error(f"{CHECK_ID}.scenario", spec.rel_path, scenario_id, "every trace step requires a non-empty command")
                    )
                    continue
                pending.append(_PendingRef(spec, scenario_id, "command", command))
        pending.extend(
            _PendingRef(spec, scenario_id, "invariant", reference) for reference in _string_list(spec, item, "requires", result)
        )


def _register_scenario_states(
    spec: _SpecDoc, item: dict[str, object], scenario_id: str, pending: list[_PendingRef], result: CheckResult
) -> None:
    for key, terminal_required in (("start", False), ("expected_end", True)):
        section = item.get(key)
        if not isinstance(section, dict) or not isinstance(section.get("status"), str) or not section.get("status"):
            result.findings.append(
                error(f"{CHECK_ID}.scenario", spec.rel_path, scenario_id, f"scenario requires {key}.status as a non-empty string")
            )
            continue
        status = section["status"]
        assert isinstance(status, str)
        pending.append(_PendingRef(spec, scenario_id, "terminal-status" if terminal_required else "status", status))
        phase = section.get("phase")
        if isinstance(phase, str) and phase:
            pending.append(_PendingRef(spec, scenario_id, "phase", phase))


def _string_list(spec: _SpecDoc, item: dict[str, object], key: str, result: CheckResult) -> list[str]:
    raw = item.get(key)
    if raw is None:
        return []
    item_id = item.get("id")
    locator = item_id if isinstance(item_id, str) else key
    if not isinstance(raw, list) or not all(isinstance(entry, str) and entry for entry in raw):
        message = f"{key!r} must be a list of non-empty strings"
        result.findings.append(error(f"{CHECK_ID}.reference", spec.rel_path, locator, message))
        return []
    return list(raw)


def _resolve_reference(
    reference: _PendingRef, context: _Context, declared_ids: frozenset[str], result: CheckResult
) -> None:
    if reference.kind == "corpus":
        if reference.reference not in declared_ids:
            result.findings.append(
                error(
                    f"{CHECK_ID}.reference",
                    reference.spec.rel_path,
                    reference.locator,
                    f"reference {reference.reference!r} is not declared anywhere in the formal corpus",
                )
            )
        return
    if reference.kind in ("status", "terminal-status", "phase"):
        _resolve_state_reference(reference, context, result)
        return
    pools = {"invariant": context.invariants, "event": context.events, "command": context.commands}
    if reference.reference not in pools[reference.kind]:
        result.findings.append(
            error(
                f"{CHECK_ID}.reference",
                reference.spec.rel_path,
                reference.locator,
                f"{reference.kind} reference {reference.reference!r} does not resolve in context {context.name!r}",
            )
        )


def _resolve_state_reference(reference: _PendingRef, context: _Context, result: CheckResult) -> None:
    rel_path = reference.spec.rel_path
    if not context.has_machine:
        result.findings.append(
            error(
                f"{CHECK_ID}.reference",
                rel_path,
                reference.locator,
                f"context {context.name!r} references state {reference.reference!r} but declares no state machine",
            )
        )
        return
    pool = context.phase_states if reference.kind == "phase" else context.status_states
    if reference.reference not in pool:
        axis = "phase axis" if reference.kind == "phase" else "status axis"
        result.findings.append(
            error(
                f"{CHECK_ID}.reference",
                rel_path,
                reference.locator,
                f"state {reference.reference!r} is not declared on the {axis} of context {context.name!r}",
            )
        )
        return
    if reference.kind == "terminal-status" and reference.reference not in context.terminal_states:
        result.findings.append(
            error(
                f"{CHECK_ID}.scenario",
                rel_path,
                reference.locator,
                f"scenario must end in a terminal status, {reference.reference!r} is not terminal",
            )
        )


def _check_axis_rules(spec: _SpecDoc, axis: _Axis, result: CheckResult, *, require_terminal: bool) -> None:
    if not axis.states:
        result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis.name, f"{axis.name} declares no states"))
        return
    if len(axis.explicit_initial) > 1:
        message = f"exactly one initial state required, got {', '.join(sorted(axis.explicit_initial))}"
        result.findings.append(error(f"{CHECK_ID}.state-machine", spec.rel_path, axis.name, message))
    elif not axis.explicit_initial:
        roots = sorted(state for state, count in axis.incoming.items() if count == 0)
        if len(roots) != 1:
            result.findings.append(
                error(
                    f"{CHECK_ID}.state-machine",
                    spec.rel_path,
                    axis.name,
                    f"exactly one initial state required (marked initial: true or unique zero-in-degree), found {len(roots)}",
                )
            )
    if require_terminal and not axis.terminal:
        result.findings.append(
            error(f"{CHECK_ID}.state-machine", spec.rel_path, axis.name, f"{axis.name} requires at least one terminal state")
        )


def _check_reciprocity(project_root: Path, specs: list[_SpecDoc], result: CheckResult) -> None:
    for spec in specs:
        for reference in spec.prose_refs:
            target = project_root / reference
            if not target.is_file():
                result.findings.append(
                    error(f"{CHECK_ID}.reciprocity", spec.rel_path, "prose_refs", f"prose reference {reference!r} does not exist")
                )
                continue
            payload, _ = split_frontmatter(target.read_text(encoding="utf-8"))
            if payload is None:
                continue
            try:
                frontmatter = parse_smy(payload)
            except SmyError as exc:
                message = f"prose reference {reference!r} has unparseable frontmatter: {exc.message}"
                result.findings.append(error(f"{CHECK_ID}.reciprocity", spec.rel_path, "prose_refs", message))
                continue
            formal_refs = frontmatter.get("formal_refs")
            if isinstance(formal_refs, list) and formal_refs and spec.object_id not in formal_refs:
                result.findings.append(
                    error(
                        f"{CHECK_ID}.reciprocity",
                        spec.rel_path,
                        "prose_refs",
                        f"prose reference {reference!r} carries formal_refs but does not list {spec.object_id!r}",
                    )
                )
