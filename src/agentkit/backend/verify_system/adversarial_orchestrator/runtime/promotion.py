"""Deterministic test promotion / quarantine (FK-48 §48.1.5, AG3-079 AC4).

A deterministic Zone-2 pipeline script (NO LLM) that decides, per sandbox-created
test, one of three paths:

1. schema-valid AND dry-run-executable AND non-duplicate AND test PASS
   -> promoted into ``tests/`` (the regular suite).
2. schema-valid AND dry-run-executable AND non-duplicate AND test FAIL
   (a proven finding) -> promoted into ``tests/adversarial_quarantine/`` (so the
   failing test does NOT break the green build; the remediation worker makes it
   green, FK-48 §48.1.5).
3. schema-invalid OR dry-run-error OR duplicate -> stays ephemeral in the sandbox
   (no promotion).

Dedup criterion (FK-48 §48.1.5 / AC4): a sandbox test is a duplicate iff a test
with the identical MODULE-QUALIFIED test name already exists under ``tests/``.

This is real, deterministic logic tested with real files (the sandbox is the only
write target the sub-agent had; promotion copies FROM the sandbox INTO the repo).
"""

from __future__ import annotations

import ast
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
    PromotionSummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
        SandboxTest,
    )

#: Directory (under the project ``tests/`` root) failing adversarial tests are
#: quarantined into (FK-48 §48.1.5). The remediation worker makes them green.
QUARANTINE_DIRNAME: str = "adversarial_quarantine"

#: Outcome wire value meaning the sandbox test passed.
_OUTCOME_PASS: str = "PASS"


class PromotionPath(StrEnum):
    """The deterministic destination of a sandbox test (FK-48 §48.1.5)."""

    SUITE = "suite"
    QUARANTINE = "quarantine"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class PromotionDecision:
    """The decision + reason for one sandbox test (deterministic, FK-48 §48.1.5).

    Attributes:
        test: The sandbox test the decision is about.
        path: Where the test ended up (suite / quarantine / ephemeral).
        reason: Human-readable reason (the failing gatekeeper for ephemeral).
        destination: Absolute repo path the test was copied to, or ``None`` when
            it stayed ephemeral.
    """

    test: SandboxTest
    path: PromotionPath
    reason: str
    destination: Path | None = None


def promote_sandbox_tests(
    *,
    tests: Iterable[SandboxTest],
    sandbox_dir: Path,
    tests_root: Path,
) -> tuple[tuple[PromotionDecision, ...], PromotionSummary]:
    """Promote / quarantine sandbox tests deterministically (FK-48 §48.1.5).

    Args:
        tests: The sandbox-created tests to consider.
        sandbox_dir: The protected sandbox dir the tests live in
            (``_temp/adversarial/{story_id}/{epoch}/``). Read-only source.
        tests_root: The project ``tests/`` root. Promoted tests are copied here
            (regular suite) or under ``tests/adversarial_quarantine/``.

    Returns:
        A tuple of per-test :class:`PromotionDecision` objects and the aggregate
        :class:`PromotionSummary` (suite / quarantine / ephemeral counts).
    """
    existing = _existing_qualified_names(tests_root)
    decisions: list[PromotionDecision] = []
    to_suite = 0
    to_quarantine = 0
    not_promoted = 0
    not_promoted_reasons: list[str] = []
    # Track names promoted in THIS run so two sandbox tests with the same
    # qualified name do not both land in the suite (intra-batch dedup).
    promoted_names: set[str] = set()

    for test in tests:
        decision = _decide(
            test,
            sandbox_dir=sandbox_dir,
            tests_root=tests_root,
            existing=existing | promoted_names,
        )
        decisions.append(decision)
        if decision.path is PromotionPath.SUITE:
            to_suite += 1
            promoted_names.add(test.qualified_name)
        elif decision.path is PromotionPath.QUARANTINE:
            to_quarantine += 1
            promoted_names.add(test.qualified_name)
        else:
            not_promoted += 1
            not_promoted_reasons.append(decision.reason)

    summary = PromotionSummary(
        promoted_to_suite=to_suite,
        promoted_to_quarantine=to_quarantine,
        not_promoted=not_promoted,
        not_promoted_reasons=tuple(not_promoted_reasons),
    )
    return tuple(decisions), summary


