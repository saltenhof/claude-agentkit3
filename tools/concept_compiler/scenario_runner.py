"""Scenario validation for formal concept specifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from concept_compiler.loader import FormalSpecDocument
from agentkit.exceptions import AgentKitError


class FormalScenarioError(AgentKitError):
    """Raised when formal scenarios are structurally inconsistent."""


@dataclass(frozen=True)
class ScenarioValidation:
    """Validated scenario summary."""

    context: str
    scenario_id: str


@dataclass(frozen=True)
class _Transition:
    from_state: str
    to_state: str


@dataclass(frozen=True)
class _MachineAxis:
    states: frozenset[str]
    terminal_states: frozenset[str]
    transitions: tuple[_Transition, ...]


@dataclass(frozen=True)
class _Command:
    command_id: str
    allowed_statuses: frozenset[str]


def validate_scenarios(documents: tuple[FormalSpecDocument, ...]) -> tuple[ScenarioValidation, ...]:
    """Validate all scenario sets against commands and state machines."""
    documents_by_context = _group_by_context(documents)
    validations: list[ScenarioValidation] = []

    for context, specs in documents_by_context.items():
        scenario_doc = specs.get("scenario-set")
        if scenario_doc is None:
            continue

        machine_doc = specs.get("state-machine")
        if machine_doc is None:
            raise FormalScenarioError(
                f"Scenario context '{context}' is missing a state-machine spec",
                detail={"context": context},
            )

        command_doc = specs.get("command-set")
        if command_doc is None:
            raise FormalScenarioError(
                f"Scenario context '{context}' is missing a command-set spec",
                detail={"context": context},
            )

        validations.extend(
            _validate_scenario_document(context, machine_doc.spec, command_doc.spec, scenario_doc.spec)
        )

    return tuple(validations)


def _group_by_context(documents: tuple[FormalSpecDocument, ...]) -> dict[str, dict[str, FormalSpecDocument]]:
    grouped: dict[str, dict[str, FormalSpecDocument]] = {}
    for document in documents:
        specs = grouped.setdefault(document.context, {})
        if document.spec_kind in specs:
            raise FormalScenarioError(
                f"Context '{document.context}' declares multiple '{document.spec_kind}' specs",
                detail={"context": document.context, "spec_kind": document.spec_kind},
            )
        specs[document.spec_kind] = document
    return grouped


def _validate_scenario_document(
    context: str,
    machine_spec: dict[str, Any],
    command_spec: dict[str, Any],
    scenario_spec: dict[str, Any],
) -> tuple[ScenarioValidation, ...]:
    status_axis, phase_axis = _load_machine_axes(machine_spec)
    commands = _load_commands(command_spec)
    scenarios = _require_list(scenario_spec, "scenarios", context, "scenario-set")

    validations: list[ScenarioValidation] = []
    for scenario in scenarios:
        scenario_id = _require_string(scenario, "id", context, "scenario")
        _validate_single_scenario(context, scenario_id, scenario, commands, status_axis, phase_axis)
        validations.append(ScenarioValidation(context=context, scenario_id=scenario_id))
    return tuple(validations)


def _validate_single_scenario(
    context: str,
    scenario_id: str,
    scenario: dict[str, Any],
    commands: dict[str, _Command],
    status_axis: _MachineAxis,
    phase_axis: _MachineAxis | None,
) -> None:
    start = _require_dict(scenario, "start", context, scenario_id)
    expected_end = _require_dict(scenario, "expected_end", context, scenario_id)
    trace = _require_list(scenario, "trace", context, scenario_id)

    start_status = _optional_string(start, "status")
    end_status = _optional_string(expected_end, "status")
    if start_status is None or end_status is None:
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' must define start.status and expected_end.status",
            detail={"context": context, "scenario_id": scenario_id},
        )

    _ensure_state_known(status_axis, start_status, context, scenario_id, field="start.status")
    _ensure_state_known(status_axis, end_status, context, scenario_id, field="expected_end.status")

    if end_status not in status_axis.terminal_states:
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' must end in a terminal status",
            detail={"context": context, "scenario_id": scenario_id, "status": end_status},
        )

    _validate_status_trace(context, scenario_id, trace, start_status, end_status, commands, status_axis)
    _validate_phase_trace(context, scenario_id, trace, start, expected_end, phase_axis)


def _validate_status_trace(
    context: str,
    scenario_id: str,
    trace: list[Any],
    start_status: str,
    end_status: str,
    commands: dict[str, _Command],
    status_axis: _MachineAxis,
) -> None:
    steps = [_normalize_step(step, context, scenario_id) for step in trace]

    def solve(step_index: int, current_status: str) -> bool:
        if step_index == len(steps):
            return current_status == end_status

        step = steps[step_index]
        command = commands.get(step["command"])
        if command is None:
            raise FormalScenarioError(
                f"Scenario '{scenario_id}' in context '{context}' references unknown command '{step['command']}'",
                detail={"context": context, "scenario_id": scenario_id, "command": step["command"]},
            )

        if command.allowed_statuses and current_status not in command.allowed_statuses:
            return False

        candidates = _reachable_states(
            status_axis,
            current_status,
            allow_self=_command_may_keep_state(step["command"]),
        )
        for candidate in candidates:
            if solve(step_index + 1, candidate):
                return True
        return False

    if not solve(0, start_status):
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' is not executable against the status graph",
            detail={
                "context": context,
                "scenario_id": scenario_id,
                "start_status": start_status,
                "end_status": end_status,
            },
        )


def _validate_phase_trace(
    context: str,
    scenario_id: str,
    trace: list[Any],
    start: dict[str, Any],
    expected_end: dict[str, Any],
    phase_axis: _MachineAxis | None,
) -> None:
    if phase_axis is None:
        return

    start_phase = _optional_string(start, "phase")
    if start_phase is None:
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' must define start.phase for phase-aware machines",
            detail={"context": context, "scenario_id": scenario_id},
        )
    _ensure_state_known(phase_axis, start_phase, context, scenario_id, field="start.phase")

    expected_phase = _optional_string(expected_end, "phase")
    if expected_phase is not None:
        _ensure_state_known(phase_axis, expected_phase, context, scenario_id, field="expected_end.phase")

    phase_checkpoints = [start_phase]
    for step in trace:
        normalized = _normalize_step(step, context, scenario_id)
        target_phase = normalized.get("target_phase")
        if target_phase is not None:
            _ensure_state_known(phase_axis, target_phase, context, scenario_id, field="trace.target_phase")
            phase_checkpoints.append(target_phase)
    if expected_phase is not None:
        phase_checkpoints.append(expected_phase)

    for current_phase, next_phase in zip(phase_checkpoints, phase_checkpoints[1:], strict=False):
        if current_phase == next_phase:
            continue
        reachable = _reachable_states(phase_axis, current_phase, allow_self=False)
        if next_phase not in reachable:
            raise FormalScenarioError(
                f"Scenario '{scenario_id}' in context '{context}' is not executable against the phase graph",
                detail={
                    "context": context,
                    "scenario_id": scenario_id,
                    "from_phase": current_phase,
                    "to_phase": next_phase,
                },
            )


def _load_machine_axes(machine_spec: dict[str, Any]) -> tuple[_MachineAxis, _MachineAxis | None]:
    if "states" in machine_spec:
        return _parse_axis(machine_spec, axis_name="status"), None

    if "status_axis" not in machine_spec:
        raise FormalScenarioError("State machine must define either 'states' or 'status_axis'")

    status_axis = _parse_axis(_require_dict(machine_spec, "status_axis", "machine", "status_axis"), axis_name="status")
    phase_axis = _parse_axis(_require_dict(machine_spec, "phase_axis", "machine", "phase_axis"), axis_name="phase")
    return status_axis, phase_axis


def _parse_axis(spec: dict[str, Any], axis_name: str) -> _MachineAxis:
    states_raw = _require_list(spec, "states", axis_name, "states")
    transitions_raw = _require_list(spec, "transitions", axis_name, "transitions")

    states: set[str] = set()
    terminals: set[str] = set()
    for state in states_raw:
        state_id = _require_string(state, "id", axis_name, "state")
        states.add(state_id)
        if state.get("terminal") is True:
            terminals.add(state_id)

    transitions: list[_Transition] = []
    for transition in transitions_raw:
        from_state = _require_string(transition, "from", axis_name, "transition")
        to_state = _require_string(transition, "to", axis_name, "transition")
        transitions.append(_Transition(from_state=from_state, to_state=to_state))

    return _MachineAxis(states=frozenset(states), terminal_states=frozenset(terminals), transitions=tuple(transitions))


def _load_commands(command_spec: dict[str, Any]) -> dict[str, _Command]:
    command_items = _require_list(command_spec, "commands", "commands", "commands")
    commands: dict[str, _Command] = {}
    for command in command_items:
        command_id = _require_string(command, "id", "commands", "command")
        allowed_statuses = frozenset(_require_string_list(command.get("allowed_statuses", []), command_id))
        commands[command_id] = _Command(command_id=command_id, allowed_statuses=allowed_statuses)
    return commands


def _reachable_states(axis: _MachineAxis, start: str, *, allow_self: bool) -> tuple[str, ...]:
    reachable: set[str] = {start} if allow_self else set()
    frontier = [start]
    visited = {start}

    while frontier:
        current = frontier.pop()
        for transition in axis.transitions:
            if transition.from_state != current:
                continue
            if transition.to_state not in reachable:
                reachable.add(transition.to_state)
            if transition.to_state not in visited:
                visited.add(transition.to_state)
                frontier.append(transition.to_state)

    return tuple(sorted(reachable))


def _command_may_keep_state(command_id: str) -> bool:
    markers = (
        ".query-",
        ".run-phase",
        ".resume",
        ".resume-run",
        ".ingest-",
    )
    return any(marker in command_id for marker in markers) or command_id.endswith(".query-audit-log")


def _normalize_step(step: Any, context: str, scenario_id: str) -> dict[str, str]:
    if not isinstance(step, dict):
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' contains a non-mapping trace step",
            detail={"context": context, "scenario_id": scenario_id},
        )
    command_id = _require_string(step, "command", context, scenario_id)
    normalized: dict[str, str] = {"command": command_id}
    target_phase = _optional_string(step, "target_phase")
    if target_phase is not None:
        normalized["target_phase"] = target_phase
    return normalized


def _ensure_state_known(axis: _MachineAxis, state_id: str, context: str, scenario_id: str, *, field: str) -> None:
    if state_id not in axis.states:
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' references unknown state '{state_id}' in {field}",
            detail={"context": context, "scenario_id": scenario_id, "state_id": state_id, "field": field},
        )


def _require_dict(mapping: dict[str, Any], key: str, context: str, scenario_id: str) -> dict[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise FormalScenarioError(
            f"Scenario '{scenario_id}' in context '{context}' must define '{key}' as a mapping",
            detail={"context": context, "scenario_id": scenario_id, "field": key},
        )
    return value


def _require_list(mapping: dict[str, Any], key: str, context: str, scenario_id: str) -> list[Any]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise FormalScenarioError(
            f"'{key}' in context '{context}' must be a list",
            detail={"context": context, "scenario_id": scenario_id, "field": key},
        )
    return value


def _require_string(mapping: dict[str, Any], key: str, context: str, scenario_id: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise FormalScenarioError(
            f"Field '{key}' in scenario '{scenario_id}' / context '{context}' must be a non-empty string",
            detail={"context": context, "scenario_id": scenario_id, "field": key},
        )
    return value


def _optional_string(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        return None
    return value


def _require_string_list(values: Any, context: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise FormalScenarioError(
            f"Allowed statuses for command '{context}' must be a list",
            detail={"command": context},
        )
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or value == "":
            raise FormalScenarioError(
                f"Allowed statuses for command '{context}' must contain only non-empty strings",
                detail={"command": context},
            )
        normalized.append(value)
    return tuple(normalized)
