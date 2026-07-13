"""Typed reviewer request DSL for preflight evidence enrichment."""

from __future__ import annotations

import shlex
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.core_types.verify_evidence import VerifyTestCommand


class RequestType(StrEnum):
    """Structured reviewer request types supported by the preflight turn."""

    NEED_FILE = "NEED_FILE"
    NEED_SCHEMA = "NEED_SCHEMA"
    NEED_CALLSITE = "NEED_CALLSITE"
    NEED_RUNTIME_BINDING = "NEED_RUNTIME_BINDING"
    NEED_TEST_EVIDENCE = "NEED_TEST_EVIDENCE"
    NEED_CONCEPT_SOURCE = "NEED_CONCEPT_SOURCE"
    NEED_DIFF_EXPANSION = "NEED_DIFF_EXPANSION"


class ReviewerRequest(BaseModel):
    """One structured request emitted by a reviewer during preflight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: RequestType
    target: str = Field(min_length=1, description="Path, symbol, pattern or command")
    region: str | None = Field(default=None, description="Region for NEED_DIFF_EXPANSION")
    reason: str = Field(min_length=1, description="Why this information is needed")


class RequestResultStatus(StrEnum):
    """Closed backend resolution statuses for reviewer requests."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class RequestResult(BaseModel):
    """Deterministic resolution result for one reviewer request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ReviewerRequest
    status: RequestResultStatus
    content: str | None = None
    file_path: str | None = None
    candidate_paths: tuple[str, ...] = ()
    finding_code: str | None = None
    duration_ms: int = 0


_SIMPLE_FLAGS = frozenset({"-q", "-v", "-vv", "-x", "-s", "--quiet"})
_VALUE_FLAGS = frozenset({"-k", "-m", "--maxfail", "--tb"})


def parse_test_command(target: str) -> VerifyTestCommand:
    """Parse a reviewer test target into the whitelisted arg-wise contract.

    Only ``pytest`` and ``python[-version] -m pytest`` forms are accepted. The
    edge always executes its own interpreter as ``python -m pytest``; shell
    operators, path traversal, absolute targets, plugin/config injection, and
    unlisted flags are rejected before commissioning and revalidated on edge.

    Args:
        target: LLM-supplied test command text.

    Returns:
        The normalized test command.

    Raises:
        ValueError: If the command is not in the closed whitelist.
    """
    if any(token in target for token in ("\n", "\r", "&&", "||", ";", "|", ">", "<")):
        raise ValueError("test command contains a forbidden shell operator")
    try:
        parts = shlex.split(target, posix=True)
    except ValueError as exc:
        raise ValueError("test command is not valid argument text") from exc
    if not parts:
        raise ValueError("test command must not be empty")
    if parts[0] == "pytest":
        arguments = parts[1:]
    elif (
        len(parts) >= 3
        and parts[0] in {"python", "python3"}
        and parts[1:3] == ["-m", "pytest"]
    ):
        arguments = parts[3:]
    else:
        raise ValueError("test command runner is not whitelisted")
    _validate_pytest_arguments(arguments)
    return VerifyTestCommand(arguments=tuple(arguments))


def _validate_pytest_arguments(arguments: list[str]) -> None:
    expect_value = False
    for argument in arguments:
        if expect_value:
            if not argument or argument.startswith("-"):
                raise ValueError("pytest option requires a bounded value")
            expect_value = False
            continue
        if argument in _SIMPLE_FLAGS:
            continue
        if argument in _VALUE_FLAGS:
            expect_value = True
            continue
        if any(argument.startswith(f"{flag}=") for flag in _VALUE_FLAGS):
            continue
        if argument.startswith("-"):
            raise ValueError(f"pytest option is not whitelisted: {argument}")
        path_part = argument.split("::", maxsplit=1)[0]
        path = PurePosixPath(path_part.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("pytest target must stay inside the story worktree")
    if expect_value:
        raise ValueError("pytest option value is missing")


__all__ = [
    "RequestResult",
    "RequestResultStatus",
    "RequestType",
    "ReviewerRequest",
    "parse_test_command",
]
