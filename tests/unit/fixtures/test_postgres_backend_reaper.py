"""Unit tests for the Postgres fixture container reaper safety predicate."""

from __future__ import annotations

import pytest
from tests.fixtures.postgres_backend import _is_reapable_test_container


@pytest.mark.parametrize(
    ("name", "label_value", "age_seconds", "expected"),
    [
        ("ak3-postgres-012345abcdef", None, 7200.1, True),
        ("custom-container-name", "1", 7200.1, True),
        ("ak3-postgres-012345abcdeg", None, 7200.1, False),
        ("agentkit-postgres-ci", None, 7200.1, False),
        ("agentkit-postgres-ci-55432", None, 7200.1, False),
        ("seu-sonar-db", None, 7200.1, False),
        ("arbitrary-container", None, 7200.1, False),
        ("ak3-postgres-012345abcdef", "0", 7200.1, True),
        ("ak3-postgres-012345abcdef", None, 7200.0, False),
        ("custom-container-name", "1", 7200.0, False),
    ],
    ids=[
        "legacy_exact_name_is_reapable_after_ttl",
        "label_owned_name_is_reapable_after_ttl",
        "legacy_name_requires_12_hex_chars",
        "agentkit_postgres_ci_is_not_reapable",
        "agentkit_postgres_ci_port_variant_is_not_reapable",
        "sonar_db_is_not_reapable",
        "arbitrary_unlabelled_name_is_not_reapable",
        "legacy_exact_name_does_not_need_label",
        "legacy_exact_name_at_ttl_boundary_is_not_reapable",
        "label_owned_name_at_ttl_boundary_is_not_reapable",
    ],
)
def test_is_reapable_test_container_requires_fixture_marker_and_age(
    name: str,
    label_value: str | None,
    age_seconds: float,
    expected: bool,
) -> None:
    assert (
        _is_reapable_test_container(
            name,
            label_value,
            age_seconds,
            ttl_seconds=7200.0,
        )
        is expected
    )
