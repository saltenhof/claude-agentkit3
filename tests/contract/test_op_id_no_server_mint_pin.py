"""Regression pin: no server-side ``op_id`` mint in the backend (AG3-140 AC1).

FK-91 §91.1a Rule 5: ``op_id`` is the CLIENT-supplied idempotency key. A
server-side mint (a wire-model ``op_id`` field with a ``default_factory``, or an
explicit server-side assignment on a mutating wire model) makes a client's retry
blind -- it can no longer reconcile an ambiguous mutation via
``GET /v1/project-edge/operations/{op_id}`` (Rule 17). AG3-140 removed every such
mint and made ``op_id`` a required ``Field(min_length=1)``.

This pin greps the entire ``src/agentkit/backend`` tree and fails closed if a
``default_factory`` ever reappears on an ``op_id`` field, so the contract cannot
silently regress. The legitimate CLIENT-side mints that remain (the guard-counter
hook and the failure-corpus story-creation adapter mint their own ``op_id`` AS A
CLIENT before the service call, never as a wire-model default) are matched
explicitly and are NOT server mints.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``op_id`` and ``default_factory`` on the same logical Field declaration. The
# removed anti-pattern was ``op_id: str = Field(default_factory=lambda: ...)`` /
# ``op_id: str = Field(default_factory=_mint_op_id)`` on a mutating wire model.
_OP_ID_DEFAULT_FACTORY = re.compile(
    r"op_id\s*:\s*[^\n]*default_factory", re.MULTILINE
)
# Defensive reverse: a ``default_factory=...`` whose target field is ``op_id``.
_DEFAULT_FACTORY_OP_ID = re.compile(
    r"default_factory[^\n]*\bop_id\b", re.MULTILINE
)


def _backend_root() -> Path:
    # tests/contract/<this file> -> repo root -> src/agentkit/backend
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "agentkit"
        / "backend"
    )


def test_no_default_factory_op_id_mint_in_backend() -> None:
    """AG3-140 AC1: zero ``default_factory`` op_id mints under src/agentkit/backend."""
    root = _backend_root()
    assert root.is_dir(), f"backend root not found: {root}"

    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _OP_ID_DEFAULT_FACTORY.search(text) or _DEFAULT_FACTORY_OP_ID.search(text):
            offenders.append(str(path.relative_to(root)))

    assert not offenders, (
        "server-side op_id mint (default_factory) reintroduced -- FK-91 §91.1a "
        f"Rule 5 requires a client-supplied op_id. Offending files: {offenders}"
    )


# ---------------------------------------------------------------------------
# ARCH-55 regression pin: no German in the AG3-140-touched source/tests.
# ARCH-55 is as binding as the Sonar rules -- source comments/identifiers/
# wire-keys must be English. This pin greps the AG3-140-touched .py files for a
# German blocklist so German cannot silently re-enter the AG3-140 diff.
# ---------------------------------------------------------------------------

#: The .py files AG3-140 created or modified (git diff d8a7da41..HEAD). Deleted
#: files (e.g. the retired ``idempotency.py``) are skipped when absent.
_AG3_140_TOUCHED_FILES: tuple[str, ...] = (
    "src/agentkit/backend/auth/http/routes.py",
    "src/agentkit/backend/bootstrap/composition_root.py",
    "src/agentkit/backend/cli/main.py",
    "src/agentkit/backend/control_plane/guard_counter.py",
    "src/agentkit/backend/control_plane/models.py",
    "src/agentkit/backend/control_plane/records.py",
    "src/agentkit/backend/control_plane/runtime.py",
    "src/agentkit/backend/control_plane_http/app.py",
    "src/agentkit/backend/execution_planning/http/routes.py",
    "src/agentkit/backend/governance/runner.py",
    "src/agentkit/backend/project_management/http/routes.py",
    "src/agentkit/backend/state_backend/postgres_store.py",
    "src/agentkit/backend/state_backend/sqlite_store/__init__.py",
    "src/agentkit/backend/state_backend/sqlite_store/_backend_checks.py",
    "src/agentkit/backend/state_backend/sqlite_store/_common.py",
    "src/agentkit/backend/state_backend/sqlite_store/_connection.py",
    "src/agentkit/backend/state_backend/sqlite_store/_ownership_rows.py",
    "src/agentkit/backend/state_backend/sqlite_store/_purge_rows.py",
    "src/agentkit/backend/state_backend/sqlite_store/_qa_artifact_rows.py",
    "src/agentkit/backend/state_backend/sqlite_store/_runtime_rows.py",
    "src/agentkit/backend/state_backend/sqlite_store/_schema.py",
    "src/agentkit/backend/state_backend/sqlite_store/_schema_runtime.py",
    "src/agentkit/backend/state_backend/sqlite_store/_story_identity.py",
    "src/agentkit/backend/state_backend/sqlite_store/_story_project_rows.py",
    "src/agentkit/backend/state_backend/store/facade.py",
    "src/agentkit/backend/state_backend/store/guard_counter_repository.py",
    "src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py",
    "src/agentkit/backend/state_backend/store/mappers.py",
    "src/agentkit/backend/state_backend/store/story_repository.py",
    "src/agentkit/backend/story_context_manager/errors.py",
    "src/agentkit/backend/story_context_manager/http/routes.py",
    "src/agentkit/backend/story_context_manager/service.py",
    "src/agentkit/backend/task_management/http/routes.py",
    "src/agentkit/bundles/target_project/tools/agentkit/projectedge.py",
    "src/agentkit/harness_client/projectedge/runtime.py",
    "tests/contract/state_backend/test_control_plane_operation_store_postgres.py",
    "tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py",
    "tests/contract/test_op_id_no_server_mint_pin.py",
    "tests/integration/control_plane_http/test_task_management_routes.py",
    "tests/integration/governance_hooks/test_hook_rest_mediation.py",
    "tests/integration/pipeline_engine/test_operator_cli_phase_rest.py",
    "tests/integration/story_creation/test_create_story_tool_e2e.py",
    "tests/unit/auth/http/test_auth_routes.py",
    "tests/unit/control_plane/test_hook_mediation_services.py",
    "tests/unit/control_plane/test_http.py",
    "tests/unit/control_plane/test_runtime.py",
    "tests/unit/control_plane_http/test_app.py",
    "tests/unit/control_plane_http/test_version_handshake.py",
    "tests/unit/execution_planning/http/test_execution_planning_routes.py",
    "tests/unit/project_management/http/test_routes.py",
    "tests/unit/state_backend/test_inflight_idempotency_guard.py",
    "tests/unit/story_context_manager/test_http_routes.py",
    "tests/unit/story_context_manager/test_service.py",
    "tests/unit/task_management/http/test_routes.py",
)

#: German words that must not appear in AG3-140 source comments/identifiers
#: (ARCH-55). Discrete words use word boundaries; participles match as substrings.
_GERMAN_BLOCKLIST = re.compile(
    r"\b(?:Regel|Befund|Fehlschlag|Abweichung|Minten|Sperre|Vertrag|Nachweis"
    r"|Anspruch|Wahrheit|Pflicht)\b|gemintet|beigestellt"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_no_german_in_ag3140_touched_files() -> None:
    """ARCH-55: zero German blocklist words in the AG3-140-touched .py files."""
    root = _repo_root()
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for rel in _AG3_140_TOUCHED_FILES:
        path = root / rel
        if not path.exists():  # a deleted file (e.g. the retired idempotency.py)
            continue
        if path.resolve() == this_file:
            # This pin file legitimately DEFINES the German blocklist -- skip it.
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _GERMAN_BLOCKLIST.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:80]}")

    assert not offenders, (
        "German re-entered an AG3-140-touched file (ARCH-55, English-only source). "
        "Offenders:\n" + "\n".join(offenders)
    )
