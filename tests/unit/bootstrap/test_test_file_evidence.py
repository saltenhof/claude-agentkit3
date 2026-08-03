"""A change set counts as tested only if it carries a file pytest collects.

This backs a BLOCKING structural check, so every widening is a fail-open: it
lets a change set with no executable test through as evidence that a test
exists. Both earlier definitions did exactly that.
"""

from __future__ import annotations

import pytest

from agentkit.backend.bootstrap.composition_implementation_evidence import _is_test_file


@pytest.mark.parametrize(
    "path",
    [
        # Substring matches that carry no test at all.
        "src/latest_feature.py",
        "src/protests/helper.py",
        "src/contest.py",
        # A `tests` path segment on something pytest never collects.
        "tests/README.md",
        "tests/fixtures/input.json",
        "tests/conftest.py",
        # Test-shaped names on files that are not Python.
        "src/test_data.json",
        "src/foo_test.yaml",
        "",
    ],
)
def test_files_that_are_not_collectible_tests_are_not_evidence(path: str) -> None:
    assert _is_test_file(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "tests/unit/test_engine.py",
        "tests/unit/engine_test.py",
        "src/agentkit/backend/test_inline.py",
        "test_root_level.py",
        r"tests\unit\test_windows_path.py",
    ],
)
def test_pytest_collectible_files_are_evidence(path: str) -> None:
    assert _is_test_file(path) is True