def _decide(
    test: SandboxTest,
    *,
    sandbox_dir: Path,
    tests_root: Path,
    existing: set[str],
) -> PromotionDecision:
    """Decide one sandbox test deterministically (the three FK-48 §48.1.5 paths)."""
    source = sandbox_dir / test.sandbox_relpath
    # Gatekeeper 1: schema-valid (the file exists, is a real Python test file).
    if not test.schema_valid or not source.is_file():
        return PromotionDecision(
            test=test,
            path=PromotionPath.EPHEMERAL,
            reason=f"schema-invalid ({test.sandbox_relpath})",
        )
    # Gatekeeper 2: dry-run-executable (no syntax error -> compiles).
    syntax_error = _dry_run_error(source)
    if syntax_error is not None:
        return PromotionDecision(
            test=test,
            path=PromotionPath.EPHEMERAL,
            reason=f"dry-run-error ({syntax_error})",
        )
    # Gatekeeper 3: non-duplicate (module-qualified name not already in tests/).
    if test.qualified_name in existing:
        return PromotionDecision(
            test=test,
            path=PromotionPath.EPHEMERAL,
            reason=f"duplicate ({test.qualified_name})",
        )
    # All three gatekeepers passed -> promote; PASS to the suite, FAIL to
    # quarantine (a failing promoted test is a proven finding, FK-48 §48.1.5).
    if test.outcome.upper() == _OUTCOME_PASS:
        destination = _copy_into(source, tests_root, test.sandbox_relpath)
        return PromotionDecision(
            test=test,
            path=PromotionPath.SUITE,
            reason="promoted to tests/ (PASS)",
            destination=destination,
        )
    destination = _copy_into(
        source, tests_root / QUARANTINE_DIRNAME, test.sandbox_relpath
    )
    return PromotionDecision(
        test=test,
        path=PromotionPath.QUARANTINE,
        reason="quarantined (proven finding, test FAIL)",
        destination=destination,
    )


def _copy_into(source: Path, dest_root: Path, relpath: str) -> Path:
    """Copy a sandbox test file into ``dest_root`` (creating parents)."""
    destination = dest_root / Path(relpath).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def _dry_run_error(source: Path) -> str | None:
    """Return a syntax-error message if the test does not compile, else ``None``."""
    try:
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg}"
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _existing_qualified_names(tests_root: Path) -> set[str]:
    """Collect the module-qualified test names already under ``tests/`` (dedup key).

    FK-48 §48.1.5 / AC4: the dedup identity is the FULL MODULE-QUALIFIED test
    name — the test module's dotted path RELATIVE to ``tests_root`` plus the
    test function (``pkg.sub.module::test_fn``), NOT just the file stem. This is
    what makes two same-stem/same-function tests in DIFFERENT packages (e.g.
    ``unit/foo/test_x.py::test_a`` and ``integration/foo/test_x.py::test_a``)
    distinct identities — a stem-only key would wrongly collapse them.

    Computed for every ``test_*`` / ``*_test`` function in every ``test_*.py``
    under ``tests_root`` (excluding the quarantine dir, which holds known-failing
    duplicates). A sandbox test whose ``qualified_name`` matches one of these is a
    duplicate.
    """
    names: set[str] = set()
    if not tests_root.is_dir():
        return names
    quarantine = tests_root / QUARANTINE_DIRNAME
    for path in tests_root.rglob("test_*.py"):
        if quarantine in path.parents:
            continue
        names.update(_qualified_names_in_file(path, tests_root))
    return names


def _module_qualifier(path: Path, tests_root: Path) -> str:
    """Return the dotted module path of ``path`` RELATIVE to ``tests_root``.

    E.g. ``tests_root/unit/foo/test_x.py`` -> ``unit.foo.test_x``. The rooted
    relative path (not the bare stem) is what makes the dedup identity
    module-qualified (FK-48 §48.1.5 / AC4).
    """
    relative = path.relative_to(tests_root).with_suffix("")
    return ".".join(relative.parts)


def _qualified_names_in_file(path: Path, tests_root: Path) -> set[str]:
    """Return ``{module_qualifier}::{fn}`` for every test function in ``path``.

    The ``module_qualifier`` is the dotted module path relative to ``tests_root``
    so the identity is module-qualified (FK-48 §48.1.5 / AC4), not stem-only.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return set()
    qualifier = _module_qualifier(path, tests_root)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name.startswith("test_") or node.name.endswith("_test")
        ):
            names.add(f"{qualifier}::{node.name}")
    return names


__all__ = [
    "QUARANTINE_DIRNAME",
    "PromotionDecision",
    "PromotionPath",
    "promote_sandbox_tests",
]
